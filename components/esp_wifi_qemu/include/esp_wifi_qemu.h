#pragma once
/**
 * @file esp_wifi_qemu.h
 * @brief Internal header for the QEMU virtual Wi-Fi component.
 *
 * MMIO register layout (base 0x3ff75000 = DR_REG_WDEV_BASE):
 * See docs/qemu-wifi.md §2 for the full register table.
 */

#include <stdint.h>
#include "esp_err.h"

/* ---------- MMIO base address (same as real ESP32 WDEV peripheral) -------- */
#define WIFI_QEMU_BASE      0x3ff75000UL

/* ---------- Register offsets ------------------------------------------------ */
#define WIFI_REG_VER            0x000  /**< [31:16] major, [15:0] minor        */
#define WIFI_REG_CMD            0x004  /**< Write cmd code; 0=idle, 1=busy     */
#define WIFI_REG_STATUS         0x008  /**< Current state (WIFI_STATE_*)       */
#define WIFI_REG_EVENT          0x00c  /**< Pending event (write 0 to ack)     */
#define WIFI_REG_IRQ_ENABLE     0x010  /**< Bitmask of enabled events          */
#define WIFI_REG_SSID_LEN       0x014  /**< SSID length 0–32                  */
#define WIFI_REG_SSID_BASE      0x018  /**< SSID bytes (32 bytes, 8 regs)     */
#define WIFI_REG_PASS_LEN       0x038  /**< Passphrase length 0–63            */
#define WIFI_REG_PASS_BASE      0x03c  /**< Passphrase bytes (64 bytes, 16 r) */
#define WIFI_REG_MAC0           0x080  /**< MAC bytes 0–3 (read-only)         */
#define WIFI_REG_MAC1           0x084  /**< MAC bytes 4–5 in [31:16]          */
#define WIFI_REG_IP_ADDR        0x088  /**< Assigned IPv4 (LE u32)            */
#define WIFI_REG_IP_MASK        0x08c  /**< Subnet mask (LE u32)              */
#define WIFI_REG_IP_GW          0x090  /**< Default gateway (LE u32)          */
#define WIFI_REG_SCAN_COUNT     0x094  /**< Number of scan results            */
#define WIFI_REG_SCAN_IDX       0x098  /**< Write N to load result N          */
#define WIFI_REG_SCAN_RSSI      0x09c  /**< RSSI of selected result (s8)      */
#define WIFI_REG_SCAN_SSID_LEN  0x0a0  /**< SSID length of selected result    */
#define WIFI_REG_SCAN_SSID_BASE 0x0a4  /**< SSID bytes of selected result     */
#define WIFI_REG_SCAN_BSSID0    0x0c4  /**< BSSID bytes 0–3                   */
#define WIFI_REG_SCAN_BSSID1    0x0c8  /**< BSSID bytes 4–5 in [31:16]        */
#define WIFI_REG_CTRL_SOCK_LEN  0x0d0  /**< ctrl socket path length           */
#define WIFI_REG_CTRL_SOCK_BASE 0x0d4  /**< ctrl socket path bytes (64 bytes) */

/* ---------- Command codes (write to WIFI_REG_CMD) -------------------------- */
#define WIFI_CMD_INIT           0x01
#define WIFI_CMD_DEINIT         0x02
#define WIFI_CMD_SET_MODE_STA   0x03
#define WIFI_CMD_START          0x04
#define WIFI_CMD_STOP           0x05
#define WIFI_CMD_CONNECT        0x06
#define WIFI_CMD_DISCONNECT     0x07
#define WIFI_CMD_SCAN           0x08
#define WIFI_CMD_GET_MAC        0x09

/* ---------- Event codes (read from WIFI_REG_EVENT) ------------------------- */
#define WIFI_EVT_NONE           0x00
#define WIFI_EVT_INIT_DONE      0x01
#define WIFI_EVT_INIT_FAIL      0x02
#define WIFI_EVT_START_DONE     0x03
#define WIFI_EVT_STOP_DONE      0x04
#define WIFI_EVT_CONNECTED      0x05
#define WIFI_EVT_DISCONNECTED   0x06
#define WIFI_EVT_GOT_IP         0x07
#define WIFI_EVT_SCAN_DONE      0x08
#define WIFI_EVT_ERROR          0x09

/* ---------- State codes (read from WIFI_REG_STATUS) ------------------------ */
#define WIFI_STATE_UNINIT       0x00
#define WIFI_STATE_IDLE         0x01
#define WIFI_STATE_STARTED      0x02
#define WIFI_STATE_CONNECTING   0x03
#define WIFI_STATE_CONNECTED    0x04
#define WIFI_STATE_ERROR        0x10

/* ---------- Helper macros --------------------------------------------------- */
#define WIFI_QEMU_REG(offset)  \
    (*((volatile uint32_t *)(WIFI_QEMU_BASE + (offset))))

/** Write a 32-bit value to a QEMU Wi-Fi MMIO register. */
static inline void wifi_qemu_write(uint32_t offset, uint32_t val)
{
    WIFI_QEMU_REG(offset) = val;
}

/** Read a 32-bit value from a QEMU Wi-Fi MMIO register. */
static inline uint32_t wifi_qemu_read(uint32_t offset)
{
    return WIFI_QEMU_REG(offset);
}

/**
 * @brief Write a command and busy-wait for completion (polling WIFI_REG_CMD).
 * @param cmd  Command code (WIFI_CMD_*)
 * @param timeout_ms  Max wait in milliseconds; 0 = wait forever.
 * @return ESP_OK, ESP_ERR_TIMEOUT, or ESP_FAIL (EVT_ERROR received)
 */
esp_err_t wifi_qemu_send_cmd(uint32_t cmd, uint32_t timeout_ms);
