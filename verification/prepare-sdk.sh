#!/usr/bin/env bash
set -euo pipefail
# All development tools/headers and fixture generation run inside org.kde.Sdk.
verify=${1:?verification source directory}
mkdir -p /app/verify/fixtures
cp /usr/bin/strace /app/verify/strace
# Literal $ORIGIN is a loader token, not a shell variable.
# shellcheck disable=SC2016
cc -std=c17 -Wall -Wextra -Werror -I/app/extra/include "$verify/probe.c" \
  -L/app/extra/lib -Wl,-rpath,'$ORIGIN/../extra/lib' -lvlc -ldl -o /app/verify/probe
# pkg-config intentionally supplies separate compiler/linker arguments.
# shellcheck disable=SC2046
g++ -std=c++17 -Wall -Wextra -Werror "$verify/qml-probe.cpp" \
  $(pkg-config --cflags --libs Qt6Quick Qt6QuickControls2) -o /app/verify/qml-probe
ffmpeg -hide_banner -version > /app/verify/fixtures/generator.txt
ffmpeg -nostdin -y -hide_banner -loglevel error -i /app/verify/fixtures/reference.mp4 \
  -f lavfi -i 'sine=frequency=997:sample_rate=48000' -t 8 -map 0:v:0 -map 1:a:0 \
  -c:v copy -c:a aac -movflags +faststart /app/verify/fixtures/h264-aac.mp4
ffmpeg -nostdin -y -hide_banner -loglevel error -f lavfi -i 'testsrc2=size=160x96:rate=12' \
  -f lavfi -i 'sine=frequency=997:sample_rate=48000' -t 8 -c:v libvpx -threads 2 \
  -c:a libvorbis /app/verify/fixtures/vp8-vorbis.webm
for asset in /app/verify/fixtures/h264-aac.mp4 /app/verify/fixtures/vp8-vorbis.webm; do
  ffprobe -v error -show_streams -of json "$asset" > "$asset.streams.json"
  sha256sum "$asset"
done
mkdir -p /app/verify/fixtures/hls
ffmpeg -nostdin -y -hide_banner -loglevel error -i /app/verify/fixtures/h264-aac.mp4 \
  -c copy -hls_time 1 -hls_list_size 0 /app/verify/fixtures/hls/index.m3u8
