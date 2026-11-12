#!/usr/bin/python
"""Controller-only, pull-only sync: infra-billing -> existing host_vars files.

Never creates or deletes files, never contacts the network, never adds keys.
It only rewrites the value text of keys that already exist in a host's own
infrastructure file, keeping comments, quoting and layout. Supports --check and
--diff (nothing is written in check mode).
"""
from ansible.plugins.action import ActionBase
from ansible.utils.display import Display
from decimal import Decimal, InvalidOperation
from datetime import datetime
import difflib
import json
import os
import re

import yaml

display = Display()

DOCUMENTATION = r'''
module: infra_billing_pull
short_description: Pull infra-billing service data into existing host_vars files
description:
  - Matches billing services to inventory hosts and updates only values that already exist in each host file.
options:
  services:
    description: Services returned by the infra_billing read action.
    type: list
    elements: dict
    required: true
  hosts:
    description: List of {name, file}; file is the host's infrastructure YAML.
    type: list
    elements: dict
    required: true
attributes:
  check_mode:
    support: full
  diff_mode:
    support: full
'''

PERIODS = {'hourly': (1, 'hour'), 'daily': (1, 'day'), 'monthly': (1, 'month'),
           'quarterly': (3, 'month'), 'yearly': (1, 'year'), 'onetime': (1, 'once')}
KEY_LINE = r'^(?P<indent>[ ]*)(?P<key>{key})(?P<colon>[ ]*:[ ]*)(?P<value>.*)$'


def stamp(value):
    return datetime.fromisoformat(str(value).replace('Z', '+00:00'))


def equal(kind, old, new):
    try:
        if kind == 'amount':
            return Decimal(str(old)) == Decimal(str(new))
        if kind == 'time':
            return stamp(old) == stamp(new)
    except (InvalidOperation, ValueError, TypeError):
        return False
    return old == new


def desired_values(service):
    """Billing-owned fields as {(path...): (kind, value)}; absent/null API values are skipped."""
    out, warnings = {}, []
    if service.get('cost') is not None:
        try:
            out[('infrastructure', 'billing', 'amount')] = ('amount', format(Decimal(str(service['cost'])), 'f'))
        except InvalidOperation:
            warnings.append('unparseable cost')
    if service.get('currency'):
        out[('infrastructure', 'billing', 'currency')] = ('text', service['currency'])
    if service.get('period') in PERIODS:
        every, unit = PERIODS[service['period']]
        out[('infrastructure', 'billing', 'interval', 'every')] = ('int', every)
        out[('infrastructure', 'billing', 'interval', 'unit')] = ('text', unit)
    elif service.get('period'):
        warnings.append('unsupported period ' + str(service['period']))
    if service.get('nextBillingAt'):
        out[('infrastructure', 'billing', 'next_due_at')] = ('time', service['nextBillingAt'])
    if service.get('projectUuid'):
        out[('infra_billing_service', 'project_uuid')] = ('text', service['projectUuid'])
    if service.get('uuid'):
        out[('infra_billing_service', 'uuid')] = ('text', service['uuid'])
    return out, warnings


def lookup(document, path):
    node = document
    for part in path:
        if not isinstance(node, dict) or part not in node:
            return False, None
        node = node[part]
    return True, node


def find_line(lines, path):
    """Index of the `key:` line for a nested block-mapping path, or None."""
    start, end, indent = 0, len(lines), -1
    index = None
    for part in path:
        pattern = re.compile(KEY_LINE.format(key=re.escape(part) + '|"' + re.escape(part) + '"|\'' + re.escape(part) + "'"))
        index, child_indent = None, None
        for i in range(start, end):
            line = lines[i]
            if not line.strip() or line.lstrip().startswith('#'):
                continue
            width = len(line) - len(line.lstrip(' '))
            if width <= indent:
                break  # left the parent block
            if child_indent is None:
                child_indent = width
            if width != child_indent:
                continue
            match = pattern.match(line.rstrip('\n'))
            if match:
                index = i
                break
        if index is None:
            return None
        indent = len(lines[index]) - len(lines[index].lstrip(' '))
        start = index + 1
    return index


def render(kind, value, original):
    """New value text, keeping the original quote style (comments handled by caller)."""
    text = str(value)
    quote = original[:1] if original[:1] in ('"', "'") else ''
    if kind == 'int':
        return text
    if quote:
        return quote + text + quote
    if kind in ('amount', 'time'):
        return '"' + text + '"'  # unquoted would change YAML type
    return text


def split_value(raw):
    """Split `value  # comment` into (value, trailing) honouring simple quotes."""
    raw = raw.rstrip()
    if raw[:1] in ('"', "'"):
        close = raw.find(raw[0], 1)
        if close == -1:
            return None, ''
        return raw[:close + 1], raw[close + 1:]
    match = re.match(r'^(.*?)([ ]+#.*)?$', raw)
    return match.group(1), match.group(2) or ''


def process_host(entry, services, claimed, check_mode):
    name, path = entry['name'], entry['file']
    report = {'host': name, 'file': path, 'changes': [], 'status': 'unchanged'}

    def skip(reason):
        report.update(status='skipped', reason=reason)
        return report, None, None

    if not path or os.path.islink(path) or not os.path.isfile(path):
        return skip('host file does not exist (or is a symlink); never created')
    try:
        with open(path, encoding='utf-8') as handle:
            original = handle.read()
    except (OSError, UnicodeDecodeError):
        return skip('host file is unreadable')
    if original.startswith('$ANSIBLE_VAULT'):
        return skip('host file is vault-encrypted')
    try:
        document = yaml.safe_load(original) or {}
    except yaml.YAMLError:
        return skip('host file is not valid YAML')
    if not isinstance(document, dict) or not isinstance(document.get('infrastructure'), dict):
        return skip('no infrastructure mapping in host file')

    infra = document['infrastructure']
    binding = document.get('infra_billing_service') or {}
    candidates, how = [], ''
    if binding.get('uuid'):
        candidates = [s for s in services if s.get('uuid') == binding['uuid']]
        how = 'uuid'
        if not candidates:
            return skip('infra_billing_service.uuid not found in infra-billing; not guessing another service')
    if not candidates and infra.get('service_id') not in (None, ''):
        candidates = [s for s in services if str(s.get('externalId', '')) == str(infra['service_id'])]
        how = 'service_id'
    if not candidates:
        candidates = [s for s in services if s.get('name') == binding.get('name', name)]
        how = 'name'
    if not candidates:
        return skip('no matching service in infra-billing')
    if len(candidates) > 1:
        return skip('ambiguous: ' + str(len(candidates)) + ' services match by ' + how)
    service = candidates[0]
    if service['uuid'] in claimed:
        return skip('service ' + service['uuid'] + ' is already matched to ' + claimed[service['uuid']])
    claimed[service['uuid']] = name
    report['service'] = service['uuid']
    report['matched_by'] = how

    wanted, warnings = desired_values(service)
    report['warnings'] = warnings
    lines = original.splitlines(keepends=True)
    for key_path, (kind, new) in wanted.items():
        present, current = lookup(document, key_path)
        label = '.'.join(key_path)
        if not present:
            continue  # pull never adds keys
        if equal(kind, current, new):
            continue
        index = find_line(lines, key_path)
        if index is None:
            warnings.append(label + ': layout not editable in place (flow style or anchor); skipped')
            continue
        line = lines[index]
        match = re.match(KEY_LINE.format(key='.+?'), line.rstrip('\n'))
        value, trailing = split_value(match.group('value'))
        if not value or value[0] in '{[&*|>!' or value.startswith('{{'):
            warnings.append(label + ': value is not a plain scalar; skipped')
            continue
        replacement = render(kind, new, value)
        newline = '\n' if line.endswith('\n') else ''
        lines[index] = match.group('indent') + match.group('key') + match.group('colon') + replacement + trailing + newline
        report['changes'].append({'field': label, 'from': current, 'to': new if kind != 'int' else int(new)})
    updated = ''.join(lines)
    if updated == original:
        return report, None, None
    try:
        reparsed = yaml.safe_load(updated)
    except yaml.YAMLError:
        return skip('edit would produce invalid YAML; file left untouched')
    for change in report['changes']:
        ok, got = lookup(reparsed, tuple(change['field'].split('.')))
        if not ok or not equal('amount' if change['field'].endswith('amount') else
                               'time' if change['field'].endswith('next_due_at') else 'text', got, change['to']):
            report['changes'] = []
            return skip('post-edit verification failed; file left untouched')
    report['status'] = 'would update' if check_mode else 'updated'
    return report, original, updated


class ActionModule(ActionBase):
    TRANSFERS_FILES = False
    _requires_connection = False
    _supports_check_mode = True

    def run(self, tmp=None, task_vars=None):
        result = super().run(tmp, task_vars)
        _, params = self.validate_argument_spec(argument_spec={
            'services': {'type': 'list', 'elements': 'dict', 'required': True},
            'hosts': {'type': 'list', 'elements': 'dict', 'required': True},
        })
        params = json.loads(json.dumps(params))
        check_mode = self._task.check_mode
        claimed, reports, diffs, lines = {}, [], [], []
        for entry in params['hosts']:
            report, before, after = process_host(entry, params['services'], claimed, check_mode)
            reports.append(report)
            if report['status'] == 'skipped':
                message = 'Skipping ' + report['host'] + ': ' + report['reason']
                display.warning(message)
                lines.append('SKIP ' + report['host'] + ': ' + report['reason'])
            for w in report.get('warnings', []):
                display.warning(report['host'] + ': ' + w)
                lines.append('WARN ' + report['host'] + ': ' + w)
            for c in report['changes']:
                lines.append(('WOULD UPDATE ' if check_mode else 'UPDATE ') + report['host'] + ' '
                             + c['field'] + ': ' + str(c['from']) + ' -> ' + str(c['to']))
            if after is not None:
                diffs.append({'before': before, 'after': after,
                              'before_header': report['file'], 'after_header': report['file']})
                if not check_mode:
                    # Rewrite in place (same inode/mode); the file is known to exist.
                    with open(report['file'], 'w', encoding='utf-8') as handle:
                        handle.write(after)
        changed = [r for r in reports if r['status'] in ('updated', 'would update')]
        matched = {r['service'] for r in reports if r.get('service')}
        unmatched = [s for s in params['services'] if s.get('uuid') not in matched]
        result.update(
            changed=bool(changed), reports=reports, lines=lines,
            counts={'hosts': len(reports), 'changed': len(changed),
                    'skipped': sum(r['status'] == 'skipped' for r in reports),
                    'billing_services_without_host': len(unmatched)},
            unmatched_services=[s.get('name') for s in unmatched])
        if diffs:
            result['diff'] = diffs
        return result
