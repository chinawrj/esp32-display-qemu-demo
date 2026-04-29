#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_system.h"
#include "lvgl.h"

static const char *TAG = "app_main";

#define DISP_HOR_RES 240
#define DISP_VER_RES 135

/* Headless flush callback - logs flush events but doesn't render anywhere.
 * Sufficient for verifying LVGL initialization & render loop in QEMU. */
static void disp_flush_cb(lv_display_t *disp, const lv_area_t *area, uint8_t *px_map)
{
    static int flush_count = 0;
    if (flush_count < 3) {
        ESP_LOGI(TAG, "lvgl flush #%d: area=(%d,%d)-(%d,%d)",
                 flush_count, (int)area->x1, (int)area->y1, (int)area->x2, (int)area->y2);
    }
    flush_count++;
    lv_display_flush_ready(disp);
}

/* Provide a millisecond tick source for LVGL */
static uint32_t my_tick_get_cb(void)
{
    return (uint32_t)(esp_log_timestamp());
}

void app_main(void)
{
    ESP_LOGI(TAG, "========================================");
    ESP_LOGI(TAG, "  esp32-display-qemu-demo starting...");
    ESP_LOGI(TAG, "========================================");

    /* --- LVGL initialization --- */
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

    /* Create a simple "Hello LVGL" label on the active screen */
    lv_obj_t *label = lv_label_create(lv_screen_active());
    lv_label_set_text(label, "Hello LVGL\non ESP32 / QEMU!");
    lv_obj_align(label, LV_ALIGN_CENTER, 0, 0);
    ESP_LOGI(TAG, "lvgl label created");

    /* Drive the LVGL timer handler */
    for (int i = 0; i < 50; i++) {
        lv_timer_handler();
        vTaskDelay(pdMS_TO_TICKS(20));
    }

    ESP_LOGI(TAG, "========================================");
    ESP_LOGI(TAG, "  M2 LVGL smoke-test complete");
    ESP_LOGI(TAG, "========================================");
}
