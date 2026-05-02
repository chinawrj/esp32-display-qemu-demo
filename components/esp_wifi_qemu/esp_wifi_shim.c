/**
 * @file esp_wifi_shim.c
 * @brief QEMU virtual Wi-Fi driver — esp_wifi_* API stubs (STA mode).
 *
 * This component is compiled ONLY when CONFIG_ESP_WIFI_QEMU=y.
 * It replaces the real Wi-Fi blob driver with MMIO writes to the
 * QEMU esp_wifi virtual device (docs/qemu-wifi.md).
 *
 * Implementation status (Day 8 scaffold — stubs only):
 *   [x] esp_wifi_init / esp_wifi_deinit
 *   [x] esp_wifi_set_mode / esp_wifi_get_mode
 *   [x] esp_wifi_start / esp_wifi_stop
 *   [x] esp_wifi_set_config / esp_wifi_get_config
 *   [x] esp_wifi_connect / esp_wifi_disconnect
 *   [x] esp_wifi_get_mac / esp_wifi_set_mac
 *   [x] esp_wifi_scan_start / esp_wifi_scan_stop / esp_wifi_scan_get_ap_records
 *   [ ] Full MMIO interaction (Day 9+)
 *   [ ] IRQ / event dispatch loop (Day 9+)
 *   [ ] esp_netif binding (Day 10+)
 */

#include "sdkconfig.h"

#if CONFIG_ESP_WIFI_QEMU

#include <string.h>
#include "esp_err.h"
#include "esp_log.h"
#include "esp_wifi.h"
#include "esp_wifi_qemu.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "wifi_qemu";

/* ------------------------------------------------------------------ */
/*  Internal state                                                      */
/* ------------------------------------------------------------------ */

static bool          s_inited  = false;
static wifi_mode_t   s_mode    = WIFI_MODE_NULL;
static wifi_config_t s_sta_cfg = {};

/* ------------------------------------------------------------------ */
/*  Helper: send a command and poll for completion                      */
/* ------------------------------------------------------------------ */

esp_err_t wifi_qemu_send_cmd(uint32_t cmd, uint32_t timeout_ms)
{
    /* TODO (Day 9): implement MMIO command/event polling loop.
     * For now, stubs return OK immediately so firmware boots. */
    (void)timeout_ms;
    ESP_LOGD(TAG, "cmd 0x%02" PRIx32 " (stub)", cmd);
    return ESP_OK;
}

/* ------------------------------------------------------------------ */
/*  esp_wifi_* API implementation                                       */
/* ------------------------------------------------------------------ */

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
    }
    return ret;
}

esp_err_t esp_wifi_deinit(void)
{
    if (!s_inited) {
        return ESP_ERR_INVALID_STATE;
    }
    esp_err_t ret = wifi_qemu_send_cmd(WIFI_CMD_DEINIT, 1000);
    s_inited = false;
    return ret;
}

esp_err_t esp_wifi_set_mode(wifi_mode_t mode)
{
    if (mode != WIFI_MODE_STA && mode != WIFI_MODE_NULL) {
        ESP_LOGE(TAG, "only STA mode supported in QEMU (requested %d)", mode);
        return ESP_ERR_NOT_SUPPORTED;
    }
    s_mode = mode;
    if (mode == WIFI_MODE_STA) {
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

esp_err_t esp_wifi_start(void)
{
    ESP_LOGI(TAG, "start");
    return wifi_qemu_send_cmd(WIFI_CMD_START, 3000);
}

esp_err_t esp_wifi_stop(void)
{
    ESP_LOGI(TAG, "stop");
    return wifi_qemu_send_cmd(WIFI_CMD_STOP, 3000);
}

esp_err_t esp_wifi_set_config(wifi_interface_t interface, wifi_config_t *conf)
{
    if (interface != WIFI_IF_STA) {
        return ESP_ERR_NOT_SUPPORTED;
    }
    if (!conf) {
        return ESP_ERR_INVALID_ARG;
    }
    memcpy(&s_sta_cfg, conf, sizeof(wifi_config_t));

    /* TODO (Day 9): write SSID/PASS to MMIO registers */
    ESP_LOGD(TAG, "set_config SSID=%s", s_sta_cfg.sta.ssid);
    return ESP_OK;
}

esp_err_t esp_wifi_get_config(wifi_interface_t interface, wifi_config_t *conf)
{
    if (interface != WIFI_IF_STA || !conf) {
        return ESP_ERR_INVALID_ARG;
    }
    memcpy(conf, &s_sta_cfg, sizeof(wifi_config_t));
    return ESP_OK;
}

esp_err_t esp_wifi_connect(void)
{
    ESP_LOGI(TAG, "connect SSID=%s", s_sta_cfg.sta.ssid);
    return wifi_qemu_send_cmd(WIFI_CMD_CONNECT, 30000);
}

esp_err_t esp_wifi_disconnect(void)
{
    ESP_LOGI(TAG, "disconnect");
    return wifi_qemu_send_cmd(WIFI_CMD_DISCONNECT, 5000);
}

esp_err_t esp_wifi_get_mac(wifi_interface_t ifx, uint8_t mac[6])
{
    if (ifx != WIFI_IF_STA || !mac) {
        return ESP_ERR_INVALID_ARG;
    }
    /* TODO (Day 9): send CMD_GET_MAC and read WIFI_REG_MAC0/MAC1 */
    memset(mac, 0, 6);
    return ESP_OK;
}

esp_err_t esp_wifi_set_mac(wifi_interface_t ifx, const uint8_t mac[6])
{
    (void)ifx;
    (void)mac;
    /* Virtual MAC is determined by the host; setting it is a no-op in v1. */
    return ESP_OK;
}

esp_err_t esp_wifi_scan_start(const wifi_scan_config_t *config, bool block)
{
    (void)config;
    (void)block;
    return wifi_qemu_send_cmd(WIFI_CMD_SCAN, block ? 15000 : 0);
}

esp_err_t esp_wifi_scan_stop(void)
{
    return ESP_OK;
}

esp_err_t esp_wifi_scan_get_ap_num(uint16_t *number)
{
    if (!number) {
        return ESP_ERR_INVALID_ARG;
    }
    /* TODO (Day 9): read WIFI_REG_SCAN_COUNT */
    *number = 0;
    return ESP_OK;
}

esp_err_t esp_wifi_scan_get_ap_records(uint16_t *number, wifi_ap_record_t *ap_records)
{
    if (!number || !ap_records) {
        return ESP_ERR_INVALID_ARG;
    }
    /* TODO (Day 9): iterate WIFI_REG_SCAN_IDX and read scan result regs */
    *number = 0;
    return ESP_OK;
}

#endif /* CONFIG_ESP_WIFI_QEMU */
