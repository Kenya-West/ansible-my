# wait_for_apt

Waits until nothing else uses APT/dpkg: unattended-upgrades, apt.systemd.daily,
the `apt-daily*.service` units, cloud-init package stages, or any process
holding the dpkg/APT locks. Fresh Debian/Ubuntu VPSs run these for many minutes
after first boot, and `ansible.builtin.apt` gives up after its 60 s
`lock_timeout`.

Include it right before tasks that touch APT, including third-party roles
(`oefenweb.fail2ban`, `geerlingguy.docker`) whose `lock_timeout` you can't set:

```yaml
- name: Wait for APT/dpkg to be free
  ansible.builtin.include_role:
    name: kwtoolset/wait_for_apt
```

- Idle host: one quick synchronous check, `ok`.
- Busy host: shows the reasons, then waits in an async task
  (`wait_for_apt_poll`), up to `wait_for_apt_timeout` (default 1800 s). After a
  busy spell, APT must stay idle for `wait_for_apt_settle` seconds, which covers
  the gap between `apt-get update` and `upgrade` inside apt.systemd.daily.
- Interrupted dpkg (`/var/lib/dpkg/updates` not empty, e.g. a reboot during
  unattended-upgrades): runs `dpkg --configure -a`, the only `changed` result.
- Non-dpkg hosts: `ok`, nothing to do.

Lock holders come from `/proc/locks`, so `fuser`/`psmisc` is not required. The
check lives in the role's own module, `library/wait_for_apt_lock.py`.

Variables are in `defaults/main.yml`.
