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
#include <stdlib.h>
#include <string.h>
#include "esp_err.h"
#include "esp_log.h"
#include "esp_wifi.h"
#include "esp_wifi_types.h"
#include "esp_wifi_private.h"

static const char *TAG = "esp_wifi_qemu";

/* Day-44: promiscuous-mode state (round-trip storage; raw RX still TODO). */
static bool                      s_promisc_enabled = false;
static wifi_promiscuous_filter_t s_promisc_filter      = { .filter_mask = WIFI_PROMIS_FILTER_MASK_ALL };
static wifi_promiscuous_filter_t s_promisc_ctrl_filter = { .filter_mask = WIFI_PROMIS_CTRL_FILTER_MASK_ALL };
static wifi_promiscuous_cb_t     s_promisc_rx_cb       = NULL;

/* Virtual AP MAC used when fabricating 802.11 BSSID for sniffer samples. */
static const uint8_t s_qemu_virtual_bssid[6] = { 0x02, 0x51, 0x45, 0x00, 0x00, 0xFF };

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
    s_promisc_rx_cb = cb;
    ESP_LOGD(TAG, "set_promiscuous_rx_cb(%p)", cb);
    return ESP_OK;
}

/* ---------------------------------------------------------------------------
 * Day-47 Phase-E: deliver Ethernet frame to promiscuous callback.
 *
 * Wraps the (RX or TX) Ethernet frame in a fabricated 802.11 DATA header
 * + LLC/SNAP so stock sniffer samples (network/simple_sniffer) see DATA
 * frames with correct MAC addresses and EtherType.
 *
 * The ETH frame layout is:  [DA(6)][SA(6)][type(2)][payload...]
 * The fabricated 802.11 frame layout is:
 *   FC(2) DUR(2) ADDR1(6) ADDR2(6) ADDR3(6) SEQ(2)        ← 24-byte hdr
 *   AA AA 03 00 00 00 type(2)                              ← 8-byte LLC/SNAP
 *   payload                                                ← ETH len - 14
 *
 * Direction (ETH frame coming from firmware TX vs. QEMU RX) flips the
 * FromDS / ToDS bits and address ordering.
 * -------------------------------------------------------------------------*/
void qemu_promisc_deliver_eth(const void *eth_frame, size_t eth_len, bool from_tx)
{
    if (!s_promisc_enabled || !s_promisc_rx_cb) {
        return;
    }
    if (!(s_promisc_filter.filter_mask & WIFI_PROMIS_FILTER_MASK_DATA)) {
        return;
    }
    if (!eth_frame || eth_len < 14) {
        return;
    }

    const uint8_t *eth = (const uint8_t *)eth_frame;
    const uint8_t *eth_da   = &eth[0];
    const uint8_t *eth_sa   = &eth[6];
    const uint8_t *eth_type = &eth[12];
    size_t payload_len = eth_len - 14;

    /* 24 (802.11 hdr) + 8 (LLC/SNAP) + payload */
    size_t dot11_len = 24 + 8 + payload_len;
    /* +4 for FCS (we don't compute it; sig_len includes FCS per IDF docs). */
    size_t alloc_len = sizeof(wifi_promiscuous_pkt_t) + dot11_len;

    wifi_promiscuous_pkt_t *pkt = (wifi_promiscuous_pkt_t *)calloc(1, alloc_len);
    if (!pkt) {
        return;
    }

    pkt->rx_ctrl.rssi    = -42;
    pkt->rx_ctrl.channel = 1;
    pkt->rx_ctrl.rate    = 11;        /* 54 Mbps PHY rate index */
    pkt->rx_ctrl.sig_len = (unsigned)(dot11_len + 4);

    uint8_t *p = pkt->payload;
    /* Frame Control: type=Data(2), subtype=Data(0), FromDS / ToDS bits.
     * RX (from AP -> firmware STA): FromDS=1 -> FC byte1 = 0x02
     * TX (from firmware STA -> AP): ToDS=1   -> FC byte1 = 0x01 */
    p[0] = 0x08;                     /* type=10 data, subtype=0000 */
    p[1] = from_tx ? 0x01 : 0x02;    /* ToDS or FromDS */
    p[2] = 0x00; p[3] = 0x00;        /* Duration */

    /* IEEE 802.11 DATA frame address fields:
     *   FromDS=1: ADDR1=DA, ADDR2=BSSID, ADDR3=SA
     *   ToDS=1:   ADDR1=BSSID, ADDR2=SA, ADDR3=DA */
    if (from_tx) {
        memcpy(&p[4],  s_qemu_virtual_bssid, 6); /* ADDR1 = BSSID */
        memcpy(&p[10], eth_sa, 6);               /* ADDR2 = SA */
        memcpy(&p[16], eth_da, 6);               /* ADDR3 = DA */
    } else {
        memcpy(&p[4],  eth_da, 6);               /* ADDR1 = DA */
        memcpy(&p[10], s_qemu_virtual_bssid, 6); /* ADDR2 = BSSID */
        memcpy(&p[16], eth_sa, 6);               /* ADDR3 = SA */
    }
    p[22] = 0x00; p[23] = 0x00;     /* Sequence Control */

    /* LLC/SNAP shim: AA AA 03 | 00 00 00 | EtherType */
    p[24] = 0xAA; p[25] = 0xAA; p[26] = 0x03;
    p[27] = 0x00; p[28] = 0x00; p[29] = 0x00;
    p[30] = eth_type[0]; p[31] = eth_type[1];

    if (payload_len > 0) {
        memcpy(&p[32], &eth[14], payload_len);
    }

    s_promisc_rx_cb(pkt, WIFI_PKT_DATA);
    free(pkt);
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
