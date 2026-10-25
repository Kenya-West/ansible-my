"""Consumer-independent infrastructure data validation and infra-billing projection.

No network access here. Money uses Decimal; arbitrary calendar intervals are never
silently treated as 30-day months. API-specific settings live in bindings only.
"""
import json
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit


KINDS = set('timeweb hetzner hostkey netcup hostbill billmgr selectel 4vps netlen beget porkbun spaceship vultr linode aeza vdsina cloudflare stormwall yandex doubleservers openrouter manual'.split())
CREDENTIALS = {
    'token': 'token', 'username': 'username', 'password': 'password',
    'totp_secret': 'totpSecret', 'api_password': 'apiPassword',
    'secret_key': 'secretKey', 'account_id': 'accountId',
    'project_name': 'projectName', 'panel_id': 'panelId',
}
SECRET_FLAGS = {'token': 'hasToken', 'password': 'hasPassword',
                'totpSecret': 'hasTotpSecret', 'apiPassword': 'hasApiPassword',
                'secretKey': 'hasSecretKey'}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def url(value, label):
    p = urlsplit(value)
    require(p.scheme in ('https', 'http') and p.netloc and not p.username and not p.password,
            label + ' must be an HTTP(S) URL without embedded credentials')
    return value


def identifier(value, label):
    require(isinstance(value, str) and re.fullmatch(r'[a-z0-9][a-z0-9_-]*', value),
            label + ' must be a stable lowercase identifier')


def api_uuid(value):
    from uuid import UUID
    try:
        require(isinstance(value, str), 'API UUID must be a string')
        UUID(value)
    except (ValueError, AttributeError):
        raise ValueError('invalid API UUID') from None
    return value


def validate_catalog(catalog):
    require(isinstance(catalog, dict), 'infra_providers must be a mapping')
    for key, provider in catalog.items():
        identifier(key, 'provider key')
        require(isinstance(provider, dict) and provider.get('name'), key + ' needs a name')
        for field in ('website', 'login_url'):
            if provider.get(field):
                url(provider[field], key + '.' + field)
        require('todo' not in provider.get('sources', {}),
                'Provider catalog must not contain To Do reminders; use verified service billing/policy fields')
        accounts = provider.get('accounts', {})
        require(isinstance(accounts, dict) and accounts, key + ' needs accounts')
        for aid, account in accounts.items():
            identifier(aid, 'account key')
            require(isinstance(account, dict), 'account must be a mapping')
            connection = account.get('connection', {'type': 'manual'})
            require(connection.get('type') in ('api', 'manual', 'bot', 'web'),
                    'connection.type must be api, manual, bot or web')
            if connection.get('driver'):
                require(connection['driver'] in KINDS - {'manual'}, 'unsupported API connection.driver')
                require(connection.get('type') == 'api', 'connection.driver requires type: api')
            if connection.get('api_url'):
                url(connection['api_url'], 'connection.api_url')
            require(isinstance(connection.get('credentials', {}), dict), 'credentials must be a mapping')
    return catalog


def billing_projection(billing):
    require(isinstance(billing, dict), 'billing must be a mapping')
    try:
        amount = Decimal(str(billing['amount']))
    except (KeyError, InvalidOperation):
        raise ValueError('billing.amount must be a decimal amount, not an unknown value') from None
    require(amount.is_finite() and amount >= 0, 'billing.amount must be finite and nonnegative')
    currency = billing.get('currency', '')
    require(isinstance(currency, str) and re.fullmatch('[A-Z]{3,4}', currency), 'API billing.currency must be 3 or 4 uppercase letters')
    interval = billing.get('interval', {})
    require(amount.as_tuple().exponent >= -2, 'billing.amount must have at most two decimal places')
    require(amount < Decimal('1000000000000'), 'billing.amount exceeds infra-billing NUMERIC(14,2)')
    require(isinstance(interval, dict), 'billing.interval must be a mapping')
    every, unit = interval.get('every'), interval.get('unit')
    require(type(every) is int and every > 0, 'interval.every must be a positive integer')
    require(unit in ('hour', 'day', 'month', 'year', 'once'), 'unsupported interval.unit')
    exact = {(1, 'hour'): 'hourly', (1, 'day'): 'daily', (1, 'month'): 'monthly',
             (3, 'month'): 'quarterly', (1, 'year'): 'yearly', (1, 'once'): 'onetime'}
    period = exact.get((every, unit))
    require(period is not None,
            'Supported billing intervals: 1 hour, 1 day, 1 month, 3 months, 1 year or 1 once')
    out = {'cost': format(amount, '.2f'),
           'currency': currency, 'period': period}
    if 'next_due_at' in billing:
        stamp = billing['next_due_at']
        require(isinstance(stamp, str) and re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)', stamp),
                'next_due_at must be a quoted ISO timestamp with timezone')
        from datetime import datetime
        datetime.fromisoformat(stamp.replace('Z', '+00:00'))
        out['nextBillingAt'] = stamp
    return out


def account_payload(account, binding):
    connection = account.get('connection', {})
    out = {}
    if 'label' in binding:
        out['label'] = binding['label']
        require(out['label'] is None or isinstance(out['label'], str) and 0 < len(out['label']) <= 64,
                'account label must be null or 1..64 characters')
    if 'postpaid' in account:
        require(type(account['postpaid']) is bool, 'postpaid must be boolean')
        out['isPostpaid'] = account['postpaid']
    if connection.get('api_url'):
        out['baseUrl'] = connection['api_url']
    creds = connection.get('credentials', {})
    require(not set(creds) - set(CREDENTIALS), 'unsupported credential key; extend the adapter explicitly')
    for key, value in creds.items():
        require(isinstance(value, str) and value, 'credentials must be nonempty strings')
        out[CREDENTIALS[key]] = value
    return out


def require_create_credentials(kind, body, context='new API account'):
    required = {
        'manual': (), 'billmgr': ('baseUrl', 'username', 'password'),
        'hostbill': ('baseUrl', 'username', 'password'),
        'beget': ('username', 'password'), 'doubleservers': ('username', 'password'),
        'selectel': ('accountId', 'username', 'password'),
        'porkbun': ('token', 'secretKey'), 'spaceship': ('token', 'secretKey'),
        '4vps': ('panelId', 'token'),
    }.get(kind, ('token',))
    missing = [field for field in required if not body.get(field)]
    require(not missing, context + ' needs creation credentials/settings: ' + ', '.join(missing)
            + '; supply them in the private provider catalog (existing secrets are never revealed)')


def effective_bindings(catalog, bindings, hosts):
    """Explicit API identities win; derive missing bindings from declared drivers.

    Never infer BILLmanager from a URL, a provider name, or a prior API record.
    Limit automatic bindings to accounts actually referenced by this run's hosts.
    """
    validate_catalog(catalog)
    require(isinstance(bindings, list), 'provider bindings must be a list')
    result = list(bindings)
    missing = {}
    for host in hosts:
        infra = host['infrastructure']
        key, aid = infra.get('provider'), infra.get('account')
        require(key in catalog and aid in catalog[key]['accounts'],
                host['name'] + ' refers to an unknown infrastructure provider/account')
        if not host.get('binding', {}).get('enabled', False):
            continue
        matches = [b for b in result if b['provider'] == key and aid in b.get('accounts', {})]
        require(len(matches) <= 1, 'account bound to multiple API providers')
        if matches:
            continue
        connection = catalog[key]['accounts'][aid].get('connection', {'type': 'manual'})
        driver = connection.get('driver')
        if connection.get('type') == 'api':
            require(driver, f"Host '{host['name']}' references unbound API account '{key}/{aid}': "
                    'declare accounts.<account>.connection.driver in the billing server provider catalog '
                    '(for example billmgr), or set kind in its explicit provider binding')
        else:
            driver = 'manual'
        group = (key, driver)
        if group not in missing:
            # Connector kind is immutable. Avoid splitting an existing explicit
            # identity implicitly: user must declare that account's binding.
            require(not any(b['provider'] == key for b in bindings),
                    'Provider has explicit bindings; add this account to the intended binding')
            missing[group] = {'provider': key, 'kind': driver, 'accounts': {}}
            result.append(missing[group])
        missing[group]['accounts'][aid] = {'label': aid}
    return result


def domain_entries(domains, bindings):
    """Domain services are independent records, never inventory hosts."""
    require(isinstance(domains, dict) and isinstance(bindings, dict), 'Domain data and bindings must be mappings')
    require(not set(bindings) - set(domains), 'Domain binding references an unknown domain')
    entries = []
    for name, data in domains.items():
        require(isinstance(name, str) and re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63}', name),
                'Domain keys must be lowercase fully qualified domain names (use punycode for IDNs)')
        require(isinstance(data, dict), 'Domain entry must be a mapping')
        # Convert only at the API boundary; the stored domain has no host
        # relation, country code, or inventory hostname.
        infra = dict(data, type='domain', service_id=name)
        binding = dict(bindings.get(name, {}), name=name)
        entries.append({'name': name, 'infrastructure': infra, 'binding': binding})
    return entries


def project_model(catalog, bindings, hosts):
    bindings = effective_bindings(catalog, bindings, hosts)
    providers, account_refs, identities = [], {}, set()
    for binding in bindings:
        key = binding['provider']
        require(key in catalog, 'binding refers to unknown provider ' + key)
        p = catalog[key]
        name = binding.get('name', p['name'])
        kind = binding.get('kind')
        if kind is None:
            drivers = set()
            for aid in binding.get('accounts', {}):
                require(aid in p['accounts'], 'binding refers to unknown account ' + aid)
                connection = p['accounts'][aid].get('connection', {'type': 'manual'})
                driver = connection.get('driver') if connection.get('type') == 'api' else 'manual'
                require(driver, 'API provider binding needs kind or declared connection.driver')
                drivers.add(driver)
            require(len(drivers) == 1, 'Binding accounts must share one connector driver')
            kind = next(iter(drivers))
        require(kind in KINDS, 'unsupported infra-billing connector kind')
        if binding.get('uuid'):
            api_uuid(binding['uuid'])
        identity = binding.get('uuid') or name
        require(identity not in identities, 'duplicate provider binding')
        identities.add(identity)
        body = {'name': name}
        if p.get('login_url'):
            body['loginUrl'] = p['login_url']
        entries = []
        require(isinstance(binding.get('accounts'), dict) and binding['accounts'], 'binding needs accounts')
        labels = set()
        for aid, ab in binding['accounts'].items():
            require(aid in p['accounts'], 'binding refers to unknown account ' + aid)
            connection = p['accounts'][aid].get('connection', {})
            require(not connection.get('driver') or connection['driver'] == kind,
                    'Binding kind conflicts with declared connection.driver')
            ref = (key, aid)
            require(ref not in account_refs, 'account bound to multiple API providers')
            payload = account_payload(p['accounts'][aid], ab)
            label = payload.get('label', aid)
            canonical = label.casefold() if label else None
            require(canonical not in labels, 'duplicate account label')
            labels.add(canonical)
            payload['label'] = label
            if kind == 'manual':
                payload = {k: v for k, v in payload.items() if k in ('label', 'isPostpaid')}
            if ab.get('uuid'):
                api_uuid(ab['uuid'])
            entry = {'key': ref, 'uuid': ab.get('uuid'), 'body': payload}
            entries.append(entry)
            account_refs[ref] = entry
        providers.append({'key': key, 'uuid': binding.get('uuid'), 'kind': kind, 'body': body, 'accounts': entries})
    services = []
    for host in hosts:
        infra = host['infrastructure']
        ref = (infra.get('provider'), infra.get('account'))
        require(ref[0] in catalog and ref[1] in catalog[ref[0]]['accounts'],
                host['name'] + ' refers to an unknown infrastructure provider/account')
        projection = billing_projection(infra['billing']) if 'billing' in infra else None
        # A reference alone is useful data but does not authorize billing exports.
        export = host.get('binding', {})
        if not export.get('enabled', False):
            continue
        require(ref in account_refs, 'exported host account has no provider binding')
        require(export.get('project_uuid'), 'exported host needs project_uuid')
        api_uuid(export['project_uuid'])
        if export.get('uuid'):
            api_uuid(export['uuid'])
        body = {'name': export.get('name', host['name']), 'type': infra.get('type', 'vps'),
                'projectUuid': export['project_uuid']}
        require(isinstance(body['type'], str) and 0 < len(body['type']) <= 40, 'invalid service type')
        if projection is not None:
            body.update(projection)
        # Runtime host metadata is collected separately from the stored data.
        # Never read infrastructure.country_code: country_code is already an
        # inventory variable and can be overridden independently of billing.
        country = host.get('country_code')
        if country:
            require(isinstance(country, str) and re.fullmatch('[A-Z]{2}', country), 'invalid runtime country_code')
            body['countryCode'] = country
        if 'active' in infra:
            require(type(infra['active']) is bool, 'active must be boolean')
            body['isActive'] = infra['active']
        # Keep original amount, interval, URLs and top-up/reminder policy in the only
        # free-text field accepted by this API. Do not leak credentials into it.
        note = {k: infra[k] for k in ('billing', 'service_id', 'service_url', 'notes') if k in infra}
        if infra.get('type') == 'domain' and note.get('service_id') == host['name']:
            # Domain name is already the API identity, not an owner note.
            note.pop('service_id')
        if note:
            body['description'] = json.dumps(note, ensure_ascii=False, separators=(',', ':'), default=str)
            require(len(body['description']) <= 500, 'service description exceeds API limit (500 characters)')
        services.append({'host': host['name'], 'account': ref, 'uuid': export.get('uuid'),
                         'record_type': 'domain' if infra.get('type') == 'domain' else 'host',
                         'has_billing': projection is not None,
                         'external_id': infra.get('service_id'), 'body': body})
    return {'providers': providers, 'services': services}


def same(field, left, right):
    if field == 'cost':
        return Decimal(str(left)) == Decimal(str(right))
    if field == 'nextBillingAt' and left and right:
        from datetime import datetime
        return datetime.fromisoformat(left.replace('Z', '+00:00')) == datetime.fromisoformat(right.replace('Z', '+00:00'))
    return left == right


def delta(body, current):
    return {k: v for k, v in body.items() if not same(k, current.get(k), v)}


def unique_match(items, uuid=None, **fields):
    matches = [i for i in items if i.get('uuid') == uuid] if uuid else [
        i for i in items if all(i.get(k) == v for k, v in fields.items())]
    require(len(matches) <= 1, 'ambiguous API identity; supply an explicit UUID')
    require(not uuid or matches, 'explicit API UUID not found; refusing to create a replacement')
    return matches[0] if matches else None
