#!/usr/bin/env bash
set -euo pipefail
source /recipe/scripts/download-retry.sh
mkdir -p /work/logs /work/cache
umask 022
# Preserve prior stage logs before a new resolve/build attempt, including failures.
if [[ -n $(find /work/logs -maxdepth 1 -type f -print -quit) ]]; then
  mkdir -p /work/logs/history
  previous=$(mktemp -d /work/logs/history/previous.XXXXXX)
  find /work/logs -maxdepth 1 -type f -exec mv -t "$previous" -- {} +
fi
exec > >(tee -a /work/logs/environment.log) 2>&1
mode=${1:-build}
shift || true
retry_download flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
if [[ $mode == resolve ]]; then
  exec /recipe/scripts/resolve.sh "${1:-}"
fi
[[ $mode == build ]] || { echo "Expected resolve or build" >&2; exit 2; }
arch=${1:?architecture required}
[[ $(uname -m) == "$arch" ]] || { echo "Native architecture mismatch" >&2; exit 1; }
python3 /recipe/scripts/metadata.py env /work/inputs.json "$arch" > /work/input.env
source /work/input.env
if [[ ! -d /work/source/.git ]]; then
  git clone --filter=blob:none --no-checkout https://code.videolan.org/videolan/vlc.git /work/source
fi
git -C /work/source fetch --tags origin master
git -C /work/source merge-base --is-ancestor "$VLC_SHA" origin/master
git -C /work/source checkout --detach "$VLC_SHA"
python3 /recipe/scripts/metadata.py check /work/inputs.json
# Install into the mounted user installation, never the Fedora host installation.
for component in Sdk Platform; do
  ref="org.kde.$component/$arch/6.11"
  if ! flatpak info --user "$ref" >/dev/null 2>&1; then
    retry_download flatpak install --user --noninteractive --assumeyes --no-related flathub "$ref"
  fi
  if [[ $component == Sdk ]]; then commit=$SDK_COMMIT; else commit=$RUNTIME_COMMIT; fi
  if [[ $(flatpak info --user --show-commit "$ref") != "$commit" ]]; then
    retry_download flatpak update --user --noninteractive --assumeyes --no-related --commit="$commit" "$ref"
  fi
  [[ $(flatpak info --user --show-commit "$ref") == "$commit" ]]
done
python3 /recipe/scripts/qt_identity.py --repo "${XDG_DATA_HOME}/flatpak/repo" \
  --arch "$arch" --sdk "$SDK_COMMIT" --platform "$RUNTIME_COMMIT" \
  --check-inputs /work/inputs.json --output /work/logs/qt-deployed.json
runtime_root=$(flatpak info --user --show-location "org.kde.Platform/$arch/6.11")/files
/recipe/scripts/resources.sh sdk-installed
if [[ ! -f /work/sandbox/metadata ]]; then
  flatpak build-init --arch="$arch" /work/sandbox org.flatpark.VLCBuild org.kde.Sdk org.kde.Platform 6.11
fi
# No host /usr or host pkg-config paths are exposed inside the SDK sandbox.
# Keep Flatpak's sandbox; do not use --privileged or a host compiler fallback.
exec flatpak build --die-with-parent --share=network --filesystem=/work \
  --filesystem="$runtime_root:ro" \
  --filesystem=/recipe:ro --env=TARGET_RUNTIME_ROOT="$runtime_root" --env=JOBS="${JOBS:-2}" \
  --env=GITHUB_RUN_ID="${GITHUB_RUN_ID:-local}" \
  --env=GITHUB_REPOSITORY="${GITHUB_REPOSITORY:-local}" \
  --env=GITHUB_SHA="${GITHUB_SHA:-local}" \
  /work/sandbox /bin/bash /recipe/scripts/build.sh "$arch"
