#!/usr/bin/env bash
# Retry the identical download command; retain Flatpak's partial OSTree objects.
retry_download() {
  local attempt status
  for attempt in 1 2 3; do
    if "$@"; then return 0; else status=$?; fi
    if (( attempt == 3 )); then
      echo "Download failed after 3 attempts (exit $status): $1" >&2
      return "$status"
    fi
    echo "Download attempt $attempt failed (exit $status); retrying in $((attempt * 5))s: $1" >&2
    sleep "$((attempt * 5))"
  done
}
