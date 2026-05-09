/**
 * @file esp_wifi_shim.c
 * @brief QEMU virtual Wi-Fi driver — core lifecycle API.
 *
 * Contains: shared state definitions, wifi_qemu_send_cmd(), wifi_event_task(),
 * and the lifecycle API (init/deinit/set_mode/get_mode/start/stop).
 *
 * Config/connect/MAC APIs live in esp_wifi_config.c.
 * Scan APIs live in esp_wifi_scan.c.
 */

#include "sdkconfig.h"

#if CONFIG_ESP_WIFI_QEMU

#include <string.h>
#include <inttypes.h>
#include "esp_err.h"
#include "esp_log.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_wifi_qemu.h"
#include "esp_wifi_private.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"

/* Forward declarations from esp_wifi_netif.c */
esp_err_t esp_wifi_netif_init(esp_netif_t *netif);
void      esp_wifi_netif_rx_frame(void);

static const char *TAG = "wifi_qemu";

/* ------------------------------------------------------------------ */
/*  Shared state definitions                                            */
/* ------------------------------------------------------------------ */

static bool          s_inited     = false;
static wifi_mode_t   s_mode       = WIFI_MODE_NULL;
wifi_config_t        s_sta_cfg    = {};    /* exported via esp_wifi_private.h */
static TaskHandle_t  s_evt_task   = NULL;
esp_netif_t  *s_sta_netif  = NULL;

/* ------------------------------------------------------------------ */
/*  Forward declarations                                               */
/* ------------------------------------------------------------------ */

static void wifi_event_task(void *arg);

/* ------------------------------------------------------------------ */
/*  Helper: send a command and poll for completion                      */
/* ------------------------------------------------------------------ */

esp_err_t wifi_qemu_send_cmd(uint32_t cmd, uint32_t timeout_ms)
{
    ESP_LOGD(TAG, "cmd 0x%02" PRIx32 " timeout=%" PRIu32 "ms", cmd, timeout_ms);

    /* Write command register */
    wifi_qemu_write(WIFI_REG_CMD, cmd);

    /* Poll WIFI_REG_EVENT until a non-NONE event appears or timeout */
    TickType_t deadline = xTaskGetTickCount() +
                         pdMS_TO_TICKS(timeout_ms ? timeout_ms : 1);
    while (xTaskGetTickCount() < deadline) {
        uint32_t evt = wifi_qemu_read(WIFI_REG_EVENT);
        if (evt == WIFI_EVT_ERROR) {
            wifi_qemu_write(WIFI_REG_EVENT, 0); /* ack */
            return ESP_FAIL;
        }
        if (evt != WIFI_EVT_NONE) {
            wifi_qemu_write(WIFI_REG_EVENT, 0); /* ack */
            return ESP_OK;
        }
        vTaskDelay(pdMS_TO_TICKS(10));
    }
    ESP_LOGW(TAG, "cmd 0x%02" PRIx32 " timed out", cmd);
    return ESP_ERR_TIMEOUT;
}

/* ------------------------------------------------------------------ */
/*  esp_wifi_* API implementation                                       */
/* ------------------------------------------------------------------ */

/* ------------------------------------------------------------------ */
/*  Async event dispatch task                                           */
/*                                                                      */
/*  Monitors WIFI_REG_EVENT for events posted by the QEMU device that  */
/*  are NOT consumed by wifi_qemu_send_cmd (i.e., events arising from  */
/*  CMD_CONNECT and CMD_DISCONNECT which are non-blocking).            */
/*                                                                      */
/*  Synchronous commands (INIT, START, STOP, GET_MAC) are handled by  */
/*  wifi_qemu_send_cmd() which ACKs the event before returning, and   */
/*  the calling API function posts the ESP event inline.               */
/* ------------------------------------------------------------------ */

static void wifi_event_task(void *arg)
{
    (void)arg;
    for (;;) {
        uint32_t evt = wifi_qemu_read(WIFI_REG_EVENT);
        if (evt == WIFI_EVT_NONE) {
            /* Also fast-path poll for RX frames even without explicit event */
            if (wifi_qemu_read(WIFI_REG_RX_LEN) > 0) {
                esp_wifi_netif_rx_frame();
            }
            vTaskDelay(pdMS_TO_TICKS(10));
            continue;
        }
        wifi_qemu_write(WIFI_REG_EVENT, 0); /* ACK */
        ESP_LOGD(TAG, "async event 0x%02" PRIx32, evt);

        switch (evt) {
        case WIFI_EVT_CONNECTED: {
            wifi_event_sta_connected_t ev = {
                .ssid_len = (uint8_t)strnlen((char *)s_sta_cfg.sta.ssid, 32),
                .channel  = 1,
                .authmode = WIFI_AUTH_WPA2_PSK,
                .aid      = 1,
            };
            memcpy(ev.ssid, s_sta_cfg.sta.ssid, ev.ssid_len);
            esp_event_post(WIFI_EVENT, WIFI_EVENT_STA_CONNECTED,
                           &ev, sizeof(ev), portMAX_DELAY);
            break;
        }
        case WIFI_EVT_GOT_IP: {
            /* All IP setup is done in the STA_CONNECTED static-IP handler
             * registered in esp_wifi_start().  Calling set_ip_info or
             * netif_init here races with that handler and corrupts netif
             * function pointers (Day-27 InstrFetchProhibited bug). */
            ESP_LOGD(TAG, "WIFI_EVT_GOT_IP (no-op: STA_CONNECTED handler owns IP setup)");
            break;
        }
        case WIFI_EVT_DISCONNECTED: {
            wifi_event_sta_disconnected_t ev = {
                .ssid_len = (uint8_t)strnlen((char *)s_sta_cfg.sta.ssid, 32),
                .reason   = WIFI_REASON_ASSOC_LEAVE,
                .rssi     = 0,
            };
            memcpy(ev.ssid, s_sta_cfg.sta.ssid, ev.ssid_len);
            esp_event_post(WIFI_EVENT, WIFI_EVENT_STA_DISCONNECTED,
                           &ev, sizeof(ev), portMAX_DELAY);
            break;
        }
        case WIFI_EVT_SCAN_DONE: {
            wifi_event_sta_scan_done_t ev = {
                .status  = 0,
                .number  = (uint8_t)wifi_qemu_read(WIFI_REG_SCAN_COUNT),
                .scan_id = 0,
            };
            esp_event_post(WIFI_EVENT, WIFI_EVENT_SCAN_DONE,
                           &ev, sizeof(ev), portMAX_DELAY);
            break;
        }
        case WIFI_EVT_ERROR:
            ESP_LOGE(TAG, "device error event");
            break;
        case WIFI_EVT_RX_READY:
            /* RX Ethernet frame ready in MMIO buffer — inject into lwIP */
            esp_wifi_netif_rx_frame();
            break;
        default:
            /* INIT_DONE, START_DONE, STOP_DONE handled by wifi_qemu_send_cmd */
            break;
        }
    }
}

esp_err_t esp_wifi_init(const wifi_init_config_t *config)
{
    (void)config;
    if (s_inited) {
        return ESP_ERR_INVALID_STATE;
    }
    ESP_LOGI(TAG, "init (QEMU virtual Wi-Fi)");
    esp_err_t ret = wifi_qemu_send_cmd(WIFI_CMD_INIT, 2000);
    if (ret == ESP_OK) {
        s_inited = true;
        /* NOTE: wifi_event_task is started in esp_wifi_start() — AFTER all
         * synchronous commands (INIT, SET_MODE, START) are done.  Starting
         * the task here at tskIDLE_PRIORITY+2 (> app_main priority 1) would
         * race with wifi_qemu_send_cmd() for WIFI_EVT_INIT_DONE/START_DONE,
         * causing those commands to time out. */
    }
    return ret;
}

esp_err_t esp_wifi_deinit(void)
{
    if (!s_inited) {
        return ESP_ERR_INVALID_STATE;
    }
    if (s_evt_task) {
        vTaskDelete(s_evt_task);
        s_evt_task = NULL;
    }
    esp_err_t ret = wifi_qemu_send_cmd(WIFI_CMD_DEINIT, 1000);
    s_inited = false;
    return ret;
}

esp_err_t esp_wifi_set_mode(wifi_mode_t mode)
{
    s_mode = mode;
    /* For STA or APSTA, configure the STA channel in QEMU */
    if (mode == WIFI_MODE_STA || mode == WIFI_MODE_APSTA) {
        return wifi_qemu_send_cmd(WIFI_CMD_SET_MODE_STA, 1000);
    }
    return ESP_OK;
}

esp_err_t esp_wifi_get_mode(wifi_mode_t *mode)
{
    if (!mode) {
        return ESP_ERR_INVALID_ARG;
    }
    *mode = s_mode;
    return ESP_OK;
}

/* ---------------------------------------------------------------------------
 * Late STA_CONNECTED static-IP handler.
 *
 * Registered for WIFI_EVENT_STA_CONNECTED in esp_wifi_start().
 * Fires AFTER IDF's built-in DHCP-clearing handler, so we can safely stop
 * DHCP and push the static IP that the QEMU device pre-loaded in its
 * MMIO registers.  This avoids the Day-27 race where GOT_IP fired before
 * the netif was ready to accept esp_netif_set_ip_info().
 * -------------------------------------------------------------------------*/
static void wifi_qemu_sta_connected_static_ip(void *arg, esp_event_base_t base,
                                               int32_t event_id, void *event_data)
{
    (void)arg; (void)base; (void)event_id; (void)event_data;

    if (!s_sta_netif) {
        s_sta_netif = esp_netif_get_handle_from_ifkey("WIFI_STA_DEF");
    }
    if (!s_sta_netif) {
        ESP_LOGW(TAG, "static_ip handler: no STA netif yet");
        return;
    }

    uint32_t ip   = wifi_qemu_read(WIFI_REG_IP_ADDR);
    uint32_t mask = wifi_qemu_read(WIFI_REG_IP_MASK);
    uint32_t gw   = wifi_qemu_read(WIFI_REG_IP_GW);

    if (!ip) {
        ESP_LOGD(TAG, "static_ip handler: IP not yet in MMIO, skipping");
        return;
    }

    /* Stop DHCP client before setting static IP (IDF 5.5 requirement) */
    esp_netif_dhcpc_stop(s_sta_netif);

    esp_netif_ip_info_t ip_info = {};
    ip_info.ip.addr      = ip;
    ip_info.netmask.addr = mask;
    ip_info.gw.addr      = gw;
    esp_netif_set_ip_info(s_sta_netif, &ip_info);

    /* Install the QEMU DMA packet driver now that we have the netif */
    esp_wifi_netif_init(s_sta_netif);

    ip_event_got_ip_t got_ip = {
        .esp_netif  = s_sta_netif,
        .ip_changed = true,
    };
    got_ip.ip_info.ip.addr      = ip;
    got_ip.ip_info.netmask.addr = mask;
    got_ip.ip_info.gw.addr      = gw;
    ESP_LOGI(TAG, "got ip:" IPSTR, IP2STR(&got_ip.ip_info.ip));
    esp_event_post(IP_EVENT, IP_EVENT_STA_GOT_IP,
                   &got_ip, sizeof(got_ip), portMAX_DELAY);
}

esp_err_t esp_wifi_start(void)
{
    ESP_LOGI(TAG, "start");
    bool sta_enabled = (s_mode == WIFI_MODE_STA || s_mode == WIFI_MODE_APSTA);
    bool ap_enabled  = (s_mode == WIFI_MODE_AP  || s_mode == WIFI_MODE_APSTA);

    if (sta_enabled) {
        /* Register late static-IP handler so it fires after IDF's DHCP handler */
        esp_event_handler_register(WIFI_EVENT, WIFI_EVENT_STA_CONNECTED,
                                   wifi_qemu_sta_connected_static_ip, NULL);

        esp_err_t ret = wifi_qemu_send_cmd(WIFI_CMD_START, 500);
        if (ret == ESP_OK) {
            /* Start async event dispatch task NOW — after all synchronous
             * commands (INIT, SET_MODE, START) have been ACK'd.  Starting
             * it earlier would race for WIFI_EVT_INIT_DONE / START_DONE. */
            if (!s_evt_task) {
                xTaskCreate(wifi_event_task, "wifi_evt", 4096, NULL,
                            tskIDLE_PRIORITY + 2, &s_evt_task);
            }
            /* Issue a background scan right at startup so AP list is already
             * populated when the app's WIFI_EVENT_STA_START handler fires
             * or when esp_wifi_connect() is called.  The event task picks up
             * WIFI_EVT_SCAN_DONE and posts WIFI_EVENT_SCAN_DONE with the
             * result count.  A subsequent esp_wifi_scan_start() call works
             * normally and overwrites these results.
             *
             * IMPORTANT: write the CMD_SCAN MMIO BEFORE posting STA_START.
             * The event task runs at tskIDLE_PRIORITY+2 and can preempt this
             * task as soon as the post returns; if the app's STA_START
             * handler then synchronously calls esp_wifi_connect(), the
             * resulting CMD_CONNECT can land on the device before our
             * housekeeping CMD_SCAN.  In that order CMD_SCAN re-asserts
             * `scan_only=true` on top of an in-flight connect flow,
             * causing the device's SCAN_RESULTS handler to short-circuit
             * to SCAN_DONE and skip ADD_NETWORK / SELECT_NETWORK / GOT_IP.
             * Stock samples wifi/fast_scan and wifi/getting_started/station
             * both follow the "connect from STA_START" pattern, so this
             * ordering guarantee is required for drop-in compatibility.
             */
            wifi_qemu_write(WIFI_REG_CMD, WIFI_CMD_SCAN);
            ESP_LOGI(TAG, "startup scan initiated");
            esp_event_post(WIFI_EVENT, WIFI_EVENT_STA_START, NULL, 0, portMAX_DELAY);
        } else {
            ESP_LOGW(TAG, "esp_wifi_start STA: %s (0x%x) — continuing in QEMU",
                     esp_err_to_name(ret), ret);
        }
    }

    if (ap_enabled) {
        /* For AP mode without STA, also start the event task if not running */
        if (!s_evt_task) {
            xTaskCreate(wifi_event_task, "wifi_evt", 4096, NULL,
                        tskIDLE_PRIORITY + 2, &s_evt_task);
        }
        esp_event_post(WIFI_EVENT, WIFI_EVENT_AP_START, NULL, 0, portMAX_DELAY);

        /* Day-45: fabricate fake associated stations so stock softAP
         * samples produce real join logs and ap_get_sta_list is non-empty. */
        qemu_wifi_ap_clear_stations();
#ifdef CONFIG_ESP_WIFI_QEMU_AP_FAKE_CLIENTS
        for (uint8_t i = 0; i < CONFIG_ESP_WIFI_QEMU_AP_FAKE_CLIENTS; ++i) {
            qemu_wifi_ap_inject_fake_station(i);
        }
#endif
    }

    return ESP_OK;
}

esp_err_t esp_wifi_stop(void)
{
    ESP_LOGI(TAG, "stop");
    bool sta_enabled = (s_mode == WIFI_MODE_STA || s_mode == WIFI_MODE_APSTA);
    bool ap_enabled  = (s_mode == WIFI_MODE_AP  || s_mode == WIFI_MODE_APSTA);

    esp_err_t ret = ESP_OK;
    if (sta_enabled) {
        ret = wifi_qemu_send_cmd(WIFI_CMD_STOP, 3000);
        if (ret == ESP_OK) {
            esp_event_post(WIFI_EVENT, WIFI_EVENT_STA_STOP, NULL, 0, portMAX_DELAY);
        }
    }
    if (ap_enabled) {
        esp_event_post(WIFI_EVENT, WIFI_EVENT_AP_STOP, NULL, 0, portMAX_DELAY);
    }
    return ret;
}

#endif /* CONFIG_ESP_WIFI_QEMU */
