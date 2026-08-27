#!/usr/bin/env bash

set -euo pipefail

DEFAULT_EGET_CONFIG="${HOME}/.config/eget/eget.toml"
DEFAULT_INSTALLED_CONFIG="${HOME}/.config/eget/installed.toml"

usage() {
  cat <<EOF
Usage:
  $(basename "$0") [eget.toml] [installed.toml]

Defaults:
  eget.toml      -> ${DEFAULT_EGET_CONFIG}
  installed.toml -> ${DEFAULT_INSTALLED_CONFIG}
EOF
}

if [[ "${1:-}" =~ ^(-h|--help)$ ]]; then
  usage
  exit 0
fi

EGET_CONFIG="${1:-$DEFAULT_EGET_CONFIG}"
INSTALLED_CONFIG="${2:-$DEFAULT_INSTALLED_CONFIG}"

[[ -f "$EGET_CONFIG" ]] || {
  echo "ERROR: eget config not found: $EGET_CONFIG" >&2
  exit 1
}

[[ -f "$INSTALLED_CONFIG" ]] || {
  echo "ERROR: installed config not found: $INSTALLED_CONFIG" >&2
  exit 1
}

wanted="$(
  yq -p=toml -o=json -r '
    .packages
    | to_entries
    | .[]
    | (.value.name // .key)
  ' "$EGET_CONFIG" \
  | sort -u
)"

installed="$(
  yq -p=toml -o=json -r '
    .installed
    | to_entries
    | .[]
    | [
        .key,
        .value.tool,
        (.value.extracted_files[]? | split("/") | .[-1])
      ]
    | .[]
    | select(. != null)
  ' "$INSTALLED_CONFIG" \
  | sort -u
)"

missing="$(
  comm -23 \
    <(printf "%s\n" "$wanted") \
    <(printf "%s\n" "$installed")
)"

if [[ -n "$missing" ]]; then
  echo "Missing packages:"
  printf '%s\n' "$missing" | sed 's/^/  - /'
  exit 1
fi

echo "All packages from eget.toml are present in installed.toml"