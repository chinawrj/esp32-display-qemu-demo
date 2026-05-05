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

extern wifi_config_t s_sta_cfg;

#endif /* CONFIG_ESP_WIFI_QEMU */
