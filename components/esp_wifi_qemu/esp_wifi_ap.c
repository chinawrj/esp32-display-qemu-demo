/**
 * @file esp_wifi_ap.c
 * @brief QEMU virtual Wi-Fi driver — GAP-B: SoftAP stubs.
 *
 * These stubs allow stock ESP-IDF softAP samples to build and run in QEMU
 * without any source code changes.  AP-side client management is not
 * emulated (QEMU models a STA endpoint only); the stubs return safe no-op
 * values so the sample application can reach its "wifi_init_softap finished."
 * log line.
 */

#include "sdkconfig.h"

#if CONFIG_ESP_WIFI_QEMU

#include <string.h>
#include "esp_err.h"
#include "esp_log.h"
#include "esp_wifi.h"

static const char *TAG = "wifi_qemu_ap";

/**
 * @brief Return the list of stations connected to the soft-AP.
 *
 * QEMU models a STA endpoint only — no real clients can associate.
 * Always returns an empty list (count = 0).
 */
esp_err_t esp_wifi_ap_get_sta_list(wifi_sta_list_t *info)
{
    if (!info) {
        return ESP_ERR_INVALID_ARG;
    }
    memset(info, 0, sizeof(*info));
    ESP_LOGD(TAG, "ap_get_sta_list -> 0 stations (QEMU stub)");
    return ESP_OK;
}

/**
 * @brief De-authenticate a station from the soft-AP.
 *
 * No-op in QEMU (there are no real associated clients).
 */
esp_err_t esp_wifi_deauth_sta(uint16_t aid)
{
    (void)aid;
    ESP_LOGD(TAG, "deauth_sta aid=%u (QEMU no-op)", (unsigned)aid);
    return ESP_OK;
}

/**
 * @brief Get AID for a specific station MAC.
 *
 * Always returns 0 / ESP_ERR_NOT_FOUND in QEMU (no real clients).
 */
esp_err_t esp_wifi_ap_get_sta_aid(const uint8_t mac[6], uint16_t *aid)
{
    (void)mac;
    if (!aid) {
        return ESP_ERR_INVALID_ARG;
    }
    *aid = 0;
    return ESP_ERR_NOT_FOUND;
}

#endif /* CONFIG_ESP_WIFI_QEMU */
