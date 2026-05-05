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
void esp_wifi_netif_rx_frame(void);
void esp_wifi_netif_register_rx_buf(void);

static const char *TAG = "wifi_qemu";

/* ------------------------------------------------------------------ */
/*  Shared state definitions                                            */
/* ------------------------------------------------------------------ */

static bool          s_inited     = false;
static wifi_mode_t   s_mode       = WIFI_MODE_NULL;
wifi_config_t        s_sta_cfg    = {};    /* exported via esp_wifi_private.h */
static TaskHandle_t  s_evt_task   = NULL;
esp_netif_t  *s_sta_netif  = NULL;

/* BUG-004 fix: set while wifi_qemu_send_cmd() is polling WIFI_REG_EVENT so
 * wifi_event_task() backs off and does not steal the synchronous response. */
static volatile bool s_cmd_in_flight = false;

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

    /* BUG-004 fix: signal to wifi_event_task that we own the EVENT register. */
    s_cmd_in_flight = true;

    /* Write command register */
    wifi_qemu_write(WIFI_REG_CMD, cmd);

    /* Poll WIFI_REG_EVENT until a non-NONE event appears or timeout */
    TickType_t deadline = xTaskGetTickCount() +
                         pdMS_TO_TICKS(timeout_ms ? timeout_ms : 1);
    while (xTaskGetTickCount() < deadline) {
        uint32_t evt = wifi_qemu_read(WIFI_REG_EVENT);
        if (evt == WIFI_EVT_ERROR) {
            wifi_qemu_write(WIFI_REG_EVENT, 0); /* ack */
            s_cmd_in_flight = false;
            return ESP_FAIL;
        }
        if (evt != WIFI_EVT_NONE) {
            wifi_qemu_write(WIFI_REG_EVENT, 0); /* ack */
            s_cmd_in_flight = false;
            return ESP_OK;
        }
        vTaskDelay(pdMS_TO_TICKS(10));
    }
    s_cmd_in_flight = false;
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
        /* BUG-004 fix: back off while a synchronous command is polling
         * WIFI_REG_EVENT.  If we ACK the sync response event here the
         * calling wifi_qemu_send_cmd() will time-out and return an error. */
        if (s_cmd_in_flight) {
            vTaskDelay(pdMS_TO_TICKS(5));
            continue;
        }

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
            /* QEMU mock_wpa writes the IP into MMIO registers; read them for
             * the debug log only.  We do NOT manually post IP_EVENT_STA_GOT_IP
             * nor call esp_netif_set_ip_info() here.
             *
             * With esp_wifi_internal_tx() now calling qemu_wifi_tx_raw(), DHCP
             * packets (DISCOVER/REQUEST) are actually sent to QEMU's SLIRP
             * layer which has a built-in DHCP server.  SLIRP assigns 10.0.2.15
             * and the normal lwIP DHCP state machine fires IP_EVENT_STA_GOT_IP
             * via netif_status_callback.  That event properly configures lwIP
             * routing (netif_set_default etc.) before any socket code runs.
             *
             * Previously, firing the event from here was RACING the lwIP task:
             * example_connect() would unblock before ip4_route() had a valid
             * route, causing EHOSTUNREACH (errno 118) in tcp_client. */
            uint32_t ip = wifi_qemu_read(WIFI_REG_IP_ADDR);
            esp_ip4_addr_t a; a.addr = ip;
            ESP_LOGI(TAG, "got ip:" IPSTR " (DHCP will fire event)", IP2STR(&a));
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
        /* Start the async event dispatch task */
        if (!s_evt_task) {
            xTaskCreate(wifi_event_task, "wifi_evt", 4096, NULL,
                        tskIDLE_PRIORITY + 2, &s_evt_task);
        }
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

/* ------------------------------------------------------------------ */
/*  Late WIFI_EVENT_STA_CONNECTED handler - sets static IP after       */
/*  IDF default handlers have started (and cleared) DHCP.             */
/* ------------------------------------------------------------------ */

/**
 * @brief Handler for WIFI_EVENT_STA_CONNECTED, registered AFTER the IDF
 * default handlers (which start DHCP and clear the netif IP in
 * esp_netif_dhcpc_start_api lines 1624-1626).
 *
 * By registering in esp_wifi_start(), this handler runs LAST among all
 * STA_CONNECTED handlers in the same event loop dispatch.  At that point
 * DHCP has been started and the IP has been cleared to 0.0.0.0.
 *
 * We read the IP already written to MMIO by the QEMU device (from mock_wpa
 * STATUS response), stop DHCP, and assign the static IP.  This fires
 * IP_EVENT_STA_GOT_IP via netif_status_callback (triggered by netif_set_addr
 * inside esp_netif_set_ip_info_api) before example_connect's semaphore is
 * given.
 *
 * Day-27 bug: the previous approach (setting IP in WIFI_EVT_GOT_IP handler)
 * raced with the event queue ordering - STA_CONNECTED was processed after
 * our IP_EVENT_STA_GOT_IP posts, causing DHCP to clear the IP and resulting
 * in EHOSTUNREACH (errno 118) when tcp_client called connect().
 */
static void wifi_qemu_sta_connected_static_ip(void *arg,
                                              esp_event_base_t base,
                                              int32_t event_id,
                                              void *event_data)
{
    (void)arg; (void)base; (void)event_id; (void)event_data;

    uint32_t ip   = wifi_qemu_read(WIFI_REG_IP_ADDR);
    uint32_t mask = wifi_qemu_read(WIFI_REG_IP_MASK);
    uint32_t gw   = wifi_qemu_read(WIFI_REG_IP_GW);

    if (!ip) {
        ESP_LOGW(TAG, "WIFI_REG_IP_ADDR is 0 - static IP not yet available");
        return;
    }

    esp_netif_t *netif = esp_netif_get_handle_from_ifkey("WIFI_STA_DEF");
    if (!netif) {
        ESP_LOGW(TAG, "WIFI_STA_DEF netif not found");
        return;
    }

    /* Cache the netif pointer for esp_wifi_netif_rx_frame() */
    if (!s_sta_netif) {
        s_sta_netif = netif;
    }

    /* Stop DHCP first; in IDF 5.5, esp_netif_set_ip_info_api requires
     * dhcpc_status == STOPPED (it no longer stops DHCP automatically). */
    esp_err_t stop_ret = esp_netif_dhcpc_stop(netif);
    if (stop_ret != ESP_OK &&
        stop_ret != ESP_ERR_ESP_NETIF_DHCP_ALREADY_STOPPED) {
        ESP_LOGW(TAG, "dhcpc_stop: %s", esp_err_to_name(stop_ret));
        /* continue; set_ip_info may still succeed if DHCP is off */
    }

    /* Assign the static IP from mock_wpa STATUS registers. */
    esp_netif_ip_info_t ip_info = {};
    ip_info.ip.addr      = ip;
    ip_info.netmask.addr = mask;
    ip_info.gw.addr      = gw;
    esp_err_t ret = esp_netif_set_ip_info(netif, &ip_info);
    if (ret != ESP_OK) {
        ESP_LOGW(TAG, "esp_netif_set_ip_info failed: %s", esp_err_to_name(ret));
        return;
    }

    /* netif_status_callback (fired by netif_set_addr inside set_ip_info_api)
     * already posts IP_EVENT_STA_GOT_IP.  Post one more explicitly so
     * example_connect's handler fires even if the netif callback is suppressed
     * (e.g. IP unchanged from a previous run). */
    ip_event_got_ip_t got_ip = { .esp_netif = netif, .ip_changed = true };
    got_ip.ip_info.ip.addr      = ip;
    got_ip.ip_info.netmask.addr = mask;
    got_ip.ip_info.gw.addr      = gw;
    esp_ip4_addr_t dbg; dbg.addr = ip;
    ESP_LOGI(TAG, "static IP assigned:" IPSTR, IP2STR(&dbg));
    esp_event_post(IP_EVENT, IP_EVENT_STA_GOT_IP,
                   &got_ip, sizeof(got_ip), portMAX_DELAY);
}

esp_err_t esp_wifi_start(void)
{
    ESP_LOGI(TAG, "start (mode=%d)", (int)s_mode);
    bool ap_enabled = (s_mode == WIFI_MODE_AP || s_mode == WIFI_MODE_APSTA);
    bool sta_enabled = (s_mode == WIFI_MODE_STA || s_mode == WIFI_MODE_APSTA);

    if (ap_enabled) {
        esp_event_post(WIFI_EVENT, WIFI_EVENT_AP_START, NULL, 0,
                       portMAX_DELAY);
    }
    if (!sta_enabled) {
        return ESP_OK;
    }

    esp_err_t ret = wifi_qemu_send_cmd(WIFI_CMD_START, 500);
    if (ret == ESP_OK) {
        /* Register our late STA_CONNECTED handler AFTER esp_wifi_start().
         * This ensures it runs after the IDF default handler (registered by
         * esp_wifi_set_default_wifi_sta_handlers in esp_netif_create_default_
         * wifi_sta or protocol_examples_common).  The IDF handler starts DHCP
         * and clears the IP; ours runs afterward to assign the static IP. */
        esp_event_handler_register(WIFI_EVENT, WIFI_EVENT_STA_CONNECTED,
                                   wifi_qemu_sta_connected_static_ip, NULL);

        /* BUG-002 fix: pre-register RX DMA buffer so QEMU can deliver ARP
         * and DHCP frames before the full netif driver is installed at GOT_IP. */
        esp_wifi_netif_register_rx_buf();
        esp_event_post(WIFI_EVENT, WIFI_EVENT_STA_START, NULL, 0,
                       portMAX_DELAY);
    }
    return ret;
}

esp_err_t esp_wifi_stop(void)
{
    ESP_LOGI(TAG, "stop (mode=%d)", (int)s_mode);
    bool ap_enabled = (s_mode == WIFI_MODE_AP || s_mode == WIFI_MODE_APSTA);
    bool sta_enabled = (s_mode == WIFI_MODE_STA || s_mode == WIFI_MODE_APSTA);

    if (ap_enabled) {
        esp_event_post(WIFI_EVENT, WIFI_EVENT_AP_STOP, NULL, 0,
                       portMAX_DELAY);
    }
    if (!sta_enabled) {
        return ESP_OK;
    }

    esp_err_t ret = wifi_qemu_send_cmd(WIFI_CMD_STOP, 3000);
    if (ret == ESP_OK) {
        esp_event_post(WIFI_EVENT, WIFI_EVENT_STA_STOP, NULL, 0,
                       portMAX_DELAY);
    }
    return ret;
}

#endif /* CONFIG_ESP_WIFI_QEMU */
