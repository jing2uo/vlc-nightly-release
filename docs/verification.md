# Verification

The shared `pair.REQUIRED` set defines the native and dual-architecture release
checks. Core checks require PASS; skipped, missing or optional core evidence
fails closed. Archive/provenance/extraction safety, static path policy, ELF
architecture/dependencies/symbol resolution, Qt ABI/runtime compatibility,
startup/version/plugins and H.264/AAC decoding remain mandatory.

Default `scripts/verify.sh --backend=podman --headless` runs only the core.
`--diagnostics` adds the existing advanced suite; `--desktop`, `--external`
and `--trace-http` also opt into diagnostics. Their failures, unavailable tools,
missing logs and driver exceptions are recorded without affecting the core
result. Core failures still return nonzero. CI's manual `diagnostics` input
selects this coverage on both native runners; scheduled runs use core checks.
No GUI/audio/network fixture service is needed for a core run. Pair validation
requires only named core reports, and never turns an optional FAIL into PASS.
Signing, immutability, source/deployment/Qt identity checks and publication
permissions are unchanged. Flatpak installation/integration requirements are
unchanged. The historical waiver is unnecessary for current optional stress
results; its exact original time window remains unchanged for historical policy
coverage. A core PASS does not certify advanced Beta features.

Runtime-path source/configuration hashes in `inputs.json` describe the exact
pinned Git tree and build recipes. `metadata.py check` and build metadata
creation recollect and compare that evidence; tampering or source/recipe mismatch
fails. Native reports retain the same evidence and pair validation requires exact
agreement with the input lock and embedded build provenance. The old
`runtime-path-policy.json` hashes are an informational audit baseline: resolve
logs and native reports list changed, added and removed tracked files with hashes.
Source drift alone does not authorize new runtime paths. Known consumer/path
pairs remain narrowly classified; unknown paths, unsafe loader paths and missing
runtime dependencies still fail. Optional API/filesystem traces remain available
for deeper behavioral investigation; hashes alone do not prove runtime behavior.

## Commands and evidence

```sh
# Native core checks, using the matching input lock and archive in WORK_DIR.
scripts/verify.sh --backend=podman --headless
# Optional headless diagnostics.
scripts/verify.sh --backend=podman --headless --diagnostics
# Real local desktop and external HTTPS diagnostics.
scripts/verify.sh --backend=host --desktop --external
# Lightweight regression suite; no VLC compilation.
python3 -m unittest discover -s verification -p 'test_*.py'
# Pair validation: inputs.json, both archives and matching reports in one directory.
scripts/verify-artifacts.sh work/dist
```

Set `WORK_DIR=/absolute/path` for another persistent workspace. `--dist=...`
selects a candidate directory beneath WORK_DIR with its own matching input lock,
archives and metadata. Native architecture checks cannot be replaced with an
emulated run or a report from another artifact.

Reports and logs are under `WORK_DIR/verification/results/<UTC>-<arch>/`.
The current native reports are copied to `dist/verification-<arch>.json`.
Pair validation checks exact artifact bytes, source/SDK/runtime/Qt identities,
runtime-path evidence and matching verification recipes; a failed re-evaluation
invalidates an older successful pair summary. Publication authorization and signed
attestations remain separate requirements.

Advanced diagnostics retain real playback evidence: decoded frames/nonzero PCM,
GUI presentation and MPRIS progress, private PulseAudio output, relocation,
network requests, GnuTLS/SOFA probes and filesystem traces. Raw failures remain
failures with `mandatory: false`; they are never rewritten as successful tests.
Only diagnostic tracing requests Flatpak's development permission. Production
sandbox permissions and rendering settings are unchanged.

The old aarch64 rapid-quit waiver is unnecessary for the current optional stress
test. Its machine-readable policy and regression coverage remain in
`verification/`; no separate waiver narrative is needed. The upstream assertion
has not been fixed by making the test optional.

Core verification is not human visual/audio quality review, GPU/Wayland
certification, or an installed Flatpak integration test. FlatPark's installation
and reviewer requirements still apply independently. Do not label unavailable,
skipped or unexecuted diagnostics as passed.
