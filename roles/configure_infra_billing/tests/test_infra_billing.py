"""Controller-only billing reconciliation tests; all API requests are mocked.

Run: python3 -m unittest discover -s roles/configure_infra_billing/tests -v
"""
import copy
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from ansible.errors import AnsibleActionFail
import yaml

REPO = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location('billing_action', REPO / 'action_plugins/infra_billing.py')
billing = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(billing)

PROJECT = '00000000-0000-0000-0000-000000000001'
PROVIDER = '00000000-0000-0000-0000-000000000002'
ACCOUNT = '00000000-0000-0000-0000-000000000003'
SERVICE = '00000000-0000-0000-0000-000000000004'


def provider(uuid=PROVIDER, kind='billmgr', accounts=None):
    return {'uuid': uuid, 'name': 'Vendor', 'kind': kind,
            'accounts': accounts if accounts is not None else [
                {'uuid': ACCOUNT, 'label': 'main', 'isEnabled': True,
                 'hasPassword': True, 'username': 'user', 'baseUrl': 'https://vendor.example'}]}


def params(**overrides):
    result = {
        'api_url': 'https://billing.example', 'token': 'PRIVATE-TOKEN',
        'action': 'reconcile', 'catalog': {}, 'bindings': [], 'hosts': [],
        'domains': {}, 'domain_bindings': {}, 'rotate_credentials': False,
        'sync_missing_services': True, 'sync_all_accounts': True,
        'allow_http': False, 'validate_certs': True, 'timeout': 30,
    }
    result.update(overrides)
    return result


def declared_service(has_billing=False):
    catalog = {'vendor': {'name': 'Vendor', 'accounts': {'main': {'connection': {
        'type': 'api', 'driver': 'billmgr', 'api_url': 'https://vendor.example',
        'credentials': {'username': 'user', 'password': 'PRIVATE-PASSWORD'},
    }}}}}
    bindings = [{'provider': 'vendor', 'kind': 'billmgr', 'accounts': {'main': {'label': 'main'}}}]
    infra = {'provider': 'vendor', 'account': 'main', 'service_id': '42'}
    if has_billing:
        infra['billing'] = {'amount': '10.00', 'currency': 'USD', 'interval': {'every': 1, 'unit': 'month'}}
    hosts = [{'name': 'vendor-de-1', 'infrastructure': infra,
              'binding': {'enabled': True, 'project_uuid': PROJECT}}]
    return {'catalog': catalog, 'bindings': bindings, 'hosts': hosts}


def managed_service(**overrides):
    result = {'uuid': SERVICE, 'name': 'Connector name', 'type': 'vps', 'accountUuid': ACCOUNT,
              'externalId': '42', 'isManaged': True, 'projectUuid': PROJECT,
              'cost': '20.00', 'currency': 'EUR', 'period': 'yearly',
              'nextBillingAt': '2027-01-01T00:00:00Z'}
    result.update(overrides)
    return result


class FakeAPI:
    def __init__(self, providers=None, services=None, imported=None, status='ok'):
        self.providers = copy.deepcopy(providers or [])
        self.services = copy.deepcopy(services or [])
        self.imported = imported
        self.status = status
        self.calls = []

    def __call__(self, url, method, data, **kwargs):
        path = url.split('/api', 1)[1]
        body = json.loads(data) if data else None
        self.calls.append((method, path, body, kwargs))
        if method == 'GET':
            result = {'/providers': self.providers, '/services': self.services,
                      '/projects': [{'uuid': PROJECT}]}[path]
        elif path.endswith('/sync'):
            aid = path.removeprefix('/provider-accounts/').removesuffix('/sync')
            status = self.status.get(aid, 'ok') if isinstance(self.status, dict) else self.status
            if isinstance(status, Exception):
                raise status
            if self.imported is not None and status == 'ok':
                self.services = copy.deepcopy(self.imported)
            result = {'status': status, 'error': 'PRIVATE-ERROR password=PRIVATE-PASSWORD'}
        elif method == 'POST' and path == '/providers':
            first = dict(body['account'], uuid=ACCOUNT, isEnabled=True, hasPassword=True)
            row = dict(body, uuid=PROVIDER, accounts=[first])
            self.providers.append(row)
            result = row
        elif method == 'POST' and path == '/services':
            result = dict(body, uuid=SERVICE, isManaged=False)
            self.services.append(result)
        elif method == 'PATCH':
            rows = self.services if path.startswith('/services/') else self.providers
            if path.startswith('/provider-accounts/'):
                rows = [a for p in self.providers for a in p['accounts']]
            row = next(row for row in rows if row['uuid'] == path.rsplit('/', 1)[1])
            row.update(body)
            result = row
        else:
            raise AssertionError((method, path, body))
        return io.BytesIO(json.dumps(result).encode())

    def writes(self):
        return [(m, p, b) for m, p, b, _ in self.calls if m != 'GET']


class BillingSyncTests(unittest.TestCase):
    def run_action(self, p, api, check=False):
        with patch.object(billing, 'open_url', api):
            return billing.reconcile(p, check_mode=check)

    def test_full_playbook_opts_in_but_scoped_role_defaults_do_not(self):
        play = yaml.safe_load((REPO / 'playbooks/observability/server/infra_billing_sync.yaml').read_text())[0]
        self.assertTrue(play['roles'][0]['vars']['infra_billing_sync_all_accounts'])
        defaults = yaml.safe_load((REPO / 'roles/configure_infra_billing/defaults/main.yml').read_text())
        self.assertFalse(defaults['infra_billing_sync_all_accounts'])
        tasks = yaml.safe_load((REPO / 'roles/configure_infra_billing/tasks/main.yml').read_text())
        action = next(t['infra_billing'] for t in tasks if 'infra_billing' in t)
        self.assertEqual(action['sync_all_accounts'], '{{ infra_billing_sync_all_accounts }}')

    def test_check_plans_every_enabled_live_connector_account_without_writes(self):
        api = FakeAPI(providers=[provider(accounts=[
            {'uuid': ACCOUNT, 'label': None, 'isEnabled': True},
            {'uuid': 'second', 'label': 'business', 'isEnabled': True},
            {'uuid': 'disabled', 'label': 'disabled', 'isEnabled': False},
        ]), provider('manual-provider', 'manual', [{'uuid': 'manual', 'label': 'main'}]),
            dict(provider('other-provider', 'porkbun', [{'uuid': 'registrar', 'label': None}]), name='Registrar')])
        result = self.run_action(params(), api, check=True)
        self.assertTrue(result['changed'])
        self.assertEqual(result['counts'], {'creates': 0, 'updates': 0, 'syncs': 3})
        self.assertEqual(api.writes(), [])
        self.assertEqual(len(api.calls), 3)
        self.assertEqual(len(result['report']['lines']), 3)
        self.assertIn('Vendor/business', result['report']['lines'][1])
        self.assertIn('Registrar', result['report']['lines'][2])
        self.assertNotIn('PRIVATE', json.dumps(result))

    def test_apply_refreshes_unbound_accounts_on_every_run(self):
        api = FakeAPI(providers=[provider()])
        for _ in range(2):
            result = self.run_action(params(), api)
            self.assertEqual(result['counts'], {'creates': 0, 'updates': 0, 'syncs': 1})
        self.assertEqual(api.writes(), [('POST', '/provider-accounts/' + ACCOUNT + '/sync', {})] * 2)
        self.assertTrue(all(call[3]['timeout'] >= 150 for call in api.calls if call[1].endswith('/sync')))

    def test_read_never_syncs_even_if_flag_is_set(self):
        api = FakeAPI(providers=[provider()])
        result = self.run_action(params(action='read'), api)
        self.assertFalse(result['changed'])
        self.assertEqual(api.writes(), [])

    def test_scoped_reconcile_retains_idempotent_missing_service_only_behavior(self):
        api = FakeAPI(providers=[provider()], services=[managed_service(description='{"service_id":"42"}')])
        result = self.run_action(params(**declared_service(), sync_all_accounts=False), api)
        self.assertFalse(result['changed'])
        self.assertEqual(api.writes(), [])

    def test_scoped_missing_service_import_remains_available(self):
        api = FakeAPI(providers=[provider()], imported=[managed_service()])
        result = self.run_action(params(**declared_service(), sync_all_accounts=False), api)
        self.assertEqual(result['counts'], {'creates': 0, 'updates': 1, 'syncs': 1})

    def test_full_refresh_is_independent_of_scoped_missing_import_flag(self):
        api = FakeAPI(providers=[provider()], imported=[managed_service()])
        result = self.run_action(params(**declared_service(), sync_missing_services=False), api)
        self.assertEqual(result['counts']['syncs'], 1)

    def test_credential_rotation_precedes_refresh_and_is_redacted_in_report(self):
        api = FakeAPI(providers=[provider()])
        data = declared_service()
        data['hosts'] = []
        result = self.run_action(params(**data, rotate_credentials=True), api)
        self.assertEqual([path for _, path, _ in api.writes()],
                         ['/provider-accounts/' + ACCOUNT, '/provider-accounts/' + ACCOUNT + '/sync'])
        self.assertEqual(result['counts'], {'creates': 0, 'updates': 1, 'syncs': 1})
        self.assertNotIn('PRIVATE', json.dumps(result))

    def test_disabled_account_is_not_enabled_to_import_a_missing_service(self):
        row = provider()
        row['accounts'][0]['isEnabled'] = False
        api = FakeAPI(providers=[row])
        with self.assertRaises(AnsibleActionFail):
            self.run_action(params(**declared_service()), api)
        self.assertEqual(api.writes(), [])

    def test_check_plans_known_annotation_changes_but_does_not_sync(self):
        api = FakeAPI(providers=[provider()], services=[managed_service()])
        result = self.run_action(params(**declared_service()), api, check=True)
        self.assertEqual(result['counts'], {'creates': 0, 'updates': 1, 'syncs': 1})
        self.assertEqual(len(result['report']['lines']), 2)
        self.assertEqual(api.writes(), [])

    def test_existing_managed_service_preserves_refreshed_connector_billing(self):
        p = params(**declared_service(has_billing=True))
        refreshed = managed_service(cost='99.00', nextBillingAt='2028-01-01T00:00:00Z')
        api = FakeAPI(providers=[provider()], services=[managed_service()], imported=[refreshed])
        result = self.run_action(p, api)
        self.assertEqual(result['counts'], {'creates': 0, 'updates': 1, 'syncs': 1})
        self.assertEqual(api.writes()[0][1], '/provider-accounts/' + ACCOUNT + '/sync')
        service_patch = api.writes()[1]
        self.assertEqual(set(service_patch[2]), {'description'})
        self.assertEqual(api.services[0]['cost'], '99.00')
        self.assertEqual(api.services[0]['nextBillingAt'], '2028-01-01T00:00:00Z')
        self.assertEqual(len(result['report']['lines']), sum(result['counts'].values()))
        self.assertNotIn('PRIVATE', json.dumps(result))

    def test_missing_connector_service_with_billing_imports_instead_of_manual_duplicate(self):
        api = FakeAPI(providers=[provider()], imported=[managed_service()])
        result = self.run_action(params(**declared_service(has_billing=True)), api)
        self.assertEqual(result['counts']['creates'], 0)
        self.assertEqual(result['counts']['syncs'], 1)
        self.assertFalse(any(path == '/services' for _, path, _ in api.writes()))

    def test_new_account_is_created_before_its_single_import(self):
        api = FakeAPI(imported=[managed_service()])
        result = self.run_action(params(**declared_service()), api)
        self.assertEqual(result['counts'], {'creates': 1, 'updates': 1, 'syncs': 1})
        self.assertEqual([path for _, path, _ in api.writes()],
                         ['/providers', '/provider-accounts/' + ACCOUNT + '/sync', '/services/' + SERVICE])
        self.assertNotIn('PRIVATE', json.dumps(result))

    def test_missing_services_on_shared_account_sync_once(self):
        data = declared_service()
        data['hosts'].append(copy.deepcopy(data['hosts'][0]))
        data['hosts'][1]['name'] = 'vendor-de-2'
        data['hosts'][1]['infrastructure']['service_id'] = '43'
        api = FakeAPI(providers=[provider()], imported=[managed_service(), managed_service(uuid='second', externalId='43')])
        result = self.run_action(params(**data), api)
        self.assertEqual(result['counts']['syncs'], 1)
        self.assertEqual(result['counts']['updates'], 2)

    def test_manual_exports_still_reconcile_without_connector_sync(self):
        data = declared_service(has_billing=True)
        data['catalog']['vendor']['accounts']['main']['connection'] = {'type': 'manual'}
        data['bindings'][0]['kind'] = 'manual'
        api = FakeAPI(providers=[provider(kind='manual')])
        result = self.run_action(params(**data), api)
        self.assertEqual(result['counts'], {'creates': 1, 'updates': 0, 'syncs': 0})
        self.assertEqual(api.writes()[0][1], '/services')

    def test_domains_share_full_refresh_scope(self):
        data = declared_service()
        data['hosts'] = []
        data['domains'] = {'example.com': {'provider': 'vendor', 'account': 'main'}}
        data['domain_bindings'] = {'example.com': {'enabled': True, 'project_uuid': PROJECT}}
        api = FakeAPI(providers=[provider()], imported=[managed_service(type='domain', externalId='example.com')])
        result = self.run_action(params(**data), api)
        self.assertEqual(result['counts'], {'creates': 0, 'updates': 0, 'syncs': 1})

    def test_failed_import_never_creates_manual_fallback_or_leaks_api_error(self):
        api = FakeAPI(providers=[provider()], status='error')
        result = self.run_action(params(**declared_service()), api)
        self.assertTrue(result['failed'])
        self.assertTrue(result['changed'])
        self.assertEqual(result['sync_failed'], 1)
        self.assertIn('FAILED: connector error', result['report']['lines'][0])
        self.assertIn('vendor/main', result['report']['lines'][0])
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.assertEqual(len(api.writes()), 1)

    def test_full_sync_attempts_every_account_after_connector_and_http_failures(self):
        api = FakeAPI(providers=[provider(accounts=[
            {'uuid': ACCOUNT, 'label': 'broken', 'isEnabled': True},
            {'uuid': 'network', 'label': 'network', 'isEnabled': True},
            {'uuid': 'healthy', 'label': 'healthy', 'isEnabled': True},
        ])], status={ACCOUNT: 'error', 'network': TimeoutError('PRIVATE-ERROR')})
        result = self.run_action(params(), api)
        self.assertTrue(result['failed'])
        self.assertEqual(result['sync_failed'], 2)
        self.assertEqual(result['counts'], {'creates': 0, 'updates': 0, 'syncs': 3})
        self.assertEqual(len(api.writes()), 3)
        self.assertEqual(result['report']['mode'], 'apply (partial failure)')
        self.assertIn('FAILED: connector error', result['report']['lines'][0])
        self.assertIn('FAILED: infra-billing request failed', result['report']['lines'][1])
        self.assertNotIn('FAILED', result['report']['lines'][2])
        self.assertNotIn('PRIVATE', json.dumps(result))

    def test_failed_account_does_not_block_healthy_service_annotation(self):
        data = declared_service(has_billing=True)
        data['catalog']['vendor']['accounts']['healthy'] = copy.deepcopy(data['catalog']['vendor']['accounts']['main'])
        data['bindings'][0]['accounts']['healthy'] = {'label': 'healthy'}
        healthy_host = copy.deepcopy(data['hosts'][0])
        healthy_host['name'] = 'healthy-de-1'
        healthy_host['infrastructure']['account'] = 'healthy'
        data['hosts'].append(healthy_host)
        # The failed account's target is missing; even with billing it must not
        # create a manual fallback. The healthy account's service is imported.
        row = provider()
        row['accounts'].append(dict(row['accounts'][0], uuid='healthy', label='healthy'))
        api = FakeAPI(providers=[row], status={ACCOUNT: 'error'},
                      imported=[managed_service(accountUuid='healthy')])
        result = self.run_action(params(**data, return_records=True), api)
        self.assertTrue(result['failed'])
        self.assertNotIn('records', result)
        self.assertEqual(result['counts'], {'creates': 0, 'updates': 1, 'syncs': 2})
        self.assertEqual(api.writes()[-1][1], '/services/' + SERVICE)
        self.assertEqual(set(api.writes()[-1][2]), {'description'})
        self.assertEqual(len(result['report']['lines']), 3)

    def test_scoped_import_still_fails_immediately_with_safe_account_identity(self):
        api = FakeAPI(providers=[provider()], status='error')
        with self.assertRaises(AnsibleActionFail) as exc:
            self.run_action(params(**declared_service(), sync_all_accounts=False), api)
        self.assertIn(ACCOUNT, str(exc.exception))
        self.assertTrue(exc.exception.result['changed'])
        self.assertNotIn('PRIVATE', str(exc.exception))

    def test_sync_failure_classifier_only_emits_fixed_safe_text(self):
        for error, expected in [('PRIVATE token 403', 'connector authentication/permission failure'),
                                ('PRIVATE timed out', 'connector timeout'),
                                ('PRIVATE credentials', 'missing connector credentials'),
                                ('PRIVATE arbitrary body', 'connector error')]:
            self.assertEqual(billing.reporting.sync_failure_reason({'status': 'error', 'error': error}), expected)
        self.assertEqual(billing.reporting.sync_failure_reason(None), 'unexpected sync response')
        self.assertEqual(billing.reporting.sync_failure_reason({'status': 'running'}), 'unexpected sync response')
        self.assertIsNone(billing.reporting.sync_failure_reason({'status': 'ok'}))

    def test_successful_import_without_target_refuses_manual_fallback(self):
        api = FakeAPI(providers=[provider()], imported=[])
        with self.assertRaises(AnsibleActionFail):
            self.run_action(params(**declared_service(has_billing=True)), api)
        self.assertEqual(len(api.writes()), 1)

    def test_manual_service_on_connector_account_without_external_id_is_still_created(self):
        data = declared_service(has_billing=True)
        del data['hosts'][0]['infrastructure']['service_id']
        api = FakeAPI(providers=[provider()])
        result = self.run_action(params(**data), api)
        self.assertEqual(result['counts'], {'creates': 1, 'updates': 0, 'syncs': 1})
        self.assertEqual(api.writes()[1][1], '/services')

    def test_bad_project_fails_before_any_sync(self):
        data = declared_service()
        data['hosts'][0]['binding']['project_uuid'] = PROVIDER
        api = FakeAPI(providers=[provider()])
        with self.assertRaises(AnsibleActionFail):
            self.run_action(params(**data), api)
        self.assertEqual(api.writes(), [])

    def test_deleted_connector_uuid_names_host_and_manual_migration_fix(self):
        data = declared_service()
        data['catalog']['vendor']['accounts']['main']['connection'] = {'type': 'manual'}
        data['bindings'][0]['kind'] = 'manual'
        data['hosts'][0]['binding']['uuid'] = SERVICE
        api = FakeAPI()
        with self.assertRaises(AnsibleActionFail) as exc:
            self.run_action(params(**data), api, check=True)
        message = exc.exception.result['public_error']
        self.assertIn('vendor-de-1 (vendor/main)', message)
        self.assertIn(SERVICE, message)
        self.assertIn('remove the old UUID', message)
        self.assertIn('infrastructure.billing.amount', message)
        self.assertEqual(api.writes(), [])

    def test_manual_migration_without_billing_explains_required_fields(self):
        data = declared_service()
        data['catalog']['vendor']['accounts']['main']['connection'] = {'type': 'manual'}
        data['bindings'][0]['kind'] = 'manual'
        api = FakeAPI()
        with self.assertRaises(AnsibleActionFail) as exc:
            self.run_action(params(**data), api, check=True)
        message = exc.exception.result['public_error']
        self.assertIn('vendor-de-1 (vendor/main)', message)
        self.assertIn('manual export needs verified infrastructure.billing.amount', message)
        self.assertEqual(api.writes(), [])

    def test_manual_account_requires_verified_billing_even_with_old_managed_record(self):
        data = declared_service()
        data['catalog']['vendor']['accounts']['main']['connection'] = {'type': 'manual'}
        data['bindings'][0]['kind'] = 'manual'
        api = FakeAPI(providers=[provider(kind='manual')], services=[managed_service()])
        with self.assertRaises(AnsibleActionFail) as exc:
            self.run_action(params(**data), api, check=True)
        self.assertIn('manual export needs verified', exc.exception.result['public_error'])
        self.assertEqual(api.writes(), [])

    def test_manual_migration_with_verified_billing_creates_without_sync(self):
        data = declared_service(has_billing=True)
        data['catalog']['vendor']['accounts']['main']['connection'] = {'type': 'manual'}
        data['bindings'][0]['kind'] = 'manual'
        api = FakeAPI()
        result = self.run_action(params(**data), api, check=True)
        self.assertEqual(result['counts'], {'creates': 2, 'updates': 0, 'syncs': 0})
        self.assertEqual(api.writes(), [])
        result = self.run_action(params(**data), api)
        self.assertEqual(result['counts'], {'creates': 2, 'updates': 0, 'syncs': 0})
        self.assertEqual([path for _, path, _ in api.writes()], ['/providers', '/services'])

    def test_kind_and_driver_conflicts_name_provider_and_do_not_write(self):
        data = declared_service(has_billing=True)
        data['bindings'][0]['kind'] = 'manual'
        api = FakeAPI()
        with self.assertRaises(AnsibleActionFail) as exc:
            self.run_action(params(**data), api, check=True)
        self.assertIn('Provider/account vendor/main', exc.exception.result['public_error'])
        self.assertIn('remove connection.driver', exc.exception.result['public_error'])
        self.assertEqual(api.writes(), [])

    def test_live_kind_mismatch_has_safe_public_diagnostic(self):
        api = FakeAPI(providers=[provider(kind='manual')])
        with self.assertRaises(AnsibleActionFail) as exc:
            self.run_action(params(**declared_service(has_billing=True)), api, check=True)
        self.assertIn('Provider vendor: live kind manual differs from binding kind billmgr',
                      exc.exception.result['public_error'])
        self.assertEqual(api.writes(), [])

    def test_raw_key_errors_are_never_promoted_to_public_diagnostic(self):
        api = FakeAPI()
        with patch.object(billing, 'project_model', side_effect=KeyError('PRIVATE-PASSWORD')):
            with self.assertRaises(AnsibleActionFail) as exc:
                self.run_action(params(), api)
        self.assertNotIn('PRIVATE', exc.exception.result['public_error'])
        self.assertIn('malformed data', exc.exception.result['public_error'])

    def test_empty_or_manual_only_server_is_noop(self):
        for providers in ([], [provider(kind='manual')]):
            api = FakeAPI(providers=providers)
            result = self.run_action(params(), api)
            self.assertFalse(result['changed'])
            self.assertEqual(api.writes(), [])


if __name__ == '__main__':
    unittest.main()
