#!/usr/bin/env bash
set -euo pipefail
arch=${1:?};shift
# Platform declares this official GL extension branch; no host GL library copy.
flatpak info --user org.freedesktop.Platform.GL.default//25.08 >/dev/null 2>&1 || \
  flatpak install --user --noninteractive -y flathub org.freedesktop.Platform.GL.default//25.08
export DISPLAY=:99
XDG_RUNTIME_DIR=$(mktemp -d /tmp/vlc-runtime.XXXXXX)
export XDG_RUNTIME_DIR
mkdir -p "$XDG_RUNTIME_DIR"
chmod 700 "$XDG_RUNTIME_DIR"
Xvfb :99 -screen 0 1024x768x24 -nolisten tcp -ac > /work/verification/results/xvfb.log 2>&1 &
xvfb=$!
trap 'kill "$xvfb" 2>/dev/null || true' EXIT
# A socket readiness check, not a long-running compilation poll.
for _ in {1..50}; do [[ ! -S /tmp/.X11-unix/X99 ]] || break; sleep .1; done
pulseaudio --daemonize=yes --exit-idle-time=-1 --load="module-null-sink sink_name=vlc_verify"
export VLC_PRIVATE_PULSE=1
exec dbus-run-session -- python3 /recipe/verification/run.py --work /work --arch "$arch" "$@"
