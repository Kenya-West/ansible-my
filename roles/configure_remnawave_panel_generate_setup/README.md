configure_remnawave_panel_generate_setup
========================================

Generates the chain setup of the Remnawave panel on the host it runs against
out of the facts of the nodes relating to that panel, and applies it through
the
[kenyawest.remnawave](https://github.com/kenya-west/remnawave-ansible-collection)
collection.

Three things have to agree for a chain to work: the **Remnawave Host** a
client connects to, the **routing rule** that catches it, and the
**outbound** that rule sends it through. They agree because they are all
derived in one pass from the same ordered list of exits - the role never
stores a route id, it computes one.

Which panel, which nodes
------------------------

The role configures the panel of the host it runs against: a host of
`vpn_server_remnawave`, reached at `https://<domains_keys.remnawave>` with that
host's own `vpn_server_remnawave_api_token` (and
`vpn_server_remnawave_custom_login_route_api_token` behind the Caddy custom
path). There is nothing to choose - run against several panels, each one is
configured with its own nodes.

A node of `vpn_server_remnawave_hosts_node_group` belongs to the panel when its
`host_relations` resolve to it, exactly as the node's own remna playbook
resolves them (`kwtoolset/resolve_host_relations`, group
`vpn_server_remnawave`, component `remna`):

```yaml
# host_vars/cloudrix-ru-11/0_all/1_domains.yaml
host_relations:
  default:
    hosts:
      - host: play2go-nl-3
```

What it generates
-----------------

**Exits** are the distinct domains of type `net-location`
(`vpn_deployment_domain_prefix.net_location.type`) published by the nodes. A
domain is one exit no matter how many Ansible hosts sit behind it, so a
round-robin record in front of two nodes stays a single Host in the panel,
bound to both.

**Chain entries** are the distinct domains of type `chain-location`
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

Tags: what the role owns
------------------------

Every host the role publishes carries every tag of
`vpn_server_remnawave_tags`. Tags are authoritative, so a tag added by hand to
such a host is removed on the next run. The tags marked `primary_filter: true`
are how the role recognises its own hosts:

```yaml
vpn_server_remnawave_tags:
  - value: "MANAGED_BY:ANSIBLE"
    primary_filter: true
  - value: "ENVIRONMENT:{{ inventory_file | basename | splitext | first | upper }}"
    primary_filter: true
```

With several primary tags a host is the role's only when it carries all of
them, so above, a run with `staging.ini` never touches the hosts a run with
`production.ini` published on the same panel, and the other way round.

- The panel is read through `kenyawest.remnawave.remnawave` with only
  `remnawave_gather` set, and its hosts are split into the ones carrying
  **all** primary tags and the rest.
- Only the former are retired when the inventory stops producing them
  (`vpn_server_remnawave_hosts_prune`), and cleaned by
  `remnawave_clean_hosts.yaml`.
- A generated host whose remark belongs to a host *without* the primary tags
  is not published, and is reported. Set
  `vpn_server_remnawave_hosts_adopt_untagged: true` to take such hosts over
  and tag them - once is enough to adopt hosts published before the tags
  existed (for example ones tagged `ANSIBLE_MANAGED`).

The tags are checked before anything is sent: at most 10 distinct tags of up
to 36 characters of `A-Z`, `0-9`, `_` and `:`, at least one of them primary.

Snippets have no tags in Remnawave, so what the role owns inside them is told
apart by content. Both snippets are read back before they are written, and
only the parts the role owns are replaced:

- an **outbound** is the role's when its `tag` starts with
  `vpn_server_remnawave_snippets_outbound_tag_prefix`;
- a **rule** is the role's when its `vlessRoute` is a single number inside
  `vpn_server_remnawave_snippets_vless_route_id_range`.

So hand-written outbounds, the geo-targeted rule families, the balancers and
catch-all ranges such as `"400-600"` all survive a regeneration. The default
tag prefix is `out-chain-auto`, deliberately distinct from a hand-written
`out-chain-*` namespace; point it at `out-chain` only when the role is meant
to own that namespace.

New hosts are disabled
----------------------

A host the panel does not have yet is created disabled - `isDisabled` is part
of the create request, so it never carries traffic before it is reviewed.
What happens afterwards is `vpn_server_remnawave_hosts_publish_state`:

| Value | New host | Existing host |
| --- | --- | --- |
| `present` (default) | created disabled | switch left as the panel has it, so a host enabled by hand stays enabled |
| `disabled` | created disabled | disabled again on every run |
| `enabled` | created enabled | enabled again on every run |

Cleaning
--------

`playbooks/reverse_proxy/remnawave_clean_hosts.yaml` (`tasks_from:
clean_hosts`) lists every host of the panel carrying all the primary tags,
asks for `yes`, and deletes them. Hosts without the primary tags are never
touched.

```sh
ansible-playbook -i inventory/production.ini playbooks/reverse_proxy/remnawave_clean_hosts.yaml
  # -e vpn_server_remnawave_hosts_clean_state=disabled   disable instead of delete
  # -e vpn_server_remnawave_hosts_clean_confirm=true     do not ask
```

`--check` lists what would be cleaned without asking.

Requirements
------------

- The `kenyawest.remnawave` collection, version 1.2.1 or newer - the panel is
  read through the `remnawave_gather` of its role, and hosts are published,
  retired and cleaned in one `kenyawest.remnawave.hosts` task each. Install it
  with `ansible-galaxy collection install -r roles/requirements.yaml`.
- Network access from the controller to the panel: every Remnawave task is
  delegated to `localhost`, so nothing goes over SSH to the panel host, which
  only lends its variables.
- The `kwtoolset/resolve_host_relations` role of this repository.
- Nodes in `vpn_server_remnawave_hosts_node_group` with `host_relations`
  resolving to the panel and `domains_keys.remna_node` entries typed from
  `vpn_deployment_domain_prefix`.
- In the panel host's `host_vars`: `domains_keys.remnawave`,
  `vpn_server_remnawave_api_token`, and for the snippets `service_user_id` and
  `vpn_server_remnawave_xray_reality_password` (generated by `setup/server`).
- A config profile and an inbound that already exist in the panel.
- The nodes themselves already registered in the panel. A host is bound to
  the node named after its inventory hostname; set `remna_node_panel_name`
  in a node's host_vars when the panel calls it something else.
  `vpn_server_remnawave_hosts_chain_bind_nodes: none` leaves the *chain*
  hosts unbound, so they are served from every node; a direct host is always
  bound to the nodes behind its own domain.

Role Variables
--------------

Set in `inventory/group_vars/vpn_server_remnawave/`, or per panel in its
`host_vars`; the role's `defaults/main.yml` holds the same names as fallbacks.

### Panel

| Variable | Default | Meaning |
| --- | --- | --- |
| `vpn_server_remnawave_access_mode` | `api_token` | `caddy_custom_path` also sends the Caddy `X-Api-Key` |
| `vpn_server_remnawave_panel_url` | `https://{{ domains_keys.remnawave }}` | URL of the panel of this host |
| `vpn_server_remnawave_panel_validate_certs` | `true` | Whether TLS certificates are validated |
| `vpn_server_remnawave_panel_timeout` | `30` | Per-request timeout in seconds |
| `vpn_server_remnawave_tags` | `[{value: MANAGED_BY:ANSIBLE, primary_filter: true}]` | Tags put on what the role creates; the primary ones mark what it owns |
| `vpn_server_remnawave_generate_stages` | `[snippets, hosts]` | Which halves this run generates |

### Hosts

| Variable | Default | Meaning |
| --- | --- | --- |
| `vpn_server_remnawave_hosts_node_group` | `vpn_caddy` | Group the nodes are read from |
| `vpn_server_remnawave_hosts_node_relation_group` | `vpn_server_remnawave` | Relation group a node names its panel by |
| `vpn_server_remnawave_hosts_node_relation_component` | `remna` | Relation component a node names its panel by |
| `vpn_server_remnawave_hosts_node_manage_key` | `remna_node` | Key of `domains_keys` holding the node's domains |
| `..._domain_types_direct_filter` | `[net-location]` | Domain types a direct host is published on |
| `..._domain_types_specific_filter` | `[chain-location]` | Domain types a chain host is entered through |
| `vpn_server_remnawave_hosts_publish_state` | `present` | `present`, `disabled` or `enabled`, see [New hosts are disabled](#new-hosts-are-disabled) |
| `vpn_server_remnawave_hosts_adopt_untagged` | `false` | Whether a generated host may take over a host of its remark without the primary tags |
| `vpn_server_remnawave_hosts_prune` | `disable` | What to do with primary-tagged hosts the inventory no longer produces: `ignore`, `disable`, `delete` |
| `vpn_server_remnawave_hosts_config_profile` | `''` | **Required.** Config profile the hosts attach to |
| `vpn_server_remnawave_hosts_inbound` | `''` | Inbound tag, unless given per protocol below |
| `vpn_server_remnawave_hosts_inbound_by_protocol` | `{}` | Inbound tag per `remna_protocol_types.<key>.full` value |
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
beside it (a host without the primary tags also needs
`vpn_server_remnawave_hosts_adopt_untagged`):

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

### Cleaning

| Variable | Default | Meaning |
| --- | --- | --- |
| `vpn_server_remnawave_hosts_clean_state` | `absent` | `absent` deletes the primary-tagged hosts, `disabled` switches them off |
| `vpn_server_remnawave_hosts_clean_confirm` | `false` | Skip the confirmation prompt |

### Snippets

| Variable | Default | Meaning |
| --- | --- | --- |
| `vpn_server_remnawave_snippets_key_outbounds_all` | `outbounds_all_prod_1` | Panel snippet the outbounds are written into |
| `vpn_server_remnawave_snippets_key_rules_all` | `rules_all_prod_1` | Panel snippet the routing rules are written into |
| `vpn_server_remnawave_snippets_template_revision` | `'001'` | Suffix of the template variable names |
| `vpn_server_remnawave_snippets_default_protocol_type` | `vless-reality-tcp` | Used by a node that declares no `remna_node_primary_protocol_type` |
| `vpn_server_remnawave_snippets_outbound_tag_prefix` | `out-chain-auto` | Prefix marking the outbounds the role owns |
| `vpn_server_remnawave_snippets_outbound_tag_index_width` | `3` | Zero padding of the per-region index |
| `vpn_server_remnawave_snippets_vless_route_id_range` | `[400, 499]` | Route ids the role owns in the rules snippet |
| `vpn_server_remnawave_snippets_region_codes` | `vpn_deployments_region_codes_global` + `_censorship` | `europe: eu`, ...; an unlisted region uses its first two letters |
| `vpn_server_remnawave_snippets_sync` | `on_change` | Whether to push the snippets into the profiles embedding them |

Outbound templates live beside the inventory as
`group_vars/vpn_server_remnawave/snippet_<protocol key>_<revision>.yaml` and
define one variable of the same name, for example `vless_reality_tcp_001`.
The protocol key is the key of `remna_protocol_types` (read from the nodes)
whose `full` value a node declares in `remna_node_primary_protocol_type`. A
template is rendered once per chained exit with `node_address` set to that
exit's domain, and `service_user_id` and
`vpn_server_remnawave_xray_reality_password` of the panel host in scope; its
`tag` is replaced with the generated one.

Dependencies
------------

`kenyawest.remnawave` >= 1.2.1, declared in `roles/requirements.yaml`, and
`kwtoolset/resolve_host_relations`.

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
