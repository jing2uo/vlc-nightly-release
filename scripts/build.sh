#!/usr/bin/env bash
set -euo pipefail
arch=${1:?architecture required}
source /work/input.env
export SOURCE_DATE_EPOCH LC_ALL=C.UTF-8 TZ=UTC
umask 022
mkdir -p /work/logs /work/dist /work/deps
exec > >(tee -a /work/logs/build.log) 2>&1
source_verified=false
finish() {
  local rc=$? file
  local -a catalogs=()
  trap - EXIT
  set +e
  if [[ $source_verified == true ]]; then
    # Upstream gettext regenerates tracked catalogs during make. Preserve its
    # generated diff and restore only these outputs, never arbitrary user edits.
    while IFS= read -r -d '' file; do
      case $file in
        po/*.po|po/vlc.pot) catalogs+=("$file");;
        src/network/stream.c) :;; # Exact postimage verified below, never ignored.
        *) echo "Unexpected tracked source change: $file" >&2; rc=1;;
      esac
    done < <(git -C /work/source diff --name-only -z HEAD --)
    if (( ${#catalogs[@]} )); then
      git -C /work/source diff --binary HEAD -- "${catalogs[@]}" > /work/logs/generated-catalogs.patch
      git -C /work/source restore --source="$VLC_SHA" --worktree -- "${catalogs[@]}" || rc=1
    fi
  fi
  if [[ $source_verified == true ]]; then
    python3 /recipe/scripts/source_patches.py restore /work/source /work/inputs.json || rc=1
  fi
  /recipe/scripts/resources.sh "exit-$rc" || true
  if [[ -n ${build:-} && -f $build/config.log ]]; then cp "$build/config.log" /work/logs/config.log; fi
  exit "$rc"
}
trap finish EXIT
[[ $(uname -m) == "$arch" ]]
[[ $(gcc -dumpmachine) == "$arch"-* ]]
[[ -f /usr/manifest.json ]] || { echo 'KDE SDK sandbox is required'; exit 1; }
[[ $(git -C /work/source rev-parse HEAD) == "$VLC_SHA" ]]
git -C /work/source diff --quiet HEAD -- || { echo 'Tracked source edits are not allowed' >&2; exit 1; }
[[ $(git -C /work/source describe --always HEAD) == "$VERSION" ]]
python3 /recipe/scripts/source_patches.py apply /work/source /work/inputs.json
source_verified=true
# Remove host-controlled search paths; /usr is exclusively the mounted KDE SDK.
unset CPATH C_INCLUDE_PATH CPLUS_INCLUDE_PATH LIBRARY_PATH LD_LIBRARY_PATH PKG_CONFIG_PATH CMAKE_PREFIX_PATH
export PATH=/usr/bin:/bin
export PKG_CONFIG_LIBDIR="/usr/lib/$arch-linux-gnu/pkgconfig:/usr/lib/pkgconfig:/usr/share/pkgconfig"
export CMAKE_PREFIX_PATH=/usr
export CC=gcc CXX=g++
# KDE SDK names its Qt 6 qmake simply qmake; upstream accepts QMAKE6 explicitly.
export QMAKE6=/usr/bin/qmake
# Keep upstream download URLs, checksums and fallback rules, but bound stalled
# transfers. Curl reads this before upstream's command-line arguments.
export CURL_HOME=/work/cache/curl
mkdir -p "$CURL_HOME"
cat > "$CURL_HOME/.curlrc" <<'CURLRC'
connect-timeout = 30
max-time = 900
speed-limit = 1024
speed-time = 120
retry-max-time = 300
no-progress-meter
show-error
CURLRC
jobs=${JOBS:-2}
[[ $jobs =~ ^[1-4]$ ]] || { echo 'JOBS must be between 1 and 4'; exit 2; }
# Limit Ninja, CMake and Rust as well as the top-level make.
export CMAKE_BUILD_PARALLEL_LEVEL=$jobs CARGO_BUILD_JOBS=$jobs
{
  gcc --version
  g++ --version
  ld --version
  "$QMAKE6" -query
  pkg-config --modversion Qt6Core Qt6Quick Qt6QuickControls2 KF6WindowSystem glib-2.0 libffi
} > /work/logs/toolchain.log
[[ $("$QMAKE6" -query QT_INSTALL_PREFIX) == /usr ]]
python3 /work/source/buildsystem/check_qml_module.py --qmake "$QMAKE6" \
  --modules QtQml.Models= QtQml.WorkerScript= QtQuick.Layouts= QtQuick.Window= QtQuick.Controls=
/recipe/scripts/resources.sh start
stage() {
  local name=$1; shift
  local start=$SECONDS rc=0
  echo "Starting $name; full output: /work/logs/$name.log"
  python3 /recipe/scripts/metadata.py time "/work/logs/$name.time" "$@" > "/work/logs/$name.log" 2>&1 || rc=$?
  printf '%s\t%s\t%s\n' "$name" "$((SECONDS-start))" "$rc" >> /work/logs/durations.tsv
  /recipe/scripts/resources.sh "$name" || rc=$?
  if (( rc )); then tail -n 70 "/work/logs/$name.log"; return "$rc"; fi
}
stage transport-regression python3 /recipe/verification/tfo-transport-test.py /work/source
source /recipe/scripts/contrib.sh
build_contrib
# Native SDK tools have generic names, not the compiler aliases searched by
# configure. These overrides are for VLC's build-time helpers, after contrib.
export BUILDCC='gcc -std=gnu17' OBJCOPY=/usr/bin/objcopy
cd /work/source
stage vlc-bootstrap ./bootstrap
patch_key=$(sha256sum /recipe/patches/manifest.json | cut -d' ' -f1)
build=/work/vlc-build/$CACHE_KEY/$VLC_SHA-$patch_key
mkdir -p "$build"
cd "$build"
# Preserve upstream flags. /app/extra is the future extra-data installation root.
stage configure /work/source/configure --host="$triplet" --prefix=/app/extra \
  --libdir=/app/extra/lib --libexecdir=/app/extra/lib --with-contrib="$deps/contrib/$triplet" \
  --enable-qt --enable-merge-ffmpeg --enable-extra-checks \
  --disable-qt-qml-cache --disable-pipewire
export LD_LIBRARY_PATH="$build/src/.libs:$build/lib/.libs"
stage vlc make -j"$jobs"
rm -rf /work/stage
mkdir -p /work/stage
stage install make install DESTDIR=/work/stage
payload=/work/stage/app/extra
find "$payload" -name '*.la' -delete
# Static contrib is normally linked into VLC plugins. Include any shared runtime
# outputs too, without copying SDK Qt/KF or development archives into the payload.
while IFS= read -r -d '' library; do cp -a "$library" "$payload/lib/"; done \
  < <(find "$deps/contrib/$triplet/lib" -maxdepth 1 \( -type f -o -type l \) -name '*.so*' -print0)
if [[ -d $deps/contrib/$triplet/share ]]; then
  cp -a "$deps/contrib/$triplet/share/." "$payload/share/"
fi
# Retain runtime data (including Java jars/locales if contrib installed them),
# without shipping contrib's build-system metadata.
rm -rf "$payload/share/aclocal" "$payload/share/pkgconfig" "$payload/share/cmake"
python3 /recipe/scripts/prepare-payload.py "$payload" /work/source "$VLC_SHA"
mkdir -p "$payload/share/vlc/build"
cp /work/inputs.json "$payload/share/vlc/build/inputs.json"
cp -a /recipe/patches "$payload/share/vlc/build/patches"
cp /work/logs/toolchain.log "$payload/share/vlc/build/"
stage qt-abi python3 /recipe/verification/qt_abi.py --payload "$payload" \
  --runtime "$TARGET_RUNTIME_ROOT" --arch "$arch" --inputs /work/inputs.json --output /work/logs/qt-abi.json
python3 /recipe/scripts/metadata.py build /work/inputs.json "$arch" "$CACHE_KEY" "$cache_hit" \
  "/work/dist/build-$arch.json"
cp /work/logs/toolchain.log "$payload/share/vlc/build/"
# Preserve VLC licenses; contrib share/licenses was copied above.
mkdir -p "$payload/share/licenses"
cp /work/source/COPYING* "$payload/share/licenses/"
/recipe/scripts/sanity.sh "$payload" "$arch"
stage package /recipe/scripts/package.sh "$payload" "$arch" "${ARTIFACT_VERSION:-$VERSION}"
