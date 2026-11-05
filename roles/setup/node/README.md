setup/node
==========

Adds a host to the inventory, on the controller. It was
`playbooks/ansible/node/add_host_initial.yaml` (and the `vpn/add_host_*`
playbooks) before; that playbook is now only its launcher.

Servers (`analytics_server`, `vpn_server_remnawave`, `backup_restic_server`,
`matrix_server`) are added by `setup/server`, which also writes their secrets.

What it does
------------

1. Looks at what the inventory already holds: the hostnames (from
   `host_vars/` and the inventory), the addresses in use, the base domains
   (read from every `host_vars/*/0_all/1_domains.yaml`: a literal
   `domains_keys.main` and the `vpn_server_remnawave_node_base_domains` of the
   panels) and the `net-<region>-N` / `chain-<region>-N` indexes per
   deployment region (`domains_node` of the nodes).
2. Asks, through the `ansible-prompting-engine` role, for:
   - the hosting provider, the country and the index: the hostname is
     `<provider>-<country>-<index>` (`ovh-sg-2`), since `country_code` is
     derived from the hostname and `vpn_deployment_region` from
     `country_code`. A country in no region matcher is pointed out; the
     index defaults to the next free one for that country and must not
     produce a hostname that exists;
   - the IPv4 address, checked against the ones already in use;
   - the optional groups (`vpn_caddy`, `analytics_node`,
     `backup_restic_node` by default); `general_vps_prepare` and
     `domain_management` are always joined;
   - the host the new one relates to by default (`host_relations.default`
     of `1_domains.yaml`): chosen from the `analytics_server` and
     `vpn_server_remnawave` hosts (deduplicated), or typed. This is asked
     before domain selection; a `vpn_caddy` host selects one or more main
     and XRay base domains from that panel's catalog;
   - for a host outside `vpn_caddy`, the base domain of its own domain
     (`initial_configure_host_base_domain_name`, `accessto.page`): chosen
     from the base domains already in use, or typed when there is none or
     another one is wanted. A `vpn_caddy` host takes its base domains from
     the panel it relates to, see below;
   - for a `vpn_caddy` host, the exit and entry (chain) location indexes
     (the `4` of `chain-russia-4.123987465.xyz`; the default is the next
     free index of the region, and an existing one joins that round-robin
     domain), the primary protocol of the node and whether its
     certificates use the Cloudflare DNS-01 challenge.
3. Renders `templates/host/0_all/` of `setup/common` and of this role and, for every group joined that has a
   directory of the same name in `templates/host/`, that directory into
   `host_vars/<hostname>/`.
4. Adds `<hostname> ansible_host=<ip>` to every group's section of the
   inventory file(s) the play runs with.

Nothing is written when `host_vars/<hostname>/` already exists.

A host on a local network
-------------------------

`playbooks/ansible/node/add_host_local.yaml` runs the role with
`setup_node_local: true`, for a laptop or a home server:

- the hostname is asked whole (`kw-laptop`), not built from provider, country
  and index; the country is still asked and written to
  `0_all/0_country.yaml` as `country_code`, overriding the one
  `group_vars/all` derives from the hostname;
- its own domain is `<hostname>.<suffix>` (`local` by default, resolved
  through mDNS), with no DNS record: the host joins `general_vps_prepare` and
  `local_caddy`, never `domain_management` or `vpn_caddy` (the Remnawave panel
  publishes every `vpn_caddy` host as a node). `local_devices`,
  `backup_restic_node` and `analytics_node` are offered;
- no provider, account or billing is asked, and `0_all/3_infrastructure.yaml`
  is not written;
- a host it relates to is required: Caddy resolves its analytics server
  through it.

`group_vars/local_caddy` sets `caddy_http_only`: Caddy turns `auto_https`
off and serves one `http://` site, so every container labelled with
`caddy_site_address` answers on port 80 at any address of the host (LAN,
localhost). Prepare the host with `playbooks/profile/bootstrap.yaml`, then
`playbooks/profile/node_local.yaml`.

Unattended:

    ansible-playbook -i inventory/production.ini playbooks/ansible/node/add_host_local.yaml \
      -e prompting_engine_interactive=false \
      -e '{"setup_node_prompt_answers": {"local_hostname": "kw-laptop", "country_code": "ru",
           "ip_address": "192.168.1.50", "groups": ["local_devices"],
           "default_relation_host_choice": "play2go-nl-3"}}'

Domains of a `vpn_caddy` host
-----------------------------

Its `1_domains.yaml` holds `domains_node` (the location indexes and optional
base-domain subsets) and `host_relations`. The panel catalog accepts ordered
lists and legacy strings. `inventory/group_vars/vpn_caddy/domain_generator.yaml`
builds `domains_keys` from them: the primary string `main`, `main_extra` aliases,
and every `remna_node` entry of
`domains_node_remna_node_spec`, on the base domains of the panel its
`host_relations` resolve to (`vpn_server_remnawave_node_base_domains` of that
panel's `host_vars`). `domains_node.remna_node_types` narrows the entries,
`domains_node.remna_node_extra` adds some. `domains` is flattened from
`domains_keys` in `group_vars/all/0_defaults/domains.yaml`.

The unattended answers are `node_main_base_domains` and
`node_xray_base_domains` (default: the panel's first entry); plain hosts can use
`extra_base_domains` for aliases. The relation is asked before these selections.

In `host_vars/<panel>/0_all/1_domains.yaml`, declare the panel's supported domains:

```yaml
vpn_server_remnawave_node_base_domains:
  main: [hosts.example.com, hosts.example.net]
  xray: [vpn.example.com, vpn.example.net]
```

Both keys accept a non-empty list or a legacy string of bare lowercase DNS
names. Lists preserve order and remove duplicates. Select a subset per node:

```yaml
domains_node:
  base_domains:
    main: [hosts.example.net]
    xray: [vpn.example.com, vpn.example.net]
  net_location_index: 4
  chain_location_index: 4
```

An omitted selection key takes only the first entry of that key, so a node
declares nothing unless it wants another domain, or more than one. The generated
`1_domains.yaml` writes only a selection that differs from this. An explicit
selection must be non-empty and registered on the related panel. `main` and
`xray` selections are independent; their list positions are not paired.
The first selected `main` domain is the primary service/control hostname;
remaining own hostnames go into `domains_keys.main_extra`. DNS, Caddy and
certificate consumers include those aliases. `host_relations` still selects
the panel and its credentials, even if several panels share domain bases.

Existing strings need no migration. Adding a catalog entry at the end changes
no node until one declares it; changing the first entry moves every node that
declares nothing, so pin those first. Adding domains to nodes can renumber
generated remarks, outbounds and route
IDs; preview panel playbooks with `--check --diff` and review route-ID limits.
Deploy DNS, Caddy/node configuration and certificates before generating the
panel's config profiles, snippets, nodes and hosts; then run
`remnawave_verify.yaml`. Ensure all chosen DNS zones have provider credentials.

Run it
------

    ansible-playbook -i inventory/production.ini playbooks/ansible/node/add_host_initial.yaml

The play must run against the inventory, with localhost listed in it, so
that `group_vars/all` (the region matchers) applies to the controller.

Unattended, e.g. for a host in Germany:

    ansible-playbook -i inventory/production.ini playbooks/ansible/node/add_host_initial.yaml \
      -e prompting_engine_interactive=false \
      -e '{"setup_node_prompt_answers": {"provider": "hetzner", "country_code": "de", "index": 14,
           "ip_address": "203.0.113.10", "groups": ["vpn_caddy", "analytics_node", "backup_restic_node"],
           "net_location_index": 15, "chain_location_index": 15,
           "default_relation_host_choice": "play2go-nl-3"}}'

Role variables
--------------

| Variable | Default | Description |
| --- | --- | --- |
| `setup_node_local` | `false` | A host on a local network: free hostname, country written as `country_code`, local domain suffix, no DNS, no billing. |
| `setup_node_local_domain_default` | `local` | Suffix of a local host's own domain offered at the prompt. |
| `setup_node_templates_skip` | `3_infrastructure.yaml.j2` (local) or `0_country.yaml.j2` | Files of this role's `templates/host/0_all/` not written. |
| `setup_node_inventory_dir` | directory of the inventory the play runs with, else `inventory/` of the project | Where `host_vars/` lives. |
| `setup_node_inventory_files` | the `.ini` files of `ansible_inventory_sources` | Inventory files that get the host. |
| `setup_node_groups_required` | `general_vps_prepare`, `domain_management` | Groups every host joins. |
| `setup_node_groups_optional` | `vpn_caddy`, `analytics_node`, `backup_restic_node` | Groups offered at the prompt (value: label). |
| `setup_node_groups_optional_default` | all three | The ones chosen when Enter is pressed. |
| `setup_node_templates_always` | `0_all` | Template directories rendered for every host. |
| `setup_node_remna_protocol_types` | `vless_reality_tcp`, `vless_reality_xhttp` | Protocols offered at the prompt. |
| `setup_node_relation_host_groups` | `analytics_server`, `vpn_server_remnawave` | Groups whose hosts are offered as the default relation host. |
| `setup_node_backup_restic_remotes` | keys of `backup_restic_node_remotes_base` | Remotes written to `backup_restic_node/backup_restic_node.yaml`, each with a generated restic key. |
| `setup_node_prompt_answers` | `{}` | Preset answers by prompt id, for unattended runs. |

The prompts are in `vars/prompts/host.yml`; every answer is set as the
fact `initial_configure_host_<id>`, and the role adds
`initial_configure_host_hostname`, `initial_configure_host_base_domain_name`
and `initial_configure_host_default_relation_host` for the templates.

Templates
---------

- `host/0_all/0_country.yaml.j2`: `country_code`, for a local host only.
- `host/0_all/1_domains.yaml.j2`: for a `vpn_caddy` host, `domains_node`
  with location indexes, and `base_domains` when the selection is not the
  panel's first entry; for any other,
  `domains_keys.main`, optional `main_extra` aliases, and an empty
  `remna_node`. Then `host_relations.default`.
- `host/0_all/2_domains.yaml` of `setup/common`: how to add or override DNS
  records and define `host_relations` (resolved by
  `kwtoolset/resolve_host_relations`), as comments.
- `host/vpn_caddy/remna.yaml.j2`: `remna_node_primary_protocol_type`.
- `host/vpn_caddy/caddy.yaml`: `caddy_occupy_HTTPS`, commented out.
- `host/backup_restic_node/backup_restic_node.yaml.j2`: the postgres
  location and one restic key per remote.

Requirements
------------

- ansible-core 2.19 or newer, for the prompting engine.
- The `ansible-prompting-engine` role and the `community.general`
  collection, both in `roles/requirements.yaml`.
