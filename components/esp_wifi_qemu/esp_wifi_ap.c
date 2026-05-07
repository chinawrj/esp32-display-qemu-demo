/**
 * @file esp_wifi_ap.c
 * @brief QEMU virtual Wi-Fi driver — SoftAP station-list emulation.
 *
 * Day-45: instead of returning an empty station list, the QEMU shim now
 * keeps a firmware-side table of associated stations.  The table is
 * populated by `qemu_wifi_ap_inject_fake_station()` (called from
 * esp_wifi_start() in AP/APSTA mode) and drained by
 * `esp_wifi_deauth_sta()`.  Stock softAP samples that read
 * `esp_wifi_ap_get_sta_list()` or print join logs from
 * WIFI_EVENT_AP_STACONNECTED therefore see real entries.
 *
 * Real radio association is still impossible in QEMU; the synthetic
 * stations are deterministic placeholders so behaviour-driven samples
 * (sta count, deauth, AID lookup) can be exercised end-to-end.
 */

#include "sdkconfig.h"

#if CONFIG_ESP_WIFI_QEMU

#include <string.h>
#include "esp_err.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_wifi_qemu.h"
#include "esp_wifi_private.h"

static const char *TAG = "wifi_qemu_ap";

#ifndef ESP_WIFI_MAX_CONN_NUM
#define ESP_WIFI_MAX_CONN_NUM 4
#endif

typedef struct {
    bool     in_use;
    uint16_t aid;
    uint8_t  mac[6];
    int8_t   rssi;
    wifi_phy_mode_t phy_mode;
} qemu_ap_sta_t;

static qemu_ap_sta_t s_ap_table[ESP_WIFI_MAX_CONN_NUM];

/* ---------------------------------------------------------------------------
 * Internal helpers (called from esp_wifi_shim.c on AP start)
 * -------------------------------------------------------------------------*/

static int qemu_ap_find_by_mac(const uint8_t mac[6])
{
    for (int i = 0; i < ESP_WIFI_MAX_CONN_NUM; ++i) {
        if (s_ap_table[i].in_use && memcmp(s_ap_table[i].mac, mac, 6) == 0) {
            return i;
        }
    }
    return -1;
}

static int qemu_ap_find_by_aid(uint16_t aid)
{
    for (int i = 0; i < ESP_WIFI_MAX_CONN_NUM; ++i) {
        if (s_ap_table[i].in_use && s_ap_table[i].aid == aid) {
            return i;
        }
    }
    return -1;
}

void qemu_wifi_ap_clear_stations(void)
{
    memset(s_ap_table, 0, sizeof(s_ap_table));
}

esp_err_t qemu_wifi_ap_inject_fake_station(uint8_t index)
{
    if (index >= ESP_WIFI_MAX_CONN_NUM) {
        return ESP_ERR_INVALID_ARG;
    }
    qemu_ap_sta_t *e = &s_ap_table[index];
    if (e->in_use) {
        return ESP_ERR_INVALID_STATE;
    }
    e->in_use   = true;
    e->aid      = (uint16_t)(index + 1);
    e->rssi     = -42;
    e->phy_mode = WIFI_PHY_MODE_11G;
    /* Deterministic locally-administered MAC: 02:QE:00:00:00:idx */
    e->mac[0] = 0x02;
    e->mac[1] = 'Q';
    e->mac[2] = 'E';
    e->mac[3] = 0x00;
    e->mac[4] = 0x00;
    e->mac[5] = index;

    wifi_event_ap_staconnected_t ev = {
        .aid       = e->aid,
        .is_mesh_child = false,
    };
    memcpy(ev.mac, e->mac, 6);
    esp_event_post(WIFI_EVENT, WIFI_EVENT_AP_STACONNECTED,
                   &ev, sizeof(ev), portMAX_DELAY);
    ESP_LOGI(TAG, "fake station joined aid=%u mac=" MACSTR,
             (unsigned)e->aid, MAC2STR(e->mac));
    return ESP_OK;
}

/* ---------------------------------------------------------------------------
 * Public esp_wifi_* API
 * -------------------------------------------------------------------------*/

esp_err_t esp_wifi_ap_get_sta_list(wifi_sta_list_t *info)
{
    if (!info) {
        return ESP_ERR_INVALID_ARG;
    }
    memset(info, 0, sizeof(*info));
    int n = 0;
    for (int i = 0; i < ESP_WIFI_MAX_CONN_NUM; ++i) {
        if (!s_ap_table[i].in_use) {
            continue;
        }
        if (n >= (int)(sizeof(info->sta) / sizeof(info->sta[0]))) {
            break;
        }
        wifi_sta_info_t *out = &info->sta[n++];
        memcpy(out->mac, s_ap_table[i].mac, 6);
        out->rssi     = s_ap_table[i].rssi;
        out->phy_11b  = 1;
        out->phy_11g  = 1;
        out->phy_11n  = 1;
    }
    info->num = n;
    ESP_LOGD(TAG, "ap_get_sta_list -> %d stations", n);
    return ESP_OK;
}

esp_err_t esp_wifi_deauth_sta(uint16_t aid)
{
    /* aid == 0 means "deauth all" per IDF docs. */
    if (aid == 0) {
        for (int i = 0; i < ESP_WIFI_MAX_CONN_NUM; ++i) {
            if (!s_ap_table[i].in_use) {
                continue;
            }
            wifi_event_ap_stadisconnected_t ev = {
                .aid    = s_ap_table[i].aid,
                .reason = WIFI_REASON_ASSOC_LEAVE,
            };
            memcpy(ev.mac, s_ap_table[i].mac, 6);
            s_ap_table[i].in_use = false;
            esp_event_post(WIFI_EVENT, WIFI_EVENT_AP_STADISCONNECTED,
                           &ev, sizeof(ev), portMAX_DELAY);
        }
        return ESP_OK;
    }

    int idx = qemu_ap_find_by_aid(aid);
    if (idx < 0) {
        return ESP_ERR_NOT_FOUND;
    }
    wifi_event_ap_stadisconnected_t ev = {
        .aid    = s_ap_table[idx].aid,
        .reason = WIFI_REASON_ASSOC_LEAVE,
    };
    memcpy(ev.mac, s_ap_table[idx].mac, 6);
    s_ap_table[idx].in_use = false;
    esp_event_post(WIFI_EVENT, WIFI_EVENT_AP_STADISCONNECTED,
                   &ev, sizeof(ev), portMAX_DELAY);
    ESP_LOGI(TAG, "deauth_sta aid=%u", (unsigned)aid);
    return ESP_OK;
}

esp_err_t esp_wifi_ap_get_sta_aid(const uint8_t mac[6], uint16_t *aid)
{
    if (!mac || !aid) {
        return ESP_ERR_INVALID_ARG;
    }
    int idx = qemu_ap_find_by_mac(mac);
    if (idx < 0) {
        *aid = 0;
        return ESP_ERR_NOT_FOUND;
    }
    *aid = s_ap_table[idx].aid;
    return ESP_OK;
}

#endif /* CONFIG_ESP_WIFI_QEMU */
