#!/usr/bin/env bash
#
# run-parallel-cmds.sh — Execute commands in parallel via GNU parallel
#                         with structured output, logging, and progress.
#
# Usage:
#   run-parallel-cmds.sh [OPTIONS] [--] "cmd1" "cmd2" ...
#   run-parallel-cmds.sh [OPTIONS] -f commands.txt
#   echo -e "cmd1\ncmd2" | run-parallel-cmds.sh [OPTIONS]
#
# Requires: GNU parallel

set -uo pipefail

# ═══════════════════════════════════════════════════════════════════════════════
# Defaults
# ═══════════════════════════════════════════════════════════════════════════════
TIMEOUT=30
PREPEND=""
APPEND=""
SHOW_LOGS=false
TAIL_LINES=0
SHOW_EXIT_CODE=true
FORMAT="json"           # json | text
SHORT_OUTPUT=false
OUTPUT_FILE=""
MAX_JOBS=0              # 0 = let parallel decide (CPU count)
NO_COLOR=false
declare -a COMMANDS=()

# ═══════════════════════════════════════════════════════════════════════════════
# Colors (set once after arg parsing)
# ═══════════════════════════════════════════════════════════════════════════════
RED="" GRN="" YLW="" BLU="" CYN="" BLD="" DIM="" RST=""

init_colors() {
  if [[ "$NO_COLOR" == true ]] || [[ ! -t 2 ]]; then
    return
  fi
  RED=$'\033[31m'   GRN=$'\033[32m'   YLW=$'\033[33m'
  BLU=$'\033[34m'   CYN=$'\033[36m'   BLD=$'\033[1m'
  DIM=$'\033[2m'    RST=$'\033[0m'
}

# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════
die()  { printf '%s\n' "${RED}Error:${RST} $*" >&2; exit 1; }

fmt_elapsed() {
  local s=$1
  if (( s >= 3600 )); then printf '%dh%02dm%02ds' $((s/3600)) $((s%3600/60)) $((s%60))
  elif (( s >= 60 )); then printf '%dm%02ds' $((s/60)) $((s%60))
  else                      printf '%ds' "$s"
  fi
}

# Pure-bash JSON string escape (handles \, ", newline, CR, tab)
json_escape() {
  local s="$1"
  s="${s//\\/\\\\}"
  s="${s//\"/\\\"}"
  s="${s//$'\n'/\\n}"
  s="${s//$'\r'/\\r}"
  s="${s//$'\t'/\\t}"
  printf '%s' "\"$s\""
}

strip_ansi() { sed $'s/\033\[[0-9;]*m//g'; }

progress_bar() {
  local pct=$1 width=${2:-30}
  local filled=$(( pct * width / 100 ))
  local empty=$(( width - filled ))
  printf '%s' "${GRN}"
  printf '█%.0s' $(seq 1 $filled 2>/dev/null)   || true
  printf '%s' "${DIM}"
  printf '░%.0s' $(seq 1 $empty 2>/dev/null)     || true
  printf '%s %3d%%' "${RST}" "$pct"
}

# ═══════════════════════════════════════════════════════════════════════════════
# Usage
# ═══════════════════════════════════════════════════════════════════════════════
usage() {
  cat <<'EOF'
Usage: run-parallel-cmds.sh [OPTIONS] [--] "cmd1" "cmd2" ...
       run-parallel-cmds.sh [OPTIONS] -f commands.txt
       echo -e "cmd1\ncmd2" | run-parallel-cmds.sh [OPTIONS]

Options:
  -t, --timeout SEC       Timeout per command              (default: 30)
      --prepend STR       Prepend string to every command
      --append  STR       Append  string to every command
      --logs              Include stdout/stderr in output   (default: off)
      --tail N            Keep only last N log lines        (implies --logs)
  -e, --no-exit-code      Omit exit codes from output
      --format FMT        Output format: json | text        (default: json)
      --short             Minimal stdout; save full output to file
  -o, --output-file PATH  File path for --short mode        (default: $PWD/parallel-results.<ts>.<ext>)
  -j, --jobs N            Max parallel jobs                 (default: CPU count)
  -f, --file FILE         Read commands from file, one per line
      --no-color          Disable colored output
  -h, --help              Show this help

Examples:
  # Run three commands with 10s timeout, show logs
  run-parallel-cmds.sh -t 10 --logs "sleep 2 && echo ok" "false" "echo hi"

  # Prepend sudo to every command, text output
  run-parallel-cmds.sh --prepend sudo --format text "systemctl status nginx" "systemctl status redis"

  # Pipe commands, short output saved to file
  cat urls.txt | run-parallel-cmds.sh --prepend "curl -sS" --short -o results.json
EOF
}

# ═══════════════════════════════════════════════════════════════════════════════
# Parse arguments
# ═══════════════════════════════════════════════════════════════════════════════
while [[ $# -gt 0 ]]; do
  case "$1" in
    -t|--timeout)      TIMEOUT="$2";        shift 2 ;;
    --prepend)         PREPEND="$2";         shift 2 ;;
    --append)          APPEND="$2";          shift 2 ;;
    --logs)            SHOW_LOGS=true;       shift   ;;
    --tail)            TAIL_LINES="$2"; SHOW_LOGS=true; shift 2 ;;
    -e|--no-exit-code) SHOW_EXIT_CODE=false; shift   ;;
    --format)          FORMAT="$2";          shift 2 ;;
    --short)           SHORT_OUTPUT=true;    shift   ;;
    -o|--output-file)  OUTPUT_FILE="$2";     shift 2 ;;
    -j|--jobs)         MAX_JOBS="$2";        shift 2 ;;
    --no-color)        NO_COLOR=true;        shift   ;;
    -f|--file)
      while IFS= read -r _line; do
        [[ -z "$_line" || "$_line" =~ ^[[:space:]]*# ]] && continue
        COMMANDS+=("$_line")
      done < "$2"
      shift 2 ;;
    -h|--help) usage; exit 0 ;;
    --)        shift; COMMANDS+=("$@"); break ;;
    -*)        printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    *)         COMMANDS+=("$1"); shift ;;
  esac
done

# Read from stdin when no commands given and stdin is piped
if [[ ${#COMMANDS[@]} -eq 0 ]] && [[ ! -t 0 ]]; then
  while IFS= read -r _line; do
    [[ -z "$_line" || "$_line" =~ ^[[:space:]]*# ]] && continue
    COMMANDS+=("$_line")
  done
fi

# -o without --short implies --short
[[ -n "$OUTPUT_FILE" ]] && SHORT_OUTPUT=true

init_colors

# ═══════════════════════════════════════════════════════════════════════════════
# Validate
# ═══════════════════════════════════════════════════════════════════════════════
command -v parallel &>/dev/null || die "GNU parallel is required but not found.
  Install: apt install parallel | brew install parallel | pacman -S parallel"

[[ ${#COMMANDS[@]} -eq 0 ]] && { die "No commands provided. See --help."; }

case "$FORMAT" in
  json|text) ;;
  *) die "Unknown format '$FORMAT'. Use json or text." ;;
esac

# ═══════════════════════════════════════════════════════════════════════════════
# Prepare workspace
# ═══════════════════════════════════════════════════════════════════════════════
WORK_DIR=$(mktemp -d)
trap 'rm -rf "$WORK_DIR"' EXIT

JOBLOG="$WORK_DIR/joblog"
OUT_DIR="$WORK_DIR/out"
mkdir -p "$OUT_DIR"

# Build constructed commands (apply prepend / append)
declare -a CONSTRUCTED=()
for cmd in "${COMMANDS[@]}"; do
  built=""
  [[ -n "$PREPEND" ]] && built+="${PREPEND} "
  built+="$cmd"
  [[ -n "$APPEND" ]]  && built+=" ${APPEND}"
  CONSTRUCTED+=("$built")
done

TOTAL=${#CONSTRUCTED[@]}

# Write one script per command (avoids quoting issues in parallel)
for i in "${!CONSTRUCTED[@]}"; do
  printf '%s\n' "${CONSTRUCTED[$i]}" > "$WORK_DIR/cmd_$((i+1)).sh"
done

# Wrapper: runs a numbered command and captures stdout/stderr to files
cat > "$WORK_DIR/_run.sh" << 'WRAPPER'
#!/usr/bin/env bash
idx="$1"; dir="$2"
bash "$dir/cmd_${idx}.sh" \
  >"$dir/out/${idx}.stdout" \
  2>"$dir/out/${idx}.stderr"
WRAPPER
chmod +x "$WORK_DIR/_run.sh"

# ═══════════════════════════════════════════════════════════════════════════════
# Execute
# ═══════════════════════════════════════════════════════════════════════════════
printf '\n' >&2
printf '%s\n' \
  "${BLD}${CYN}▶ Running ${TOTAL} command(s) in parallel${RST}  ${DIM}timeout=${TIMEOUT}s${RST}" >&2
printf '%s\n' "${DIM}$(printf '─%.0s' $(seq 1 50))${RST}" >&2

# Assemble parallel flags
PARALLEL_ARGS=(
  --timeout "$TIMEOUT"
  --joblog  "$JOBLOG"
  --halt    never
)
[[ -t 2 ]] && PARALLEL_ARGS+=(--bar)
(( MAX_JOBS > 0 )) && PARALLEL_ARGS+=(-j "$MAX_JOBS")

START_EPOCH=$(date +%s)

seq 1 "$TOTAL" | parallel "${PARALLEL_ARGS[@]}" \
  "bash \"$WORK_DIR/_run.sh\" {} \"$WORK_DIR\"" || true

END_EPOCH=$(date +%s)
ELAPSED=$(( END_EPOCH - START_EPOCH ))

# ═══════════════════════════════════════════════════════════════════════════════
# Parse job log
# ═══════════════════════════════════════════════════════════════════════════════
declare -A EXIT_CODES=() SIGNALS=() JOB_TIMES=()
SUCCEEDED=0  FAILED=0  TIMED_OUT=0

while IFS=$'\t' read -r seq host starttime runtime send receive exitval signal _rest; do
  [[ "$seq" == "Seq" ]] && continue        # header row
  EXIT_CODES[$seq]="$exitval"
  SIGNALS[$seq]="$signal"
  JOB_TIMES[$seq]="$runtime"

  if [[ "$signal" -ne 0 ]]; then
    (( TIMED_OUT++ ));  (( FAILED++ ))
  elif [[ "$exitval" -ne 0 ]]; then
    (( FAILED++ ))
  else
    (( SUCCEEDED++ ))
  fi
done < "$JOBLOG"

# ═══════════════════════════════════════════════════════════════════════════════
# Collect logs for a command index (1-based)
# ═══════════════════════════════════════════════════════════════════════════════
get_logs() {
  local idx=$1 combined=""
  local f_out="$OUT_DIR/${idx}.stdout"
  local f_err="$OUT_DIR/${idx}.stderr"

  [[ -s "$f_out" ]] && combined=$(< "$f_out")
  if [[ -s "$f_err" ]]; then
    [[ -n "$combined" ]] && combined+=$'\n'
    combined+=$(< "$f_err")
  fi

  if (( TAIL_LINES > 0 )) && [[ -n "$combined" ]]; then
    combined=$(printf '%s' "$combined" | tail -n "$TAIL_LINES")
  fi

  printf '%s' "$combined"
}

# ═══════════════════════════════════════════════════════════════════════════════
# Format: JSON
# ═══════════════════════════════════════════════════════════════════════════════
format_json() {
  local buf
  buf=$'{\n  "results": [\n'

  local i
  for (( i = 1; i <= TOTAL; i++ )); do
    local cmd="${CONSTRUCTED[$((i-1))]}"
    local ec="${EXIT_CODES[$i]:-255}"
    local sig="${SIGNALS[$i]:-0}"
    local is_timeout="false"
    (( sig != 0 )) && is_timeout="true"

    buf+="    {"
    buf+=$'\n'"      \"command\": $(json_escape "$cmd")"

    if [[ "$SHOW_EXIT_CODE" == true ]]; then
      buf+=","$'\n'"      \"exit_code\": ${ec}"
      [[ "$is_timeout" == "true" ]] && \
        buf+=","$'\n'"      \"timed_out\": true"
    fi

    if [[ "$SHOW_LOGS" == true ]]; then
      local logs
      logs=$(get_logs "$i")
      buf+=","$'\n'"      \"logs\": $(json_escape "$logs")"
    fi

    buf+=$'\n'"    }"
    (( i < TOTAL )) && buf+=","
    buf+=$'\n'
  done

  buf+='  ],'$'\n'
  buf+='  "summary": {'$'\n'
  buf+="    \"total\": ${TOTAL},"$'\n'
  buf+="    \"succeeded\": ${SUCCEEDED},"$'\n'
  buf+="    \"failed\": ${FAILED},"$'\n'
  buf+="    \"timed_out\": ${TIMED_OUT},"$'\n'
  buf+="    \"elapsed\": \"$(fmt_elapsed "$ELAPSED")\","$'\n'
  buf+="    \"elapsed_seconds\": ${ELAPSED}"$'\n'
  buf+='  }'$'\n'
  buf+='}'

  printf '%s\n' "$buf"
}

# ═══════════════════════════════════════════════════════════════════════════════
# Format: text
# ═══════════════════════════════════════════════════════════════════════════════
format_text() {
  local buf="" i
  for (( i = 1; i <= TOTAL; i++ )); do
    local cmd="${CONSTRUCTED[$((i-1))]}"
    local ec="${EXIT_CODES[$i]:-255}"
    local sig="${SIGNALS[$i]:-0}"

    # Logs
    if [[ "$SHOW_LOGS" == true ]]; then
      local logs
      logs=$(get_logs "$i")
      [[ -n "$logs" ]] && buf+="${logs}"$'\n'
    fi

    # Exit code | command
    if [[ "$SHOW_EXIT_CODE" == true ]]; then
      if (( sig != 0 )); then
        buf+="${YLW}exit code: TIMEOUT${RST} | ${cmd}"$'\n'
      elif (( ec == 0 )); then
        buf+="${GRN}exit code: ${ec}${RST} | ${cmd}"$'\n'
      else
        buf+="${RED}exit code: ${ec}${RST} | ${cmd}"$'\n'
      fi
    else
      buf+="${cmd}"$'\n'
    fi

    buf+=$'\n'
  done

  # Summary
  buf+="${BLD}$(printf '─%.0s' $(seq 1 50))${RST}"$'\n'

  buf+="${BLD}Total:${RST} ${TOTAL}  "
  buf+="${GRN}Passed:${RST} ${SUCCEEDED}  "
  buf+="${RED}Failed:${RST} ${FAILED}"
  (( TIMED_OUT > 0 )) && buf+="  ${YLW}Timeout:${RST} ${TIMED_OUT}"
  buf+="  ${DIM}($(fmt_elapsed "$ELAPSED"))${RST}"$'\n'

  printf '%s\n' "$buf"
}

# ═══════════════════════════════════════════════════════════════════════════════
# Emit output
# ═══════════════════════════════════════════════════════════════════════════════
RESULT=""
if [[ "$FORMAT" == "json" ]]; then
  RESULT=$(format_json)
else
  RESULT=$(format_text)
fi

if [[ "$SHORT_OUTPUT" == true ]]; then
  # Determine output file path
  if [[ -z "$OUTPUT_FILE" ]]; then
    local_ext="json"
    [[ "$FORMAT" != "json" ]] && local_ext="txt"
    OUTPUT_FILE="${PWD}/parallel-results.$(date +%Y%m%d_%H%M%S).${local_ext}"
  fi

  # Strip ANSI when writing to file
  printf '%s\n' "$RESULT" | strip_ansi > "$OUTPUT_FILE"

  printf '%s\n' "${GRN}✓${RST} Results saved to ${BLD}${OUTPUT_FILE}${RST}" >&2

  # Short summary on stderr
  printf '%s' "${BLD}Total:${RST} ${TOTAL}  ${GRN}OK:${RST} ${SUCCEEDED}  ${RED}Fail:${RST} ${FAILED}" >&2
  (( TIMED_OUT > 0 )) && printf '  %s' "${YLW}Timeout:${RST} ${TIMED_OUT}" >&2
  printf '  %s\n' "${DIM}($(fmt_elapsed "$ELAPSED"))${RST}" >&2
else
  printf '%s\n' "$RESULT"
fi

# ── Footer with progress bar ─────────────────────────────────────────────────
printf '\n' >&2

if (( TOTAL > 0 )); then
  pct=$(( SUCCEEDED * 100 / TOTAL ))
  printf '  %s  ' "$(progress_bar "$pct" 30)" >&2
  printf '%s\n' "${DIM}${SUCCEEDED}/${TOTAL} succeeded${RST}" >&2
fi

printf '%s\n\n' \
  "${BLD}${CYN}■ Done${RST} — ${TOTAL} commands in $(fmt_elapsed "$ELAPSED")" >&2

# Exit non-zero if any command failed
(( FAILED > 0 )) && exit 1
exit 0
