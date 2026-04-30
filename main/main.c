#include <stdio.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_system.h"
#include "esp_heap_caps.h"
#include "lvgl.h"
#include "demos/lv_demos.h"

static const char *TAG = "app_main";

#define DISP_HOR_RES 240
#define DISP_VER_RES 135
#define DISP_PIXELS  (DISP_HOR_RES * DISP_VER_RES)
#define DISP_BYTES   (DISP_PIXELS * 2)  /* RGB565 */

/* Number of LVGL ticks (10 ms each) — ≥3 s gives benchmark room to log a summary */
#define LVGL_LOOP_CYCLES 600
#define LVGL_LOOP_DELAY_MS 10

/* Capture frame number — chosen to be after layout settles but before we hit cycle cap.
 * Benchmark renders ~144 flushes total in ~7 s; capturing at #80 lands mid-scene
 * with both a benchmark scene and the SYSMON/perf overlay drawn. */
#define CAPTURE_FLUSH_INDEX 80

static volatile uint32_t s_flush_count = 0;
static volatile bool s_benchmark_done = false;
static volatile bool s_fb_dumped = false;

/* Full-screen framebuffer allocated at runtime (heap) — placing 64 KB in
 * .bss overflows ESP32's dram0_0_seg. Heap allocation also lets us release
 * it later if memory pressure rises during the benchmark. */
static lv_color_t *s_fb = NULL;

static const char b64_alphabet[] =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

/* Emit base64 of buffer to stdout in 60-char lines, surrounded by sentinels.
 * Designed to be parseable from a serial log: lines starting with FB= contain payload. */
static void dump_framebuffer_base64(const uint8_t *data, size_t len)
{
    printf("\n<<<FB_BEGIN size=%u w=%d h=%d fmt=RGB565>>>\n",
           (unsigned)len, DISP_HOR_RES, DISP_VER_RES);

    char line[64 + 8];  /* up to 60 b64 chars + "FB=" prefix + NUL */
    size_t lp = 0;
    line[lp++] = 'F'; line[lp++] = 'B'; line[lp++] = '=';
    const size_t prefix = lp;

    for (size_t i = 0; i < len; i += 3) {
        uint32_t b0 = data[i];
        uint32_t b1 = (i + 1 < len) ? data[i + 1] : 0;
        uint32_t b2 = (i + 2 < len) ? data[i + 2] : 0;
        uint32_t triple = (b0 << 16) | (b1 << 8) | b2;

        line[lp++] = b64_alphabet[(triple >> 18) & 0x3F];
        line[lp++] = b64_alphabet[(triple >> 12) & 0x3F];
        line[lp++] = (i + 1 < len) ? b64_alphabet[(triple >> 6) & 0x3F] : '=';
        line[lp++] = (i + 2 < len) ? b64_alphabet[triple & 0x3F] : '=';

        if (lp >= prefix + 60) {
            line[lp] = '\0';
            puts(line);
            lp = prefix;
        }
    }
    if (lp > prefix) {
        line[lp] = '\0';
        puts(line);
    }
    /* Brief settle so the UART FIFO drains before the END marker */
    vTaskDelay(pdMS_TO_TICKS(50));
    printf("<<<FB_END>>>\n");
}

/* QEMU `esp_rgb` virtual display VRAM lives at this fixed address; matches
 * Espressif's `esp_lcd_qemu_rgb` driver constant. The device surface is
 * fixed at ESP_RGB_MAX_WIDTH x ESP_RGB_MAX_HEIGHT (800x600) so we render at
 * top-left with a row-stride that skips the rest of the line. Harmless on
 * real hardware (this region is unmapped MMIO) since we never run there. */
#define QEMU_RGB_VRAM_ADDR    ((volatile uint16_t *)0x20000000U)
#define QEMU_RGB_SURFACE_W    800
/* Y-offset for the frozen snapshot region (well below the live mirror). */
#define QEMU_RGB_SNAPSHOT_Y   200

/* Copy a 240x135 RGB565 frame from LVGL into the QEMU virtual framebuffer.
 * `dst_y` selects the destination row inside the 800x600 surface so we can
 * keep both a "live mirror" at y=0 (overwritten every flush) and a "frozen
 * snapshot" at y=QEMU_RGB_SNAPSHOT_Y (written only at CAPTURE_FLUSH_INDEX,
 * matching the UART base64 dump for byte-for-byte comparability). */
static void mirror_to_qemu_vram(const uint8_t *px_map, int dst_y)
{
    const uint16_t *src = (const uint16_t *)px_map;
    volatile uint16_t *dst = QEMU_RGB_VRAM_ADDR;
    for (int row = 0; row < DISP_VER_RES; row++) {
        for (int col = 0; col < DISP_HOR_RES; col++) {
            dst[(dst_y + row) * QEMU_RGB_SURFACE_W + col] =
                src[row * DISP_HOR_RES + col];
        }
    }
}

static void disp_flush_cb(lv_display_t *disp, const lv_area_t *area, uint8_t *px_map)
{
    if (s_flush_count < 3) {
        ESP_LOGI(TAG, "lvgl flush #%lu: area=(%d,%d)-(%d,%d)",
                 (unsigned long)s_flush_count,
                 (int)area->x1, (int)area->y1, (int)area->x2, (int)area->y2);
    }

    /* Live mirror at (0, 0): every flush overwrites this region so any host
     * tool with the file mmap'd sees the latest LVGL frame in real time. */
    mirror_to_qemu_vram(px_map, 0);

    /* Capture the framebuffer once after layout has settled. With FULL render
     * mode, px_map is the entire DISP_HOR_RES * DISP_VER_RES buffer. */
    if (!s_fb_dumped && s_flush_count == CAPTURE_FLUSH_INDEX) {
        ESP_LOGI(TAG, "capturing framebuffer at flush #%d (%d bytes)",
                 CAPTURE_FLUSH_INDEX, DISP_BYTES);
        /* Frozen snapshot at y=QEMU_RGB_SNAPSHOT_Y: never overwritten, so it
         * holds exactly the same pixels we base64-dump to UART. The host can
         * then assert byte-for-byte equality between the two transports. */
        mirror_to_qemu_vram(px_map, QEMU_RGB_SNAPSHOT_Y);
        dump_framebuffer_base64(px_map, DISP_BYTES);
        s_fb_dumped = true;
        ESP_LOGI(TAG, "framebuffer dump complete");
    }

    s_flush_count++;
    lv_display_flush_ready(disp);
}

static uint32_t my_tick_get_cb(void)
{
    return (uint32_t)esp_log_timestamp();
}

static void benchmark_end_cb(const lv_demo_benchmark_summary_t *summary)
{
    (void)summary;
    s_benchmark_done = true;
    ESP_LOGI(TAG, "lv_demo_benchmark end_cb fired");
}

void app_main(void)
{
    ESP_LOGI(TAG, "========================================");
    ESP_LOGI(TAG, "  esp32-display-qemu-demo starting...");
    ESP_LOGI(TAG, "========================================");

    ESP_LOGI(TAG, "free heap before lvgl: %u bytes",
             (unsigned)heap_caps_get_free_size(MALLOC_CAP_DEFAULT));

    lv_init();
    ESP_LOGI(TAG, "lvgl initialized: v%d.%d.%d",
             lv_version_major(), lv_version_minor(), lv_version_patch());

    lv_tick_set_cb(my_tick_get_cb);

    lv_display_t *disp = lv_display_create(DISP_HOR_RES, DISP_VER_RES);

    s_fb = heap_caps_malloc(DISP_BYTES, MALLOC_CAP_DEFAULT | MALLOC_CAP_8BIT);
    if (!s_fb) {
        ESP_LOGE(TAG, "failed to allocate %d-byte framebuffer", DISP_BYTES);
        return;
    }
    /* FULL render mode: flush_cb gets the entire framebuffer each call,
     * which is what we need for a clean screenshot capture. */
    lv_display_set_buffers(disp, s_fb, NULL,
                           DISP_BYTES, LV_DISPLAY_RENDER_MODE_FULL);
    lv_display_set_flush_cb(disp, disp_flush_cb);
    ESP_LOGI(TAG, "lvgl display created: %dx%d (FULL render, fb=%d bytes)",
             DISP_HOR_RES, DISP_VER_RES, DISP_BYTES);

    /* Launch the benchmark demo */
    lv_demo_benchmark_set_end_cb(benchmark_end_cb);
    lv_demo_benchmark();
    ESP_LOGI(TAG, "lv_demo_benchmark started");

    /* Drive LVGL until benchmark signals end OR loop cap reached */
    for (int i = 0; i < LVGL_LOOP_CYCLES && !s_benchmark_done; i++) {
        lv_timer_handler();
        vTaskDelay(pdMS_TO_TICKS(LVGL_LOOP_DELAY_MS));
    }

    ESP_LOGI(TAG, "lvgl flush total: %lu", (unsigned long)s_flush_count);
    ESP_LOGI(TAG, "framebuffer dumped: %s", s_fb_dumped ? "yes" : "NO");
    ESP_LOGI(TAG, "free heap after demo: %u bytes",
             (unsigned)heap_caps_get_free_size(MALLOC_CAP_DEFAULT));

    ESP_LOGI(TAG, "========================================");
    ESP_LOGI(TAG, "  M3 LVGL benchmark demo complete");
    ESP_LOGI(TAG, "========================================");
}
