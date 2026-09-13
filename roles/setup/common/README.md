setup/common
============

Task files shared by the roles under `roles/setup/`. The role does nothing
when included as a whole; include one of its task files with `tasks_from`.

render_tree
-----------

Writes a tree of templates and plain files, kept in a role, into a directory
of this project on the controller. Files ending with `.j2` are rendered and
lose the extension; every other file is copied byte for byte, so Jinja meant
for the inventory (`"{{ inventory_hostname }}"` in a plain `.yaml`) survives.
Nothing needs rsync or `become`.

```yaml
- ansible.builtin.include_role:
    name: setup/common
    tasks_from: render_tree
  vars:
    setup_render_tree_src: "{{ role_path }}/templates/host/0_all"
    setup_render_tree_dest: "{{ inventory_dir }}/host_vars/ovh-sg-2/0_all"
```

| Variable | Default | Description |
| --- | --- | --- |
| `setup_render_tree_src` | | Source directory, absolute path. |
| `setup_render_tree_dest` | | Destination directory; created when missing. |
| `setup_render_tree_file_mode` | `0664` | Mode of the written files. |
| `setup_render_tree_dir_mode` | `0775` | Mode of the created directories. |

generate_passwords
------------------

Generates random passwords as facts, `initial_configure_generated_password_<name>`
by default, for the templates of `setup/secrets` and `setup/server`. Nothing is
logged.

```yaml
- ansible.builtin.include_role:
    name: setup/common
    tasks_from: generate_passwords
  vars:
    setup_generate_passwords:
      - name: analytics_server_victorialogs
      - name: vpn_common_frp_token
        length: 15
```

| Variable | Default | Description |
| --- | --- | --- |
| `setup_generate_passwords` | | The passwords: `name`, optional `length`. |
| `setup_generate_passwords_length` | `50` | Length of a password without its own. |
| `setup_generate_passwords_special_chars` | `-=+!#$()[]` | Special characters allowed. |
| `setup_generate_passwords_prefix` | `initial_configure_generated_password_` | Prefix of the facts. |

inventory_add_host
------------------

Adds `<name> ansible_host=<address>` to sections of INI inventory files; the
first file is backed up once. Used by `setup/node` and `setup/server`.

| Variable | Default | Description |
| --- | --- | --- |
| `setup_inventory_add_host_files` | | The INI files. |
| `setup_inventory_add_host_name` | | The inventory hostname. |
| `setup_inventory_add_host_address` | | Its `ansible_host`. |
| `setup_inventory_add_host_groups` | | The sections it is added to. |

templates/host/0_all
--------------------

The `host_vars/<hostname>/0_all/` files every host gets, whether `setup/node`
or `setup/server` adds it: `2_domains.yaml`, the documentation of the
additional DNS records and of `host_relations`, as comments.
