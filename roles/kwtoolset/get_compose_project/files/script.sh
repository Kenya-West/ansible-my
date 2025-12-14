#!/usr/bin/env bash
# determine-compose-project-name.sh
#
# Outputs exactly ONE docker compose project name (no extra text) for the compose
# file(s) in the current directory. On any error, outputs nothing and exits with
# a non-zero status.
#
# Resolution order (best-effort):
#  1) Active Compose projects whose ConfigFiles match this directory (docker compose ls)
#  2) Compose-resolved name from `docker compose config` (works even if nothing is running)
#  3) Explicit COMPOSE_PROJECT_NAME from .env / env (if readable)
#  4) Fallback: sanitized directory name (only if no other method works)
#
# If multiple stacks match this directory (e.g., multiple projects share files or
# multiple -f combos), the script treats it as ambiguous and fails.

set -euo pipefail

# --- helpers ---
fail() { exit "${1:-1}"; }
is_cmd() { command -v "$1" >/dev/null 2>&1; }

# Strictly print one line (project name) and exit 0
ok() {
  # $1 = name
  [[ -n "${1:-}" ]] || fail 1
  printf '%s\n' "$1"
  exit 0
}

# Allow only compose project name charset Compose uses (libcompose-ish).
# (Compose mostly allows [a-z0-9][a-z0-9_-]*; we validate conservatively.)
valid_name() {
  local n="${1:-}"
  [[ -n "$n" ]] || return 1
  [[ "$n" =~ ^[a-z0-9][a-z0-9_-]*$ ]]
}

# Normalize directory fallback same as Compose "project from dir":
# lower-case and replace anything not [a-z0-9] with nothing? Compose sanitization
# can vary slightly; this is conservative and stable.
dir_fallback_name() {
  local base
  base="$(basename "$(pwd)")"
  # lower-case
  base="$(printf '%s' "$base" | tr '[:upper:]' '[:lower:]')"
  # replace invalid chars with nothing, then trim leading non-alnum
  base="$(printf '%s' "$base" | sed -E 's/[^a-z0-9_-]+//g; s/^[^a-z0-9]+//')"
  printf '%s' "$base"
}

# Read COMPOSE_PROJECT_NAME from .env if present
read_env_file_name() {
  [[ -r .env ]] || return 1
  # Support lines like: COMPOSE_PROJECT_NAME=foo  (optionally quoted)
  local v
  v="$(
    awk -F= '
      /^[[:space:]]*COMPOSE_PROJECT_NAME[[:space:]]*=/ {
        $1=""; sub(/^=/,""); gsub(/^[[:space:]]+|[[:space:]]+$/,"");
        # strip surrounding quotes
        gsub(/^'\''|'\''$/,""); gsub(/^"|"$/,"");
        print; exit
      }' .env
  )"
  [[ -n "$v" ]] && printf '%s' "$v"
}

# --- preconditions ---
# docker compose must exist for the best methods
if ! is_cmd docker; then
  fail 127
fi

# Prefer Compose v2 plugin (`docker compose ...`)
if ! docker compose version >/dev/null 2>&1; then
  # Fallback to legacy `docker-compose` if present
  if ! is_cmd docker-compose; then
    fail 127
  fi
fi

PWD_ABS="$(pwd)"

# Determine candidate compose config file(s) in this dir (most common names).
# We do NOT try to emulate all file discovery rules; instead we use directory
# matching for `ls` and `docker compose config` for canonical resolution.
CANDIDATE_FILES=()
for f in docker-compose.yml docker-compose.yaml compose.yml compose.yaml; do
  [[ -f "$f" ]] && CANDIDATE_FILES+=("$PWD_ABS/$f")
done

# If no compose file exists here, it's an error for this script’s purpose.
if [[ "${#CANDIDATE_FILES[@]}" -eq 0 ]]; then
  fail 2
fi

# --- method 1: match running stacks via docker compose ls (by ConfigFiles) ---
# This handles "multiple stacks spinned up": we match all compose projects whose
# ConfigFiles include files in this directory.
#
# NOTE: docker compose ls --format json schema typically includes Name, Status, ConfigFiles.
# ConfigFiles may be a comma-separated list.
if docker compose ls --format json >/dev/null 2>&1 && is_cmd jq; then
  names="$(
    docker compose ls --format json \
    | jq -r --arg dir "$PWD_ABS/" '
        .[]
        | select(.ConfigFiles? != null)
        | select(
            (.ConfigFiles | split(",") | map(gsub("^\\s+|\\s+$";"")))
            | any(startswith($dir))
          )
        | .Name
      ' \
    | awk 'NF' \
    | sort -u
  )"

  # If exactly one matching running project, return it
  if [[ -n "$names" ]]; then
    count="$(printf '%s\n' "$names" | wc -l | tr -d ' ')"
    if [[ "$count" -eq 1 ]]; then
      n="$names"
      if valid_name "$n"; then ok "$n"; fi
      # If somehow invalid, treat as error
      fail 3
    else
      # Ambiguous: multiple projects in this directory
      fail 4
    fi
  fi
fi

# --- method 2: canonical compose-resolved name via `docker compose config` ---
# Works even if the stack is not running. Honors:
#   -p, COMPOSE_PROJECT_NAME, .env, etc.
#
# We run it in the current directory, with default file selection.
if docker compose version >/dev/null 2>&1; then
  # Use `docker compose config` (v2). It prints "name: <project>" at the top.
  name="$(
    docker compose config 2>/dev/null \
    | awk '/^name:[[:space:]]*/ {print $2; exit}'
  )"
  if valid_name "$name"; then
    ok "$name"
  fi
else
  # Legacy docker-compose
  name="$(
    docker-compose config 2>/dev/null \
    | awk '/^name:[[:space:]]*/ {print $2; exit}'
  )"
  if valid_name "$name"; then
    ok "$name"
  fi
fi

# --- method 3: read COMPOSE_PROJECT_NAME from env / .env directly ---
# Environment variable takes precedence over .env file.
if [[ -n "${COMPOSE_PROJECT_NAME:-}" ]]; then
  if valid_name "$COMPOSE_PROJECT_NAME"; then ok "$COMPOSE_PROJECT_NAME"; fi
  fail 5
fi

envfile_name="$(read_env_file_name || true)"
if [[ -n "$envfile_name" ]]; then
  if valid_name "$envfile_name"; then ok "$envfile_name"; fi
  fail 6
fi

# --- method 4: directory fallback (last resort) ---
fallback="$(dir_fallback_name)"
if valid_name "$fallback"; then
  ok "$fallback"
fi

fail 7
