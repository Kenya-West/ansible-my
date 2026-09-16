# -*- coding: utf-8 -*-
"""Turn the inventory's node facts into the Remnawave setup to apply.

Direct hosts, chain hosts, routing rules and the route ids tying them together
are derived here in one pass, so the three sides can never drift apart: an
exit's route id, the outbound its rule points at and the hosts carrying that
id all follow the outbound plan of the inventory
(group_vars/vpn_server_remnawave/snippets.yaml), which names every outbound.

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


def _index(label):
    """The trailing number of a net-<region>-<n> / chain-<region>-<n> label."""
    parts = label.split('-')
    if parts and parts[-1].isdigit():
        return int(parts[-1])
    return None


def _flag(country, symbols):
    """The flag emoji of a two-letter country code.

    ``symbols`` is the inventory's letter -> regional indicator map
    (vpn_deployments_regional_indicator_symbols); without it the indicators
    are composed from the code itself.
    """
    code = str(country or '').strip().lower()
    if len(code) != 2 or not code.isalpha():
        return ''
    if symbols:
        first, second = symbols.get(code[0]), symbols.get(code[1])
        return (first + second) if first and second else ''
    return ''.join(chr(0x1F1E6 + ord(letter) - ord('a')) for letter in code)


def _name(slots, region_codes, flag_symbols):
    """Name every domain of a collection "<flag> <REGION CODE>-<n>".

    The number is the domain's position among the domains of its own region,
    counted from one in domain-index order, so net-asia-2 and net-asia-4 are
    AS-1 and AS-2 however they are numbered in DNS. The flag is the one of the
    country the domain's nodes are in, so a Kazakh exit behind a Russian entry
    reads "🇰🇿 AS-1 | by 🇷🇺 RU-1".
    """
    counted = {}
    ordered = sorted(
        slots,
        key=lambda slot: (slot['region'],
                          _index(slot['label']) is None,
                          _index(slot['label']) or 0,
                          slot['label']))
    for slot in ordered:
        region = slot['region']
        counted[region] = counted.get(region, 0) + 1
        code = str(region_codes.get(region) or region).upper()
        flag = _flag(slot['country'], flag_symbols)
        slot['region_code'] = code
        slot['position'] = counted[region]
        slot['short_name'] = '%s-%d' % (code, counted[region])
        slot['display'] = ('%s %s' % (flag, slot['short_name'])) if flag else slot['short_name']
    return slots


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
    """A domain's name in the panel: the one the inventory gives it, else its
    generated short name, else the domain label itself."""
    return labels.get(slot['label']) or slot.get('display') or slot['label']


def remnawave_model(nodes, options):
    """Build the whole desired setup out of the collected node facts.

    ``nodes`` is a list of {name, country, protocol, domains}; ``options``
    carries the role's variables, ``outbounds`` among them: the outbound plan
    of the inventory, which names the tag of every exit. Returns exits,
    entries, the chained exits, hosts, rules and any warnings worth surfacing.
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

    # Short names are per collection: an entry that no country lets act as one
    # is gone by now, so it takes no number with it.
    region_codes = options.get('region_codes') or {}
    flag_symbols = options.get('flag_symbols') or {}
    _name(exits, region_codes, flag_symbols)
    _name(entries, region_codes, flag_symbols)

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
    # Every exit's outbound is planned in the inventory, tag included. A
    # chained exit's rule points at that outbound and its route id is its
    # position in the plan, so tag and id always follow the same order.
    planned = [o for o in (options.get('outbounds') or [])
               if o.get('kind', 'location') == 'location']
    position_of = {}
    tag_of = {}
    for position, outbound in enumerate(planned):
        position_of.setdefault(outbound['address'], position)
        tag_of.setdefault(outbound['address'], outbound['tag'])

    unplanned = sorted(e['domain'] for e in exits
                       if e['domain'] in pairs and e['domain'] not in tag_of)
    if unplanned:
        warnings.append(
            'Exits with chain entries but no planned outbound get no route id, '
            'rule or chain hosts: %s' % ', '.join(unplanned))
    chained = sorted(
        (e for e in exits if e['domain'] in pairs and e['domain'] in tag_of),
        key=lambda e: position_of[e['domain']])

    base = int(options['route_id_base'])
    rules = []
    for position, exit_slot in enumerate(chained):
        tag = tag_of[exit_slot['domain']]
        route_id = base + position
        exit_slot['route_id'] = route_id
        exit_slot['outbound_tag'] = tag
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
                'sni': '',
                'vless_route_id': exit_slot['route_id'],
                'nodes': bound,
                'protocol': exit_slot['protocol'],
                'exit': exit_slot['domain'],
                'entry': entry['domain'],
            })

    # Nodes managed in the panel require their SNI to come from the address,
    # regardless of host kind.
    for host in hosts:
        host['override_sni_from_address'] = True

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


def remnawave_select_profiles_kept(profiles, nodes, protected):
    """The config profiles that must never be deleted: the ones a node still
    activates, and the ones whose name is in ``protected``.

    The panel reserves some profile names (Default-Profile), so a profile of
    such a name could not be created again once it is gone.
    """
    in_use = set(((node or {}).get('configProfile') or {}).get('activeConfigProfileUuid')
                 for node in (nodes or []))
    protected = set(protected or [])
    return [profile for profile in (profiles or [])
            if (profile or {}).get('uuid') in in_use
            or (profile or {}).get('name') in protected]


def _route_number(value):
    """A vlessRoute / vlessRouteId as an int, or None when it is not one number."""
    if value is None or value == '':
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _snippet_refs(section):
    """The snippet names a config profile section embeds ({snippet: name})."""
    return [item.get('snippet') for item in (section or [])
            if isinstance(item, dict) and item.get('snippet')]


def remnawave_verify(panel, model, options):
    """Check what the panel holds against itself and against the desired setup.

    ``panel`` is the remnawave_gathered fact with hosts, nodes, snippets and
    config_profiles; ``model`` the output of remnawave_model. Follows every
    managed host the way a client would be routed: its route id to the rule
    in the rules snippet, the rule to the outbound in the outbounds snippet,
    the outbound to the exit it should reach; then the nodes the host binds to
    and the inbound and profile they activate, and the snippets the profile
    embeds.

    Returns ``problems`` - what would misroute or drop traffic - and ``notes``
    - what is off but harmless, such as a stale host already disabled - plus
    the counts of what was looked at.
    """
    primary = set(options.get('primary_tags') or [])
    separator = options['separator']
    direct_route_id = _route_number(options.get('direct_route_id'))
    lo, hi = _as_pair(options['route_id_range'], 'route_id_range')
    problems, notes = [], []

    hosts = panel.get('hosts') or []
    managed = {}
    untagged = {}
    for host in hosts:
        remark = host.get('remark')
        if primary.issubset(host.get('tags') or []):
            managed[remark] = host
        else:
            untagged[remark] = host

    nodes_by_uuid = dict((n.get('uuid'), n) for n in panel.get('nodes') or [])
    nodes_by_name = dict((n.get('name'), n) for n in panel.get('nodes') or [])
    profiles = dict((p.get('uuid'), p) for p in panel.get('config_profiles') or [])
    snippets = dict((s.get('name'), s.get('snippet') or [])
                    for s in panel.get('snippets') or [])

    rules_name = options['rules_snippet']
    outbounds_name = options['outbounds_snippet']
    balancers_name = options.get('balancers_snippet')
    for name in (rules_name, outbounds_name):
        if name not in snippets:
            problems.append('Snippet %s is not in the panel' % name)

    rule_of = {}
    for rule in snippets.get(rules_name) or []:
        number = _route_number((rule or {}).get('vlessRoute'))
        if number is None:
            continue
        if number in rule_of:
            problems.append('Rules snippet %s has route id %d twice (%s and %s)'
                            % (rules_name, number, rule_of[number], rule.get('outboundTag')))
        rule_of[number] = rule.get('outboundTag')

    outbound_address = {}
    for outbound in snippets.get(outbounds_name) or []:
        tag = (outbound or {}).get('tag')
        if not tag:
            continue
        vnext = ((outbound.get('settings') or {}).get('vnext') or [{}])
        outbound_address[tag] = (vnext[0] or {}).get('address')

    for balancer in snippets.get(balancers_name) or [] if balancers_name else []:
        for tag in (balancer or {}).get('selector') or []:
            if tag not in outbound_address:
                problems.append('Balancer %s selects outbound %s, which is not in %s'
                                % (balancer.get('tag'), tag, outbounds_name))

    def describe(host):
        return "'%s'" % host.get('remark')

    # --- every desired host, followed the way a client is routed ------------
    used_route_ids = set()
    for want in model.get('hosts') or []:
        remark = want['remark']
        have = managed.get(remark)
        if have is None:
            if remark in untagged:
                notes.append("Host '%s' is in the panel without the primary tags, so it is "
                             "not the role's; it was left out when generating" % remark)
            else:
                problems.append("Host '%s' is not in the panel" % remark)
            continue

        have_id = _route_number(have.get('vlessRouteId'))
        want_id = _route_number(want.get('vless_route_id'))
        if have_id != want_id:
            problems.append('Host %s carries route id %s, the inventory wants %s'
                            % (describe(have), have_id, want_id))
        if have.get('address') != want['address']:
            problems.append('Host %s has address %s, the inventory wants %s'
                            % (describe(have), have.get('address'), want['address']))

        if want['kind'] == 'chain':
            if have_id is None:
                problems.append('Chain host %s has no route id, so it is served directly '
                                'by its entry instead of reaching %s'
                                % (describe(have), want['exit']))
            else:
                used_route_ids.add(have_id)
                tag = rule_of.get(have_id)
                if tag is None:
                    problems.append('Chain host %s carries route id %d, but %s has no rule '
                                    'for it' % (describe(have), have_id, rules_name))
                elif tag not in outbound_address:
                    problems.append('Chain host %s: route id %d goes to outbound %s, which '
                                    'is not in %s' % (describe(have), have_id, tag, outbounds_name))
                elif outbound_address[tag] != want['exit']:
                    problems.append('Chain host %s: route id %d goes to outbound %s (%s), '
                                    'not to its exit %s'
                                    % (describe(have), have_id, tag,
                                       outbound_address[tag], want['exit']))
        elif have_id != direct_route_id:
            problems.append('Direct host %s carries route id %s instead of %s'
                            % (describe(have), have_id, direct_route_id))

        # The inbound and the nodes: a host bound to a node that does not
        # activate its inbound is offered to clients and serves nothing.
        inbound = have.get('inbound') or {}
        profile_uuid = inbound.get('configProfileUuid')
        inbound_uuid = inbound.get('configProfileInboundUuid')
        profile = profiles.get(profile_uuid)
        if profile is None:
            problems.append('Host %s is attached to config profile %s, which is not in the panel'
                            % (describe(have), profile_uuid))
        else:
            config = profile.get('config') or {}
            routing = config.get('routing') or {}
            if outbounds_name not in _snippet_refs(config.get('outbounds')):
                problems.append("Config profile '%s' of host %s does not embed snippet %s"
                                % (profile.get('name'), describe(have), outbounds_name))
            if rules_name not in _snippet_refs(routing.get('rules')):
                problems.append("Config profile '%s' of host %s does not embed snippet %s"
                                % (profile.get('name'), describe(have), rules_name))

        bound = [nodes_by_uuid.get(uuid, {'name': uuid}) for uuid in have.get('nodes') or []]
        bound_names = sorted(n.get('name') for n in bound)
        if bound_names != sorted(want.get('nodes') or []):
            problems.append('Host %s is bound to nodes %s, the inventory wants %s'
                            % (describe(have), ', '.join(bound_names) or '-',
                               ', '.join(sorted(want.get('nodes') or [])) or '-'))
        for node in bound:
            if node.get('uuid') is None:
                problems.append('Host %s is bound to node %s, which is not in the panel'
                                % (describe(have), node.get('name')))
                continue
            active = node.get('configProfile') or {}
            if active.get('activeConfigProfileUuid') != profile_uuid:
                problems.append("Node %s bound to host %s activates config profile %s, not "
                                "the host's %s" % (node.get('name'), describe(have),
                                                   active.get('activeConfigProfileUuid'),
                                                   profile_uuid))
            elif inbound_uuid not in [i.get('uuid') for i in active.get('activeInbounds') or []]:
                problems.append("Node %s bound to host %s does not activate the host's inbound"
                                % (node.get('name'), describe(have)))
            if node.get('isDisabled') and not have.get('isDisabled'):
                notes.append('Host %s is enabled but its node %s is disabled'
                             % (describe(have), node.get('name')))

    # --- what the panel holds beyond the desired setup ----------------------
    desired = set(h['remark'] for h in model.get('hosts') or [])
    for remark, have in sorted(managed.items()):
        if remark in desired:
            continue
        have_id = _route_number(have.get('vlessRouteId'))
        where = ''
        if have_id is not None and have_id in rule_of:
            where = ' and route id %d now goes to %s (%s)' % (
                have_id, rule_of[have_id], outbound_address.get(rule_of[have_id]))
        if have.get('isDisabled'):
            notes.append('Host %s is no longer produced by the inventory; it is disabled%s'
                         % (describe(have), where))
        else:
            problems.append('Host %s is no longer produced by the inventory but still enabled%s'
                            % (describe(have), where))

    for number in sorted(rule_of):
        if not lo <= number <= hi:
            continue
        if rule_of[number] not in outbound_address:
            problems.append('Rule for route id %d goes to outbound %s, which is not in %s'
                            % (number, rule_of[number], outbounds_name))
        if number not in used_route_ids:
            notes.append('Rule for route id %d (%s) is used by no host of the inventory'
                         % (number, rule_of[number]))

    return {
        'problems': problems,
        'notes': notes,
        'checked': {
            'hosts': len(managed),
            'untagged_hosts': len(untagged),
            'rules': len([n for n in rule_of if lo <= n <= hi]),
            'outbounds': len(outbound_address),
            'nodes': len(nodes_by_uuid),
            'config_profiles': len(profiles),
        },
    }


class FilterModule(object):
    def filters(self):
        return {
            'remnawave_model': remnawave_model,
            'remnawave_merge_outbounds': remnawave_merge_outbounds,
            'remnawave_merge_rules': remnawave_merge_rules,
            'remnawave_select_tagged': remnawave_select_tagged,
            'remnawave_select_profiles_kept': remnawave_select_profiles_kept,
            'remnawave_verify': remnawave_verify,
        }
