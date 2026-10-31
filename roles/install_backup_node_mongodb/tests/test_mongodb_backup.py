"""MongoDB runner regression tests; fake tools/containers, no live databases."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

RUNNER = Path(__file__).resolve().parents[1] / "files/mongodb_backup.py"
spec = importlib.util.spec_from_file_location("mongodb_backup", RUNNER)
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


def target():
    return {"id": "example-db", "project_path": "/srv/example",
            "execution": {"driver": "compose_exec", "service": "db", "project_name": "example"},
            "connection": {"source": "container_environment"}, "dump": {"gzip": True},
            "output": {"subdirectory": "example/0", "filename": "dump.archive.gz"}}


class MongoDBTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.output = self.root / "output"
        self.output.mkdir()
        self.config = self.root / "connection.yaml"
        self.config.write_text('uri: "mongodb+srv://user:secret@cluster.example/app?authSource=admin"\n')
        self.config.chmod(0o600)

    def direct(self):
        item = target()
        item['execution'] = {'driver': 'direct'}
        item['connection'] = {'source': 'config_file', 'config_file': str(self.config)}
        return item

    def test_direct_config_keeps_credentials_out_of_argv(self):
        item = self.direct()
        backup.validate_target(item, self.output)
        with backup.dump_command(item) as (command, env, cwd, stdin):
            self.assertIn('--archive', command)
            self.assertIn('--gzip', command)
            self.assertEqual(command[-2], '--config')
            self.assertEqual(Path(command[-1]).read_text(), self.config.read_text())
            self.assertEqual(Path(command[-1]).stat().st_mode & 0o777, 0o600)
            temporary = Path(command[-1])
            self.assertNotIn('secret', ' '.join(command))
            self.assertIsNone(stdin)
        self.assertFalse(temporary.exists())
        self.config.chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'private regular file'):
            with backup.dump_command(item):
                pass

    def test_remote_url_file_uses_ephemeral_private_config(self):
        uri = 'mongodb+srv://user:p%40ss@cluster.example/app?authSource=admin'
        self.config.write_text(uri)
        item = self.direct()
        item['connection'] = {'url_file': str(self.config)}
        backup.validate_target(item, self.output)
        with backup.dump_command(item) as (command, _, _, _):
            path = Path(command[-1])
            self.assertEqual(json.loads(path.read_text()), {'uri': uri})
            self.assertNotIn(uri, ' '.join(command))
        self.assertFalse(path.exists())

    def test_mongodb_options_and_oplog_constraints(self):
        item = target()
        item['dump'] = {'gzip': False, 'oplog': True}
        backup.validate_target(item, self.output)
        with backup.dump_command(item) as (command, _, _, _):
            self.assertIn('--oplog', command)
            self.assertNotIn('--gzip', command)
            self.assertIn('-T', command)
        item['connection']['database'] = 'app'
        with self.assertRaisesRegex(ValueError, 'oplog requires'):
            backup.validate_target(item, self.output)
        item['dump']['oplog'] = False
        with backup.dump_command(item) as (command, _, _, _):
            self.assertEqual(command[command.index('--db') + 1], 'app')

    def test_compose_private_config_stream(self):
        item = target()
        item['connection'] = {'source': 'config_file', 'config_file': str(self.config)}
        with backup.dump_command(item) as (command, _, _, config):
            self.assertEqual(config, self.config.read_bytes())
            self.assertNotIn('secret', ' '.join(command))
            script = command[command.index('-c') + 1]
            tool = self.root / 'mongodump'
            tool.write_text('#!/bin/sh\nwhile [ "$1" != --config ]; do shift; done\ncat "$2"\n')
            tool.chmod(0o700)
            result = subprocess.run(['sh', '-c', script, 'test', str(tool), '--archive'],
                                    input=config, capture_output=True, check=True,
                                    env=dict(os.environ, TMPDIR=str(self.root)))
            self.assertEqual(result.stdout, config)
            self.assertEqual(list(self.root.glob('tmp.*')), [])

    def test_container_environment_uses_private_config_and_cleanup(self):
        item = target()
        with backup.dump_command(item) as (command, _, _, _):
            script = command[command.index('-c') + 1]
            mongosh = self.root / 'mongosh'
            # Fake JS serializer verifies env exists; no secrets passed as argv.
            mongosh.write_text('#!/usr/bin/env python3\nimport os,json\nprint("uri: " + json.dumps("mongodb://root@localhost/?authSource=admin"))\nprint("password: " + json.dumps(os.environ["MONGO_INITDB_ROOT_PASSWORD"]))\n')
            mongosh.chmod(0o700)
            tool = self.root / 'mongodump'
            tool.write_text('#!/bin/sh\nwhile [ "$1" != --config ]; do shift; done\ncat "$2"\n')
            tool.chmod(0o700)
            secret = 'p@ss:"\\\nword'
            result = subprocess.run(['sh', '-c', script, 'test', 'localhost:27017', 'admin', str(tool)],
                                    env=dict(os.environ, PATH=f'{self.root}:'+os.environ['PATH'], TMPDIR=str(self.root),
                                             MONGO_INITDB_ROOT_USERNAME='root', MONGO_INITDB_ROOT_PASSWORD=secret),
                                    capture_output=True, text=True, check=True)
            self.assertIn(json.dumps(secret), result.stdout)
            self.assertEqual(list(self.root.glob('tmp.*')), [])

    def test_failed_and_empty_dumps_preserve_archive(self):
        directory = self.output / 'example/0'
        directory.mkdir(parents=True)
        destination = directory / 'dump.archive.gz'
        destination.write_bytes(b'previous')
        for failure in (True, False):
            def fake_run(command, **kwargs):
                kwargs['stdout'].write(b'new archive')
                self.assertEqual(destination.read_bytes(), b'previous')
                if failure:
                    raise subprocess.CalledProcessError(1, command, stderr=b'URI secret')
            with patch.object(backup.subprocess, 'run', side_effect=fake_run):
                if failure:
                    with self.assertRaises(subprocess.CalledProcessError):
                        backup.run_backup(self.direct(), self.output)
                else:
                    backup.run_backup(self.direct(), self.output)
                    self.assertEqual(destination.read_bytes(), b'new archive')
                    self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
            self.assertEqual(list(directory.glob('*.tmp')), [])
        with patch.object(backup.subprocess, 'run'):
            with self.assertRaisesRegex(ValueError, 'empty'):
                backup.run_backup(self.direct(), self.output)
        self.assertEqual(destination.read_bytes(), b'new archive')

    def test_stopped_container_skips_default_but_strict_fails(self):
        with patch.object(backup.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, stdout='')):
            backup.run_backup(target(), self.output)
        self.assertFalse((self.output / 'example').exists())
        item = target()
        item['execution']['skip_if_unavailable'] = False
        with patch.object(backup.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, [])):
            with self.assertRaises(subprocess.CalledProcessError):
                backup.run_backup(item, self.output)

    def test_docker_errors_are_not_skips(self):
        with patch.object(backup.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, [])):
            with self.assertRaises(subprocess.CalledProcessError):
                backup.run_backup(target(), self.output)

    def test_container_stop_race_cleans_partial_archive(self):
        results = [subprocess.CompletedProcess([], 0, stdout='id'), subprocess.CalledProcessError(1, []),
                   subprocess.CompletedProcess([], 0, stdout='')]
        with patch.object(backup.subprocess, 'run', side_effect=results):
            backup.run_backup(target(), self.output)
        self.assertEqual(list(self.output.rglob('*.tmp')), [])
        self.assertFalse((self.output / 'example/0/dump.archive.gz').exists())

    def test_inline_credentials_are_rejected(self):
        item = target()
        item['connection']['uri'] = 'mongodb://user:secret@localhost'
        with self.assertRaisesRegex(ValueError, 'private connection file'):
            backup.validate_target(item, self.output)

    def test_paths_duplicates_and_boolean_validation(self):
        item = target()
        for value in ('false', None, 0):
            item['dump']['gzip'] = value
            with self.assertRaises(ValueError):
                backup.validate_target(item, self.output)
        item = target()
        item['output']['subdirectory'] = '../escape'
        with self.assertRaises(ValueError):
            backup.validate_target(item, self.output)
        with self.assertRaisesRegex(ValueError, 'duplicate target'):
            backup.validate_targets([target(), target()], self.output)
        outside = self.root / 'outside'
        outside.mkdir()
        (self.output / 'example').symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'escapes root'):
            backup.validate_target(target(), self.output)

    def test_cli_direct_dump_redacts_tool_errors_and_works_with_fake_tool(self):
        tool = self.root / 'mongodump'
        tool.write_text('#!/bin/sh\necho "secret MongoDB URI" >&2\nexit 1\n')
        tool.chmod(0o700)
        item = self.direct()
        item['execution']['mongodump_bin'] = str(tool)
        manifests = self.root / 'manifests'
        manifests.mkdir()
        (manifests / 'example.json').write_text(json.dumps({'schema_version': 1, 'owner': 'example', 'targets': [item]}))
        command = [str(RUNNER), '--manifest-dir', str(manifests), '--output-root', str(self.output), '--target', item['id']]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn('secret', result.stderr)
        tool.write_text('#!/bin/sh\nprintf "archive data"\n')
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.output / 'example/0/dump.archive.gz').read_bytes(), b'archive data')

    def test_concurrent_direct_invocations_share_lock(self):
        tool = self.root / 'mongodump'
        marker = self.root / 'busy'
        tool.write_text(f'#!/usr/bin/env python3\nimport os,time\nfd=os.open({str(marker)!r},os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)\ntry:\n time.sleep(.2)\n print("archive")\nfinally:\n os.close(fd)\n os.unlink({str(marker)!r})\n')
        tool.chmod(0o700)
        item = self.direct()
        item['execution']['mongodump_bin'] = str(tool)
        manifests = self.root / 'manifests'
        manifests.mkdir()
        (manifests / 'example.json').write_text(json.dumps({'schema_version': 1, 'owner': 'example', 'targets': [item]}))
        command = [str(RUNNER), '--manifest-dir', str(manifests), '--output-root', str(self.output), '--target', item['id']]
        processes = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
        for process in processes:
            _, stderr = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0, stderr)


if __name__ == '__main__':
    unittest.main()
