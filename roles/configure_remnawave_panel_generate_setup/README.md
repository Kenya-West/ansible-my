configure_remnawave_panel_generate_setup
========================================

Generates a Remnawave panel's chain setup out of the node facts already in
this inventory, and applies it through the
[kenyawest.remnawave](https://github.com/kenya-west/remnawave-ansible-collection)
collection.

Three things have to agree for a chain to work: the **Remnawave Host** a
client connects to, the **routing rule** that catches it, and the
**outbound** that rule sends it through. They agree because they are all
derived in one pass from the same ordered list of exits - the role never
stores a route id, it computes one.

What it generates
-----------------

**Exits** are the distinct domains of type `location_net` published by the
nodes. A domain is one exit no matter how many Ansible hosts sit behind it,
so a round-robin record in front of two nodes stays a single Host in the
panel, bound to both.

**Chain entries** are the distinct domains of type `location_chain`
published by nodes whose `country_code_upper` is listed in
`vpn_server_remnawave_hosts_chain.entry_country_codes`.

For every exit the role generates:

- one **direct host** on the exit's own domain, and
- one **chain host** per usable entry, addressed by the *entry's* domain and
  carrying the exit's route id, so `AS-1 | by RU-2` reaches the same exit the
  long way round.

An entry is not usable for an exit in its own country - there is no
`RU-1 | by RU-2` - and pairs can be ruled out one by one through
`vpn_server_remnawave_hosts_chain.exclude`. An exit with no usable entry gets
its direct host and nothing else: no route id, no outbound, no rule.

For every *chained* exit it also generates one outbound, rendered from the
snippet template matching that exit's protocol, and one routing rule
pointing at it.

Route ids
---------

A chained exit's route id is `vpn_server_remnawave_hosts_vless_route_id_base`
plus its position in the ordered list of chained exits - ordered by region,
then protocol, then domain. Adding or removing a chained exit therefore
renumbers the ones after it. The rules snippet is regenerated in the same
run, so panel and rules stay in step; anything outside this repo that
hardcodes a route id will not.

Direct hosts all carry
`vpn_server_remnawave_hosts_vless_route_id_direct` instead.

What it will not touch
----------------------

Both snippets are read back before they are written, and only the parts the
role owns are replaced:

- an **outbound** is the role's when its `tag` starts with
  `vpn_server_remnawave_snippets_outbound_tag_prefix`;
- a **rule** is the role's when its `vlessRoute` is a single number inside
  `vpn_server_remnawave_snippets_vless_route_id_range`.

So hand-written outbounds, the geo-targeted rule families, the balancers and
catch-all ranges such as `"400-600"` all survive a regeneration. The default
tag prefix is `out-chain-auto`, deliberately distinct from a hand-written
`out-chain-*` namespace; point it at `out-chain` only when the role is meant
to own that namespace.

**Hosts** are found by their remark, and the role only ever retires hosts
carrying `vpn_server_remnawave_hosts_tag`. A host you created by hand is
never disabled or deleted by this role.

Requirements
------------

- The `kenyawest.remnawave` collection, version 1.1.0 or newer - earlier
  versions cannot set `vless_route_id`. Install it with
  `ansible-galaxy collection install -r roles/requirements.yaml`.
- Nodes in `vpn_server_remnawave_hosts_node_group` with
  `domains_keys.remna_node` entries typed from `remna_domain_types`.
- A config profile and an inbound that already exist in the panel.
- The nodes themselves already registered in the panel. A host is bound to
  the node named after its inventory hostname; set `remna_node_panel_name`
  in a node's host_vars when the panel calls it something else.
  `vpn_server_remnawave_hosts_chain_bind_nodes: none` leaves the *chain*
  hosts unbound, so they are served from every node; a direct host is always
  bound to the nodes behind its own domain.

Role Variables
--------------

Set in `inventory/group_vars/vpn_server_remnawave/`; the role's
`defaults/main.yml` holds the same names as fallbacks.

### Panel

| Variable | Default | Meaning |
| --- | --- | --- |
| `vpn_server_remnawave_panel_group` | `vpn_server_remnawave` | Group the panel is taken from |
| `vpn_server_remnawave_choose_panel_strategy` | `autoselect_if_single` | `autoselect_if_single` picks the only panel there is; `manual_set` always uses the recorded one |
| `vpn_server_remnawave_selected_panel_hostname` | unset | The panel to use. Written here automatically after a prompt |
| `vpn_server_remnawave_selected_panel_record` | `true` | Whether an answer at the prompt is written back to the inventory |
| `vpn_server_remnawave_access_mode` | `api_token` | `caddy_custom_path` also sends the Caddy `X-Api-Key` |
| `vpn_server_remnawave_generate_stages` | `[snippets, hosts]` | Which halves this run generates |

When the panel cannot be derived the role asks, accepts a number or a
hostname, and records the answer in
`vpn_server_remnawave_selected_panel_record_path`, so it asks once.

### Hosts

| Variable | Default | Meaning |
| --- | --- | --- |
| `vpn_server_remnawave_hosts_node_group` | `vpn_caddy` | Group the nodes are read from |
| `vpn_server_remnawave_hosts_node_manage_key` | `remna_node` | Key of `domains_keys` holding the node's domains |
| `..._domain_types_direct_filter` | `[location_net]` | Domain types a direct host is published on |
| `..._domain_types_specific_filter` | `[location_chain]` | Domain types a chain host is entered through |
| `vpn_server_remnawave_hosts_publish_state` | `disabled` | `disabled`, `enabled`, or `present` (create switched off, then leave the panel's own switch alone) |
| `vpn_server_remnawave_hosts_tag` | `ANSIBLE_MANAGED` | Tag marking the hosts the role may retire. The panel only accepts `A-Z`, `0-9`, `_` and `:` |
| `vpn_server_remnawave_hosts_prune` | `disable` | What to do with tagged hosts the inventory no longer produces: `ignore`, `disable`, `delete` |
| `vpn_server_remnawave_hosts_config_profile` | `''` | **Required.** Config profile the hosts attach to |
| `vpn_server_remnawave_hosts_inbound` | `''` | Inbound tag, unless given per protocol below |
| `vpn_server_remnawave_hosts_inbound_by_protocol` | `{}` | Inbound tag per `remna_protocol_types` value |
| `vpn_server_remnawave_hosts_port` | `443` | Port advertised to clients |
| `vpn_server_remnawave_hosts_fingerprint` | `chrome` | uTLS fingerprint |
| `vpn_server_remnawave_hosts_labels` | `{}` | Display names keyed by domain label, used to build remarks |
| `vpn_server_remnawave_hosts_remark_chain_separator` | `' \| by '` | Joins the two labels of a chain host's remark |
| `vpn_server_remnawave_hosts_chain_bind_nodes` | `exit` | Which nodes a chain host binds to: `exit`, `entry`, `both`, `none` |

Remarks identify hosts in the panel, so they are how the role finds its own
work again. By default a host is named after its domain label
(`net-europe-1`, `net-europe-1 | by chain-russia-1`). Point
`vpn_server_remnawave_hosts_labels` at the remark an existing host already
has to make the role **adopt** that host instead of creating a second one
beside it:

```yaml
vpn_server_remnawave_hosts_labels:
  net-europe-1: "🇩🇪 EU-1"
  chain-russia-1: "RU-1"
```

### Chains and route ids

```yaml
vpn_server_remnawave_hosts_chain:
  entry_country_codes: [RU]   # nodes that may act as chain entries
  skip_same_country: true     # no RU-1 by RU-2
  exclude:                    # pairs to rule out on top of that
    - exit: net-europe-15.123987465.xyz
      entries: '*'            # or a list of entry domains
```

| Variable | Default |
| --- | --- |
| `vpn_server_remnawave_hosts_vless_route_id_base` | `400` |
| `vpn_server_remnawave_hosts_vless_route_id_direct` | `2` |

### Snippets

| Variable | Default | Meaning |
| --- | --- | --- |
| `vpn_server_remnawave_snippets_key_outbounds_all` | `outbounds_all_prod_1` | Panel snippet the outbounds are written into |
| `vpn_server_remnawave_snippets_key_rules_all` | `rules_all_prod_1` | Panel snippet the routing rules are written into |
| `vpn_server_remnawave_snippets_template_revision` | `'001'` | Suffix of the template variable names |
| `vpn_server_remnawave_snippets_default_protocol_type` | `remna_protocol_types.vless_reality_tcp` | Used by a node that declares no `remna_node_primary_protocol_type` |
| `vpn_server_remnawave_snippets_outbound_tag_prefix` | `out-chain-auto` | Prefix marking the outbounds the role owns |
| `vpn_server_remnawave_snippets_outbound_tag_index_width` | `3` | Zero padding of the per-region index |
| `vpn_server_remnawave_snippets_vless_route_id_range` | `[400, 499]` | Route ids the role owns in the rules snippet |
| `vpn_server_remnawave_snippets_region_codes` | `{}` | `europe: eu`, ...; an unlisted region uses its first two letters |
| `vpn_server_remnawave_snippets_sync` | `on_change` | Whether to push the snippets into the profiles embedding them |

Outbound templates live beside the inventory as
`group_vars/vpn_server_remnawave/snippet_<protocol key>_<revision>.yaml` and
define one variable of the same name, for example `vless_reality_tcp_001`.
The protocol key is the key of `remna_protocol_types` whose value a node
declares in `remna_node_primary_protocol_type`. A template is rendered once
per chained exit with `node_address` set to that exit's domain, and
`service_user_id` and `vpn_server_remnawave_xray_reality_password` in scope;
its `tag` is replaced with the generated one.

Dependencies
------------

`kenyawest.remnawave` >= 1.1.0, declared in `roles/requirements.yaml`.

Example Playbook
----------------

```yaml
- name: Generate Remnawave snippets (outbounds and rules)
  hosts: vpn_server_remnawave
  become: false
  gather_facts: false
  vars:
    vpn_server_remnawave_generate_stages: [snippets]
  roles:
    - configure_remnawave_panel_generate_setup
```

`playbooks/reverse_proxy/remnawave_generate_snippets.yaml` and
`remnawave_generate_hosts.yaml` are exactly this, one stage each. Run the
snippets one first so the outbounds a host's route id points at already
exist. Both support `--check --diff`.

License
-------

MIT

Author Information
------------------

Kenya-West
