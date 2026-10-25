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
                'profiles': [],
                'scopes': [],
            })
            scope = node.get('scope')
            if scope and scope not in slot['scopes']:
                slot['scopes'].append(scope)
            profile = node.get('profile')
            if profile and profile not in slot['profiles']:
                slot['profiles'].append(profile)
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
    # A host is attached to one inbound, so every node behind a domain has to
    # activate the same profile; nodes split across profiles cannot be served
    # by one host and are refused rather than half published.
    if len(slot['profiles']) > 1 or len(slot['scopes']) > 1:
        raise AnsibleFilterError(
            '%s %s is served by nodes with different scopes or protocols (%s; %s). '
            'Nodes behind one domain must share their scope and protocol.'
            % (kind, slot['domain'], ', '.join(s['scope'] for s in slot['scopes']),
               ', '.join(protocols)))
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


def _chain_pairs(exits, entries, options):
    """Usable chain entries for each exit, independent of profile rendering."""
    pairs = {}
    skip_same_country = _as_bool(options.get('skip_same_country', True))
    for exit_slot in exits:
        excluded = _excluded_entries(options.get('exclude'), exit_slot['domain'])
        if excluded == '*':
            continue
        usable = [entry for entry in entries
                  if entry['domain'] not in excluded
                  and entry['domain'] != exit_slot['domain']
                  and not (skip_same_country and entry['country'] == exit_slot['country'])]
        if usable:
            pairs[exit_slot['domain']] = usable
    return pairs


def _remark(slot, labels):
    """A domain's name in the panel: the one the inventory gives it, else its
    generated short name, else the domain label itself."""
    return labels.get(slot['label']) or slot.get('display') or slot['label']


def _plain(value):
    """A copy of a templated value made of plain dicts and lists.

    Ansible hands filters lazily templated containers; reading every item
    resolves it where it was defined, while copy.deepcopy would carry the lazy
    containers away from their templating context. So whatever the model keeps
    or alters is copied through this rather than deepcopy.
    """
    if isinstance(value, dict):
        return dict((k, _plain(v)) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


_KIND_ORDER = {'global': 0, 'location': 1, 'exclusive': 2}
_SELECTOR_KEYS = ('kind', 'geo', 'scope', 'protocol', 'profile')


def _as_list(value):
    if value is None or value == '':
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _matches(selector, profile):
    """Whether a profile selector picks a profile.

    A selector is a mapping of kind, geo, scope, protocol and profile (the
    profile's name), each a value or a list of values: every key given must
    match, any value of a key may. An empty mapping picks every profile. A list
    of selectors picks what any of them picks, so an empty list picks none.
    """
    if selector is None:
        return True
    if isinstance(selector, (list, tuple)):
        return any(_matches(item, profile) for item in selector)
    if not isinstance(selector, dict):
        raise AnsibleFilterError('A profile selector must be a mapping or a list '
                                 'of mappings, got %r' % (selector,))
    unknown = sorted(set(selector) - set(_SELECTOR_KEYS))
    if unknown:
        raise AnsibleFilterError('Unknown profile selector keys %s in %r; use %s'
                                 % (', '.join(unknown), selector, ', '.join(_SELECTOR_KEYS)))
    for key in _SELECTOR_KEYS:
        wanted = _as_list(selector.get(key))
        if not wanted:
            continue
        value = profile['name'] if key == 'profile' else profile[key]
        if value not in [str(w) for w in wanted]:
            return False
    return True


def _scope_of(node, options, exclusive_names, warnings):
    """The scope a node's config profile is chosen by.

    exclusive: the node is in the exclusive group and names its profile;
    location: the node sits behind a censorship geo (russia -> RU);
    global: everything else.
    """
    geo = str(node.get('geo') or 'global')
    exclusive = str(node.get('exclusive_profile') or '')
    if _as_bool(node.get('exclusive_member')):
        if not exclusive:
            raise AnsibleFilterError(
                'Node %s is in the exclusive group but sets no '
                'remna_node_panel_exclusive_profile' % node['name'])
        if exclusive not in exclusive_names:
            raise AnsibleFilterError(
                'Node %s names exclusive profile %s, which the panel does not '
                'declare in vpn_server_remnawave_config_profiles_exclusive (%s)'
                % (node['name'], exclusive, ', '.join(sorted(exclusive_names)) or '-'))
        return {'kind': 'exclusive', 'scope': exclusive, 'geo': geo}
    if exclusive:
        warnings.append('Node %s names exclusive profile %s but is not in the '
                        'exclusive group; it is published by its location instead'
                        % (node['name'], exclusive))
    if geo != 'global':
        codes = options.get('region_codes') or {}
        return {'kind': 'location', 'scope': str(codes.get(geo) or geo).upper(), 'geo': geo}
    return {'kind': 'global', 'scope': 'global', 'geo': geo}


def _inject_private_key(inbound, tag, base_tag, keys, common):
    """Put the REALITY private key of an inbound in place: the one of its own
    tag, else the one of the tag it was derived from, else the common key."""
    stream = inbound.get('streamSettings') or {}
    if stream.get('security') != 'reality':
        return
    reality = stream.setdefault('realitySettings', {})
    key = keys.get(tag) or keys.get(base_tag) or common
    if key:
        reality['privateKey'] = key


def _profile_identity(scope, base, location, exclusive_of):
    """The name and inbound tag suffix of a base profile rendered for a scope."""
    variant = str(base.get('variant_suffix') or '')
    if scope['kind'] == 'global':
        return str(base['name']), ''
    if scope['kind'] == 'location':
        values = {'code': scope['scope'], 'geo': scope['geo']}
        name = str(location.get('name', 'Reverse-{code}')).format(**values) + variant
        suffix = str(location.get('inbound_suffix', 'REVERSE_{code}')).format(**values)
        return name, suffix
    item = exclusive_of[scope['scope']]
    return str(item['name']) + variant, str(item['inbound_suffix'])


def _render_profiles(scopes_in_use, options, warnings):
    """Render every config profile the panel needs.

    Every base profile is rendered for the global scope, always. Other scopes
    get the protocols their nodes serve or their exclusive chains need, so a
    location or exclusive group without nodes produces no profile at all.
    """
    bases = list(options.get('profiles_base') or [])
    base_of = {}
    for base in bases:
        if not base.get('name') or not base.get('protocol') or not base.get('inbounds'):
            raise AnsibleFilterError('Every vpn_server_remnawave_config_profiles_base item '
                                     'needs name, protocol and inbounds, got %r' % (base,))
        if base['protocol'] in base_of:
            raise AnsibleFilterError('Two base config profiles serve protocol %s'
                                     % base['protocol'])
        base_of[base['protocol']] = base

    location = options.get('profiles_location') or {}
    exclusive_of = dict((str(e['name']), e) for e in options.get('profiles_exclusive') or [])
    keys = options.get('private_keys') or {}
    common_key = options.get('private_key_common') or ''
    common = options.get('profile_common') or {}
    addons = list(options.get('addons') or [])
    seen_addons = set()
    for addon in addons:
        if not addon.get('name') or addon['name'] in seen_addons:
            raise AnsibleFilterError('Every addon needs a unique name, got %r' % (addon.get('name'),))
        seen_addons.add(addon['name'])

    wanted = [({'kind': 'global', 'scope': 'global', 'geo': 'global'}, base['protocol'])
              for base in bases]
    for (kind, scope, geo), protocols in sorted(scopes_in_use.items()):
        missing = sorted(p for p in protocols if p not in base_of)
        if missing:
            raise AnsibleFilterError(
                'No base config profile serves protocol %s, which nodes of scope %s '
                'declare; add it to vpn_server_remnawave_config_profiles_base'
                % (', '.join(missing), scope))
        if kind != 'global':
            wanted.extend(({'kind': kind, 'scope': scope, 'geo': geo}, protocol)
                          for protocol in sorted(protocols))

    profiles = []
    for scope, protocol in wanted:
        base = base_of[protocol]
        name, suffix = _profile_identity(scope, base, location, exclusive_of)
        inbounds, inbound_map = [], {}
        for inbound in base['inbounds']:
            inbound = _plain(inbound)
            base_tag = str(inbound['tag'])
            tag = base_tag + ('_' + suffix if suffix else '')
            inbound['tag'] = tag
            _inject_private_key(inbound, tag, base_tag, keys, common_key)
            inbounds.append(inbound)
            inbound_map[base_tag] = tag
        profile = {
            'name': name,
            'kind': scope['kind'],
            'scope': scope['scope'],
            'geo': scope['geo'],
            'protocol': protocol,
            'base': str(base['name']),
            'inbound_tags': [i['tag'] for i in inbounds],
            'inbound_map': inbound_map,
            'addons': [],
            'squads': [],
        }

        config = _plain(common)
        config.update(_plain(base.get('config') or {}))
        config['inbounds'] = inbounds
        outbounds = list(config.get('outbounds') or [])
        routing = dict(config.get('routing') or {})
        rules = list(routing.get('rules') or [])
        balancers = list(routing.get('balancers') or [])
        for addon in addons:
            if not _matches(addon.get('profiles'), profile):
                continue
            scoped = [inbound_map[t] for t in _as_list(addon.get('inbounds')) if t in inbound_map]
            if _as_list(addon.get('inbounds')) and not scoped:
                continue
            profile['addons'].append(addon['name'])
            outbounds.extend(_plain(_as_list(addon.get('outbounds'))))
            balancers.extend(_plain(_as_list(addon.get('balancers'))))
            for rule in _as_list(addon.get('rules')):
                rule = _plain(rule)
                if scoped:
                    if 'snippet' in rule:
                        raise AnsibleFilterError(
                            'Addon %s scopes its rules to inbounds, so they must be '
                            'written inline: a snippet reference cannot carry an '
                            'inboundTag' % addon['name'])
                    rule['inboundTag'] = scoped
                rules.append(rule)
        config['outbounds'] = outbounds
        routing['rules'] = rules
        if balancers:
            routing['balancers'] = balancers
        else:
            routing.pop('balancers', None)
        config['routing'] = routing
        profile['config'] = config
        profiles.append(profile)

    names = [p['name'] for p in profiles]
    duplicates = sorted(set(n for n in names if names.count(n) > 1))
    if duplicates:
        raise AnsibleFilterError('Generated config profile names are not unique: %s'
                                 % ', '.join(duplicates))
    for profile in profiles:
        if not 2 <= len(profile['name']) <= 30:
            raise AnsibleFilterError('Config profile name %r must be 2 to 30 characters'
                                     % profile['name'])
    profiles.sort(key=lambda p: (_KIND_ORDER[p['kind']], p['scope'],
                                 [b['protocol'] for b in bases].index(p['protocol'])))
    return profiles


def _squad_grants(profiles, grants):
    """The inbounds each named internal squad must hold: every inbound of the
    profiles its selector picks. Several items naming one squad add up."""
    out = {}
    order = []
    for item in grants or []:
        squad = item.get('squad')
        if not squad:
            raise AnsibleFilterError('Every vpn_server_remnawave_internal_squads_inbounds '
                                     'item needs a squad, got %r' % (item,))
        if squad not in out:
            out[squad] = {'squad': squad, 'inbounds': [], 'profiles': []}
            order.append(squad)
        for profile in profiles:
            if not _matches(item.get('profiles', {}), profile):
                continue
            if profile['name'] not in out[squad]['profiles']:
                out[squad]['profiles'].append(profile['name'])
            if squad not in profile['squads']:
                profile['squads'].append(squad)
            for tag in profile['inbound_tags']:
                if tag not in out[squad]['inbounds']:
                    out[squad]['inbounds'].append(tag)
    return [out[s] for s in order]


def remnawave_model(nodes, options):
    """Build the whole desired setup out of the collected node facts.

    ``nodes`` is a list of {name, country, protocol, domains, geo,
    exclusive_member, exclusive_profile, panel_inbounds}; ``options`` carries
    the role's variables, ``outbounds`` among them: the outbound plan of the
    inventory, which names the tag of every exit. Returns the config profiles,
    the profile each node activates, the inbounds each squad is granted, exits,
    entries, the chained exits, hosts, rules and any warnings worth surfacing.
    """
    if not isinstance(nodes, list):
        raise AnsibleFilterError('remnawave_model expects a list of node facts')
    nodes = _plain(nodes)

    default_protocol = options['default_protocol']
    labels = options.get('labels') or {}
    warnings = []

    # --- the config profile of every node ----------------------------------
    # A node activates exactly one profile, chosen by its scope and the
    # protocol it serves; the profiles are rendered for the scopes in use.
    exclusive_names = set(str(e.get('name')) for e in options.get('profiles_exclusive') or [])
    scopes_in_use = {}
    for node in nodes:
        node['protocol'] = node.get('protocol') or default_protocol
        node['scope'] = _scope_of(node, options, exclusive_names, warnings)
        key = (node['scope']['kind'], node['scope']['scope'], node['scope']['geo'])
        scopes_in_use.setdefault(key, set()).add(node['protocol'])

    # An exclusive profile is one profile name per protocol, so its nodes have
    # to agree on the geo that decides which addons it gets.
    exclusive_geos = {}
    for node in nodes:
        if node['scope']['kind'] == 'exclusive':
            exclusive_geos.setdefault(node['scope']['scope'], set()).add(node['scope']['geo'])
    split = sorted(name for name, geos in exclusive_geos.items() if len(geos) > 1)
    if split:
        raise AnsibleFilterError('Exclusive profiles with nodes in different censorship '
                                 'geos: %s' % ', '.join(split))

    # Plan chains before rendering profiles: their client-facing transport is
    # the entry's, but access is granted by the exit's scope. Shared chains use
    # the global base; exclusive chains need a variant for each entry protocol.
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
    pairs = _chain_pairs(exits, entries, options)
    planned_domains = set(o['address'] for o in options.get('outbounds') or []
                          if o.get('kind', 'location') == 'location')
    for exit_slot in exits:
        if exit_slot['domain'] not in planned_domains:
            continue
        scope = exit_slot['scopes'][0]
        if scope['kind'] == 'exclusive':
            key = (scope['kind'], scope['scope'], scope['geo'])
            scopes_in_use[key].update(e['protocol'] for e in pairs.get(exit_slot['domain'], []))

    profiles = _render_profiles(scopes_in_use, options, warnings)
    squad_grants = _squad_grants(profiles, options.get('squads_inbounds'))
    profile_by_key = dict(((p['kind'], p['scope'], p['protocol']), p) for p in profiles)
    profile_by_name = dict((p['name'], p) for p in profiles)

    node_profiles = {}
    for node in nodes:
        profile = profile_by_key[(node['scope']['kind'], node['scope']['scope'], node['protocol'])]
        node['profile'] = profile['name']
        inbounds = list(profile['inbound_tags'])
        if node.get('panel_inbounds'):
            unknown = [t for t in node['panel_inbounds'] if t not in profile['inbound_map']]
            if unknown:
                raise AnsibleFilterError(
                    'Node %s lists inbounds %s in remna_node_panel_inbounds, which config '
                    'profile %s is not derived from (%s)'
                    % (node['name'], ', '.join(unknown), profile['name'],
                       ', '.join(profile['inbound_map'])))
            inbounds = [profile['inbound_map'][t] for t in node['panel_inbounds']]
        node_profiles[node.get('panel_name') or node['name']] = {
            'config_profile': profile['name'],
            'inbounds': inbounds,
        }

    for profile in profiles:
        if profile['kind'] != 'global' and not profile['squads']:
            warnings.append('Config profile %s is granted to no internal squad, so no '
                            'user can connect through its inbounds' % profile['name'])

    # Every node behind one domain must activate the same profile, even when
    # the scope agrees but its primary transports do not.
    for slot in exits + entries:
        slot['profiles'] = sorted(set(node_profiles[n]['config_profile'] for n in slot['nodes']))
        _settle(slot, default_protocol, [], 'Domain')

    # Short names are per collection: an entry that no country lets act as one
    # is gone by now, so it takes no number with it.
    region_codes = options.get('region_codes') or {}
    flag_symbols = options.get('flag_symbols') or {}
    for slot in exits + entries:
        profile = profile_by_name[slot['profiles'][0]]
        slot['profile'] = profile['name']
        slot['inbound'] = profile['inbound_tags'][0]
        slot['scope_kind'] = profile['kind']
        slot['scope'] = profile['scope']

    # Exclusive exits are counted apart, per exclusive profile, so neither the
    # shared numbering nor an exclusive squad's own list has gaps; their names
    # carry the profile's name, since a remark has to be unique panel-wide.
    def group_of(slot):
        return slot['scope'] if slot['scope_kind'] == 'exclusive' else ''

    exclusive_format = options.get('remark_exclusive_format') or '{name} · {profile}'
    for collection in (exits, entries):
        for group in sorted(set(group_of(s) for s in collection)):
            members = [s for s in collection if group_of(s) == group]
            _name(members, region_codes, flag_symbols)
            if group:
                for slot in members:
                    slot['display'] = exclusive_format.format(
                        name=slot['display'], profile=group)

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
    # A direct host uses its exit's profile. A chain host uses the entry's
    # transport on the global base (shared) or exit's exclusive scope.
    bind = options.get('chain_bind_nodes', 'entry')
    separator = options['remark_chain_separator']
    direct_route_id = options.get('direct_route_id')
    direct_route_id = '' if direct_route_id in (None, '') else int(direct_route_id)
    unrestricted = {'mode': 'exclude', 'squads': []}

    hosts = []
    for exit_slot in exits:
        hosts.append({
            'kind': 'direct',
            'remark': _remark(exit_slot, labels),
            'address': exit_slot['domain'],
            'sni': '',
            'vless_route_id': direct_route_id,
            'nodes': list(exit_slot['nodes']),
            'protocol': exit_slot['protocol'],
            'config_profile': exit_slot['profile'],
            'inbound': exit_slot['inbound'],
            'internal_squads': dict(unrestricted),
            'exit': exit_slot['domain'],
            'entry': None,
        })

    for exit_slot in chained:
        # Visibility follows the exit's access scope, never the RU entry's.
        if exit_slot['scope_kind'] == 'exclusive':
            allowed = sorted(profile_by_name[exit_slot['profile']]['squads'])
            restriction = {'mode': 'allow_only', 'squads': allowed}
            if not allowed:
                warnings.append('Chain hosts of exclusive exit %s are shown to no one: no '
                                'internal squad is granted config profile %s'
                                % (exit_slot['domain'], exit_slot['profile']))
        else:
            restriction = dict(unrestricted)
        for entry in pairs[exit_slot['domain']]:
            scope_kind = 'exclusive' if exit_slot['scope_kind'] == 'exclusive' else 'global'
            scope = exit_slot['scope'] if scope_kind == 'exclusive' else 'global'
            client_profile = profile_by_key[(scope_kind, scope, entry['protocol'])]
            if bind == 'exit':
                bound = list(exit_slot['nodes'])
            elif bind == 'both':
                bound = sorted(set(exit_slot['nodes']) | set(entry['nodes']))
            elif bind == 'none':
                bound = []
            else:
                bound = list(entry['nodes'])
            if bind in ('exit', 'both'):
                warnings.append(
                    'Chain host of %s through %s is bound to exit nodes, but the client '
                    'connects to the entry; set vpn_server_remnawave_hosts_chain_bind_nodes '
                    'to entry' % (exit_slot['domain'], entry['domain']))
            hosts.append({
                'kind': 'chain',
                'remark': _remark(exit_slot, labels) + separator + _remark(entry, labels),
                'address': entry['domain'],
                'sni': '',
                'vless_route_id': exit_slot['route_id'],
                'nodes': bound,
                'protocol': entry['protocol'],
                'config_profile': client_profile['name'],
                'inbound': client_profile['inbound_tags'][0],
                'internal_squads': restriction,
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
        'profiles': profiles,
        'node_profiles': node_profiles,
        'squad_grants': squad_grants,
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


def remnawave_select_profiles_kept(profiles, nodes, protected, managed_tags=None, produced=None):
    """The config profiles that must never be deleted: the ones a node still
    activates, and the ones whose name is in ``protected``.

    The panel reserves some profile names (Default-Profile), so a profile of
    such a name could not be created again once it is gone.

    With ``managed_tags`` and ``produced`` (node names) given, a node carrying
    every managed tag that the inventory no longer produces does not keep a
    profile: it is the role's own retired node, so the profile of a location
    whose last node is gone can go too.
    """
    managed = set(managed_tags or [])
    produced = None if produced is None else set(produced)

    def holds(node):
        if produced is None or not managed:
            return True
        if not managed.issubset(node.get('tags') or []):
            return True
        return node.get('name') in produced

    in_use = set(((node or {}).get('configProfile') or {}).get('activeConfigProfileUuid')
                 for node in (nodes or []) if holds(node or {}))
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


def _client_transport(inbound):
    """Settings that must agree when a chain advertises a different profile.

    Tags and server-side routing may differ; the client-facing protocol,
    transport and REALITY credentials may not.
    """
    stream = inbound.get('streamSettings') or {}
    reality = stream.get('realitySettings') or {}
    return {
        'protocol': inbound.get('protocol'),
        'network': {'tcp': 'raw'}.get(stream.get('network'), stream.get('network')),
        'security': stream.get('security'),
        'reality': {k: reality.get(k) for k in ('privateKey', 'shortIds', 'serverNames')},
        'xhttp': stream.get('xhttpSettings'),
    }


def remnawave_verify(panel, model, options):
    """Check what the panel holds against itself and against the desired setup.

    ``panel`` is the remnawave_gathered fact with hosts, nodes, snippets,
    config_profiles and internal_squads; ``model`` the output of
    remnawave_model. Follows every managed host the way a client would be
    routed: its route id to the rule in the rules snippet, the rule to the
    outbound in the outbounds snippet, the outbound to the exit it should
    reach; then the profile and inbound it is attached to, the squads it is
    shown to and the nodes it binds to. Then checks every generated profile's
    inbounds and embedded snippets, the profile every node activates and the
    inbounds every squad is granted.

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
    profiles_by_name = dict((p.get('name'), p) for p in panel.get('config_profiles') or [])
    inbound_tag = {}
    for profile in profiles.values():
        for inbound in profile.get('inbounds') or []:
            inbound_tag[inbound.get('uuid')] = inbound.get('tag')
    snippets = dict((s.get('name'), s.get('snippet') or [])
                    for s in panel.get('snippets') or [])
    squads = dict((s.get('name'), s) for s in panel.get('internal_squads') or [])
    squad_name = dict((s.get('uuid'), s.get('name')) for s in squads.values())
    squad_tags = dict((name, set(i.get('tag') for i in s.get('inbounds') or []))
                      for name, s in squads.items())
    want_profiles = dict((p['name'], p) for p in model.get('profiles') or [])

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

    def config_inbound(profile, tag):
        return next((i for i in (profile.get('config') or {}).get('inbounds') or []
                     if i.get('tag') == tag), None)

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

        if (have.get('sni') or '') != (want.get('sni') or ''):
            problems.append('Host %s has SNI %s, the inventory wants %s'
                            % (describe(have), have.get('sni'), want.get('sni') or 'blank'))
        if have.get('overrideSniFromAddress') is not True:
            problems.append('Host %s does not override SNI from address' % describe(have))
        if options.get('fingerprint') and have.get('fingerprint') != options['fingerprint']:
            problems.append('Host %s has fingerprint %s, the inventory wants %s'
                            % (describe(have), have.get('fingerprint'), options['fingerprint']))

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
        elif (profile.get('name') != want.get('config_profile')
              or inbound_tag.get(inbound_uuid) != want.get('inbound')):
            problems.append("Host %s is attached to %s/%s, the inventory wants %s/%s"
                            % (describe(have), profile.get('name'), inbound_tag.get(inbound_uuid),
                               want.get('config_profile'), want.get('inbound')))

        # Who the host is shown to: a chain into an exclusive exit only to the
        # squads of that exit's profile, every other host to everyone.
        have_squads = have.get('internalSquads') or {}
        have_restriction = (str(have_squads.get('mode') or 'EXCLUDE').lower(),
                            sorted(squad_name.get(u, u) for u in have_squads.get('squads') or []))
        want_squads = want.get('internal_squads') or {'mode': 'exclude', 'squads': []}
        want_restriction = (want_squads['mode'], sorted(want_squads['squads']))
        if have_restriction != want_restriction:
            problems.append('Host %s is %s squads %s, the inventory wants %s %s'
                            % (describe(have), have_restriction[0], have_restriction[1] or '-',
                               want_restriction[0], want_restriction[1] or '-'))
        elif want_restriction[0] == 'allow_only':
            for name in want_restriction[1]:
                if want.get('inbound') not in squad_tags.get(name, set()):
                    notes.append("Host %s is shown only to squad %s, which does not hold the "
                                 "advertised inbound %s, so its members cannot obtain "
                                 "this host through that squad alone"
                                 % (describe(have), name, want.get('inbound')))

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
            if want['kind'] == 'chain' and active.get('activeConfigProfileUuid') != profile_uuid:
                # A chain's advertised profile controls subscription access;
                # the entry still runs its location profile and routing. Verify
                # wire compatibility instead of requiring identical UUIDs.
                advertised = config_inbound(profile or {}, want.get('inbound'))
                active_profile = profiles.get(active.get('activeConfigProfileUuid')) or {}
                candidates = [config_inbound(active_profile, i.get('tag'))
                              for i in active.get('activeInbounds') or []]
                if (advertised is None or not any(
                        i is not None and _client_transport(i) == _client_transport(advertised)
                        for i in candidates)):
                    problems.append('Node %s bound to chain host %s has no active inbound '
                                    'compatible with %s/%s'
                                    % (node.get('name'), describe(have),
                                       want.get('config_profile'), want.get('inbound')))
            elif active.get('activeConfigProfileUuid') != profile_uuid:
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

    # --- the config profiles: what they embed -------------------------------
    # The snippets a profile embeds decide what its nodes route; an addon such
    # as WARP in a profile it was not declared for is as wrong as one missing.
    for name, want in sorted(want_profiles.items()):
        have = profiles_by_name.get(name)
        if have is None:
            problems.append("Config profile '%s' is not in the panel" % name)
            continue
        have_tags = sorted(i.get('tag') for i in have.get('inbounds') or [])
        if have_tags != sorted(want['inbound_tags']):
            problems.append("Config profile '%s' holds inbounds %s, the inventory wants %s"
                            % (name, ', '.join(have_tags) or '-', ', '.join(sorted(want['inbound_tags']))))
        have_config = have.get('config') or {}
        want_config = want.get('config') or {}
        for part, section in (('outbounds', lambda c: c.get('outbounds')),
                              ('rules', lambda c: (c.get('routing') or {}).get('rules')),
                              ('balancers', lambda c: (c.get('routing') or {}).get('balancers'))):
            have_refs = _snippet_refs(section(have_config))
            want_refs = _snippet_refs(section(want_config))
            if have_refs != want_refs:
                problems.append("Config profile '%s' embeds %s snippets %s, the inventory wants %s"
                                % (name, part, ', '.join(have_refs) or '-', ', '.join(want_refs) or '-'))
        if outbounds_name not in _snippet_refs(have_config.get('outbounds')):
            problems.append("Config profile '%s' does not embed snippet %s" % (name, outbounds_name))
        if rules_name not in _snippet_refs((have_config.get('routing') or {}).get('rules')):
            problems.append("Config profile '%s' does not embed snippet %s" % (name, rules_name))
        if not any(want['inbound_tags'][0] in tags for tags in squad_tags.values()):
            notes.append("Config profile '%s': inbound %s is in no internal squad, so no user "
                         "can connect through it" % (name, want['inbound_tags'][0]))

    for profile in sorted(profiles.values(), key=lambda p: p.get('name') or ''):
        if (not primary.issubset(profile.get('tags') or [])
                and profile.get('name') not in want_profiles
                and not any(((n.get('configProfile') or {}).get('activeConfigProfileUuid'))
                            == profile.get('uuid') for n in nodes_by_uuid.values())):
            notes.append("Config profile '%s' is not the role's and no node activates it; "
                         "delete it by hand once nothing depends on it" % profile.get('name'))

    # --- the nodes: the profile each one activates --------------------------
    for name, want in sorted((model.get('node_profiles') or {}).items()):
        node = nodes_by_name.get(name)
        if node is None:
            problems.append('Node %s is not in the panel' % name)
            continue
        active = node.get('configProfile') or {}
        have_name = (profiles.get(active.get('activeConfigProfileUuid')) or {}).get('name')
        have_inbounds = sorted(i.get('tag') for i in active.get('activeInbounds') or [])
        if have_name != want['config_profile'] or have_inbounds != sorted(want['inbounds']):
            problems.append('Node %s activates %s with %s, the inventory wants %s with %s'
                            % (name, have_name, ', '.join(have_inbounds) or '-',
                               want['config_profile'], ', '.join(sorted(want['inbounds']))))

    # --- the internal squads: the inbounds they are granted -----------------
    for grant in model.get('squad_grants') or []:
        if grant['squad'] not in squads:
            problems.append('Internal squad %s is not in the panel, so it is granted none of %s'
                            % (grant['squad'], ', '.join(grant['inbounds']) or '-'))
            continue
        missing = [t for t in grant['inbounds'] if t not in squad_tags[grant['squad']]]
        if missing:
            problems.append('Internal squad %s lacks inbounds %s'
                            % (grant['squad'], ', '.join(missing)))

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
            'internal_squads': len(squads),
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
