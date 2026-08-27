#!/bin/sh

# This script installs Eget.

# Acknowledgments:
#   - zyedidia.github.io: https://github.com/zyedidia/eget
#   - inhere: https://github.com/inhere
#   - getmic.ro: https://github.com/benweissmann/getmic.ro

#!/usr/bin/env sh
set -eu

repo="inherelab/eget"
bin="eget"
install_dir="${EGET_INSTALL_DIR:-$HOME/.local/bin}"

os="$(uname -s | tr '[:upper:]' '[:lower:]')"
arch="$(uname -m)"

case "$os" in
  linux|darwin) ;;
  *) echo "unsupported OS: $os" >&2; exit 1 ;;
esac

case "$arch" in
  x86_64|amd64) arch="amd64" ;;
  arm64|aarch64) arch="arm64" ;;
  *) echo "unsupported arch: $arch" >&2; exit 1 ;;
esac

asset="$bin-$os-$arch.tar.gz"
url="https://github.com/$repo/releases/latest/download/$asset"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT INT TERM

mkdir -p "$install_dir"
if command -v curl >/dev/null 2>&1; then
  curl -fsSL "$url" -o "$tmp/$asset"
elif command -v wget >/dev/null 2>&1; then
  wget -q "$url" -O "$tmp/$asset"
else
  echo "curl or wget is required" >&2
  exit 1
fi

tar -xzf "$tmp/$asset" -C "$tmp"
install -m 755 "$tmp/$bin-$os-$arch" "$install_dir/$bin"

echo "installed $bin to $install_dir/$bin"
case ":$PATH:" in
  *":$install_dir:"*) ;;
  *) echo "add $install_dir to PATH to run $bin from anywhere" ;;
esac
