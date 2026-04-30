#include "qemu_vram.h"

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

void qemu_vram_mirror(const uint8_t *px_map, int width, int height, int dst_y)
{
    const uint16_t *src = (const uint16_t *)px_map;
    volatile uint16_t *dst = QEMU_RGB_VRAM_ADDR;
    for (int row = 0; row < height; row++) {
        for (int col = 0; col < width; col++) {
            dst[(dst_y + row) * QEMU_RGB_SURFACE_W + col] =
                src[row * width + col];
        }
    }
}

void qemu_vram_gradient_loop_forever(int width, int height)
{
    volatile uint16_t *vram = QEMU_RGB_VRAM_ADDR;
    uint32_t phase = 0;
    while (1) {
        for (int row = 0; row < height; row++) {
            for (int col = 0; col < width; col++) {
                /* Diagonal RGB565 gradient that scrolls with `phase`. Mixes
                 * R/G/B channels so the live mirror always has many unique
                 * colours (auto-test threshold = 8). */
                uint8_t r = (uint8_t)((col + phase) & 0x1F);
                uint8_t g = (uint8_t)((row * 2 + phase / 2) & 0x3F);
                uint8_t b = (uint8_t)((col + row + phase) & 0x1F);
                vram[row * QEMU_RGB_SURFACE_W + col] =
                    (uint16_t)((r << 11) | (g << 5) | b);
            }
        }
        phase += 2;
        vTaskDelay(pdMS_TO_TICKS(33));   /* ~30 fps */
    }
}
