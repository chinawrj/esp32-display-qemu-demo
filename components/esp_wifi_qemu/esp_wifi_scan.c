/**
 * @file esp_wifi_scan.c
 * @brief QEMU virtual Wi-Fi driver — scan APIs.
 *
 * This file handles: esp_wifi_scan_start, esp_wifi_scan_stop,
 * esp_wifi_scan_get_ap_num, esp_wifi_scan_get_ap_records.
 */

#include "sdkconfig.h"

#if CONFIG_ESP_WIFI_QEMU

#include <string.h>
#include "esp_err.h"
#include "esp_wifi.h"
#include "esp_wifi_qemu.h"
#include "esp_wifi_private.h"

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
            memcpy(ssid + j, &chunk, SHIM_MIN(4, ssid_len - j));
        }
        memcpy(ap_records[i].ssid, ssid, ssid_len);
        ap_records[i].rssi = (int8_t)(uint8_t)wifi_qemu_read(WIFI_REG_SCAN_RSSI);
        uint32_t b0 = wifi_qemu_read(WIFI_REG_SCAN_BSSID0);
        uint32_t b1 = wifi_qemu_read(WIFI_REG_SCAN_BSSID1);
        memcpy(ap_records[i].bssid, &b0, 4);
        ap_records[i].bssid[4] = (uint8_t)((b1 >> 24) & 0xff);
        ap_records[i].bssid[5] = (uint8_t)((b1 >> 16) & 0xff);
        ap_records[i].authmode = WIFI_AUTH_WPA2_PSK;
        ap_records[i].primary  = 1;
    }
    *number = total;
    return ESP_OK;
}

#endif /* CONFIG_ESP_WIFI_QEMU */
