#!/usr/bin/env bash
#
# pty-runner.sh — runs inside the PTY that pty-capture.sh sets up with
# script(1) and starts one benchmark script.
#
# Usage: pty-runner.sh <columns> <timeout> <script> <rc_file> [bashrc]
#
# script(1) starts this as the PTY's session leader, so its process group is
# the terminal's foreground group. The benchmark runs in that same group:
# it can call stty/tput without being stopped, and the timeout can signal
# the whole group, which reaches everything the benchmark started.
#
# On the way out anything the benchmark left running is killed, so nothing
# keeps writing to the terminal after the capture is over.

set -u

columns=$1 limit=$2 script=$3 rc_file=$4 bashrc=${5:-}

# The PTY gets no size from script(1) when Ansible runs it (no terminal on
# its side). Rows must match SCREEN_ROWS in ansi-flatten.py.
stty cols "$columns" rows 50 2>/dev/null
export COLUMNS=$columns LINES=50

# Header: the command line being run, as a terminal prompt would show it.
# With a bashrc (the Oh My Posh profile), the prompt is the one that profile
# gives an interactive bash: its prompt hooks run once and PS1 is expanded.
# \001/\002 are the markers bash puts around non-printing parts.
prompt=
if [ -n "$bashrc" ]; then
  prompt=$(bash --rcfile "$bashrc" -i -c \
    'for c in "${PROMPT_COMMAND[@]}"; do eval "$c"; done; printf "%s" "${PS1@P}"' \
    </dev/null 2>/dev/null | tr -d '\001\002')
fi
if [ -n "$prompt" ]; then
  printf '%s\033[0m\033[1m%s\033[0m\n\n' "$prompt" "$(<"$script")"
else
  printf '\033[1;32m$\033[0m \033[1m%s\033[0m\n\n' "$(<"$script")"
fi

# Marks where the benchmark's own output starts (after the header), for
# start_at in ansi-flatten.py. An OSC sequence: a terminal ignores it.
printf '\033]777;benchmark-output\007'

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
