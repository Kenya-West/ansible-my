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

For every *chained* exit it also generates one routing rule, sending the
exit's route id to the exit's outbound. The outbounds themselves, the
balancers and the default snippets are built in the inventory - see
[Snippets](#snippets).

**Nodes** are one per Ansible host relating to the panel that publishes
domains under `domains_keys.<vpn_server_remnawave_hosts_node_manage_key>`
(a host publishing none, such as the panel itself sitting in the node group
for its Caddy, is skipped and reported, and takes no part in anything the
role generates), named
`remna_node_name_in_panel` (the inventory hostname) - the same name generated
hosts bind to - and reached at `remna_node_panel_address`:`remna_node_control_port`,
which follows the node's compose (`remna_node_control_port`, published onto
`remna_node_app_port`). They carry the tags, adopt, collide, prune and
publish-state rules the hosts do. The collection has no bulk module for nodes,
so each is its own module run. Run the nodes stage before the hosts one.

**Config profiles** are the items of `vpn_server_remnawave_config_profiles`
(`group_vars/vpn_server_remnawave/config_profiles.yaml`), each written to the
panel as it is. See [Config profiles](#config-profiles).

Config profiles
---------------

Each profile is `{name, config}`, written in YAML. The config repeats nothing
the inventory already holds:

| Part | Taken from |
| --- | --- |
| `serverNames` of the REALITY inbounds | `vpn_server_remnawave_server_names` |
| `privateKey` | `vpn_server_remnawave_inbounds_private_keys` of the panel's host_vars: the entry of the inbound's tag in `specific`, else `common` |
| `outbounds`, `routing.rules`, `routing.balancers` | `{snippet: ...}` references named by `vpn_server_remnawave_snippets_key_*` |
| `log`, `sniffing`, REALITY `target` | `vpn_server_remnawave_config_profiles_log`, `_sniffing`, `_reality_target` |

A profile is found in the panel by the tag of its **first inbound** (or the
tag in an `inbound` key), and failing that by its **name**. The panel keeps
inbound tags unique across profiles, so:

- a profile holding the inbound is updated, and renamed when its name differs;
- otherwise a profile of that name is updated, its config replaced;
- otherwise the profile is created.

The config is authoritative: what the panel's profile had is replaced, except
the inbounds' `settings.clients`, which the panel manages. Profiles carry the
tags and follow the adopt rules of hosts and nodes - a profile without the
primary tags is left out and reported unless
`vpn_server_remnawave_config_profiles_adopt_untagged` is true.

The panel reserves the name **`Default-Profile`**: a profile of that name can
be updated and adopted, but not created. That is why pruning and cleaning
never delete a profile named in `vpn_server_remnawave_config_profiles_protected`,
nor one a node still activates.

Run the config profiles stage after the snippets, which the profiles embed,
and before the nodes and hosts, which attach to the profiles' inbounds.

Route ids
---------

A chained exit's route id is `vpn_server_remnawave_hosts_vless_route_id_base`
plus its position among the chained exits in
`vpn_server_remnawave_snippets_outbounds_plan` - the order of their outbound
tags: region, protocol, domain index. Adding or removing a chained exit therefore
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

Snippets have no tags in Remnawave, so what the role owns inside the outbounds
and rules snippets is told apart by content. Both are read back before they
are written, and only the parts the role owns are replaced:

- an **outbound** is the role's when its `tag` starts with
  `vpn_server_remnawave_snippets_outbound_tag_prefix` and a hyphen
  (`out-chain-`);
- a **rule** is the role's when its `vlessRoute` is a single number inside
  `vpn_server_remnawave_snippets_vless_route_id_range`.

So hand-written outbounds, the geo-targeted rule families and catch-all ranges
such as `"400-600"` all survive a regeneration. The snippets of
`vpn_server_remnawave_snippets_whole` - the balancers and the defaults - are
different: they are written exactly as the inventory builds them.

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

`playbooks/anti_censorship/server/remnawave_clean_hosts.yaml` (`tasks_from:
clean_hosts`) lists every host of the panel carrying all the primary tags,
asks for `yes`, and deletes them. Hosts without the primary tags are never
touched.

```sh
ansible-playbook -i inventory/production.ini playbooks/anti_censorship/server/remnawave_clean_hosts.yaml
  # -e vpn_server_remnawave_hosts_clean_state=disabled   disable instead of delete
  # -e vpn_server_remnawave_hosts_clean_confirm=true     do not ask
```

`remnawave_clean_nodes.yaml` (`tasks_from: clean_nodes`) does the same for
nodes, with `vpn_server_remnawave_nodes_clean_state` and
`vpn_server_remnawave_nodes_clean_confirm`.

`remnawave_clean_config_profiles.yaml` (`tasks_from: clean_config_profiles`)
deletes the primary-tagged config profiles, with
`vpn_server_remnawave_config_profiles_clean_confirm`. It keeps, and lists,
the ones a node still activates and the protected ones.

`--check` lists what would be cleaned without asking.

Verifying
---------

The `verify` stage (`remnawave_verify.yaml`, and the end of every
`remnawave_generate_all.yaml` run) reads the panel back and follows what it
holds the way a client is routed, writing nothing:

- every managed host's route id leads, through the rule of that id in the
  rules snippet and the outbound that rule names, to the exit domain the host
  is named after (`🇰🇿 AS-1 | by 🇷🇺 RU-1` must reach `net-asia-2`); direct
  hosts carry `vpn_server_remnawave_hosts_vless_route_id_direct`;
- the nodes a host binds to exist, activate its config profile and its
  inbound;
- the config profile embeds the outbounds and rules snippets;
- the balancers select outbounds that exist.

**Problems** are what would misroute or drop traffic - a route id without a
rule, a rule reaching the wrong exit, a node not activating a host's inbound,
a host the inventory no longer produces but still enabled - and fail the play
unless `vpn_server_remnawave_verify_fail` is false. **Notes** are harmless:
a stale host already disabled (with where its old route id now leads, since
route ids are renumbered), a rule no host uses, a host left out for a
hand-made one of the same remark.

In `--check` the panel has not been written, so the report shows what the
run would fix and nothing fails.

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
- The nodes registered in the panel - by `remnawave_generate_nodes.yaml`, or
  by hand. A host is bound to the node named after its inventory hostname;
  set `remna_node_name_in_panel` in a node's host_vars when the panel calls it
  something else.
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
| `vpn_server_remnawave_generate_stages` | `[snippets, config_profiles, nodes, hosts, verify]` | Which parts this run generates, in dependency order; `verify` writes nothing |
| `vpn_server_remnawave_verify_fail` | `true` | Whether a problem found by `verify` fails the play (never in `--check`) |

### Config profiles

In `group_vars/vpn_server_remnawave/config_profiles.yaml`:

| Variable | Default | Meaning |
| --- | --- | --- |
| `vpn_server_remnawave_config_profiles` | the two below | Profiles as `{name, config, inbound (optional)}` |
| `vpn_server_remnawave_config_profiles_adopt_untagged` | `false` | Whether a generated profile may take over a profile holding its inbound or name without the primary tags |
| `vpn_server_remnawave_config_profiles_prune` | `ignore` | What to do with primary-tagged profiles the inventory no longer produces: `ignore`, `delete` |
| `vpn_server_remnawave_config_profiles_protected` | `[Default-Profile]` | Names never deleted by pruning or cleaning |
| `vpn_server_remnawave_config_profiles_clean_confirm` | `false` | Skip the confirmation prompt |
| `vpn_server_remnawave_config_profiles_reality_target` | `caddy:443` | REALITY `target` of the inbounds |

| Profile | Identifying inbound | Transport |
| --- | --- | --- |
| `Default-Profile` | `VLESS_TCP_REALITY` | raw |
| `Default-xHTTP` | `VLESS_REALITY_XHTTP` | xhttp |

### Nodes

Panel side, in `group_vars/vpn_server_remnawave/nodes.yaml`:

| Variable | Default | Meaning |
| --- | --- | --- |
| `vpn_server_remnawave_nodes_publish_state` | `present` | `present`, `disabled` or `enabled`, as for hosts |
| `vpn_server_remnawave_nodes_adopt_untagged` | `false` | Whether a generated node may take over a node of its name without the primary tags |
| `vpn_server_remnawave_nodes_prune` | `disable` | What to do with primary-tagged nodes the inventory no longer produces: `ignore`, `disable`, `delete` |
| `vpn_server_remnawave_nodes_config_profile` | the hosts' profile | Config profile the nodes activate |
| `vpn_server_remnawave_nodes_inbounds` | every inbound the hosts use | Inbounds activated on a node naming none of its own |
| `vpn_server_remnawave_nodes_clean_state` | `absent` | `absent` deletes the primary-tagged nodes, `disabled` switches them off |
| `vpn_server_remnawave_nodes_clean_confirm` | `false` | Skip the confirmation prompt |

Node side, in `group_vars/vpn_caddy/remna.yaml` or a node's host_vars:

| Variable | Default | Meaning |
| --- | --- | --- |
| `remna_node_name_in_panel` | `{{ inventory_hostname }}` | Name on the panel; hosts bind to it |
| `remna_node_panel_address` | `{{ ansible_host }}` | Address the panel reaches the node at |
| `remna_node_control_port` |  | Port the panel reaches the node at |
| `remna_node_panel_country_code` | `{{ country_code_upper }}` | Country shown in the panel |
| `remna_node_panel_inbounds` | `[]` | This node's inbounds; empty uses the panel's list |

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
| `vpn_server_remnawave_hosts_labels` | `{}` | Display names keyed by domain label, overriding the generated ones |
| `vpn_server_remnawave_hosts_remark_chain_separator` | `' \| by '` | Joins the two names of a chain host's remark |
| `vpn_server_remnawave_hosts_chain_bind_nodes` | `exit` | Which nodes a chain host binds to: `exit`, `entry`, `both`, `none` |

Remarks identify hosts in the panel, so they are how the role finds its own
work again. A host is named `<flag> <REGION CODE>-<n>` - the flag of the
country its nodes are in, the short code of its region and its position
among the domains of that region:

| domain | country | remark |
| --- | --- | --- |
| `net-asia-2.123987465.xyz` | `KZ` | `🇰🇿 AS-1` |
| `net-asia-4.123987465.xyz` | `KZ` | `🇰🇿 AS-2` |
| `chain-russia-1.123987465.xyz` | `RU` | `🇷🇺 RU-1` |
| the first through the last | | `🇰🇿 AS-1 \| by 🇷🇺 RU-1` |

The region codes are `vpn_deployments_region_codes` and the flags are built
from `vpn_deployments_regional_indicator_symbols`, both of
`group_vars/all/0_defaults/regions.yaml`, so a region renamed there is
renamed in the panel too.

The numbering is per region and per collection, counted from one in the order
of the domains' own indexes: it closes the gaps DNS leaves, so `net-asia-2`
and `net-asia-4` are `AS-1` and `AS-2`. Adding a domain in the middle of a
region therefore renumbers the ones after it, and the panel follows on the
next run - point `vpn_server_remnawave_hosts_labels` at a fixed remark for
any host that must keep its name.

A domain listed in `vpn_server_remnawave_hosts_labels` uses that name instead.
Point it at the remark an existing host already has to make the role **adopt**
that host instead of creating a second one beside it (a host without the
primary tags also needs `vpn_server_remnawave_hosts_adopt_untagged`):

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
The snippet contents are built in
`inventory/group_vars/vpn_server_remnawave/snippets.yaml`, out of the nodes
whose `domains_node_panel` is the panel:

| Snippet (`_key_*` variable) | Default name | Content |
| --- | --- | --- |
| `outbounds_all` | `outbounds_all_prod_1` | One outbound per exit domain, merged into the panel's |
| `rules_all` | `rules_all_prod_1` | One rule per chained exit, merged into the panel's |
| `balancers_all` | `balancers_all_prod_1` | One balancer per censorship geo with `all` outbounds |
| `outbounds_default` | `outbounds_default_prod_1` | `DIRECT` (freedom) and `BLOCK` (blackhole) |
| `rules_default` | `rules_default_prod_1` | `geoip:private` and `geosite:private` to `BLOCK` |

Exits and their outbound tags:

| Domain type | Example domain | Outbound tag |
| --- | --- | --- |
| `net-location` | `net-europe-3.<xray base>` | `out-chain-eu-tcp-001`, numbered per region and protocol in domain index order |
| `net-protocol` | `net-global-reality-xhttp.<xray base>` | `out-chain-global-xhttp-all` (`out-chain-ru-...` for russia) |

and the balancers select the `all` outbounds of their geo:
`bal-global-all-001: [out-chain-global-tcp-all, out-chain-global-xhttp-all]`.
A domain several nodes publish is one outbound.

| Variable | Default | Meaning |
| --- | --- | --- |
| `vpn_server_remnawave_snippets_key_*` | see above | Panel snippet names |
| `vpn_server_remnawave_snippets_whole` | balancers, defaults | Snippets written as they are, as `{name, snippet}` |
| `vpn_server_remnawave_snippets_outbounds_plan` | built | Every exit's outbound, as `{kind, address, protocol, template, tag, ...}` |
| `vpn_server_remnawave_snippets_template_revision` | `'001'` | Suffix of the template variable names |
| `vpn_server_remnawave_snippets_default_protocol_type` | `vless-reality-tcp` | Used by a node that declares no `remna_node_primary_protocol_type` |
| `vpn_server_remnawave_snippets_outbound_tag_prefix` | `out-chain` | Prefix of the outbound tags, and of the outbounds the role owns |
| `vpn_server_remnawave_snippets_outbound_tag_index_width` | `3` | Zero padding of the per-region index |
| `vpn_server_remnawave_snippets_outbound_tag_all_suffix` | `all` | Last part of the tag of an `all` outbound |
| `vpn_server_remnawave_snippets_balancer_tag_prefix` | `bal` | First part of a balancer tag |
| `vpn_server_remnawave_snippets_balancer_tag_suffix` | `all-001` | Last part of a balancer tag |
| `vpn_server_remnawave_snippets_vless_route_id_range` | `[400, 499]` | Route ids the role owns in the rules snippet |
| `vpn_server_remnawave_snippets_sync` | `on_change` | Whether to push the snippets into the profiles embedding them |

Outbound templates live beside the inventory as
`group_vars/vpn_server_remnawave/snippet_<protocol key>_<revision>.yaml` and
define one variable of the same name, for example `vless_reality_tcp_001`.
The protocol key is the key of `remna_protocol_types` whose `full` value a
node declares in `remna_node_primary_protocol_type`. A template is rendered
once per exit with `node_address` set to that exit's domain, and
`service_user_id` and `vpn_server_remnawave_xray_reality_password` of the
panel host in scope; its `tag` is replaced with the planned one.

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

`playbooks/anti_censorship/server/remnawave_generate_snippets.yaml`,
`remnawave_generate_config_profiles.yaml`, `remnawave_generate_nodes.yaml` and
`remnawave_generate_hosts.yaml` are exactly this, one stage each. Run them in
that order, so the snippets a profile embeds, the outbounds a host's route id
points at and the nodes it binds to already exist. All
support `--check`, and end with a list of what was (or would be) added,
modified, left out and retired.

`remnawave_generate_all.yaml` runs the four stages in that order in one play,
so the model is built once for all of them, and ends with [verify](#verifying):

```sh
ansible-playbook -i inventory/production.ini playbooks/anti_censorship/server/remnawave_generate_all.yaml --check --diff
ansible-playbook -i inventory/production.ini playbooks/anti_censorship/server/remnawave_generate_all.yaml
ansible-playbook -i inventory/production.ini playbooks/anti_censorship/server/remnawave_verify.yaml
```

A run against a panel other than the inventory's - a throwaway one - is a
matter of extra vars: `vpn_server_remnawave_panel_url`,
`vpn_server_remnawave_api_token`, `vpn_server_remnawave_access_mode: api_token`,
the profile by name in `vpn_server_remnawave_hosts_config_profile`, and
`vpn_server_remnawave_config_profiles_adopt_untagged: true` to take over its
hand-made `Default-Profile`; override the private keys, the REALITY password
and `service_user_id` too, so no production secret reaches it.

License
-------

MIT

Author Information
------------------

Kenya-West
