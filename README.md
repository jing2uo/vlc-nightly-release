# VLC nightly release

Public VLC nightly build infrastructure. A personal or organization GitHub
repository is supported; the workflow uses its actual repository context.
VLC is built from a pinned master commit with one explicitly recorded downstream
[TCP Fast Open fallback correction](docs/tfo-eacces-fix.md), using its own tools and
contrib recipes inside the actual `org.kde.Sdk//6.11` Flatpak SDK. Qt 6 and KF6
belong to the matching `org.kde.Platform//6.11` runtime.

**Publication remains disabled.** Phase 2 now runs artifact, dependency,
relocation, decoding, GUI/MPRIS and audio gates against the actual KDE Platform.
See [verification commands](docs/verification.md) and
[actual Phase 2 results](docs/phase-2-report.md) and
[Task 2.1 remediation](docs/task-2.1-report.md) and
[Task 2.2 update/Qt compatibility audit](docs/task-2.2-report.md).
The Task 2.2 handoff reports successful native x86_64 and aarch64 Actions builds
(about one hour total); those builds are preserved and are not repeated by this
audit. The amended gates still need their next native CI execution. Manual and
scheduled builds retain 30-day downloadable artifacts even when verification
fails. Historical reports describe their execution status at the time.

On Fedora, with rootless Podman already available:

```sh
scripts/run-container.sh resolve                         # current upstream master
# Or: scripts/run-container.sh resolve <full-40-character-master-SHA>
scripts/run-container.sh build "$(uname -m)"             # native only
```

Run from this repository directory. `WORK_DIR=/absolute/persistent/directory`
overrides `./work`; `JOBS=2` is the default (accepted range: 1–4). Use a native
machine for each architecture and copy the **same** `work/inputs.json` to both.
The resolver pins the VLC commit plus both architectures' SDK/runtime OSTree
commits. Save this file with the build recipe to reproduce the inputs. Changing
build scripts requires resolving a new input lock.

No host compiler or multimedia development package is installed. The outer
Fedora container installs orchestration tools only. A nested Flatpak build mounts
the SDK as `/usr`; neither the container's nor the host's libraries are used for
compilation. Container recreation retains source, SDK installation, intermediate
objects, tarballs and logs under `work/`.

Build output is `work/dist/vlc-<git-describe>-r3-qt<identity>-<arch>.tar.zst`, its SHA-256 and byte
size, and per-architecture JSON provenance. The archive has a single top-level `extra/` directory. Manual staging extracts
under `/app`; a future extra-data installer must strip that one component while
extracting inside its writable `/app/extra` directory. The input lock records upstream `version` separately from `artifact_version`
(including the packaging revision and both targets' relevant Qt content identity).
An unchanged Qt context skips completed releases even if runtime revision metadata
changes; changed private Qt libraries/headers select a fresh immutable release. Launch
`/app/extra/bin/vlc` or `/app/extra/bin/vlc-nightly` inside the matching KDE runtime. This is a runtime
payload, not a standalone distribution or Flatpak package.

[Architecture, commands, resource policy and Snap differences](docs/architecture.md)
explain the build. Phase 2 verification and its remaining limitations are documented separately. Phase 3 owns FlatPark integration; no FlatPark
manifest or migration is included here.
