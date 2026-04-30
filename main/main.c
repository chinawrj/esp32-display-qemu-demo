#include <stdio.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_system.h"
#include "esp_heap_caps.h"
#include "lvgl.h"
#include "demos/lv_demos.h"

#include "fb_dump.h"
#include "qemu_vram.h"

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

static void disp_flush_cb(lv_display_t *disp, const lv_area_t *area, uint8_t *px_map)
{
    if (s_flush_count < 3) {
        ESP_LOGI(TAG, "lvgl flush #%lu: area=(%d,%d)-(%d,%d)",
                 (unsigned long)s_flush_count,
                 (int)area->x1, (int)area->y1, (int)area->x2, (int)area->y2);
    }

    /* Live mirror at (0, 0): every flush overwrites this region so any host
     * tool with the file mmap'd sees the latest LVGL frame in real time. */
    qemu_vram_mirror(px_map, DISP_HOR_RES, DISP_VER_RES, 0);

    /* Capture the framebuffer once after layout has settled. With FULL render
     * mode, px_map is the entire DISP_HOR_RES * DISP_VER_RES buffer. */
    if (!s_fb_dumped && s_flush_count == CAPTURE_FLUSH_INDEX) {
        ESP_LOGI(TAG, "capturing framebuffer at flush #%d (%d bytes)",
                 CAPTURE_FLUSH_INDEX, DISP_BYTES);
        /* Frozen snapshot at QEMU_RGB_SNAPSHOT_Y: never overwritten, so it
         * holds exactly the same pixels we base64-dump to UART. The host can
         * then assert byte-for-byte equality between the two transports. */
        qemu_vram_mirror(px_map, DISP_HOR_RES, DISP_VER_RES, QEMU_RGB_SNAPSHOT_Y);
        fb_dump_base64(px_map, DISP_BYTES, DISP_HOR_RES, DISP_VER_RES);
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

    /* Day 23: keep the live mirror at y=0 content-rich for the interactive
     * Chrome demo. We deliberately do NOT touch LVGL after the benchmark —
     * its deferred teardown corrupts widget/heap state, and re-invoking
     * lv_demo_benchmark() resets the flush counter, breaking
     * test_qemu_boot / test_qemu_vram_file invariants. Direct VRAM writes
     * bypass LVGL entirely. The frozen snapshot at y=200 is preserved. */
    qemu_vram_gradient_loop_forever(DISP_HOR_RES, DISP_VER_RES);
}
