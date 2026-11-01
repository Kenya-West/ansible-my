# Microwarp

Deploys the Microwarp Docker Compose project and schedules rotation using the
`microwarp-rotate.service` / `.timer` **user-scoped** units. Cron installation is
no longer supported.

The existing defaults remain: daily at midnight in `Asia/Yakutsk`, up to 30
minutes of randomized delay, and persistent catch-up. Override
`systemd_unit_configs` to customize the units. `systemd_user`/`systemd_group`
default to `standard_user`, with files in
`/home/<standard_user>/.config/systemd/user`.

Requires the external `0x0I.systemd` role, systemd, an existing service account,
and Docker access for that account. Setup enables lingering and starts the user
manager. Services are not explicitly run during deployment; only timers are
enabled and started. Namespace sandboxing is omitted because unprivileged user
services cannot reliably create those namespaces on all hosts.

`microwarp_migrate_legacy_cron` defaults to `true`: the old root cron entry
`microwarp:rotate` is removed after timer reconciliation. Set
`microwarp_legacy_cron_name` if the old job had a customized name. No cron
scheduling variables or cron task files remain.

Update with `--tags update_systemd_timer` (or `install_systemd_timer`).
`role_state: absent` removes the timer and service before taking down Compose
and removing the project directory.

```bash
systemctl --user status microwarp-rotate.timer
journalctl --user -u microwarp-rotate.service
```
