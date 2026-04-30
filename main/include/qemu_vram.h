#pragma once

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* QEMU `esp_rgb` virtual display VRAM lives at this fixed MMIO address (matches
 * Espressif's `esp_lcd_qemu_rgb` driver). The device surface is fixed at
 * 800x600 RGB565; we render a smaller LVGL frame at the top-left and use the
 * row-stride to skip the rest. Harmless on real hardware (this region is
 * unmapped MMIO) since this firmware is QEMU-only by design. */
#define QEMU_RGB_VRAM_ADDR    ((volatile uint16_t *)0x20000000U)
#define QEMU_RGB_SURFACE_W    800
/* Y-offset for the frozen-snapshot region (well below the live mirror at y=0). */
#define QEMU_RGB_SNAPSHOT_Y   200

/* Copy a `width`x`height` RGB565 frame from `px_map` into the QEMU virtual
 * framebuffer at row offset `dst_y`. Two destinations are useful:
 *   - dst_y = 0                  → live mirror (overwritten every flush)
 *   - dst_y = QEMU_RGB_SNAPSHOT_Y → frozen snapshot (written once, byte-equal
 *                                  to the UART base64 dump). */
void qemu_vram_mirror(const uint8_t *px_map, int width, int height, int dst_y);

/* Forever loop painting a scrolling RGB565 gradient directly into the live
 * mirror region (y=0). Bypasses LVGL entirely so it stays safe to call after
 * `lv_demo_benchmark`'s teardown corrupts the LVGL heap (see Day 23 notes in
 * docs/qemu-native-fb.md and skill-feedback FB-002). Never returns. */
void qemu_vram_gradient_loop_forever(int width, int height);

#ifdef __cplusplus
}
#endif
