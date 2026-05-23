#!/bin/sh

# This script installs Eget.

# Acknowledgments:
#   - zyedidia.github.io: https://github.com/zyedidia/eget
#   - getmic.ro: https://github.com/benweissmann/getmic.ro

set -e -u

githubLatestTag() {
  finalUrl=$(curl "https://github.com/$1/releases/latest" -s -L -I -o /dev/null -w '%{url_effective}')
  printf "%s\n" "${finalUrl##*v}"
}

platform=''
machine=$(uname -m)

if [ "${GETEGET_PLATFORM:-x}" != "x" ]; then
  platform="$GETEGET_PLATFORM"
else
  case "$(uname -s | tr '[:upper:]' '[:lower:]')" in
    "linux")
      case "$machine" in
        "arm64"* | "aarch64"* ) platform='linux-arm64' ;;
        "arm"* | "aarch"*) platform='linux-arm' ;;
        *"86") platform='linux-386' ;;
        *"64") platform='linux-amd64' ;;
      esac
      ;;
    "darwin")
      case "$machine" in
        "arm64"* | "aarch64"* ) platform='darwin-arm64' ;;
        *"64") platform='darwin-amd64' ;;
      esac
      ;;
    "msys"*|"cygwin"*|"mingw"*|*"_nt"*|"win"*)
      case "$machine" in
        *"86") platform='windows-386' ;;
        *"64") platform='windows-amd64' ;;
      esac
      ;;
  esac
fi

if [ "x$platform" = "x" ]; then
  cat << 'EOM'
/=====================================\\
|      COULD NOT DETECT PLATFORM      |
\\=====================================/
Uh oh! We couldn't automatically detect your operating system.
To continue with installation, please choose from one of the following values:
- linux-arm
- linux-arm64
- linux-386
- linux-amd64
- darwin-amd64
- darwin-arm64
- windows-386
- windows-amd64
Export your selection as the GETEGET_PLATFORM environment variable, and then
re-run this script.
EOM
  exit 1
else
  printf "Detected platform: %s\n" "$platform"
fi

TAG=$(githubLatestTag inherelab/eget)

if [ "x$platform" = "xwindows-amd64" ] || [ "x$platform" = "xwindows-386" ]; then
  extension='zip'
else
  extension='tar.gz'
fi

printf "Latest Version: %s\n" "$TAG"
printf "Downloading https://github.com/inherelab/eget/releases/download/v%s/eget-%s.%s\n" "$TAG" "$platform" "$extension"

url_with_ext="https://github.com/inherelab/eget/releases/download/v$TAG/eget-$platform.$extension"
url_noext="https://github.com/inherelab/eget/releases/download/v$TAG/eget-$platform"

# Use secure temp files in /tmp so we never clobber files in cwd
tmp_with_ext="$(mktemp /tmp/eget.XXXXXX)"
tmp_noext="$(mktemp /tmp/eget.XXXXXX)"
downloaded=""

if curl -fL "$url_with_ext" -o "$tmp_with_ext"; then
  downloaded="$tmp_with_ext"
else
  printf "Download with extension failed; trying without extension...\n"
  if curl -fL "$url_noext" -o "$tmp_noext"; then
    downloaded="$tmp_noext"
    # leave extension as-is; we'll detect archive type below
  else
    echo "Failed to download from $url_with_ext or $url_noext"
    rm -f "$tmp_with_ext" "$tmp_noext"
    exit 1
  fi
fi

# Create a temporary extraction directory
tmpdir="$(mktemp -d /tmp/eget-extract.XXXXXX)"

# Determine whether the downloaded file is a tar.gz, zip, or a raw binary.
if tar -tzf "$downloaded" >/dev/null 2>&1; then
  tar -xzf "$downloaded" -C "$tmpdir"
  found="$(find "$tmpdir" -type f -name 'eget' -print -quit || true)"
elif unzip -l "$downloaded" >/dev/null 2>&1; then
  unzip -q "$downloaded" -d "$tmpdir"
  found="$(find "$tmpdir" -type f -name 'eget' -print -quit || true)"
else
  # Not an archive: treat as binary
  found=""
fi

if [ -n "$found" ]; then
  mv "$found" ./eget
elif [ -s "$downloaded" ]; then
  # downloaded file is non-empty and not an archive -> assume it's the binary
  mv "$downloaded" ./eget
else
  echo "Downloaded file is empty or no executable found inside archive"
  rm -f "$tmp_with_ext" "$tmp_noext"
  rm -rf "$tmpdir"
  exit 1
fi

rm -f "$tmp_with_ext" "$tmp_noext"
rm -rf "$tmpdir"
chmod +x ./eget

cat <<-'EOM'
Eget has been downloaded to the current directory.
You can run it with:
./eget
EOM
