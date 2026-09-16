setup/server
============

Adds a server to the inventory, on the controller, with secrets of its own.
A server is a host of `analytics_server`, `vpn_server_remnawave`,
`backup_restic_server` or `matrix_server`. The nodes relate to it
(`host_relations`) and read its credentials from its `host_vars/` through
`kwtoolset/resolve_host_relations`, so its secrets are written there and
nowhere else: `setup/secrets` no longer writes server secrets to
`group_vars/all/`, where every host would load them.

`playbooks/ansible/server/add_server_initial.yaml` is its launcher.

What it does
------------

1. Looks at what the inventory already holds, with the scan of `setup/node`
   (`tasks_from: scan`): the hostnames, the addresses in use, the base
   domains of the existing hosts and the hosts of
   `setup_node_relation_host_groups`.
2. Asks, through the `ansible-prompting-engine` role, for:
   - the hosting provider, the country and the index: the hostname is
     `<provider>-<country>-<index>` (`play2go-nl-3`); the index defaults to
     the next free one for that country and must not produce a hostname that
     exists;
   - the IPv4 address, checked against the ones already in use;
   - the server groups, at least one; `general_vps_prepare` and
     `domain_management` are always joined;
   - the base domain of the server's own domain, chosen from the base
     domains already in use or typed;
   - for each server group with service domains, their base domain
     (`prometheus.<base>`, `rw.<base>`, `matrix.<base>` ..., see
     `setup_server_service_domains`), the server's own base domain by
     default;
   - for `vpn_server_remnawave`, the base domain of the Xray domains of the
     nodes relating to the panel (`vpn_server_remnawave_node_base_domains.xray`,
     next to `.main`, the server's own base domain), from which
     `group_vars/vpn_caddy/domain_generator.yaml` builds their `domains_keys`;
   - for `matrix_server`, the admin account; for `analytics_server`, the
     Telepush bot token (optional, hidden);
   - the host the server relates to by default (`host_relations.default`):
     the server itself when it joins `analytics_server` or
     `vpn_server_remnawave`, otherwise the first of those hosts.
3. Generates one password per entry of `setup_server_generated_passwords`,
   as the facts `initial_configure_generated_password_<name>`, for this
   server only.
4. Renders `templates/host/0_all/` of `setup/common` and of this role, and
   the directory of every server group joined, into `host_vars/<hostname>/`.
5. Adds `<hostname> ansible_host=<ip>` to every group's section of the
   inventory file(s) the play runs with.
6. Lists the files that still hold `<placeholders>` to fill in by hand
   (tokens of external services, the node `SECRET_KEY` the Remnawave panel
   shows once it runs, ...).

Nothing is written when `host_vars/<hostname>/` already exists.

A server that is also a node, like `play2go-nl-3` (`vpn_caddy`,
`analytics_node`, `backup_restic_node`), gets the node groups and their
`host_vars/` by hand: `setup/node` refuses a host whose `host_vars/` exists.

Run it
------

    ansible-playbook -i inventory/production.ini playbooks/ansible/server/add_server_initial.yaml

The play must run against the inventory, with localhost listed in it, after
steps 1 and 2 of the initial configuration, so that `group_vars/all`
(`standard_user`, `emails`, the internal paths) applies to the controller.

Unattended, e.g. an analytics and Remnawave server in the Netherlands:

    ansible-playbook -i inventory/production.ini playbooks/ansible/server/add_server_initial.yaml \
      -e prompting_engine_interactive=false \
      -e '{"setup_server_prompt_answers": {"provider": "play2go", "country_code": "nl", "index": 4,
           "ip_address": "203.0.113.20", "groups": ["analytics_server", "vpn_server_remnawave"],
           "base_domain_name_choice": "accessto.page", "analytics_base_domain_name": "kenyawest.me",
           "remnawave_base_domain_name": "accessto.page", "node_xray_base_domain_name": "123987465.xyz",
           "default_relation_host_choice": "play2go-nl-4"}}'

Role variables
--------------

| Variable | Default | Description |
| --- | --- | --- |
| `setup_server_inventory_dir` | directory of the inventory the play runs with, else `inventory/` of the project | Where `host_vars/` lives. |
| `setup_server_inventory_files` | the `.ini` files of `ansible_inventory_sources` | Inventory files that get the server. |
| `setup_server_groups_required` | `general_vps_prepare`, `domain_management` | Groups every server joins. |
| `setup_server_groups_optional` | `analytics_server`, `vpn_server_remnawave`, `backup_restic_server`, `matrix_server` | Server groups offered at the prompt (value: label). |
| `setup_server_groups_optional_default` | `analytics_server` | The ones chosen when Enter is pressed. |
| `setup_server_templates_always` | `0_all` | Template directories rendered for every server. |
| `setup_server_service_domains` | the service domains of `analytics_server`, `vpn_server_remnawave` and `matrix_server` | `domains_keys` of each group, `key: label`, written as `<label>.<base domain of the group>`. |
| `setup_server_relation_host_groups` | `analytics_server`, `vpn_server_remnawave` | Groups whose hosts are offered as the default relation host. |
| `setup_server_generated_passwords` | 20 entries | The passwords generated for the server: `name`, optional `length`. |
| `setup_server_password_length` | `50` | Length of a generated password. |
| `setup_server_password_special_chars` | `-=+!#$()[]` | Special characters allowed in a password. |
| `setup_server_prompt_answers` | `{}` | Preset answers by prompt id, for unattended runs. |

The prompts are in `vars/prompts/host.yml`; every answer is set as the fact
`initial_configure_server_<id>`, and the role adds
`initial_configure_server_hostname`, `initial_configure_server_base_domain_name`,
`initial_configure_server_default_relation_host`, `setup_server_groups` and
`setup_server_service_base_domains` for the templates.

Templates
---------

- `host/0_all/1_domains.yaml.j2`: `domains_keys.main` and the service
  domains of the groups joined, an empty `remna_node`, `domains` and
  `host_relations.default`.
- `host/analytics_server/`: Prometheus (its basic auth users, the scrape jobs
  and `prometheus_server_scrape_credentials`, the credentials the nodes
  relating to the server read), PushGateway, VictoriaLogs, VictoriaMetrics,
  the MongoDB exporter, the XRay checker, Alertmanager, Telepush and Grafana.
  The FRPS job's password is the nodes' `frp_dashboard_password`, and the
  Restic job's is the backup server's: they are placeholders unless the
  backup server is this one.
- `host/vpn_server_remnawave/`: the panel (`vpn_server_remnawave_node_secret_key`
  included, to fill in from the panel), the custom login route, the mini app,
  the bots, and the service user and REALITY password the generated chain
  outbounds are rendered with.
- `host/backup_restic_server/`: the users of the Restic REST server.
- `host/matrix_server/`: the Synapse settings and its database password.

Requirements
------------

- ansible-core 2.19 or newer, for the prompting engine.
- The `ansible-prompting-engine` role and the `community.general`
  collection, both in `roles/requirements.yaml`.
- `passlib` and `bcrypt` on the controller: the templates hash passwords
  with `password_hash('bcrypt')`.
