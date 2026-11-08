> Historical policy: rapid OpenUri/Quit is now an optional diagnostic. The
> current core release gate does not need or apply this waiver. Its original
> policy and expiration below are retained unchanged as historical evidence.

# Temporary ARM64 X11 rapid-quit waiver

The explicitly enabled policy is [verification/x11-waiver.json](../verification/x11-waiver.json):

| Field | Value |
| --- | --- |
| ID | `VLC-X11-RAPID-QUIT-AARCH64-2026-11` |
| Effective | `2026-11-02T00:00:00Z`, inclusive |
| Expiry | `2026-11-16T00:00:00Z`, exclusive |
| Architecture | `aarch64` only |
| Test | `xcb-gui-openuri-quit-rapid` only |
| Raw exit | exactly integer `134` |
| Assertion | `CompositorX11::quickWindow()` asserting `m_qmlView` |

The JSON `enabled: true` is the explicit, reviewed activation requested for this
14-calendar-day period. There is no environment override for time, expiry or
signature. UTC is read at actual native verification and again at pair
verification (including the check performed by publish.sh). An old WAIVED report
cannot authorize publication after expiry. PASS reports need no waiver, even
after expiry. Existing published historical releases are not rewritten.

There is no VLC SHA allowlist: each application records its exact pinned source
commit. Normal source, downstream patch, Qt, deployment, archive, ELF, runtime,
relocation and playback checks remain prerequisites; changed upstream source is
accepted only through the existing approved source/build policies. The waiver
never overrides those policies or makes unreviewed source valid.

## Evidence and outcomes

The rapid test still runs with its original immediate OpenUri/Quit sequence.
Its raw mandatory check remains `status: fail`. The GUI controller separately
records the actual exit code, execution and playback prerequisites, and the
SHA-256 of its real log. The architecture-qualified log is copied to dist/ so
pair verification reads the original evidence rather than trusting an assertion
string in the report. Missing logs, wrong hashes, incomplete signatures,
additional assertions, other fatal GUI errors, missing playback evidence,
different exit codes and all other mandatory failures are rejected.

`automated_status` is `pass`, `waived` or `fail`, displayed as PASS, WAIVED or FAIL.
`automated_decision.waiver` records ID, source SHA, architecture, test, exit,
assertion lines, log name/hash, evaluation time, effective/expiry timestamps,
policy hash and decision. A waived native run is only conditionally eligible:
pair verification still requires every mandatory x86_64 check to pass, all
other ARM64 checks to pass, and all existing provenance/pair checks to succeed.
The test is never reported as PASS when it crashed.

`verification-pair.json` labels the pair PASS or WAIVED and lists known issues;
a failed re-evaluation leaves a FAIL summary rather than a stale WAIVED summary.
Release notes, if publication is separately authorized in the future, explicitly
identify the upstream ARM64 X11 rapid-quit crash and waiver expiry. The pair
summary and raw logs are included in the explicit release asset list. Phase 3 replaces the old unconditional disable with trusted-main, native/pair,
signed-attestation and production-environment gates. `VLC_PUBLICATION_APPROVED`
and raw `release_ready: false` remain separate from waiver eligibility. The waiver grants **no publication authorization**.

## Validation and removal

Run focused tests without VLC compilation:

```sh
python3 -m unittest discover -s verification -p test_waiver.py
python3 -m unittest discover -s verification -p test_pair.py
```

The complete unit suite also covers unchanged Qt/provenance/runtime-path/archive
checks. No old verification reports are upgraded or backfilled. New native
verification must produce the structured evidence; old failed reports remain
failed historical evidence.

After an upstream fix, verify the rapid test passes on both native architectures
and set `enabled` to false. Keep this document/policy as the historical record,
or remove the evaluator integration in a separate reviewed cleanup. A passing
test already produces PASS without applying any waiver. No manual expiry action
is needed: failures are automatically blocking from November 16 at 00:00 UTC.

Local implementation validation: **104 unit tests passed**, including 16 focused
waiver cases and 20 ordinary/waived pair cases. The exact assertion from
`diagnostics-aarch64 (2).zip` matches the policy; its old report still fails
because missing structured evidence was not backfilled. Python/Bash syntax,
ShellCheck for publish.sh/verify.sh, workflow YAML and the disabled-publication
condition passed. actionlint is unavailable in the existing environment.
No VLC/native GUI tests were rerun, no binaries rebuilt and no CI dispatched.
