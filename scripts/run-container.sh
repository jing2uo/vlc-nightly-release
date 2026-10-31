#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
work=${WORK_DIR:-$root/work}
mkdir -p "$work"
work=$(cd "$work" && pwd)
# The same paths are used locally and in Actions: cached build files contain them.
podman build -t localhost/vlc-nightly-builder -f "$root/container/Containerfile" "$root/container"
# Bubblewrap's proc mount needs an unmasked parent proc. On Fedora SELinux
# also denies that nested mount; disable labels for this one rootless container.
# Keep seccomp, namespaces and capability drops. See docs/phase-1-report.md.
exec podman run --rm --userns=keep-id --cap-drop=ALL \
  --security-opt 'unmask=/proc/*' --security-opt label=disable \
  --volume "$root:/recipe:ro" --volume "$work:/work" \
  --env JOBS="${JOBS:-2}" --env GITHUB_RUN_ID="${GITHUB_RUN_ID:-local}" \
  --env GITHUB_REPOSITORY="${GITHUB_REPOSITORY:-local}" \
  --env GITHUB_SHA="${GITHUB_SHA:-local}" \
  localhost/vlc-nightly-builder "$@"
