/**
 * @file esp_wifi_shim.c
 * @brief QEMU virtual Wi-Fi driver — esp_wifi_* API stubs (STA mode).
 *
 * This component is compiled ONLY when CONFIG_ESP_WIFI_QEMU=y.
 * It replaces the real Wi-Fi blob driver with MMIO writes to the
 * QEMU esp_wifi virtual device (docs/qemu-wifi.md).
 *
 * Implementation status (Day 10):
 *   [x] esp_wifi_init / esp_wifi_deinit
 *   [x] esp_wifi_set_mode / esp_wifi_get_mode
 *   [x] esp_wifi_start / esp_wifi_stop
 *   [x] esp_wifi_set_config / esp_wifi_get_config  (MMIO SSID/PASS write)
 *   [x] esp_wifi_connect / esp_wifi_disconnect
 *   [x] esp_wifi_get_mac / esp_wifi_set_mac        (CMD_GET_MAC + sysfs)
 *   [x] esp_wifi_scan_start / esp_wifi_scan_stop
 *   [x] esp_wifi_scan_get_ap_num / ap_records      (MMIO scan register read)
 *   [x] wifi_qemu_send_cmd() — real MMIO polling loop
 *   [ ] IRQ / event dispatch loop (Day 11+)
 *   [ ] esp_netif binding (Day 11+)
 */

#include "sdkconfig.h"

#if CONFIG_ESP_WIFI_QEMU

#include <string.h>
#include <inttypes.h>
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

    /* Write SSID to MMIO */
    size_t ssid_len = strlen((char *)s_sta_cfg.sta.ssid);
    ssid_len = ssid_len > 32 ? 32 : ssid_len;
    for (size_t i = 0; i < ssid_len; i += 4) {
        uint32_t chunk = 0;
        memcpy(&chunk, s_sta_cfg.sta.ssid + i, MIN(4, ssid_len - i));
        wifi_qemu_write(WIFI_REG_SSID_BASE + i, chunk);
    }
    wifi_qemu_write(WIFI_REG_SSID_LEN, (uint32_t)ssid_len);

    /* Write password to MMIO */
    size_t pass_len = strlen((char *)s_sta_cfg.sta.password);
    pass_len = pass_len > 64 ? 64 : pass_len;
    for (size_t i = 0; i < pass_len; i += 4) {
        uint32_t chunk = 0;
        memcpy(&chunk, s_sta_cfg.sta.password + i, MIN(4, pass_len - i));
        wifi_qemu_write(WIFI_REG_PASS_BASE + i, chunk);
    }
    wifi_qemu_write(WIFI_REG_PASS_LEN, (uint32_t)pass_len);
    ESP_LOGD(TAG, "set_config SSID=%s (len=%zu)", s_sta_cfg.sta.ssid, ssid_len);
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
    wifi_qemu_send_cmd(WIFI_CMD_GET_MAC, 1000);
    uint32_t mac0 = wifi_qemu_read(WIFI_REG_MAC0);
    uint32_t mac1 = wifi_qemu_read(WIFI_REG_MAC1);
    memcpy(mac,     &mac0, 4);
    mac[4] = (uint8_t)((mac1 >> 24) & 0xff);
    mac[5] = (uint8_t)((mac1 >> 16) & 0xff);
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
    *number = (uint16_t)wifi_qemu_read(WIFI_REG_SCAN_COUNT);
    return ESP_OK;
}

esp_err_t esp_wifi_scan_get_ap_records(uint16_t *number, wifi_ap_record_t *ap_records)
{
    if (!number || !ap_records) {
        return ESP_ERR_INVALID_ARG;
    }
    uint16_t total = (uint16_t)wifi_qemu_read(WIFI_REG_SCAN_COUNT);
    if (total > *number) { total = *number; }
    for (uint16_t i = 0; i < total; i++) {
        wifi_qemu_write(WIFI_REG_SCAN_IDX, i);
        uint32_t ssid_len = wifi_qemu_read(WIFI_REG_SCAN_SSID_LEN);
        ssid_len = ssid_len > 32 ? 32 : ssid_len;
        uint8_t ssid[33] = {0};
        for (uint32_t j = 0; j < ssid_len; j += 4) {
            uint32_t chunk = wifi_qemu_read(WIFI_REG_SCAN_SSID_BASE + j);
            memcpy(ssid + j, &chunk, MIN(4, ssid_len - j));
        }
        memcpy(ap_records[i].ssid, ssid, ssid_len);
        ap_records[i].rssi = (int8_t)(uint8_t)wifi_qemu_read(WIFI_REG_SCAN_RSSI);
        uint32_t b0 = wifi_qemu_read(WIFI_REG_SCAN_BSSID0);
        uint32_t b1 = wifi_qemu_read(WIFI_REG_SCAN_BSSID1);
        memcpy(ap_records[i].bssid, &b0, 4);
        ap_records[i].bssid[4] = (uint8_t)((b1 >> 24) & 0xff);
        ap_records[i].bssid[5] = (uint8_t)((b1 >> 16) & 0xff);
        ap_records[i].authmode = WIFI_AUTH_WPA2_PSK; /* conservative default */
        ap_records[i].primary  = 1;
    }
    *number = total;
    return ESP_OK;
}

#endif /* CONFIG_ESP_WIFI_QEMU */
