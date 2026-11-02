#!/usr/bin/env bash
set -euo pipefail
script_dir=$(cd "$(dirname "$0")" && pwd)
payload=${1:?} arch=${2:?} version=${3:?}
name="vlc-$version-$arch.tar.zst"
cd "${DIST_DIR:-/work/dist}"
[[ ! -e $name && ! -e $name.sha256 && ! -e $name.size ]] || { echo "Refusing to replace an existing artifact" >&2; exit 1; }
# Stable archive order, ownership and timestamps; single compression thread.
tar --sort=name --mtime="@$SOURCE_DATE_EPOCH" --owner=0 --group=0 --numeric-owner \
  -C "$(dirname "$payload")" -I 'zstd -T1 -19' -cf "$name" extra
(( $(stat -c %s "$name") < 2147483648 ))
sha256sum "$name" > "$name.sha256"
stat -c '%s' "$name" > "$name.size"
# Real extraction, not just an archive listing; reclaim the duplicate afterwards.
check=$(mktemp -d "${EXTRACT_TMPDIR:-/work}/extract.XXXXXX")
trap 'rm -rf "$check"' EXIT
sha256sum -c "$name.sha256"
tar --zstd -xf "$name" -C "$check" --no-same-owner
"$script_dir/sanity.sh" "$check/extra" "$arch"
