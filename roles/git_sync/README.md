# Git sync

Synchronizes each `git_sync_configs` entry using a user-scoped oneshot service
and persistent systemd timer. Requires `0x0I.systemd`, systemd, and an existing
`standard_user` account. Setup enables lingering and starts the user manager so
jobs run after logout and reboot.

Defaults:

- `git_sync_user`: `standard_user`
- `git_sync_home`: `/home/<git_sync_user>`
- `git_sync_systemd_unit_path`: `<git_sync_home>/.config/systemd/user`
- `git_sync_calendar`: `*-*-* 00:00:00` (host timezone)
- `git_sync_randomized_delay`: `5min`
- `git_sync_timeout`: `6h`

Each config can override `calendar` and `randomized_delay`. Unit names include
the **whole** config filename, e.g. `git-sync-repo.main.conf.timer`, so filenames
sharing the same first component no longer collide. Config filenames must be
unique basenames containing letters, numbers, dots, underscores and hyphens.

Root-owned project files and SSH keys are transferred to `git_sync_user`. Any
external SSH key files and persistent work directories referenced by configs
must also be accessible and writable as appropriate to that user. The
`analytics_node` monitoring wrapper is retained, including the existing metric
job names.

Deployment installs services without explicitly starting syncs; timers trigger
them, including catch-up runs from `Persistent=true`. Legacy root cron entries
are removed after timer reconciliation. Disable that cleanup with
`git_sync_migrate_legacy_cron: false`, or customize
`git_sync_legacy_cron_name_prefix` (the old `cron_job_name_prefix` is accepted for
cleanup only).

Use `--tags update_systemd_timer` to update scheduling. `role_state: absent`
stops/disables timers and services, removes their unit files and legacy cron
entries, then removes the project. Keep the same config list during removal;
removing a config from the list alone does not retire its old timer.

```bash
systemctl --user list-timers 'git-sync-*'
journalctl --user -u git-sync-repo.main.conf.service
```
