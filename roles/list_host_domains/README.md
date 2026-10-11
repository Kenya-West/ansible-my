list_host_domains
==================

Prints, for every host the play targets (set by `target_hosts`, narrowed by `--limit`), the unique domains found in its `domains_keys` variable. Each domain is listed with the key(s) it came from, so a domain used by several keys appears once.

Read-only: makes no changes on any host.

Role Variables
--------------

None. The hosts come from the play: `-e target_hosts=<group|host|pattern>` selects them and `--limit` narrows them. The role runs with `connection: local` and prints once (`run_once`).

Every `domains_keys` value is read as it resolves for that host, so templated values such as `main: "{{ inventory_hostname }}.…"` show their final domain.

Supported `domains_keys` shapes:

- a string value (`main`, `prometheus`, ...), listed under its key;
- a list of `{domain, type}` objects (`remna_node`), listed as `key[index] (type)`;
- a list of strings, listed as `key[index]`.

Dependencies
------------

None. Uses the `hostvars` magic variable and the play's `ansible_play_hosts`.

Example Playbook
----------------

See [playbooks/ansible/node/list_host_domains.yaml](../../playbooks/ansible/node/list_host_domains.yaml).

    ansible-playbook -i ./inventory/production.ini ./playbooks/ansible/node/list_host_domains.yaml --limit=play2go-de-7

License
-------

MIT

Author Information
------------------

Kenya-West
