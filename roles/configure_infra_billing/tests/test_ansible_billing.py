"""Exercise role failure/report handling with the real Ansible CLI and a fake action."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[3]


@unittest.skipUnless(shutil.which('ansible-playbook'), 'requires Ansible')
class BillingRoleTests(unittest.TestCase):
    def cli(self, result, check=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'inventory.ini').write_text('[analytics_server]\nlocalhost ansible_connection=local\n')
            (root / 'result.json').write_text(json.dumps(result))
            plugins = root / 'plugins'
            plugins.mkdir()
            (plugins / 'infra_billing.py').write_text('''
import json
import os
from ansible.plugins.action import ActionBase
class ActionModule(ActionBase):
    _requires_connection = False
    _supports_check_mode = True
    def run(self, tmp=None, task_vars=None):
        self._task.no_log = True
        with open(os.environ['BILLING_TEST_RESULT']) as stream:
            result = json.load(stream)
        result['_ansible_no_log'] = True
        return result
''')
            command = ['ansible-playbook', '-i', str(root / 'inventory.ini'),
                       str(REPO / 'playbooks/observability/server/infra_billing_sync.yaml'),
                       '-e', json.dumps({'infra_billing_manage_hosts': False,
                                         'infra_billing_api_url': 'https://billing.example',
                                         'infra_billing_api_token': 'PRIVATE-TOKEN'})]
            if check:
                command.append('--check')
            completed = subprocess.run(command, cwd=REPO, env=dict(
                os.environ, ANSIBLE_ACTION_PLUGINS=str(plugins),
                ANSIBLE_LOG_PATH=str(root / 'ansible.log'), ANSIBLE_NOCOLOR='1',
                BILLING_TEST_RESULT=str(root / 'result.json'),
            ), text=True, capture_output=True, timeout=60)
            return completed.returncode, completed.stdout + completed.stderr

    def test_partial_failure_prints_safe_report_then_fails(self):
        code, output = self.cli({
            'changed': True, 'failed': True, 'sync_failed': 1,
            'msg': 'PRIVATE raw action result',
            'counts': {'creates': 0, 'updates': 0, 'syncs': 2},
            'report': {'mode': 'apply (partial failure)', 'lines': [
                'SYNC account broken/main [FAILED: connector error]',
                'SYNC account healthy/main (account-wide connector refresh/import)',
            ]},
        })
        self.assertNotEqual(code, 0, output)
        self.assertIn('SYNC=2', output)
        self.assertIn('broken/main [FAILED: connector error]', output)
        self.assertIn('healthy/main', output)
        self.assertIn('1 infra-billing account sync(s) failed', output)
        self.assertNotIn('PRIVATE', output)

    def test_validation_failure_is_not_deferred_or_exposed(self):
        code, output = self.cli({'failed': True, 'changed': False, 'msg': 'PRIVATE validation input'})
        self.assertNotEqual(code, 0, output)
        self.assertNotIn('Report billing changes', output)
        self.assertNotIn('PRIVATE', output)

    def test_safe_validation_failure_is_shown_without_private_result(self):
        message = ('Host/service hshp-de-14 (hshp/main): infra_billing_service.uuid no longer exists; '
                   'manual replacement needs verified infrastructure.billing.amount, currency and interval')
        code, output = self.cli({'failed': True, 'changed': False, 'msg': 'PRIVATE validation input',
                                 'private_data': {'password': 'PRIVATE-PASSWORD'}, 'public_error': message}, check=True)
        self.assertNotEqual(code, 0, output)
        self.assertIn(message, output)
        self.assertNotIn('Report billing changes', output)
        self.assertNotIn('PRIVATE', output)

    def test_check_success_does_not_run_final_fail_task(self):
        code, output = self.cli({
            'changed': True, 'counts': {'creates': 0, 'updates': 0, 'syncs': 1},
            'report': {'mode': 'check (planned, no API writes; connector health not tested)',
                       'lines': ['SYNC account healthy/main']},
        }, check=True)
        self.assertEqual(code, 0, output)
        self.assertIn('connector health not tested', output)
        self.assertIn('SYNC account healthy/main', output)


if __name__ == '__main__':
    unittest.main()
