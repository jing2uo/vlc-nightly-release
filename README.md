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
packaging revision is 3. A release contains exactly two versioned `.tar.zst`
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

To promote the already successful Phase 2.2 pair without recompilation, upload
this implementation to main, then dispatch **VLC nightly** with
`promote_run_id: 41523505909` and `publish: true`. The workflow authenticates the
source run, selects its immutable artifact ID, verifies its trusted ancestry,
revalidates both archived candidates, checks current Flathub Qt content without
deploying the SDK, and signs the exact promoted bytes. A changed Qt identity
requires a new compatible build instead of promotion.
Expired artifacts, mismatched origins or failed native jobs are rejected.
No tokens need to be pasted into scripts; hosted jobs use scoped GitHub tokens.

## Cadence and maintenance

The workflow wakes every Monday at 04:43 UTC. Starting November 2, 2026 it
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

The existing [PR #910](https://github.com/flatpark/flatpark/pull/910) is being
updated on its original fork branch. The package uses KDE Platform 6.11,
managed extra-data pins, offline extraction directly into `/app/extra`, and an
environment-only launcher that forwards arguments. Its read-only resolver
selects a complete production pair from one release, including eligible
production prereleases. FlatPark computes download hashes/sizes and updates
managed pins; incomplete feeds leave the known-good pin untouched.

The first pins must be populated from actual published bytes before the PR is
ready to merge. After FlatPark acceptance/publication, users can install
`org.videolan.VLCBeta` from FlatPark; it is **not currently advertised as live**.
Optional `flatpark/publish-action` notifications stay off until the repository
variable `FLATPARK_ACCEPTED=true` is set after catalog association. Polling works
independently of notifications.

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
certification. Installed FlatPark testing and actual tested/untested results are
recorded in the Phase 3 handoff. Historical reports remain in `docs/`.
