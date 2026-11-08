#!/usr/bin/env bash
set -euo pipefail
script_dir=$(cd "$(dirname "$0")" && pwd)
payload=${1:?} arch=${2:?} version=${3:?}
name="vlc-$version-$arch.tar.zst"
cd "${DIST_DIR:-/work/dist}"
[[ ! -e $name && ! -e $name.sha256 && ! -e $name.size ]] || { echo "Refusing to replace an existing artifact" >&2; exit 1; }
# Strip only staged ELF executables/shared objects, including copied contrib
# libraries and VLC plugins. --strip-unneeded retains dynamic runtime symbols.
python3 - "$payload" <<'PYSTRIP'
from pathlib import Path
import subprocess
import sys

for path in sorted(Path(sys.argv[1]).rglob('*')):
    if path.is_symlink() or not path.is_file():
        continue
    with path.open('rb') as file:
        header = file.read(18)
    if header[:4] != b'\x7fELF':
        continue
    if len(header) < 18 or header[5] not in (1, 2):
        raise ValueError(f'Invalid ELF header: {path}')
    kind = int.from_bytes(header[16:18], 'little' if header[5] == 1 else 'big')
    if kind in (2, 3):  # ET_EXEC and ET_DYN (shared objects and PIE executables).
        subprocess.run(['strip', '--strip-unneeded', str(path)], check=True)
PYSTRIP
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
