#!/usr/bin/env bash
set -euo pipefail
pin=${1:-}
[[ -z $pin || $pin =~ ^[0-9a-f]{40}$ ]] || { echo 'Use a full 40-character SHA' >&2; exit 2; }
if [[ ! -d /work/source/.git ]]; then
  git clone --filter=blob:none https://code.videolan.org/videolan/vlc.git /work/source
fi
cd /work/source
git fetch --tags origin master
sha=${pin:-$(git rev-parse FETCH_HEAD)}
git cat-file -e "$sha^{commit}"
git merge-base --is-ancestor "$sha" origin/master
# Full history and annotated tags are required for upstream's nightly version.
git checkout --detach "$sha"
version=$(git describe --always HEAD)
[[ $version =~ ^4\.0\.0-dev-[0-9]+-g[0-9a-f]+$ ]] || {
  echo "Unexpected upstream nightly version: $version" >&2; exit 1;
}
export VLC_SHA=$sha VLC_VERSION=$version
for arch in x86_64 aarch64; do
  for component in Sdk Platform; do
    flatpak remote-info --user --arch="$arch" --show-commit flathub "org.kde.$component//6.11" > "/work/$component-$arch.commit"
  done
  python3 /recipe/scripts/qt_identity.py --repo "${XDG_DATA_HOME}/flatpak/repo" \
    --arch "$arch" --sdk "$(cat "/work/Sdk-$arch.commit")" \
    --platform "$(cat "/work/Platform-$arch.commit")" --pull --output "/work/qt-$arch.json"
done
python3 /recipe/scripts/metadata.py resolve /work/inputs.json
