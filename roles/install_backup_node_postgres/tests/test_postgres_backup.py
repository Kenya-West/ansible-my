"""Local tests: no PostgreSQL, Docker daemon, root or systemd required."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

RUNNER = Path(__file__).resolve().parents[1] / "files" / "postgres_backup.py"
spec = importlib.util.spec_from_file_location("postgres_backup", RUNNER)
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


def target():
    return {
        "id": "example-db", "project_path": "/srv/example",
        "execution": {"driver": "compose_exec", "service": "db", "project_name": "example"},
        "connection": {"source": "container_environment"},
        "dump": {"scope": "cluster", "format": "plain"},
        "output": {"subdirectory": "example/0", "filename": "dump.sql"},
    }


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.manifests = self.root / "manifests"
        self.manifests.mkdir()
        self.output = self.root / "output"
        self.output.mkdir()

    def publish(self, owner, targets):
        (self.manifests / (owner + ".json")).write_text(json.dumps({
            "schema_version": 1, "owner": owner, "targets": targets}))

    def test_persistent_registry_and_zero_instances(self):
        self.publish("example", [target()])
        self.publish("empty", [])
        self.assertEqual(len(backup.load_targets(self.manifests, self.output)), 1)
        # A standalone process sees declarations from previous invocations.
        result = subprocess.run([str(RUNNER), "--manifest-dir", str(self.manifests),
                                 "--output-root", str(self.output), "--validate"],
                                capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout)[0]["id"], "example-db")
        self.publish("example", [])
        self.assertEqual(backup.load_targets(self.manifests, self.output), [])

    def test_duplicate_ids_and_outputs(self):
        first, second = target(), target()
        self.publish("first", [first])
        self.publish("second", [second])
        with self.assertRaisesRegex(ValueError, "duplicate target"):
            backup.load_targets(self.manifests, self.output)
        second["id"] = "different"
        self.publish("second", [second])
        with self.assertRaisesRegex(ValueError, "duplicate output"):
            backup.load_targets(self.manifests, self.output)

    def test_invalid_paths_and_dump_scope(self):
        for key, value in [("subdirectory", "../escape"), ("subdirectory", "/etc"),
                           ("filename", "../dump.sql"), ("filename", "")]:
            item = target()
            item["output"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                backup.validate_target(item, self.output)
        item = target()
        item["dump"]["format"] = "custom"
        with self.assertRaises(ValueError):
            backup.validate_target(item, self.output)
        outside = self.root / "outside"
        outside.mkdir()
        (self.output / "example").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "escapes root"):
            backup.validate_target(target(), self.output)

    def test_rootless_compose_argv_and_database_format(self):
        command, env, cwd = backup.dump_command(target())
        self.assertIn("-T", command)
        self.assertNotIn("-t", command)
        self.assertIn("pg_dumpall", command)
        self.assertEqual(env.get("DOCKER_HOST"), os.environ.get("DOCKER_HOST"))
        self.assertEqual(cwd, "/srv/example")
        self.assertIn("POSTGRES_USER", command[command.index("-c") + 1])
        item = target()
        item["dump"] = {"scope": "database", "format": "custom"}
        command, _, _ = backup.dump_command(item)
        self.assertIn("pg_dump", command)
        self.assertIn("--format=c", command)

    def test_compose_does_not_guess_socket_and_preserves_cli_selection(self):
        with patch.dict(os.environ, {}, clear=True):
            _, env, _ = backup.compose_command(target())
            self.assertNotIn('DOCKER_HOST', env)
            self.assertNotIn('DOCKER_CONTEXT', env)
        with patch.dict(os.environ, {'DOCKER_HOST': 'unix:///custom.sock', 'DOCKER_CONFIG': '/home/test/.docker'}, clear=True):
            _, env, _ = backup.compose_command(target())
            self.assertEqual(env['DOCKER_HOST'], 'unix:///custom.sock')
            self.assertEqual(env['DOCKER_CONFIG'], '/home/test/.docker')
        with patch.dict(os.environ, {'DOCKER_CONTEXT': 'my-rootless'}, clear=True):
            _, env, _ = backup.compose_command(target())
            self.assertEqual(env['DOCKER_CONTEXT'], 'my-rootless')
            self.assertNotIn('DOCKER_HOST', env)

    def test_explicit_target_host_or_context_overrides_conflicting_environment(self):
        item = target()
        item['execution']['docker_host'] = 'unix:///chosen.sock'
        with patch.dict(os.environ, {'DOCKER_CONTEXT': 'wrong-context'}, clear=True):
            _, env, _ = backup.compose_command(item)
            self.assertEqual(env['DOCKER_HOST'], 'unix:///chosen.sock')
            self.assertNotIn('DOCKER_CONTEXT', env)
        item['execution'].pop('docker_host')
        item['execution']['docker_context'] = 'chosen-context'
        with patch.dict(os.environ, {'DOCKER_HOST': 'unix:///wrong.sock'}, clear=True):
            _, env, _ = backup.compose_command(item)
            self.assertEqual(env['DOCKER_CONTEXT'], 'chosen-context')
            self.assertNotIn('DOCKER_HOST', env)
        item['execution']['docker_host'] = 'unix:///conflict.sock'
        with self.assertRaisesRegex(ValueError, 'not both'):
            backup.validate_target(item, self.output)

    def test_atomic_success_and_failure_preserve_previous_dump(self):
        directory = self.output / "example/0"
        directory.mkdir(parents=True)
        destination = directory / "dump.sql"
        destination.write_bytes(b"previous successful dump")
        for failure in (True, False):
            def fake_run(command, **kwargs):
                if "ps" in command:
                    return subprocess.CompletedProcess(command, 0, stdout="container-id\n")
                kwargs["stdout"].write(b"new dump")
                self.assertEqual(destination.read_bytes(), b"previous successful dump")
                if failure:
                    raise subprocess.CalledProcessError(1, command)
            with patch.object(backup.subprocess, "run", side_effect=fake_run):
                if failure:
                    with self.assertRaises(subprocess.CalledProcessError):
                        backup.run_backup(target(), self.output)
                    self.assertEqual(destination.read_bytes(), b"previous successful dump")
                else:
                    backup.run_backup(target(), self.output)
                    self.assertEqual(destination.read_bytes(), b"new dump")
                    self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
            self.assertEqual(list(directory.glob("*.tmp")), [])

    def test_empty_dump_is_failure(self):
        def fake_run(command, **kwargs):
            return subprocess.CompletedProcess(command, 0, stdout="container-id\n" if "ps" in command else None)
        with patch.object(backup.subprocess, "run", side_effect=fake_run):
            with self.assertRaisesRegex(ValueError, "empty"):
                backup.run_backup(target(), self.output)
        self.assertFalse((self.output / "example/0/dump.sql").exists())

    def test_direct_uri_does_not_leak_into_argv(self):
        credentials = self.root / "connection"
        credentials.write_text("postgresql://backup:p%40ss@localhost:5433/app?sslmode=require")
        credentials.chmod(0o600)
        item = target()
        item["execution"] = {"driver": "direct"}
        item["connection"] = {"url_file": str(credentials)}
        backup.validate_target(item, self.output)
        command, env, _ = backup.dump_command(item)
        self.assertNotIn("p@ss", " ".join(command))
        self.assertEqual(env["PGPASSWORD"], "p@ss")
        self.assertEqual(env["PGSSLMODE"], "require")
        self.assertEqual(env["PGPORT"], "5433")
        credentials.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "credential file"):
            backup.dump_command(item)
        credentials.chmod(0o600)
        credentials.write_text("postgresql://backup:secret@localhost/app?schema=public")
        with self.assertRaisesRegex(ValueError, "unsupported libpq"):
            backup.dump_command(item)

    def test_container_credentials_and_arguments_are_not_shell_interpolated(self):
        item = target()
        item["connection"]["user"] = "name; touch /tmp/not-executed"
        command, _, _ = backup.dump_command(item)
        self.assertNotIn(item["connection"]["user"], command[command.index("-c") + 1])
        self.assertIn(item["connection"]["user"], command)
        # Exercise fixed shell code against a fake pg_dumpall.
        tool = self.root / "pg_dumpall"
        tool.write_text('#!/bin/sh\nprintf "%s\\n" "$PGPASSWORD" "$@"\n')
        tool.chmod(0o700)
        script = command[command.index("-c") + 1]
        env = dict(os.environ, PATH=f"{self.root}:{os.environ['PATH']}",
                   POSTGRES_USER="configured_user", POSTGRES_PASSWORD="configured_password",
                   POSTGRES_DB="configured_db")
        result = subprocess.run(["sh", "-c", script, "test", "", "", "cluster", "pg_dumpall"],
                                env=env, capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.splitlines(),
                         ["configured_password", "-U", "configured_user", "-l", "configured_db"])

    def test_optional_docker_unit_validation(self):
        for value in ("", "docker.service", "docker.socket", "rootless@user.service"):
            item = target()
            item['execution']['docker_unit'] = value
            backup.validate_target(item, self.output)
        for value in (None, 'docker.service other.service', '../docker.service', 'docker.service\n'):
            item = target()
            item['execution']['docker_unit'] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'docker_unit'):
                backup.validate_target(item, self.output)

    def test_skip_policy_must_be_boolean(self):
        for value in ("false", 0, None):
            item = target()
            item["execution"]["skip_if_unavailable"] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "must be a boolean"):
                backup.validate_target(item, self.output)

    def test_absent_or_stopped_container_skips_without_touching_dumps(self):
        directory = self.output / "example/0"
        directory.mkdir(parents=True)
        destination = directory / "dump.sql"
        destination.write_bytes(b"previous dump")
        with patch.object(backup.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, stdout="\n")) as run:
            backup.run_backup(target(), self.output)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0][-5:], ["ps", "--status", "running", "--quiet", "db"])
        self.assertEqual(run.call_args.kwargs['env'].get('DOCKER_HOST'), os.environ.get('DOCKER_HOST'))
        self.assertEqual(run.call_args.kwargs['cwd'], '/srv/example')
        self.assertEqual(destination.read_bytes(), b"previous dump")
        self.assertEqual(sorted(p.name for p in directory.iterdir()), ["dump.sql"])

    def test_strict_policy_does_not_skip_missing_container(self):
        item = target()
        item["execution"]["skip_if_unavailable"] = False
        with patch.object(backup.subprocess, "run", side_effect=subprocess.CalledProcessError(1, ["docker", "exec"])) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                backup.run_backup(item, self.output)
        self.assertEqual(run.call_count, 1)
        self.assertIn("exec", run.call_args.args[0])

    def test_unavailable_docker_is_failure_not_skip(self):
        with patch.object(backup.subprocess, "run", side_effect=subprocess.CalledProcessError(1, ["docker", "ps"])):
            with self.assertRaises(subprocess.CalledProcessError):
                backup.run_backup(target(), self.output)
        self.assertFalse((self.output / "example").exists())

    def test_container_stopping_during_dump_skips_and_cleans_staging(self):
        responses = [subprocess.CompletedProcess([], 0, stdout="container-id\n"),
                     subprocess.CalledProcessError(1, ["docker", "exec"]),
                     subprocess.CompletedProcess([], 0, stdout="")]
        directory = self.output / "example/0"
        directory.mkdir(parents=True)
        (directory / "dump.sql").write_bytes(b"previous dump")
        with patch.object(backup.subprocess, "run", side_effect=responses):
            backup.run_backup(target(), self.output)
        self.assertEqual((directory / "dump.sql").read_bytes(), b"previous dump")
        self.assertEqual(list(directory.glob("*.tmp")), [])

    def test_running_container_dump_error_is_failure(self):
        responses = [subprocess.CompletedProcess([], 0, stdout="container-id\n"),
                     subprocess.CalledProcessError(1, ["docker", "exec"]),
                     subprocess.CompletedProcess([], 0, stdout="container-id\n")]
        with patch.object(backup.subprocess, "run", side_effect=responses):
            with self.assertRaises(subprocess.CalledProcessError):
                backup.run_backup(target(), self.output)
        self.assertFalse((self.output / "example/0/dump.sql").exists())

    def test_skip_is_success_at_cli_level_and_strict_mode_fails(self):
        docker = self.root / "docker"
        docker.write_text('#!/bin/sh\ncase " $* " in *" ps "*) exit 0;; *) exit 1;; esac\n')
        docker.chmod(0o700)
        item = target()
        item["project_path"] = str(self.root)
        item["execution"]["docker_bin"] = str(docker)
        command = [str(RUNNER), "--manifest-dir", str(self.manifests),
                   "--output-root", str(self.output), "--target", item["id"]]
        self.publish("example", [item])
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Backup skipped:", result.stdout)
        self.assertFalse((self.output / "example").exists())
        strict_result = subprocess.run(command + ["--require-available"], capture_output=True, text=True)
        self.assertNotEqual(strict_result.returncode, 0)
        self.assertIn("Backup failed:", strict_result.stderr)
        item["execution"]["skip_if_unavailable"] = False
        self.publish("example", [item])
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Backup failed:", result.stderr)

    def test_direct_driver_does_not_check_docker_availability(self):
        item = target()
        item["execution"] = {"driver": "direct"}
        with patch.object(backup.subprocess, "run") as run:
            self.assertFalse(backup.skip_unavailable_container(item))
        run.assert_not_called()

    def test_concurrent_manual_and_timer_runs_share_lock(self):
        docker = self.root / "docker"
        marker = self.root / "busy"
        docker.write_text(f'''#!/usr/bin/env python3
import os, sys, time
if "ps" in sys.argv:
    print("container-id")
    sys.exit(0)
fd = os.open({str(marker)!r}, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
try:
    time.sleep(0.2)
    print("complete dump")
finally:
    os.close(fd)
    os.unlink({str(marker)!r})
''')
        docker.chmod(0o700)
        item = target()
        item["project_path"] = str(self.root)
        item["execution"]["docker_bin"] = str(docker)
        self.publish("example", [item])
        command = [str(RUNNER), "--manifest-dir", str(self.manifests),
                   "--output-root", str(self.output), "--target", item["id"]]
        processes = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
        for process in processes:
            _, stderr = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0, stderr.decode())
        self.assertEqual((self.output / "example/0/dump.sql").read_text(), "complete dump\n")


if __name__ == "__main__":
    unittest.main()
