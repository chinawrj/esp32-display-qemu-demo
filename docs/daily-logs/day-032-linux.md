# Day 032 - 2026-05-05 (Linux)

## Morning Planning

### Yesterday Review

- Completed: Day 31 added `summary.tsv` output to the basic Wi-Fi smoke gate.
- Completed: Runtime smoke gate passed station, scan, and softAP with `3 passed, 0 failed`.
- Completed: Full non-runtime suite passed with `161 passed, 6 skipped`.

### Today Goals

1. Documentation freeze: create the stock ESP-IDF Wi-Fi sample release guide.
2. TEST: add non-runtime coverage for required documentation sections and commands.
3. Release readiness: verify the docs and smoke tooling remain aligned.

### Risks And Dependencies

- Keep the guide focused on basic STA/SCAN/AP instead of expanding release scope.
- Ensure commands match the actual helper scripts and current verify profiles.
- Known limits must be explicit enough for a formal release candidate.

### Acceptance Checkpoints

- [x] `docs/qemu-wifi-stock-samples.md` exists.
- [x] The guide documents prerequisites, build/run commands, expected logs, and known limits.
- [x] The guide includes station, scan, and softAP release samples.
- [x] Non-runtime tests cover the documentation contract.
- [x] Runtime smoke gate passes using the documented command.
- [x] Full non-runtime suite passes.
- [ ] `git status --short` is clean after commit.

## Execution Notes

- Added `docs/qemu-wifi-stock-samples.md` as the Day 32 release-facing guide.
- The guide documents the one-command release gate and the per-sample build/run commands for station, scan, and softAP.
- Added README discoverability for the stock sample release guide.
- Added non-runtime tests that require the guide to cover supported samples, verifier profiles, expected logs, known limits, and `summary.tsv`.

## Verification

- Focused documentation tests: `4 passed`.
- Full non-runtime suite: `165 passed, 6 skipped`.
- Runtime smoke gate: `3 passed, 0 failed` with `LOG_DIR=/tmp/day32-basic-wifi-smoke`.
- Generated summary: `/tmp/day32-basic-wifi-smoke/summary.tsv`.

```text
sample  profile build   run     build_log       run_log serial_log
station station ok      ok      /tmp/day32-basic-wifi-smoke/station-build.log   /tmp/day32-basic-wifi-smoke/station-run.log       /tmp/day32-basic-wifi-smoke/station-serial.log
scan    scan    ok      ok      /tmp/day32-basic-wifi-smoke/scan-build.log      /tmp/day32-basic-wifi-smoke/scan-run.log  /tmp/day32-basic-wifi-smoke/scan-serial.log
softAP  softap  ok      ok      /tmp/day32-basic-wifi-smoke/softAP-build.log    /tmp/day32-basic-wifi-smoke/softAP-run.log        /tmp/day32-basic-wifi-smoke/softAP-serial.log
```

## Wrap-up

- Day 32 documentation freeze is complete for the basic STA/SCAN/AP release plan.
- No new skill/workflow feedback was found today.