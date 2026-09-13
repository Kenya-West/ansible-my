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
   of the existing hosts (read from every `host_vars/*/0_all/1_domains.yaml`,
   `domains_keys.main` and `domains_keys.remna_node[].domain`) and the
   `net-<region>-N` / `chain-<region>-N` indexes per deployment region.
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
     `domain_management` are always joined, and a russian host also joins
     `vps_russia` (and `vpn_caddy_russia_chain` when it is a `vpn_caddy`
     host), see `setup_node_groups_by_region`;
   - the base domain of the host's own domain
     (`initial_configure_host_base_domain_name`, `accessto.page`) and, for
     a `vpn_caddy` host, the base domain of the shared Xray domains
     (`initial_configure_host_xray_base_domain_name`, `123987465.xyz`):
     chosen from the base domains already in use, or typed when there is
     none or another one is wanted;
   - for a `vpn_caddy` host, the exit and entry (chain) location indexes
     (the `4` of `chain-russia-4.123987465.xyz`; the default is the next
     free index of the region, and an existing one joins that round-robin
     domain), the primary protocol of the node and whether its
     certificates use the Cloudflare DNS-01 challenge;
   - the host the new one relates to by default (`host_relations.default`
     of `1_domains.yaml`): chosen from the hosts of the `analytics_server`
     and `vpn_server_remnawave` groups of the inventory the play runs
     against (deduplicated), or typed when there is none or another one is
     wanted.
3. Renders `templates/host/0_all/` of `setup/common` and of this role and, for every group joined that has a
   directory of the same name in `templates/host/`, that directory into
   `host_vars/<hostname>/`.
4. Adds `<hostname> ansible_host=<ip>` to every group's section of the
   inventory file(s) the play runs with.

Nothing is written when `host_vars/<hostname>/` already exists.

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
           "base_domain_name_choice": "accessto.page", "xray_base_domain_name_choice": "123987465.xyz",
           "net_location_index": 15, "chain_location_index": 15,
           "default_relation_host_choice": "play2go-nl-3"}}'

Role variables
--------------

| Variable | Default | Description |
| --- | --- | --- |
| `setup_node_inventory_dir` | directory of the inventory the play runs with, else `inventory/` of the project | Where `host_vars/` lives. |
| `setup_node_inventory_files` | the `.ini` files of `ansible_inventory_sources` | Inventory files that get the host. |
| `setup_node_groups_required` | `general_vps_prepare`, `domain_management` | Groups every host joins. |
| `setup_node_groups_optional` | `vpn_caddy`, `analytics_node`, `backup_restic_node` | Groups offered at the prompt (value: label). |
| `setup_node_groups_optional_default` | all three | The ones chosen when Enter is pressed. |
| `setup_node_groups_by_region` | `russia`: `vps_russia`, `vpn_caddy_russia_chain` (requires `vpn_caddy`) | Groups joined depending on the deployment region. |
| `setup_node_templates_always` | `0_all` | Template directories rendered for every host. |
| `setup_node_remna_node_domains` | the seven keys of `remna_node_domain_types_allowlist` | The `remna_node` entries of `1_domains.yaml`: `key`, `base` (`main` or `xray`), optional `index` (`net` or `chain`). |
| `setup_node_remna_protocol_types` | `vless_reality_tcp`, `vless_reality_xhttp` | Protocols offered at the prompt. |
| `setup_node_relation_host_groups` | `analytics_server`, `vpn_server_remnawave` | Groups whose hosts are offered as the default relation host. |
| `setup_node_backup_restic_remotes` | keys of `backup_restic_node_remotes_base` | Remotes written to `backup_restic_node/backup_restic_node.yaml`, each with a generated restic key. |
| `setup_node_prompt_answers` | `{}` | Preset answers by prompt id, for unattended runs. |

The prompts are in `vars/prompts/host.yml`; every answer is set as the
fact `initial_configure_host_<id>`, and the role adds
`initial_configure_host_hostname`, `initial_configure_host_base_domain_name`,
`initial_configure_host_xray_base_domain_name` and
`initial_configure_host_default_relation_host` for the templates.

Templates
---------

- `host/0_all/1_domains.yaml.j2`: `domains_keys.main`, the `remna_node`
  list (empty for a host outside `vpn_caddy`), `domains`,
  `host_relations.default`, `remna_node_use_dns01_cloudflare` and
  `domains_settings`, in the shape of
  the existing hosts.
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
