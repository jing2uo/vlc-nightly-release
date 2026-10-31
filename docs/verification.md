# Phase 2 verification

Use the existing `work/inputs.json`, pinned SDK/Platform deployment and matching
archive/sidecars in `work/dist`. Verification never fetches VLC source or rebuilds
VLC/contrib. A historical artifact is compared to its original input lock, not
the digest of today's verification scripts.

```sh
# Fedora: real Wayland/X11 desktop, external HTTPS regression cases
scripts/verify.sh --backend=host --desktop --external
# CI/local: private Xvfb, D-Bus and PulseAudio null sink, native architecture only
scripts/verify.sh --backend=podman --headless
# Lightweight adversarial archive/release-gate tests
python3 -m unittest discover -s verification -p 'test_*.py'
# Local assembly: put the shared lock beside both native archives/reports
cp work/inputs.json work/dist/inputs.json
# Require both native reports and the corresponding exact artifacts
scripts/verify-artifacts.sh work/dist
```

Set `WORK_DIR=/absolute/path` for the existing persistent workspace. Run each
native architecture separately using the same Phase 1 input lock. No emulated
run counts as native coverage. External network cases are opt-in and separate
from deterministic local HTTP MP4/HLS fixtures. An unreachable endpoint is
`unavailable`; an application failure after reachability is established is
`fail`. GUI logs also record whether VLC actually reached Playing, advanced its
position, selected a video output, and presented a surface.

## Isolation and namespace compatibility

Phase 1 uses real `flatpak build`/bubblewrap inside rootless Podman. Compilation
success is not taken as proof of runtime sandbox compatibility. The Podman
verification entry point first runs `unshare --user --map-root-user true` and an
actual pinned KDE **Platform** sandbox. It checks `/.flatpak-info` and the absence
of GCC. If nested sandboxing fails it keeps the log and tries host-managed
Flatpak, using the same `XDG_DATA_HOME=work/flatpak-data`. If that is unavailable,
verification fails with diagnostics. Host fallback needs a working display for
GUI checks; it does not silently substitute an offscreen GUI pass.

Host-managed Flatpak is also the default for local desktop verification. The
compiler, Qt headers, fixture encoders and diagnostic helper builds still run
inside the actual KDE SDK. Runtime checks explicitly use `flatpak build
--runtime --readonly`: `/usr` belongs to KDE Platform, not the SDK or Fedora.
Runtime tests expose no source/contrib/build directories. Host code handles only
orchestration, metadata, archives and D-Bus observations.

No privileged container, added SYS_ADMIN capability, unrestricted seccomp,
sandbox disabling or kernel setting change is used. Existing Phase 1 rootless
settings are retained. Desktop tests expose only requested display/session-bus
and audio sockets. X11 captures target only the test VLC window.

The disposable verification image adds diagnostic tools, Xvfb and a private
PulseAudio server. Fedora's container base pulls a PipeWire replacement daemon;
only the test image swaps that conflicting package for PulseAudio. The real
host audio server is untouched. The matching official
`org.freedesktop.Platform.GL.default//25.08` extension is installed in the user
work store for headless GL; the effective extension commits are recorded in
`platform-namespace-smoke.log`. Reproducing rendering requires those extension
commits and a matching display/driver, in addition to the pinned KDE runtime.
No Ubuntu libraries or host GL library copies enter the payload.

## Checks and evidence

* Archive audit checks SHA-256, exact byte size, provenance, root namespace,
  ownership/modes, bounded unpacking, duplicates, traversal and safe link targets
  before custom two-pass extraction. ELF headers/permissions and required
  payload components are checked on the extracted files. No `tar --extract` is
  run on unaudited release archives.
* SDK `readelf` inventories every ELF, NEEDED/RPATH and allocated strings.
  Actual Platform `dlopen(RTLD_NOW)` in separate child processes resolves every
  shared payload object/plugin, catching missing libraries, symbols and symbol
  versions. Temporary runtime data/config defaults fail a separate gate;
  harmless source assertions/configuration provenance remain diagnostics.
* A small SDK-built libVLC helper requires decoded video frames and nonzero
  PCM audio from H.264/AAC and VP8/Vorbis fixtures. It checks local HTTP MP4 and
  HLS too. Independent H.264 reference media is checksum pinned; SDK FFmpeg
  creates the synthetic audio/WebM and HLS, with stream inventories saved.
* Actual runtime QML component creation checks Qt imports; visible Qt windows
  and real VLC Qt GUI playback are separate checks. The default Qt Quick and
  RHI backends are left selected by upstream, with diagnostic logs enabled.
* Relocation physically moves the payload, leaving `/app/extra` absent, then
  repeats startup, symbol resolution, decoding and `cvlc` invocation.
* Private PulseAudio monitor analysis requires nonzero output and the fixture's
  997 Hz tone. PCM callbacks alone are not claimed as device-output testing.
* Bounded X11/Wayland GUI tests record process signals, QML diagnostics, video
  outputs, MPRIS position/status/metadata, pause/play/OpenUri, and two files in
  one invocation. Screenshots or Wayland surface commits establish presentation
  evidence; neither establishes human-reviewed visual quality.

Results live under `work/verification/results/<UTC>-<arch>/`. Logs and JSON are
preserved; fixture/helper test files live under
`work/verification/app-<arch>/files/verify`. SDK, source, contrib, VLC objects and
original tarballs are retained. The latest native JSON is copied into
`work/dist/verification-<arch>.json`; historical result directories distinguish
desktop versus headless runs. A later run does not erase earlier diagnostics.

## Release gates and manual limits

The native workflow verifies each architecture before its job can succeed.
Build artifacts remain downloadable for 30 days even if verification fails;
diagnostics upload with `always()`. The joint job requires every named mandatory
check, passing status, exact artifact hash/size, architecture, shared source,
SDK/runtime pins and identical verification recipes. Missing/skipped checks or a
partial pair fail. The publisher repeats this check before any GitHub mutation,
requires an explicit reviewed-publication environment value, and refuses prior
tags/assets. The workflow's publication job remains literally disabled.

Private Xvfb/null-sink results are deterministic CI evidence. Real display/GPU,
physical audio quality, network stream behavior across drivers, human GUI
interaction and future launcher/portal permissions require separate review.
Passing automated checks does not assert those results. Native aarch64 and an
actual hosted workflow execution remain mandatory release blockers. Consult
[the execution report](phase-2-report.md) before considering publication.

The Phase 2 test harness prepends payload directories while preserving Flatpak's
existing `LD_LIBRARY_PATH` (including its GL extensions). An early diagnostic
run replaced it and produced spurious GLX aborts. Those historical logs are kept
with an explicit correction in the execution report; they are not evidence of
a VLC regression.

## Task 2.1 candidate and regression replay

The original Phase 1 archive remains in `work/dist`. The corrected local
candidate is kept separately under `work/candidates/r2`. To create a fresh
candidate from the original archive and existing pinned source checkout:

```sh
# Refuses an existing destination; do not rerun over the recorded candidate.
python3 scripts/repackage.py work/dist work/candidates/r2
scripts/verify.sh --backend=host --dist="$PWD/work/candidates/r2" --desktop --external
scripts/verify.sh --backend=podman --dist="$PWD/work/candidates/r2" --headless
```

`--dist=...` selects a separate input lock, archives, metadata and verification
sidecars while reusing the original SDK installation, fixtures and caches. The
Podman wrapper translates that path into its existing `/work` mount. Archives
and release tags now use `artifact_version`, retaining upstream `version` for
VLC's version assertion. All output bytes and original ELF hashes remain auditable.

New mandatory checks cover six separate GnuTLS constructor traces, the actual
SOFA loader with VLC's upstream default HRTF file, application filesystem
accesses, direct relocated `vlc`, relocated `cvlc` playback and relocated HRTF
data. Only tracing uses Flatpak's `--allow=devel`; it still runs under Platform,
not SDK, and adds no production permission. Source-based classification of the
nine old strings is narrowly pinned and does not replace these execution gates.

Ordinary OpenUri now must actually play the requested file before clean Quit.
Rapid OpenUri followed immediately by Quit remains a distinct mandatory stress
case. `verification/reproduce-x11.py` bypasses wrappers with `--raw-elf` for a
controlled comparison; `--settle 2` labels a separate diagnostic control. See
[Task 2.1](task-2.1-report.md) for commands, reproducibility and the release decision.

## Task 2.2 content and Qt gates

New resolved input locks include `runtime_path_evidence`, per-architecture
`qt_abi` snapshots and their combined `qt_abi_identity`. Native verification
requires the content evidence and a `qt-private-abi` report, in addition to the
unchanged constructor/filesystem/runtime-loader gates. The joint release check
requires both new named gates and matching Qt build identity/version evidence.
Existing archives/reports remain historical records and are not rewritten to
invent new build-time attestations. Fresh publication candidates must come from
the updated resolution/verification procedure. The existing r2 binary was
inspected separately for this audit; its bytes and checksum remain unchanged.

Focused stdlib tests (no compilation):

```sh
python3 -m unittest discover -s verification -p 'test_*.py'
```

`verification/qt_abi.py` finds the actual GUI plugin recursively. Run it with SDK
ELF tools, a read-only view of the deployed target Platform's `files` directory,
and the payload's original `toolchain.log`. It records all required Qt symbols'
resolution and the private imports/providers. Namespace `Qt_6_PRIVATE_API` alone
is insufficient: exact compiled/target versions and tracked Qt build identities
are checked too. No GUI interaction, X11 gate change or playback rerun is needed
for this static audit. The original X11 stress gate remains mandatory and intact.

The producer can detect and rebuild for a changed target Qt context, but cannot
guarantee that a client independently updating KDE Platform has already received
the matching VLC payload. Coordinating consumer updates and handling that window
needs review before release/Phase 3; no FlatPark integration is implemented here.
