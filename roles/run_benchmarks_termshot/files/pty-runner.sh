#!/usr/bin/env bash
#
# pty-runner.sh — runs inside termshot's PTY and starts one benchmark script.
#
# Usage: pty-runner.sh <timeout> <script> <rc_file>
#
# termshot starts this as the PTY's session leader, so its process group is
# the terminal's foreground group. The benchmark runs in that same group:
# it can call stty/tput without being stopped, and the timeout can signal
# the whole group, which reaches everything the benchmark started.
#
# termshot renders only after every process holding the terminal has closed
# it, so on the way out anything the benchmark left running is killed.

set -u

limit=$1 script=$2 rc_file=$3

unset CI  # set for termshot only, see termshot-capture.sh

# Header: the command line being run, as a terminal prompt would show it
printf '\033[1;32m$\033[0m \033[1m%s\033[0m\n\n' "$(<"$script")"

# stdin is /dev/null: a prompt gets an empty answer instead of waiting
bash "$script" </dev/null &
child=$!

(
  sleep "$limit"
  printf '\n\033[1;31m*** Stopped: no result after %ss ***\033[0m\n' "$limit"
  kill -TERM 0
) &

# Ignore TERM only now, so the benchmark and the watcher keep the default
trap '' TERM

wait "$child"
rc=$?
printf '%s\n' "$rc" >"$rc_file"

if [ "$rc" -ne 0 ]; then
  printf '\n\033[2m(exit code %s)\033[0m\n' "$rc"
fi

kill -TERM 0 2>/dev/null
sleep 1
for pid in $(pgrep -g "$$"); do
  [ "$pid" != "$$" ] && kill -KILL "$pid" 2>/dev/null
done

exit "$rc"
