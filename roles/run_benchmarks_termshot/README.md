# run_benchmarks_termshot

Runs a list of benchmark/check scripts on a host one after another, each
under [termshot](https://github.com/homeport/termshot), and fetches the PNG
screenshots of their terminal output to the controller:

```
inventory/host_vars/<inventory_hostname>/benchmarks/<YYYY-MM-DD_HHMMSS>/01_ip_check_place.png
                                                    01_ip_check_place.log   # raw output, view with less -R
```

Playbook: `playbooks/maintenance/benchmarks.yaml` (group `general_vps_prepare`).

```sh
ansible-playbook -i inventory/production.ini playbooks/maintenance/benchmarks.yaml -l <host>
# only some of them
ansible-playbook ... -e '{"benchmarks_termshot_select": ["yabs", "bench_sh"]}'
```

## Steps

1. When `/usr/local/bin/termshot` is missing (or `benchmarks_termshot_update`
   is true), runs `install_eget_inherelab` to check, install or update eget.
   Then it runs `install_packages_binary_concurrent` with only the
   `homeport/termshot` entry from `packages_binary_list_essentials`. That role
   needs GNU `parallel` on the host.
2. Installs the apt packages for commands the scripts check for
   (`benchmarks_termshot_dependencies`), only those not on the host. A script
   that finds one missing asks before installing it, and nobody can answer.
3. Runs every benchmark in `benchmarks_termshot_list` in order. Each one is
   written to a script and run by `files/termshot-capture.sh`, then the PNG
   is fetched.
4. Prints one status line per benchmark. It fails the host if any benchmark
   produced no screenshot (`benchmarks_termshot_fail_on_error`). A non-zero
   exit code or a timeout still gives a screenshot and is only reported.

## How a benchmark is run

- termshot copies its stdin into the PTY and closes the PTY when stdin
  reaches EOF. Under Ansible stdin is already at EOF, so the capture script
  gives termshot a pipe that stays open until it exits.
- Without a terminal, termshot sizes the PTY from `--columns` only when
  `CI=true` is set. The scripts see `benchmarks_termshot_columns` columns and
  `TERM=xterm-256color`, so they print colors.
- `files/pty-runner.sh` runs inside the PTY. It prints the command as a
  header and runs the script with stdin from `/dev/null`, so a prompt gets
  an empty answer instead of hanging. After `timeout` seconds it stops the
  whole process group, then prints a note that ends up in the screenshot.
  It also kills anything the script left running, because termshot renders
  only after every process has let go of the terminal.

## Limits

- termshot handles `\r` and erase-line (`\033[K`), so spinners and progress
  lines collapse to their final text. It does not handle cursor-up
  (`\033[1A`): a line redrawn that way shows both the old and the new
  version. IP.Check.Place uses this for its progress bars.
- A script that asks via `/dev/tty` (not stdin) waits until the timeout.
  The vernette and Davoyan ipregion scripts do this only when a dependency
  is missing, which step 2 prevents.
- termshot returns success whatever the command's exit code was, so the
  runner writes the benchmark's exit code to a file next to its script.
