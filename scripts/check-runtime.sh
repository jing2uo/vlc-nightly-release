#!/usr/bin/env bash
# Metadata/Qt-object inspection only: no SDK deployment, compiler or VLC rebuild.
set -euo pipefail
if [[ ${1:-} != --inside ]]; then
  mode=${2:-}
  root=$(cd "$(dirname "$0")/.." && pwd)
  candidate=$(realpath -- "${1:?candidate directory}")
  work=$(realpath -m -- "${WORK_DIR:-$root/work}")
  mkdir -p "$work/logs"
  if [[ -f $work/inputs.json ]]; then
    cmp "$candidate/inputs.json" "$work/inputs.json" || {
      echo 'Use a separate WORK_DIR: existing inputs differ' >&2; exit 1;
    }
  else
    cp "$candidate/inputs.json" "$work/inputs.json"
  fi
  podman build -t localhost/vlc-nightly-builder -f "$root/container/Containerfile" "$root/container"
  podman run --rm --userns=keep-id --cap-drop=ALL --security-opt 'unmask=/proc/*' --security-opt label=disable \
    --volume "$root:/recipe:ro" --volume "$work:/work" --entrypoint /bin/bash localhost/vlc-nightly-builder \
    /recipe/scripts/check-runtime.sh --inside "$mode"
  cp "$work/logs/current-runtime.json" "$candidate/current-runtime.json"
  if [[ $mode == --watch ]]; then
    python3 - "$candidate/current-runtime.json" <<'PYOUT'
import json,os,sys
result=json.load(open(sys.argv[1]))
line='changed='+str(result['changed']).lower()
print(line)
with open(os.environ['GITHUB_OUTPUT'],'a') as output:print(line,file=output)
PYOUT
  fi
  exit 0
fi
source /recipe/scripts/download-retry.sh
retry_download flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
for arch in x86_64 aarch64; do
  sdk=$(flatpak remote-info --user --arch="$arch" --show-commit flathub org.kde.Sdk//6.11)
  platform=$(flatpak remote-info --user --arch="$arch" --show-commit flathub org.kde.Platform//6.11)
  python3 /recipe/scripts/qt_identity.py --repo "${XDG_DATA_HOME}/flatpak/repo" --arch "$arch" \
    --sdk "$sdk" --platform "$platform" --pull --output "/work/logs/current-$arch.json"
done
python3 - "${2:-}" <<'PY'
from datetime import datetime,timezone
import json,sys
from pathlib import Path
sys.path.insert(0,'/recipe/scripts')
from qt_identity import release_identity,validate_inputs
lock=json.load(open('/work/inputs.json'))
snapshots={a:json.load(open('/work/logs/current-'+a+'.json')) for a in ('x86_64','aarch64')}
for arch,snapshot in snapshots.items():validate_inputs(snapshot,arch,snapshot['deployments'])
current_identity=release_identity(snapshots)
changed=current_identity!=lock['qt_abi_identity']
print('Production Qt identity: '+lock['qt_abi_identity'])
print('Current Qt identity: '+current_identity)
print('Decision: '+('rebuild both architectures' if changed else 'unchanged Qt content; skip rebuild'))
if sys.argv[1]!='--watch':
    assert not changed, 'Current Qt content changed: rebuild/verify; do not promote stale binaries'
Path('/work/logs/current-runtime.json').write_text(json.dumps(dict(schema=1,
    changed=changed,checked_at=datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),qt_abi=snapshots),indent=2)+'\n')
PY
