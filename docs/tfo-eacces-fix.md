# TCP Fast Open fallback correction

The build carries one approved downstream patch:
[vlc-tfo-eacces.patch](../patches/vlc-tfo-eacces.patch). It was introduced in
packaging revision 3 and remains in revision 4. These binaries are not unchanged
upstream VLC builds; upstream acceptance of this correction is not claimed.

## Failure and correction

Original x86_64 and aarch64 CI traces showed actual VLC HTTP MP4/HLS requests:

```text
sendmsg(..., MSG_FASTOPEN | MSG_NOSIGNAL) = -1 EACCES
```

The newer HTTP transport closed the socket without ordinary TCP fallback.
The separate oldhttp module could connect, but that fallback did not provide
working MP4 seeking or HLS segment playback. The kernel/security policy that
returned EACCES was not established; do not attribute it to a particular sandbox.

In `src/network/stream.c`, `vlc_tls_ConnectWrite()` now handles EACCES through
its existing EOPNOTSUPP ordinary-connect/write fallback. Positive/partial sends
and EINPROGRESS handling are unchanged. Ordinary TCP permission denial still
fails, and no sandbox or production network permission is broadened.

## Provenance and regression checks

[patches/manifest.json](../patches/manifest.json) pins the patch SHA-256 and exact
source pre/post images. Resolution checks applicability without changing the
source checkout. Builds verify the clean pinned source, apply the locked patch,
and restore it only when the postimage still matches. Changed patch/source
content requires review rather than silently applying a fuzzy patch.

Input locks, build/native reports and published archives retain the patch
identity and bytes. Archive/pair checks enforce agreement. Patch identities also
separate incompatible VLC object directories; compatible contrib keys are not
invalidated solely by this transport change.

[The transport harness](../verification/tfo-transport-test.py) covers Fast Open
success/partial writes, EINPROGRESS, unsupported operation, EACCES recovery,
ordinary TCP denial and no duplicate payload. Source/patch unit tests reject
identity tampering. Run toolchain-dependent tests inside the existing KDE SDK;
do not rebuild VLC solely for this focused harness. Optional HTTP/HLS diagnostics
exercise actual media playback separately from these transport tests.
