---
applyTo: "tools/build-qemu.sh,tools/qemu-src-patches/**,tools/run-qemu.sh,tools/run-demo.sh,tools/run-direct-demo.sh,tests/cdp/**,tests/fb_server/**"
---

# QEMU Tools Instructions

Do not edit `tools/qemu-src/` as a source of truth. It is ignored and
regenerated.

Rules:

- Put tracked QEMU source additions under `tools/qemu-src-patches/`.
- Encode source edits to generated QEMU files as idempotent patches in
  `tools/build-qemu.sh`.
- Be careful with long-running QEMU subprocesses: tests and scripts must kill
  child emulators reliably and avoid stale `/tmp` artifacts.
- Browser/canvas tests should verify nonblank pixels and avoid depending on
  stale VRAM or serial logs.
