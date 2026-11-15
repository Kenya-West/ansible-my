#!/usr/bin/env bash
#
# render-png.sh — turn one benchmark's raw terminal output into a PNG.
#
# Usage: render-png.sh <raw output> <png> <columns> <font family> <freeze>
#                      [start_at]
#
# 1. ansi-flatten.py replays the output like a terminal would, so progress
#    bars and spinners collapse to their final text (freeze itself would
#    print every redraw one after another).
# 2. freeze (charmbracelet/freeze) draws it as a terminal window. With
#    rsvg-convert in PATH it uses that for the PNG, which falls back through
#    the installed fonts glyph by glyph, so emoji and Nerd Font icons show
#    as long as a font has them. Emoji come out in the text color, not their
#    own: color emoji need a browser engine, which is not used here.

set -euo pipefail

raw=$1 png=$2 columns=$3 font=$4 freeze=$5 start_at=${6:-}
here="$(dirname "$(readlink -f "$0")")"

command -v rsvg-convert >/dev/null || {
  echo "rsvg-convert is missing: freeze would draw every emoji and icon as a square" >&2
  exit 1
}

flat=$(mktemp)
trap 'rm -f -- "$flat"' EXIT

python3 -I "$here/ansi-flatten.py" "$raw" "$columns" "$start_at" >"$flat"

rm -f -- "$png"
timeout 600 "$freeze" --config full --language ansi --font.family "$font" \
  --output "$png" "$flat" >/dev/null

[ -s "$png" ] || {
  echo "freeze made no PNG" >&2
  exit 1
}
