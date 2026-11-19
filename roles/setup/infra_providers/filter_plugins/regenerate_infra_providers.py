"""Pure catalog import/merge helpers; no filesystem or network operations."""
import copy
import re
from ansible.errors import AnsibleFilterError


def _key(value):
    result = re.sub(r'[^a-z0-9]+', '-', value.lower()).strip('-')
    if not result:
        raise AnsibleFilterError('Provider name cannot form a stable key; supply provider_keys')
    return result


def _check_key(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', value):
        raise AnsibleFilterError('Provider/account keys must be stable lowercase identifiers')
    return value


def _check_catalog(catalog):
    if not isinstance(catalog, dict):
        raise AnsibleFilterError('Provider definitions must be a mapping')
    for key, provider in catalog.items():
        _check_key(key)
        if not isinstance(provider, dict) or not provider.get('name'):
            raise AnsibleFilterError('Every provider definition needs a name and accounts')
        if 'todo' in provider.get('sources', {}):
            raise AnsibleFilterError('Provider catalog cannot hold To Do reminders; use verified service billing/policy fields')
        accounts = provider.get('accounts')
        if not isinstance(accounts, dict) or not accounts:
            raise AnsibleFilterError('Every provider definition needs an accounts mapping')
        for aid, account in accounts.items():
            _check_key(aid)
            if not isinstance(account, dict):
                raise AnsibleFilterError('Provider accounts must be mappings')


def _merge_missing(existing, incoming):
    """Existing data wins, including empty strings/lists and template references."""
    out = copy.deepcopy(existing)
    for key, value in incoming.items():
        if key not in out:
            out[key] = copy.deepcopy(value)
        elif isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _merge_missing(out[key], value)
    return out


def _merge_declared(existing, incoming):
    """Host declarations are authoritative, but conflicting hosts must fail."""
    out = copy.deepcopy(existing)
    for key, value in incoming.items():
        if key not in out:
            out[key] = copy.deepcopy(value)
        elif isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _merge_declared(out[key], value)
        elif out[key] != value:
            # Never include values (which might be passwords) in exceptions.
            raise AnsibleFilterError('Conflicting host provider definitions; give the accounts distinct keys or reconcile the declarations')
    return out


def _overlay(existing, declared):
    out = copy.deepcopy(existing)
    for key, value in declared.items():
        if isinstance(out.get(key), dict) and isinstance(value, dict):
            out[key] = _overlay(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _identities(catalog):
    """Known infra-billing identity of every catalog account.

    Mirrors the reconcile model: an account-level infra_billing.provider replaces
    the provider-level default; name defaults to the catalog name, label to the key.
    """
    rows = []
    for key, provider in catalog.items():
        for aid, account in provider.get('accounts', {}).items():
            own = account.get('infra_billing') or {}
            ident = own['provider'] if 'provider' in own else provider.get('infra_billing') or {}
            rows.append({'key': key, 'aid': aid, 'provider_uuid': ident.get('uuid'),
                         'provider_name': ident.get('name', provider['name']),
                         'uuid': own.get('uuid'), 'label': own.get('label', aid),
                         'declared': bool(account.get('infra_billing') or provider.get('infra_billing'))})
    return rows


def regenerate_catalog(document, entries):
    if not isinstance(document, dict):
        raise AnsibleFilterError('Existing provider file must be a YAML mapping, not an encrypted vault or scalar')
    existing = document.get('infra_providers', {})
    if existing:
        _check_catalog(existing)
    if not isinstance(existing, dict):
        raise AnsibleFilterError('Existing infra_providers must be a mapping')
    imported, declared = {}, {}
    # Build imports separately: existing fields always win over API hints,
    # explicit host declarations win over both. Unrelated YAML keys survive.
    for entry in entries:
        if entry['kind'] == 'host_vars':
            _check_catalog(entry['data'])
            declared = _merge_declared(declared, entry['data'])
    identities = {}
    # Catalog infra_billing identities decide which stable key/account an API
    # provider belongs to (e.g. two API providers split across one vendor key).
    known = _overlay(existing, declared)
    _check_catalog(known)
    known_rows = _identities(known)
    # API-account sources precede account-less panels regardless of host order.
    api_entries = sorted((e for e in entries if e['kind'] != 'host_vars'),
                         key=lambda e: e['kind'] == 'remnawave')
    for entry in api_entries:
        kind = entry['kind']
        data = entry['data']
        if not isinstance(data, list):
            raise AnsibleFilterError('Provider API must return a list')
        key_map = entry.get('provider_keys', {})
        account_map = entry.get('account_keys', {})
        for p in data:
            uuid, name = p['uuid'], p['name']
            rows = [r for r in known_rows if r['provider_uuid'] == uuid
                    or (not r['provider_uuid'] and r['provider_name'] == name)] if kind == 'infra_billing' else []
            if len({r['key'] for r in rows}) > 1:
                raise AnsibleFilterError('Ambiguous catalog infra_billing identity during import; give the providers distinct infra_billing names/UUIDs')
            key = _check_key(key_map.get(uuid, key_map.get(name, rows[0]['key'] if rows else _key(name))))
            # Names which sanitize to the same key must not be conflated. An
            # explicit key map/catalog identity authorizes multi-account grouping.
            explicit = uuid in key_map or name in key_map or bool(rows)
            identity = (kind, entry['host'], key)
            if identity in identities and not explicit:
                raise AnsibleFilterError('Provider names collide after key normalization; supply provider_keys')
            identities[identity] = uuid
            # Pre-scan explicit host declarations and API accounts, so panel
            # metadata never invents main merely because that source came first.
            provider = {'name': name, 'accounts': {}}
            if p.get('loginUrl'):
                provider['login_url'] = p['loginUrl']
            if p.get('faviconLink'):
                provider['favicon_link'] = p['faviconLink']
            if kind == 'remnawave':
                # Remnawave has no accounts or API connector information. Do
                # not invent an account beside already-known real accounts.
                known = _merge_missing(_merge_missing(existing, imported), declared).get(key, {}).get('accounts', {})
                provider['accounts'] = {} if known else {'main': {'connection': {'type': 'manual'}}}
            elif kind == 'infra_billing':
                for a in p['accounts']:
                    matches = [r['aid'] for r in rows if r['key'] == key and (
                        r['uuid'] == a['uuid'] or (not r['uuid'] and r['label'] == a['label']))]
                    if len(matches) > 1:
                        raise AnsibleFilterError('Ambiguous catalog account identity during import')
                    aid = _check_key(account_map.get(a['uuid'], matches[0] if matches else _key(a['label'] or 'main')))
                    connection = {'type': 'manual' if p['kind'] == 'manual' else 'api'}
                    if p['kind'] != 'manual':
                        connection['driver'] = p['kind']
                    if a.get('baseUrl'):
                        connection['api_url'] = a['baseUrl']
                    account = {'connection': connection}
                    if 'isPostpaid' in a:
                        account['postpaid'] = a['isPostpaid']
                    # Record the live identity only where the catalog declares
                    # none; declared names/UUIDs always win over the API.
                    if not any(r['declared'] for r in known_rows if (r['key'], r['aid']) == (key, aid)):
                        account['infra_billing'] = {'provider': {'uuid': uuid, 'name': name},
                                                    'uuid': a['uuid'], 'label': a['label']}
                    accounts = provider['accounts']
                    if aid in accounts:
                        raise AnsibleFilterError('Imported account keys collide; supply account_keys')
                    accounts[aid] = account
            else:
                raise AnsibleFilterError('Unsupported provider import source')
            imported = _merge_missing(imported, {key: provider})
    generated = _overlay(_merge_missing(existing, imported), declared)
    _check_catalog(generated)
    result = copy.deepcopy(document)
    result['infra_providers'] = dict(sorted(generated.items()))
    return result


class FilterModule:
    def filters(self):
        return {'regenerate_infra_providers': regenerate_catalog}
