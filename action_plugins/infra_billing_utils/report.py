"""Compact, credential-safe report: exactly one line per counted API operation."""


def match(items, uuid=None, **fields):
    matches = [row for row in items if row.get('uuid') == uuid] if uuid else [
        row for row in items if all(row.get(k) == value for k, value in fields.items())]
    return matches[0] if len(matches) == 1 else None


def single_line(value):
    # User-supplied names must not turn one operation into several output lines.
    return ' '.join(str(value).split())


def sync_failure_reason(result):
    """Classify failures using fixed text only; connector errors may embed secrets."""
    if not isinstance(result, dict) or result.get('status') not in ('ok', 'error'):
        return 'unexpected sync response'
    if result['status'] == 'ok':
        return None
    error = str(result.get('error') or '').lower()
    if any(word in error for word in ('401', '403', 'unauthorized', 'forbidden', 'authentication', 'permission')):
        return 'connector authentication/permission failure'
    if any(word in error for word in ('timeout', 'timed out', 'canceled')):
        return 'connector timeout'
    if any(word in error for word in ('no api token', 'credentials')):
        return 'missing connector credentials'
    return 'connector error'


def build_report(projected, entries, before, after, operations, check_mode, resolved=None, sync_failures=None):
    resolved = resolved or {}
    sync_failures = sync_failures or {}
    providers, accounts, services = {}, {}, {}
    # Full refresh includes live accounts not represented by inventory bindings.
    # Report their public provider name/label, never credential hints or bodies.
    for provider in before['providers'] + after['providers']:
        providers[provider['uuid']] = provider['name']
        for account in provider['accounts']:
            accounts[account['uuid']] = provider['name'] + ('/' + account['label'] if account.get('label') else '')
    for index, provider in enumerate(projected['providers']):
        current = match(before['providers'], provider['uuid'], name=provider['body']['name'])
        latest = match(after['providers'], provider['uuid'], name=provider['body']['name'])
        identity = f"{provider['key']} ({provider['kind']})"
        for ref in [f'@provider:{index}', (current or {}).get('uuid'), (latest or {}).get('uuid')]:
            if ref:
                providers[ref] = identity
        for account in provider['accounts']:
            old = match(current['accounts'], account['uuid'], label=account['body']['label']) if current else None
            new = match(latest['accounts'], account['uuid'], label=account['body']['label']) if latest else None
            identity = '/'.join(account['key'])
            for ref in ['@account:' + identity, (old or {}).get('uuid'), (new or {}).get('uuid')]:
                if ref:
                    accounts[ref] = identity
    for service in projected['services']:
        for row in before['services'] + after['services']:
            account = accounts.get(row.get('accountUuid'))
            if row.get('uuid') == service['uuid'] or (
                account == '/'.join(service['account']) and (
                    row.get('name') == service['body']['name'] or
                    service.get('external_id') and row.get('externalId') == str(service['external_id']))
            ):
                services[row['uuid']] = service

    lines = []
    for method, path, body, ref in operations:
        for symbolic in sorted(resolved, key=len, reverse=True):
            path = path.replace(symbolic, resolved[symbolic])
        if method == 'POST' and path == '/providers':
            target = providers.get(ref, body.get('name', 'provider'))
            detail = 'provider ' + target + ' (includes first account)'
        elif path.startswith('/provider-accounts/'):
            aid = path.removeprefix('/provider-accounts/').removesuffix('/sync')
            target = accounts.get(aid, aid)
            detail = 'account ' + target
            if method == 'SYNC':
                detail += ' (account-wide connector refresh/import)'
                if aid in sync_failures:
                    detail += ' [FAILED: ' + sync_failures[aid] + '; check account sync error in the UI]'
        elif path.startswith('/providers/') and path.endswith('/accounts'):
            target = accounts.get(ref, ref or body.get('label', 'account'))
            detail = 'account ' + target
        elif path.startswith('/providers/'):
            pid = path.removeprefix('/providers/')
            detail = 'provider ' + providers.get(pid, pid)
        else:
            service = services.get(path.removeprefix('/services/')) if method == 'PATCH' else None
            entity = 'domain' if (service or {}).get('record_type') == 'domain' or body.get('type') == 'domain' else 'service'
            detail = entity + ' ' + ((service or {}).get('host') or body.get('name') or path.removeprefix('/services/'))
        if method == 'PATCH':
            # Field names only: credential values/free-text never enter output.
            detail += ' [fields: ' + ', '.join(sorted(body)) + ']'
        verb = {'POST': 'CREATE', 'PATCH': 'UPDATE', 'SYNC': 'SYNC'}[method]
        lines.append(single_line(verb + ' ' + detail))
    mode = 'check (planned, no API writes; connector health not tested)' if check_mode else (
        'apply (partial failure)' if sync_failures else 'apply (completed)')
    return {'mode': mode, 'lines': lines}
