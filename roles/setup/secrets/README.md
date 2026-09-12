setup/secrets
=============

Writes the shared secrets of the inventory, on the controller. It was
`playbooks/ansible/secrets/*.yaml` before; the playbooks
`playbooks/ansible/initial_configure_step2.yaml` and
`playbooks/ansible/initial_configure_group.yaml` are now only its launchers.

`setup_secrets_scope` decides how much of the tree a run writes.

Scope `all`: step 2 of the initial configuration
------------------------------------------------

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

    ansible-playbook -i inventory/production.ini playbooks/ansible/initial_configure_step2.yaml

Scope `group`: the secrets of one inventory group
-------------------------------------------------

Step 2 writes the whole tree with freshly generated values, which is right
once and wrong afterwards: it rotates every credential of every group. This
scope writes one group, and keeps what is already there.

1. Lists the groups of `inventory/group_vars/` that have secret templates and
   asks which one to write. A group whose template directory is not named
   after it is matched through `setup_secrets_group_template_dirs`, so
   `general_vps_prepare` writes `1_general_vps_prepare`. The
   groups that resolve to no directory, like `git_sync`, are not offered.
2. Asks whether the values already written are kept. Answering no asks for a
   confirmation before every value of the group is generated again.
3. Renders the group's template directories into a staging directory, and
   merges each file with the one in the inventory before putting it in place.

The merge takes the shape from the template and the values from the file on
disk: every field the two have in common keeps its old value, however deeply
it is nested and including the items of lists, and only the fields the
templates added get a freshly generated value. An old value is ignored when
it is empty or still an `<angle bracket>` placeholder. Lists of mappings are
paired by the first key of `setup_secrets_preserve_id_keys` an item has, so
inserting an entry into a template does not shift the values onto the wrong
one; items with none of those keys are paired by position.

The merge works on the text of the rendered file, not on a structure that is
dumped again, so the commented out documentation the templates carry survives
it. A file whose merge changes nothing is not written at all, and a file that
is written leaves the previous one next to it as a `.bak`.

A trailing comment follows the value it sits behind: the templates write a
bcrypt hash and repeat the raw password in a comment, and keeping the old
hash keeps the old comment with it, so the two never disagree.

The e-mail addresses and the API tokens are not asked for again; they are
read from the inventory that step 2 wrote.

    ansible-playbook -i inventory/production.ini playbooks/ansible/initial_configure_group.yaml

Run it
------

Some templates read group variables of `vpn_caddy` and the other groups, so
localhost has to be in those sections of the inventory: step 1 puts it
there.

Unattended:

    ansible-playbook -i inventory/production.ini playbooks/ansible/initial_configure_step2.yaml \
      -e prompting_engine_interactive=false \
      -e '{"setup_secrets_prompt_answers": {"replace_secrets": true, "email_main": "me@example.com"}}'

    ansible-playbook -i inventory/production.ini playbooks/ansible/initial_configure_group.yaml \
      -e prompting_engine_interactive=false \
      -e '{"setup_secrets_prompt_answers": {"group": "vpn_caddy", "keep_existing": true}}'

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
| `setup_secrets_scope` | `all` | `all` writes the whole tree, `group` one inventory group. |
| `setup_secrets_group` | `""` | The group to write; only the default of the prompt. |
| `setup_secrets_group_vars_dir` | `group_vars/` of the inventory | Where the groups to choose from are looked up. |
| `setup_secrets_group_vars_exclude` | `[]` | Directories of that scan that name no deployable group. |
| `setup_secrets_group_template_dirs` | `all`, `general_vps_prepare`, `vpn_server_remnawave` | The template directories of a group whose directory is not named after it. |
| `setup_secrets_keep_existing` | `true` | Default of the prompt that keeps the values already written. |
| `setup_secrets_preserve_id_keys` | `name`, `id`, `username`, ... | The keys that pair the items of two lists of mappings. |
| `setup_secrets_prompt_answers` | `{}` | Preset answers by prompt id, for unattended runs. |

The prompts are in `vars/prompts/input.yml` and `vars/prompts/group.yml`, and
the merge is `filter_plugins/secrets_preserve.py`.

Requirements
------------

- ansible-core 2.19 or newer, for the prompting engine.
- The `ansible-prompting-engine` role and the `community.general`
  collection, both in `roles/requirements.yaml`.
- `passlib` and `bcrypt` on the controller: the templates hash passwords
  with `password_hash('bcrypt')`.
- ansible-core 2.19 or newer is what keeps the `{% raw %}` parts of the
  templates intact: the merged text is written through a module argument, and
  only that version stops the `{{ }}` it contains from being rendered again.
