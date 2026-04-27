#!/usr/bin/env bash
set -euo pipefail

SCRIPT_NAME="$(basename "$0")"

CONFIG_FILE=""
VERBOSE=0

log() {
  local level="$1"; shift
  local ts
  ts="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

  [[ "$level" == "DEBUG" && "$VERBOSE" -lt 1 ]] && return 0
  printf '%s [%s] %s\n' "$ts" "$level" "$*" >&2
}

die() {
  log "ERROR" "$*"
  exit 1
}

usage() {
  cat <<EOF
Usage:
  $SCRIPT_NAME --config <path> [--verbose]

Options:
  --config <path>   Path to Bash-native config file
  --verbose         Enable verbose logging
  --help            Show help
EOF
}

expand_path() {
  local path="$1"
  case "$path" in
    "~") printf '%s\n' "$HOME" ;;
    "~/"*) printf '%s/%s\n' "$HOME" "${path#"~/"}" ;;
    *) printf '%s\n' "$path" ;;
  esac
}

git_ssh() {
  local ssh_key="$1"
  shift

  ssh_key="$(expand_path "$ssh_key")"

  [[ -f "$ssh_key" ]] || die "SSH key does not exist: $ssh_key"

  GIT_SSH_COMMAND="ssh -i $ssh_key -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new" \
    git "$@"
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --config)
        [[ $# -ge 2 ]] || die "--config requires a path"
        CONFIG_FILE="$2"
        shift 2
        ;;
      --verbose)
        VERBOSE=$((VERBOSE + 1))
        shift
        ;;
      --help|-h)
        usage
        exit 0
        ;;
      *)
        die "Unknown argument: $1"
        ;;
    esac
  done
}

load_config() {
  [[ -n "$CONFIG_FILE" ]] || die "Missing --config <path>"
  [[ -f "$CONFIG_FILE" ]] || die "Config file does not exist: $CONFIG_FILE"

  # shellcheck source=/dev/null
  source "$CONFIG_FILE"

  : "${SOURCE_URL:?SOURCE_URL is required}"
  : "${DESTINATIONS:?DESTINATIONS array is required}"

  SOURCE_BRANCH="${SOURCE_BRANCH:-}"
  SOURCE_SSH_KEY="${SOURCE_SSH_KEY:-${GLOBAL_SSH_KEY:-$HOME/.ssh/id_rsa}}"
  GLOBAL_SSH_KEY="${GLOBAL_SSH_KEY:-$HOME/.ssh/id_rsa}"

  WORK_MODE="${WORK_MODE:-temp}"
  WORK_DIR="${WORK_DIR:-}"

  MIRROR_TAGS="${MIRROR_TAGS:-true}"
  PUSH_FORCE="${PUSH_FORCE:-false}"

  if [[ "$WORK_MODE" != "temp" && "$WORK_MODE" != "persistent" ]]; then
    die "WORK_MODE must be either 'temp' or 'persistent'"
  fi

  if [[ "$WORK_MODE" == "persistent" && -z "$WORK_DIR" ]]; then
    die "WORK_DIR is required when WORK_MODE=persistent"
  fi
}

prepare_workdir() {
  if [[ "$WORK_MODE" == "temp" ]]; then
    WORK_DIR="$(mktemp -d)"
    CLEANUP_WORK_DIR=true
  else
    WORK_DIR="$(expand_path "$WORK_DIR")"
    mkdir -p "$WORK_DIR"
    CLEANUP_WORK_DIR=false
  fi

  REPO_DIR="$WORK_DIR/repo"

  log "INFO" "Work mode: $WORK_MODE"
  log "INFO" "Work directory: $WORK_DIR"
}

cleanup() {
  if [[ "${CLEANUP_WORK_DIR:-false}" == "true" && -n "${WORK_DIR:-}" && -d "$WORK_DIR" ]]; then
    log "DEBUG" "Cleaning temporary work directory: $WORK_DIR"
    rm -rf "$WORK_DIR"
  fi
}

set_safe_directory() {
  # Git 2.35+ requires explicitly marking directories as safe when running as root
  # or when the directory is owned by a different user. We mark the repo directory
  # as safe to avoid issues in those cases.
  if git -C "$REPO_DIR" config --global --get safe.directory >/dev/null 2>&1; then
    log "DEBUG" "Git safe.directory already configured globally"
  else
    log "DEBUG" "Configuring Git safe.directory for work directory: $REPO_DIR"
    git config --global --add safe.directory "$REPO_DIR"
  fi
}

clone_or_update_source() {
  if [[ -d "$REPO_DIR/.git" ]]; then
    log "INFO" "Updating existing local repository"

    git -C "$REPO_DIR" remote set-url origin "$SOURCE_URL"

    git_ssh "$SOURCE_SSH_KEY" \
      -C "$REPO_DIR" fetch origin --prune --tags

    if [[ -n "$SOURCE_BRANCH" ]]; then
      git_ssh "$SOURCE_SSH_KEY" \
        -C "$REPO_DIR" checkout "$SOURCE_BRANCH"

      git_ssh "$SOURCE_SSH_KEY" \
        -C "$REPO_DIR" reset --hard "origin/$SOURCE_BRANCH"
    else
      local current_branch
      current_branch="$(git -C "$REPO_DIR" rev-parse --abbrev-ref HEAD)"

      git_ssh "$SOURCE_SSH_KEY" \
        -C "$REPO_DIR" reset --hard "origin/$current_branch"
    fi
  else
    log "INFO" "Cloning source repository: $SOURCE_URL"

    if [[ -n "$SOURCE_BRANCH" ]]; then
      git_ssh "$SOURCE_SSH_KEY" \
        clone --origin origin --branch "$SOURCE_BRANCH" "$SOURCE_URL" "$REPO_DIR"
    else
      git_ssh "$SOURCE_SSH_KEY" \
        clone --origin origin "$SOURCE_URL" "$REPO_DIR"
    fi
  fi
}

get_dest_var() {
  local dest_name="$1"
  local suffix="$2"
  local var_name="DEST_${dest_name}_${suffix}"

  printf '%s' "${!var_name-}"
}

push_destination() {
  local dest_name="$1"

  local dest_url
  local dest_branch
  local dest_ssh_key
  local remote_name
  local push_args=()

  dest_url="$(get_dest_var "$dest_name" "URL")"
  dest_branch="$(get_dest_var "$dest_name" "BRANCH")"
  dest_ssh_key="$(get_dest_var "$dest_name" "SSH_KEY")"

  [[ -n "$dest_url" ]] || {
    log "ERROR" "Destination '$dest_name' has no DEST_${dest_name}_URL"
    return 1
  }

  dest_branch="${dest_branch:-${SOURCE_BRANCH:-}}"
  dest_ssh_key="${dest_ssh_key:-$GLOBAL_SSH_KEY}"
  remote_name="dest_${dest_name}"

  log "INFO" "Pushing destination '$dest_name': $dest_url"

  git -C "$REPO_DIR" remote remove "$remote_name" >/dev/null 2>&1 || true
  git -C "$REPO_DIR" remote add "$remote_name" "$dest_url"

  if [[ "$PUSH_FORCE" == "true" ]]; then
    push_args+=(--force)
  fi

  if [[ -n "$dest_branch" ]]; then
    push_args+=(HEAD:"$dest_branch")
  else
    push_args+=(--all)
  fi

  if git_ssh "$dest_ssh_key" -C "$REPO_DIR" push "$remote_name" "${push_args[@]}"; then
    if [[ "$MIRROR_TAGS" == "true" ]]; then
      git_ssh "$dest_ssh_key" -C "$REPO_DIR" push "$remote_name" --tags || {
        log "ERROR" "Destination '$dest_name': branch push succeeded, tag push failed"
        return 1
      }
    fi

    log "INFO" "Destination '$dest_name': push succeeded"
    return 0
  else
    log "ERROR" "Destination '$dest_name': push failed"
    return 1
  fi
}

main() {
  parse_args "$@"

  command -v git >/dev/null 2>&1 || die "Required command not found: git"
  command -v date >/dev/null 2>&1 || die "Required command not found: date"
  command -v mktemp >/dev/null 2>&1 || die "Required command not found: mktemp"

  load_config
  prepare_workdir

  trap cleanup EXIT

  log "INFO" "Git mirror run started"

  set_safe_directory

  clone_or_update_source

  local success_count=0
  local failure_count=0
  local dest

  for dest in "${DESTINATIONS[@]}"; do
    if push_destination "$dest"; then
      success_count=$((success_count + 1))
    else
      failure_count=$((failure_count + 1))
    fi
  done

  log "INFO" "Git mirror run finished: success=$success_count failure=$failure_count"

  [[ "$failure_count" -eq 0 ]] || exit 2
}

main "$@"