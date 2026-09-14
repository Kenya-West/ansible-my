# -*- coding: utf-8 -*-
"""Turn the inventory's node facts into the Remnawave setup to apply.

Everything the role generates - direct hosts, chain hosts, outbounds, routing
rules and the route ids tying them together - is derived here in one pass, so
the three sides can never drift apart: an exit's route id, the outbound its
rule points at and the hosts carrying that id are computed from the same
ordered list.

The tasks stay declarative and this module keeps the grouping, the cross
product and the numbering, which Jinja expresses badly.
"""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

from ansible.errors import AnsibleFilterError


def _as_bool(value):
    """Coerce a templated option to a bool.

    A variable that reaches a filter through Ansible templating can arrive as
    the string "False", which is truthy, so booleans are read explicitly
    rather than by truthiness.
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in ('true', 'yes', 'on', '1')


def _as_pair(value, name):
    """Read a two-number range that may have arrived as a string."""
    if isinstance(value, str):
        value = [part for part in value.strip('[]() ').split(',') if part.strip()]
    try:
        low, high = (int(str(v).strip()) for v in value)
    except (TypeError, ValueError):
        raise AnsibleFilterError('%s must be two numbers, got %r' % (name, value))
    return low, high


def _label(domain):
    """The first DNS label, which is how domains are named in remarks and tags."""
    return str(domain).split('.')[0]


def _region(label):
    """The region out of a net-<region>-<n> / chain-<region>-<n> label."""
    parts = label.split('-')
    if len(parts) >= 3:
        return parts[1]
    return parts[-1] if parts else ''


def _region_code(region, codes):
    return codes.get(region) or region[:2]


def _domains_of(node):
    """A node's domain entries, normalized to a list of (domain, type).

    domains_keys holds either a list of {domain, type} mappings (remna_node)
    or a plain string (main), so accept both rather than making the caller
    care which key it pointed the role at.
    """
    raw = node.get('domains')
    if raw is None:
        return []
    if isinstance(raw, str):
        return [(raw, None)]
    out = []
    for item in raw:
        if isinstance(item, dict):
            out.append((item.get('domain'), item.get('type')))
        else:
            out.append((item, None))
    return [(d, t) for d, t in out if d]


def _collect(nodes, wanted_types):
    """Group nodes by each domain of a wanted type.

    Several Ansible hosts may publish one domain - a round-robin record in
    front of two nodes - and that is a single entity in the panel, so the
    domain is the key and the hosts behind it are its nodes.
    """
    found = {}
    for node in nodes:
        for domain, domain_type in _domains_of(node):
            if wanted_types and domain_type not in wanted_types:
                continue
            slot = found.setdefault(domain, {
                'domain': domain,
                'label': _label(domain),
                'nodes': [],
                'countries': [],
                'protocols': [],
            })
            # Hosts are bound to nodes by the name the panel knows them by,
            # which is the inventory hostname unless the node says otherwise.
            panel_name = node.get('panel_name') or node['name']
            if panel_name not in slot['nodes']:
                slot['nodes'].append(panel_name)
            country = (node.get('country') or '').upper()
            if country and country not in slot['countries']:
                slot['countries'].append(country)
            protocol = node.get('protocol')
            if protocol and protocol not in slot['protocols']:
                slot['protocols'].append(protocol)
    return found


def _settle(slot, default_protocol, warnings, kind):
    """Reduce a domain's nodes to the one country and protocol it publishes.

    A domain served by nodes that disagree is a configuration mistake rather
    than something to average out, so it is reported and the first value in
    sorted order is used, keeping the run deterministic.
    """
    countries = sorted(slot['countries'])
    protocols = sorted(slot['protocols'])
    if len(countries) > 1:
        warnings.append(
            '%s %s is served by nodes in different countries (%s); using %s'
            % (kind, slot['domain'], ', '.join(countries), countries[0]))
    if len(protocols) > 1:
        warnings.append(
            '%s %s is served by nodes with different primary protocols (%s); '
            'using %s' % (kind, slot['domain'], ', '.join(protocols), protocols[0]))
    slot['country'] = countries[0] if countries else ''
    slot['protocol'] = protocols[0] if protocols else default_protocol
    slot['region'] = _region(slot['label'])
    return slot


def _excluded_entries(exclude, exit_domain):
    """The entry domains ruled out for one exit; '*' means every one of them."""
    for item in exclude or []:
        if item.get('exit') != exit_domain:
            continue
        entries = item.get('entries')
        if entries in ('*', ['*']):
            return '*'
        return list(entries or [])
    return []


def _remark(slot, labels):
    return labels.get(slot['label'], slot['label'])


def remnawave_model(nodes, options):
    """Build the whole desired setup out of the collected node facts.

    ``nodes`` is a list of {name, country, protocol, domains}; ``options``
    carries the role's variables. Returns exits, entries, hosts, outbounds,
    rules and any warnings worth surfacing.
    """
    if not isinstance(nodes, list):
        raise AnsibleFilterError('remnawave_model expects a list of node facts')

    default_protocol = options['default_protocol']
    labels = options.get('labels') or {}
    warnings = []

    exits = [
        _settle(slot, default_protocol, warnings, 'Direct domain')
        for _, slot in sorted(_collect(nodes, set(options['direct_domain_types'])).items())
    ]
    entries = [
        _settle(slot, default_protocol, warnings, 'Chain domain')
        for _, slot in sorted(_collect(nodes, set(options['entry_domain_types'])).items())
    ]

    entry_countries = set(str(c).upper() for c in options['entry_country_codes'])
    entries = [e for e in entries if e['country'] in entry_countries]

    # --- which exit is reachable through which entry ------------------------
    skip_same_country = _as_bool(options.get('skip_same_country', True))
    pairs = {}
    for exit_slot in exits:
        excluded = _excluded_entries(options.get('exclude'), exit_slot['domain'])
        if excluded == '*':
            continue
        usable = [
            entry for entry in entries
            if entry['domain'] not in excluded
            and entry['domain'] != exit_slot['domain']
            and not (skip_same_country and entry['country'] == exit_slot['country'])
        ]
        if usable:
            pairs[exit_slot['domain']] = usable

    # --- number the chained exits ------------------------------------------
    # Ordering by region then protocol keeps the generated outbound tags
    # grouped the way they are read, and the route id is the position in that
    # same order, so tag and id always agree.
    codes = options.get('region_codes') or {}
    chained = sorted(
        (e for e in exits if e['domain'] in pairs),
        key=lambda e: (_region_code(e['region'], codes), e['protocol'], e['domain']))

    prefix = options['outbound_tag_prefix']
    width = int(options.get('outbound_tag_index_width', 3))
    base = int(options['route_id_base'])
    seen = {}
    outbounds = []
    rules = []
    for position, exit_slot in enumerate(chained):
        code = _region_code(exit_slot['region'], codes)
        group = (code, exit_slot['protocol'])
        seen[group] = seen.get(group, 0) + 1
        tag = '%s-%s-%s-%s' % (prefix, code, exit_slot['protocol'],
                               str(seen[group]).zfill(width))
        route_id = base + position
        exit_slot['route_id'] = route_id
        exit_slot['outbound_tag'] = tag
        outbounds.append({
            'tag': tag,
            'address': exit_slot['domain'],
            'protocol': exit_slot['protocol'],
            'route_id': route_id,
        })
        rules.append({'vlessRoute': str(route_id), 'outboundTag': tag})

    highest = base + len(chained) - 1 if chained else None
    lo, hi = _as_pair(options['route_id_range'], 'route_id_range')
    if highest is not None and (base < lo or highest > hi):
        warnings.append(
            'Generated route ids %d-%d fall outside the owned range %d-%d, so '
            'regenerating the rules snippet will not clean up after itself'
            % (base, highest, lo, hi))

    # --- the hosts ----------------------------------------------------------
    bind = options.get('chain_bind_nodes', 'exit')
    separator = options['remark_chain_separator']
    direct_route_id = options.get('direct_route_id')
    direct_route_id = '' if direct_route_id in (None, '') else int(direct_route_id)

    hosts = []
    for exit_slot in exits:
        hosts.append({
            'kind': 'direct',
            'remark': _remark(exit_slot, labels),
            'address': exit_slot['domain'],
            'sni': exit_slot['domain'],
            'override_sni_from_address': False,
            'vless_route_id': direct_route_id,
            'nodes': list(exit_slot['nodes']),
            'protocol': exit_slot['protocol'],
            'exit': exit_slot['domain'],
            'entry': None,
        })

    for exit_slot in chained:
        for entry in pairs[exit_slot['domain']]:
            if bind == 'entry':
                bound = list(entry['nodes'])
            elif bind == 'both':
                bound = sorted(set(exit_slot['nodes']) | set(entry['nodes']))
            elif bind == 'none':
                bound = []
            else:
                bound = list(exit_slot['nodes'])
            hosts.append({
                'kind': 'chain',
                'remark': _remark(exit_slot, labels) + separator + _remark(entry, labels),
                'address': entry['domain'],
                # The entry publishes a domain the exit does not terminate TLS
                # for, so the SNI has to come from the address instead.
                'sni': '',
                'override_sni_from_address': True,
                'vless_route_id': exit_slot['route_id'],
                'nodes': bound,
                'protocol': exit_slot['protocol'],
                'exit': exit_slot['domain'],
                'entry': entry['domain'],
            })

    duplicates = sorted(set(
        h['remark'] for h in hosts
        if [x['remark'] for x in hosts].count(h['remark']) > 1))
    if duplicates:
        raise AnsibleFilterError(
            'Generated host remarks are not unique: %s. Remarks identify hosts '
            'in the panel, so give the domains behind them distinct entries in '
            'vpn_server_remnawave_hosts_labels.' % ', '.join(duplicates))

    return {
        'exits': exits,
        'entries': entries,
        'chained': chained,
        'hosts': hosts,
        'outbounds': outbounds,
        'rules': rules,
        'warnings': warnings,
    }


def remnawave_merge_outbounds(existing, generated, prefix):
    """Replace the role's outbounds in a snippet, leaving the rest in place."""
    marker = '%s-' % prefix
    kept = [o for o in (existing or [])
            if not str((o or {}).get('tag', '')).startswith(marker)]
    return kept + list(generated or [])


def remnawave_merge_rules(existing, generated, route_id_range):
    """Replace the role's routing rules in a snippet, leaving the rest in place.

    A rule is the role's when its vlessRoute is a single number inside the
    owned range. Ranges such as "400-600" and the hand-written geo families
    are therefore preserved even when they overlap it.
    """
    low, high = _as_pair(route_id_range, 'route_id_range')

    def owned(rule):
        value = (rule or {}).get('vlessRoute')
        if value is None:
            return False
        try:
            number = int(str(value).strip())
        except (TypeError, ValueError):
            return False
        return low <= number <= high

    return [r for r in (existing or []) if not owned(r)] + list(generated or [])


def remnawave_select_tagged(entities, tags, tagged=True):
    """The panel entities carrying every one of ``tags``, or with ``tagged``
    false, the ones that do not.

    The panel is shared with entities made by hand, so the role only ever
    takes over, retires or cleans what carries all of its primary tags.
    """
    wanted = set(tags or [])
    tagged = _as_bool(tagged)
    return [entity for entity in (entities or [])
            if wanted.issubset((entity or {}).get('tags') or []) == tagged]


class FilterModule(object):
    def filters(self):
        return {
            'remnawave_model': remnawave_model,
            'remnawave_merge_outbounds': remnawave_merge_outbounds,
            'remnawave_merge_rules': remnawave_merge_rules,
            'remnawave_select_tagged': remnawave_select_tagged,
        }
