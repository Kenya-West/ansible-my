"""Run actual Ansible CLI regressions without SSH, sudo, Docker or systemd."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[3]


def target(identity):
    return {"id": identity, "project_path": "/srv/example",
            "execution": {"driver": "compose_exec", "service": "db"},
            "output": {"subdirectory": identity, "filename": "dump.sql"}}


@unittest.skipUnless(shutil.which("ansible-playbook"), "requires ansible-playbook")
class AnsibleCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.inventory = self.root / "inventory.ini"
        self.inventory.write_text("[vpn_server_remnawave]\nlocalhost ansible_connection=local\n"
                                  "[backup_restic_node]\nlocalhost\n")
        self.variables = {
            "standard_user": os.environ["USER"],
            "pgdump_backup_home": str(self.root / "home"),
            "pgdump_manifest_dir": str(self.root / "home/manifests"),
            "pgdump_declare_directory": str(self.root / "home/manifests"),
            "pgdump_runner_path": str(self.root / "home/bin/runner.py"),
            "pgdump_systemd_unit_path": str(self.root / "home/units"),
            "pgdump_backup_location_root_path": str(self.root / "dumps"),
            "pgdump_backup_monitor_argv": [],
            "vpn_server_remnawave": {"project": {"root": "vpn", "paths": {"panel": "vpn/panel"}}},
            "location_custom_files_path_hostname": str(self.root / "assets"),
            "source_paths_add_role_dirs": [], "source_paths_add_repo_dirs": [],
            "expected_other_targets": [],
        }

    def cli(self, playbook, tags=None, success=True, check=True):
        variables = self.root / "vars.json"
        variables.write_text(json.dumps(self.variables))
        command = ["ansible-playbook", "-i", str(self.inventory), str(REPO / playbook),
                   "-e", "@" + str(variables)]
        if check:
            command.append("--check")
        if tags:
            command += ["--tags", tags]
        env = dict(os.environ, ANSIBLE_LOG_PATH=str(self.root / "ansible.log"), ANSIBLE_NOCOLOR="1")
        result = subprocess.run(command, cwd=REPO, env=env, capture_output=True, text=True, timeout=60)
        output = result.stdout + result.stderr
        if success:
            self.assertEqual(result.returncode, 0, output)
        else:
            self.assertNotEqual(result.returncode, 0, output)
        return output

    def test_real_panel_declare_tag_first_install(self):
        output = self.cli("playbooks/anti_censorship/server/remna.yaml", "declare_backups")
        self.assertNotIn("configure_remnawave_panel_get_backup :", output)
        self.assertIn("remnawave-panel-db", output)
        self.assertIn("Preview PostgreSQL backup changes", output)
        self.assertFalse((self.root / "home").exists())
        self.assertFalse((self.root / "dumps").exists())

    def test_normal_declare_tag_does_not_run_controller_backup(self):
        # Exercise real publication; suppress only privileged host reconciliation.
        self.variables["pgdump_declare_reconcile"] = False
        output = self.cli("playbooks/anti_censorship/server/remna.yaml", "declare_backups", check=False)
        self.assertNotIn("configure_remnawave_panel_get_backup :", output)
        manifest = Path(self.variables["pgdump_manifest_dir"]) / "remnawave-panel.json"
        self.assertEqual(json.loads(manifest.read_text())["targets"][0]["id"], "remnawave-panel-db")
        self.assertFalse(Path(self.variables["pgdump_runner_path"]).exists())

    def test_project_skip_setting_is_published_as_boolean(self):
        self.variables["pgdump_declare_reconcile"] = False
        self.variables["vpn_server_remnawave_postgres_backup_skip_if_unavailable"] = False
        self.cli("playbooks/anti_censorship/server/remna.yaml", "declare_backups", check=False)
        manifest = Path(self.variables["pgdump_manifest_dir"]) / "remnawave-panel.json"
        self.assertIs(json.loads(manifest.read_text())["targets"][0]["execution"]["skip_if_unavailable"], False)

    def test_fresh_registry_can_preview_and_remove_targets(self):
        self.cli("roles/install_backup_node_postgres/tests/check-mode.yml")
        self.assertFalse((self.root / "home").exists())
        self.assertFalse((self.root / "dumps").exists())

    def test_overlay_persisted_registry_and_retire_units_without_changes(self):
        manifests = Path(self.variables["pgdump_manifest_dir"])
        units = Path(self.variables["pgdump_systemd_unit_path"])
        manifests.mkdir(parents=True)
        units.mkdir()
        for owner, identity in (("example", "old-db"), ("other", "other-db")):
            (manifests / f"{owner}.json").write_text(json.dumps({"schema_version": 1, "owner": owner,
                                                                "targets": [target(identity)]}))
        for kind in ("service", "timer"):
            (units / f"ansible-postgres-backup-old-db.{kind}").write_text("original unit")
        before = {str(path): path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        self.variables["expected_other_targets"] = ["other-db"]
        self.cli("roles/install_backup_node_postgres/tests/check-mode.yml")
        for path, content in before.items():
            self.assertEqual(Path(path).read_bytes(), content)
        self.assertFalse(Path(self.variables["pgdump_runner_path"]).exists())
        self.assertFalse((self.root / "dumps").exists())

    def test_check_mode_validates_full_proposed_dump_contract(self):
        item = target("bad-db")
        item["dump"] = {"scope": "cluster", "format": "custom"}
        self.variables["vpn_server_remnawave_postgres_backup_targets"] = [item]
        output = self.cli("playbooks/anti_censorship/server/remna.yaml", "declare_backups", success=False)
        self.assertIn("cluster dumps require plain format", output)
        self.assertFalse((self.root / "home").exists())

    def test_standalone_backup_check_does_not_require_registry_or_user_manager(self):
        output = self.cli("playbooks/backup/node/postgres.yaml")
        self.assertIn("Preview PostgreSQL backup changes", output)
        self.assertFalse((self.root / "home").exists())
        self.assertFalse((self.root / "dumps").exists())

    def test_proposed_target_collision_with_another_producer_is_rejected(self):
        manifests = Path(self.variables["pgdump_manifest_dir"])
        manifests.mkdir(parents=True)
        (manifests / "other.json").write_text(json.dumps({
            "schema_version": 1, "owner": "other", "targets": [target("remnawave-panel-db")]}))
        output = self.cli("playbooks/anti_censorship/server/remna.yaml", "declare_backups", success=False)
        self.assertIn("duplicate target id", output)
        self.assertFalse((manifests / "remnawave-panel.json").exists())
        self.assertFalse(Path(self.variables["pgdump_runner_path"]).exists())

    def test_explicit_controller_backup_is_previewed_without_runner(self):
        output = self.cli("playbooks/anti_censorship/server/remna.yaml", "backup_controller")
        self.assertIn("Preview a fresh panel backup and download", output)
        self.assertNotIn("Backup runner not installed.", output)
        self.assertFalse((self.root / "home").exists())


if __name__ == "__main__":
    unittest.main()
