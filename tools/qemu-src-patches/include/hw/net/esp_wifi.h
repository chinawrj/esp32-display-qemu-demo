#pragma once
/*
 * ESP32 Virtual Wi-Fi device — QEMU hardware model
 *
 * Implements a virtual Wi-Fi STA peripheral at DR_REG_WDEV_BASE (0x3ff75000).
 * The device bridges to the host wpa_supplicant daemon via its Unix-domain
 * ctrl socket.  Protocol spec: docs/qemu-wifi.md.
 *
 * Copyright (c) 2026 esp32-display-qemu-demo contributors.
 * SPDX-License-Identifier: GPL-2.0-or-later
 */

#include "hw/sysbus.h"
#include "hw/hw.h"
#include "qemu/osdep.h"

/* ---------- QEMU type plumbing -------------------------------------------- */
#define TYPE_ESP_WIFI   "net.esp.wifi"
#define ESP_WIFI(obj)            OBJECT_CHECK(ESPWifiState, (obj), TYPE_ESP_WIFI)
#define ESP_WIFI_GET_CLASS(obj)  OBJECT_GET_CLASS(ESPWifiState, obj, TYPE_ESP_WIFI)
#define ESP_WIFI_CLASS(klass)    OBJECT_CLASS_CHECK(ESPWifiState, klass, TYPE_ESP_WIFI)

/* ---------- Device/protocol version --------------------------------------- */
#define ESP_WIFI_VERSION_MAJOR  1
#define ESP_WIFI_VERSION_MINOR  0

/* ---------- MMIO size ----------------------------------------------------- */
/* 0x124 bytes: covers all control regs + 4 DMA pointer regs.                */
/* MUST stay < 0x144 to avoid overlapping the RNG device at WDEV_BASE+0x144. */
#define ESP_WIFI_IO_SIZE        0x124

/* ---------- Packet buffer size (DMA transfer, no MMIO buffer needed) ------- */
#define WIFI_PKT_BUF_SIZE       1516    /* handles Ethernet max 1514 bytes   */

/* ---------- Register offsets (must match docs/qemu-wifi.md §2) ------------ */
#define WIFI_REG_VER            0x000
#define WIFI_REG_CMD            0x004
#define WIFI_REG_STATUS         0x008
#define WIFI_REG_EVENT          0x00c
#define WIFI_REG_IRQ_ENABLE     0x010
#define WIFI_REG_SSID_LEN       0x014
#define WIFI_REG_SSID_BASE      0x018   /* 32 bytes, 8 regs  */
#define WIFI_REG_PASS_LEN       0x038
#define WIFI_REG_PASS_BASE      0x03c   /* 64 bytes, 16 regs */
#define WIFI_REG_MAC0           0x080
#define WIFI_REG_MAC1           0x084
#define WIFI_REG_IP_ADDR        0x088
#define WIFI_REG_IP_MASK        0x08c
#define WIFI_REG_IP_GW          0x090
#define WIFI_REG_SCAN_COUNT     0x094
#define WIFI_REG_SCAN_IDX       0x098
#define WIFI_REG_SCAN_RSSI      0x09c
#define WIFI_REG_SCAN_SSID_LEN  0x0a0
#define WIFI_REG_SCAN_SSID_BASE 0x0a4   /* 32 bytes, 8 regs  */
#define WIFI_REG_SCAN_BSSID0    0x0c4
#define WIFI_REG_SCAN_BSSID1    0x0c8
#define WIFI_REG_CTRL_SOCK_LEN  0x0d0
#define WIFI_REG_CTRL_SOCK_BASE 0x0d4   /* 64 bytes, 16 regs */

/* --- Packet data-plane registers (NEXT-003: TCP/IP DMA forwarding) --------- */
/* DMA design: firmware allocates DRAM buffers and registers their physical   */
/* addresses here.  QEMU calls cpu_physical_memory_read/write to access them. */
/* This avoids any MMIO address conflict with the RNG device at +0x144.       */
#define WIFI_REG_TX_ADDR        0x114   /* u32: guest-physical addr of TX buf */
#define WIFI_REG_TX_LEN         0x118   /* u32: write frame len to trigger TX; 0=idle */
#define WIFI_REG_RX_ADDR        0x11c   /* u32: guest-physical addr of RX buf */
#define WIFI_REG_RX_LEN         0x120   /* u32: non-zero = frame ready; write 0 to consume */
/* Range 0x000–0x123 ✓  RNG lives at +0x144, safely out of our MMIO region */

/* ---------- Command codes (write to WIFI_REG_CMD) ------------------------- */
#define WIFI_CMD_INIT           0x01
#define WIFI_CMD_DEINIT         0x02
#define WIFI_CMD_SET_MODE_STA   0x03
#define WIFI_CMD_START          0x04
#define WIFI_CMD_STOP           0x05
#define WIFI_CMD_CONNECT        0x06
#define WIFI_CMD_DISCONNECT     0x07
#define WIFI_CMD_SCAN           0x08
#define WIFI_CMD_GET_MAC        0x09

/* ---------- Event codes (WIFI_REG_EVENT) ---------------------------------- */
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
#define WIFI_EVT_RX_READY       0x0a    /* RX packet available in RX_BUF     */

/* ---------- State codes (WIFI_REG_STATUS) --------------------------------- */
#define WIFI_STATE_UNINIT       0x00
#define WIFI_STATE_IDLE         0x01
#define WIFI_STATE_STARTED      0x02
#define WIFI_STATE_CONNECTING   0x03
#define WIFI_STATE_CONNECTED    0x04
#define WIFI_STATE_ERROR        0x10

/* ---------- Device state -------------------------------------------------- */

/* Max scan results cached in device */
#define ESP_WIFI_MAX_SCAN_RESULTS   16

typedef struct ESPWifiScanResult {
    uint8_t  bssid[6];
    uint8_t  ssid[32];
    uint8_t  ssid_len;
    int8_t   rssi;
} ESPWifiScanResult;

typedef struct ESPWifiState {
    SysBusDevice parent_obj;

    MemoryRegion iomem;
    qemu_irq     irq;           /**< IRQ line 0 → ETS_WIFI_MAC_INTR_SOURCE */

    /* --- Registers visible to firmware --- */
    uint32_t status;            /**< WIFI_STATE_* */
    uint32_t event;             /**< WIFI_EVT_* pending (0 = none) */
    uint32_t irq_enable;        /**< Event bitmask that asserts IRQ */
    uint8_t  ssid[32];
    uint8_t  ssid_len;
    uint8_t  pass[64];
    uint8_t  pass_len;
    uint8_t  mac[6];
    uint32_t ip_addr;
    uint32_t ip_mask;
    uint32_t ip_gw;
    char     ctrl_sock_path[64];
    uint8_t  ctrl_sock_path_len;

    /* --- Scan results --- */
    uint32_t            scan_count;
    uint32_t            scan_idx;
    ESPWifiScanResult   scan_results[ESP_WIFI_MAX_SCAN_RESULTS];

    /* --- wpa_supplicant async I/O --- */
    int         ctrl_fd;            /**< Unix DGRAM ctrl socket, -1 = closed */
    char        ctrl_local[64];     /**< bound client path /tmp/qemu_wifi_PID_FD */
    GIOChannel *ctrl_chan;          /**< GLib I/O channel wrapping ctrl_fd */
    guint       ctrl_watch;         /**< g_io_add_watch source tag */
    int         net_id;             /**< ADD_NETWORK id returned by wpa_supplicant */
    int         conn_state;         /**< WpaConnState (see below) */

    /* --- Packet relay socket (NEXT-003: TCP/IP data plane) --- */
    int         pkt_fd;             /**< Unix STREAM relay socket, -1 = closed */
    GIOChannel *pkt_chan;           /**< GLib I/O channel wrapping pkt_fd */
    guint       pkt_watch;          /**< g_io_add_watch source tag */

    /* --- DMA packet registers (firmware writes guest-physical addrs here) --- */
    uint32_t    tx_addr;            /**< guest-physical addr of firmware TX buf */
    uint32_t    tx_len;             /**< 0 = idle; non-zero triggers TX via DMA */
    uint32_t    rx_addr;            /**< guest-physical addr of firmware RX buf */
    uint32_t    rx_len;             /**< 0 = consumed; non-zero = frame ready   */

    /* --- Host-side relay receive accumulation buffer --- */
    uint8_t     pkt_rx_hdr[4];      /**< length prefix accumulator (4 bytes) */
    int         pkt_rx_hdr_pos;     /**< bytes received into pkt_rx_hdr      */
    uint8_t     pkt_rx_data[WIFI_PKT_BUF_SIZE]; /**< partial frame data      */
    int         pkt_rx_data_pos;    /**< bytes received into pkt_rx_data      */
    int         pkt_rx_expected;    /**< total frame bytes expected           */
} ESPWifiState;

/* ---------- wpa_supplicant connection-sequencing state -------------------- */
typedef enum {
    WPA_CONN_NONE = 0,
    WPA_CONN_ATTACH_SENT,
    WPA_CONN_IDLE,              /**< attached, ready */
    WPA_CONN_SCAN_SENT,
    WPA_CONN_SCAN_RESULTS_SENT,
    WPA_CONN_ADD_NET_SENT,
    WPA_CONN_SET_SSID_SENT,
    WPA_CONN_SET_PSK_SENT,
    WPA_CONN_SELECT_SENT,
    WPA_CONN_GETTING_STATUS,
    WPA_CONN_CONNECTED,
} WpaConnState;
