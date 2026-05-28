---
applyTo: "components/esp_wifi_qemu/**,tools/qemu-src-patches/hw/net/**,tools/qemu-src-patches/include/hw/net/**"
---

# Wi-Fi Shim Instructions

The QEMU Wi-Fi shim exists to let stock ESP-IDF networking samples build and
run without modifying upstream `.c` or `.h` files.

Rules:

- Match ESP-IDF public API validation behavior before adding shim logic.
- Prefer real state round-trips over hardcoded fakes.
- Keep QEMU MMIO register changes mirrored between firmware headers and QEMU
  patch headers.
- Add or update source-analysis tests when closing an API gap.
- Do not special-case this repo's demo app if the stock sample API behavior is
  the real issue.
