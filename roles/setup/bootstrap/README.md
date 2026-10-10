setup/bootstrap
===============

Step 1 of the initial configuration of this project, on the controller. It
was `playbooks/ansible/bootstrap/*.yaml` before; the playbook
`playbooks/scenarios/initial_configure_step1.yaml` is now only its launcher.

What it does
------------

1. Makes sure the inventory file exists. When it is missing,
   `templates/inventory/production.ini.j2` is written in its place.
2. Puts `localhost ansible_connection=local ansible_become=false` in every
   section of `setup_bootstrap_localhost_sections`, so that the controller
   can be a target of the playbooks.
3. Asks for the standard username (through the `ansible-prompting-engine`
   role) and makes it the name of the first user of `users_to_set` in
   `group_vars/general_vps_prepare/users.yaml`.
4. Renders `templates/group_vars_initial/` into
   `group_vars/all/z_common_hosts_secrets/`: the user file with a generated
   root password.

Run it
------

    ansible-playbook -i inventory/production.ini playbooks/scenarios/initial_configure_step1.yaml

Without an inventory yet, run it the same way: the file is created first.
The questions are asked once, on the controller.

Unattended:

    ansible-playbook -i inventory/production.ini playbooks/scenarios/initial_configure_step1.yaml \
      -e prompting_engine_interactive=false \
      -e '{"setup_bootstrap_prompt_answers": {"standard_user": "alice"}}'

Role variables
--------------

| Variable | Default | Description |
| --- | --- | --- |
| `setup_bootstrap_inventory_dir` | directory of the inventory the play runs with, else `inventory/` of the project | Where `group_vars/` and the inventory file live. |
| `setup_bootstrap_inventory_file` | the inventory file the play runs with, else `production.ini` in the directory above | The INI file that gets the localhost entries. |
| `setup_bootstrap_localhost_sections` | `general_vps_prepare`, `vpn_caddy`, `analytics_node`, `analytics_server`, `proxy_client`, `backup_restic_server`, `backup_restic_node` | Sections that get a localhost entry. |
| `setup_bootstrap_users_file` | `group_vars/general_vps_prepare/users.yaml` | The file whose first user is renamed. |
| `setup_bootstrap_render` | `group_vars_initial/all/z_common_hosts_secrets` | Template trees rendered into the inventory directory. |
| `setup_bootstrap_prompt_answers` | `{}` | Preset answers by prompt id, for unattended runs. |

The prompts are in `vars/prompts/users.yml`. The answer is set as the fact
`standard_user`.

Requirements
------------

- ansible-core 2.19 or newer, for the prompting engine.
- The `ansible-prompting-engine` role and the `community.general`
  collection, both in `roles/requirements.yaml`.
