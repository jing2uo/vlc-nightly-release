# Phase 3 local implementation and manual handoff

## State and baseline

Work is local only, as requested after the initial Phase 3 authorization. No push,
workflow dispatch, GitHub Release or FlatPark notification was sent.

Public API evidence confirms successful run **41523505909**, repository main
**6b1b6f2398f0858bf3895c6a8a11afa6640fdb3f**: resolve, both native build/verification
jobs and pair verification succeeded; the old release job was skipped. Its
`release-candidate` artifact ID is **13181376064**, size 561563498 bytes. The
candidate itself requires authenticated download and was not available locally.
Therefore this task has not independently rehashed its payloads or revalidated
its exact archived reports. The supplied prior ARM64 archive confirms source
`8a47770f6333df6b60181329db5fdaad318bdb44`; the exact successful-run lock still
must be read during authenticated promotion. Do not substitute historical bytes.

A separate release worktree `vlc-nightly-phase3` is based on that current main;
the older dirty `vlc-nightly-release-new2` checkout is preserved. The FlatPark
checkout `flatpark-vlc-beta` uses the existing fork branch
`add/org.videolan.VLCBeta`, based on `edcef2bb7d41436e2a2c0e75efc82a45661b5d95`.
No unrelated Filee checkout is modified.

## Production controls

- Trusted main/run/repository/native-job/ancestor checks before promotion.
- Exact immutable Actions artifact ID; no VLC/contrib rebuild for promotion.
- Existing archive, provenance, Qt, source-path, native/pair and waiver gates.
- Fresh signed-OSTree Qt-content check against current Flathub deployments before
  promotion/publication, without a full SDK installation; stale/changed content
  blocks promotion. Unrelated deployment metadata alone does not block reuse.
- Existing waiver JSON and its expiry are unchanged.
- Production environment protections, explicit trusted-workflow authorization,
  scoped publication permissions and GitHub/Sigstore signed attestations.
- Draft-first upload, download/size/hash comparison, then fresh UTC gate before
  publication; no replacement, tag deletion or clobber.
- Truthful original build-run provenance when publication promotes old bytes.
- Two-week source cadence, weekly Qt compatibility checks, manual controls.
- Notifications explicitly conditional on FlatPark acceptance/association.

The old unconditional Phase 2 disable is replaced in the prepared workflow,
not silently bypassed. Raw native reports retain their original PASS/WAIVED/FAIL
and release_ready fields. Production authorization is an independent trusted
workflow/environment decision; a waiver alone cannot authorize publishing.

## Package integration

Current FlatPark documentation and maintainer comments require a public build
repository, a complete architecture-specific install tree, managed pins, KDE
6.11, offline extraction, a stable Flatpak branch, and support links to the build
repository. The implementation follows those requirements and keeps the app ID.
The existing downstream source correction differs from the maintainer's initial
"no changes to app behaviour" condition and must be disclosed for human review.
The package unpacks the published tree as-is; it injects no code or renderer fix.

The managed pin block is deliberately empty pending a real public Release.
There is no invented production URL/hash/size and no stale PPA pin. This branch
is not merge-ready until that block and metainfo release are populated and the
actual production payload is installed/tested. Run from the FlatPark root:

```sh
cd registry/org.videolan.VLCBeta
./resolve-update.sh > /tmp/vlc-update.json
cd ../..
node scripts/update-pins.mjs registry/org.videolan.VLCBeta/org.videolan.VLCBeta.yml \
  registry/org.videolan.VLCBeta/org.videolan.VLCBeta.metainfo.xml < /tmp/vlc-update.json
./scripts/check-apply-extra.sh org.videolan.VLCBeta
FLATPARK_VERIFY_KEEP=1 ./scripts/publish.sh --verify org.videolan.VLCBeta
```

The resolver accepts production development prereleases only with a complete,
consistent release.json and both exact assets/digests. It rejects drafts, test
channels, ambiguous payloads, mixed releases, malformed data and API errors. It
never writes pins itself. WAIVED feeds cannot introduce an expired exception as
a new FlatPark update; existing installed/pinned releases are not deleted.

## Local installed-app evidence

Without the new candidate or public assets, an explicitly labelled **historical
payload plumbing test** used the existing unmodified r2 archive
`vlc-4.0.0-dev-39603-gc7834066e2-r2-qt83e596ea4f40c119-x86_64.tar.zst`,
SHA-256 `2fd0e95cf57b12bbe78d6a62d18af4b256dff75febf6316dd3a3b75773f6cdf5`.
It was not promoted, relabelled as new, or given new build attestations.

The actual FlatPark scaffolding was built and installed from a local Flatpak
repository inside the established rootless Podman environment, using the real
KDE SDK/runtime and private Xvfb/PulseAudio/D-Bus session. Extraction checked the
download hash/size during install. Separate offline extraction was tested as
namespace uid 0, with all capabilities dropped and no network/proc.

The first local-file cases failed because the minimal container had no configured
XDG Music directory. Those logs remain intact. Configuring standard XDG Music
and Videos directories in the test-only outer profile fixed reachability without
changing package permissions. The same installed package was reused.

Final installed historical-payload checks: direct /app/extra layout, no nested
extra/extra, version and cvlc startup, real H.264/AAC, VP8/Vorbis, HTTP MP4 and HLS
GUI playback, MPRIS progress and bounded Pause/Play, video output and screenshots.
Additional installed tests passed multiple-file metadata transitions, ordinary
OpenUri playback, and PulseAudio capture: 491999 samples, RMS 2546.85, 997 Hz
amplitude 3173.13. This is PCM output evidence, not audible-quality certification.

Physical audio quality, GPU/Wayland, portals, native ARM64 installation, settings
persistence and the **exact new production asset** remain untested/unavailable.
Do not present this diagnostic run as production-candidate verification.

Raw evidence is in the preserved WORK_DIR under `logs/phase3/`, including initial
failure logs, configured rerun results and screenshots, offline extraction,
public API metadata, packaging audits and unit/static checks.

## Manual next steps

1. Upload the local release-repository commits to main using normal history.
2. In GitHub Actions dispatch VLC nightly with promote_run_id=41523505909 and
   publish=true; retain any configured production environment approval.
   The run revalidates the exact pair, signs it and publishes only if eligible.
   It will reject an expired waiver or unavailable/expired candidate.
3. Verify public release asset URLs, downloaded checksums/sizes and attestations.
4. Populate FlatPark pins using the resolver, run the reviewer installation
   playbook against those public assets, and upload the existing PR branch.
5. Provide the prepared PR summary and request maintainer review of the source
   correction and disclosed temporary exception. Do not merge upstream main.
6. Enable FLATPARK_ACCEPTED only after actual catalog association.

No publication or public install result is claimed in this local handoff.

## Final local validation

The release repository's full unit suite passed **118 tests**. Publication tests
use local GH/validator stubs and explicitly check signature rejection, altered
upload bytes, expiry during upload and non-main authorization; they are not an
actual hosted publication. Resolver fixtures passed **9 tests**. Python/Bash
syntax, ShellCheck, workflow YAML and official actionlint v1.7.12 passed. The
small actionlint configuration only declares the existing successful hosted
26.04 runner labels missing from that tool's catalog; it adds no self-hosting.

The current-runtime checker executed against real Flathub signed metadata and
Qt objects on November 2: Qt **6.11.3** for both architectures, content identities
matching the existing lock. It downloaded approximately 80 MiB of metadata/Qt
objects, not complete SDK deployments; no compiler/VLC/contrib stage ran.
The temporary installed test app and test remote were removed afterwards;
SDKs, original archives, logs, source trees and build caches remain preserved.
