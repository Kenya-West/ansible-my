#!/usr/bin/python
"""Controller-only infra-billing action. All operations are planned before writes."""
from ansible.plugins.action import ActionBase
from ansible.module_utils.urls import open_url
from ansible.errors import AnsibleActionFail
from pathlib import Path
import importlib.util
import json

# Ansible loads action plugins under generated module names, so a sibling
# package cannot rely on a normal relative import. Resolve it from this file
# without adding paths to ansible.cfg or modifying sys.path.
_model_spec = importlib.util.spec_from_file_location(
    '_infra_billing_model', Path(__file__).with_name('infra_billing_utils') / '__init__.py',
)
model = importlib.util.module_from_spec(_model_spec)
_model_spec.loader.exec_module(model)
SECRET_FLAGS = model.SECRET_FLAGS
delta = model.delta
project_model = model.project_model
effective_bindings = model.effective_bindings
require = model.require
require_create_credentials = model.require_create_credentials
unique_match = model.unique_match
url = model.url
_report_spec = importlib.util.spec_from_file_location(
    '_infra_billing_report', Path(__file__).with_name('infra_billing_utils') / 'report.py',
)
reporting = importlib.util.module_from_spec(_report_spec)
_report_spec.loader.exec_module(reporting)

DOCUMENTATION = r'''
module: infra_billing
short_description: Read or reconcile infrastructure records in infra-billing
description:
  - Plans additive provider, account and service updates without contacting Remnawave.
options:
  api_url:
    description: Base URL without the api suffix.
    type: str
    required: true
  token:
    description: Bearer API token.
    type: str
    required: true
  action:
    description: Read entities or reconcile explicitly declared data.
    type: str
    choices: [read, reconcile, resolve_bindings]
    default: read
  catalog:
    description: Consumer-independent private provider catalog.
    type: dict
    default: {}
  bindings:
    description: API provider and account bindings.
    type: list
    elements: dict
    default: []
  hosts:
    description: Related hosts and their service export settings.
    type: list
    elements: dict
    default: []
  domains:
    description: Independent domain data keyed by domain name, not Ansible hosts.
    type: dict
    default: {}
  domain_bindings:
    description: Domain export settings (enabled, project_uuid and optional service uuid).
    type: dict
    default: {}
  sync_all_accounts:
    description: Refresh every enabled non-manual account in infra-billing, including accounts absent from the catalog.
    type: bool
    default: false
  sync_missing_services:
    description: Import missing connector services through infra-billing account sync only when needed.
    type: bool
    default: true
  return_records:
    description: Return resolved provider/account/service UUIDs for host onboarding.
    type: bool
    default: false
  rotate_credentials:
    description: Replace existing account secrets on this run.
    type: bool
    default: false
  validate_certs:
    description: Validate TLS certificates.
    type: bool
    default: true
  timeout:
    description: HTTP timeout in seconds.
    type: int
    default: 30
  allow_http:
    description: Allow unencrypted HTTP for local tests only.
    type: bool
    default: false
attributes:
  check_mode:
    support: full
'''
EXAMPLES = r'''
- name: Read billing records
  infra_billing:
    api_url: https://billing.example.com
    token: "{{ vault_billing_token }}"
'''
RETURN = r'''
report:
  description: Credential-safe report with exactly one text line per counted API operation; render with native Ansible debug.
  type: dict
  returned: reconcile
counts:
  description: Number of planned or applied API requests (provider create includes its first account).
  type: dict
  returned: always
'''


def plan(model, providers, services, projects, rotate=False, allow_sync=False, accounts_only=False,
         sync_all_accounts=False):
    operations, account_ids = [], {}
    for index, entry in enumerate(model['providers']):
        current = unique_match(providers, entry['uuid'], name=entry['body']['name'])
        require(not current or current['kind'] == entry['kind'],
                'Provider ' + entry['key'] + ': live kind ' + str(current['kind'] if current else '')
                + ' differs from binding kind ' + entry['kind']
                + '; kind cannot be changed by reconciliation. Update the binding/adoption UUIDs '
                  'to the intended live provider; do not reuse deleted connector UUIDs')
        pref = '@provider:' + str(index)
        if current:
            pref = current['uuid']
            changes = delta(entry['body'], current)
            if changes:
                operations.append(('PATCH', '/providers/' + pref, changes, None))
            accounts = current['accounts']
        else:
            first = entry['accounts'][0]
            require_create_credentials(entry['kind'], first['body'],
                                       'Provider/account ' + '/'.join(first['key']) + ' (' + entry['kind'] + ')')
            body = dict(entry['body'], kind=entry['kind'], account=first['body'])
            if body['account'].get('label') is None:
                body['account'] = {k: v for k, v in body['account'].items() if k != 'label'}
            operations.append(('POST', '/providers', body, pref))
            accounts = []
        for n, account in enumerate(entry['accounts']):
            key = tuple(account['key'])
            aref = '@account:' + '/'.join(key)
            acurrent = unique_match(accounts, account['uuid'], label=account['body']['label'])
            if acurrent:
                account_ids[key] = acurrent['uuid']
                changes = delta(account['body'], acurrent)
                for secret, flag in SECRET_FLAGS.items():
                    # Secrets cannot be compared with GET. Existing credentials
                    # are only replaced by explicit rotation, never every run.
                    if secret in changes and not rotate and acurrent.get(flag) is not False:
                        del changes[secret]
                if changes:
                    operations.append(('PATCH', '/provider-accounts/' + acurrent['uuid'], changes, None))
            else:
                require(not account['uuid'], 'account UUID missing from its bound provider')
                require_create_credentials(entry['kind'], account['body'],
                                           'Provider/account ' + '/'.join(account['key']) + ' (' + entry['kind'] + ')')
                account_ids[key] = aref
                if current or n:
                    require(account['body']['label'] is not None, 'additional account needs a label')
                    operations.append(('POST', '/providers/' + pref + '/accounts', account['body'], aref))
                # First account is returned with POST /providers.
    if accounts_only:
        return operations
    account_kinds = {tuple(a['key']): p['kind'] for p in model['providers'] for a in p['accounts']}
    sync_operations, service_operations = [], []
    synced_accounts = set()

    def schedule_sync(aid):
        account = next((a for p in providers for a in p['accounts'] if a['uuid'] == aid), None)
        require(not account or account.get('isEnabled', True), 'Account sync is disabled; enable it explicitly before importing')
        if aid not in synced_accounts:
            sync_operations.append(('SYNC', '/provider-accounts/' + aid + '/sync', {}, None))
            synced_accounts.add(aid)

    if sync_all_accounts:
        # Live accounts are authoritative for refresh scope. Include accounts
        # with no inventory binding/services, plus accounts created by this plan.
        for provider in providers:
            if provider['kind'] != 'manual':
                for account in provider['accounts']:
                    if account.get('isEnabled', True):
                        schedule_sync(account['uuid'])
        for key, aid in account_ids.items():
            if aid.startswith('@account:') and account_kinds[key] != 'manual':
                schedule_sync(aid)
    desired_names = set()
    matched_services = set()
    for entry in model['services']:
        body = dict(entry['body'], accountUuid=account_ids[tuple(entry['account'])])
        require(any(p['uuid'] == body['projectUuid'] for p in projects), 'service project UUID not found')
        identity = (body['accountUuid'], body['name'])
        require(identity not in desired_names, 'duplicate service identity in desired data')
        desired_names.add(identity)
        if account_kinds[tuple(entry['account'])] == 'manual':
            require(entry.get('has_billing'),
                    'Host/service ' + entry['host'] + ' (' + '/'.join(entry['account'])
                    + '): manual export needs verified infrastructure.billing.amount, currency and interval '
                      '(for example {every: 1, unit: month}); connector billing cannot be recovered '
                      'from a deleted service. Supply verified billing before enabling this export')
        current = unique_match(services, entry['uuid'], accountUuid=body['accountUuid'], name=body['name'])
        if not current and entry.get('external_id'):
            current = unique_match(services, accountUuid=body['accountUuid'], externalId=str(entry['external_id']))
        if current:
            if entry.get('record_type') == 'domain':
                require(current.get('type') == 'domain', 'Domain identity matched a non-domain service; refusing adoption')
            require(current['uuid'] not in matched_services, 'multiple hosts match one service')
            matched_services.add(current['uuid'])
            require(current['accountUuid'] == body['accountUuid'], 'service belongs to a different account')
            require(entry.get('has_billing') or current.get('isManaged'),
                    'Service ' + entry['host'] + ': existing manual service needs verified infrastructure.billing')
            if current.get('isManaged'):
                # Preserve connector-owned price, dates, names and types. Adoption
                # may only annotate or assign its project, never override sync.
                body = {k: v for k, v in body.items() if k in ('description', 'projectUuid')}
            changes = delta(body, current)
            if changes:
                service_operations.append(('PATCH', '/services/' + current['uuid'], changes, None))
        else:
            if not entry.get('has_billing') or (sync_all_accounts and entry.get('external_id')
                                                and account_kinds[tuple(entry['account'])] != 'manual'):
                require((allow_sync or sync_all_accounts) and account_kinds[tuple(entry['account'])] != 'manual',
                        'Service ' + entry['host'] + ' (' + '/'.join(entry['account'])
                        + '): no connector service matched; a manual provider requires verified infrastructure.billing '
                        '(amount, currency, interval), or configure the actual API driver and credentials')
                require(entry.get('external_id'), 'First-run connector import requires infrastructure.service_id')
                schedule_sync(body['accountUuid'])
                continue
            service_operations.append(('POST', '/services', body, None))
    # Refresh after account creation/credential updates but before service
    # annotations, so connector metadata is never overwritten by stale billing.
    return operations + sync_operations + service_operations


def public_failure(prefix, exc):
    """Expose only intentional model validation messages, never raw Python/API errors."""
    message = reporting.single_line(prefix + str(exc)) if isinstance(exc, ValueError) else (
        prefix + 'malformed data or API response; check required fields and types')
    return AnsibleActionFail(message, result={'public_error': message})


def reconcile(p, check_mode=False):
    if p['action'] == 'resolve_bindings':
        return dict(changed=False, bindings=effective_bindings(p['catalog'], p['bindings'], p['hosts']))
    try:
        base = url(p['api_url'].rstrip('/'), 'api_url')
        require(base.startswith('https://') or p['allow_http'], 'HTTPS required (allow_http is only for local tests)')
        require(p['token'], 'token must not be empty')
        entries = p['hosts'] + model.domain_entries(p.get('domains', {}), p.get('domain_bindings', {}))
        projected = project_model(p['catalog'], p['bindings'], entries) if p['action'] == 'reconcile' else None
    except (ValueError, KeyError, TypeError) as exc:
        # Exception messages never include credentials or request bodies.
        raise public_failure('Invalid infrastructure data: ', exc) from None

    def request(method, path, body=None):
        try:
            response = open_url(base + '/api' + path, method=method,
                                data=json.dumps(body).encode() if body is not None else None,
                                headers={'Authorization': 'Bearer ' + p['token'], 'Content-Type': 'application/json'},
                                validate_certs=p['validate_certs'],
                                timeout=max(p['timeout'], 150) if path.endswith('/sync') else p['timeout'],
                                http_agent='ansible-httpget',
                                follow_redirects='none', unredirected_headers=['Authorization'])
            return json.loads(response.read())
        except Exception as exc:
            status = getattr(exc, 'code', None)
            message = 'infra-billing request failed: ' + method + ' ' + path
            if status is not None:
                message += ' (HTTP ' + str(status) + ')'
            raise AnsibleActionFail(message, result={'status': status, 'public_error': message}) from None

    providers, services, projects = [request('GET', '/' + kind) for kind in ('providers', 'services', 'projects')]
    if p['action'] == 'read':
        return dict(changed=False, gathered={'providers': providers, 'services': services, 'projects': projects}, counts={},
                    report={'mode': 'read-only', 'read': {'providers': len(providers),
                            'accounts': sum(len(row['accounts']) for row in providers),
                            'services': len(services), 'projects': len(projects)}})
    try:
        require(all(isinstance(v, list) for v in (providers, services, projects)), 'unexpected API list response')
        for entry in projected['services']:
            require(not entry['uuid'] or any(s.get('uuid') == entry['uuid'] for s in services),
                    'Host/service ' + entry['host'] + ' (' + '/'.join(entry['account'])
                    + '): infra_billing_service.uuid ' + str(entry['uuid'])
                    + ' no longer exists in infra-billing. After replacing/deleting a connector, '
                      'remove the old UUID or bind the intended live service UUID. '
                      'Manual replacement also needs verified infrastructure.billing.amount, currency and interval')
        operations = plan(projected, providers, services, projects, p['rotate_credentials'],
                          p.get('sync_missing_services', True), sync_all_accounts=p.get('sync_all_accounts', False))
    except (ValueError, KeyError, TypeError) as exc:
        raise public_failure('Cannot plan infra-billing reconciliation: ', exc) from None
    if not check_mode and p.get('sync_all_accounts') and any(op[0] == 'SYNC' for op in operations):
        # Re-plan service PATCHes against refreshed state, not the stale GET.
        # An imported service may now be managed or have changed billing data.
        operations = [op for op in operations if not (op[0] == 'PATCH' and op[1].startswith('/services/'))]
    counts = {'creates': sum(op[0] == 'POST' for op in operations),
              'updates': sum(op[0] == 'PATCH' for op in operations),
              'syncs': sum(op[0] == 'SYNC' for op in operations)}
    initial = {'providers': providers, 'services': services, 'projects': projects}
    all_operations = list(operations)
    resolved, sync_failures = {}, {}
    if not check_mode:
        for method, path, body, ref in operations:
            # Account placeholders contain '/' (provider/account), so replace
            # whole symbolic identifiers, not path segments. Longest first
            # prevents one identifier from being a prefix of another.
            for symbolic in sorted(resolved, key=len, reverse=True):
                path = path.replace(symbolic, resolved[symbolic])
            body = {k: resolved.get(v, v) if isinstance(v, str) else v for k, v in body.items()}
            if method == 'SYNC':
                aid = path.removeprefix('/provider-accounts/').removesuffix('/sync')
                try:
                    result = request('POST', path, body)
                    reason = reporting.sync_failure_reason(result)
                except AnsibleActionFail:
                    # A failed HTTP response/timeout can affect only this account.
                    # Never expose HTTP bodies or retry a possibly completed sync.
                    reason = 'infra-billing request failed'
                if reason:
                    if not p.get('sync_all_accounts'):
                        message = ('infra-billing account import failed for ' + aid
                                   + ': ' + reason + '; check its sync error in the UI')
                        raise AnsibleActionFail(message, result={'changed': True, 'public_error': message})
                    sync_failures[aid] = reason
                continue
            result = request(method, path, body)
            if ref:
                resolved[ref] = result['uuid']
                if ref.startswith('@provider:'):
                    index = int(ref.split(':')[1])
                    first = projected['providers'][index]['accounts'][0]
                    resolved['@account:' + '/'.join(first['key'])] = result['accounts'][0]['uuid']
    # Re-read refreshed/imported services and plan project/description updates
    # without allowing another sync or a manual fallback for missing imports.
    if not check_mode and counts['syncs']:
        providers, services = request('GET', '/providers'), request('GET', '/services')
        # Failed accounts must not adopt stale services or create a fallback.
        # Continue inventory annotations for the successfully refreshed accounts.
        account_ids = {}
        for entry in projected['providers']:
            current = unique_match(providers, entry['uuid'], name=entry['body']['name'])
            for account in entry['accounts']:
                row = unique_match(current['accounts'], account['uuid'], label=account['body']['label']) if current else None
                account_ids[tuple(account['key'])] = row['uuid'] if row else None
        followup_model = dict(projected, services=[entry for entry in projected['services']
                                                  if account_ids[tuple(entry['account'])] not in sync_failures])
        try:
            followup = plan(followup_model, providers, services, projects, False, False)
            require(all(op[0] == 'PATCH' for op in followup), 'Unexpected creation after connector import; refusing to duplicate services')
        except (ValueError, KeyError, TypeError) as exc:
            raise public_failure('Cannot reconcile refreshed infra-billing records: ', exc) from None
        for method, path, body, _ in followup:
            request(method, path, body)
        counts['updates'] += len(followup)
        all_operations.extend(followup)
    if not check_mode and operations:
        providers, services = request('GET', '/providers'), request('GET', '/services')
    report = reporting.build_report(projected, entries, initial,
                                    {'providers': providers, 'services': services, 'projects': projects},
                                    all_operations, check_mode, resolved, sync_failures)
    report['request_counts'] = counts
    output = dict(changed=bool(operations), counts=counts, report=report)
    if sync_failures:
        # Preserve the partial report for callers; onboarding must still fail
        # before saving local service UUIDs. The server role prints then fails.
        output.update(failed=True, sync_failed=len(sync_failures),
                      msg='infra-billing sync failed for ' + str(len(sync_failures))
                          + ' account(s); remaining accounts were attempted. Check failed accounts in the UI.')
        return output
    if p.get('return_records'):
        accounts, resolved_bindings = {}, []
        for entry in projected['providers']:
            current = unique_match(providers, entry['uuid'], name=entry['body']['name'])
            binding = {'uuid': current['uuid'] if current else None, 'accounts': {}}
            for account in entry['accounts']:
                acurrent = unique_match(current['accounts'], account['uuid'], label=account['body']['label']) if current else None
                accounts[tuple(account['key'])] = acurrent['uuid'] if acurrent else None
                binding['accounts'][account['key'][1]] = acurrent['uuid'] if acurrent else None
            resolved_bindings.append(binding)
        records = []
        for entry in projected['services']:
            account = accounts[tuple(entry['account'])]
            current = unique_match(services, entry['uuid'], accountUuid=account, name=entry['body']['name'])
            if not current and entry.get('external_id'):
                current = unique_match(services, accountUuid=account, externalId=str(entry['external_id']))
            require(check_mode or current is not None, 'Service was not found after reconciliation; local settings were not saved')
            records.append({'host': entry['host'], 'uuid': current['uuid'] if current else None,
                            'project_uuid': entry['body']['projectUuid']})
        output.update(records=records, resolved_bindings=resolved_bindings)
    return output


class ActionModule(ActionBase):
    """Controller-only action; no module transfer or SSH connection is needed."""

    TRANSFERS_FILES = False
    _requires_connection = False
    _supports_check_mode = True

    def run(self, tmp=None, task_vars=None):
        result = super().run(tmp, task_vars)
        # Protect credentials and private reads even if the caller omits no_log.
        self._task.no_log = True
        result['_ansible_no_log'] = True
        try:
            _, params = self.validate_argument_spec(argument_spec={
                'api_url': {'type': 'str', 'required': True},
                'token': {'type': 'str', 'required': True, 'no_log': True},
                'action': {'choices': ['read', 'reconcile', 'resolve_bindings'], 'default': 'read'},
                'catalog': {'type': 'dict', 'default': {}, 'no_log': True},
                'bindings': {'type': 'list', 'elements': 'dict', 'default': []},
                'hosts': {'type': 'list', 'elements': 'dict', 'default': []},
                'domains': {'type': 'dict', 'default': {}},
                'domain_bindings': {'type': 'dict', 'default': {}},
                'sync_all_accounts': {'type': 'bool', 'default': False},
                'sync_missing_services': {'type': 'bool', 'default': True},
                'return_records': {'type': 'bool', 'default': False},
                'rotate_credentials': {'type': 'bool', 'default': False},
                'validate_certs': {'type': 'bool', 'default': True},
                'allow_http': {'type': 'bool', 'default': False},
                'timeout': {'type': 'int', 'default': 30},
            })
            # Controller-side values carry Ansible provenance tags/subclasses.
            # Round-trip the JSON API data to plain Python types, just as the
            # former remote module's argument transport did (e.g. tagged ints).
            params = json.loads(json.dumps(params))
            result.update(reconcile(params, self._task.check_mode))
        except AnsibleActionFail as exc:
            result.update(exc.result)
            result.update(failed=True, msg=str(exc))
        except Exception:
            # Never expose request bodies, credentials or raw HTTP errors.
            message = 'infra-billing action failed; check required input fields and API compatibility (private details withheld)'
            result.update(failed=True, msg=message, public_error=message)
        return result
