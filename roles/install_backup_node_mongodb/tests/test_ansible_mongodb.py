"""Actual Ansible CLI tests with isolated paths; no Docker/systemd/sudo needed."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[3]


def target(identity):
    return {'id': identity, 'project_path': '/srv/example',
            'execution': {'driver': 'compose_exec', 'service': 'db'},
            'output': {'subdirectory': identity, 'filename': 'dump.archive.gz'}}


@unittest.skipUnless(shutil.which('ansible-playbook'), 'requires Ansible')
class AnsibleMongoDBTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.inventory = self.root / 'inventory.ini'
        self.inventory.write_text('[backup_restic_node]\nlocalhost ansible_connection=local\n')
        self.variables = {
            'standard_user': os.environ['USER'],
            'mongodump_backup_home': str(self.root / 'home'),
            'mongodump_manifest_dir': str(self.root / 'home/manifests'),
            'mongodump_declare_directory': str(self.root / 'home/manifests'),
            'mongodump_runner_path': str(self.root / 'home/bin/runner.py'),
            'mongodump_systemd_unit_path': str(self.root / 'home/units'),
            'mongodump_backup_location_root_path': str(self.root / 'dumps'),
            'mongodump_legacy_credentials_dir': str(self.root / 'credentials'),
            'mongodump_backup_monitor_argv': [], 'expected_other_targets': [],
        }

    def cli(self, playbook, check=True, success=True):
        variables = self.root / 'vars.json'
        variables.write_text(json.dumps(self.variables))
        command = ['ansible-playbook', '-i', str(self.inventory), str(REPO / playbook), '-e', '@'+str(variables)]
        if check:
            command.append('--check')
        result = subprocess.run(command, cwd=REPO, env=dict(os.environ, ANSIBLE_LOG_PATH=str(self.root/'ansible.log'),
                                                           ANSIBLE_NOCOLOR='1'), capture_output=True, text=True, timeout=60)
        output = result.stdout + result.stderr
        if success:
            self.assertEqual(result.returncode, 0, output)
        else:
            self.assertNotEqual(result.returncode, 0, output)
        return output

    def test_standalone_first_install_check_needs_no_tools_or_registry(self):
        output = self.cli('playbooks/backup/node/mongodb.yaml')
        self.assertIn('Preview MongoDB backup changes', output)
        self.assertFalse((self.root/'home').exists())
        self.assertFalse((self.root/'dumps').exists())

    def test_check_overlay_and_removal_work_on_fresh_host(self):
        self.cli('roles/install_backup_node_mongodb/tests/check-mode.yml')
        self.assertFalse((self.root/'home').exists())

    def test_other_producers_are_preserved_in_check_overlay(self):
        manifests = Path(self.variables['mongodump_manifest_dir'])
        units = Path(self.variables['mongodump_systemd_unit_path'])
        manifests.mkdir(parents=True)
        units.mkdir()
        for owner, identity in [('example','old-db'), ('other','other-db')]:
            (manifests/f'{owner}.json').write_text(json.dumps({'schema_version':1,'owner':owner,'targets':[target(identity)]}))
        for kind in ('service','timer'):
            (units/f'ansible-mongodb-backup-old-db.{kind}').write_text('original')
        before = {p:p.read_bytes() for p in manifests.glob('*')} | {p:p.read_bytes() for p in units.glob('*')}
        self.variables['expected_other_targets'] = ['other-db']
        self.cli('roles/install_backup_node_mongodb/tests/check-mode.yml')
        for p, data in before.items():
            self.assertEqual(p.read_bytes(), data)

    def test_legacy_remote_targets_are_previewed_without_writing_credentials(self):
        self.variables['mongotools_mongodb_endpoints'] = [{'uri':'mongodb+srv://user:secret@cluster.example/app',
                                                          'out_file':'app.archive.gz'}]
        output = self.cli('playbooks/backup/node/mongodb.yaml')
        self.assertIn('Preview MongoDB backup changes', output)
        self.assertNotIn('user:secret', output)
        self.assertFalse((self.root/'credentials').exists())
        self.assertFalse((self.root/'home').exists())

    def test_empty_legacy_list_is_valid(self):
        self.variables['mongotools_mongodb_endpoints'] = []
        self.cli('playbooks/backup/node/mongodb.yaml')
        self.assertFalse((self.root/'credentials').exists())

    def test_unsafe_legacy_output_rejected_before_changes(self):
        self.variables['mongotools_mongodb_endpoints'] = [{'uri':'mongodb://localhost', 'out_file':'../bad'}]
        self.cli('playbooks/backup/node/mongodb.yaml', success=False)
        self.assertFalse((self.root/'credentials').exists())

    def test_legacy_apply_publishes_private_config_without_plaintext_manifest_uri(self):
        self.variables['mongotools_mongodb_endpoints'] = [{'uri':'mongodb+srv://user:secret@cluster.example/app',
                                                          'out_file':'app.archive.gz'}]
        self.variables['mongodump_declare_reconcile'] = False
        self.cli('playbooks/backup/node/mongodb.yaml', check=False)
        manifest = Path(self.variables['mongodump_manifest_dir'])/'legacy-mongotools.json'
        text = manifest.read_text()
        data = json.loads(text)
        self.assertNotIn('user:secret', text)
        self.assertTrue(data['legacy_cron_job'])
        connection = Path(data['targets'][0]['connection']['config_file'])
        self.assertEqual(json.loads(connection.read_text())['uri'], self.variables['mongotools_mongodb_endpoints'][0]['uri'])
        self.assertEqual(connection.stat().st_mode & 0o777, 0o600)
        self.assertEqual(data['targets'][0]['output'], {'subdirectory':'legacy', 'filename':'app.archive.gz'})

    def test_duplicate_legacy_outputs_fail_before_writing_credentials(self):
        self.variables['mongotools_mongodb_endpoints'] = [{'uri':'mongodb://host-a', 'out_file':'same.gz'},
                                                         {'uri':'mongodb://host-b', 'out_file':'same.gz'}]
        self.cli('playbooks/backup/node/mongodb.yaml', success=False)
        self.assertFalse((self.root/'credentials').exists())

    def test_local_and_remote_manifests_publish_without_secret_values(self):
        remote = {'id':'remote-db', 'execution':{'driver':'direct'},
                  'connection':{'source':'config_file','config_file':str(self.root/'private.yaml')},
                  'dump':{'gzip':True}, 'output':{'subdirectory':'remote','filename':'dump.archive.gz'}}
        self.variables['test_targets'] = [target('local-db'), remote]
        self.cli('roles/install_backup_node_mongodb/tests/publish.yml', check=False)
        manifest = Path(self.variables['mongodump_manifest_dir'])/'example.json'
        data = json.loads(manifest.read_text())
        self.assertEqual(data['targets'], self.variables['test_targets'])
        self.assertEqual(manifest.stat().st_mode & 0o777, 0o600)
        self.assertFalse(Path(self.variables['mongodump_runner_path']).exists())


if __name__ == '__main__':
    unittest.main()
