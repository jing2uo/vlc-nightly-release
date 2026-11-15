# VLC 4 development builds

Community-maintained VLC 4 development builds for FlatPark's
[`org.videolan.VLCBeta`](https://flatpark.org/apps/org.videolan.VLCBeta/),
with native x86_64 and aarch64 releases. These are not official VideoLAN binary
releases and are separate from Flathub's stable VLC package.

## [!IMPORTANT]

#### Issue Reporting: Report issues here first. Contact VideoLAN only for confirmed upstream bugs.

#### Transparency & Security: Built through public GitHub Actions with traceable sources and immutable releases. Flatpak sandboxing limits permissions when installed as a Flatpak. These safeguards reduce risks.

## Builds and provenance

The resolver pins one VLC master commit for native x86_64 and aarch64, both KDE
SDK/Platform 6.11 OSTree deployments, and their Qt content identities. VLC uses
its own `extras/tools` and source-built contrib dependencies. Qt 6 and KF6 come
from KDE; no Ubuntu package tree is resolved or bundled.

VLC's GUI uses private Qt API. Real symbol-resolution gates run against the
Platform, and changed Qt content generates a new release identity even when the
VLC source commit stays the same. Unrelated runtime metadata does not alone
force a rebuild. Exact identities are in `inputs.json` and `build-<arch>.json`.

One reviewed downstream correction permits ordinary TCP fallback when Fast Open
returns EACCES. It does not expand sandbox permissions. The exact patch and
source pre/post hashes are published and embedded; these builds must not be
represented as unchanged upstream source. See [the correction](docs/tfo-eacces-fix.md).

```sh
WORK_DIR=/absolute/persistent/work scripts/run-container.sh resolve
WORK_DIR=/absolute/persistent/work JOBS=2 scripts/run-container.sh build x86_64
WORK_DIR=/absolute/persistent/work scripts/verify.sh --backend=podman --headless
```

Use a native ARM64 runner for aarch64 and the same resolved lock for both.
Fedora toolchains remain inside the KDE SDK under rootless Podman. Host-managed
Flatpak remains the fallback when nested user namespaces do not work. Persistent
source/contrib/SDK caches are retained; incompatible binary outputs are rejected.

## Production releases

Versions are `4.0.0-dev-<count>-g<sha>-r<revision>-qt<identity>`; the current
packaging revision is 4. Staged ELF executables, libraries and plugins, including
contrib libraries, are stripped with `strip --strip-unneeded` before packaging;
dynamic runtime symbols are retained. A release contains exactly two versioned `.tar.zst`
payloads, `SHA256SUMS`, `sizes.json`, `inputs.json`, both build/verification
reports, `verification-pair.json`, `release.json`, a fresh `current-runtime.json`, the signed
`provenance.intoto.jsonl`, and relevant crash evidence. GitHub marks development
releases as prereleases; `release.json` distinguishes the production channel
from internal candidates.

Archives have one top-level `extra/` application tree intended for `/app/extra`.
The included launcher handles VLC libraries/plugins/data and GnuTLS; Qt/QML
remain in the runtime. Asset names and tag URLs are versioned and immutable.
Existing tags/assets are never replaced. A failed upload remains a draft for
investigation; it is not overwritten or published partially.

After publication, verify downloads with:

```sh
sha256sum -c SHA256SUMS
# For each downloaded payload and release.json:
gh attestation verify <file> --repo rhgKc2yp/vlc-nightly-release
```

The attestation signs publication bytes and workflow provenance. When promoting
an existing candidate it does **not** claim to have rebuilt VLC. The original
build run, recipe, source and deployment identities remain in the metadata.

### Publishing and promotion

A trusted `main` workflow must pass native and pair gates, produce signed
attestations and satisfy the `production` environment's configured protection
rules. Only publication has `contents: write`. UTC waiver validity is checked
again after uploading/verifying draft bytes, immediately before publication.
A manual dispatch can disable publication with `publish: false`.

For a normal build and release, dispatch **VLC nightly** with `publish: true`
(and an optional upstream SHA). To promote an existing eligible pair without
recompilation, set `promote_run_id` to its successful trusted main workflow run.
The workflow authenticates the source run, selects its immutable artifact ID,
revalidates both candidates, checks current Flathub Qt content without deploying
the SDK, and signs the exact promoted bytes. A changed Qt identity requires a
new compatible build instead of promotion.
Expired artifacts, mismatched origins or failed native jobs are rejected.
No tokens need to be pasted into scripts; hosted jobs use scoped GitHub tokens.

## Cadence and maintenance

A dedicated runtime watcher checks KDE SDK/Platform 6.11 on both architectures every 12 hours (05:17 and 17:17 UTC), comparing Qt libraries, private headers, QML modules and runtime plugin content against the latest production release without deploying the SDK. Relevant changes enter the existing two-architecture build and verification pipeline using the production VLC source SHA. Unchanged content skips resolution and builds; incompatible SDK/Platform pairs fail closed and are retried at the next check. Watcher identities and rebuild decisions are recorded in CI logs. The weekly source workflow wakes every Monday at 04:43 UTC. Starting November 2, 2026 it
selects a new VLC snapshot every **two weeks**. Off-weeks reuse the last
production source SHA while resolving current SDK/Qt identities, allowing an
urgent Qt compatibility rebuild without waiting for the next source snapshot.
Manual source pins and promotion remain available.

When a gate fails the release is withheld and the previous public release
remains intact. Artifacts and diagnostics are retained for 30 days. Maintainers
or an external Bot can inspect those logs and submit ordinary fixes; no gate is
automatically relaxed. Build-affecting recipe changes require an appropriate
packaging revision; publication-only changes are checked against actual tracked
build inputs before an immutable completed release is reused.

## FlatPark

VLC 4 Beta is [published on FlatPark](https://flatpark.org/apps/org.videolan.VLCBeta/).
[PR #910](https://github.com/flatpark/flatpark/pull/910) was merged on
November 9, 2026. Install from the public remote:

```sh
flatpak remote-add --user --if-not-exists flatpark https://dl.flatpark.org/flatpark.flatpakrepo
flatpak install --user flatpark org.videolan.VLCBeta
flatpak run org.videolan.VLCBeta
```

Or open the official
[Flatpak installer reference](https://dl.flatpark.org/org.videolan.VLCBeta.flatpakref)
in your software installer. Updates arrive through:

```sh
flatpak update --user org.videolan.VLCBeta
```

The package uses the stable Flatpak branch and KDE Platform 6.11, with managed
extra-data pins for both architectures. Flatpak downloads the exact versioned
GitHub Release archive, verifies its SHA-256 and size, and extracts it offline
directly into `/app/extra`. The launcher forwards command-line arguments.

FlatPark's resolver selects a complete production pair from one release,
including eligible production prereleases, and its updater refreshes download
hashes, sizes and metainfo. Incomplete feeds leave the known-good pin untouched.
The first catalog release is the stripped
[`4.0.0-dev-39705-g978212a42d-r4-qt83e596ea4f40c119`](https://github.com/rhgKc2yp/vlc-nightly-release/releases/tag/4.0.0-dev-39705-g978212a42d-r4-qt83e596ea4f40c119).

Report packaging and build issues in
[this repository](https://github.com/rhgKc2yp/vlc-nightly-release/issues) first.
Optional `flatpark/publish-action` notifications require the repository variable
`FLATPARK_ACCEPTED=true` after FlatPark confirms repository association; listing
availability alone does not establish that notifications are enabled. Polling
works independently of notifications.

## Tests and known limitations

Release-blocking checks on both native architectures cover archive integrity,
SHA-256/provenance/extraction safety, ELF architecture and dependency/symbol
resolution, Qt private ABI/runtime compatibility, static source-content/runtime
path safety, VLC startup/version, plugin loading, and real H.264/AAC decoding.
The pair gate also requires matching source, deployment and Qt identities,
verification recipes, artifact sizes and hashes. Signing, current-runtime checks,
immutable assets and independent publication authorization remain required.

Advanced tests are optional diagnostics: GUI/QML playback, MPRIS, HLS/HTTP,
WebM, PulseAudio, rapid OpenUri/Quit, relocation, and GnuTLS/SOFA/filesystem
tracing. Run `scripts/verify.sh --diagnostics` (add `--desktop` for a local
session), or enable the manual workflow's `diagnostics` input. Raw failures and
logs remain visible with `mandatory: false`; missing diagnostic reports do not
block releases. Optional success is not claimed when tests were not run.

The historical aarch64 rapid-quit waiver is no longer needed by the core gate.
Its original policy and expiry are retained for historical report evaluation;
the upstream crash has not been fixed by this gate change. Installed Flatpak
integration requirements remain separate and unchanged.

Automated CI is not human playback-quality, physical audio, real GPU or Wayland
certification. See [verification](docs/verification.md) for coverage and diagnostic
commands, and [architecture](docs/architecture.md) for build inputs and caches.
Historical implementation reports are available in Git history; build/test logs
remain in the persistent workspace and published workflow artifacts.
