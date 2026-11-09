"""Regression tests: python3 -m unittest discover -s roles/configure_remnawave_panel_generate_setup/tests."""

import copy
import importlib.util
import json
from pathlib import Path
import unittest

from jinja2 import Environment
from jinja2.nativetypes import NativeEnvironment, NativeTemplate
import yaml
from ansible.errors import AnsibleFilterError
from ansible.plugins.filter.core import FilterModule as AnsibleCoreFilters

ROLE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('remnawave_setup', ROLE / 'filter_plugins/remnawave_setup.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)

TCP = 'vless-reality-tcp'
XHTTP = 'vless-reality-xhttp'


def options():
    def base(protocol, name, tag, network, suffix):
        return {
            'protocol': protocol, 'name': name, 'variant_suffix': suffix,
            'inbounds': [{
                'tag': tag, 'port': 443, 'protocol': 'vless',
                'streamSettings': {
                    'network': network, 'security': 'reality',
                    'realitySettings': {'serverNames': ['example.test'], 'shortIds': ['']},
                },
            }],
        }
    return {
        'default_protocol': TCP,
        'direct_domain_types': ['net-location'], 'entry_domain_types': ['chain-location'],
        'entry_country_codes': ['RU'], 'region_codes': {'russia': 'ru', 'europe': 'eu'},
        'route_id_base': 400, 'route_id_range': [400, 499], 'direct_route_id': 2,
        'remark_chain_separator': ' | by ',
        'profiles_base': [base(TCP, 'Default-Profile', 'VLESS_TCP_REALITY', 'raw', ''),
                          base(XHTTP, 'Default-xHTTP', 'VLESS_REALITY_XHTTP', 'xhttp', '-xHTTP')],
        'profiles_exclusive': [{'name': 'Xenus-team', 'inbound_suffix': 'XENUS'}],
        'private_key_common': 'mock-private-key',
        'profile_composition': [{
            'name': 'chains',
            'config': {'outbounds': [{'snippet': 'outbounds'}],
                       'routing': {'rules': [{'snippet': 'rules'}]}},
        }],
        'squads_inbounds': [
            {'squad': 'Default-Squad', 'profiles': {'kind': 'global'}},
            {'squad': 'Reverse-proxy', 'profiles': {'kind': 'location'}},
            {'squad': 'Xenus-team', 'profiles': {'scope': 'Xenus-team'}},
        ],
        'outbounds': [
            {'address': 'net-europe-1.example.test', 'tag': 'out-chain-1'},
            {'address': 'net-europe-2.example.test', 'tag': 'out-chain-2'},
        ],
    }


def nodes():
    def node(name, country, geo, protocol, domain, domain_type, exclusive=False):
        return {
            'name': name, 'country': country, 'geo': geo, 'protocol': protocol,
            'domains': [{'domain': domain + '.example.test', 'type': domain_type}],
            'exclusive_member': exclusive, 'exclusive_profile': 'Xenus-team' if exclusive else '',
        }
    return [
        node('shared-exit', 'NL', 'global', TCP, 'net-europe-1', 'net-location'),
        node('exclusive-exit', 'CZ', 'global', TCP, 'net-europe-2', 'net-location', True),
        node('ru-tcp', 'RU', 'russia', TCP, 'chain-russia-1', 'chain-location'),
        node('ru-xhttp', 'RU', 'russia', XHTTP, 'chain-russia-2', 'chain-location'),
    ]


def reverse_scenario():
    """Shared global entries, RU entries and RU exits: both chain directions."""
    opts = options()
    opts['entry_global_for_non_global'] = True
    items = nodes()
    items[0]['domains'].append({'domain': 'chain-europe-1.example.test', 'type': 'chain-location'})
    global_xhttp = copy.deepcopy(items[0])
    global_xhttp.update(name='global-xhttp', protocol=XHTTP)
    global_xhttp['domains'] = [{'domain': 'chain-asia-1.example.test', 'type': 'chain-location'}]
    items.append(global_xhttp)
    items[1]['domains'].append({'domain': 'chain-europe-2.example.test', 'type': 'chain-location'})
    for index, node in enumerate(items[2:4], 1):
        domain = 'net-russia-%d.example.test' % index
        node['domains'].append({'domain': domain, 'type': 'net-location'})
        opts['outbounds'].append({'address': domain, 'tag': 'out-chain-ru-%d' % index})
    return items, opts


def legacy_scenarios():
    """Inventories without remna_node_hops, whose hosts, route ids and tags
    must stay what they were before hops existed (fixtures/legacy_snapshot.json)."""
    exclusive_ru = reverse_scenario()
    exclusive_ru[0][2].update(exclusive_member=True, exclusive_profile='Xenus-team')
    exclusive_ru[0][1]['geo'] = 'russia'
    return {
        'forward': (nodes(), options()),
        'reverse': reverse_scenario(),
        'exclusive_reverse': exclusive_ru,
    }


def legacy_view(model):
    """The parts of a model that existing panels and subscriptions depend on."""
    keys = ('kind', 'remark', 'address', 'vless_route_id', 'nodes', 'config_profile',
            'inbound', 'internal_squads', 'exit', 'entry', 'protocol')
    return {
        'hosts': [dict((k, h.get(k)) for k in keys) for h in model['hosts']],
        'forward_rules': [r for r in model['rules']
                          if not set(r) & {'domain', 'ip'} and 'outboundTag' in r],
        'profiles': [(p['name'], p['kind'], p['scope'], p['protocol'], p['inbound_tags'], p['squads'])
                     for p in model['profiles']],
        'node_profiles': model['node_profiles'],
        'squad_grants': model['squad_grants'],
    }


def panel_for(model):
    """Mock the API's UUID relations, including differently scoped chain inbounds."""
    profiles = [{
        'uuid': p['name'], 'name': p['name'], 'tags': ['MANAGED_BY:ANSIBLE'],
        'inbounds': [{'uuid': tag, 'tag': tag} for tag in p['inbound_tags']],
        'config': copy.deepcopy(p['config']),
    } for p in model['profiles']]
    return {
        'config_profiles': profiles,
        'nodes': [{
            'uuid': name, 'name': name,
            'configProfile': {
                'activeConfigProfileUuid': p['config_profile'],
                'activeInbounds': [{'uuid': tag, 'tag': tag} for tag in p['inbounds']],
            },
        } for name, p in model['node_profiles'].items()],
        'hosts': [{
            'remark': h['remark'], 'address': h['address'], 'sni': None,
            'fingerprint': 'firefox', 'overrideSniFromAddress': True,
            'tags': ['MANAGED_BY:ANSIBLE'], 'vlessRouteId': h['vless_route_id'],
            'nodes': h['nodes'],
            'inbound': {'configProfileUuid': h['config_profile'],
                        'configProfileInboundUuid': h['inbound']},
            'internalSquads': h['internal_squads'],
        } for h in model['hosts']],
        'internal_squads': [{
            'uuid': g['squad'], 'name': g['squad'],
            'inbounds': [{'uuid': tag, 'tag': tag} for tag in g['inbounds']],
        } for g in model['squad_grants']],
        'snippets': [
            {'name': 'rules', 'snippet': model['rules']},
            {'name': 'outbounds', 'snippet': [
                {'tag': e['outbound_tag'], 'settings': {'vnext': [{'address': e['domain']}]}}
                for e in model['chained']
            ]},
        ],
    }


class FinalMaskTests(unittest.TestCase):
    ADDRESS = 'net-asia-1.123987465.xyz'
    TCP = [
        {'type': 'fragment', 'settings': {'packets': 'tlshello', 'lengths': ['6', '98', '1'],
                                          'delays': ['0'], 'maxSplit': '0'}},
        {'type': 'fragment', 'settings': {'packets': '1-1', 'lengths': ['114', '1'],
                                          'delays': ['1'], 'maxSplit': '11'}},
    ]

    def spec(self):
        tcp = copy.deepcopy(self.TCP)
        return {'hosts': {'enabled': True, 'tcp': tcp},
                'outbounds': {'enabled': True, 'tcp': copy.deepcopy(tcp)}}

    def test_the_masks_come_out_as_written_and_in_order(self):
        self.assertEqual(setup.remnawave_final_mask(self.spec(), 'hosts', self.ADDRESS), {'tcp': self.TCP})
        self.assertEqual(setup.remnawave_final_mask(self.spec(), 'outbounds', self.ADDRESS), {'tcp': self.TCP})

    def test_ranges_are_kept_and_plain_numbers_become_strings(self):
        spec = self.spec()
        settings = spec['hosts']['tcp'][0]['settings']
        settings.update({'lengths': ['5-7', 98, 1], 'delays': [0], 'maxSplit': '0-3'})
        out = setup.remnawave_final_mask(spec, 'hosts', self.ADDRESS)['tcp'][0]['settings']
        self.assertEqual(out['lengths'], ['5-7', '98', '1'])
        self.assertEqual(out['delays'], ['0'])
        self.assertEqual(out['maxSplit'], '0-3')

    def test_a_missing_max_split_means_no_limit(self):
        spec = self.spec()
        del spec['hosts']['tcp'][0]['settings']['maxSplit']
        out = setup.remnawave_final_mask(spec, 'hosts', self.ADDRESS)['tcp'][0]['settings']
        self.assertEqual(out['maxSplit'], '0')

    def test_a_side_switched_off_gives_no_mask(self):
        spec = self.spec()
        spec['outbounds']['enabled'] = 'False'
        self.assertEqual(setup.remnawave_final_mask(spec, 'outbounds', self.ADDRESS), {})
        self.assertEqual(setup.remnawave_final_mask(None, 'hosts', self.ADDRESS), {})

    def test_what_xray_would_drop_or_refuse_is_refused(self):
        for position, change in (
                (0, {'interval': '10-20'}),         # dropped by Xray unnoticed
                (0, {'length': '10-20'}),           # the old form
                (0, {'lengths': ['0', '98', '1']}),  # an empty TLS record
                (0, {'lengths': ['6', '98', '0']}),  # never finishes
                (0, {'lengths': []}),
                (0, {'lengths': '6'}),
                (0, {'lengths': ['20-10', '1']}),
                (0, {'lengths': ['abc', '1']}),
                (0, {'delays': []}),
                (0, {'maxSplit': ''}),
                (1, {'packets': '0-1'}),
                (1, {'packets': 'hello'}),
                (1, {'lengths': ['114', '0']})):
            spec = self.spec()
            spec['hosts']['tcp'][position]['settings'].update(change)
            with self.assertRaises(AnsibleFilterError, msg=str(change)):
                setup.remnawave_final_mask(spec, 'hosts', self.ADDRESS)

    def test_the_stream_form_may_skip_a_write(self):
        spec = self.spec()
        spec['hosts']['tcp'][1]['settings']['lengths'] = ['0', '1']
        out = setup.remnawave_final_mask(spec, 'hosts', self.ADDRESS)['tcp'][1]['settings']
        self.assertEqual(out['lengths'], ['0', '1'])

    def test_masks_in_an_order_that_cannot_work_are_refused(self):
        spec = self.spec()
        spec['hosts']['tcp'].reverse()
        with self.assertRaises(AnsibleFilterError):
            setup.remnawave_final_mask(spec, 'hosts', self.ADDRESS)

    def test_only_fragment_masks_and_a_list_of_them(self):
        spec = self.spec()
        spec['hosts']['tcp'][0]['type'] = 'sudoku'
        with self.assertRaises(AnsibleFilterError):
            setup.remnawave_final_mask(spec, 'hosts', self.ADDRESS)
        spec['hosts']['tcp'] = []
        with self.assertRaises(AnsibleFilterError):
            setup.remnawave_final_mask(spec, 'hosts', self.ADDRESS)

    def varying(self):
        spec = self.spec()
        spec['hosts']['tcp'][0]['settings']['lengths'] = [{'pick': '5-8'}, {'pick': '90-98'}, '1']
        spec['hosts']['tcp'][1]['settings']['lengths'] = ['aligned', '1-2']
        spec['outbounds'] = copy.deepcopy(spec['hosts'])
        return spec

    def test_the_inventory_pins_the_mask_to_the_values_known_to_work(self):
        with open(ROLE.parents[1] / 'inventory/group_vars/vpn_server_remnawave/final_mask.yaml') as handle:
            spec = yaml.safe_load(handle)['vpn_server_remnawave_final_mask']
        for side in ('hosts', 'outbounds'):
            for address in (self.ADDRESS, 'chain-russia-3.14886769.xyz'):
                self.assertEqual(setup.remnawave_final_mask(spec, side, address), {'tcp': self.TCP})

    def test_a_pick_is_stable_and_inside_its_window(self):
        spec = self.varying()
        seen = set()
        for i in range(1, 200):
            address = 'net-asia-%d.123987465.xyz' % i
            mask = setup.remnawave_final_mask(spec, 'hosts', address)
            self.assertEqual(mask, setup.remnawave_final_mask(spec, 'hosts', address))
            first, second, tail = mask['tcp'][0]['settings']['lengths']
            self.assertTrue(5 <= int(first) <= 8 and 90 <= int(second) <= 98)
            self.assertEqual(tail, '1')
            seen.add((first, second))
        self.assertGreater(len(seen), 10)

    def test_a_pick_differs_between_domains_and_sides(self):
        spec = self.varying()
        addresses = ['net-asia-%d.123987465.xyz' % i for i in range(1, 30)]
        hosts = [setup.remnawave_final_mask(spec, 'hosts', a) for a in addresses]
        self.assertGreater(len(set(str(m) for m in hosts)), 1)
        self.assertNotEqual(hosts, [setup.remnawave_final_mask(spec, 'outbounds', a) for a in addresses])

    def test_aligned_ends_the_write_after_the_tlshello_records(self):
        spec = self.varying()
        for i in range(1, 50):
            mask = setup.remnawave_final_mask(spec, 'hosts', 'net-asia-%d.123987465.xyz' % i)
            first, second, _ = mask['tcp'][0]['settings']['lengths']
            self.assertEqual(mask['tcp'][1]['settings']['lengths'],
                             [str(int(first) + int(second) + 10), '1-2'])

    def test_aligned_is_refused_where_no_one_size_could_be_right(self):
        for position, change in (
                (0, {'lengths': ['5-8', '98', '1']}),  # drawn per connection
                (0, {'lengths': ['1']}),                # no records but the repeating one
                (0, {'delays': ['1']}),                 # the records are separate writes
                (0, {'maxSplit': '2'}),                 # cuts the second record short
                (0, {'maxSplit': '0-2'}),
                (1, {'packets': '2-3'}),                # not the write holding the records
                (1, {'lengths': ['aligned']}),
                (1, {'lengths': ['1', 'aligned']})):
            spec = self.varying()
            spec['hosts']['tcp'][position]['settings'].update(change)
            with self.assertRaises(AnsibleFilterError, msg=str(change)):
                setup.remnawave_final_mask(spec, 'hosts', self.ADDRESS)
        spec = self.varying()
        del spec['hosts']['tcp'][0]
        with self.assertRaises(AnsibleFilterError):
            setup.remnawave_final_mask(spec, 'hosts', self.ADDRESS)
        spec = self.varying()
        spec['hosts']['tcp'][0]['settings']['lengths'] = ['aligned', '1']
        with self.assertRaises(AnsibleFilterError):
            setup.remnawave_final_mask(spec, 'hosts', self.ADDRESS)

    def test_a_malformed_pick_is_refused(self):
        for value in ({'pick': '98-90'}, {'pick': 'abc'}, {'pick': '5', 'other': 1}, {'nope': '5'},
                      {'pick': '0-3'}):
            spec = self.spec()
            spec['hosts']['tcp'][0]['settings']['lengths'] = [value, '1']
            with self.assertRaises(AnsibleFilterError, msg=str(value)):
                setup.remnawave_final_mask(spec, 'hosts', self.ADDRESS)

    def test_a_host_takes_its_picks_from_the_address_it_dials(self):
        option_set = options()
        option_set['final_mask'] = self.varying()
        hosts = setup.remnawave_model(nodes(), option_set)['hosts']
        self.assertTrue(any(h['kind'] == 'chain' for h in hosts))
        for host in hosts:
            self.assertEqual(host['final_mask'],
                             setup.remnawave_final_mask(option_set['final_mask'], 'hosts', host['address']))

    def test_model_gives_every_host_the_mask(self):
        option_set = options()
        option_set['final_mask'] = self.spec()
        hosts = setup.remnawave_model(nodes(), option_set)['hosts']
        self.assertTrue(any(h['kind'] == 'chain' for h in hosts))
        self.assertTrue(all(h['final_mask'] == {'tcp': self.TCP} for h in hosts))

    def test_model_without_the_option_gives_hosts_no_mask(self):
        hosts = setup.remnawave_model(nodes(), options())['hosts']
        self.assertTrue(all(h['final_mask'] == {} for h in hosts))


class GenerationTests(unittest.TestCase):
    def setUp(self):
        self.options = options()
        self.nodes = nodes()
        self.model = setup.remnawave_model(self.nodes, self.options)

    def test_shared_chain_uses_base_for_entry_transport(self):
        chains = [h for h in self.model['hosts'] if h['kind'] == 'chain'
                  and h['exit'] == 'net-europe-1.example.test']
        self.assertEqual([(h['config_profile'], h['inbound'], h['nodes']) for h in chains], [
            ('Default-Profile', 'VLESS_TCP_REALITY', ['ru-tcp']),
            ('Default-xHTTP', 'VLESS_REALITY_XHTTP', ['ru-xhttp']),
        ])
        self.assertEqual(self.model['node_profiles']['ru-tcp']['config_profile'], 'Reverse-RU')

    def test_exclusive_chain_gets_both_transports_and_keeps_restrictions(self):
        profiles = {p['name']: p for p in self.model['profiles']}
        self.assertIn('Xenus-team-xHTTP', profiles)
        self.assertEqual(profiles['Xenus-team-xHTTP']['inbound_tags'], ['VLESS_REALITY_XHTTP_XENUS'])
        chains = [h for h in self.model['hosts'] if h['kind'] == 'chain'
                  and h['exit'] == 'net-europe-2.example.test']
        self.assertEqual([h['config_profile'] for h in chains], ['Xenus-team', 'Xenus-team-xHTTP'])
        for host in chains:
            self.assertEqual(host['internal_squads'], {'mode': 'allow_only', 'squads': ['Xenus-team']})
            self.assertEqual(host['vless_route_id'], 401)
        self.assertEqual(self.model['node_profiles']['exclusive-exit']['config_profile'], 'Xenus-team')
        grant = next(g for g in self.model['squad_grants'] if g['squad'] == 'Xenus-team')
        self.assertIn('VLESS_REALITY_XHTTP_XENUS', grant['inbounds'])

    def test_direct_hosts_keep_primary_transport_and_clear_duplicate_sni(self):
        direct = [h for h in self.model['hosts'] if h['kind'] == 'direct']
        self.assertEqual([h['config_profile'] for h in direct], ['Default-Profile', 'Xenus-team'])
        for host in self.model['hosts']:
            self.assertEqual(host['sni'], '')
            self.assertIs(host['override_sni_from_address'], True)

    def test_fingerprint_defaults_and_inventory_are_firefox(self):
        for path in (ROLE / 'defaults/main.yml',
                     ROLE.parents[1] / 'inventory/group_vars/vpn_server_remnawave/hosts.yaml'):
            self.assertEqual(yaml.safe_load(path.read_text())['vpn_server_remnawave_hosts_fingerprint'],
                             'firefox')

    def test_unused_exclusive_protocol_not_generated(self):
        self.options['exclude'] = [{'exit': 'net-europe-2.example.test',
                                   'entries': ['chain-russia-2.example.test']}]
        model = setup.remnawave_model(self.nodes, self.options)
        self.assertNotIn('Xenus-team-xHTTP', [p['name'] for p in model['profiles']])
        self.options['outbounds'] = self.options['outbounds'][:1]
        model = setup.remnawave_model(self.nodes, self.options)
        self.assertNotIn('Xenus-team-xHTTP', [p['name'] for p in model['profiles']])

    def test_mixed_scope_round_robin_domain_is_rejected(self):
        self.nodes[1]['domains'] = self.nodes[0]['domains']
        with self.assertRaises(AnsibleFilterError):
            setup.remnawave_model(self.nodes, self.options)

    def test_xhttp_exit_chained_through_tcp_uses_tcp_exclusive_variant(self):
        self.nodes[1]['protocol'] = XHTTP
        model = setup.remnawave_model(self.nodes, self.options)
        direct = next(h for h in model['hosts'] if h['kind'] == 'direct'
                      and h['exit'] == 'net-europe-2.example.test')
        self.assertEqual(direct['config_profile'], 'Xenus-team-xHTTP')
        chain = next(h for h in model['hosts'] if h['kind'] == 'chain'
                     and h['exit'] == direct['exit'] and h['nodes'] == ['ru-tcp'])
        self.assertEqual(chain['config_profile'], 'Xenus-team')
        self.assertEqual(chain['protocol'], TCP)

    def test_mixed_protocol_round_robin_domain_is_rejected(self):
        self.nodes[0]['domains'].append(self.nodes[2]['domains'][0])
        self.nodes[0]['country'] = 'RU'
        self.nodes[0]['geo'] = 'russia'
        self.nodes[0]['protocol'] = XHTTP
        with self.assertRaises(AnsibleFilterError):
            setup.remnawave_model(self.nodes, self.options)

    def test_missing_exclusive_transport_base_is_rejected(self):
        self.options['profiles_base'] = self.options['profiles_base'][:1]
        with self.assertRaises(AnsibleFilterError):
            setup.remnawave_model(self.nodes, self.options)

    def test_route_rules_unchanged_by_transport_variants(self):
        self.assertEqual(self.model['rules'], [
            {'vlessRoute': '400', 'outboundTag': 'out-chain-1'},
            {'vlessRoute': '401', 'outboundTag': 'out-chain-2'},
        ])
        self.assertEqual(len(self.model['hosts']), 6)

    def verify(self, panel):
        return setup.remnawave_verify(panel, self.model, {
            'primary_tags': ['MANAGED_BY:ANSIBLE'], 'separator': ' | by ',
            'direct_route_id': 2, 'route_id_range': [400, 499],
            'rules_snippet': 'rules', 'outbounds_snippet': 'outbounds', 'fingerprint': 'firefox',
        })['problems']

    def test_verify_accepts_compatible_chain_entry_profile(self):
        self.assertEqual(self.verify(panel_for(self.model)), [])

    def test_verify_rejects_incompatible_reality_keys(self):
        panel = panel_for(self.model)
        reverse = next(p for p in panel['config_profiles'] if p['name'] == 'Reverse-RU')
        reverse['config']['inbounds'][0]['streamSettings']['realitySettings']['privateKey'] = 'wrong-key'
        self.assertTrue(any('no active inbound compatible' in p for p in self.verify(panel)))

    def test_verify_rejects_missing_active_chain_inbound(self):
        panel = panel_for(self.model)
        entry = next(n for n in panel['nodes'] if n['name'] == 'ru-xhttp')
        entry['configProfile']['activeInbounds'] = []
        self.assertTrue(any('no active inbound compatible' in p for p in self.verify(panel)))

    def test_verify_still_requires_direct_profile_identity(self):
        panel = panel_for(self.model)
        exit_node = next(n for n in panel['nodes'] if n['name'] == 'shared-exit')
        exit_node['configProfile'] = {
            'activeConfigProfileUuid': 'Reverse-RU',
            'activeInbounds': [{'uuid': 'VLESS_TCP_REALITY_REVERSE_RU',
                               'tag': 'VLESS_TCP_REALITY_REVERSE_RU'}],
        }
        self.assertTrue(any('not the host\'s' in p for p in self.verify(panel)))

    def test_verify_rejects_wrong_profile_fingerprint_and_duplicate_sni(self):
        panel = panel_for(self.model)
        chain = next(h for h in panel['hosts'] if ' | by ' in h['remark'])
        chain['inbound'] = {'configProfileUuid': 'Reverse-RU',
                            'configProfileInboundUuid': 'VLESS_TCP_REALITY_REVERSE_RU'}
        chain['sni'] = chain['address']
        chain['fingerprint'] = 'chrome'
        chain['overrideSniFromAddress'] = False
        problems = self.verify(panel)
        for text in ('inventory wants Default-Profile', 'has fingerprint chrome', 'has SNI',
                     'does not override SNI'):
            self.assertTrue(any(text in p for p in problems), problems)


class ReverseChainTests(unittest.TestCase):
    def setUp(self):
        self.options = options()
        self.options['entry_global_for_non_global'] = True
        self.nodes = nodes()
        self.nodes[0]['domains'].append({'domain': 'chain-europe-1.example.test', 'type': 'chain-location'})
        # Also exercise a shared global xHTTP entry independently of the TCP one.
        global_xhttp = copy.deepcopy(self.nodes[0])
        global_xhttp.update(name='global-xhttp', protocol=XHTTP)
        global_xhttp['domains'] = [{'domain': 'chain-asia-1.example.test', 'type': 'chain-location'}]
        self.nodes.append(global_xhttp)
        # Exclusive global domains must not enter the new shared entry pool.
        self.nodes[1]['domains'].append({'domain': 'chain-europe-2.example.test', 'type': 'chain-location'})
        for index, node in enumerate(self.nodes[2:4], 1):
            domain = 'net-russia-%d.example.test' % index
            node['domains'].append({'domain': domain, 'type': 'net-location'})
            self.options['outbounds'].append({'address': domain, 'tag': 'out-chain-ru-%d' % index})

    def model(self):
        return setup.remnawave_model(self.nodes, self.options)

    def test_both_directions_use_exit_scope_entry_transport_and_binding(self):
        model = self.model()
        reverse = [h for h in model['hosts'] if h['kind'] == 'chain' and h['exit'].startswith('net-russia')]
        self.assertEqual(len(reverse), 4)
        for host in reverse:
            self.assertEqual(host['config_profile'], 'Reverse-RU' if host['protocol'] == TCP else 'Reverse-RU-xHTTP')
            self.assertEqual(host['address'], host['entry'])
            self.assertEqual(host['nodes'], ['shared-exit'] if host['protocol'] == TCP else ['global-xhttp'])
            self.assertEqual(host['sni'], '')
            self.assertIs(host['override_sni_from_address'], True)
            self.assertEqual(host['internal_squads'], {'mode': 'exclude', 'squads': []})
        forward = [h for h in model['hosts'] if h['kind'] == 'chain' and h['exit'].startswith('net-europe')]
        self.assertEqual(len(forward), 4)
        self.assertEqual([h['config_profile'] for h in forward],
                         ['Default-Profile', 'Default-xHTTP', 'Xenus-team', 'Xenus-team-xHTTP'])
        self.assertNotIn('chain-europe-2.example.test', [e['domain'] for e in model['entries']])
        self.assertEqual(setup.remnawave_verify(panel_for(model), model, {
            'primary_tags': ['MANAGED_BY:ANSIBLE'], 'separator': ' | by ',
            'direct_route_id': 2, 'route_id_range': [400, 499],
            'rules_snippet': 'rules', 'outbounds_snippet': 'outbounds',
        })['problems'], [])

    def test_reverse_routes_reuse_outbounds_and_preserve_forward_ids(self):
        model = self.model()
        self.assertEqual(model['rules'], [
            {'vlessRoute': '400', 'outboundTag': 'out-chain-1'},
            {'vlessRoute': '401', 'outboundTag': 'out-chain-2'},
            {'vlessRoute': '402', 'outboundTag': 'out-chain-ru-1'},
            {'vlessRoute': '403', 'outboundTag': 'out-chain-ru-2'},
        ])
        for domain in ('net-russia-1.example.test', 'net-russia-2.example.test'):
            hosts = [h for h in model['hosts'] if h['kind'] == 'chain' and h['exit'] == domain]
            self.assertEqual(len(set(h['vless_route_id'] for h in hosts)), 1)

    def test_disabling_new_direction_restores_legacy_entry_pool(self):
        self.options['entry_global_for_non_global'] = 'false'
        model = self.model()
        self.assertEqual([e['domain'] for e in model['entries']],
                         ['chain-russia-1.example.test', 'chain-russia-2.example.test'])
        self.assertEqual(len(model['rules']), 2)
        self.assertFalse(any(h['kind'] == 'chain' and h['exit'].startswith('net-russia')
                             for h in model['hosts']))

    def test_does_not_add_global_to_global_or_self_chains(self):
        self.options['skip_same_country'] = False
        for host in self.model()['hosts']:
            if host['kind'] == 'chain':
                exit_node = next(n for n in self.nodes if any(d['domain'] == host['exit'] for d in n['domains']))
                self.assertFalse(set(host['nodes']).intersection([exit_node['name']]))
                if exit_node['geo'] == 'global':
                    self.assertTrue(host['entry'].startswith('chain-russia'))

    def test_reverse_pairs_honor_exclusions_and_same_country(self):
        self.options['exclude'] = [{'exit': 'net-russia-1.example.test',
                                   'entries': ['chain-europe-1.example.test']},
                                  {'exit': 'net-russia-2.example.test', 'entries': '*'}]
        model = self.model()
        reverse = [h for h in model['hosts'] if h['kind'] == 'chain' and h['exit'].startswith('net-russia')]
        self.assertEqual(len(reverse), 1)
        self.assertEqual(reverse[0]['entry'], 'chain-asia-1.example.test')
        self.nodes[-1]['country'] = 'RU'
        # Geography, not country, determines the new direction; same-country
        # suppression still applies even to a global-geo entry located in RU.
        self.options['entry_country_codes'] = []
        self.assertFalse(any(h['kind'] == 'chain' for h in self.model()['hosts']))

    def test_new_direction_is_geography_based_not_russia_specific(self):
        self.options['region_codes']['iran'] = 'IR'
        for node in self.nodes[2:4]:
            node.update(country='IR', geo='iran')
        reverse = [h for h in self.model()['hosts'] if h['kind'] == 'chain'
                   and h['exit'].startswith('net-russia')]
        self.assertEqual(len(reverse), 4)
        self.assertEqual({h['config_profile'] for h in reverse}, {'Reverse-IR', 'Reverse-IR-xHTTP'})

    def test_global_nodes_without_chain_domains_are_not_used_as_entries(self):
        self.nodes[0]['domains'] = self.nodes[0]['domains'][:1]
        self.nodes[-1]['domains'] = []
        model = self.model()
        self.assertEqual(len(model['entries']), 2)
        self.assertFalse(any(h['kind'] == 'chain' and h['exit'].startswith('net-russia')
                             for h in model['hosts']))

    def test_missing_reverse_outbound_is_reported_not_half_published(self):
        self.options['outbounds'] = self.options['outbounds'][:2]
        model = self.model()
        self.assertTrue(any('net-russia-1' in warning and 'no planned outbound' in warning
                            for warning in model['warnings']))
        self.assertFalse(any(h['kind'] == 'chain' and h['exit'].startswith('net-russia')
                             for h in model['hosts']))

    def test_location_variant_generated_for_entry_transport_without_exit_node(self):
        self.nodes[3]['domains'] = []
        self.nodes[3]['protocol'] = TCP
        model = self.model()
        self.assertIn('Reverse-RU-xHTTP', [p['name'] for p in model['profiles']])
        self.assertEqual(model['node_profiles']['ru-tcp']['config_profile'], 'Reverse-RU')
        grant = next(g for g in model['squad_grants'] if g['squad'] == 'Reverse-proxy')
        self.assertIn('VLESS_REALITY_XHTTP_REVERSE_RU', grant['inbounds'])

    def test_exclusive_non_global_exit_stays_exclusive_in_reverse_direction(self):
        self.nodes[2].update(exclusive_member=True, exclusive_profile='Xenus-team')
        self.nodes[1]['geo'] = 'russia'  # exclusive scope must agree on geography
        model = self.model()
        reverse = [h for h in model['hosts'] if h['kind'] == 'chain'
                   and h['exit'] == 'net-russia-1.example.test']
        self.assertEqual({h['config_profile'] for h in reverse}, {'Xenus-team', 'Xenus-team-xHTTP'})
        for host in reverse:
            self.assertEqual(host['internal_squads'], {'mode': 'allow_only', 'squads': ['Xenus-team']})

    def test_global_round_robin_entry_remains_one_host_bound_to_all_nodes(self):
        node = copy.deepcopy(self.nodes[0])
        node['name'] = 'global-rr-peer'
        node['domains'] = [node['domains'][1]]
        self.nodes.append(node)
        model = self.model()
        hosts = [h for h in model['hosts'] if h['kind'] == 'chain'
                 and h['exit'] == 'net-russia-1.example.test' and h['protocol'] == TCP]
        self.assertEqual(len(hosts), 1)
        self.assertEqual(set(hosts[0]['nodes']), {'shared-exit', 'global-rr-peer'})

    def test_verify_detects_stale_warp_snippet_without_route_guard(self):
        model = self.model()
        definition = {
            'name': 'rules-warp',
            'snippet': [{'vlessRoute': '0,2', 'domain': ['geosite:openai'], 'outboundTag': 'warp'}],
        }
        model['profile_snippets'] = [definition]
        panel = panel_for(model)
        stale = copy.deepcopy(definition)
        del stale['snippet'][0]['vlessRoute']
        panel['snippets'].append(stale)
        report = setup.remnawave_verify(panel, model, {
            'primary_tags': ['MANAGED_BY:ANSIBLE'], 'separator': ' | by ',
            'direct_route_id': 2, 'route_id_range': [400, 499],
            'rules_snippet': 'rules', 'outbounds_snippet': 'outbounds',
        })
        self.assertTrue(any('rules-warp differs from the inventory' in p for p in report['problems']))

    def test_warp_rule_only_matches_unmarked_or_direct_route_ids(self):
        inventory = yaml.safe_load((ROLE.parents[1] /
                                   'inventory/group_vars/vpn_server_remnawave/snippets_warp.yaml').read_text())
        template = inventory['vpn_server_remnawave_snippets_rules_warp'][0]['vlessRoute']
        env = Environment()
        for direct_id, expected in ((2, '0,2'), (7, '0,7'), ('', '0'), (None, '0'), (0, '0')):
            rendered = str(env.from_string(template).render(vpn_server_remnawave_hosts_vless_route_id_direct=direct_id))
            self.assertEqual(rendered, expected)
            self.assertNotIn('402', rendered.split(','))


INVENTORY = ROLE.parents[1] / 'inventory/group_vars/vpn_server_remnawave'


def _ansible_concat(values):
    """Template results the way ansible-core 2.21 has them: one expression
    keeps its native value, a string stays a string ("0,2" is no tuple)."""
    values = list(values)
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    return ''.join(str(v) for v in values)


class AnsibleLikeEnvironment(NativeEnvironment):
    concat = staticmethod(_ansible_concat)


class AnsibleLikeTemplate(NativeTemplate):
    environment_class = AnsibleLikeEnvironment


AnsibleLikeEnvironment.template_class = AnsibleLikeTemplate


def inventory_vars(snippets=None, direct_route_id=2):
    """The panel's inventory variables this role reads, rendered the way
    Ansible would: real routing_local.yaml, snippets_warp.yaml and
    config_profiles.yaml, with mock snippet contents unless given."""
    env = AnsibleLikeEnvironment()
    env.filters.update(AnsibleCoreFilters().filters())
    env.filters['remnawave_route_uuid'] = setup.remnawave_route_uuid
    env.globals.update({
        'vpn_server_remnawave_hosts_vless_route_id_direct': direct_route_id,
        'vpn_server_remnawave_config_profiles_log': {'loglevel': 'warning'},
        'vpn_server_remnawave_snippets_outbound_warp_tag': 'out-warp-socks',
        'warp_socks5_host': 'microwarp-socks', 'warp_socks5_port': 1080,
        'warp_socks5_user': 'socks5', 'warp_socks5_pass': 'mock-pass',
        **{'vpn_server_remnawave_snippets_key_' + name: name + '_prod_1'
           for name in ('outbounds_default', 'rules_default', 'outbounds_warp',
                        'rules_warp', 'outbounds_all', 'rules_all', 'balancers_all')},
        **{'vpn_server_remnawave_snippets_' + name: []
           for name in ('outbounds_default', 'rules_default', 'outbounds_warp',
                        'rules_warp', 'balancers_all')},
    })

    def render(value):
        if isinstance(value, dict):
            return {k: render(v) for k, v in value.items()}
        if isinstance(value, list):
            return [render(v) for v in value]
        return env.from_string(value).render() if isinstance(value, str) else value

    def load(name):
        return yaml.safe_load((INVENTORY / name).read_text())

    out = {}
    for name in ('routing_local.yaml', 'snippets_warp.yaml'):
        for key, value in load(name).items():
            out[key] = render(value)
            env.globals[key] = out[key]
    for key, value in (snippets or {}).items():
        env.globals['vpn_server_remnawave_snippets_' + key] = value
    out['composition'] = render(load('config_profiles.yaml')['vpn_server_remnawave_config_profiles_composition'])
    return out


class CompositionTests(unittest.TestCase):
    def setUp(self):
        # Render the actual inventory composition using mock snippet contents.
        self.options = options()
        self.options['profile_composition'] = inventory_vars()['composition']
        self.nodes = nodes()

    def model(self):
        return setup.remnawave_model(self.nodes, self.options)

    def test_inventory_rule_order_for_tcp_xhttp_shared_and_exclusive(self):
        for profile in self.model()['profiles']:
            expected = ['rules_default_prod_1']
            if profile['geo'] == 'global':
                expected.append('rules_warp_prod_1')
            expected.append('rules_all_prod_1')
            self.assertEqual(setup._snippet_refs(profile['config']['routing']['rules']), expected)
            self.assertEqual(profile['composition'],
                             ['defaults', 'warp_outbound', 'warp', 'chains'] if profile['geo'] == 'global'
                             else ['defaults', 'warp_outbound', 'chains'])

    def test_no_profile_has_inline_rules_or_a_domain_strategy(self):
        # Reverse profiles block nothing: their exit traffic falls to DIRECT.
        for profile in self.model()['profiles']:
            routing = profile['config']['routing']
            self.assertEqual([r for r in routing['rules'] if 'snippet' not in r], [])
            self.assertNotIn('domainStrategy', routing)

    def test_empty_condition_lists_are_refused(self):
        self.options['profile_composition'].append({
            'name': 'oops', 'config': {'routing': {'rules': [
                {'vlessRoute': '0', 'domain': [], 'outboundTag': 'out-warp-socks'}]}}})
        with self.assertRaisesRegex(AnsibleFilterError, 'empty domain list'):
            self.model()

    def test_outbounds_balancers_and_log_are_preserved(self):
        for profile in self.model()['profiles']:
            # Every profile can send local traffic to WARP: any node may be
            # where a path leaves its censored geo.
            expected = ['outbounds_default_prod_1', 'outbounds_warp_prod_1']
            expected.append('outbounds_all_prod_1')
            self.assertEqual(setup._snippet_refs(profile['config']['outbounds']), expected)
            self.assertEqual(profile['config']['routing']['balancers'],
                             [{'snippet': 'balancers_all_prod_1'}])
            self.assertEqual(profile['config']['log'], {'loglevel': 'warning'})

    def test_fragment_order_controls_rule_precedence(self):
        fragments = self.options['profile_composition']
        names = [f['name'] for f in fragments]
        warp, chains = names.index('warp'), names.index('chains')
        fragments[warp], fragments[chains] = fragments[chains], fragments[warp]
        profile = next(p for p in self.model()['profiles'] if p['name'] == 'Default-Profile')
        self.assertEqual(setup._snippet_refs(profile['config']['routing']['rules']),
                         ['rules_default_prod_1', 'rules_all_prod_1', 'rules_warp_prod_1'])

    def test_nested_config_merge_and_base_override(self):
        self.options['profile_composition'].append({
            'name': 'routing-settings', 'profiles': {'kind': 'global'},
            'config': {'routing': {'domainStrategy': 'IPIfNonMatch'},
                       'log': {'access': '/tmp/access.log'}},
        })
        self.options['profiles_base'][0]['config'] = {'log': {'loglevel': 'error'},
                                                     'routing': {'domainStrategy': 'AsIs'}}
        config = next(p['config'] for p in self.model()['profiles'] if p['name'] == 'Default-Profile')
        self.assertEqual(config['log'], {'loglevel': 'error', 'access': '/tmp/access.log'})
        self.assertEqual(config['routing']['domainStrategy'], 'AsIs')
        self.assertEqual(len(config['routing']['rules']), 3)
        self.assertIn('balancers', config['routing'])

    def test_base_list_override_replaces_composition_list(self):
        self.options['profiles_base'][0]['config'] = {'routing': {'rules': [{'outboundTag': 'DIRECT'}]}}
        config = next(p['config'] for p in self.model()['profiles'] if p['name'] == 'Default-Profile')
        self.assertEqual(config['routing']['rules'], [{'outboundTag': 'DIRECT'}])
        self.assertIn('balancers', config['routing'])

    def test_scoped_inline_rules_map_tags_without_mutating_fragments(self):
        fragment = {
            'name': 'tcp-inline', 'inbounds': ['VLESS_TCP_REALITY'],
            'config': {'routing': {'rules': [{'domain': ['example.test'], 'outboundTag': 'DIRECT'}]}},
        }
        self.options['profile_composition'].insert(1, fragment)
        original = copy.deepcopy(self.options)
        for profile in self.model()['profiles']:
            if profile['protocol'] == TCP:
                rule = profile['config']['routing']['rules'][1]
                self.assertEqual(rule['inboundTag'], [profile['inbound_map']['VLESS_TCP_REALITY']])
            else:
                self.assertNotIn('tcp-inline', profile['composition'])
        self.assertEqual(self.options, original)

    def test_scoped_snippet_rule_is_rejected(self):
        warp = next(f for f in self.options['profile_composition'] if f['name'] == 'warp')
        warp['inbounds'] = ['VLESS_TCP_REALITY']
        with self.assertRaisesRegex(AnsibleFilterError, 'must be inline'):
            self.model()

    def test_snippet_definitions_are_collected_once(self):
        duplicate = copy.deepcopy(self.options['profile_composition'][1]['snippets'][0])
        self.options['profile_composition'].append({'name': 'repeat-definition', 'snippets': [duplicate]})
        snippets = self.model()['profile_snippets']
        self.assertEqual(len(snippets), 5)
        self.assertEqual([s['name'] for s in snippets], [
            'outbounds_default_prod_1', 'rules_default_prod_1', 'outbounds_warp_prod_1',
            'rules_warp_prod_1', 'balancers_all_prod_1',
        ])

    def test_conflicting_snippet_definitions_are_rejected(self):
        duplicate = copy.deepcopy(self.options['profile_composition'][1]['snippets'][0])
        duplicate['snippet'] = [{'tag': 'different'}]
        self.options['profile_composition'].append({'name': 'conflict', 'snippets': [duplicate]})
        with self.assertRaisesRegex(AnsibleFilterError, 'Conflicting definitions'):
            self.model()

    def test_bad_composition_shapes_are_rejected(self):
        for fragment, message in [
            ({'config': {}}, 'needs a name'),
            ({'name': 'defaults'}, 'Duplicate'),
            ({'name': 'bad', 'rules': []}, 'unknown fields'),
            ({'name': 'bad', 'config': {'inbounds': []}}, 'without inbounds'),
            ({'name': 'bad', 'config': {'routing': {'rules': 'not-a-list'}}}, 'must be a list'),
            ({'name': 'bad', 'config': {'routing': {'rules': ['not-a-mapping']}}}, 'of mappings'),
            ({'name': 'bad', 'profiles': {'typo': 'global'}}, 'Unknown profile selector keys'),
            ({'name': 'bad', 'snippets': [{'name': 'bad'}]}, 'snippets need'),
        ]:
            with self.subTest(fragment=fragment):
                opts = copy.deepcopy(self.options)
                opts['profile_composition'].append(fragment)
                with self.assertRaisesRegex(AnsibleFilterError, message):
                    setup.remnawave_model(self.nodes, opts)

    def test_legacy_options_fail_with_migration_guidance(self):
        for key in ('profile_common', 'addons'):
            self.options[key] = {}
            with self.assertRaisesRegex(AnsibleFilterError, 'Replace profile_common/addons'):
                self.model()
            del self.options[key]

    def test_verify_detects_wrong_snippet_order(self):
        model = self.model()
        panel = panel_for(model)
        profile = next(p for p in panel['config_profiles'] if p['name'] == 'Default-Profile')
        rules = profile['config']['routing']['rules']
        rules[1], rules[2] = rules[2], rules[1]
        report = setup.remnawave_verify(panel, model, {
            'primary_tags': ['MANAGED_BY:ANSIBLE'], 'separator': ' | by ',
            'direct_route_id': 2, 'route_id_range': [400, 499],
            'rules_snippet': 'rules', 'outbounds_snippet': 'outbounds',
        })
        self.assertTrue(any("'Default-Profile' embeds rules snippets" in p for p in report['problems']))


class RoutingDependencyTests(unittest.TestCase):
    def setUp(self):
        fixture = CompositionTests()
        fixture.setUp()
        self.options = fixture.options
        # Populate real targets instead of empty snippet mocks.
        definitions = {
            'outbounds_default_prod_1': [{'tag': 'DIRECT'}, {'tag': 'BLOCK'}],
            'rules_default_prod_1': [{'ip': ['geoip:private'], 'outboundTag': 'BLOCK'}],
            'outbounds_warp_prod_1': [{'tag': 'out-warp-socks'}],
            'rules_warp_prod_1': [{'domain': ['geosite:openai'], 'vlessRoute': '0,2',
                                 'outboundTag': 'out-warp-socks'}],
        }
        for fragment in self.options['profile_composition']:
            for definition in fragment.get('snippets', []):
                definition['snippet'] = definitions.get(definition['name'], [])
        self.nodes = nodes()
        for index, node in enumerate(self.nodes[2:4], 1):
            domain = 'net-russia-%d.example.test' % index
            node['domains'].append({'domain': domain, 'type': 'net-location'})
            self.options['outbounds'].append({'address': domain, 'tag': 'out-chain-ru-%d' % index})
        self.model = setup.remnawave_model(self.nodes, self.options)
        self.panel = panel_for(self.model)
        self.panel['snippets'] = copy.deepcopy(self.model['profile_snippets']) + [
            {'name': 'rules_all_prod_1', 'snippet': self.model['rules']},
            {'name': 'outbounds_all_prod_1', 'snippet': [
                {'tag': o['tag'], 'settings': {'vnext': [{'address': o['address']}]}}
                for o in self.options['outbounds']
            ]},
        ]

    def verify(self):
        return setup.remnawave_verify(self.panel, self.model, {
            'primary_tags': ['MANAGED_BY:ANSIBLE'], 'separator': ' | by ',
            'direct_route_id': 2, 'route_id_range': [400, 499],
            'rules_snippet': 'rules_all_prod_1', 'outbounds_snippet': 'outbounds_all_prod_1',
        })['problems']

    def test_non_global_direct_id_2_does_not_activate_catalog_warp_rule(self):
        self.assertEqual(self.verify(), [])
        direct = [h for h in self.model['hosts'] if h['kind'] == 'direct'
                  and h['config_profile'].startswith('Reverse-RU')]
        self.assertEqual(len(direct), 2)
        for host in direct:
            self.assertEqual(host['vless_route_id'], 2)
            profile = next(p for p in self.model['profiles'] if p['name'] == host['config_profile'])
            self.assertNotIn('rules_warp_prod_1', setup._snippet_refs(profile['config']['routing']['rules']))
            # The outbound is there: a node of a censored geo hands default
            # users' local traffic to its WARP where their path leaves the geo.
            self.assertIn('outbounds_warp_prod_1', setup._snippet_refs(profile['config']['outbounds']))
            self.assertEqual(setup._routing_dependencies(
                profile['config'], {s['name']: s['snippet'] for s in self.panel['snippets']}), [])

    def test_stray_warp_snippet_in_non_global_profile_is_rejected(self):
        for name in ('Reverse-RU', 'Reverse-RU-xHTTP'):
            profile = next(p for p in self.panel['config_profiles'] if p['name'] == name)
            profile['config']['routing']['rules'].insert(1, {'snippet': 'rules_warp_prod_1'})
        problems = self.verify()
        for name in ('Reverse-RU', 'Reverse-RU-xHTTP'):
            self.assertIn("Config profile '%s' embeds rules snippets rules_default_prod_1, "
                          "rules_warp_prod_1, rules_all_prod_1, the inventory wants "
                          "rules_default_prod_1, rules_all_prod_1" % name, problems)

    def test_inline_warp_rule_cannot_evade_snippet_reference_check(self):
        profile = next(p for p in self.panel['config_profiles'] if p['name'] == 'Reverse-RU')
        profile['config']['routing']['rules'].insert(1, {
            'domain': ['geosite:openai'], 'vlessRoute': '0,2', 'outboundTag': 'out-warp-socks',
        })
        self.assertIn("Config profile 'Reverse-RU' holds inline rules that differ from the "
                      "inventory", self.verify())

    def test_global_profile_missing_warp_outbound_is_rejected(self):
        profile = next(p for p in self.panel['config_profiles'] if p['name'] == 'Default-Profile')
        profile['config']['outbounds'] = [i for i in profile['config']['outbounds']
                                        if i.get('snippet') != 'outbounds_warp_prod_1']
        self.assertTrue(any("'Default-Profile': routing rule targets outbound out-warp-socks" in p
                            for p in self.verify()))

    def test_route_id_split_across_rules_to_one_target_is_no_conflict(self):
        rules = next(s for s in self.panel['snippets'] if s['name'] == 'rules_all_prod_1')
        rules['snippet'][:0] = [
            {'vlessRoute': '10', 'ip': ['geoip:ru'], 'outboundTag': 'out-chain-ru-1'},
            {'vlessRoute': '10', 'domain': ['geosite:category-ru'], 'outboundTag': 'out-chain-ru-1'},
            {'vlessRoute': '100', 'ip': ['geoip:ru'], 'balancerTag': 'bal-ru'},
            {'vlessRoute': '100', 'domain': ['geosite:category-ru'], 'balancerTag': 'bal-ru'},
        ]
        self.assertFalse([p for p in self.verify() if 'different rules' in p])
        # Conditional rules only split traffic off (local traffic to WARP), so
        # they may differ; two rules on the route alone may not.
        rules['snippet'][1]['outboundTag'] = 'out-chain-ru-2'
        self.assertFalse([p for p in self.verify() if 'different rules' in p])
        rules['snippet'][2:4] = [{'vlessRoute': '100', 'balancerTag': 'bal-ru'},
                                 {'vlessRoute': '99-101', 'outboundTag': 'out-chain-ru-2'}]
        self.assertEqual([p for p in self.verify() if 'different rules' in p], [
            'Route id 100 is sent to bal-ru and to out-chain-ru-2 by different rules'])

    def test_nested_snippet_rules_and_outbounds_are_resolved(self):
        snippets = {'rules': [{'snippet': 'nested-rules'}],
                    'nested-rules': [{'outboundTag': 'warp'}],
                    'outbounds': [{'snippet': 'nested-outbounds'}],
                    'nested-outbounds': [{'tag': 'warp'}]}
        config = {'outbounds': [{'snippet': 'outbounds'}],
                  'routing': {'rules': [{'snippet': 'rules'}]}}
        self.assertEqual(setup._routing_dependencies(config, snippets), [])
        snippets['nested-outbounds'] = [{'tag': 'DIRECT'}]
        self.assertEqual(setup._routing_dependencies(config, snippets), [
            'routing rule targets outbound warp, which is absent from this profile'])

    def test_missing_and_cyclic_snippets_are_reported(self):
        config = {'routing': {'rules': [{'snippet': 'rules'}]}}
        self.assertEqual(setup._routing_dependencies(config, {}), [
            'routing.rules references missing snippet rules'])
        self.assertEqual(setup._routing_dependencies(config, {'rules': [{'snippet': 'rules'}]}), [
            'routing.rules has a cyclic snippet reference rules -> rules'])

    def test_balancer_and_fallback_targets_must_exist_in_same_profile(self):
        config = {'outbounds': [{'tag': 'DIRECT'}], 'routing': {
            'rules': [{'balancerTag': 'bal'}],
            'balancers': [{'tag': 'bal', 'fallbackTag': 'DIRECT'}],
        }}
        self.assertEqual(setup._routing_dependencies(config, {}), [])
        config['routing']['balancers'][0]['fallbackTag'] = 'missing'
        self.assertTrue(any('fallback outbound missing' in p
                            for p in setup._routing_dependencies(config, {})))
        config['routing']['balancers'] = []
        self.assertEqual(setup._routing_dependencies(config, {}), [
            'routing rule targets balancer bal, which is absent from this profile'])


class ServerNamesTests(unittest.TestCase):
    def model(self, server_names):
        opts = options()
        for base in opts['profiles_base']:
            base['inbounds'][0]['streamSettings']['realitySettings']['serverNames'] = server_names
        return setup.remnawave_model(nodes(), opts)

    def every_dialed_address(self):
        model = self.model([])
        return sorted(set(h['address'] for h in model['hosts'])
                      | set(o['address'] for o in options()['outbounds']))

    def test_no_warning_when_every_dialed_address_is_listed(self):
        model = self.model(self.every_dialed_address())
        self.assertFalse(any('serverNames' in w for w in model['warnings']))

    def test_an_unlisted_host_address_is_reported_per_inbound(self):
        listed = [a for a in self.every_dialed_address() if a != 'chain-russia-1.example.test']
        warnings = [w for w in self.model(listed)['warnings'] if 'serverNames' in w]
        self.assertTrue(warnings)
        self.assertTrue(all('chain-russia-1.example.test' in w for w in warnings))
        self.assertTrue(any('Default-Profile' in w for w in warnings))


SERVICE = 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee'


def hop_node(name, country, geo, domain, hops=None, protocol=TCP, extra=()):
    node = {'name': name, 'country': country, 'geo': geo, 'protocol': protocol,
            'domains': [{'domain': domain + '.example.test', 'type': 'net-location'}]
            + [{'domain': d + '.example.test', 'type': 'chain-location'} for d in extra],
            'exclusive_member': False, 'exclusive_profile': ''}
    if hops is not None:
        node['hops'] = hops
    return node


def hop_scenario(fanout=False, visible=True):
    """reverse_scenario plus hops: EU-1 (shared-exit) carried on by hidden
    eu-tail (and eu-tail-2 with fanout), RU entry ru-tcp by hidden ru-tail -
    the 4-hop RU-1 > RU-3 > EU-1 > EU-3 - and eu-visible published through
    ru-tcp only."""
    items, opts = reverse_scenario()
    items += [hop_node('eu-tail', 'DE', 'global', 'net-europe-3', {'from': ['shared-exit']}),
              hop_node('ru-tail', 'RU', 'russia', 'net-russia-3', {'from': ['ru-tcp']})]
    if visible:
        items.append(hop_node('eu-visible', 'SE', 'global', 'net-europe-5',
                              {'from': [{'host': 'ru-tcp', 'hidden': False}]}))
    if fanout:
        items.append(hop_node('eu-tail-2', 'FI', 'global', 'net-europe-4', {'from': ['shared-exit']}))
    for domain, tag in (('net-europe-3', 'out-chain-3'), ('net-europe-4', 'out-chain-4'),
                        ('net-europe-5', 'out-chain-5'), ('net-russia-3', 'out-chain-ru-3')):
        opts['outbounds'].append({'address': domain + '.example.test', 'tag': tag})
    opts['local_traffic'] = {'russia': {'domain': ['geosite:category-ru'], 'ip': ['geoip:ru']}}
    opts['observatory'] = {
        'global': {'probeUrl': 'https://www.gstatic.com/generate_204', 'probeInterval': '1m'},
        'russia': {'probeUrl': 'https://www.google.ru/generate_204', 'probeInterval': '1m'},
    }
    return items, opts


def panel_with_outbounds(model, opts):
    """panel_for with every outbound as the snippets stage writes it: the
    planned ones handing over route 0, the hop ones their route, all as the
    service user."""
    panel = panel_for(model)
    outbounds = [{'tag': o['tag'], 'settings': {'vnext': [{
        'address': o['address'],
        'users': [{'id': setup.remnawave_route_uuid(SERVICE, o.get('route', 0))}]}]}}
        for o in opts['outbounds'] + model['hop_outbounds']]
    # What the warp_outbound fragment gives every profile in the inventory.
    outbounds.append({'tag': 'out-warp-socks', 'protocol': 'socks'})
    panel['snippets'] = [s for s in panel['snippets'] if s['name'] != 'outbounds']
    panel['snippets'].append({'name': 'outbounds', 'snippet': outbounds})
    return panel


def verify_problems(model, panel, **extra):
    options_ = {'primary_tags': ['MANAGED_BY:ANSIBLE'], 'separator': ' | by ',
                'direct_route_id': 2, 'route_id_range': [400, 999],
                'rules_snippet': 'rules', 'outbounds_snippet': 'outbounds'}
    options_.update(extra)
    return setup.remnawave_verify(panel, model, options_)


def short(paths):
    return [' > '.join(d.split('.')[0] for d in path) for path in paths]


class LegacySnapshotTests(unittest.TestCase):
    """Without remna_node_hops nothing panels and subscriptions depend on moves."""

    def test_models_without_hops_match_the_snapshot_taken_before_hops(self):
        snapshot = json.loads((ROLE / 'tests/fixtures/legacy_snapshot.json').read_text())
        for name, (items, opts) in legacy_scenarios().items():
            with self.subTest(scenario=name):
                view = json.loads(json.dumps(legacy_view(setup.remnawave_model(items, opts)),
                                             sort_keys=True))
                self.assertEqual(view, snapshot[name])

    def test_local_traffic_adds_rules_but_keeps_every_id_and_tag(self):
        items, opts = reverse_scenario()
        before = setup.remnawave_model(copy.deepcopy(items), copy.deepcopy(opts))
        opts['local_traffic'] = {'russia': {'domain': ['geosite:category-ru'], 'ip': ['geoip:ru']}}
        after = setup.remnawave_model(items, opts)
        self.assertEqual(legacy_view(after), legacy_view(before))
        local = [r for r in after['rules'] if 'domain' in r or 'ip' in r]
        # RU entries reaching global and exclusive exits leave the russia geo there.
        self.assertEqual(local, [
            {'vlessRoute': '400,401', 'domain': ['geosite:category-ru'], 'outboundTag': 'out-warp-socks'},
            {'vlessRoute': '400,401', 'ip': ['geoip:ru'], 'outboundTag': 'out-warp-socks'},
        ])
        self.assertEqual(after['hop_outbounds'], [])


class RouteUuidTests(unittest.TestCase):
    def test_the_route_goes_into_the_third_group(self):
        self.assertEqual(setup.remnawave_route_uuid(SERVICE, 405), 'aaaaaaaa-bbbb-0195-8ddd-eeeeeeeeeeee')
        self.assertEqual(setup.remnawave_route_uuid(SERVICE.upper(), '0'), 'aaaaaaaa-bbbb-0000-8ddd-eeeeeeeeeeee')
        self.assertEqual(setup._uuid_route(setup.remnawave_route_uuid(SERVICE, 65535)), 65535)

    def test_what_is_no_uuid_or_no_route_is_refused(self):
        for uuid, route in (('not-a-uuid', 1), (SERVICE, -1), (SERVICE, 65536), (SERVICE, 'x')):
            with self.subTest(uuid=uuid, route=route):
                with self.assertRaises(AnsibleFilterError):
                    setup.remnawave_route_uuid(uuid, route)

    def test_the_outbound_templates_hand_over_the_route(self):
        env = AnsibleLikeEnvironment()
        env.filters['remnawave_route_uuid'] = setup.remnawave_route_uuid
        for name in ('snippet_vless_reality_tcp_001.yaml', 'snippet_vless_reality_xhttp_001.yaml'):
            template = list(yaml.safe_load((INVENTORY / name).read_text()).values())[0]
            user_id = template['settings']['vnext'][0]['users'][0]['id']
            for route, expected in ((None, '0000'), (404, '0194')):
                context = {'service_user_id': SERVICE}
                if route is not None:
                    context['node_route_id'] = route
                with self.subTest(template=name, route=route):
                    self.assertEqual(env.from_string(user_id).render(**context)[14:18], expected)


class HopTests(unittest.TestCase):
    def model(self, **kwargs):
        items, opts = hop_scenario(**kwargs)
        return setup.remnawave_model(items, opts), opts

    def host(self, model, remark_start):
        return next(h for h in model['hosts'] if h['remark'].startswith(remark_start))

    def test_a_hidden_node_carries_on_for_its_upstream_and_is_not_published(self):
        model, _ = self.model()
        addresses = [h['address'] for h in model['hosts']]
        self.assertNotIn('net-europe-3.example.test', addresses)
        self.assertNotIn('net-russia-3.example.test', addresses)
        direct = self.host(model, '🇳🇱 EU-1')
        self.assertEqual(short(direct['paths']), ['net-europe-1 > net-europe-3'])
        self.assertNotEqual(direct['vless_route_id'], 2)
        self.assertEqual(short(self.host(model, '🇷🇺 RU-1')['paths']), ['net-russia-1 > net-russia-3'])
        # A direct exit without a tail keeps the direct route id.
        self.assertEqual(self.host(model, '🇷🇺 RU-2')['vless_route_id'], 2)

    def test_the_tail_of_an_entry_and_of_an_exit_make_four_hops(self):
        model, opts = self.model()
        host = self.host(model, '🇳🇱 EU-1 | by 🇷🇺 RU-1')
        self.assertEqual(short(host['paths']),
                         ['chain-russia-1 > net-russia-3 > net-europe-1 > net-europe-3'])
        routes = dict((r['id'], r) for r in model['routes'])
        hops = []
        route = host['vless_route_id']
        while route:
            step = routes[route]
            hops.append((step['next'][0]['address'].split('.')[0], step['local']))
            route = step['next'][0]['carried']
        # Local traffic leaves the russia geo at RU-3, the last node inside it.
        self.assertEqual(hops, [('net-russia-3', None), ('net-europe-1', 'russia'),
                                ('net-europe-3', None)])
        self.assertEqual(verify_problems(model, panel_with_outbounds(model, opts))['problems'], [])

    def test_a_hidden_entry_tail_reaches_the_reverse_direction_too(self):
        model, _ = self.model()
        self.assertEqual(short(self.host(model, '🇷🇺 RU-1 | by 🇳🇱 EU-1')['paths']),
                         ['chain-europe-1 > net-europe-3 > net-russia-1 > net-russia-3'])

    def test_a_shared_node_may_be_hidden_behind_an_exclusive_one(self):
        # Exclusive users exiting through a shared node give nobody access
        # they lacked; the opposite direction is refused (test below).
        items, opts = hop_scenario()
        next(n for n in items if n['name'] == 'eu-tail')['hops']['from'].append('exclusive-exit')
        model = setup.remnawave_model(items, opts)
        host = next(h for h in model['hosts'] if h['remark'] == '🇨🇿 EU-1 · Xenus-team')
        self.assertEqual(short(host['paths']), ['net-europe-2 > net-europe-3'])
        self.assertEqual(host['config_profile'], 'Xenus-team')

    def test_fan_in_shares_the_action_of_the_hidden_node(self):
        items, opts = hop_scenario()
        items.append(hop_node('ru-tcp-peer', 'RU', 'russia', 'net-russia-6',
                              extra=['chain-russia-6']))
        items[-1]['protocol'] = TCP
        opts['outbounds'].append({'address': 'net-russia-6.example.test', 'tag': 'out-chain-ru-6'})
        tail = next(n for n in items if n['name'] == 'ru-tail')
        tail['hops']['from'].append('ru-tcp-peer')
        model = setup.remnawave_model(items, opts)
        via = [h for h in model['hosts'] if h['kind'] == 'chain'
               and h['exit'] == 'net-europe-1.example.test' and h['entry'] in (
                   'chain-russia-1.example.test', 'chain-russia-6.example.test')]
        self.assertEqual(len(via), 2)
        for host in via:
            self.assertEqual(short(host['paths'])[0].split(' > ')[1:], ['net-russia-3', 'net-europe-1', 'net-europe-3'])
        routes = dict((r['id'], r) for r in model['routes'])
        # Both entries hand the same route to RU-3: one action, one id.
        self.assertEqual(len(set(routes[h['vless_route_id']]['next'][0]['carried'] for h in via)), 1)

    def test_fan_out_balances_inline_in_the_balancing_profile_only(self):
        model, opts = self.model(fanout=True)
        balanced = [r for r in model['routes'] if r['balancer']]
        self.assertTrue(balanced)
        self.assertTrue(all(r['profiles'] == ['Default-Profile'] for r in balanced))
        self.assertFalse(any(r.get('balancerTag') for r in model['rules']))
        self.assertFalse(set(str(r['id']) for r in balanced)
                         & set(r['vlessRoute'] for r in model['rules']))
        for profile in model['profiles']:
            config = profile['config']
            if profile['name'] != 'Default-Profile':
                self.assertNotIn('observatory', config)
                continue
            tags = sorted(b['tag'] for b in config['routing']['balancers'] if 'tag' in b)
            self.assertEqual(tags, sorted(r['balancer'] for r in balanced))
            for balancer in config['routing']['balancers']:
                self.assertEqual(balancer['strategy'], {'type': 'leastPing'})
                self.assertEqual(balancer['fallbackTag'], balancer['selector'][0])
            # The balanced reverse paths end in Russia: its probe is taken
            # when one is set (this scenario sets one).
            self.assertEqual(config['observatory']['probeUrl'], 'https://www.google.ru/generate_204')
            self.assertEqual(config['observatory']['subjectSelector'],
                             sorted(n['tag'] for r in balanced for n in r['next']))
        self.assertEqual(sorted(short(self.host(model, '🇳🇱 EU-1')['paths'])),
                         ['net-europe-1 > net-europe-3', 'net-europe-1 > net-europe-4'])
        self.assertEqual(verify_problems(model, panel_with_outbounds(model, opts))['problems'], [])

    def test_hop_tags_never_prefix_one_another(self):
        model, _ = self.model(fanout=True)
        tags = [o['tag'] for o in model['hop_outbounds']]
        for tag in tags:
            self.assertEqual([t for t in tags if t.startswith(tag)], [tag])

    def test_a_visible_relation_publishes_only_d_by_u(self):
        model, opts = self.model()
        published = [h for h in model['hosts'] if h['exit'] == 'net-europe-5.example.test']
        self.assertEqual([(h['remark'], h['via'], short(h['paths'])) for h in published], [
            ('🇸🇪 EU-2 | by 🇷🇺 RU-1', 'relation', ['chain-russia-1 > net-russia-3 > net-europe-5'])])
        self.assertEqual(published[0]['nodes'], ['ru-tcp'])
        self.assertEqual(verify_problems(model, panel_with_outbounds(model, opts))['problems'], [])

    def test_publish_direct_adds_the_own_host_and_auto_chains_without_a_collision(self):
        items, opts = hop_scenario()
        next(n for n in items if n['name'] == 'eu-visible')['hops']['publish_direct'] = True
        model = setup.remnawave_model(items, opts)
        published = sorted((h['remark'], h.get('via', h['kind']))
                           for h in model['hosts'] if h['exit'] == 'net-europe-5.example.test')
        self.assertEqual(published, [('🇸🇪 EU-2', 'direct'),
                                     ('🇸🇪 EU-2 | by 🇷🇺 RU-1', 'relation'),
                                     ('🇸🇪 EU-2 | by 🇷🇺 RU-2', 'chain')])

    def test_a_visible_relation_into_a_location_node_gets_its_variant(self):
        items, opts = hop_scenario(visible=False)
        items.append(hop_node('ru-visible', 'RU', 'russia', 'net-russia-7',
                              {'from': [{'host': 'global-xhttp', 'hidden': False}]}))
        opts['outbounds'].append({'address': 'net-russia-7.example.test', 'tag': 'out-chain-ru-7'})
        model = setup.remnawave_model(items, opts)
        host = next(h for h in model['hosts'] if h['exit'] == 'net-russia-7.example.test')
        self.assertEqual((host['config_profile'], host['protocol']), ('Reverse-RU-xHTTP', XHTTP))
        self.assertEqual(host['nodes'], ['global-xhttp'])

    def refused(self, change, message):
        items, opts = hop_scenario()
        change(items, opts)
        with self.assertRaisesRegex(AnsibleFilterError, message):
            setup.remnawave_model(items, opts)

    def node_of(self, items, name):
        return next(n for n in items if n['name'] == name)

    def test_a_cycle_is_refused_with_the_whole_cycle_named(self):
        def change(items, opts):
            self.node_of(items, 'shared-exit')['hops'] = {'from': ['eu-tail']}
        self.refused(change, r'hop relations form a cycle: eu-tail → shared-exit → eu-tail\. Each '
                             r'arrow means the next host lists the previous one in '
                             r'remna_node_hops\.from; remove one of these relations\.')

    def test_a_longer_cycle_is_named_too(self):
        def change(items, opts):
            items.append(hop_node('eu-mid', 'AT', 'global', 'net-europe-8', {'from': ['eu-tail']}))
            opts['outbounds'].append({'address': 'net-europe-8.example.test', 'tag': 'out-chain-8'})
            self.node_of(items, 'shared-exit')['hops'] = {'from': ['eu-mid']}
        self.refused(change, 'cycle: eu-mid → shared-exit → eu-tail → eu-mid')

    def test_what_cannot_work_is_refused(self):
        def hidden_across_geos(items, opts):
            self.node_of(items, 'ru-tail')['hops'] = {'from': ['shared-exit']}

        def hidden_into_exclusive(items, opts):
            self.node_of(items, 'exclusive-exit')['hops'] = {'from': ['shared-exit']}

        def self_relation(items, opts):
            self.node_of(items, 'eu-tail')['hops'] = {'from': ['eu-tail']}

        def unknown_host(items, opts):
            self.node_of(items, 'eu-tail')['hops'] = {'from': ['nowhere']}

        def twice(items, opts):
            self.node_of(items, 'eu-tail')['hops'] = {'from': ['shared-exit', 'shared-exit']}

        def no_chain_domain(items, opts):
            self.node_of(items, 'eu-visible')['hops'] = {'from': [{'host': 'eu-tail', 'hidden': False}]}

        def round_robin_disagrees(items, opts):
            peer = copy.deepcopy(self.node_of(items, 'shared-exit'))
            peer['name'] = 'shared-exit-peer'
            peer['domains'] = peer['domains'][:1]
            items.append(peer)

        def ipv6_forwarder(items, opts):
            self.node_of(items, 'shared-exit')['hops'] = {'egress': {'interface': 'ens4',
                                                                     'family': 'ipv6'}}

        def typo(items, opts):
            self.node_of(items, 'eu-tail')['hops'] = {'form': ['shared-exit']}

        for change, message in (
                (hidden_across_geos, 'crosses censorship geos'),
                (hidden_into_exclusive, 'exclusive node exclusive-exit'),
                (self_relation, 'names the host itself.*egress'),
                (unknown_host, 'names nowhere, which is no node of this panel'),
                (twice, 'names shared-exit twice'),
                (no_chain_domain, r'eu-tail needs exactly one chain \(chain-location\) domain'),
                (round_robin_disagrees, 'declare different hop relations'),
                (ipv6_forwarder, 'family of shared-exit is ipv6'),
                (typo, 'unknown keys form')):
            with self.subTest(change=change.__name__):
                self.refused(change, message)

    def test_an_auto_pair_whose_tails_meet_is_skipped_with_a_warning(self):
        items, opts = hop_scenario()
        opts['skip_same_country'] = False
        self.node_of(items, 'ru-tail')['hops']['from'].append('ru-xhttp')
        model = setup.remnawave_model(items, opts)
        self.assertTrue(any('both reach ru-tail' in w for w in model['warnings']))
        for host in model['hosts']:
            for path in host['paths']:
                hosts = [d for d in path]
                self.assertEqual(len(hosts), len(set(hosts)))

    def test_verify_names_a_broken_middle_hop(self):
        model, opts = self.model()
        panel = panel_with_outbounds(model, opts)
        outbounds = next(s for s in panel['snippets'] if s['name'] == 'outbounds')['snippet']
        middle = next(o for o in outbounds if o['tag'].startswith('out-hop-001'))
        # The hop to RU-3 hands over route 0: RU-3 becomes the exit.
        middle['settings']['vnext'][0]['users'][0]['id'] = setup.remnawave_route_uuid(SERVICE, 0)
        problems = verify_problems(model, panel)['problems']
        self.assertTrue(any("'🇳🇱 EU-1 | by 🇷🇺 RU-1' goes chain-russia-1.example.test > "
                            "net-russia-3.example.test, the inventory wants" in p for p in problems),
                        problems)

    def test_verify_checks_the_service_user_reaches_every_dialed_node(self):
        model, opts = self.model()
        panel = panel_with_outbounds(model, opts)
        user = {'username': 'svc', 'vlessUuid': SERVICE,
                'activeInternalSquads': [{'name': 'Default-Squad'}]}
        problems = verify_problems(model, panel, service_user=user)['problems']
        self.assertTrue(any('Service user svc cannot connect to node ru-tail' in p for p in problems))
        user['activeInternalSquads'] += [{'name': 'Reverse-proxy'}, {'name': 'Xenus-team'}]
        self.assertFalse([p for p in verify_problems(model, panel, service_user=user)['problems']
                          if 'Service user' in p])
        user['vlessUuid'] = '11111111-2222-4333-8444-555555555555'
        self.assertTrue(any('is not the user the chain outbounds authenticate as' in p
                            for p in verify_problems(model, panel, service_user=user)['problems']))
        notes = verify_problems(model, panel)['notes']
        self.assertTrue(any('vpn_server_remnawave_service_user_name' in n for n in notes))


# --- Xray routing, evaluated -------------------------------------------------

SITES = {  # domain -> geosite lists it is in
    'yandex.ru': ['category-ru'], 'gosuslugi.ru': ['category-ru'],
    'shop-in-moscow.com': [], 'google.com': [], 'gemini.google.com': ['google-gemini'],
}
RESOLVED = {'yandex.ru': '77.88.55.88', 'gosuslugi.ru': '213.59.254.7',
            'shop-in-moscow.com': '95.213.0.9', 'google.com': '142.250.74.46',
            'gemini.google.com': '142.250.74.47'}
GEOIP = {'77.88.55.88': 'ru', '213.59.254.7': 'ru', '95.213.0.9': 'ru',
         '142.250.74.46': 'us', '142.250.74.47': 'us', '10.1.2.3': 'private', '8.8.8.8': 'us'}


class Xray(object):
    """Enough of Xray's router for the rules this role writes: first match;
    vlessRoute lists/ranges; inboundTag; geosite/plain domains; geoip and
    CIDR /0; AsIs or IPIfNonMatch (resolve a domain nothing matched, then
    match again); balancers; the first outbound by default."""

    def __init__(self, config, snippets):
        def expand(section):
            out = []
            for item in section or []:
                out.extend(expand(snippets[item['snippet']]) if 'snippet' in item else [item])
            return out
        routing = config.get('routing') or {}
        self.rules = expand(routing.get('rules'))
        self.outbounds = [o['tag'] for o in expand(config.get('outbounds'))]
        self.balancers = dict((b['tag'], b) for b in expand(routing.get('balancers')))
        self.strategy = routing.get('domainStrategy', 'AsIs')
        for rule in self.rules:
            for target in ('outboundTag', 'balancerTag'):
                if rule.get(target):
                    known = self.outbounds if target == 'outboundTag' else self.balancers
                    assert rule[target] in known, 'dangling %s %s' % (target, rule[target])

    @staticmethod
    def domain_matches(entries, domain):
        for entry in entries:
            if entry.startswith('geosite:'):
                if entry[8:] in SITES.get(domain, []):
                    return True
            elif domain == entry or domain.endswith('.' + entry):
                return True
        return False

    @staticmethod
    def ip_matches(entries, ip):
        for entry in entries:
            if entry.startswith('geoip:') and GEOIP.get(ip) == entry[6:]:
                return True
            if entry in ('0.0.0.0/0', '::/0') and (':' in ip) == (entry == '::/0'):
                return True
        return False

    def first(self, inbound, route, domain, ip):
        for rule in self.rules:
            if 'inboundTag' in rule and inbound not in rule['inboundTag']:
                continue
            if 'vlessRoute' in rule and route not in setup._route_numbers(rule['vlessRoute']):
                continue
            if 'domain' in rule and not (domain and self.domain_matches(rule['domain'], domain)):
                continue
            if 'ip' in rule and not (ip and self.ip_matches(rule['ip'], ip)):
                continue
            return rule.get('outboundTag') or 'balancer:' + rule['balancerTag']
        return None

    def route(self, inbound, route, target):
        is_ip = target[0].isdigit()
        found = self.first(inbound, route, None if is_ip else target, target if is_ip else None)
        if found is None and not is_ip and self.strategy == 'IPIfNonMatch':
            found = self.first(inbound, route, target, RESOLVED[target])
        return found or self.outbounds[0]


class RoutingSemanticsTests(unittest.TestCase):
    """Default users' local traffic leaves through WARP where their path leaves
    Russia, or at the global exit; reverse users get the whole internet
    DIRECT at the Russian exit; nothing touches the node's own API."""

    def setUp(self):
        defaults = yaml.safe_load((INVENTORY / 'snippets.yaml').read_text())
        rendered = inventory_vars()
        items, self.opts = hop_scenario()
        self.opts['profile_composition'] = rendered['composition']
        self.opts['local_traffic'] = rendered['vpn_server_remnawave_routing_local_traffic']
        self.model = setup.remnawave_model(items, self.opts)
        outbounds = [{'tag': o['tag']} for o in self.opts['outbounds'] + self.model['hop_outbounds']]
        self.snippets = {
            'outbounds_default_prod_1': defaults['vpn_server_remnawave_snippets_outbounds_default'],
            'rules_default_prod_1': defaults['vpn_server_remnawave_snippets_rules_default'],
            'outbounds_warp_prod_1': rendered['vpn_server_remnawave_snippets_outbounds_warp'],
            'rules_warp_prod_1': rendered['vpn_server_remnawave_snippets_rules_warp'],
            'outbounds_all_prod_1': outbounds,
            'rules_all_prod_1': self.model['rules'],
            'balancers_all_prod_1': [],
        }

    def xray(self, profile):
        return Xray(next(p for p in self.model['profiles'] if p['name'] == profile)['config'],
                    self.snippets)

    def inbound(self, profile):
        return next(p for p in self.model['profiles'] if p['name'] == profile)['inbound_tags'][0]

    def check(self, profile, route, expected):
        xray = self.xray(profile)
        for target, outcome in expected.items():
            with self.subTest(profile=profile, route=route, target=target):
                self.assertEqual(xray.route(self.inbound(profile), route, target), outcome)

    def test_every_profile_resolves_every_rule(self):
        for profile in self.model['profiles']:
            self.xray(profile['name'])

    def test_default_user_crossing_at_the_last_russian_node(self):
        # EU-1 | by RU-2: RU-2 (xHTTP) is where the path leaves Russia.
        host = next(h for h in self.model['hosts'] if h['remark'] == '🇳🇱 EU-1 | by 🇷🇺 RU-2')
        forward = next(r for r in self.model['routes'] if r['id'] == host['vless_route_id'])
        self.assertEqual(forward['local'], 'russia')
        self.check('Reverse-RU-xHTTP', host['vless_route_id'], {
            'yandex.ru': 'out-warp-socks', '77.88.55.88': 'out-warp-socks',
            # geoip on a domain needs resolving, which the forward rule's
            # match before it never asks for: only the list catches it.
            'shop-in-moscow.com': forward['next'][0]['tag'],
            'google.com': forward['next'][0]['tag'], 'gemini.google.com': forward['next'][0]['tag'],
            '10.1.2.3': 'BLOCK',
        })

    def test_default_user_four_hops_crosses_only_at_the_tail(self):
        host = next(h for h in self.model['hosts'] if h['remark'] == '🇳🇱 EU-1 | by 🇷🇺 RU-1')
        entry = next(r for r in self.model['routes'] if r['id'] == host['vless_route_id'])
        # RU-1 hands everything to RU-3, its hidden tail, local traffic too.
        self.check('Reverse-RU', host['vless_route_id'],
                   {'yandex.ru': entry['next'][0]['tag'], 'google.com': entry['next'][0]['tag']})
        crossing = entry['next'][0]['carried']
        self.check('Reverse-RU', crossing, {'yandex.ru': 'out-warp-socks', 'google.com': 'out-hop-005-net-europe-1'})

    def test_default_user_at_a_global_exit(self):
        # Route 0 from the hop before, 2 from a client of a direct host.
        for route in (0, 2):
            self.check('Default-Profile', route, {
                'yandex.ru': 'out-warp-socks', '77.88.55.88': 'out-warp-socks',
                'gemini.google.com': 'out-warp-socks', 'google.com': 'DIRECT', '10.1.2.3': 'BLOCK'})
            self.check('Xenus-team', route, {'yandex.ru': 'out-warp-socks', 'google.com': 'DIRECT'})

    def test_reverse_user_gets_the_whole_internet_direct(self):
        # Route 0 from the hop before (chains), 2 from a direct host's client.
        for profile in ('Reverse-RU', 'Reverse-RU-xHTTP'):
            for route in (0, 2):
                self.check(profile, route, {
                    'yandex.ru': 'DIRECT', 'gosuslugi.ru': 'DIRECT', '77.88.55.88': 'DIRECT',
                    'shop-in-moscow.com': 'DIRECT',
                    'google.com': 'DIRECT', '8.8.8.8': 'DIRECT', 'gemini.google.com': 'DIRECT',
                    'www.gstatic.com': 'DIRECT',   # client ping probes
                    '10.1.2.3': 'BLOCK'})

    def test_the_node_api_inbound_is_never_blocked(self):
        xray = self.xray('Reverse-RU')
        self.assertEqual(xray.route('REMNAWAVE_API_INBOUND', 0, 'google.com'), 'DIRECT')

    def test_chain_routes_through_a_russian_node_are_untouched_by_reverse_rules(self):
        # RU-1 | by EU-1 enters Russia; at RU-1 the route is the forward one.
        host = next(h for h in self.model['hosts'] if h['remark'] == '🇷🇺 RU-1 | by 🇳🇱 EU-1')
        first = next(r for r in self.model['routes'] if r['id'] == host['vless_route_id'])
        self.check('Default-Profile', host['vless_route_id'],
                   {'google.com': first['next'][0]['tag'], 'yandex.ru': first['next'][0]['tag']})


if __name__ == '__main__':
    unittest.main()
