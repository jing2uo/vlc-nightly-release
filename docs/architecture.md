# Build architecture and audit inputs

The specification is the [maintainer proposal of October 31, 2026](https://github.com/flatpark/flatpark/pull/910)
and the [upstream-faithful/public-audit conditions](https://github.com/flatpark/flatpark/issues/389).
The implementation follows [VLC's Snap recipe](https://github.com/videolan/vlc/blob/master/extras/package/snap/snapcraft.yaml)
and studies its [wrapper](https://github.com/videolan/vlc/blob/master/extras/package/snap/vlc-snap-wrapper.sh).
The workflow uses the resolve/native-matrix/release pattern of
[jing2uo/ayugram-release](https://github.com/jing2uo/ayugram-release/blob/main/.github/workflows/build.yml).
The authoritative source is [VideoLAN Git](https://code.videolan.org/videolan/vlc);
the GitHub mirror was used to inspect files when the web frontend blocked access.

## Inputs and isolation

`resolve.sh` fetches full master history and tags (blob-filtered, never shallow),
validates that an optional full SHA belongs to master, and uses upstream's
`git describe --always HEAD`. Unexpected versions fail instead of inventing a
commit count. Both native jobs consume one uploaded `inputs.json`. SDK and runtime
OSTree commits are resolved for **both** architectures in that job. Each build
checks the deployed commits, source SHA, recipe digest and contrib/tools trees.
There is no fallback to another runtime branch or host Qt.

The Fedora container's `/usr` holds only orchestration dependencies. `flatpak build`
creates a second sandbox whose `/usr` is KDE SDK 6.11. `/work` is persistent and
`/recipe` is read-only. The container uses rootless Podman, user namespace mapping,
and drops capabilities; no privileged mode, host system mounts, or host dependency
installation. Flatpak downloads use `/work/flatpak-data`. `build-init` creates only
application metadata and an empty `/app`, not another copy of the SDK.

Source acquisition and SDK operations also happen inside this container. Archive
and checksum operations are lightweight and may be run on the host; the shared
build script happens to package inside the SDK so CI and local commands coincide.
Nested execution on Fedora requires container `/proc/*` unmasking and disabling
SELinux labels for this one rootless container; the measured investigation is
in the implementation report. Seccomp remains enabled. Each native job now verifies the payload inside KDE Platform. The joint job
audits archive namespaces and native reports without executing foreign binaries.

## Exact compilation sequence

The recipe operates at stable `/work` paths so cached build files remain valid.
For the native architecture, `triplet=$(gcc -dumpmachine)` uses the SDK compiler.
The equivalent commands are:

```sh
# deps = /work/deps/<compatibility-hash>; unmodified copies of upstream subtrees
cd "$deps/extras/tools"
./bootstrap
make -j2 all
export PATH="$deps/extras/tools/build/bin:$PATH"

mkdir -p "$deps/contrib/linux"
cd "$deps/contrib/linux"
../bootstrap --host="$triplet" --enable-sections --enable-libdsm --enable-dvdcss
make "PKGS_FOUND=$system_packages" list
make -j2 "PKGS_FOUND=$system_packages" fetch
make -j2 "PKGS_FOUND=$system_packages"

export BUILDCC="gcc -std=gnu17" OBJCOPY=/usr/bin/objcopy
cd /work/source
./bootstrap
mkdir -p "/work/vlc-build/$CACHE_KEY/$VLC_SHA"
cd "/work/vlc-build/$CACHE_KEY/$VLC_SHA"
/work/source/configure --host="$triplet" --prefix=/app/extra \
  --libdir=/app/extra/lib --libexecdir=/app/extra/lib --with-contrib="$deps/contrib/$triplet" \
  --enable-qt --enable-merge-ffmpeg --enable-extra-checks \
  --disable-qt-qml-cache --disable-pipewire
make -j2
make install DESTDIR=/work/stage
```

The actual script additionally logs timing, checks resources, sets native compiler
and SDK search paths, and validates the resulting payload. It never applies a
patch to VLC. Upstream's own dependency patches remain part of its contrib system.

`contrib.sh` asks upstream's own make rules which packages are present in the
SDK, then retains only a public platform allowlist: GLib/libffi, font/text
platform libraries, libxml2, Cairo/Pixman/Pango, libc conversion/localization,
X11/XCB protocols, Wayland and graphics API headers/loaders. Only packages that
upstream actually detects in the SDK are retained; the actual selected names
are printed in the build log and `contrib-list.log`.

Everything outside that platform set uses the upstream default contrib selection
with system detection suppressed. Thus codecs, containers, multimedia rendering
and network libraries (including FFmpeg, libass, libplacebo, GnuTLS and the media
library) remain source builds. This restores upstream's normal SDK detection for
the platform ABI without allowing SDK codec binaries to replace contrib.

Initial attempts showed why this distinction matters: blanket `PKGS_FOUND=`
built GLib 2.75, below SDK Pango's >= 2.82 requirement; retaining only GLib/libffi
then exposed an old contrib xproto 7.0.29 below the SDK's >= 7.0.33 requirement.
Logs/configuration are preserved and those incompatible caches are never reused.

Qt is not selected by default for Linux and is supplied by KDE SDK. A guard
rejects contrib Qt libraries. This policy does not enable every optional contrib
package. Remaining supporting-library ABI closure is a Phase 2 verification item.

At the observed commit, contrib selects FFmpeg 9.0. FFmpeg remains VLC's static
contrib build, with its upstream-selected version,
checksums, dependency patches and restricted configure features. VLC's
`--enable-merge-ffmpeg` combines its FFmpeg modules as upstream specifies; it does
not request a full standalone system FFmpeg. No Snap contrib archive is consumed.

The Qt interface uses upstream's `qt6.pro`: Core, GUI, QML, SVG, Quick, Widgets,
and Quick Controls 2, plus optional private Qt headers. `QMAKE6=/usr/bin/qmake`, moc, rcc, uic,
qsb and qmlimportscanner must come from the SDK. The build sets `QMAKE6=/usr/bin/qmake` (the SDK does not provide `qmake6`)
and records `qmake -query`
and requires KDE WindowSystem via SDK pkg-config. Upstream's own QML module check
requires QtQml.Models, QtQml.WorkerScript, QtQuick.Layouts, QtQuick.Window and
QtQuick.Controls. Disabling QML cache generation does **not** remove these
runtime imports. VLC's own QML resources are installed/embedded by its upstream
make rules; Qt's QML modules and Qt plugins are supplied by KDE Platform and are
not duplicated into this payload.

## Differences from the Snap recipe

| Adaptation | Reason |
| --- | --- |
| KDE Flatpak SDK and Platform instead of core24/KDE Neon and Ubuntu packages | Required target ABI; avoid an independently resolved Ubuntu dependency tree. |
| Build multimedia contrib from source, retain detected SDK platform libraries | Multimedia provenance must come from VLC's contrib, with no Snap prebuilt fallback. |
| `/app/extra`, fixed `lib/`, out-of-tree application build | Future extra-data root; consistent archive layout and retained incremental work. |
| Explicit Qt enablement and SDK-origin checks | Fail if a nightly would silently omit the GUI or obtain Qt from another source. |
| Native triplet from SDK GCC; explicit native BUILDCC/objcopy | Debian/Snap triplets and `c17`/`c99`/prefixed-binutils aliases are absent from this SDK. The architecture guard permits the SDK’s generic native tools. |
| Two jobs, fail immediately, no `make -k || make -j1` retry | Conservative resource usage; preserve original failures instead of repeating a resource failure. |
| Simple relocatable launcher | Replace Snap paths with payload paths; do not force xcb, software rendering, custom config, or home symlink creation. |
| Deterministic tar ordering/ownership/mtime and zstd | Persistent one-file payload per architecture instead of a Snap filesystem. |
| No Snap desktop rewriting or Snap cleanup against base files | Future FlatPark packaging supplies desktop integration; KDE owns runtime files. |

The Snap flags `--enable-sections` for contrib and `--enable-merge-ffmpeg`,
`--enable-extra-checks`, `--disable-qt-qml-cache`, `--disable-pipewire` for VLC
are retained. Keeping PipeWire disabled follows the current upstream recipe;
Phase 2 must evaluate runtime audio/capture behavior before any change.

## Payload contract

```text
extra/
  bin/vlc -> vlc-nightly   public relocatable entry point
  bin/vlc.bin              byte-identical upstream executable
  bin/cvlc, qvlc, ...      upstream aliases, executable path made relative
  bin/vlc-nightly          shared library/plugin/data and optional TLS-policy environment
  lib/libvlc.so*, libvlccore.so*, shared contrib outputs if present
  lib/vlc/plugins/         upstream plugins, including Qt and merged FFmpeg
  lib/vlc/vlc-cache-gen    upstream plugin cache utility
  share/vlc/              upstream runtime data, Lua/QML and pinned default HRTF data
  share/locale/           translations
  share/licenses/         VLC and available contrib license material
  share/vlc/build/        input lock and toolchain provenance
```

`extra/` is extracted under `/app`, producing `/app/extra`. A future Flatpak
extra-data helper, whose writable working directory is `/app/extra`, must strip
the archive's one top-level component when extracting there. No helper or
FlatPark manifest is implemented in this phase. SDK Qt/KF libraries,
QML imports, themes and system plugins stay under the runtime's `/usr`. The launcher
uses paths relative to itself for VLC libraries, plugins and data. Both `libdir` and `libexecdir` are configured to `/app/extra/lib`, keeping
VLC helper binaries and compiled Lua in `lib/vlc/`. The configured
installation root is `/app/extra`; arbitrary-root relocation of every third-party
library, locale path and plugin cache is a Phase 2 check, not a proven property.
No binary patching or host library copying is used.

Run-specific build metadata is a sidecar outside the archive, so a workflow run
number alone does not change payload bytes. Build metadata identifies upstream
SHA, SDK/runtime branch and OSTree commits,
architecture, recipe digest/commit, cache key/use and workflow run. Each archive
has a SHA-256 sidecar and exact byte-size sidecar. Joint verification creates
`SHA256SUMS` and `sizes.json` and compares both builds to the input lock.
Every compressed archive must be strictly below 2 GiB.

Normalization of archive metadata is not a claim of bit-for-bit reproducible
compilation. Upstream may embed dates and build paths; Phase 2 must compare clean
rebuilds and document remaining nondeterminism. SDK commits must still be
available from Flathub for a historical reproduction; this repository does not
mirror SDK objects or upstream dependency servers.

## Persistence, caches and resources

```text
work/source/                 upstream Git checkout and bootstrap outputs
work/flatpak-data/           one user Flatpak/OSTree installation
work/cache/                  orchestration/download cache
work/deps/<key>/             tools + contrib source, objects and installs
work/deps/tarballs/          shared source archives; verified per pinned recipe
work/vlc-build/<key>/<source-sha>/  incremental VLC objects
work/stage/                  current staged installation
work/dist/                   archives and provenance
work/logs/                   stage logs, timing/RSS output, resource snapshots
```

The compatibility hash includes architecture, SDK branch/commit, runtime commit,
upstream contrib tree, tools tree, dependency source epoch and `contrib.sh` digest. The SDK commit pins
the compiler/toolchain. Dependency flags/toolchain overrides belong in
`contrib.sh`; packaging-only changes do not discard compatible compiled outputs.
The full recipe digest is separately checked and recorded in the input lock.
Dependency `SOURCE_DATE_EPOCH` comes from the last upstream change to contrib or
tools, while VLC and archive timestamps use the VLC commit epoch. A different key gets a separate directory. Local failed
builds retain partial intermediates. Completed compatible contrib builds skip
bootstrap and compilation; partial builds keep their existing configuration so
rewriting config timestamps does not force unnecessary recompilation. Actions restores only exact cache keys and
saves caches only after contrib completed successfully, including when a later
VLC stage fails; no unverified downloaded binary dependencies enter it.
Do not import caches from untrusted users. Downloaded source archives are shared through `work/deps/tarballs`; each
compatibility tree verifies its own pinned upstream checksums rather than
sharing `.sum-*` stamps. Old local cache directories can be
removed manually when no build is using them. SDK and application build trees
are not uploaded to Actions cache; only contrib/tools are cached.

The cold-build planning budget is **20 GiB**, revised from the initial 28 GiB
estimate after measuring a successful local build. It allows approximately
4.5 GiB for SDK/container storage, 1 GiB for source/tools, 7 GiB for contrib,
4 GiB for VLC objects/staging and 3.5 GiB for archives, extraction and headroom.
The measured first successful build used about 5.7 GiB for contrib, 2.5 GiB for
VLC objects, 1.1 GiB for staging and 275 MiB for its compressed artifact. The
SDK user installation occupied about 3.4 GiB. These are local measurements;
GitHub cache-upload temporary storage and hosted-runner peaks remain unmeasured.

The workflow measures actual disk first and, if needed, removes only unused
Android, .NET, Haskell and JVM installations. It retains Podman, system libraries,
Python, GitHub CLI, archive tools and the Actions runtime. Host JVMs are not used
by the isolated SDK build. It stops if the planning budget remains unavailable.
No paid runner or external service is introduced.

SDK install, tools, contrib fetch/build, configure, VLC, install and packaging
boundaries record `df`, memory and directory sizes. Each build stage uses Python monotonic time and child resource accounting
for elapsed time and maximum RSS; durations and exit codes are in
`durations.tsv`. A 2 GiB free-space guard stops subsequent stages. The job limit
is 350 minutes, with two parallel compile processes by default; nested CMake
and Cargo parallelism are also capped. Compiler logs stay in files. Inspect
progress at most every 5–10 minutes during compilation. A failure prints only
the final relevant log section and preserves diagnostics, with no automatic
retry. Actions uploads diagnostics even after failure.

Before runtime verification, test nested user namespaces and a real Platform
sandbox. If these fail, retain the exact error and use host-managed Flatpak
with the existing SDK store; the SDK sandbox still owns compilers and libraries.
Do not weaken seccomp, use privileged execution, or change kernel settings.
See verification.md for the measured smoke tests and fallback.

## Release lifecycle

A single concurrency group prevents competing scheduled/manual runs. Existing
completed releases are skipped only after successful API enumeration and expected
assets are present. API errors fail the check. Incomplete releases/drafts cause an
explicit failure and are never overwritten. Both native jobs must succeed before
the joint archive/SHA/architecture/input checks. `release-candidate` preserves
both tarballs and metadata for 30 days as a manual testing download.

The prepared publisher creates a draft containing both archives, checksums,
size map and provenance, then exposes it as a persistent prerelease. It refuses
an existing tag and has no upload/clobber/delete path. A failed draft requires
manual inspection. Its workflow job has literal `if: ${{ false }}`. Phase 2 adds native runtime
gates and a strict pair check; the separately documented X11 issue, validation of the amended gates
and incomplete manual coverage keep publication locked. The publisher repeats
the pair checks before any mutation and requires explicit reviewed evidence
before the lock can be lifted. There is no FlatPark hook or notification.

The first source fetch exposed a stalled VideoLAN-mirror GnuTLS transfer. The
local investigation terminated only that curl process after more than five
minutes without byte progress, allowing upstream's own origin fallback to run;
it did not restart a compiler or replace any dependency. Fetch checksums remain
upstream's. See the execution report for the final result.

Curl now has a 30-second connection limit, a 120-second low-speed stall limit,
a 15-minute per-transfer limit and a five-minute retry window via a generated
`CURL_HOME/.curlrc`. Upstream's own download rules, origin fallback and checksum
verification are unchanged; curl progress meters are suppressed. After the
first failure, one HTTP/1.1 source-only download from the official alternate
`download.videolan.org` hostname succeeded and passed upstream's GnuTLS SHA-512
check. That verified source archive was retained in the shared cache.

Before each new resolve/build attempt, existing stage logs are moved into
`work/logs/history/` rather than overwritten. Setup and compiler diagnostics
remain available through container recreation.

The published runner inventories list Podman, GitHub CLI, Python and zstd on the
selected [x86_64](https://github.com/actions/runner-images/blob/main/images/ubuntu/Ubuntu2404-Readme.md)
and [aarch64](https://github.com/actions/runner-images/blob/main/images/ubuntu/Ubuntu2404-Arm64-Readme.md)
Ubuntu 24.04 images. The inventories do not establish nested-sandbox compatibility
or available disk space for this job; those require actual workflow measurements.

VLC object directories include both the SDK/contrib compatibility key and source
SHA. Re-resolving the same source against a changed SDK cannot reuse incompatible
application objects.

Upstream make regenerates tracked translation catalogs. After a verified clean
source checkout has been built, `build.sh` saves their diff and restores only
`po/*.po` and `po/vlc.pot`. Other tracked changes fail the build. This keeps
incremental checkouts clean while preserving the upstream build's generated
translation outputs in the payload; no application-source patch is applied.

## Task 2.1 packaging corrections

The source/configure/contrib sequence above is unchanged. Upstream's alias scripts
hard-code the installation prefix, so packaging makes just their executable path
relative and routes all public VLC entry points through one launcher. The original
ELF is moved to `bin/vlc.bin`; `exec -a` preserves its upstream argv[0]. No ELF
strings or debug information are rewritten. GnuTLS's supported environment
override selects the target runtime's optional `/etc/gnutls/config`, preserving
explicit user settings and normal built-in defaults when the file is absent.

VLC's default HRTF file is in `share/Makefile.am`'s `EXTRA_DIST` but is not
installed by upstream's make rules. The packaging helper retrieves that exact
file from the pinned Git commit into `share/vlc/hrtfs`, recording its hash.
This fixes missing runtime data without changing the HRTF selection or
substituting a different library dataset. See task-2.1-report.md for all nine
source-reviewed compiled defaults and the mandatory runtime traces.

`version` remains upstream's git-describe string. `artifact_version` appends the
packaging revision (`-r2`), used for filenames and release tags. Bump the revision
when changing already-published bytes for the same source. Local packaging refuses
existing output files; publishing refuses previous tags/assets. A legacy build
can be repackaged without recompilation using `scripts/repackage.py`; it preserves
the old binary inputs and records the original archive SHA and every unchanged
ELF hash. Normal CI still builds upstream source using the existing build scripts.

## Task 2.2 update identities

Runtime-path review is content-bound, rather than bound to one VLC commit.
`verification/runtime-path-policy.json` records 55 relevant committed source
files and four local build/packaging recipe files. Resolution records their
actual hashes and requires equality with the reviewed policy; the build
recomputes them before compilation/cache use. Unrelated upstream commits can
advance without a policy edit. Changed callers, dependency recipes/checksums,
common path/configuration code or unknown compiled paths/consumers still fail
closed. Constructor, filesystem, SOFA/data and relocation gates remain mandatory.
The policy is never regenerated automatically in CI. Selected-file changes
(including comments) conservatively require review; this is not semantic analysis.

`scripts/qt_identity.py` inspects official signed OSTree commits for Core, Gui,
Quick and Qml libraries and their SDK private-header trees. It fetches only
these Qt libraries, SONAME links and config-header anchors into the existing
OSTree store, without installing another SDK or executing foreign architecture
code. The objects are reused on subsequent native SDK installation. `ostree` is
an orchestration CLI in the existing container, not another build framework.
A normal Flatpak client User-Agent avoids an observed public-CDN rejection;
checksums and commit signature verification remain enabled.

The Qt identity excludes enclosing SDK/runtime commit metadata and includes the
actual tracked Qt module objects, versions and private-header tree IDs. The input
lock separately retains full SDK/Platform revisions. SDK/Platform versions and
private Qt builds must match; a temporary out-of-sync pair blocks before a build.
Each native job rechecks the deployed Qt identity and then checks every Qt ELF
import against the target Platform using SDK tools. Private imports additionally
require the exact compiled Qt version and a tracked, matching private provider.
The actual Platform eager-loader check remains independent.

Artifact versions are now `<upstream-version>-r2-qt<16-hex-pair-identity>`; Qt
changes select new immutable names even for the same VLC commit. Release lookup
compares the full ABI identity and build recipe in the existing release's input
lock before skipping it. Hash-prefix collisions/conflicting inputs fail rather
than replace assets. Non-Qt deployment-metadata changes leave the Qt identity
and existing release unchanged. This is conservative Qt-content tracking, not
a claim that equal exported symbol names prove private C++ layout compatibility.

Existing contrib cache keys are deliberately preserved: they already pin the
architecture, full SDK/toolchain and runtime revisions plus contrib/tools/flags.
The new Qt data is a separate top-level field, so unchanged compatible inputs
retain their keys. SDK revision changes can still conservatively miss contrib
cache even if only Qt changed; no cache migration or equivalence framework was
introduced. VLC object paths retain that compatibility key and source SHA.

A public personal repository satisfies the maintainer's updated ownership
guidance. Release API paths use `GITHUB_REPOSITORY`; recipe/run links also use
`GITHUB_SERVER_URL` and workflow context. No organization-specific release host
is required. See task-2.2-report.md for the pinned PR comparison and actual tests.
