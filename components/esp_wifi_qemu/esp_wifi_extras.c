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
#include <string.h>
#include "esp_err.h"
#include "esp_log.h"
#include "esp_wifi.h"
#include "esp_wifi_qemu.h"
#include "esp_wifi_private.h"
#include "esp_wifi_types.h"

static const char *TAG = "esp_wifi_qemu";

/* ---------------------------------------------------------------------------
 * Day-43 Phase-B: round-trip storage for runtime configuration
 *
 * Stock ESP-IDF samples (fast_scan, iperf, wifi_country, power_save) call
 * pairs of esp_wifi_set_X / esp_wifi_get_X and assume the getter returns
 * the value the setter just wrote.  These were previously no-ops returning
 * fixed defaults; now they round-trip through static state.  Real radio
 * effects (channel switching, regulatory limits, …) are out of scope —
 * QEMU has no PHY.
 * -------------------------------------------------------------------------*/

static uint8_t            s_channel_primary  = 1;
static wifi_second_chan_t s_channel_second   = WIFI_SECOND_CHAN_NONE;
static wifi_country_t     s_country = {
    .cc           = "CN",
    .schan        = 1,
    .nchan        = 13,
    .max_tx_power = 20,
    .policy       = WIFI_COUNTRY_POLICY_AUTO,
};
/* max_tx_power is stored in IDF's 0.25 dBm units (range 8..84 = 2..21 dBm). */
static int8_t             s_max_tx_power_qdbm = 80;  /* 20 dBm */
/* Per-interface state (indexed by wifi_interface_t: 0=STA, 1=AP). */
#define QEMU_WIFI_IF_COUNT 2
static uint8_t            s_protocol[QEMU_WIFI_IF_COUNT] = {
    WIFI_PROTOCOL_11B | WIFI_PROTOCOL_11G | WIFI_PROTOCOL_11N,
    WIFI_PROTOCOL_11B | WIFI_PROTOCOL_11G | WIFI_PROTOCOL_11N,
};
static wifi_bandwidth_t   s_bandwidth[QEMU_WIFI_IF_COUNT] = {
    WIFI_BW_HT20, WIFI_BW_HT20,
};

/* Convert an 802.11 channel-centre frequency in MHz to a primary channel
 * number.  Returns 0 if the frequency is not in a recognised band. */
static uint8_t qemu_freq_to_channel(uint16_t freq_mhz)
{
    if (freq_mhz == 0) {
        return 0;
    }
    if (freq_mhz == 2484) {
        return 14;
    }
    if (freq_mhz >= 2412 && freq_mhz <= 2472) {
        return (uint8_t)((freq_mhz - 2407) / 5);
    }
    if (freq_mhz >= 5180 && freq_mhz <= 5885) {
        return (uint8_t)((freq_mhz - 5000) / 5);
    }
    return 0;
}

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
    if ((unsigned)ifx >= QEMU_WIFI_IF_COUNT) {
        return ESP_ERR_INVALID_ARG;
    }
    if (bw != WIFI_BW_HT20 && bw != WIFI_BW_HT40) {
        return ESP_ERR_INVALID_ARG;
    }
    s_bandwidth[ifx] = bw;
    ESP_LOGD(TAG, "set_bandwidth(ifx=%d, bw=%d)", ifx, bw);
    return ESP_OK;
}

esp_err_t esp_wifi_get_bandwidth(wifi_interface_t ifx, wifi_bandwidth_t *bw)
{
    if (!bw || (unsigned)ifx >= QEMU_WIFI_IF_COUNT) {
        return ESP_ERR_INVALID_ARG;
    }
    *bw = s_bandwidth[ifx];
    ESP_LOGD(TAG, "get_bandwidth(ifx=%d) → %d", ifx, *bw);
    return ESP_OK;
}

/* ---------------------------------------------------------------------------
 * Channel
 * -------------------------------------------------------------------------*/

esp_err_t esp_wifi_set_channel(uint8_t primary, wifi_second_chan_t second)
{
    if (primary < 1 || primary > 14) {
        return ESP_ERR_INVALID_ARG;
    }
    if (second != WIFI_SECOND_CHAN_NONE  &&
        second != WIFI_SECOND_CHAN_ABOVE &&
        second != WIFI_SECOND_CHAN_BELOW) {
        return ESP_ERR_INVALID_ARG;
    }
    s_channel_primary = primary;
    s_channel_second  = second;
    ESP_LOGD(TAG, "set_channel(primary=%u, second=%d)", primary, second);
    return ESP_OK;
}

esp_err_t esp_wifi_get_channel(uint8_t *primary, wifi_second_chan_t *second)
{
    if (!primary || !second) {
        return ESP_ERR_INVALID_ARG;
    }
    /* If the firmware is connected to an AP, return the AP's channel
     * (Phase-A reuse): the QEMU device exposes the connected AP's freq
     * via WIFI_REG_CONN_FREQ_RSSI_AUTH and freq==0 means "not connected". */
    uint16_t freq = (uint16_t)(wifi_qemu_read(WIFI_REG_CONN_FREQ_RSSI_AUTH) & 0xffff);
    uint8_t  ch   = qemu_freq_to_channel(freq);
    if (ch != 0) {
        *primary = ch;
    } else {
        *primary = s_channel_primary;
    }
    *second = s_channel_second;
    ESP_LOGD(TAG, "get_channel() → ch=%u sec=%d", *primary, *second);
    return ESP_OK;
}

/* ---------------------------------------------------------------------------
 * Country / regulatory
 * -------------------------------------------------------------------------*/

esp_err_t esp_wifi_set_country(const wifi_country_t *country)
{
    if (!country) {
        return ESP_ERR_INVALID_ARG;
    }
    if (country->schan < 1 || country->schan > 14 ||
        country->nchan < 1 || country->nchan > 14 ||
        (uint16_t)(country->schan + country->nchan - 1) > 14) {
        return ESP_ERR_INVALID_ARG;
    }
    s_country = *country;
    ESP_LOGD(TAG, "set_country(cc=%c%c schan=%u nchan=%u)",
             country->cc[0] ? country->cc[0] : '?',
             country->cc[1] ? country->cc[1] : '?',
             country->schan, country->nchan);
    return ESP_OK;
}

esp_err_t esp_wifi_get_country(wifi_country_t *country)
{
    if (!country) {
        return ESP_ERR_INVALID_ARG;
    }
    *country = s_country;
    return ESP_OK;
}

esp_err_t esp_wifi_get_country_code(char *country)
{
    if (!country) {
        return ESP_ERR_INVALID_ARG;
    }
    country[0] = s_country.cc[0] ? s_country.cc[0] : 'C';
    country[1] = s_country.cc[1] ? s_country.cc[1] : 'N';
    country[2] = '\0';
    return ESP_OK;
}

/* ---------------------------------------------------------------------------
 * TX power
 * -------------------------------------------------------------------------*/

esp_err_t esp_wifi_set_max_tx_power(int8_t power)
{
    /* IDF spec: range 8..84 in 0.25 dBm units (= 2..21 dBm). */
    if (power < 8 || power > 84) {
        return ESP_ERR_INVALID_ARG;
    }
    s_max_tx_power_qdbm = power;
    ESP_LOGD(TAG, "set_max_tx_power(%d * 0.25 dBm)", power);
    return ESP_OK;
}

esp_err_t esp_wifi_get_max_tx_power(int8_t *power)
{
    if (!power) {
        return ESP_ERR_INVALID_ARG;
    }
    *power = s_max_tx_power_qdbm;
    return ESP_OK;
}

/* ---------------------------------------------------------------------------
 * Protocol
 * -------------------------------------------------------------------------*/

esp_err_t esp_wifi_set_protocol(wifi_interface_t ifx, uint8_t protocol_bitmap)
{
    if ((unsigned)ifx >= QEMU_WIFI_IF_COUNT) {
        return ESP_ERR_INVALID_ARG;
    }
    s_protocol[ifx] = protocol_bitmap;
    ESP_LOGD(TAG, "set_protocol(ifx=%d, 0x%02x)", ifx, protocol_bitmap);
    return ESP_OK;
}

esp_err_t esp_wifi_get_protocol(wifi_interface_t ifx, uint8_t *protocol_bitmap)
{
    if (!protocol_bitmap || (unsigned)ifx >= QEMU_WIFI_IF_COUNT) {
        return ESP_ERR_INVALID_ARG;
    }
    *protocol_bitmap = s_protocol[ifx];
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

    /* Day-42 Phase-A: read the connected-AP record from the QEMU device.
     * The device populates these registers from the wpa_supplicant STATUS
     * reply parsed in wpa_parse_status().  When no STATUS has been parsed
     * yet (e.g. before connect, or after disconnect) all fields are zero. */
    memset(ap_info, 0, sizeof(*ap_info));

    /* BSSID from the two packed regs. */
    uint32_t b0 = wifi_qemu_read(WIFI_REG_CONN_BSSID0);
    uint32_t b1 = wifi_qemu_read(WIFI_REG_CONN_BSSID1);
    memcpy(ap_info->bssid, &b0, 4);
    ap_info->bssid[4] = (uint8_t)((b1 >> 24) & 0xff);
    ap_info->bssid[5] = (uint8_t)((b1 >> 16) & 0xff);

    /* freq / rssi / authmode packed in one reg. */
    uint32_t fra = wifi_qemu_read(WIFI_REG_CONN_FREQ_RSSI_AUTH);
    uint16_t freq    = (uint16_t)(fra & 0xffff);
    int8_t   rssi    = (int8_t)((fra >> 16) & 0xff);
    uint8_t  authmode = (uint8_t)((fra >> 24) & 0xff);
    ap_info->rssi    = rssi;
    ap_info->authmode = (wifi_auth_mode_t)authmode;

    /* MHz -> channel (matches Day-41 scan path). */
    uint8_t channel;
    if (freq >= 2412 && freq <= 2472) {
        channel = (uint8_t)((freq - 2407) / 5);
    } else if (freq == 2484) {
        channel = 14;
    } else if (freq >= 5160 && freq <= 5885) {
        channel = (uint8_t)((freq - 5000) / 5);
    } else {
        channel = 1;
    }
    ap_info->primary = channel;
    ap_info->second  = WIFI_SECOND_CHAN_NONE;

    /* pairwise / group cipher packed in one reg. */
    uint32_t cph = wifi_qemu_read(WIFI_REG_CONN_CIPHERS);
    ap_info->pairwise_cipher = (wifi_cipher_type_t)(cph & 0xff);
    ap_info->group_cipher    = (wifi_cipher_type_t)((cph >> 8) & 0xff);

    /* SSID is not transmitted via STATUS reliably; fall back to the
     * config the firmware itself wrote via esp_wifi_set_config(). */
    size_t slen = strnlen((char *)s_sta_cfg.sta.ssid, sizeof(ap_info->ssid) - 1);
    memcpy(ap_info->ssid, s_sta_cfg.sta.ssid, slen);
    ap_info->ssid[slen] = 0;

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
    /* Day-42 Phase-A: derive from connected-AP record. */
    uint32_t fra = wifi_qemu_read(WIFI_REG_CONN_FREQ_RSSI_AUTH);
    int8_t v = (int8_t)((fra >> 16) & 0xff);
    *rssi = (int)v;
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

#endif /* CONFIG_ESP_WIFI_QEMU */
