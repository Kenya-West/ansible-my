kwtoolset/resolve_host_relations
================================

Resolves `host_relations` of the host the role runs against into the hosts a
solution of that host relates to (the upstream it pushes to, is scraped by,
registers with...).

For a relation group and a component, the first non-empty `hosts` list of

```
host_relations.<group>.components.<component>.hosts
    ↓ fallback
host_relations.<group>.hosts
    ↓ fallback
host_relations.default.hosts
```

is taken and sorted by `priority` (lowest first; equal priorities keep their
order). Every `host` must be an `inventory_hostname` of the inventory the play
runs against, and every relation must be a mapping (`default: {hosts: [...]}`,
not `default: [...]`); the role fails otherwise.

```yaml
# host_vars/node-17/1_domains.yaml
host_relations:
  default:
    hosts:
      - host: somehosting-zz-1
        priority: 1
      - host: somehosting-zz-2
        priority: 10

  analytics_server:
    hosts:
      - host: somehosting-zz-4

    components:
      pushgateway:
        hosts:
          - host: somehosting-zz-3
```

| group / component                  | `resolve_host_relations_host` | `resolve_host_relations_hosts`         |
| ---------------------------------- | ----------------------------- | -------------------------------------- |
| `analytics_server` / `pushgateway` | `somehosting-zz-3`            | `[somehosting-zz-3]`                   |
| `analytics_server` / `grafana`     | `somehosting-zz-4`            | `[somehosting-zz-4]`                   |
| `vpn_server_remnawave` / `panel`   | `somehosting-zz-1`            | `[somehosting-zz-1, somehosting-zz-2]` |
| host without `host_relations`      | `''`                          | `[]`                                   |

Role Variables
--------------

Input:

- `resolve_host_relations_group`: the relation group, the inventory group of
  the side the solution relates to (`analytics_server` for both the node and
  the server playbooks of observability). Default `""`.
- `resolve_host_relations_component`: the component of the group, the key of
  the solution in `<group>.project.paths` where there is one. Default `""`.
- `resolve_host_relations_source`: the relations to resolve. Default
  `host_relations`, or `{}` when it is undefined.
- `resolve_host_relations_default_priority`: the priority of a relation host
  without one. Default `100`.

Output (host facts):

- `resolve_host_relations_host`: the relation host of the highest priority, a
  string, `''` when nothing resolves. For components that need one upstream.
- `resolve_host_relations_hosts`: all the resolved relation hosts, by
  priority. For components that use every upstream.

Usage
-----

Each playbook that deploys a solution names its relation group and component
and runs the role first, so the facts are there for the roles after it:

```yaml
- name: Install and configure PushGateway with dependencies
  hosts: analytics_node
  become: false
  become_user: "{{ standard_user }}"

  roles:
    - name: kwtoolset/resolve_host_relations
      vars:
        resolve_host_relations_group: analytics_server
        resolve_host_relations_component: pushgateway
    - install_analytics_node_pushgateway
```

A role that needs another relation includes the role again; the facts are
overwritten:

```yaml
- name: Resolve the VictoriaLogs relation
  ansible.builtin.include_role:
    name: kwtoolset/resolve_host_relations
  vars:
    resolve_host_relations_group: analytics_server
    resolve_host_relations_component: victorialogs
```

Test
----

```sh
ansible-playbook -i roles/kwtoolset/resolve_host_relations/tests/inventory \
  roles/kwtoolset/resolve_host_relations/tests/test.yml
```
