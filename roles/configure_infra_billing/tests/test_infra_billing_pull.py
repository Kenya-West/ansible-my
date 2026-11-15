"""Pull-only host_vars sync tests (no network, temp files only).

Run: python3 -m unittest discover -s roles/configure_infra_billing/tests -v
"""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location('pull_action', REPO / 'action_plugins/infra_billing_pull.py')
pull = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pull)

UUID = '00000000-0000-0000-0000-000000000004'
PROJECT = '00000000-0000-0000-0000-000000000001'
HOST_YAML = '''# keep me
infrastructure:
  provider: "vendor"
  account: "main"
  service_id: '42'
  billing:
    amount: "370"   # trailing comment
    currency: RUB
    interval:
      every: 1
      unit: month
    next_due_at: "2026-12-01T00:00:00Z"

infra_billing_service:
  enabled: true
  project_uuid: %s
''' % PROJECT


def service(**o):
    s = {'uuid': UUID, 'name': 'vendor-de-1', 'externalId': '42', 'cost': '400.00', 'currency': 'RUB',
         'period': 'quarterly', 'nextBillingAt': '2027-01-01T00:00:00Z', 'projectUuid': PROJECT}
    s.update(o)
    return s


class PullTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = os.path.join(self.dir.name, 'host.yaml')
        Path(self.path).write_text(HOST_YAML)

    def run_one(self, services, check=False, path=None):
        return pull.process_host({'name': 'vendor-de-1', 'file': path or self.path}, services, {}, check)

    def test_updates_values_keeping_comments_and_layout(self):
        report, before, after = self.run_one([service()])
        self.assertEqual(report['status'], 'updated')
        self.assertIn('# keep me', after)
        self.assertIn('amount: "400.00"   # trailing comment', after)
        self.assertIn('every: 3', after)
        self.assertIn('next_due_at: "2027-01-01T00:00:00Z"', after)
        self.assertEqual(before, HOST_YAML)
        self.assertEqual(Path(self.path).read_text(), HOST_YAML, 'process_host itself never writes')

    def test_equivalent_values_are_not_rewritten(self):
        report, _, after = self.run_one([service(cost='370', period='monthly', nextBillingAt='2026-12-01T00:00:00.000Z')])
        self.assertIsNone(after)
        self.assertEqual(report['status'], 'unchanged')

    def test_missing_keys_are_never_added(self):
        Path(self.path).write_text('infrastructure:\n  provider: v\n  account: main\n  service_id: "42"\n')
        report, _, after = self.run_one([service()])
        self.assertIsNone(after)

    def test_missing_file_is_skipped_not_created(self):
        missing = os.path.join(self.dir.name, 'nope.yaml')
        report, _, after = self.run_one([service()], path=missing)
        self.assertEqual(report['status'], 'skipped')
        self.assertFalse(os.path.exists(missing))

    def test_unknown_uuid_and_ambiguity_skip(self):
        Path(self.path).write_text(HOST_YAML.replace('enabled: true', 'enabled: true\n  uuid: ' + '9' * 8 + '-0000-0000-0000-000000000000'))
        self.assertEqual(self.run_one([service()])[0]['status'], 'skipped')
        Path(self.path).write_text(HOST_YAML)
        other = service(uuid='00000000-0000-0000-0000-000000000005')
        self.assertEqual(self.run_one([service(), other])[0]['status'], 'skipped')

    def test_vault_and_symlink_skipped(self):
        Path(self.path).write_text('$ANSIBLE_VAULT;1.1;AES256\n00')
        self.assertEqual(self.run_one([service()])[0]['status'], 'skipped')
        Path(self.path).write_text(HOST_YAML)
        link = os.path.join(self.dir.name, 'link.yaml')
        os.symlink(self.path, link)
        self.assertEqual(self.run_one([service()], path=link)[0]['status'], 'skipped')

    def test_check_mode_status(self):
        self.assertEqual(self.run_one([service()], check=True)[0]['status'], 'would update')


if __name__ == '__main__':
    unittest.main()
