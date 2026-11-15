# run_benchmarks

Runs a list of benchmark/check scripts on a host one after another, each in
its own terminal, and saves PNG screenshots of their output on the
controller:

```
inventory/host_vars/<inventory_hostname>/benchmarks/<YYYY-MM-DD_HHMMSS>/01_ip_check_place.png
                                                    01_ip_check_place.log   # raw output, view with less -R
```

Playbook: `playbooks/maintenance/benchmarks.yaml` (group `general_vps_prepare`).

```sh
ansible-playbook -i inventory/production.ini playbooks/maintenance/benchmarks.yaml -l <host>
# only some of them
ansible-playbook ... -e '{"benchmarks_select": ["yabs", "bench_sh"]}'
```

## Steps

1. When `/usr/local/bin/freeze` is missing (or `benchmarks_freeze_update` is
   true), runs `install_eget_inherelab`, then `install_packages_eget_inherelab`
   with only the `charmbracelet/freeze` entry from
   `packages_binary_list_essentials` and its own eget config
   (`benchmarks_freeze_eget_config`), so the main `eget.toml` is untouched.
2. Installs with apt the commands the scripts check for
   (`benchmarks_dependencies`, only those not on the host; a script that
   finds one missing asks before installing it, and nobody can answer), plus
   `rsvg-convert` and the fonts for the screenshots (`benchmarks_font_packages`).
3. Switches TCP congestion control to BBR (`benchmarks_enable_bbr`) when it
   is not already, with `sysctl -w`, so nothing is written to sysctl files.
   After the last benchmark, also when one fails, the previous algorithm is
   set again. A kernel without BBR only gets a warning.
4. Runs every benchmark in `benchmarks_list` in order. Each one is written to
   a script and run by `files/pty-capture.sh`.
5. Renders the PNG on the host with `files/render-png.sh` and fetches it,
   plus the raw output as `NN_<name>.log` when `benchmarks_save_logs` is true.
6. Prints one status line per benchmark. It fails the host if any benchmark
   produced no screenshot (`benchmarks_fail_on_error`). A non-zero exit code
   or a timeout still gives a screenshot and is only reported.

## How a benchmark is run

- `files/pty-capture.sh` starts `files/pty-runner.sh` under `script(1)`,
  which gives it a PTY, and keeps everything printed to it. Older `script`
  versions stop when stdin reaches EOF, and under Ansible stdin is already
  at EOF, so it gets a pipe that stays open until the run is over.
- `files/pty-runner.sh` sets the PTY to `benchmarks_columns`
  columns and 50 rows; the scripts also see `TERM=xterm-256color`, so they
  print colors. It prints the command as a header (with the Oh My Posh
  prompt from the user's `.bashrc` when there is one) and runs the script
  with stdin from `/dev/null`, so a prompt gets an empty answer instead of
  hanging. After `timeout` seconds it stops the whole process group, then
  prints a note that ends up in the screenshot. It also kills anything the
  script left running.

## How a screenshot is rendered

1. `files/ansi-flatten.py` replays the raw output like a terminal: carriage
   return, backspace, erase in line/display, cursor up/down/left/right and
   absolute positioning, line wrapping at the column count. Spinners and
   progress bars, including ones redrawn with cursor-up, end up as their
   final text. Colors and text attributes are kept. (`freeze --execute`
   would show every redraw one after another.) A screen clear (`clear`)
   starts a fresh screen below what was printed, so nothing is lost. freeze
   ignores the basic background colors (`\e[41m` etc.), so they are passed
   on as true colors from the Tango palette, which keeps white text on them
   readable. With `start_at` the output is cut here (see below).
2. `freeze --config full --language ansi` draws it as a terminal window in
   `benchmarks_font_family`. With `rsvg-convert` in `PATH` freeze uses it
   for the PNG, and it takes every glyph the first font lacks from another
   installed font. freeze's built-in PNG export knows only its bundled font
   and draws emoji and icons as squares, so `rsvg-convert` is required.

## Per-benchmark options

Besides `name` and `command`, an entry in `benchmarks_list` can set:

- `timeout`: seconds before it is stopped (default `benchmarks_timeout`)
- `columns`: terminal width for this one (default `benchmarks_columns`),
  e.g. `vernette_censorcheck_dpi` gets 120
- `start_at`: the screenshot shows the output from the first line that
  contains this text; everything before it is left out, the command header
  stays. When the text never shows up, everything is kept. The raw `.log`
  is always complete. `ip_check_place` uses it to skip the sponsor banners.
  This is done after the run, not with `| sed`/`| awk` in the command: a
  pipe would take the script's terminal away, so it would stop printing
  colors and progress bars.

## Limits

- Emoji are drawn in the text color, not in their own colors: color emoji
  need a browser engine, which is deliberately not used.
- Nerd Font icons (the Oh My Posh prompt) need a Nerd Font on the host; none
  is installed by this role, so they are squares unless one is added.

- A script that asks via `/dev/tty` (not stdin) waits until the timeout.
  The vernette and Davoyan ipregion scripts do this only when a dependency
  is missing, which step 1 prevents.
- A full-screen program (one that switches to the alternate screen) is not
  emulated beyond the basics; only its last 50 rows of output matter.
