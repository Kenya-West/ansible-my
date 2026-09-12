setup/secrets
=============

Step 2 of the initial configuration of this project, on the controller. It
was `playbooks/ansible/secrets/*.yaml` before; the playbooks
`playbooks/scenarios/initial_configure_step2.yaml` and
`initial_configure_group_vpn.yaml` are now only its launchers.

What it does
------------

1. Looks at `group_vars/all/z_common_hosts_secrets/`. When secret files are
   already there (`.gitkeep` and `user.yaml` do not count), the first
   question is whether to replace them all; answering no ends the run
   without changing anything.
2. Asks (through the `ansible-prompting-engine` role) for the main and the
   domain e-mail addresses, the GitHub tokens for eget and deb-get, the ACME
   e-mail address and the Cloudflare DNS API token. Tokens are typed hidden
   and never logged.
3. Generates one password per entry of `setup_secrets_generated_passwords`,
   as the facts `initial_configure_generated_password_<name>`.
4. Renders `templates/group_vars/all/z_common_hosts_secrets/` into the
   secrets directory: `.j2` files are rendered with the answers and the
   passwords, the other files are copied as they are.

The facts the templates read are the same as before: `standard_user`,
`initial_configure_user_input_user_email` (`main`, `domain`),
`initial_configure_user_input_gh_token` (`eget`, `debget`),
`initial_configure_user_input_acme_email`,
`initial_configure_user_input_cloudflare_api_token_dns` and the generated
passwords.

Run it
------

    ansible-playbook -i inventory/production.ini playbooks/scenarios/initial_configure_step2.yaml

Some templates read group variables of `vpn_caddy` and the other groups, so
localhost has to be in those sections of the inventory: step 1 puts it
there.

Unattended:

    ansible-playbook -i inventory/production.ini playbooks/scenarios/initial_configure_step2.yaml \
      -e prompting_engine_interactive=false \
      -e '{"setup_secrets_prompt_answers": {"replace_secrets": true, "email_main": "me@example.com"}}'

Role variables
--------------

| Variable | Default | Description |
| --- | --- | --- |
| `setup_secrets_inventory_dir` | directory of the inventory the play runs with, else `inventory/` of the project | Where `group_vars/` lives. |
| `setup_secrets_dir` | `group_vars/all/z_common_hosts_secrets` in it | Where the secrets are written. |
| `setup_secrets_keep_files` | `.gitkeep`, `user.yaml` | Files that do not count as existing secrets. |
| `setup_secrets_template_dir` | `group_vars/all/z_common_hosts_secrets` | The tree rendered, relative to `templates/`. |
| `setup_secrets_generated_passwords` | 35 entries | The passwords to generate: `name`, optional `length`. |
| `setup_secrets_password_length` | `50` | Length of a generated password. |
| `setup_secrets_password_special_chars` | `-=+!#$()[]` | Special characters allowed in a password. |
| `setup_secrets_prompt_answers` | `{}` | Preset answers by prompt id, for unattended runs. |

The prompts are in `vars/prompts/input.yml`.

Requirements
------------

- ansible-core 2.19 or newer, for the prompting engine.
- The `ansible-prompting-engine` role and the `community.general`
  collection, both in `roles/requirements.yaml`.
- `passlib` and `bcrypt` on the controller: the templates hash passwords
  with `password_hash('bcrypt')`.
