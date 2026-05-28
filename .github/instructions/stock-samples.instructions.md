---
applyTo: "tools/build-stock-sample.sh,tools/run-stock-qemu.sh,tools/run-basic-wifi-smoke.sh,tests/test_stock_sample_build.py,docs/qemu-wifi-stock-samples.md"
---

# Stock Sample Wrapper Instructions

Stock ESP-IDF sample compatibility is governed by the zero-source-diff rule:
do not edit upstream sample `.c` or `.h` files.

When extending the wrapper:

- Use generated wrapper CMake files, `SDKCONFIG_DEFAULTS`, or
  `EXTRA_SDKCONFIG_DEFAULTS`.
- Preserve sample-local assets, `components/`, embeds, partition CSVs, managed
  dependencies, and project-level CMake calls.
- Add a regression test in `tests/test_stock_sample_build.py` for each wrapper
  behavior that was broken once.
- Update `docs/qemu-wifi-stock-samples.md` when smoke-gate coverage changes.
