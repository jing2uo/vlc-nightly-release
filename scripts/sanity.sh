#!/usr/bin/env bash
set -euo pipefail
payload=${1:?payload required}
arch=${2:?architecture required}
test -x "$payload/bin/vlc"
test -x "$payload/lib/vlc/vlc-cache-gen"
for library in libvlc libvlccore; do
  test -n "$(find "$payload/lib" -maxdepth 1 -name "$library.so.*" -print -quit)"
done
for dir in lib/vlc/plugins share/vlc share/locale; do test -d "$payload/$dir"; done
for plugin in libqt_plugin.so libavcodec_plugin.so; do
  test -n "$(find "$payload/lib/vlc/plugins" -name "$plugin" -print -quit)"
done
case $arch in x86_64) machine='Advanced Micro Devices X86-64';; aarch64) machine=AArch64;; *) exit 2;; esac
while IFS= read -r -d '' binary; do
  if [[ $(od -An -N4 -t x1 "$binary" | tr -d '[:space:]') == 7f454c46 ]]; then
    readelf -h "$binary" | grep -F "Machine:" | grep -Fq "$machine"
  fi
done < <(find "$payload" -type f -print0)
