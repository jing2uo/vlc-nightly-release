# Confirmed CI transport failure and revision 3 correction

## Independent archive review

Both supplied archives were read directly:
`diagnostics-x86_64(1).zip` and `diagnostics-aarch64(1).zip`.
Their MP4 and HLS network traces contain real VLC sendmsg failures with flags
`0x20004000` (MSG_FASTOPEN | MSG_NOSIGNAL) and errno EACCES. Examples:

- x86_64 MP4: PID 6300, fd 3, timestamp 1793481611.169707.
- aarch64 MP4: PID 6245, fd 3, timestamp 1793481384.842806.
- x86_64 HLS: PIDs 6329/6346, EACCES on newer HTTP requests.
- aarch64 HLS: PIDs 6274/6291, EACCES on newer HTTP requests.

The same traces contain ordinary connect/SO_ERROR success for oldhttp; media
logs record fallback HTTP/1.0 responses and MP4 nonseekability / HLS segment
failure. Independent reachability is not a substitute for these playback gates.
The actor returning EACCES (kernel/security module/container policy) remains
unidentified. No permissions are changed to avoid that denial.

## Source correction and provenance

`patches/vlc-tfo-eacces.patch` changes only `vlc_tls_ConnectWrite()`'s fallback
predicate and comment in `src/network/stream.c`: EACCES joins EOPNOTSUPP in the
existing ordinary TCP connect/write path. Ordinary TCP denial still fails.
Positive/partial Fast Open sends and EINPROGRESS handling are unchanged.
The user authorized implementation after the proposal review; upstream
acceptance is not claimed. The upstream search is documented in
[the original review](proposals/tfo-eacces-review.md), whose proposal-only status
is historical and superseded by this implementation.

Fresh locks record `source_patches`, including base SHA, patch SHA-256, exact
pre/post source hashes, purpose and downstream origin. Resolution simulates the
patch in a disposable directory without changing the upstream checkout. An
unrelated upstream commit remains acceptable if the patched file's content is
unchanged; changed source or patch content fails closed pending review.

The build requires a clean source tree, applies exactly the locked patch,
verifies the exact resulting content, and restores that change on normal exit
only if it still matches. Unexpected edits remain errors. Generated gettext
changes retain their separate existing handling. The patch manifest and patch
are included in the payload. Archive verification checks actual patch bytes
against the lock and compares the policy against the repository manifest; pair
verification requires matching patch identities in both native reports.

Packaging revision is **3**, retaining the existing Qt identity suffix. r2
archives/locks are not upgraded or relabelled. Repackaging an archive without the
current patch identity is rejected. New locks must be resolved; existing input
locks and candidate files have deliberately not been modified.

Patch bytes participate in the recipe hash and patch identity separates new VLC
object directories. Existing compatible contrib/tools keys are unchanged: this
fix changes no contrib recipe, toolchain, Qt identity or deployment pin. The
runtime-path policy's build-recipe hash was reviewed and updated for the explicit
patch lifecycle, SDK regression stage, build-object namespace and published
patch files; all source classifications and runtime checks remain unchanged.

## ARM64 GUI findings and bounded control check

The ARM64 log eventually selects `xcb_render` after failed software OpenGL
candidates. Stale plugin entries are rejected and modules reloaded by VLC.
Those messages alone do not establish the failure. No renderer/plugin settings
are changed.

The recorded ordinary H.264 test observes Playing at position 0, then Paused at
83334 microseconds throughout. Its controller itself sends Pause on the first
Playing observation, before demonstrated playback progress; it neither records
D-Bus command failures nor verifies that Play actually resumed playback. This
is a demonstrated harness readiness/diagnostic defect, but does not establish
that VLC has no independent ARM64 issue.

The ordinary control check now waits for the existing playback threshold
(position >500 ms), sends Pause once, waits up to two seconds for Paused, sends
Play once, then requires Playing with advancing position within two seconds.
All command results are retained. A stuck or denied resume still fails. The
actual GUI/video, multiple-file, HTTP/HLS and rapid stress assertions are
unchanged. No arbitrary delay, retry-to-green, rendering workaround or lower
playback threshold is introduced. ARM64 success remains **unverified** until a
native run executes the amended harness.

## Executed validation and remaining work

- Pinned source/patch preimage and postimage verified without modifying the
  preserved source checkout or historical workspaces.
- Actual patched `vlc_tls_ConnectWrite` and `vlc_tls_Write` compiled in KDE SDK
  6.11 with deterministic syscall substitutes: Fast Open success, partial writes,
  EINPROGRESS, unsupported operation, EACCES recovery, direct and asynchronous
  TCP denial, unknown fatal errno, no duplicate payload and multiple iovecs pass.
- The identical regression harness rejects the original unpatched function.
- Unit tests cover source/patch tampering, changed relevant source, unrelated
  commits, exact postimages, asynchronous control success, stuck playback and
  D-Bus failure. Full suite results are in the completion report.

Full patched VLC compilation, real patched HTTP MP4/HLS/GUI playback and native
ARM64 verification have **not** run. The tiny SDK harness is not a substitute
for those required gates. No VLC/contrib rebuild, push, workflow dispatch,
publication or privileged execution was performed. The next step is fresh input
resolution followed by authorized native builds and the complete strict suite.

Final local check results: **75/75 unit tests passed** in the existing rootless
lint image. Python syntax, Bash syntax, workflow YAML/publication-lock checks
and diff whitespace checks passed. ShellCheck reports exactly the pre-existing
dynamic-source/externally-assigned-variable findings for build.sh; comparison
against HEAD finds no new warning. The verification wrapper passes ShellCheck.
actionlint remains unavailable in the existing lint environment.

A separate diagnostic lock was generated and validated from the cached pinned
SDK/Platform/Qt metadata at `logs/confirmed-ci/inputs-r3-preflight.json`. Its
artifact version is `4.0.0-dev-39603-gc7834066e2-r3-qt83e596ea4f40c119`.
The preflight verified recipe, source patch, Qt and runtime-path evidence and an
unchanged x86_64 contrib key. It is **not** evidence of a new binary build or a
new remote resolution; active `inputs.json` and existing candidates are untouched.

Archive review details/counts and source archive SHA-256 hashes are retained in
`logs/confirmed-ci/archive-findings.json`. Tests and transport evidence are saved
alongside it. The ARM64 findings remain pending native rerun, not reclassified as
passed or skipped.
