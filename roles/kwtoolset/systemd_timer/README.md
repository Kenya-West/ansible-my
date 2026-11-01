# systemd_timer

Shared setup/removal for scheduled oneshot services using the `0x0I.systemd`
unit schema. Pass `systemd_timer_units`, `systemd_timer_state` (`present` or
`absent`), and optionally `systemd_timer_legacy_cron_jobs` (list of `{user, name}`
objects).

For user scope, enables lingering and starts `user@UID.service`. Installation
uses the external role; callers set `manage_state: false`, `enabled: false` on
oneshot services and enable/start only timers. Removal stops timers before
services, deletes unit files and reloads the corresponding service manager.
Lingering is not disabled on removal because other roles may still need it.

Legacy cron entries are removed only after unit reconciliation. Missing cron
binaries and nonexistent crontabs are tolerated. This helper never installs a
cron job. Requires privileged setup and the `0x0I.systemd` role.

Non-privileged contract tests capture the real roles' unit requests with a
fixture helper and verify generated units with systemd's parser:

```bash
ANSIBLE_ROLES_PATH="$PWD/roles/kwtoolset/systemd_timer/tests/fixtures/roles:$PWD/roles:$HOME/.ansible/roles" \
  ansible-playbook -i localhost, roles/kwtoolset/systemd_timer/tests/contract.yml
```
