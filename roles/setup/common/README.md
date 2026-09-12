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
