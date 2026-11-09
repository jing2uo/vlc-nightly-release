# Build architecture

The build follows [VLC's upstream Snap recipe](https://github.com/videolan/vlc/blob/master/extras/package/snap/snapcraft.yaml),
adapted to KDE SDK/Platform 6.11 and the
[FlatPark maintainer's requirements](https://github.com/flatpark/flatpark/pull/910).
The source origin is [VideoLAN Git](https://code.videolan.org/videolan/vlc).
This is a community build with one documented [downstream correction](tfo-eacces-fix.md).

## Inputs and isolation

One resolver selects a pinned VLC master commit, upstream `git describe` version,
and architecture-specific SDK/Platform OSTree deployments. Both native jobs use
that shared `inputs.json`. It records recipe hashes, contrib/tools trees, source
patch identities, runtime-path evidence, Qt library/private-header identities,
and exact deployment commits.

Fedora runs orchestration under rootless Podman. Real `flatpak build`/bubblewrap
sandboxes supply the KDE SDK compiler and libraries. Runtime tests use the
readonly KDE Platform rather than the SDK or host libraries. If nested user
namespaces are unavailable, use host-managed Flatpak with the existing SDK store.
Do not disable sandboxing, use privileged containers, or install compilation
dependencies on the host.

Runtime-path hashes describe the actual pinned source and build recipes; changes
relative to the historical baseline are informational. Build-time comparison
against the resolved inputs remains strict. Unknown compiled runtime paths and
consumers remain errors. See [verification](verification.md).

Qt private API imports require matching compiled Qt versions and providers.
Content identities track the relevant SDK/Platform Qt objects and private headers;
changed Qt content selects a new artifact identity even with the same VLC SHA.
Unrelated deployment metadata does not alone change that identity. Exact
SDK/toolchain deployment changes may still invalidate the contrib cache.

## Compilation

[scripts/build.sh](../scripts/build.sh) and
[scripts/contrib.sh](../scripts/contrib.sh) are the authoritative commands:

1. Check the source, SDK, recipe and input identities; apply only the locked patch.
2. Bootstrap and build `extras/tools` when the compatible cache is absent.
3. Bootstrap contrib for the native SDK compiler triplet with
   `--enable-sections --enable-libdsm --enable-dvdcss`, fetch checksum-verified
   source archives, and build the required dependencies.
4. Bootstrap VLC and configure an out-of-tree build with
   `--prefix=/app/extra --libdir=/app/extra/lib --libexecdir=/app/extra/lib`,
   the contrib prefix, `--enable-qt --enable-merge-ffmpeg --enable-extra-checks`,
   `--disable-qt-qml-cache --disable-pipewire`.
5. Run make and staged installation, collect runtime contrib libraries/data,
   prepare the launcher and provenance, and check Qt ABI compatibility.
6. Strip staged ELF executables/shared libraries/plugins with
   `strip --strip-unneeded`, then produce the deterministic-order tar.zst archive
   and fresh checksum/size sidecars. Runtime dynamic symbols are retained.

The SDK supplies Qt 6/KF6 and the detected desktop platform allowlist in
`contrib.sh`. Multimedia/network dependencies, including FFmpeg and GnuTLS, use
VLC contrib. No Ubuntu package tree or Snap prebuilt contrib archive is used.
`QMAKE6=/usr/bin/qmake` and the SDK's pkg-config/search paths prevent host Qt
selection. Qt/QML runtime modules remain supplied by KDE Platform.

## Payload and persistence

Each archive contains one `extra/` tree:

- `bin/`: shared launcher, VLC executable and relative command aliases.
- `lib/`: VLC libraries, shared contrib outputs, `vlc/plugins` and `vlc-cache-gen`.
- `share/`: VLC data, HRTF/SOFA data, translations, licenses and build inputs.
- `include/`: installed upstream headers.

FlatPark's offline extra-data installer flattens that archive root into
`/app/extra`, avoiding `/app/extra/extra`. Runtime Qt/KF libraries and extensions
remain under `/usr`. The launcher resolves VLC's library, plugin and data paths
relative to its installation and forwards arguments.

`WORK_DIR` defaults to the checkout's `work/`:

```text
source/                     pinned Git checkout
flatpak-data/               persistent SDK/Platform OSTree installation
cache/                      download/orchestration cache
deps/<key>/                 tools/contrib source, objects and installs
deps/tarballs/              shared checksum-verified source downloads
vlc-build/<key>/<sha>-<patch-key>/  incremental VLC objects
stage/                      staged application tree
dist/                       candidate archives, input lock and metadata
verification/results/       native test logs and reports
logs/                       build logs, timings and resource measurements
```

Contrib cache keys include architecture, SDK/runtime deployments, contrib/tools
trees, dependency epoch and contrib recipe hash. Only exact compatible caches
are restored. Packaging changes do not require discarding compatible contrib
objects. Keep historical artifacts out of active candidate selection; do not
backfill missing build-time attestations.

Build stages record disk/memory use and durations. CI checks a 20 GiB planning
budget, may remove unused hosted-runner toolchains, and uses two compile jobs
by default with a 350-minute job limit. Logs and compatible caches survive failures.
Archive size must remain below 2 GiB. Normalized archive metadata does not imply
bit-for-bit reproducible compilation or permanent availability of upstream inputs.

## Releases and FlatPark

Both native architectures must pass the current core checks and strict pair
validation. Publication rechecks Qt compatibility, signs the exact bytes, uploads
and verifies a draft, and publishes only with the required authorization.
Existing tags/assets are never replaced. Failed candidates leave the last release
available. Source updates run approximately every two weeks, with intervening Qt
compatibility checks; see [operations and installation](../README.md).
