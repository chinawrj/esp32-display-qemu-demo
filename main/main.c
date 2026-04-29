#include <stdio.h>
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

/* Number of LVGL ticks (10 ms each) — ≥3 s gives benchmark room to log a summary */
#define LVGL_LOOP_CYCLES 300
#define LVGL_LOOP_DELAY_MS 10

static volatile uint32_t s_flush_count = 0;
static volatile bool s_benchmark_done = false;

static void disp_flush_cb(lv_display_t *disp, const lv_area_t *area, uint8_t *px_map)
{
    if (s_flush_count < 3) {
        ESP_LOGI(TAG, "lvgl flush #%lu: area=(%d,%d)-(%d,%d)",
                 (unsigned long)s_flush_count,
                 (int)area->x1, (int)area->y1, (int)area->x2, (int)area->y2);
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

    static lv_color_t buf1[DISP_HOR_RES * 20];
    static lv_color_t buf2[DISP_HOR_RES * 20];

    lv_display_t *disp = lv_display_create(DISP_HOR_RES, DISP_VER_RES);
    lv_display_set_buffers(disp, buf1, buf2,
                           sizeof(buf1), LV_DISPLAY_RENDER_MODE_PARTIAL);
    lv_display_set_flush_cb(disp, disp_flush_cb);
    ESP_LOGI(TAG, "lvgl display created: %dx%d", DISP_HOR_RES, DISP_VER_RES);

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
    ESP_LOGI(TAG, "free heap after demo: %u bytes",
             (unsigned)heap_caps_get_free_size(MALLOC_CAP_DEFAULT));

    ESP_LOGI(TAG, "========================================");
    ESP_LOGI(TAG, "  M3 LVGL benchmark demo complete");
    ESP_LOGI(TAG, "========================================");
}
