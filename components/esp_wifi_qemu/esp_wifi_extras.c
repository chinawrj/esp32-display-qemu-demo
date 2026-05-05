/**
 * @file esp_wifi_extras.c
 * @brief QEMU Wi-Fi shim — stub implementations for esp_wifi_* symbols that
 *        are called by ESP-IDF Wi-Fi samples but not functionally required
 *        for QEMU STA emulation (GAP-A).
 *
 * Each stub returns ESP_OK (or an appropriate error) and emits a LOGD so
 * we can track which APIs a stock sample exercises at runtime.
 *
 * Symbols covered here are the ones most likely to be called by Phase-1
 * target samples (station, scan, tcp_client, udp_client).  AP / ESPNOW /
 * WPS stubs are tracked in BACKLOG.md gaps B, C, D and will be added when
 * those samples become Phase-1 targets.
 */

#include "sdkconfig.h"

#if CONFIG_ESP_WIFI_QEMU

#include <inttypes.h>
#include "esp_err.h"
#include "esp_log.h"
#include "esp_wifi.h"
#include "esp_wifi_types.h"

static const char *TAG = "esp_wifi_qemu";

/* ---------------------------------------------------------------------------
 * Storage / NVS
 * -------------------------------------------------------------------------*/

esp_err_t esp_wifi_set_storage(wifi_storage_t storage)
{
    /* QEMU shim always operates in RAM; storage type is irrelevant. */
    ESP_LOGD(TAG, "set_storage(%d) — no-op in QEMU", storage);
    return ESP_OK;
}

/* ---------------------------------------------------------------------------
 * Factory reset / restore
 * -------------------------------------------------------------------------*/

esp_err_t esp_wifi_restore(void)
{
    ESP_LOGD(TAG, "restore() — no-op in QEMU");
    return ESP_OK;
}

/* ---------------------------------------------------------------------------
 * Power-save mode
 * -------------------------------------------------------------------------*/

esp_err_t esp_wifi_set_ps(wifi_ps_type_t type)
{
    ESP_LOGD(TAG, "set_ps(%d) — no-op in QEMU", type);
    return ESP_OK;
}

esp_err_t esp_wifi_get_ps(wifi_ps_type_t *type)
{
    if (!type) {
        return ESP_ERR_INVALID_ARG;
    }
    *type = WIFI_PS_NONE;
    ESP_LOGD(TAG, "get_ps() → WIFI_PS_NONE (QEMU)");
    return ESP_OK;
}

/* ---------------------------------------------------------------------------
 * Bandwidth
 * -------------------------------------------------------------------------*/

esp_err_t esp_wifi_set_bandwidth(wifi_interface_t ifx, wifi_bandwidth_t bw)
{
    ESP_LOGD(TAG, "set_bandwidth(ifx=%d, bw=%d) — no-op in QEMU", ifx, bw);
    return ESP_OK;
}

esp_err_t esp_wifi_get_bandwidth(wifi_interface_t ifx, wifi_bandwidth_t *bw)
{
    if (!bw) {
        return ESP_ERR_INVALID_ARG;
    }
    *bw = WIFI_BW_HT20;
    ESP_LOGD(TAG, "get_bandwidth(ifx=%d) → WIFI_BW_HT20 (QEMU)", ifx);
    return ESP_OK;
}

/* ---------------------------------------------------------------------------
 * Channel
 * -------------------------------------------------------------------------*/

esp_err_t esp_wifi_set_channel(uint8_t primary, wifi_second_chan_t second)
{
    ESP_LOGD(TAG, "set_channel(primary=%u, second=%d) — no-op in QEMU",
             primary, second);
    return ESP_OK;
}

esp_err_t esp_wifi_get_channel(uint8_t *primary, wifi_second_chan_t *second)
{
    if (!primary || !second) {
        return ESP_ERR_INVALID_ARG;
    }
    *primary = 1;
    *second  = WIFI_SECOND_CHAN_NONE;
    ESP_LOGD(TAG, "get_channel() → ch1 (QEMU)");
    return ESP_OK;
}

/* ---------------------------------------------------------------------------
 * Country / regulatory
 * -------------------------------------------------------------------------*/

esp_err_t esp_wifi_set_country(const wifi_country_t *country)
{
    ESP_LOGD(TAG, "set_country() — no-op in QEMU");
    return ESP_OK;
}

esp_err_t esp_wifi_get_country(wifi_country_t *country)
{
    if (!country) {
        return ESP_ERR_INVALID_ARG;
    }
    /* Return a safe default: CN, channels 1-13. */
    static const wifi_country_t s_default_country = {
        .cc      = "CN",
        .schan   = 1,
        .nchan   = 13,
        .max_tx_power = 20,
        .policy  = WIFI_COUNTRY_POLICY_AUTO,
    };
    *country = s_default_country;
    return ESP_OK;
}

esp_err_t esp_wifi_get_country_code(char *country)
{
    if (!country) {
        return ESP_ERR_INVALID_ARG;
    }
    country[0] = 'C';
    country[1] = 'N';
    country[2] = '\0';
    return ESP_OK;
}

/* ---------------------------------------------------------------------------
 * TX power
 * -------------------------------------------------------------------------*/

esp_err_t esp_wifi_set_max_tx_power(int8_t power)
{
    ESP_LOGD(TAG, "set_max_tx_power(%d) — no-op in QEMU", power);
    return ESP_OK;
}

esp_err_t esp_wifi_get_max_tx_power(int8_t *power)
{
    if (!power) {
        return ESP_ERR_INVALID_ARG;
    }
    *power = 20; /* 20 dBm */
    return ESP_OK;
}

/* ---------------------------------------------------------------------------
 * Protocol
 * -------------------------------------------------------------------------*/

esp_err_t esp_wifi_set_protocol(wifi_interface_t ifx, uint8_t protocol_bitmap)
{
    ESP_LOGD(TAG, "set_protocol(ifx=%d, 0x%02x) — no-op in QEMU",
             ifx, protocol_bitmap);
    return ESP_OK;
}

esp_err_t esp_wifi_get_protocol(wifi_interface_t ifx, uint8_t *protocol_bitmap)
{
    if (!protocol_bitmap) {
        return ESP_ERR_INVALID_ARG;
    }
    *protocol_bitmap = WIFI_PROTOCOL_11B | WIFI_PROTOCOL_11G | WIFI_PROTOCOL_11N;
    return ESP_OK;
}

/* ---------------------------------------------------------------------------
 * STA AP info (connected AP record)
 * -------------------------------------------------------------------------*/

esp_err_t esp_wifi_sta_get_ap_info(wifi_ap_record_t *ap_info)
{
    if (!ap_info) {
        return ESP_ERR_INVALID_ARG;
    }
    /* Return a minimal fake record for the QEMU virtual AP. */
    static const wifi_ap_record_t s_fake_ap = {
        .bssid       = {0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF},
        .ssid        = "QEMU_TEST",
        .primary     = 1,
        .second      = WIFI_SECOND_CHAN_NONE,
        .rssi        = -50,
        .authmode    = WIFI_AUTH_WPA2_PSK,
        .pairwise_cipher = WIFI_CIPHER_TYPE_CCMP,
        .group_cipher    = WIFI_CIPHER_TYPE_CCMP,
    };
    *ap_info = s_fake_ap;
    return ESP_OK;
}

/* ---------------------------------------------------------------------------
 * RSSI
 * -------------------------------------------------------------------------*/

esp_err_t esp_wifi_sta_get_rssi(int *rssi)
{
    if (!rssi) {
        return ESP_ERR_INVALID_ARG;
    }
    *rssi = -50;  /* fixed fake RSSI for QEMU */
    return ESP_OK;
}

/* ---------------------------------------------------------------------------
 * Event mask
 * -------------------------------------------------------------------------*/

esp_err_t esp_wifi_set_event_mask(uint32_t mask)
{
    ESP_LOGD(TAG, "set_event_mask(0x%08" PRIx32 ") — no-op in QEMU", mask);
    return ESP_OK;
}

esp_err_t esp_wifi_get_event_mask(uint32_t *mask)
{
    if (!mask) {
        return ESP_ERR_INVALID_ARG;
    }
    *mask = WIFI_EVENT_MASK_NONE;
    return ESP_OK;
}

/* ---------------------------------------------------------------------------
 * Inactive time (AP-side idle timeout)
 * -------------------------------------------------------------------------*/

esp_err_t esp_wifi_set_inactive_time(wifi_interface_t ifx, uint16_t sec)
{
    ESP_LOGD(TAG, "set_inactive_time(ifx=%d, %u) — no-op in QEMU", ifx, sec);
    return ESP_OK;
}

esp_err_t esp_wifi_get_inactive_time(wifi_interface_t ifx, uint16_t *sec)
{
    if (!sec) {
        return ESP_ERR_INVALID_ARG;
    }
    *sec = 300;
    return ESP_OK;
}

/* ---------------------------------------------------------------------------
 * Vendor IE (beacon injection) — stub: not meaningful in QEMU
 * -------------------------------------------------------------------------*/

esp_err_t esp_wifi_set_vendor_ie(bool enable, wifi_vendor_ie_type_t type,
                                  wifi_vendor_ie_id_t idx, const void *vnd_ie)
{
    ESP_LOGD(TAG, "set_vendor_ie(enable=%d) — no-op in QEMU", enable);
    return ESP_OK;
}

esp_err_t esp_wifi_set_vendor_ie_cb(esp_vendor_ie_cb_t cb, void *ctx)
{
    ESP_LOGD(TAG, "set_vendor_ie_cb() — no-op in QEMU");
    return ESP_OK;
}

/* ---------------------------------------------------------------------------
 * Promiscuous mode — stub (no raw frame capture in QEMU shim v1)
 * -------------------------------------------------------------------------*/

esp_err_t esp_wifi_set_promiscuous(bool en)
{
    if (en) {
        ESP_LOGW(TAG, "set_promiscuous(true) — not supported in QEMU shim v1");
        return ESP_ERR_NOT_SUPPORTED;
    }
    return ESP_OK;
}

esp_err_t esp_wifi_get_promiscuous(bool *en)
{
    if (!en) {
        return ESP_ERR_INVALID_ARG;
    }
    *en = false;
    return ESP_OK;
}

esp_err_t esp_wifi_set_promiscuous_filter(const wifi_promiscuous_filter_t *filter)
{
    ESP_LOGD(TAG, "set_promiscuous_filter() — no-op in QEMU");
    return ESP_OK;
}

esp_err_t esp_wifi_get_promiscuous_filter(wifi_promiscuous_filter_t *filter)
{
    if (!filter) {
        return ESP_ERR_INVALID_ARG;
    }
    filter->filter_mask = WIFI_PROMIS_FILTER_MASK_ALL;
    return ESP_OK;
}

esp_err_t esp_wifi_set_promiscuous_ctrl_filter(const wifi_promiscuous_filter_t *filter)
{
    return ESP_OK;
}

esp_err_t esp_wifi_get_promiscuous_ctrl_filter(wifi_promiscuous_filter_t *filter)
{
    if (!filter) {
        return ESP_ERR_INVALID_ARG;
    }
    filter->filter_mask = WIFI_PROMIS_CTRL_FILTER_MASK_ALL;
    return ESP_OK;
}

esp_err_t esp_wifi_set_promiscuous_rx_cb(wifi_promiscuous_cb_t cb)
{
    ESP_LOGD(TAG, "set_promiscuous_rx_cb() — no-op in QEMU");
    return ESP_OK;
}

/* ---------------------------------------------------------------------------
 * Raw 802.11 frame TX — not supported in shim v1
 * -------------------------------------------------------------------------*/

esp_err_t esp_wifi_80211_tx(wifi_interface_t ifx, const void *buffer,
                             int len, bool en_sys_seq)
{
    ESP_LOGW(TAG, "80211_tx() — not supported in QEMU shim v1");
    return ESP_ERR_NOT_SUPPORTED;
}

#endif /* CONFIG_ESP_WIFI_QEMU */
