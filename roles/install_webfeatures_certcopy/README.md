# Caddy certificate copying

Copies Caddy certificates to the shared certificate directory using
`certcopy.service` / `.timer`, scoped to `standard_user`. Requires systemd,
`0x0I.systemd`, sudo/visudo, Docker and rsync. Lingering is enabled so scheduling
continues after logout and reboot.

Defaults:

- `certcopy_user`: `standard_user`
- `certcopy_home`: `/home/<certcopy_user>`
- `certcopy_systemd_unit_path`: `<certcopy_home>/.config/systemd/user`
- `certcopy_unit_name`: `certcopy`
- `certcopy_calendar`: `*-*-* 00:00:00` (host timezone)
- `certcopy_randomized_delay`: `0`
- `certcopy_timeout`: `30min`

The privileged helper is rendered directly from the role template to
`/usr/local/libexec/ansible-certcopy/copy.sh`, owned by root in a root-owned
non-user-writable directory. `/etc/sudoers.d/ansible-certcopy` permits only this
helper **without arguments**, with `NOPASSWD` and no TTY requirement. The user
service invokes `sudo -n`; it must not set `NoNewPrivileges=yes` or namespace
hardening that prevents sudo. Keep helper paths outside user-writable
locations. This retains access to root-owned shared certificates without giving
sudo permission to execute a user-editable project script.

The `analytics_node` wrapper and `copy_certs` metric name are preserved. The
service is explicitly run once during installation, as certificate copying was
before; the persistent timer schedules subsequent runs.

`certcopy_migrate_legacy_cron: true` removes the old root `Copy certs` entry after
the timer is reconciled. Old `copy_certs_auto_renew_hour`/`minute` options are
replaced by `certcopy_calendar`.

`playbooks/reverse_proxy/remove.yaml` removes the timer/service, helper and sudo
rule before deleting the project. Scheduling can be reconciled alone with
`tasks_from: systemd`; pass `role_state: absent` to remove units.

```bash
systemctl --user list-timers certcopy.timer
journalctl --user -u certcopy.service
```
