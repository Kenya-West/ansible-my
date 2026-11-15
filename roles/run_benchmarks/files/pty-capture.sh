#!/usr/bin/env bash
#
# pty-capture.sh — run one benchmark script in a pseudo terminal and save
# everything it printed, escape codes included, to a file. The controller
# turns that file into the screenshot.
#
# Usage: pty-capture.sh <raw output> <columns> <timeout> <script> [bashrc]
#
# Exit code: the benchmark's (pty-runner.sh writes it to <script without
# .sh>.rc), or script(1)'s own when the PTY could not be set up.

set -u

out=$1 columns=$2 limit=$3 bench=$4 bashrc=${5:-}
runner="$(dirname "$(readlink -f "$0")")/pty-runner.sh"
rc_file="${bench%.sh}.rc"

rm -f -- "$out" "$rc_file"

# Older script(1) versions stop once stdin reaches EOF, and under Ansible
# stdin is already at EOF. So it gets a pipe that stays open (and empty)
# until the run is over; the sleep is bounded so it cannot linger for long.
exec 3< <(exec sleep "$((limit + 900))" 2>/dev/null)
keeper=$!

# script(1) gives the runner a PTY as its controlling terminal. With -q
# nothing but the PTY output goes to stdout (the log file argument would get
# a header and footer, so it is /dev/null and stdout is kept instead).
cmd=$(printf '%q ' bash "$runner" "$columns" "$limit" "$bench" "$rc_file" "$bashrc")
script -q -e -c "$cmd" /dev/null <&3 >"$out"
script_rc=$?

exec 3<&-
kill "$keeper" 2>/dev/null

rc=$(cat -- "$rc_file" 2>/dev/null) || exit "$script_rc"
exit "$rc"
