# Autorestic node backups

Deploys Autorestic configuration/scripts and schedules execution with persistent
**root-scoped systemd timers**. Root scope is deliberate: full-filesystem backups
and hooks retain root access without interactive sudo, new sudoers rules, or
sandbox options that prevent privilege elevation.

Requires systemd and the external `0x0I.systemd` role.

| Variable | Default |
| --- | --- |
| `restic_node_backup_unit_name` | `autorestic-backup` |
| `restic_node_forget_unit_name` | `autorestic-forget` |
| `restic_node_backup_calendar` | `*-*-* *:00,30:00` |
| `restic_node_forget_calendar` | `*-*-* 00:16:00` |
| `restic_node_backup_randomized_delay` | `5min` |
| `restic_node_timeout` | `24h` |
| `restic_node_systemd_unit_path` | `/etc/systemd/system` |

Calendars use the host timezone. The backup service invokes the existing
`update-cron.sh`; **`autorestic --ci cron` and the configuration's `cron` fields
are Autorestic's internal due-location selector, not OS cron jobs**, and remain
necessary. The forget service invokes `forget.sh`. The `analytics_node`
monitoring wrapper and `autorestic_backup`/`autorestic_forget` metric names are
preserved.

Timer reconciliation does not explicitly start the backup services. Persistent
timers may perform catch-up runs; the existing installation scenario still
performs its initial backup/configuration checks.

`restic_node_migrate_legacy_cron: true` removes the old root entries only after
both timers are reconciled. Customize `restic_node_legacy_cron_names` if needed;
old `restic_node_cron_job_name` and `restic_node_cron_job_name_forget` overrides
are accepted for cleanup only. Shell sleep prefixes are replaced by systemd's
randomized delay.

`playbooks/backup/node/remove_restic.yaml` removes timers/services and both legacy
cron entries before deleting the project, regardless of analytics group
membership. Scheduling can be reconciled separately via `tasks_from: systemd`
with `role_state: present` or `absent`.

```bash
sudo systemctl list-timers 'autorestic-*'
sudo journalctl -u autorestic-backup.service
```
