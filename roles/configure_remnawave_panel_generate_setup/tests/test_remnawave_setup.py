"""Regression tests: python3 -m unittest discover -s roles/configure_remnawave_panel_generate_setup/tests."""

import copy
import importlib.util
from pathlib import Path
import unittest

from jinja2.nativetypes import NativeEnvironment
import yaml
from ansible.errors import AnsibleFilterError

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


class CompositionTests(unittest.TestCase):
    def setUp(self):
        inventory = yaml.safe_load((ROLE.parents[1] /
                                   'inventory/group_vars/vpn_server_remnawave/config_profiles.yaml').read_text())
        # Render the actual inventory composition using mock snippet contents.
        env = NativeEnvironment()
        env.globals.update({
            'vpn_server_remnawave_config_profiles_log': {'loglevel': 'warning'},
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

        self.options = options()
        self.options['profile_composition'] = render(inventory['vpn_server_remnawave_config_profiles_composition'])
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
                             ['defaults', 'warp', 'chains'] if profile['geo'] == 'global'
                             else ['defaults', 'chains'])

    def test_outbounds_balancers_and_log_are_preserved(self):
        for profile in self.model()['profiles']:
            expected = ['outbounds_default_prod_1']
            if profile['geo'] == 'global':
                expected.append('outbounds_warp_prod_1')
            expected.append('outbounds_all_prod_1')
            self.assertEqual(setup._snippet_refs(profile['config']['outbounds']), expected)
            self.assertEqual(profile['config']['routing']['balancers'],
                             [{'snippet': 'balancers_all_prod_1'}])
            self.assertEqual(profile['config']['log'], {'loglevel': 'warning'})

    def test_fragment_order_controls_rule_precedence(self):
        fragments = self.options['profile_composition']
        fragments[1], fragments[2] = fragments[2], fragments[1]
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
        self.options['profile_composition'][1]['inbounds'] = ['VLESS_TCP_REALITY']
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


if __name__ == '__main__':
    unittest.main()
