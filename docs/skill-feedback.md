# Skill / Workflow Feedback

Running log of issues, gaps, and improvement ideas surfaced during the daily
iteration. Append-only — entries are not deleted once recorded.

### FB-001 (2026-04-30)
- **Skill**: tools/run-qemu.sh + daily-iteration
- **Category**: improvement
- **Summary**: `idf.py qemu` always re-runs build action; first run after a
  source touch can blow past a 75 s timeout.
- **Detail**: `run-qemu.sh 75 verify` failed cold today because `idf.py qemu`
  triggered a CMake reconfigure and consumed the whole budget before QEMU
  even started. Existing `conftest.py` already uses 180 s for the first
  boot, which works.
- **Workaround**: invoke `run-qemu.sh 150 verify` (or higher) when running
  manually after source/sdkconfig touches; tests are unaffected.
- **Priority**: low
