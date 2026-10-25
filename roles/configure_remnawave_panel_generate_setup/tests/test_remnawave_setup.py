"""Regression tests: python3 -m unittest discover -s roles/configure_remnawave_panel_generate_setup/tests."""

import copy
import importlib.util
from pathlib import Path
import unittest

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
        'profile_common': {
            'outbounds': [{'snippet': 'outbounds'}],
            'routing': {'rules': [{'snippet': 'rules'}]},
        },
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


if __name__ == '__main__':
    unittest.main()
