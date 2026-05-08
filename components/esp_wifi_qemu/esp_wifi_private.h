#pragma once
/**
 * @file esp_wifi_private.h
 * @brief Internal shared state for the QEMU virtual Wi-Fi component.
 *
 * Not part of the public API. Include ONLY from within this component.
 */

#include "sdkconfig.h"

#if CONFIG_ESP_WIFI_QEMU

#include <stddef.h>
#include "esp_wifi.h"

/* Portable MIN for size_t operands */
#define SHIM_MIN(a, b) ((size_t)(a) < (size_t)(b) ? (size_t)(a) : (size_t)(b))

/* Shared Wi-Fi configuration — written by esp_wifi_set_config,
 * read by esp_wifi_get_config, esp_wifi_connect, and wifi_event_task. */

/* Transmit a raw Ethernet frame via QEMU MMIO (esp_wifi_netif.c).
 * Called from esp_wifi_internal_tx() when the IDF default wifi driver
 * is in use (e.g. protocol_examples_common based samples). */
int qemu_wifi_tx_raw(const void *buffer, uint16_t len);

/* Day-48 Phase-E: TX an arbitrary buffer (Ethernet OR raw 802.11) onto
 * the QEMU virtual wire WITHOUT tapping the promiscuous callback.  Used
 * by esp_wifi_80211_tx() which has already delivered the original raw
 * frame to the callback and must not double-fabricate an Ethernet wrap. */
int qemu_wifi_tx_raw_no_promisc(const void *buffer, uint16_t len);

/* SoftAP fake-station table (esp_wifi_ap.c).
 * Day-45: AP/APSTA start fabricates N synthetic stations and posts
 * WIFI_EVENT_AP_STACONNECTED for each, so stock softAP samples see
 * non-empty join logs and esp_wifi_ap_get_sta_list returns real entries. */
void      qemu_wifi_ap_clear_stations(void);
esp_err_t qemu_wifi_ap_inject_fake_station(uint8_t index);

/* Day-47 Phase-E: deliver an Ethernet frame to the registered promiscuous
 * RX callback (wraps it in a fabricated 802.11 DATA header).  No-op when
 * promiscuous mode is disabled or no callback is registered.  Called from
 * the netif RX/TX paths regardless of whether the firmware enables promisc. */
void qemu_promisc_deliver_eth(const void *eth_frame, size_t eth_len, bool from_tx);

extern wifi_config_t s_sta_cfg;

#endif /* CONFIG_ESP_WIFI_QEMU */
