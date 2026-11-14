#!/usr/bin/env bash
#
# termshot-capture.sh — run one benchmark script under termshot and render
# its terminal output into a PNG.
#
# Usage: termshot-capture.sh <termshot> <png> <columns> <timeout> <script> [bashrc]
#
# Exit code: termshot's own when it fails (no PNG then), otherwise the
# benchmark's (pty-runner.sh writes it to <script without .sh>.rc).

set -u

termshot=$1 png=$2 columns=$3 limit=$4 script=$5 bashrc=${6:-}
runner="$(dirname "$(readlink -f "$0")")/pty-runner.sh"
rc_file="${script%.sh}.rc"

rm -f -- "$png" "$rc_file"

# termshot copies its stdin into the PTY and closes the PTY as soon as stdin
# reaches EOF. Under Ansible stdin is already at EOF, which would cut the
# capture short, so termshot gets a pipe that stays open (and empty) until it
# exits. The sleep is bounded so it cannot outlive a killed run for long.
exec 3< <(exec sleep "$((limit + 900))" 2>/dev/null)
keeper=$!

# Without a terminal on stdout, termshot sizes the PTY from --columns only
# when CI=true; pty-runner.sh unsets CI again before starting the benchmark.
CI=true "$termshot" --columns "$columns" --filename "$png" \
  -- bash "$runner" "$limit" "$script" "$rc_file" "$bashrc" <&3
termshot_rc=$?

exec 3<&-
kill "$keeper" 2>/dev/null

if [ "$termshot_rc" -ne 0 ]; then
  exit "$termshot_rc"
fi

rc=$(cat -- "$rc_file" 2>/dev/null) || rc=255
exit "$rc"
