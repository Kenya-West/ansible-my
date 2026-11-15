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

import hashlib
import re

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
                          slot['label'], slot['domain']))
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
                'hosts': [],
                'countries': [],
                'protocols': [],
                'profiles': [],
                'scopes': [],
            })
            # The inventory hostnames behind the domain, which hop relations
            # (remna_node_hops) name, beside the panel names hosts bind to.
            if node['name'] not in slot['hosts']:
                slot['hosts'].append(node['name'])
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


def _chain_entry_allowed(entry, exit_slot, options):
    """Keep legacy country-selected entries; add shared global -> non-global."""
    countries = set(str(c).upper() for c in options.get('entry_country_codes') or [])
    if entry['country'] in countries:
        return True
    entry_scope = entry['scopes'][0]
    return (_as_bool(options.get('entry_global_for_non_global', False))
            and entry_scope['kind'] == 'global'
            and exit_slot['scopes'][0]['geo'] != 'global')


def _chain_pairs(exits, entries, options):
    """Usable chain entries for each exit, independent of profile rendering."""
    pairs = {}
    skip_same_country = _as_bool(options.get('skip_same_country', True))
    for exit_slot in exits:
        excluded = _excluded_entries(options.get('exclude'), exit_slot['domain'])
        if excluded == '*':
            continue
        usable = [entry for entry in entries
                  if _chain_entry_allowed(entry, exit_slot, options)
                  and entry['domain'] not in excluded
                  and entry['domain'] != exit_slot['domain']
                  and not set(entry['nodes']).intersection(exit_slot['nodes'])
                  and not (skip_same_country and entry['country'] == exit_slot['country'])]
        if usable:
            pairs[exit_slot['domain']] = usable
    return pairs


def _remark(slot, labels):
    """A domain's name in the panel: the one the inventory gives it, else its
    generated short name, else the domain label itself."""
    return labels.get(slot['domain']) or labels.get(slot['label']) or slot.get('display') or slot['label']


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


def _merge_profile_config(target, fragment, append_lists=True):
    """Merge nested config mappings; composition lists concatenate in order.

    Per-protocol base config uses the same merge with list replacement, so it
    can override a composed section without losing unrelated routing fields.
    """
    for key, value in fragment.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge_profile_config(target[key], value, append_lists)
        elif append_lists and isinstance(value, list) and isinstance(target.get(key), list):
            target[key].extend(_plain(value))
        else:
            target[key] = _plain(value)
    return target


def _refuse_empty_conditions(rule, where):
    """Xray reads an empty domain or ip list as no condition at all, so such a
    rule would send all of its route's traffic where it meant to send some."""
    if not isinstance(rule, dict) or not ('outboundTag' in rule or 'balancerTag' in rule):
        return
    for field in ('domain', 'ip'):
        if field in rule and not rule[field]:
            raise AnsibleFilterError(
                '%s has a routing rule with an empty %s list, which Xray reads as matching '
                'everything: %r' % (where, field, rule))


def _prepare_composition(options):
    """Validate ordered fragments and collect their snippet definitions once."""
    if 'addons' in options or 'profile_common' in options:
        raise AnsibleFilterError('Replace profile_common/addons with profile_composition '
                                 '(vpn_server_remnawave_config_profiles_composition)')
    composition = _plain(options.get('profile_composition') or [])
    if not isinstance(composition, list):
        raise AnsibleFilterError('Config profile composition must be a list of named fragments')
    names, snippets = set(), {}
    for fragment in composition:
        if not isinstance(fragment, dict) or not fragment.get('name'):
            raise AnsibleFilterError('Every config profile composition fragment needs a name')
        name = fragment['name']
        if name in names:
            raise AnsibleFilterError('Duplicate config profile composition fragment %s' % name)
        names.add(name)
        unknown = set(fragment) - {'name', 'profiles', 'config', 'snippets', 'inbounds'}
        if unknown:
            raise AnsibleFilterError('Composition fragment %s has unknown fields %s; put '
                                     'Xray settings inside config' % (name, ', '.join(sorted(unknown))))
        # Validate selectors even when this panel has no profile they could match.
        _matches(fragment.get('profiles'), {k: '' for k in ('name',) + _SELECTOR_KEYS})
        config = fragment.get('config') or {}
        if not isinstance(config, dict) or 'inbounds' in config:
            raise AnsibleFilterError('Composition fragment %s needs a config mapping without '
                                     'inbounds; define inbounds in profiles_base' % name)
        routing = config.get('routing') or {}
        if not isinstance(routing, dict):
            raise AnsibleFilterError('Composition fragment %s config.routing must be a mapping' % name)
        for section, value in (('outbounds', config.get('outbounds')),
                               ('routing.rules', routing.get('rules')),
                               ('routing.balancers', routing.get('balancers'))):
            if value is not None and (not isinstance(value, list)
                                      or any(not isinstance(item, dict) for item in value)):
                raise AnsibleFilterError('Composition fragment %s config.%s must be a list '
                                         'of mappings' % (name, section))
        for rule in routing.get('rules') or []:
            _refuse_empty_conditions(rule, 'Composition fragment %s' % name)
        for snippet in _as_list(fragment.get('snippets')):
            if (not isinstance(snippet, dict) or not snippet.get('name')
                    or not isinstance(snippet.get('snippet'), list)):
                raise AnsibleFilterError('Composition fragment %s snippets need name and '
                                         'snippet (a list)' % name)
            for rule in snippet['snippet']:
                _refuse_empty_conditions(rule, 'Snippet %s' % snippet['name'])
            previous = snippets.get(snippet['name'])
            if previous is not None and previous != snippet:
                raise AnsibleFilterError('Conflicting definitions of composition snippet %s'
                                         % snippet['name'])
            snippets[snippet['name']] = snippet
    return composition, list(snippets.values())


def _render_profiles(scopes_in_use, options, composition, warnings):
    """Render every config profile the panel needs.

    Every base profile is rendered for the global scope, always. Other scopes
    get the protocols their nodes serve or their location/exclusive chains need,
    so a scope without nodes produces no profile at all.
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

    wanted = [({'kind': 'global', 'scope': 'global', 'geo': 'global'}, base['protocol'])
              for base in bases]
    for (kind, scope, geo), protocols in sorted(scopes_in_use.items()):
        missing = sorted(p for p in protocols if p not in base_of)
        if missing:
            raise AnsibleFilterError(
                'No base config profile serves protocol %s, required by nodes or chains '
                'of scope %s; add it to vpn_server_remnawave_config_profiles_base'
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
            'composition': [],
            'squads': [],
        }

        config = {}
        for fragment in composition:
            if not _matches(fragment.get('profiles'), profile):
                continue
            scoped = [inbound_map[t] for t in _as_list(fragment.get('inbounds')) if t in inbound_map]
            if _as_list(fragment.get('inbounds')) and not scoped:
                continue
            contribution = _plain(fragment.get('config') or {})
            if scoped:
                for rule in (contribution.get('routing') or {}).get('rules') or []:
                    if 'snippet' in rule:
                        raise AnsibleFilterError(
                            'Composition fragment %s scopes its rules to inbounds, so they '
                            'must be inline: a snippet reference cannot carry an inboundTag'
                            % fragment['name'])
                    rule['inboundTag'] = scoped
            _merge_profile_config(config, contribution)
            profile['composition'].append(fragment['name'])
        _merge_profile_config(config, base.get('config') or {}, append_lists=False)
        config['inbounds'] = inbounds
        config.setdefault('outbounds', [])
        config.setdefault('routing', {}).setdefault('rules', [])
        if not config['routing'].get('balancers'):
            config['routing'].pop('balancers', None)
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
            # transit_profiles: profiles granted only to let the squad in at a
            # chain's entry (remnawave_model), not to show it their hosts.
            out[squad] = {'squad': squad, 'inbounds': [], 'profiles': [], 'transit_profiles': []}
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


def _final_mask_bounds(name, value, lowest):
    """Read a number or a "low-high" range of a mask into its two ends."""
    match = re.match(r'^(\d+)(?:-(\d+))?$', str(value).strip())
    if isinstance(value, bool) or not match:
        raise AnsibleFilterError('final_mask %s must be a number or a low-high range, '
                                 'got %r' % (name, value))
    low = int(match.group(1))
    high = int(match.group(2)) if match.group(2) else low
    if low < lowest or low > high:
        raise AnsibleFilterError('final_mask %s must be ascending and start at %d or more, '
                                 'got %s' % (name, lowest, value))
    return low, high


def _final_mask_range(name, value, lowest, address):
    """A value of a mask, as the string Xray reads.

    Always a string: the panel holds what was sent, so 6 and "6" must not read
    as a change. Xray draws from a range by itself, for every connection.
    {pick: "low-high"} is settled here instead, once per domain: a hash of the
    domain and the value's place, so it differs per domain and side yet never
    changes between runs, which would rewrite the panel every time.
    """
    if not isinstance(value, dict):
        _final_mask_bounds(name, value, lowest)
        return str(value).strip()
    if set(value) != {'pick'}:
        raise AnsibleFilterError('final_mask %s must be a value or {pick: low-high}, got %r'
                                 % (name, value))
    low, high = _final_mask_bounds(name, value['pick'], lowest)
    digest = hashlib.sha256(('%s|%s' % (address, name)).encode('utf-8')).digest()
    return str(low + int.from_bytes(digest[:8], 'big') % (high - low + 1))


def _final_mask_ranges(name, values, lowest, last_lowest, address):
    """The list of values of a mask; Xray repeats its last entry."""
    if not isinstance(values, (list, tuple)) or not values:
        raise AnsibleFilterError('final_mask %s must be a non-empty list, got %r' % (name, values))
    last = len(values) - 1
    return [_final_mask_range('%s[%d]' % (name, i), value,
                              last_lowest if i == last else lowest, address)
            for i, value in enumerate(values)]


def _final_mask_aligned(name, packets, hello):
    """The size that ends the first write right after the tlshello mask's records.

    Those are its lengths but the last, which repeats, each with a 5-byte header.
    It needs them to be known here and to leave as one write, or no one size
    falls on their end.
    """
    if hello is None or _final_mask_bounds(name + ' packets', packets, 1)[0] != 1:
        raise AnsibleFilterError('final_mask %s: aligned needs a tlshello mask before it, '
                                 'and packets starting at the first write' % name)
    records = hello['lengths'][:-1]
    if not records or any('-' in length for length in records):
        raise AnsibleFilterError('final_mask %s: aligned needs tlshello lengths without '
                                 'ranges, use pick, and a last one to repeat; got %s'
                                 % (name, hello['lengths']))
    if hello['delays'] != ['0']:
        raise AnsibleFilterError('final_mask %s: aligned needs tlshello delays of just "0", '
                                 'which keep its records in one write' % name)
    low, high = _final_mask_bounds(name + ' tlshello maxSplit', hello['maxSplit'], 0)
    if high >= 1 and max(low, 1) <= len(records):
        raise AnsibleFilterError('final_mask %s: aligned needs a tlshello maxSplit of 0 or '
                                 'above %d, which cuts its records short otherwise'
                                 % (name, len(records)))
    return str(sum(int(length) + 5 for length in records))


def _final_mask_fragment(name, settings, address, hello):
    """Check the settings of one fragment mask and rebuild them.

    Xray drops a key it does not know without a word, which is how "interval"
    once left a mask with no delays, so anything else is refused here. ``hello``
    is the settings of the tlshello mask before this one, if any.
    """
    if not isinstance(settings, dict):
        raise AnsibleFilterError('final_mask %s needs settings' % name)
    unknown = sorted(set(settings) - {'packets', 'lengths', 'delays', 'maxSplit'})
    if unknown:
        raise AnsibleFilterError('final_mask %s has unknown settings %s; it takes packets, '
                                 'lengths, delays and maxSplit' % (name, ', '.join(unknown)))
    packets = settings.get('packets')
    tlshello = str(packets).lower() == 'tlshello'
    if not tlshello:
        _final_mask_bounds(name + ' packets', packets, 1)
    lengths = settings.get('lengths')
    aligned = None
    if isinstance(lengths, (list, tuple)) and lengths and str(lengths[0]) == 'aligned':
        if tlshello:
            raise AnsibleFilterError('final_mask %s: only a stream mask can be aligned' % name)
        if len(lengths) < 2:
            raise AnsibleFilterError('final_mask %s: aligned needs a length after it, '
                                     'for the rest of the stream' % name)
        aligned = _final_mask_aligned(name, packets, hello)
        lengths = [aligned] + list(lengths[1:])
    # A zero-length TLS record is an empty one, which Go TLS rejects. The stream
    # form may skip a write, but its last length repeats and must make progress.
    return {
        'packets': str(packets).strip(),
        'lengths': _final_mask_ranges(name + ' lengths', lengths, 1 if tlshello else 0, 1, address),
        'delays': _final_mask_ranges(name + ' delays', settings.get('delays'), 0, 0, address),
        'maxSplit': _final_mask_range(name + ' maxSplit', settings.get('maxSplit', 0), 0, address),
    }


def remnawave_final_mask(spec, side, address):
    """The finalmask of a domain on a side, 'hosts' or 'outbounds', or {} when off.

    ``spec`` is vpn_server_remnawave_final_mask. The first mask of tcp gets the
    write first. tlshello only recognises a whole ClientHello, so it has to come
    before any mask slicing the stream. Fragmenting only touches writes and the
    peer reassembles ordinary TLS records, so hosts and outbounds need not match.
    """
    side_spec = (spec or {}).get(side) or {}
    if not _as_bool(side_spec.get('enabled')):
        return {}
    masks = side_spec.get('tcp')
    if not isinstance(masks, (list, tuple)) or not masks:
        raise AnsibleFilterError('final_mask %s is enabled, so its tcp must list masks' % side)
    out = []
    hello = None
    stream_seen = False
    for position, mask in enumerate(masks):
        name = '%s tcp[%d]' % (side, position)
        if not isinstance(mask, dict) or mask.get('type') != 'fragment':
            raise AnsibleFilterError('final_mask %s: only the fragment type is supported' % name)
        settings = _final_mask_fragment(name, mask.get('settings'), address, hello)
        if settings['packets'].lower() != 'tlshello':
            stream_seen = True
        elif stream_seen:
            raise AnsibleFilterError('final_mask %s: tlshello must come before the masks '
                                     'slicing the stream' % name)
        else:
            hello = settings
        out.append({'type': 'fragment', 'settings': settings})
    return {'tcp': out}


def remnawave_route_uuid(uuid, route):
    """``uuid`` carrying VLESS route ``route``, the way the panel writes a
    host's vlessRouteId into its clients' UUIDs: the hex of bytes 6-7 (the
    third group) replaced by the route. Xray ignores those bytes when it looks
    the user up and routes by them (vlessRoute), so a chain outbound tells the
    next hop what to do with the traffic it hands over. Route 0 is written as
    0000, unlike the panel, which leaves a UUID alone for route 0."""
    text = str(uuid or '').strip().lower()
    if not re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', text):
        raise AnsibleFilterError('remnawave_route_uuid needs a UUID, got %r' % (uuid,))
    number = _route_number(route)
    if number is None or not 0 <= number <= 0xFFFF:
        raise AnsibleFilterError('remnawave_route_uuid needs a route from 0 to 65535, got %r'
                                 % (route,))
    return text[:14] + '%04x' % number + text[18:]


def _uuid_route(uuid):
    """The route a UUID carries (its bytes 6-7), or None when it is not a UUID."""
    text = str(uuid or '').strip().lower()
    if not re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', text):
        return None
    return int(text[14:18], 16)


# --- hops between nodes (remna_node_hops) -----------------------------------

_HOPS_KEYS = ('from', 'hidden', 'show_entry', 'publish_direct', 'egress')
_HOPS_FROM_KEYS = ('host', 'hidden', 'show_entry')
_EGRESS_KEYS = ('interface', 'family', 'gateway')
_EGRESS_FAMILIES = ('ipv4', 'ipv6', 'dual')
_FINAL = 0


class _RepeatedNode(Exception):
    """A path would pass the same Ansible host twice."""


def _hops_of(node):
    """A node's remna_node_hops, normalized.

    ``from`` lists the Ansible hosts this node takes traffic from, each a
    hostname or {host, hidden}; ``hidden`` is the default of every relation;
    ``publish_direct`` keeps a node with relations published on its own;
    ``egress`` is only checked here, the node role acts on it.
    """
    name = node['name']
    raw = node.get('hops') or {}
    if not isinstance(raw, dict):
        raise AnsibleFilterError('remna_node_hops of %s must be a mapping, got %r' % (name, raw))
    unknown = sorted(set(raw) - set(_HOPS_KEYS))
    if unknown:
        raise AnsibleFilterError('remna_node_hops of %s has unknown keys %s; it takes %s'
                                 % (name, ', '.join(unknown), ', '.join(_HOPS_KEYS)))
    hidden_default = _as_bool(raw.get('hidden', True))
    show_default = _as_bool(raw.get('show_entry', True))
    items = raw.get('from') or []
    if isinstance(items, (str, dict)):
        items = [items]
    relations, seen = [], set()
    for item in items:
        if isinstance(item, str):
            item = {'host': item}
        if not isinstance(item, dict) or not item.get('host'):
            raise AnsibleFilterError('remna_node_hops.from of %s takes hostnames or {host, hidden}, '
                                     'got %r' % (name, item))
        unknown = sorted(set(item) - set(_HOPS_FROM_KEYS))
        if unknown:
            raise AnsibleFilterError('remna_node_hops.from of %s: %s has unknown keys %s; it takes %s'
                                     % (name, item['host'], ', '.join(unknown),
                                        ', '.join(_HOPS_FROM_KEYS)))
        host = str(item['host'])
        if host == name:
            raise AnsibleFilterError(
                'remna_node_hops.from of %s names the host itself. A second address of the '
                'same machine is a hop through remna_node_hops.egress (interface, family), '
                'not a relation.' % name)
        if host in seen:
            raise AnsibleFilterError('remna_node_hops.from of %s names %s twice' % (name, host))
        seen.add(host)
        hidden = item.get('hidden')
        shown = item.get('show_entry')
        relations.append({'host': host,
                          'hidden': hidden_default if hidden is None else _as_bool(hidden),
                          'show_entry': show_default if shown is None else _as_bool(shown)})
    egress = raw.get('egress') or {}
    if not isinstance(egress, dict):
        raise AnsibleFilterError('remna_node_hops.egress of %s must be a mapping, got %r'
                                 % (name, egress))
    unknown = sorted(set(egress) - set(_EGRESS_KEYS))
    if unknown:
        raise AnsibleFilterError('remna_node_hops.egress of %s has unknown keys %s; it takes %s'
                                 % (name, ', '.join(unknown), ', '.join(_EGRESS_KEYS)))
    family = str(egress.get('family') or 'ipv4')
    if family not in _EGRESS_FAMILIES:
        raise AnsibleFilterError('remna_node_hops.egress.family of %s must be one of %s, got %r'
                                 % (name, ', '.join(_EGRESS_FAMILIES), family))
    return {
        'from': relations,
        'publish_direct': _as_bool(raw.get('publish_direct', False)),
        'egress': {'interface': str(egress.get('interface') or ''), 'family': family},
    }


def _find_cycle(edges):
    """A cycle of a directed graph ({vertex: [successors]}) as a closed list of
    vertices, or None. Vertices and successors are visited in sorted order, so
    the cycle reported is the same on every run."""
    state, stack = {}, []

    def visit(vertex):
        state[vertex] = 'open'
        stack.append(vertex)
        for successor in sorted(edges.get(vertex) or []):
            if state.get(successor) == 'open':
                return stack[stack.index(successor):] + [successor]
            if successor not in state:
                found = visit(successor)
                if found:
                    return found
        stack.pop()
        state[vertex] = 'done'
        return None

    for vertex in sorted(edges):
        if vertex not in state:
            found = visit(vertex)
            if found:
                return found
    return None


class _Hops(object):
    """The hop relations of a panel's nodes, checked and lifted to domains.

    A relation U -> D (D lists U in remna_node_hops.from) is *hidden* by
    default: D then carries on whatever U would send out itself, and is not
    published. Hidden relations hang off the Ansible host, so every domain of
    U - its exit as much as its chain entry - continues into D: U's tail. A
    *visible* relation publishes "D | by U" instead, entered through U's chain
    domain.
    """

    def __init__(self, nodes, exits, entries):
        self.node = dict((n['name'], n) for n in nodes)
        for node in nodes:
            node['hop'] = _hops_of(node)
        self.exit_of = {}
        self.entry_of = {}
        for slot in exits:
            for host in slot['hosts']:
                self.exit_of.setdefault(host, []).append(slot)
        for slot in entries:
            for host in slot['hosts']:
                self.entry_of.setdefault(host, []).append(slot)
        self.hidden_down = {}
        self.visible = []
        # (upstream domain, downstream domain) of the visible relations
        # published under the downstream's name alone (show_entry: false).
        self.unnamed_entry = set()
        self.relations = []
        edges = {}
        for node in nodes:
            for relation in node['hop']['from']:
                self._check(relation['host'], node, relation['hidden'])
                edges.setdefault(relation['host'], []).append(node['name'])
                self.relations.append({'from': relation['host'], 'to': node['name'],
                                       'hidden': relation['hidden']})
                if relation['hidden']:
                    self.hidden_down.setdefault(relation['host'], []).append(node['name'])
                else:
                    self.visible.append((self.entry_of[relation['host']][0],
                                         self.exit_of[node['name']][0]))
                    if not relation['show_entry']:
                        self.unnamed_entry.add((self.entry_of[relation['host']][0]['domain'],
                                                self.exit_of[node['name']][0]['domain']))
        cycle = _find_cycle(edges)
        if cycle:
            raise AnsibleFilterError(
                'remna_node_hops: hop relations form a cycle: %s. Each arrow means the next '
                'host lists the previous one in remna_node_hops.from; remove one of these '
                'relations.' % ' → '.join(cycle))
        for slot in exits + entries:
            self._agree(slot)
        slot_edges = {}
        for slot in exits + entries:
            slot_edges.setdefault(slot['domain'], []).extend(
                t['domain'] for t in self.tails(slot))
        for upstream, downstream in self.visible:
            slot_edges.setdefault(upstream['domain'], []).append(downstream['domain'])
        cycle = _find_cycle(slot_edges)
        if cycle:
            raise AnsibleFilterError(
                'remna_node_hops: the domains of the hop relations form a cycle: %s. Nodes '
                'behind one domain take part in each other\'s relations; remove one of them.'
                % ' → '.join(cycle))
        self.visible.sort(key=lambda pair: (pair[1]['domain'], pair[0]['domain']))
        self.relations.sort(key=lambda r: (r['to'], r['from']))

    def _check(self, upstream, downstream, hidden):
        name = downstream['name']
        if upstream not in self.node:
            raise AnsibleFilterError(
                'remna_node_hops.from of %s names %s, which is no node of this panel: a host '
                'of the node group relating to the panel and publishing domains'
                % (name, upstream))
        source = self.node[upstream]
        exits = self.exit_of.get(name) or []
        if len(exits) != 1:
            raise AnsibleFilterError(
                'remna_node_hops: %s takes traffic from %s, so it needs exactly one direct '
                '(net-location) domain for it to be dialed by; it has %s'
                % (name, upstream, ', '.join(s['domain'] for s in exits) or 'none'))
        if hidden:
            if source['scope']['geo'] != downstream['scope']['geo']:
                raise AnsibleFilterError(
                    'remna_node_hops: the hidden relation %s -> %s crosses censorship geos '
                    '(%s -> %s). A hidden node carries on what its upstream sends out, inside '
                    'one geo; publish it with hidden: false to chain across them.'
                    % (upstream, name, source['scope']['geo'], downstream['scope']['geo']))
            scope = downstream['scope']
            if scope['kind'] == 'exclusive' and source['scope'] != scope:
                raise AnsibleFilterError(
                    'remna_node_hops: the hidden relation %s -> %s would let everyone %s '
                    'serves exit through exclusive node %s (%s). Hide an exclusive node only '
                    'behind a node of the same exclusive profile.'
                    % (upstream, name, upstream, name, scope['scope']))
        elif len(self.entry_of.get(upstream) or []) != 1:
            raise AnsibleFilterError(
                'remna_node_hops: %s is published through %s (hidden: false), so %s needs '
                'exactly one chain (chain-location) domain to be entered by; it has %s'
                % (name, upstream, upstream,
                   ', '.join(s['domain'] for s in self.entry_of.get(upstream) or []) or 'none'))

    def _agree(self, slot):
        """Nodes behind one domain are one entity in the panel and run the same
        rules, so they must agree on every relation they take part in."""
        def view(host):
            hop = self.node[host]['hop']
            return (sorted((r['host'], r['hidden']) for r in hop['from']),
                    hop['publish_direct'] if hop['from'] else None,
                    sorted(self.hidden_down.get(host) or []),
                    sorted(d for u, d in ((r['from'], r['to']) for r in self.relations
                                          if not r['hidden']) if u == host))
        views = dict((host, view(host)) for host in slot['hosts'])
        if len(set(repr(v) for v in views.values())) > 1:
            raise AnsibleFilterError(
                'remna_node_hops: %s is served by %s, which declare different hop relations. '
                'Nodes behind one domain run the same routing, so give them the same '
                'remna_node_hops.from and name all of them wherever one is named.'
                % (slot['domain'], ', '.join(sorted(views))))

    def egress_family(self, slot):
        """The family a domain's nodes leave in through an egress interface of
        their own (remna_node_hops.egress), when they all agree; else ''."""
        families = set(self.node[h]['hop']['egress']['family']
                       if self.node[h]['hop']['egress']['interface'] else ''
                       for h in slot['hosts'])
        return families.pop() if len(families) == 1 else ''

    def published(self, slot):
        """Whether a domain is published on its own: its nodes take traffic from
        no one, or say publish_direct."""
        return all(not self.node[h]['hop']['from'] or self.node[h]['hop']['publish_direct']
                   for h in slot['hosts'])

    def tails(self, slot):
        """The direct domains of the hidden nodes a domain's traffic continues into."""
        found = {}
        for host in slot['hosts']:
            for down in self.hidden_down.get(host) or []:
                target = self.exit_of[down][0]
                found[target['domain']] = target
        return [found[d] for d in sorted(found)]

    def hosts_of(self, slot):
        """Every Ansible host a domain's traffic passes, its tail included."""
        hosts = set(slot['hosts'])
        for tail in self.tails(slot):
            hosts |= self.hosts_of(tail)
        return hosts


def _geo_of(slot):
    return slot['scopes'][0]['geo'] if slot.get('scopes') else 'global'


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
    composition, profile_snippets = _prepare_composition(options)

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
    # to agree on the geo that decides which composition fragments it gets.
    exclusive_geos = {}
    for node in nodes:
        if node['scope']['kind'] == 'exclusive':
            exclusive_geos.setdefault(node['scope']['scope'], set()).add(node['scope']['geo'])
    split = sorted(name for name, geos in exclusive_geos.items() if len(geos) > 1)
    if split:
        raise AnsibleFilterError('Exclusive profiles with nodes in different censorship '
                                 'geos: %s' % ', '.join(split))

    # Plan chains before rendering profiles: their client-facing transport is
    # the entry's, but access is granted by the exit's scope. Location and
    # exclusive exits need a profile variant for each usable entry protocol.
    all_exits = [
        _settle(slot, default_protocol, warnings, 'Direct domain')
        for _, slot in sorted(_collect(nodes, set(options['direct_domain_types'])).items())
    ]
    all_entries = [
        _settle(slot, default_protocol, warnings, 'Chain domain')
        for _, slot in sorted(_collect(nodes, set(options['entry_domain_types'])).items())
    ]
    # Hop relations (remna_node_hops): a node taking traffic from another is
    # out of both pools unless it says publish_direct; a hidden one is only
    # ever reached through the tail of its upstream, a visible one through the
    # "D | by U" host of its relation.
    hops = _Hops(nodes, all_exits, all_entries)
    exits = [s for s in all_exits if hops.published(s)]
    entries = [s for s in all_entries if hops.published(s)]
    entry_countries = set(str(c).upper() for c in options.get('entry_country_codes') or [])
    global_entries = _as_bool(options.get('entry_global_for_non_global', False))
    entries = [e for e in entries if e['country'] in entry_countries
               or (global_entries and e['scopes'][0]['kind'] == 'global')]
    # A node leaving over IPv6 only cannot dial another node (their domains
    # have IPv4 records only), so it is an exit and never an automatic entry.
    entries = [e for e in entries if hops.egress_family(e) != 'ipv6']
    pairs = _chain_pairs(exits, entries, options)
    # A visible relation publishes its own "D | by U"; an automatic pair of the
    # same two domains would collide with it. A pair whose tails share a node
    # would pass that node twice.
    covered = set((u['domain'], d['domain']) for u, d in hops.visible)
    for exit_domain in list(pairs):
        exit_slot = next(s for s in exits if s['domain'] == exit_domain)
        exit_hosts = hops.hosts_of(exit_slot)
        kept = []
        for entry in pairs[exit_domain]:
            if (entry['domain'], exit_domain) in covered:
                continue
            shared = hops.hosts_of(entry) & exit_hosts
            if shared:
                warnings.append('No chain host of %s through %s: both reach %s through their '
                                'hop relations' % (exit_domain, entry['domain'],
                                                   ', '.join(sorted(shared))))
                continue
            kept.append(entry)
        if kept:
            pairs[exit_domain] = kept
        else:
            del pairs[exit_domain]
    planned_domains = set(o['address'] for o in options.get('outbounds') or []
                          if o.get('kind', 'location') == 'location')
    for exit_slot in exits:
        if exit_slot['domain'] not in planned_domains:
            continue
        scope = exit_slot['scopes'][0]
        if scope['kind'] != 'global':
            key = (scope['kind'], scope['scope'], scope['geo'])
            scopes_in_use[key].update(e['protocol'] for e in pairs.get(exit_slot['domain'], []))
    # A visible relation into a location or exclusive node advertises that
    # node's scope with its upstream's transport, as a chain host does.
    for upstream, downstream in hops.visible:
        if downstream['domain'] not in planned_domains:
            raise AnsibleFilterError(
                'remna_node_hops: %s is published through %s, but no outbound is planned for '
                'its domain %s' % (downstream['hosts'][0], upstream['hosts'][0],
                                   downstream['domain']))
        scope = downstream['scopes'][0]
        if scope['kind'] != 'global':
            scopes_in_use[(scope['kind'], scope['scope'], scope['geo'])].add(upstream['protocol'])

    profiles = _render_profiles(scopes_in_use, options, composition, warnings)
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

    # Every domain the setup uses: the two pools, both ends of the visible
    # relations and every hidden node in a tail of any of them.
    used, seen_domains = [], set()

    def use(slot):
        if id(slot) in seen_domains:
            return
        seen_domains.add(id(slot))
        used.append(slot)
        for tail in hops.tails(slot):
            use(tail)

    for slot in exits + entries + [s for pair in hops.visible for s in pair]:
        use(slot)

    # Every node behind one domain must activate the same profile, even when
    # the scope agrees but its primary transports do not.
    for slot in used:
        slot['profiles'] = sorted(set(node_profiles[n]['config_profile'] for n in slot['nodes']))
        _settle(slot, default_protocol, [], 'Domain')

    # Short names are per collection: an entry outside both eligible pools is
    # gone by now, so it takes no number with it.
    region_codes = options.get('region_codes') or {}
    flag_symbols = options.get('flag_symbols') or {}
    for slot in used:
        profile = profile_by_name[slot['profiles'][0]]
        slot['profile'] = profile['name']
        slot['inbound'] = profile['inbound_tags'][0]
        slot['scope_kind'] = profile['kind']
        slot['scope'] = profile['scope']

    # Exclusive exits are counted apart, per exclusive profile, so neither the
    # shared numbering nor an exclusive squad's own list has gaps; their names
    # carry the profile's name, since a remark has to be unique panel-wide.
    # Both ends of a visible relation are named with the pools; a hidden node
    # has no name of its own, as it is never published.
    def group_of(slot):
        return slot['scope'] if slot['scope_kind'] == 'exclusive' else ''

    named_exits = exits + [d for _, d in hops.visible if all(d is not s for s in exits)]
    named_entries = entries + [u for u, _ in hops.visible if all(u is not s for s in entries)]
    named_exits = [s for i, s in enumerate(named_exits) if all(s is not t for t in named_exits[:i])]
    named_entries = [s for i, s in enumerate(named_entries)
                     if all(s is not t for t in named_entries[:i])]
    exclusive_format = options.get('remark_exclusive_format') or '{name} · {profile}'
    for collection in (named_exits, named_entries):
        for group in sorted(set(group_of(s) for s in collection)):
            members = [s for s in collection if group_of(s) == group]
            _name(members, region_codes, flag_symbols)
            if group:
                for slot in members:
                    slot['display'] = exclusive_format.format(
                        name=slot['display'], profile=group)

    # A node whose own traffic leaves in another family than clients reach it
    # in says so in its name: "🇳🇱 EU-6 (IPv6)".
    egress_suffix = options.get('remark_egress_suffix')
    if egress_suffix is None:
        egress_suffix = {'ipv6': ' (IPv6)'}
    # Only as an exit: entered for another node, it hands over in IPv4.
    for slot in named_exits:
        slot['display'] += str((egress_suffix or {}).get(hops.egress_family(slot)) or '')

    # --- route ids: what each node does with the traffic it is handed -------
    # A route id is an action: where a node sends what arrives carrying it
    # (one next hop, or several behind a balancer) and with which route the
    # outbound hands it over, plus what the node does with local traffic
    # itself. A host carries the id of the action of the node it dials; every
    # chain outbound carries the next node's id in its UUID
    # (remnawave_route_uuid), so the route travels hop by hop, and the last
    # hop hands over route 0: the node it reaches is the exit. The rules are
    # one snippet in every profile, so an id must mean the same anywhere -
    # which it does, being the action itself.
    planned = [o for o in (options.get('outbounds') or [])
               if o.get('kind', 'location') == 'location']
    position_of = {}
    tag_of = {}
    plan_of = {}
    for position, outbound in enumerate(planned):
        position_of.setdefault(outbound['address'], position)
        tag_of.setdefault(outbound['address'], outbound['tag'])
        plan_of.setdefault(outbound['address'], outbound)

    unplanned = sorted(e['domain'] for e in exits
                       if e['domain'] in pairs and e['domain'] not in tag_of)
    if unplanned:
        warnings.append(
            'Exits with chain entries but no planned outbound get no route id, '
            'rule or chain hosts: %s' % ', '.join(unplanned))
    chained = sorted(
        (e for e in exits if e['domain'] in pairs and e['domain'] in tag_of),
        key=lambda e: position_of[e['domain']])

    performers = {}

    def arrive(slot, cont, passed=frozenset()):
        """The action ``slot`` takes on traffic that, past its own tail,
        continues as ``cont`` ((next head, its cont) or None at the exit),
        as a nested key; _FINAL when it is the exit itself."""
        hosts = set(slot['hosts'])
        if hosts & passed:
            raise _RepeatedNode(', '.join(sorted(hosts & passed)))
        passed = passed | hosts
        tails = hops.tails(slot)
        if tails:
            key = ('act', tuple((t['domain'], arrive(t, cont, passed)) for t in tails), None)
        elif cont is None:
            return _FINAL
        else:
            head, rest = cont
            # Local traffic of a censored geo leaves at the last node inside
            # it, through that node's WARP, never through a VPS address.
            local = (_geo_of(slot) if _geo_of(slot) != 'global' and _geo_of(head) == 'global'
                     else None)
            key = ('act', ((head['domain'], arrive(head, rest, passed)),), local)
        performers.setdefault(key, []).append(slot)
        return key

    def path_list(slot, cont):
        """Every way through, as lists of the domains passed."""
        tails = hops.tails(slot)
        if tails:
            return [[slot['domain']] + rest for t in tails for rest in path_list(t, cont)]
        if cont is None:
            return [[slot['domain']]]
        head, rest = cont
        return [[slot['domain']] + more for more in path_list(head, rest)]

    # The hosts' journeys, in the order hosts are generated: direct hosts,
    # the automatic chains, then the visible relations.
    journeys = []
    for exit_slot in exits:
        journeys.append(('direct', exit_slot, None, exit_slot, None))
    for exit_slot in chained:
        for entry in pairs[exit_slot['domain']]:
            journeys.append(('chain', entry, (exit_slot, None), exit_slot, entry))
    for upstream, downstream in hops.visible:
        journeys.append(('relation', upstream, (downstream, None), downstream, upstream))

    keys_in_order = []

    def collect(key):
        if key == _FINAL or key in keys_in_order:
            return
        keys_in_order.append(key)
        for _, child in key[1]:
            collect(child)

    journey_keys = []
    for journey in journeys:
        kind, head, cont = journey[0], journey[1], journey[2]
        try:
            key = arrive(head, cont)
        except _RepeatedNode as repeated:
            raise AnsibleFilterError(
                'remna_node_hops: the way from %s to %s passes %s twice'
                % (head['domain'], (cont or (head,))[0]['domain'], repeated))
        journey_keys.append(key)
        collect(key)

    # Legacy ids first: the n-th chained exit's action keeps base + n, as it
    # had before actions, whenever an entry without a tail reaches it.
    base = int(options['route_id_base'])
    ids = {}
    for position, exit_slot in enumerate(chained):
        for entry in pairs[exit_slot['domain']]:
            if hops.tails(entry):
                continue
            key = arrive(entry, (exit_slot, None))
            if key not in ids and base + position not in ids.values():
                ids[key] = base + position
            break
    next_id = base + len(chained)
    for key in keys_in_order:
        if key in ids:
            continue
        while next_id in ids.values():
            next_id += 1
        ids[key] = next_id
        next_id += 1

    def carried(child):
        return 0 if child == _FINAL else ids[child]

    # One outbound per next hop and route it hands over: the planned outbound
    # of the domain for route 0, an out-hop one per other route.
    hop_prefix = options.get('hop_tag_prefix') or 'out-hop'
    wanted_outbounds = set()
    for key in keys_in_order:
        for domain, child in key[1]:
            if domain not in tag_of:
                raise AnsibleFilterError(
                    'remna_node_hops: %s is dialed as a next hop but has no planned outbound '
                    '(vpn_server_remnawave_snippets_outbounds_plan)' % domain)
            wanted_outbounds.add((domain, carried(child)))
    hop_outbounds = []
    hop_tag = {}
    for sequence, (route, domain) in enumerate(sorted((r, d) for d, r in wanted_outbounds if r)):
        if sequence >= 999:
            raise AnsibleFilterError('More than 999 hop outbounds; their tags would no longer '
                                     'have a fixed width')
        tag = '%s-%03d-%s' % (hop_prefix, sequence + 1, _label(domain))
        hop_tag[(domain, route)] = tag
        outbound = dict(_plain(plan_of[domain]))
        outbound.update({'tag': tag, 'address': domain, 'route': route})
        hop_outbounds.append(outbound)

    def outbound_tag(domain, route):
        return tag_of[domain] if route == 0 else hop_tag[(domain, route)]

    def finals(key):
        """The domains a route's traffic exits at, past every next hop."""
        out = set()
        for domain, child in key[1]:
            out |= set([domain]) if child == _FINAL else finals(child)
        return out

    geo_of_domain = dict((s['domain'], _geo_of(s)) for s in used)
    slot_by_domain = dict((s['domain'], s) for s in used)
    balancer_prefix = options.get('balancer_hops_prefix') or 'bal-hop'
    routes = []
    for key, number in sorted(ids.items(), key=lambda item: item[1]):
        nexts = [{'address': domain, 'carried': carried(child),
                  'tag': outbound_tag(domain, carried(child))} for domain, child in key[1]]
        doers = performers.get(key) or []
        routes.append({
            'id': number,
            'next': nexts,
            'local': key[2],
            'balancer': ('%s-%d' % (balancer_prefix, number)) if len(nexts) > 1 else None,
            'performed_by': sorted(set(s['domain'] for s in doers)),
            'profiles': sorted(set(s['profile'] for s in doers)),
            'final_geos': sorted(set(geo_of_domain[d] for d in finals(key))),
        })

    # A node that egresses over IPv6 only is kept from IPv4 altogether, but
    # for the nodes that take traffic from it (remna_node_hops.from names it):
    # its egress routes IPv4 to exactly those (roles/install_vpn_caddy_remna).
    # Anything else it would have to dial has IPv4 records only.
    for route in routes:
        for domain in route['performed_by']:
            slot = slot_by_domain[domain]
            for host in slot['hosts']:
                if hops.node[host]['hop']['egress']['family'] != 'ipv6':
                    continue
                for target in route['next']:
                    takers = slot_by_domain[target['address']]['hosts']
                    if all(host in [r['host'] for r in hops.node[t]['hop']['from']] for t in takers):
                        continue
                    raise AnsibleFilterError(
                        'remna_node_hops.egress.family of %s is ipv6, but it would forward to '
                        '%s, which does not take traffic from it (remna_node_hops.from) and has '
                        'IPv4 records only; use dual, or keep %s out of that path'
                        % (host, target['address'], host))

    # The rules snippet: local traffic first (a node's own decision, split
    # per censored geo), then one rule per action handing to one next hop.
    # Several next hops are a balancer, written inline into the profiles of
    # the nodes taking that action, with the rule naming it and the
    # observatory measuring it, so a profile never names a balancer it lacks.
    rules = []
    local_traffic = options.get('local_traffic')
    warp_tag = options.get('warp_tag') or 'out-warp-socks'
    if local_traffic is not None:
        for geo in sorted(set(r['local'] for r in routes if r['local'])):
            numbers = ','.join(str(r['id']) for r in routes if r['local'] == geo)
            wanted = (local_traffic or {}).get(geo) or {}
            if not wanted.get('domain') and not wanted.get('ip'):
                warnings.append('Routes %s leave the %s geo, but '
                                'vpn_server_remnawave_routing_local_traffic names no local '
                                'traffic of it, so it travels to the exit with the rest'
                                % (numbers, geo))
                continue
            for field in ('domain', 'ip'):
                if wanted.get(field):
                    rules.append({'vlessRoute': numbers, field: list(wanted[field]),
                                  'outboundTag': warp_tag})
    for route in routes:
        if not route['balancer']:
            rules.append({'vlessRoute': str(route['id']), 'outboundTag': route['next'][0]['tag']})

    # Fan-out: only the nodes taking the action ever receive its id, and they
    # all activate the profiles listed on the route, so the balancer, its
    # rule and the observatory go there, written with the profile in one go.
    # leastPing picks the next hop the observatory measures fastest; every
    # node of such a profile probes, through the whole rest of each path. A
    # path ending in a censored geo blocks all but its local traffic there
    # (reverse users), so the probe of a profile balancing such paths has to
    # be local to that geo: the observatory settings of the geo the balanced
    # paths end in are taken, else those of the global geo.
    observatory = options.get('observatory') or {}
    subjects = {}
    probe_geos = {}
    for route in routes:
        if not route['balancer']:
            continue
        tags = [n['tag'] for n in route['next']]
        for name in route['profiles']:
            config = profile_by_name[name]['config']
            routing = config.setdefault('routing', {})
            routing.setdefault('rules', []).append(
                {'vlessRoute': str(route['id']), 'balancerTag': route['balancer']})
            routing.setdefault('balancers', []).append({
                'tag': route['balancer'],
                'selector': list(tags),
                'strategy': {'type': 'leastPing'},
                'fallbackTag': tags[0],
            })
            subjects.setdefault(name, set()).update(tags)
            probe_geos.setdefault(name, set()).update(g for g in route['final_geos'] if g != 'global')
    for name, tags in sorted(subjects.items()):
        censored = sorted(probe_geos.get(name) or [])
        if len(censored) > 1:
            warnings.append('Config profile %s balances paths ending in %s; one observatory '
                            'probe cannot be local to all of them, so it is local to %s'
                            % (name, ', '.join(censored), censored[0]))
        geo = censored[0] if censored else 'global'
        settings = observatory.get(geo) or observatory.get('default') or {}
        if not settings.get('probeUrl'):
            raise AnsibleFilterError(
                'Config profile %s balances hops ending in the %s geo, which needs an observatory '
                'probeUrl for it (vpn_server_remnawave_hosts_hops_observatory)' % (name, geo))
        merged = dict(_plain(settings))
        merged['subjectSelector'] = sorted(tags)
        profile['config']['observatory'] = merged

    for exit_slot in chained:
        exit_slot['route_id'] = None
        exit_slot['outbound_tag'] = tag_of[exit_slot['domain']]
    for journey, key in zip(journeys, journey_keys):
        if journey[0] == 'chain' and journey[3].get('route_id') is None:
            journey[3]['route_id'] = ids[key]

    numbers = sorted(ids.values())
    lo, hi = _as_pair(options['route_id_range'], 'route_id_range')
    if numbers and (numbers[0] < lo or numbers[-1] > hi):
        warnings.append(
            'Generated route ids %d-%d fall outside the route id range %d-%d, so '
            'verify will not check the rules beyond it'
            % (numbers[0], numbers[-1], lo, hi))

    # --- the hosts ----------------------------------------------------------
    # A direct host uses its exit's profile. A chain host uses the exit's
    # access scope and the entry's transport, in either chaining direction.
    #
    # The entry node, though, runs its own profile and carries only the users
    # of the squads holding one of its own inbounds: a user shown a chain but
    # unknown to its entry completes the REALITY handshake and is refused
    # there. So the audience of every chain - the squads granted its exit's
    # scope - is granted the entry's inbounds as well (squad grants,
    # "transit"). Holding those shows a squad the hosts attached to them, so
    # every host but the direct ones of global exits names its audience.
    bind = options.get('chain_bind_nodes', 'entry')
    separator = options['remark_chain_separator']
    direct_route_id = options.get('direct_route_id')
    direct_route_id = '' if direct_route_id in (None, '') else int(direct_route_id)
    unrestricted = {'mode': 'exclude', 'squads': []}

    key_of = {}
    for journey, key in zip(journeys, journey_keys):
        key_of[(journey[0], journey[1]['domain'], journey[3]['domain'])] = key

    def restriction_of(exit_slot, what):
        # Visibility follows the exit's access scope, never the entry's: the
        # squads granted a profile of that scope, whatever its transport.
        allowed = sorted(set(
            squad for p in profiles
            if (p['kind'], p['scope']) == (exit_slot['scope_kind'], exit_slot['scope'])
            for squad in p['squads']))
        if not allowed:
            warnings.append('%s of %s exit %s are shown to no one: no internal squad is granted '
                            'a config profile of scope %s'
                            % (what, exit_slot['scope_kind'], exit_slot['domain'],
                               exit_slot['scope']))
        return {'mode': 'allow_only', 'squads': allowed}

    grant_of = dict((g['squad'], g) for g in squad_grants)

    def let_in(squads, entry):
        """Grant ``squads`` the inbounds of the profile ``entry`` activates."""
        profile = profile_by_name[entry['profile']]
        for squad in squads:
            grant = grant_of[squad]
            if profile['name'] not in grant['profiles'] + grant['transit_profiles']:
                grant['transit_profiles'].append(profile['name'])
            for tag in profile['inbound_tags']:
                if tag not in grant['inbounds']:
                    grant['inbounds'].append(tag)

    def bound_to(exit_slot, entry):
        if bind in ('exit', 'both'):
            warnings.append(
                'Chain host of %s through %s is bound to exit nodes, but the client '
                'connects to the entry; set vpn_server_remnawave_hosts_chain_bind_nodes '
                'to entry' % (exit_slot['domain'], entry['domain']))
        if bind == 'exit':
            return list(exit_slot['nodes'])
        if bind == 'both':
            return sorted(set(exit_slot['nodes']) | set(entry['nodes']))
        if bind == 'none':
            return []
        return list(entry['nodes'])

    def through(exit_slot, entry, kind, restriction):
        client_profile = profile_by_key[(exit_slot['scope_kind'], exit_slot['scope'],
                                         entry['protocol'])]
        key = key_of[(kind, entry['domain'], exit_slot['domain'])]
        let_in(restriction['squads'], entry)
        return {
            'kind': 'chain',
            'via': kind,
            # A relation saying show_entry: false is published under its
            # exit's name alone: the node dialed stays unnamed.
            'remark': _remark(exit_slot, labels) + (
                '' if kind == 'relation'
                and (entry['domain'], exit_slot['domain']) in hops.unnamed_entry
                else separator + _remark(entry, labels)),
            'address': entry['domain'],
            'sni': '',
            'vless_route_id': ids[key],
            'nodes': bound_to(exit_slot, entry),
            'protocol': entry['protocol'],
            'config_profile': client_profile['name'],
            'inbound': client_profile['inbound_tags'][0],
            'internal_squads': dict(restriction, squads=list(restriction['squads'])),
            'exit': exit_slot['domain'],
            'entry': entry['domain'],
            'paths': path_list(entry, (exit_slot, None)),
        }

    hosts = []
    for exit_slot in exits:
        key = key_of[('direct', exit_slot['domain'], exit_slot['domain'])]
        hosts.append({
            'kind': 'direct',
            'remark': _remark(exit_slot, labels),
            'address': exit_slot['domain'],
            'sni': '',
            # A direct host's node is the exit unless a hidden node carries on
            # for it: then it is that node's first action.
            'vless_route_id': direct_route_id if key == _FINAL else ids[key],
            'nodes': list(exit_slot['nodes']),
            'protocol': exit_slot['protocol'],
            'config_profile': exit_slot['profile'],
            'inbound': exit_slot['inbound'],
            'internal_squads': (dict(unrestricted) if exit_slot['scope_kind'] == 'global'
                                else restriction_of(exit_slot, 'Direct hosts')),
            'exit': exit_slot['domain'],
            'entry': None,
            'paths': path_list(exit_slot, None),
        })

    for exit_slot in chained:
        restriction = restriction_of(exit_slot, 'Chain hosts')
        for entry in pairs[exit_slot['domain']]:
            hosts.append(through(exit_slot, entry, 'chain', restriction))

    for upstream, downstream in hops.visible:
        hosts.append(through(downstream, upstream, 'relation',
                             restriction_of(downstream, 'Relation hosts')))

    # Nodes managed in the panel require their SNI to come from the address,
    # regardless of host kind.
    for host in hosts:
        host['override_sni_from_address'] = True
        # By the address the client dials: chain hosts through one entry show
        # the censor the same SNI, so they share a mask.
        host['final_mask'] = remnawave_final_mask(options.get('final_mask'), 'hosts', host['address'])

    # A REALITY inbound refuses a handshake whose SNI it does not list, so every
    # address a client or a chain outbound dials has to be in its serverNames.
    dialed = (set(h['address'] for h in hosts) | set(o['address'] for o in planned)
              | set(o['address'] for o in hop_outbounds))
    for profile in profiles:
        for inbound in profile['config']['inbounds']:
            stream = inbound.get('streamSettings') or {}
            if stream.get('security') != 'reality':
                continue
            listed = set((stream.get('realitySettings') or {}).get('serverNames') or [])
            missing = sorted(dialed - listed)
            if missing:
                warnings.append('REALITY inbound %s of config profile %s does not list %s '
                                'in its serverNames, so connections through them fail'
                                % (inbound['tag'], profile['name'], ', '.join(missing)))

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
        'profile_snippets': profile_snippets,
        'node_profiles': node_profiles,
        'squad_grants': squad_grants,
        'exits': exits,
        'entries': entries,
        'chained': chained,
        'hosts': hosts,
        'rules': rules,
        'routes': routes,
        'hop_outbounds': hop_outbounds,
        # Every node a chain outbound dials, which the service user must reach.
        'hop_targets': dict((n['address'], sorted(slot_by_domain[n['address']]['nodes']))
                            for r in routes for n in r['next']),
        'relations': hops.relations,
        'warnings': warnings,
    }


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


def _route_numbers(value):
    """The route ids of a vlessRoute condition ("401", "400,402", "400-410"),
    as a set, or None when it is not one."""
    if value is None or value == '':
        return None
    numbers = set()
    for part in str(value).split(','):
        part = part.strip()
        match = re.match(r'^(\d+)(?:-(\d+))?$', part)
        if not match:
            return None
        low = int(match.group(1))
        high = int(match.group(2)) if match.group(2) else low
        numbers.update(range(low, high + 1))
    return numbers


_ROUTE_ONLY_KEYS = ('vlessRoute', 'outboundTag', 'balancerTag', 'ruleTag', 'type')


def _route_only(rule):
    """Whether a rule matches on its route id alone, deciding where all of that
    route's traffic goes rather than splitting some of it off."""
    return set(rule) <= set(_ROUTE_ONLY_KEYS) and 'vlessRoute' in rule


def _snippet_refs(section):
    """The snippet names a config profile section embeds ({snippet: name})."""
    return [item.get('snippet') for item in (section or [])
            if isinstance(item, dict) and item.get('snippet')]


def _routing_dependencies(config, snippets):
    """Check references within one profile, not the panel-wide snippet catalog.

    A snippet existing in the panel does not make it active on every node.
    Only references embedded in this config contribute rules and outbounds.
    """
    problems = []

    def expand(section, path, stack=()):
        result = []
        for item in section or []:
            if not isinstance(item, dict):
                problems.append('%s contains a non-mapping item' % path)
                continue
            name = item.get('snippet')
            if not name:
                result.append(item)
            elif name in stack:
                problems.append('%s has a cyclic snippet reference %s'
                                % (path, ' -> '.join(stack + (name,))))
            elif name not in snippets:
                problems.append('%s references missing snippet %s' % (path, name))
            else:
                result.extend(expand(snippets[name], path, stack + (name,)))
        return result

    routing = config.get('routing') or {}
    outbounds = expand(config.get('outbounds'), 'outbounds')
    rules = expand(routing.get('rules'), 'routing.rules')
    balancers = expand(routing.get('balancers'), 'routing.balancers')
    outbound_tags = set(o.get('tag') for o in outbounds if o.get('tag'))
    balancer_tags = set(b.get('tag') for b in balancers if b.get('tag'))
    for rule in rules:
        outbound = rule.get('outboundTag')
        balancer = rule.get('balancerTag')
        if outbound and outbound not in outbound_tags:
            problems.append('routing rule targets outbound %s, which is absent from this profile'
                            % outbound)
        if balancer and balancer not in balancer_tags:
            problems.append('routing rule targets balancer %s, which is absent from this profile'
                            % balancer)
    for balancer in balancers:
        fallback = balancer.get('fallbackTag')
        if fallback and fallback not in outbound_tags:
            problems.append('balancer %s targets fallback outbound %s, which is absent from '
                            'this profile' % (balancer.get('tag'), fallback))
    return list(dict.fromkeys(problems))


def remnawave_expand(config, snippets):
    """``config`` with every {snippet: name} item of its lists replaced by
    that snippet's items, as the panel does before a node gets it."""
    def expand(value, stack=()):
        if isinstance(value, dict):
            return dict((k, expand(v, stack)) for k, v in value.items())
        if isinstance(value, list):
            out = []
            for item in value:
                if isinstance(item, dict) and set(item) == {'snippet'}:
                    name = item['snippet']
                    if name in stack:
                        raise AnsibleFilterError('Cyclic snippet reference %s'
                                                 % ' -> '.join(stack + (name,)))
                    if name not in snippets:
                        raise AnsibleFilterError('Snippet %s is not defined' % name)
                    out.extend(expand(snippets[name], stack + (name,)))
                else:
                    out.append(expand(item, stack))
            return out
        return value
    return expand(_plain(config))


def remnawave_dangling(profiles, snippets, name, content, tags=None):
    """What would dangle once snippet ``name`` held ``content``: every rule of a
    profile embedding it that would name an outbound or balancer the profile
    lacks. ``profiles`` and ``snippets`` are the panel's (remnawave_gathered);
    only profiles carrying every one of ``tags`` are looked at, if given."""
    catalog = dict((s.get('name'), s.get('snippet') or []) for s in snippets or [])
    catalog[name] = content or []
    wanted = set(tags or [])
    problems = []
    for profile in profiles or []:
        if wanted and not wanted.issubset(profile.get('tags') or []):
            continue
        config = profile.get('config') or {}
        if name not in _snippet_refs((config.get('routing') or {}).get('rules')):
            continue
        for problem in _routing_dependencies(config, catalog):
            problems.append("Config profile '%s': %s" % (profile.get('name'), problem))
    return problems


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

    for definition in model.get('profile_snippets') or []:
        name = definition['name']
        if name not in snippets:
            problems.append('Composition snippet %s is not in the panel' % name)
        elif snippets[name] != definition['snippet']:
            problems.append('Composition snippet %s differs from the inventory; its routing '
                            'conditions or settings may bypass a chain' % name)

    if rules_name in snippets and snippets[rules_name] != model.get('rules'):
        problems.append('Rules snippet %s differs from the inventory; regenerate the snippets '
                        'stage' % rules_name)

    # The rules a route id is resolved by: the rules snippet and the rules
    # written inline into managed profiles (balanced hops). Only a rule
    # matching on the route alone decides where its traffic goes next; one
    # with domain or ip conditions only splits off local traffic (WARP), so
    # several rules of one id conflict only when two unconditional ones send
    # it to different outbounds or balancers.
    route_rules = list(snippets.get(rules_name) or [])
    inline_balancers = []
    for profile in profiles.values():
        if not primary.issubset(profile.get('tags') or []):
            continue
        routing = (profile.get('config') or {}).get('routing') or {}
        route_rules.extend(r for r in routing.get('rules') or []
                           if isinstance(r, dict) and 'snippet' not in r)
        inline_balancers.extend(b for b in routing.get('balancers') or []
                                if isinstance(b, dict) and 'snippet' not in b)
    rule_of = {}
    for rule in route_rules:
        if not isinstance(rule, dict) or not _route_only(rule):
            continue
        numbers = _route_numbers(rule.get('vlessRoute'))
        if not numbers:
            continue
        target = ('balancer', rule['balancerTag']) if rule.get('balancerTag') else \
            ('outbound', rule.get('outboundTag'))
        for number in sorted(numbers):
            if number in rule_of and rule_of[number] != target:
                problems.append('Route id %d is sent to %s and to %s by different rules'
                                % (number, rule_of[number][1], target[1]))
                continue
            rule_of.setdefault(number, target)

    # Where each outbound goes and the route it hands over (its UUID's bytes
    # 6-7); an outbound without a user id is taken to hand over route 0.
    outbound_address = {}
    outbound_route = {}
    outbound_user = {}
    for outbound in snippets.get(outbounds_name) or []:
        tag = (outbound or {}).get('tag')
        if not tag:
            continue
        vnext = ((outbound.get('settings') or {}).get('vnext') or [{}])
        outbound_address[tag] = (vnext[0] or {}).get('address')
        users = (vnext[0] or {}).get('users') or [{}]
        user_id = (users[0] or {}).get('id')
        route = _uuid_route(user_id)
        outbound_route[tag] = 0 if user_id is None else route
        if route is not None:
            outbound_user[tag] = str(user_id).lower()[:14] + str(user_id).lower()[18:]

    balancer_selectors = {}
    for balancer in (snippets.get(balancers_name) or [] if balancers_name else []) + inline_balancers:
        tag = (balancer or {}).get('tag')
        selectors = (balancer or {}).get('selector') or []
        for selector in selectors:
            if not any(t.startswith(selector) for t in outbound_address):
                problems.append('Balancer %s selects outbound %s, which is not in %s'
                                % (tag, selector, outbounds_name))
        if tag:
            balancer_selectors[tag] = selectors

    def branches(target):
        if target[0] == 'outbound':
            return [target[1]]
        selectors = balancer_selectors.get(target[1])
        if selectors is None:
            return None
        return sorted(t for t in outbound_address if any(t.startswith(s) for s in selectors))

    used_route_ids = set()

    def walk(address, route, depth=0):
        """Every way traffic arriving at ``address`` with ``route`` goes, as
        lists of the addresses passed; a str says why it cannot be followed."""
        if depth > 12:
            return 'loops through route ids without reaching an exit'
        used_route_ids.add(route)
        target = rule_of.get(route)
        if target is None:
            return 'route id %d reaches %s, but no rule routes it' % (route, address)
        tags = branches(target)
        if tags is None:
            return 'route id %d goes to balancer %s, which is in no profile' % (route, target[1])
        if not tags:
            return 'route id %d goes to %s %s, which selects nothing in %s' % (
                route, target[0], target[1], outbounds_name)
        found = []
        for tag in tags:
            if tag not in outbound_address:
                return 'route id %d goes to outbound %s, which is not in %s' % (
                    route, tag, outbounds_name)
            following = outbound_address[tag]
            handed = outbound_route.get(tag)
            if handed is None:
                return 'outbound %s has no UUID to carry a route' % tag
            if handed == 0:
                found.append([address, following])
                continue
            rest = walk(following, handed, depth + 1)
            if isinstance(rest, str):
                return rest
            found.extend([address] + more for more in rest)
        return found

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

        # Followed hop by hop: the rule of the host's route id, the outbound
        # or balanced outbounds it sends to, the route each hands over, until
        # one hands over route 0 - the exit. Every way must be the inventory's.
        want_paths = sorted(want.get('paths') or [[want['address']]])
        if want['kind'] == 'chain' and have_id is None:
            problems.append('Chain host %s has no route id, so it is served directly '
                            'by its entry instead of reaching %s'
                            % (describe(have), want['exit']))
        elif have_id is None or have_id == direct_route_id:
            if want_paths != [[want['address']]]:
                problems.append('Host %s is served by %s itself, the inventory wants it to go '
                                '%s' % (describe(have), want['address'],
                                        ' or '.join(' > '.join(p) for p in want_paths)))
        else:
            walked = walk(have.get('address') or want['address'], have_id)
            if isinstance(walked, str):
                problems.append('Host %s: %s' % (describe(have), walked))
            elif sorted(walked) != want_paths:
                problems.append('Host %s goes %s, the inventory wants %s'
                                % (describe(have), ' or '.join(' > '.join(p) for p in sorted(walked)),
                                   ' or '.join(' > '.join(p) for p in want_paths)))

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
            if want['kind'] == 'chain' and want_restriction[0] == 'allow_only':
                # The entry carries only the users of its own inbounds: a
                # squad shown the chain but holding none of them is refused
                # there after the handshake.
                served = set(i.get('tag') for i in active.get('activeInbounds') or [])
                for name in want_restriction[1]:
                    if name in squad_tags and not served & squad_tags[name]:
                        problems.append(
                            'Squad %s is shown chain host %s but is not let in at its entry '
                            'node %s: it holds none of the inbounds the node activates (%s)'
                            % (name, describe(have), node.get('name'),
                               ', '.join(sorted(served)) or '-'))
            if want['kind'] == 'chain' and active.get('activeConfigProfileUuid') != profile_uuid:
                # A chain's advertised profile controls subscription access;
                # the entry still runs its own profile and routing. Verify
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
    # The snippets a profile embeds decide what its nodes route; a fragment
    # such as WARP in a profile it was not selected for is as wrong as one missing.
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
        for problem in _routing_dependencies(have_config, snippets):
            problems.append("Config profile '%s': %s" % (name, problem))
        for part, section in (('outbounds', lambda c: c.get('outbounds')),
                              ('rules', lambda c: (c.get('routing') or {}).get('rules')),
                              ('balancers', lambda c: (c.get('routing') or {}).get('balancers'))):
            have_refs = _snippet_refs(section(have_config))
            want_refs = _snippet_refs(section(want_config))
            if have_refs != want_refs:
                problems.append("Config profile '%s' embeds %s snippets %s, the inventory wants %s"
                                % (name, part, ', '.join(have_refs) or '-', ', '.join(want_refs) or '-'))
        for part, pick in (('observatory', lambda c: c.get('observatory')),
                           ('inline balancers', lambda c: [b for b in (c.get('routing') or {})
                                                           .get('balancers') or []
                                                           if 'snippet' not in b]),
                           ('inline rules', lambda c: [r for r in (c.get('routing') or {})
                                                       .get('rules') or []
                                                       if 'snippet' not in r])):
            if (pick(have_config) or None) != (pick(want_config) or None):
                problems.append("Config profile '%s' holds %s that differ from the inventory"
                                % (name, part))
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
            target = rule_of[have_id][1]
            where = ' and route id %d now goes to %s (%s)' % (
                have_id, target, outbound_address.get(target) or 'balanced')
        if have.get('isDisabled'):
            notes.append('Host %s is no longer produced by the inventory; it is disabled%s'
                         % (describe(have), where))
        else:
            problems.append('Host %s is no longer produced by the inventory but still enabled%s'
                            % (describe(have), where))

    for number in sorted(rule_of):
        if not lo <= number <= hi:
            continue
        kind, target = rule_of[number]
        if kind == 'outbound' and target not in outbound_address:
            problems.append('Rule for route id %d goes to outbound %s, which is not in %s'
                            % (number, target, outbounds_name))
        if kind == 'balancer' and target not in balancer_selectors:
            problems.append('Rule for route id %d goes to balancer %s, which is in no profile'
                            % (number, target))
        if number not in used_route_ids:
            notes.append('Rule for route id %d (%s) is used by no host of the inventory'
                         % (number, target))

    # The chain outbounds authenticate as the service user on every node they
    # hand traffic to, so its squads must hold an inbound each such node runs.
    users = set(outbound_user.values())
    if len(users) > 1:
        problems.append('Chain outbounds authenticate as %d different users; they must all use '
                        'the service user' % len(users))
    service = options.get('service_user')
    targets = model.get('hop_targets') or {}
    if targets and not service:
        notes.append('Set vpn_server_remnawave_service_user_name to check that the service '
                     'user may connect to every node chain outbounds dial')
    elif targets:
        vless = str(service.get('vlessUuid') or '').lower()
        if users and vless[:14] + vless[18:] not in users:
            problems.append('Service user %s is not the user the chain outbounds authenticate as'
                            % service.get('username'))
        held = set()
        for squad in service.get('activeInternalSquads') or []:
            held |= squad_tags.get(squad.get('name'), set())
        for address, names in sorted(targets.items()):
            for name in names:
                node = nodes_by_name.get(name) or {}
                active = set(i.get('tag') for i in
                             ((node.get('configProfile') or {}).get('activeInbounds') or []))
                if active and not active & held:
                    problems.append('Service user %s cannot connect to node %s (%s): its squads '
                                    'hold none of the inbounds %s'
                                    % (service.get('username'), name, address,
                                       ', '.join(sorted(active))))

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
            'remnawave_final_mask': remnawave_final_mask,
            'remnawave_model': remnawave_model,
            'remnawave_route_uuid': remnawave_route_uuid,
            'remnawave_dangling': remnawave_dangling,
            'remnawave_expand': remnawave_expand,
            'remnawave_select_tagged': remnawave_select_tagged,
            'remnawave_select_profiles_kept': remnawave_select_profiles_kept,
            'remnawave_verify': remnawave_verify,
        }
