# configure_gai_ipv4

Makes glibc's `getaddrinfo(3)` return IPv4 addresses before IPv6 ones by
managing a marked block in `/etc/gai.conf`. Clients that connect to the first
address returned (apt, curl, wget, Python and most C programs) then use IPv4
on dual-stack hosts. This avoids slow or broken IPv6 paths without turning
IPv6 off.

Playbook: `playbooks/base/gai_prefer_ipv4.yaml` (group `general_vps_prepare`).
It is part of the `bootstrap*` profiles and `scenarios/0_start_step3.yaml`.

## What it writes

Any active `precedence` line replaces glibc's whole built-in table. So the
block restates the full default table and raises only `::ffff:0:0/96`:

```
precedence ::1/128          50
precedence ::/0             40
precedence 2002::/16        30
precedence ::/96            20
precedence ::ffff:0:0/96    100
```

The rest of the file is left as it is. The file is set to `root:root 0644`
because every process has to be able to read it.

## Safety checks

- Validates the variables. `gai_conf_ipv4_precedence` must be an integer
  above 50, otherwise IPv4 would not win.
- Skips hosts whose C library is not glibc (the file would be ignored there).
- Skips hosts with no IPv4 default route (`gai_conf_require_ipv4_route`).
- Follows a symlinked `/etc/gai.conf`, so the link is kept. Refuses a
  directory, a special file or a dangling link.
- Active `precedence` lines outside the block would merge into the same
  table. They are commented out with a `# disabled by configure_gai_ipv4: `
  prefix (the default), or the run fails without changing anything
  (`gai_conf_conflict_action: fail`).
- Keeps a backup copy before every change (`gai_conf_backup`).
- After a change, runs `getent ahosts one.one.one.one` and fails if an IPv6
  address still comes first. If DNS does not work yet, it only warns.
- Works with `--check --diff`.

`role_state: absent` removes the block and uncomments the lines the role
disabled (`gai_conf_restore_disabled`).

## Limits

- Long-running processes keep the table they already loaded. Restart a
  service if it needs the new order.
- `gai.conf` has no effect on programs that sort addresses themselves, such
  as Go's pure-Go resolver (e.g. Docker, Caddy, Xray) or Happy Eyeballs
  clients. It also does not apply inside containers, which have their own
  `/etc/gai.conf`.
