#!/usr/bin/env bash
set -euo pipefail
mkdir -p /work/logs
{
  echo "stage=$1 utc=$(date -u +%FT%TZ)"
  df -Pk /work
  free -m
  for metric in memory.peak memory.events memory.max; do
    if [[ -r /sys/fs/cgroup/$metric ]]; then
      echo "$metric: $(cat "/sys/fs/cgroup/$metric")"
    fi
  done
  du -sk /work/source /work/deps /work/vlc-build /work/stage /work/dist /work/flatpak-data 2>/dev/null || true
} >> /work/logs/resources.log
# A planning budget, not a measured VLC requirement. Leave diagnostics and stop.
available=$(df -Pk /work | awk 'NR==2 {print $4}')
minimum=${MIN_FREE_KIB:-2097152}
if (( available < minimum )); then
  echo "Insufficient free disk: ${available} KiB; minimum ${minimum} KiB. See resources.log." >&2
  exit 1
fi
