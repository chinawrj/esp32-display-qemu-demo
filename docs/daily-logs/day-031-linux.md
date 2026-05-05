# Day 031 - 2026-05-05 (Linux)

## Morning Planning

### Yesterday Review

- Completed: Day 30 added `tools/run-basic-wifi-smoke.sh` for the basic STA/SCAN/AP release gate.
- Completed: Blocking scan was hardened against event-register races.
- Completed: Runtime smoke gate passed all three samples.

### Today Goals

1. Release automation: make the basic Wi-Fi smoke gate produce a concise per-sample summary artifact.
2. TEST: add non-runtime coverage for the summary output contract.
3. Runtime: re-run the smoke gate and record the generated summary.

### Risks And Dependencies

- Keep the automation simple enough to inspect quickly during release candidate work.
- Do not widen release scope beyond station, scan, and softAP.
- Runtime remains tmux-managed because it builds and boots stock samples.

### Acceptance Checkpoints

- [x] `tools/run-basic-wifi-smoke.sh` writes a summary artifact under `LOG_DIR`.
- [x] Summary includes sample, profile, build status, run status, and log paths.
- [x] Non-runtime tests cover the summary format.
- [x] Runtime smoke gate passes and produces a `summary.tsv` showing all three samples green.
- [x] Full non-runtime suite passes.
- [ ] `git status --short` is clean after commit.

## Execution Notes

- Added `SUMMARY_FILE`, defaulting to `${LOG_DIR}/summary.tsv`, to the basic Wi-Fi smoke gate.
- The summary records `sample`, `profile`, `build`, `run`, `build_log`, `run_log`, and `serial_log` for each release sample.
- Build failures are recorded with `run=skipped`; runtime failures are recorded with `run=fail`.

## Verification

- Focused summary tests: `4 passed`.
- Runtime smoke gate: `3 passed, 0 failed` with `LOG_DIR=/tmp/day31-basic-wifi-smoke`.
- Generated summary: `/tmp/day31-basic-wifi-smoke/summary.tsv`.

```text
sample  profile build   run     build_log       run_log serial_log
station station ok      ok      /tmp/day31-basic-wifi-smoke/station-build.log   /tmp/day31-basic-wifi-smoke/station-run.log       /tmp/day31-basic-wifi-smoke/station-serial.log
scan    scan    ok      ok      /tmp/day31-basic-wifi-smoke/scan-build.log      /tmp/day31-basic-wifi-smoke/scan-run.log  /tmp/day31-basic-wifi-smoke/scan-serial.log
softAP  softap  ok      ok      /tmp/day31-basic-wifi-smoke/softAP-build.log    /tmp/day31-basic-wifi-smoke/softAP-run.log        /tmp/day31-basic-wifi-smoke/softAP-serial.log
```

- Full non-runtime suite: `161 passed, 6 skipped`.

## Wrap-up

- Day 31 release automation is complete for the six-day basic STA/SCAN/AP release plan.
- No new skill/workflow feedback was found today.