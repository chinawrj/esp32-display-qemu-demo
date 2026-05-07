/**
 * @file esp_wifi_promisc.c
 * @brief QEMU Wi-Fi shim — promiscuous, vendor IE, and raw-TX stubs.
 *
 * Promiscuous mode and raw 802.11 frame injection are not supported in the
 * QEMU shim v1.  These stubs satisfy the linker for stock samples that
 * reference these symbols indirectly (e.g. via esp_wifi component wrappers).
 *
 * Split from esp_wifi_extras.c (Day 33) to keep individual files ≤ 300 lines.
 */

#include "sdkconfig.h"

#if CONFIG_ESP_WIFI_QEMU

#include <inttypes.h>
#include "esp_err.h"
#include "esp_log.h"
#include "esp_wifi.h"
#include "esp_wifi_types.h"

static const char *TAG = "esp_wifi_qemu";

/* Day-44: promiscuous-mode state (round-trip storage; raw RX still TODO). */
static bool                      s_promisc_enabled = false;
static wifi_promiscuous_filter_t s_promisc_filter      = { .filter_mask = WIFI_PROMIS_FILTER_MASK_ALL };
static wifi_promiscuous_filter_t s_promisc_ctrl_filter = { .filter_mask = WIFI_PROMIS_CTRL_FILTER_MASK_ALL };

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
        ESP_LOGW(TAG, "set_promiscuous(true) — RX delivery not implemented (Phase E); state stored only");
    }
    s_promisc_enabled = en;
    return ESP_OK;
}

esp_err_t esp_wifi_get_promiscuous(bool *en)
{
    if (!en) {
        return ESP_ERR_INVALID_ARG;
    }
    *en = s_promisc_enabled;
    return ESP_OK;
}

esp_err_t esp_wifi_set_promiscuous_filter(const wifi_promiscuous_filter_t *filter)
{
    if (!filter) {
        return ESP_ERR_INVALID_ARG;
    }
    s_promisc_filter = *filter;
    ESP_LOGD(TAG, "set_promiscuous_filter(0x%08" PRIx32 ")", filter->filter_mask);
    return ESP_OK;
}

esp_err_t esp_wifi_get_promiscuous_filter(wifi_promiscuous_filter_t *filter)
{
    if (!filter) {
        return ESP_ERR_INVALID_ARG;
    }
    *filter = s_promisc_filter;
    return ESP_OK;
}

esp_err_t esp_wifi_set_promiscuous_ctrl_filter(const wifi_promiscuous_filter_t *filter)
{
    if (!filter) {
        return ESP_ERR_INVALID_ARG;
    }
    s_promisc_ctrl_filter = *filter;
    return ESP_OK;
}

esp_err_t esp_wifi_get_promiscuous_ctrl_filter(wifi_promiscuous_filter_t *filter)
{
    if (!filter) {
        return ESP_ERR_INVALID_ARG;
    }
    *filter = s_promisc_ctrl_filter;
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
