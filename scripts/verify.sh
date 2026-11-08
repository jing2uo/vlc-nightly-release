#!/usr/bin/env bash
# Verification only: no source checkout, no VLC rebuild, no publication.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
work=${WORK_DIR:-$root/work}
arch=$(uname -m)
backend=auto
headless=false
candidate=
args=()
advanced=false
for option in "$@"; do
  case $option in
    --backend=*) backend=${option#*=};;
    --dist=*) candidate=$(realpath -- "${option#*=}");;
    --headless) headless=true;;
    --diagnostics|--desktop|--external|--trace-http) advanced=true; args+=("$option");;
    *) args+=("$option");;
  esac
done
if [[ $backend == auto ]]; then
  if command -v flatpak >/dev/null && [[ $headless == false ]]; then backend=host; else backend=podman; fi
fi
host_args=("${args[@]}")
container_args=("${args[@]}")
if [[ -n $candidate ]]; then
  host_args+=(--dist "$candidate")
  [[ $candidate == "$work/"* ]] || { echo "Candidate must be under WORK_DIR" >&2; exit 2; }
  container_args+=(--dist "/work/${candidate#"$work/"}")
fi
if [[ $backend == host ]]; then
  export VLC_VERIFY_BACKEND=host
  exec python3 "$root/verification/run.py" --work "$work" --arch "$arch" "${host_args[@]}"
fi
[[ $backend == podman ]] || { echo 'backend must be auto, host or podman' >&2; exit 2; }
mkdir -p "$work/verification/results"
# Smoke test with the already built orchestration image before longer setup.
# Namespace failures select host-managed Flatpak, never weaker sandbox flags.
if ! podman run --rm --userns=keep-id --cap-drop=ALL --security-opt 'unmask=/proc/*' \
  --security-opt label=disable --volume "$root:/recipe:ro" --volume "$work:/work" \
  --entrypoint /bin/bash localhost/vlc-nightly-builder -ec \
  "unshare --user --map-root-user true; python3 /recipe/verification/run.py --work /work --arch '$arch' --smoke-only" \
  > "$work/verification/results/podman-smoke.log" 2>&1; then
  echo 'Nested Flatpak smoke failed; trying host-managed Flatpak (see podman-smoke.log)' >&2
  command -v flatpak >/dev/null || { echo 'Host Flatpak unavailable; verification is blocked' >&2; exit 1; }
  export VLC_VERIFY_BACKEND=host-fallback
  exec python3 "$root/verification/run.py" --work "$work" --arch "$arch" "${host_args[@]}"
fi
image=localhost/vlc-nightly-builder
if [[ $advanced == true ]]; then
  if podman build -t localhost/vlc-nightly-verifier -f "$root/container/Verification.Containerfile" "$root/container"; then
    image=localhost/vlc-nightly-verifier
  else
    echo 'Optional diagnostic image setup failed; retaining core environment and recording available diagnostics' >&2
  fi
fi
exec podman run --rm --userns=keep-id --cap-drop=ALL --security-opt 'unmask=/proc/*' \
  --security-opt label=disable --volume "$root:/recipe:ro" --volume "$work:/work" \
  --env VLC_VERIFY_BACKEND=podman --entrypoint /bin/bash "$image" \
  /recipe/verification/headless.sh "$arch" "${container_args[@]}"
