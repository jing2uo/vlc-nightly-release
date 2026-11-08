#!/usr/bin/env bash
set -euo pipefail
arch=${1:?};shift
XDG_RUNTIME_DIR=$(mktemp -d /tmp/vlc-runtime.XXXXXX)
export XDG_RUNTIME_DIR
mkdir -p "$XDG_RUNTIME_DIR"
chmod 700 "$XDG_RUNTIME_DIR"
# Core verification needs neither a display server nor an audio daemon.
advanced=false
for option in "$@"; do
  case $option in --diagnostics|--desktop|--external|--trace-http) advanced=true;; esac
done
if [[ $advanced == false ]]; then
  exec python3 /recipe/verification/run.py --work /work --arch "$arch" "$@"
fi
# Platform declares this official GL extension branch; no host GL library copy.
if ! flatpak info --user org.freedesktop.Platform.GL.default//25.08 >/dev/null 2>&1; then
  if ! flatpak install --user --noninteractive -y flathub org.freedesktop.Platform.GL.default//25.08; then
    echo 'Optional GL extension setup failed; core verification remains required' >&2
  fi
fi
export DISPLAY=:99
Xvfb :99 -screen 0 1024x768x24 -nolisten tcp -ac > /work/verification/results/xvfb.log 2>&1 &
xvfb=$!
trap 'kill "$xvfb" 2>/dev/null || true' EXIT
# A socket readiness check, not a long-running compilation poll.
for _ in {1..50}; do [[ ! -S /tmp/.X11-unix/X99 ]] || break; sleep .1; done
if pulseaudio --daemonize=yes --exit-idle-time=-1 --load="module-null-sink sink_name=vlc_verify"; then
  export VLC_PRIVATE_PULSE=1
else
  echo 'Optional PulseAudio setup failed; core verification remains required' >&2
fi
if ! command -v dbus-run-session >/dev/null; then
  echo 'Optional session bus unavailable; running verification without it' >&2
  exec python3 /recipe/verification/run.py --work /work --arch "$arch" "$@"
fi
exec dbus-run-session -- python3 /recipe/verification/run.py --work /work --arch "$arch" "$@"
