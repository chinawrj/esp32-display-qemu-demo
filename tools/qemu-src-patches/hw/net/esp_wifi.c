/*
 * ESP32 Virtual Wi-Fi device — QEMU hardware model
 *
 * Skeleton (Day 9): MMIO register map, state machine, command dispatch.
 * wpa_supplicant async I/O deferred to Day 10.
 *
 * Protocol spec: docs/qemu-wifi.md
 *
 * Copyright (c) 2026 esp32-display-qemu-demo contributors.
 * SPDX-License-Identifier: GPL-2.0-or-later
 */

#include "qemu/osdep.h"
#include "qemu/module.h"
#include "qemu/log.h"
#include "qemu/error-report.h"
#include "qapi/error.h"
#include "hw/sysbus.h"
#include "hw/irq.h"
#include "hw/qdev-properties.h"
#include "hw/net/esp_wifi.h"

/* ---------- Logging ------------------------------------------------------- */
#define WIFI_WARN  1
#define WIFI_DEBUG 0

/* ---------- Helpers ------------------------------------------------------- */

/** Assert or deassert the IRQ line depending on pending event + enable mask. */
static void esp_wifi_update_irq(ESPWifiState *s)
{
    bool assert = (s->event != WIFI_EVT_NONE) &&
                  (s->irq_enable & (1u << s->event));
    qemu_set_irq(s->irq, assert ? 1 : 0);
}

/** Post an event to the firmware and optionally raise IRQ. */
static void esp_wifi_post_event(ESPWifiState *s, uint32_t evt)
{
    s->event = evt;
    esp_wifi_update_irq(s);
#if WIFI_DEBUG
    info_report("[ESP WIFI] event 0x%02x posted", evt);
#endif
}

/* ---------- Command dispatch ---------------------------------------------- */

static void esp_wifi_handle_cmd(ESPWifiState *s, uint32_t cmd)
{
    switch (cmd) {
    case WIFI_CMD_INIT:
        /*
         * Day 9: skeleton — no ctrl socket yet.
         * Transition directly to IDLE and post INIT_DONE.
         * Day 10 will open the wpa_supplicant ctrl socket here.
         */
        s->status = WIFI_STATE_IDLE;
        esp_wifi_post_event(s, WIFI_EVT_INIT_DONE);
        break;

    case WIFI_CMD_DEINIT:
        s->status = WIFI_STATE_UNINIT;
        s->event  = WIFI_EVT_NONE;
        esp_wifi_update_irq(s);
        break;

    case WIFI_CMD_SET_MODE_STA:
        /* STA is the only supported mode; nothing to change */
        break;

    case WIFI_CMD_START:
        if (s->status == WIFI_STATE_IDLE) {
            s->status = WIFI_STATE_STARTED;
            esp_wifi_post_event(s, WIFI_EVT_START_DONE);
        } else {
#if WIFI_WARN
            warn_report("[ESP WIFI] CMD_START in invalid state %u", s->status);
#endif
        }
        break;

    case WIFI_CMD_STOP:
        if (s->status == WIFI_STATE_STARTED ||
            s->status == WIFI_STATE_CONNECTING ||
            s->status == WIFI_STATE_CONNECTED) {
            s->status = WIFI_STATE_IDLE;
            esp_wifi_post_event(s, WIFI_EVT_STOP_DONE);
        }
        break;

    case WIFI_CMD_CONNECT:
        if (s->status == WIFI_STATE_STARTED) {
            s->status = WIFI_STATE_CONNECTING;
            /*
             * Day 10: send wpa_supplicant SCAN + ADD_NETWORK + SELECT_NETWORK.
             * For now, stay in CONNECTING state (firmware will poll STATUS).
             */
#if WIFI_DEBUG
            info_report("[ESP WIFI] CMD_CONNECT SSID=%.*s", s->ssid_len, s->ssid);
#endif
        } else {
#if WIFI_WARN
            warn_report("[ESP WIFI] CMD_CONNECT in invalid state %u", s->status);
#endif
        }
        break;

    case WIFI_CMD_DISCONNECT:
        if (s->status == WIFI_STATE_CONNECTING ||
            s->status == WIFI_STATE_CONNECTED) {
            s->status = WIFI_STATE_STARTED;
            esp_wifi_post_event(s, WIFI_EVT_DISCONNECTED);
        }
        break;

    case WIFI_CMD_SCAN:
        /*
         * Day 10: trigger SCAN via wpa_supplicant.
         * Skeleton: return empty scan results immediately.
         */
        s->scan_count = 0;
        esp_wifi_post_event(s, WIFI_EVT_SCAN_DONE);
        break;

    case WIFI_CMD_GET_MAC:
        /* Day 10: read host NIC MAC via netlink / getifaddrs. Stub: all-zero. */
        memset(s->mac, 0, sizeof(s->mac));
        break;

    default:
#if WIFI_WARN
        warn_report("[ESP WIFI] unknown CMD 0x%02x", cmd);
#endif
        break;
    }
}

/* ---------- MMIO read ----------------------------------------------------- */

static uint64_t esp_wifi_read(void *opaque, hwaddr addr, unsigned int size)
{
    ESPWifiState *s = ESP_WIFI(opaque);
    uint32_t r = 0;

    if (size != sizeof(uint32_t)) {
        return 0;
    }

    /* SSID registers: 8 × 32-bit words at SSID_BASE */
    if (addr >= WIFI_REG_SSID_BASE && addr < WIFI_REG_SSID_BASE + 32) {
        uint32_t idx = (addr - WIFI_REG_SSID_BASE) / 4;
        memcpy(&r, s->ssid + idx * 4, 4);
        return r;
    }

    /* Passphrase registers: 16 × 32-bit words */
    if (addr >= WIFI_REG_PASS_BASE && addr < WIFI_REG_PASS_BASE + 64) {
        uint32_t idx = (addr - WIFI_REG_PASS_BASE) / 4;
        memcpy(&r, s->pass + idx * 4, 4);
        return r;
    }

    /* Scan SSID registers */
    if (addr >= WIFI_REG_SCAN_SSID_BASE && addr < WIFI_REG_SCAN_SSID_BASE + 32) {
        if (s->scan_idx < s->scan_count) {
            uint32_t idx = (addr - WIFI_REG_SCAN_SSID_BASE) / 4;
            memcpy(&r, s->scan_results[s->scan_idx].ssid + idx * 4, 4);
        }
        return r;
    }

    /* Ctrl socket path registers */
    if (addr >= WIFI_REG_CTRL_SOCK_BASE && addr < WIFI_REG_CTRL_SOCK_BASE + 64) {
        uint32_t idx = (addr - WIFI_REG_CTRL_SOCK_BASE) / 4;
        memcpy(&r, s->ctrl_sock_path + idx * 4, 4);
        return r;
    }

    switch (addr) {
    case WIFI_REG_VER:
        r = ((uint32_t)ESP_WIFI_VERSION_MAJOR << 16) | ESP_WIFI_VERSION_MINOR;
        break;
    case WIFI_REG_CMD:
        r = 0; /* never busy in skeleton */
        break;
    case WIFI_REG_STATUS:
        r = s->status;
        break;
    case WIFI_REG_EVENT:
        r = s->event;
        break;
    case WIFI_REG_IRQ_ENABLE:
        r = s->irq_enable;
        break;
    case WIFI_REG_SSID_LEN:
        r = s->ssid_len;
        break;
    case WIFI_REG_PASS_LEN:
        r = s->pass_len;
        break;
    case WIFI_REG_MAC0:
        memcpy(&r, s->mac, 4);
        break;
    case WIFI_REG_MAC1:
        r = ((uint32_t)s->mac[4] << 24) | ((uint32_t)s->mac[5] << 16);
        break;
    case WIFI_REG_IP_ADDR:
        r = s->ip_addr;
        break;
    case WIFI_REG_IP_MASK:
        r = s->ip_mask;
        break;
    case WIFI_REG_IP_GW:
        r = s->ip_gw;
        break;
    case WIFI_REG_SCAN_COUNT:
        r = s->scan_count;
        break;
    case WIFI_REG_SCAN_IDX:
        r = s->scan_idx;
        break;
    case WIFI_REG_SCAN_RSSI:
        if (s->scan_idx < s->scan_count) {
            r = (uint8_t)s->scan_results[s->scan_idx].rssi;
        }
        break;
    case WIFI_REG_SCAN_SSID_LEN:
        if (s->scan_idx < s->scan_count) {
            r = s->scan_results[s->scan_idx].ssid_len;
        }
        break;
    case WIFI_REG_SCAN_BSSID0:
        if (s->scan_idx < s->scan_count) {
            memcpy(&r, s->scan_results[s->scan_idx].bssid, 4);
        }
        break;
    case WIFI_REG_SCAN_BSSID1:
        if (s->scan_idx < s->scan_count) {
            r = ((uint32_t)s->scan_results[s->scan_idx].bssid[4] << 24) |
                ((uint32_t)s->scan_results[s->scan_idx].bssid[5] << 16);
        }
        break;
    case WIFI_REG_CTRL_SOCK_LEN:
        r = s->ctrl_sock_path_len;
        break;
    default:
#if WIFI_WARN
        warn_report("[ESP WIFI] unhandled read 0x%" HWADDR_PRIx, addr);
#endif
        break;
    }

#if WIFI_DEBUG
    info_report("[ESP WIFI] read  0x%" HWADDR_PRIx " → 0x%08x", addr, r);
#endif
    return r;
}

/* ---------- MMIO write ---------------------------------------------------- */

static void esp_wifi_write(void *opaque, hwaddr addr,
                           uint64_t value, unsigned int size)
{
    ESPWifiState *s = ESP_WIFI(opaque);
    uint32_t v = (uint32_t)value;

    if (size != sizeof(uint32_t)) {
        return;
    }

#if WIFI_DEBUG
    info_report("[ESP WIFI] write 0x%" HWADDR_PRIx " ← 0x%08x", addr, v);
#endif

    /* SSID registers */
    if (addr >= WIFI_REG_SSID_BASE && addr < WIFI_REG_SSID_BASE + 32) {
        uint32_t idx = (addr - WIFI_REG_SSID_BASE) / 4;
        memcpy(s->ssid + idx * 4, &v, 4);
        return;
    }

    /* Passphrase registers */
    if (addr >= WIFI_REG_PASS_BASE && addr < WIFI_REG_PASS_BASE + 64) {
        uint32_t idx = (addr - WIFI_REG_PASS_BASE) / 4;
        memcpy(s->pass + idx * 4, &v, 4);
        return;
    }

    /* Ctrl socket path registers */
    if (addr >= WIFI_REG_CTRL_SOCK_BASE && addr < WIFI_REG_CTRL_SOCK_BASE + 64) {
        uint32_t idx = (addr - WIFI_REG_CTRL_SOCK_BASE) / 4;
        memcpy(s->ctrl_sock_path + idx * 4, &v, 4);
        return;
    }

    switch (addr) {
    case WIFI_REG_CMD:
        if (v != 0) {
            esp_wifi_handle_cmd(s, v);
        }
        break;

    case WIFI_REG_EVENT:
        /* Writing 0 acknowledges (clears) the pending event */
        if (v == 0) {
            s->event = WIFI_EVT_NONE;
            esp_wifi_update_irq(s);
        }
        break;

    case WIFI_REG_IRQ_ENABLE:
        s->irq_enable = v;
        esp_wifi_update_irq(s);
        break;

    case WIFI_REG_SSID_LEN:
        s->ssid_len = (uint8_t)(v & 0x3f);
        break;

    case WIFI_REG_PASS_LEN:
        s->pass_len = (uint8_t)(v & 0x7f);
        break;

    case WIFI_REG_SCAN_IDX:
        s->scan_idx = (v < s->scan_count) ? v : s->scan_count;
        break;

    case WIFI_REG_CTRL_SOCK_LEN:
        s->ctrl_sock_path_len = (uint8_t)(v & 0x7f);
        break;

    default:
#if WIFI_WARN
        warn_report("[ESP WIFI] unhandled write 0x%" HWADDR_PRIx " = 0x%08x",
                    addr, v);
#endif
        break;
    }
}

/* ---------- MemoryRegionOps ------------------------------------------------ */

static const MemoryRegionOps esp_wifi_ops = {
    .read       = esp_wifi_read,
    .write      = esp_wifi_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = {
        .min_access_size = 4,
        .max_access_size = 4,
    },
};

/* ---------- Device lifecycle ---------------------------------------------- */

static void esp_wifi_reset(DeviceState *dev)
{
    ESPWifiState *s = ESP_WIFI(dev);

    s->status           = WIFI_STATE_UNINIT;
    s->event            = WIFI_EVT_NONE;
    s->irq_enable       = 0;
    s->ssid_len         = 0;
    s->pass_len         = 0;
    s->scan_count       = 0;
    s->scan_idx         = 0;
    s->ip_addr          = 0;
    s->ip_mask          = 0;
    s->ip_gw            = 0;
    s->ctrl_sock_path_len = 0;

    memset(s->ssid,           0, sizeof(s->ssid));
    memset(s->pass,           0, sizeof(s->pass));
    memset(s->mac,            0, sizeof(s->mac));
    memset(s->ctrl_sock_path, 0, sizeof(s->ctrl_sock_path));
    memset(s->scan_results,   0, sizeof(s->scan_results));

    qemu_irq_lower(s->irq);
}

static void esp_wifi_realize(DeviceState *dev, Error **errp)
{
    ESPWifiState *s = ESP_WIFI(dev);
    SysBusDevice *sbd = SYS_BUS_DEVICE(dev);

    memory_region_init_io(&s->iomem, OBJECT(dev), &esp_wifi_ops, s,
                          TYPE_ESP_WIFI, ESP_WIFI_IO_SIZE);
    sysbus_init_mmio(sbd, &s->iomem);
    sysbus_init_irq(sbd, &s->irq);
}

/* ---------- Class / type registration ------------------------------------- */

static void esp_wifi_class_init(ObjectClass *klass, void *data)
{
    DeviceClass *dc = DEVICE_CLASS(klass);
    dc->realize       = esp_wifi_realize;
    dc->legacy_reset  = esp_wifi_reset;
    dc->desc          = "ESP32 Virtual Wi-Fi STA device";
}

static const TypeInfo esp_wifi_info = {
    .name          = TYPE_ESP_WIFI,
    .parent        = TYPE_SYS_BUS_DEVICE,
    .instance_size = sizeof(ESPWifiState),
    .class_init    = esp_wifi_class_init,
};

static void esp_wifi_register_types(void)
{
    type_register_static(&esp_wifi_info);
}

type_init(esp_wifi_register_types)
