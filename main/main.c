#include <stdio.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/event_groups.h"
#include "esp_log.h"
#include "esp_system.h"
#include "esp_heap_caps.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "nvs_flash.h"
#include "lwip/ip4_addr.h"
#include "lvgl.h"
#include "demos/lv_demos.h"

#include "fb_dump.h"
#include "qemu_vram.h"
#include "wifi_ui.h"
#include "lwip_probe.h"

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

/* ---------------------------------------------------------------------------
 * Wi-Fi — connection state
 * ------------------------------------------------------------------------ */
#define WIFI_CONNECTED_BIT BIT0
#define WIFI_FAIL_BIT      BIT1

static EventGroupHandle_t s_wifi_event_group;

static void demo_wifi_event_handler(void *arg, esp_event_base_t event_base,
                                    int32_t event_id, void *event_data)
{
    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
        wifi_ui_set_status("Wi-Fi: connecting...");
    } else if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        esp_wifi_connect();
        wifi_ui_set_status("Wi-Fi: reconnecting...");
        ESP_LOGW(TAG, "Wi-Fi disconnected, retrying");
    } else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *ev = (ip_event_got_ip_t *)event_data;
        char msg[64];
        snprintf(msg, sizeof(msg), "got ip:" IPSTR, IP2STR(&ev->ip_info.ip));
        ESP_LOGI(TAG, "%s", msg);
        wifi_ui_set_status(msg);
        if (s_wifi_event_group) {
            xEventGroupSetBits(s_wifi_event_group, WIFI_CONNECTED_BIT);
        }
    }
}

static void demo_wifi_start(void)
{
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);

    s_wifi_event_group = xEventGroupCreate();

    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));

    ESP_ERROR_CHECK(esp_event_handler_instance_register(
        WIFI_EVENT, ESP_EVENT_ANY_ID, &demo_wifi_event_handler, NULL, NULL));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(
        IP_EVENT, IP_EVENT_STA_GOT_IP, &demo_wifi_event_handler, NULL, NULL));

    wifi_config_t wifi_cfg = {
        .sta = {
            .ssid     = CONFIG_DEMO_WIFI_SSID,
            .password = CONFIG_DEMO_WIFI_PASSWORD,
            .threshold.authmode = WIFI_AUTH_OPEN,
        },
    };
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_cfg));
    esp_err_t start_ret = esp_wifi_start();
    if (start_ret != ESP_OK) {
        ESP_LOGW(TAG, "esp_wifi_start: %s (0x%x) — continuing in QEMU",
                 esp_err_to_name(start_ret), start_ret);
    } else {
        ESP_LOGI(TAG, "demo_wifi_start: SSID=%s", CONFIG_DEMO_WIFI_SSID);
    }
}

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

    /* Wi-Fi status label — created after benchmark widgets so it renders on top */
    wifi_ui_init();

    /* Drive LVGL until benchmark signals end OR loop cap reached.
     * Wi-Fi init is deferred until AFTER the benchmark so its high-priority
     * tasks (prio 23) do not slow down the QEMU simulation during rendering. */
    for (int i = 0; i < LVGL_LOOP_CYCLES && !s_benchmark_done; i++) {
        wifi_ui_tick();
        lv_timer_handler();
        vTaskDelay(pdMS_TO_TICKS(LVGL_LOOP_DELAY_MS));
    }

    /* Benchmark complete — now start Wi-Fi in background.
     * Events fire asynchronously; wifi_ui_set_status() updates the label. */
    demo_wifi_start();

#if CONFIG_DEMO_LWIP_PROBE_ENABLE
    lwip_probe_start(CONFIG_DEMO_LWIP_PROBE_HOST, CONFIG_DEMO_LWIP_PROBE_PORT);
#endif

    /* Brief LVGL loop to let Wi-Fi events update the status label */
    for (int i = 0; i < 100; i++) {
        wifi_ui_tick();
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
