/**
 * @file esp_wifi_config.c
 * @brief QEMU virtual Wi-Fi driver — config, connect, and MAC APIs.
 *
 * This file handles: esp_wifi_set_config, esp_wifi_get_config,
 * esp_wifi_connect, esp_wifi_disconnect, esp_wifi_get_mac, esp_wifi_set_mac.
 */

#include "sdkconfig.h"

#if CONFIG_ESP_WIFI_QEMU

#include <string.h>
#include "esp_err.h"
#include "esp_log.h"
#include "esp_wifi.h"
#include "esp_wifi_qemu.h"
#include "esp_wifi_private.h"

static const char *TAG = "wifi_qemu";

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
        memcpy(&chunk, s_sta_cfg.sta.ssid + i, SHIM_MIN(4, ssid_len - i));
        wifi_qemu_write(WIFI_REG_SSID_BASE + i, chunk);
    }
    wifi_qemu_write(WIFI_REG_SSID_LEN, (uint32_t)ssid_len);

    /* Write password to MMIO */
    size_t pass_len = strlen((char *)s_sta_cfg.sta.password);
    pass_len = pass_len > 64 ? 64 : pass_len;
    for (size_t i = 0; i < pass_len; i += 4) {
        uint32_t chunk = 0;
        memcpy(&chunk, s_sta_cfg.sta.password + i, SHIM_MIN(4, pass_len - i));
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
    /* Non-blocking: write CMD_CONNECT and return immediately.
     * The event dispatch task in esp_wifi_shim.c delivers
     * WIFI_EVENT_STA_CONNECTED and IP_EVENT_STA_GOT_IP asynchronously. */
    ESP_LOGI(TAG, "connect SSID=%s", s_sta_cfg.sta.ssid);
    wifi_qemu_write(WIFI_REG_CMD, WIFI_CMD_CONNECT);
    return ESP_OK;
}

esp_err_t esp_wifi_disconnect(void)
{
    ESP_LOGI(TAG, "disconnect");
    wifi_qemu_write(WIFI_REG_CMD, WIFI_CMD_DISCONNECT);
    return ESP_OK;
}

esp_err_t esp_wifi_get_mac(wifi_interface_t ifx, uint8_t mac[6])
{
    if (ifx != WIFI_IF_STA || !mac) {
        return ESP_ERR_INVALID_ARG;
    }
    wifi_qemu_send_cmd(WIFI_CMD_GET_MAC, 1000);
    uint32_t mac0 = wifi_qemu_read(WIFI_REG_MAC0);
    uint32_t mac1 = wifi_qemu_read(WIFI_REG_MAC1);
    memcpy(mac, &mac0, 4);
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

#endif /* CONFIG_ESP_WIFI_QEMU */
