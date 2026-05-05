/*
 * ESP32 Virtual Wi-Fi device — QEMU hardware model
 *
 * Day 10: wpa_supplicant ctrl socket async I/O via GLib GIOChannel.
 * Full CMD_CONNECT flow: ATTACH → SCAN → ADD_NETWORK → SET_NETWORK ×2
 * → SELECT_NETWORK → CTRL-EVENT-CONNECTED → STATUS → EVT_GOT_IP.
 *
 * Protocol spec: docs/qemu-wifi.md
 *
 * Copyright (c) 2026 esp32-display-qemu-demo contributors.
 * SPDX-License-Identifier: GPL-2.0-or-later
 *
 * Marker: ESP_WIFI_PATCH
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
#include "exec/memory.h"    /* cpu_physical_memory_read / cpu_physical_memory_write */
#include "exec/address-spaces.h"

#include <sys/socket.h>
#include <sys/un.h>
#include <arpa/inet.h>
#include <fcntl.h>

/* ---------- Logging ------------------------------------------------------- */
#define WIFI_WARN  1
#define WIFI_DEBUG 0

/* ---------- wpa_supplicant ctrl socket defaults --------------------------- */
#define WPA_CTRL_DEFAULT_PATH   "/var/run/wpa_supplicant/wlo1"
#define WPA_LOCAL_PATH_FMT      "/tmp/qemu_wifi_%d_%d"
#define WPA_BUF_SIZE            4096

/* ---------- IRQ / event helpers ------------------------------------------- */

static void esp_wifi_update_irq(ESPWifiState *s)
{
    bool assert = (s->event != WIFI_EVT_NONE) &&
                  (s->irq_enable & (1u << s->event));
    qemu_set_irq(s->irq, assert ? 1 : 0);
}

static void esp_wifi_post_event(ESPWifiState *s, uint32_t evt)
{
    s->event = evt;
    esp_wifi_update_irq(s);
#if WIFI_DEBUG
    info_report("[ESP WIFI] event 0x%02x posted (state=%u)", evt, s->status);
#endif
}

/* ---------- wpa_supplicant ctrl socket ------------------------------------ */

static int wpa_ctrl_send(ESPWifiState *s, const char *cmd)
{
    if (s->ctrl_fd < 0) {
        return -1;
    }
    ssize_t n = send(s->ctrl_fd, cmd, strlen(cmd), 0);
    if (n < 0) {
#if WIFI_WARN
        warn_report("[ESP WIFI] wpa_ctrl_send '%s': %s", cmd, strerror(errno));
#endif
        return -1;
    }
#if WIFI_DEBUG
    info_report("[ESP WIFI] -> wpa '%s'", cmd);
#endif
    return 0;
}

static void wpa_parse_status(ESPWifiState *s, const char *buf)
{
    const char *p;

    p = strstr(buf, "ip_address=");
    if (p) {
        char ip_str[32] = {0};
        sscanf(p + 11, "%31[^\n]", ip_str);
        struct in_addr addr;
        if (inet_pton(AF_INET, ip_str, &addr) == 1) {
            s->ip_addr = addr.s_addr;
        }
    }

    p = strstr(buf, "\naddress=");
    if (p) {
        unsigned int m[6] = {0};
        if (sscanf(p + 9, "%02x:%02x:%02x:%02x:%02x:%02x",
                   &m[0], &m[1], &m[2], &m[3], &m[4], &m[5]) == 6) {
            for (int i = 0; i < 6; i++) {
                s->mac[i] = (uint8_t)m[i];
            }
        }
    }

    /* Parse gateway from STATUS if provided (mock_wpa_supplicant >= Day 21) */
    p = strstr(buf, "\ngateway=");
    if (p) {
        char gw_str[32] = {0};
        sscanf(p + 9, "%31[^\n]", gw_str);
        struct in_addr addr;
        if (inet_pton(AF_INET, gw_str, &addr) == 1) {
            s->ip_gw = addr.s_addr;
        }
    }

    /* Parse subnet mask from STATUS if provided */
    p = strstr(buf, "\nsubnet_mask=");
    if (p) {
        char mask_str[32] = {0};
        sscanf(p + 13, "%31[^\n]", mask_str);
        struct in_addr addr;
        if (inet_pton(AF_INET, mask_str, &addr) == 1) {
            s->ip_mask = addr.s_addr;
        }
    }

    /* Fallback: derive /24 mask and .1 gateway only if not provided by STATUS.
     * This preserves backward compatibility with older mock implementations.
     * New mock assigns 10.0.2.15/24 gw=10.0.2.2 explicitly. */
    if (s->ip_addr && !s->ip_mask) {
        s->ip_mask = htonl(0xffffff00u);
    }
    if (s->ip_addr && !s->ip_gw) {
        uint32_t a = ntohl(s->ip_addr);
        s->ip_gw = htonl((a & 0xffffff00u) | 1u);
    }
}

/**
 * g_timeout_add callback: post WIFI_EVT_GOT_IP after CONNECTED has been ACKed.
 * Returns FALSE so the timer fires only once.
 */
static gboolean esp_wifi_post_got_ip_cb(gpointer data)
{
    ESPWifiState *s = ESP_WIFI(data);
    if (s->ip_addr) {
        esp_wifi_post_event(s, WIFI_EVT_GOT_IP);
    }
    return FALSE;
}

static void wpa_handle_msg(ESPWifiState *s, const char *buf, ssize_t len)
{
    (void)len;
#if WIFI_DEBUG
    info_report("[ESP WIFI] <- wpa [conn=%d] '%.*s'",
                s->conn_state, (int)MIN(len, 120), buf);
#endif

    const char *ev = buf;
    if (*ev == '<') {
        ev = strchr(ev, '>');
        ev = ev ? ev + 1 : buf;
    }

    if (strncmp(ev, "CTRL-EVENT-SCAN-RESULTS", 23) == 0) {
        if (s->conn_state == WPA_CONN_SCAN_SENT) {
            s->conn_state = WPA_CONN_SCAN_RESULTS_SENT;
            wpa_ctrl_send(s, "SCAN_RESULTS");
        }
        return;
    }

    if (strncmp(ev, "CTRL-EVENT-CONNECTED", 20) == 0) {
        s->conn_state = WPA_CONN_GETTING_STATUS;
        s->status     = WIFI_STATE_CONNECTED;
        wpa_ctrl_send(s, "STATUS");
        return;
    }

    if (strncmp(ev, "CTRL-EVENT-DISCONNECTED", 23) == 0) {
        s->conn_state = WPA_CONN_IDLE;
        s->status     = WIFI_STATE_STARTED;
        esp_wifi_post_event(s, WIFI_EVT_DISCONNECTED);
        return;
    }

    switch (s->conn_state) {

    case WPA_CONN_ATTACH_SENT:
        if (strncmp(buf, "OK", 2) == 0) {
            s->conn_state = WPA_CONN_IDLE;
            s->status     = WIFI_STATE_IDLE;
            esp_wifi_post_event(s, WIFI_EVT_INIT_DONE);
        } else {
            s->conn_state = WPA_CONN_NONE;
            s->status     = WIFI_STATE_ERROR;
            esp_wifi_post_event(s, WIFI_EVT_INIT_FAIL);
        }
        break;

    case WPA_CONN_SCAN_RESULTS_SENT:
        {
            uint32_t count = 0;
            const char *line = buf;
            line = strchr(line, '\n');
            if (line) { line++; }
            while (line && *line && count < ESP_WIFI_MAX_SCAN_RESULTS) {
                ESPWifiScanResult *r = &s->scan_results[count];
                unsigned int b[6] = {0};
                int freq = 0, rssi = 0;
                char flags[64] = {0};
                char ssid[33]  = {0};
                int n = sscanf(line,
                    "%02x:%02x:%02x:%02x:%02x:%02x\t%d\t%d\t%63s\t%32[^\n]",
                    &b[0], &b[1], &b[2], &b[3], &b[4], &b[5],
                    &freq, &rssi, flags, ssid);
                if (n >= 9) {
                    for (int i = 0; i < 6; i++) { r->bssid[i] = (uint8_t)b[i]; }
                    r->rssi     = (int8_t)rssi;
                    r->ssid_len = (uint8_t)MIN(strlen(ssid), 32);
                    memcpy(r->ssid, ssid, r->ssid_len);
                    count++;
                }
                line = strchr(line, '\n');
                if (line) { line++; }
            }
            s->scan_count = count;
            s->conn_state = WPA_CONN_ADD_NET_SENT;
            wpa_ctrl_send(s, "ADD_NETWORK");
        }
        break;

    case WPA_CONN_ADD_NET_SENT:
        {
            int id = atoi(buf);
            if (id >= 0) {
                s->net_id     = id;
                s->conn_state = WPA_CONN_SET_SSID_SENT;
                char cmd[96];
                char ssid_str[33] = {0};
                memcpy(ssid_str, s->ssid, s->ssid_len);
                snprintf(cmd, sizeof(cmd), "SET_NETWORK %d ssid \"%s\"",
                         s->net_id, ssid_str);
                wpa_ctrl_send(s, cmd);
            } else {
                s->status = WIFI_STATE_ERROR;
                esp_wifi_post_event(s, WIFI_EVT_ERROR);
            }
        }
        break;

    case WPA_CONN_SET_SSID_SENT:
        if (strncmp(buf, "OK", 2) == 0) {
            s->conn_state = WPA_CONN_SET_PSK_SENT;
            char cmd[128];
            if (s->pass_len > 0) {
                char psk_str[65] = {0};
                memcpy(psk_str, s->pass, s->pass_len);
                snprintf(cmd, sizeof(cmd), "SET_NETWORK %d psk \"%s\"",
                         s->net_id, psk_str);
            } else {
                snprintf(cmd, sizeof(cmd),
                         "SET_NETWORK %d key_mgmt NONE", s->net_id);
            }
            wpa_ctrl_send(s, cmd);
        } else {
            s->status = WIFI_STATE_ERROR;
            esp_wifi_post_event(s, WIFI_EVT_ERROR);
        }
        break;

    case WPA_CONN_SET_PSK_SENT:
        if (strncmp(buf, "OK", 2) == 0) {
            s->conn_state = WPA_CONN_SELECT_SENT;
            s->status     = WIFI_STATE_CONNECTING;
            char cmd[32];
            snprintf(cmd, sizeof(cmd), "SELECT_NETWORK %d", s->net_id);
            wpa_ctrl_send(s, cmd);
        } else {
            s->status = WIFI_STATE_ERROR;
            esp_wifi_post_event(s, WIFI_EVT_ERROR);
        }
        break;

    case WPA_CONN_SELECT_SENT:
        /* "OK" — wait for CTRL-EVENT-CONNECTED */
        break;

    case WPA_CONN_GETTING_STATUS:
        wpa_parse_status(s, buf);
        esp_wifi_post_event(s, WIFI_EVT_CONNECTED);
        if (s->ip_addr) {
            /*
             * Delay GOT_IP by 300 ms so the firmware has time to ACK
             * WIFI_EVT_CONNECTED before we overwrite the event register.
             */
            g_timeout_add(300, esp_wifi_post_got_ip_cb, s);
        }
        s->conn_state = WPA_CONN_CONNECTED;
        break;

    default:
        break;
    }
}

static gboolean esp_wifi_ctrl_read_cb(GIOChannel *chan,
                                      GIOCondition cond,
                                      gpointer data)
{
    ESPWifiState *s = ESP_WIFI(data);

    if (cond == G_IO_HUP || cond == G_IO_ERR) {
#if WIFI_WARN
        warn_report("[ESP WIFI] ctrl socket HUP/ERR");
#endif
        return FALSE;
    }

    char buf[WPA_BUF_SIZE];
    ssize_t n = recv(g_io_channel_unix_get_fd(chan), buf, sizeof(buf) - 1, 0);
    if (n <= 0) {
        return TRUE;
    }
    buf[n] = '\0';
    wpa_handle_msg(s, buf, n);
    return TRUE;
}

static void wpa_ctrl_open(ESPWifiState *s)
{
    char ctrl_path[108] = {0};
    if (s->ctrl_sock_path_len > 0 && s->ctrl_sock_path[0] != '\0') {
        snprintf(ctrl_path, sizeof(ctrl_path), "%.*s",
                 (int)MIN((size_t)s->ctrl_sock_path_len, sizeof(ctrl_path) - 1),
                 s->ctrl_sock_path);
    } else {
        const char *env = getenv("ESP_WIFI_CTRL_SOCKET");
        snprintf(ctrl_path, sizeof(ctrl_path), "%s",
                 (env && env[0]) ? env : WPA_CTRL_DEFAULT_PATH);
    }

    int fd = socket(AF_UNIX, SOCK_DGRAM, 0);
    if (fd < 0) {
        warn_report("[ESP WIFI] socket(): %s", strerror(errno));
        esp_wifi_post_event(s, WIFI_EVT_INIT_FAIL);
        return;
    }

    char local_path[64];
    snprintf(local_path, sizeof(local_path), WPA_LOCAL_PATH_FMT,
             (int)getpid(), fd);

    struct sockaddr_un local = { .sun_family = AF_UNIX };
    snprintf(local.sun_path, sizeof(local.sun_path), "%s", local_path);
    unlink(local_path);
    if (bind(fd, (struct sockaddr *)&local, sizeof(local)) < 0) {
        warn_report("[ESP WIFI] bind(%s): %s", local_path, strerror(errno));
        close(fd);
        esp_wifi_post_event(s, WIFI_EVT_INIT_FAIL);
        return;
    }

    struct sockaddr_un remote = { .sun_family = AF_UNIX };
    snprintf(remote.sun_path, sizeof(remote.sun_path), "%s", ctrl_path);
    if (connect(fd, (struct sockaddr *)&remote, sizeof(remote)) < 0) {
        warn_report("[ESP WIFI] connect(%s): %s", ctrl_path, strerror(errno));
        close(fd);
        unlink(local_path);
        esp_wifi_post_event(s, WIFI_EVT_INIT_FAIL);
        return;
    }

    fcntl(fd, F_SETFL, O_NONBLOCK);
    snprintf(s->ctrl_local, sizeof(s->ctrl_local), "%s", local_path);
    s->ctrl_fd = fd;

    s->ctrl_chan = g_io_channel_unix_new(fd);
    g_io_channel_set_encoding(s->ctrl_chan, NULL, NULL);
    g_io_channel_set_buffered(s->ctrl_chan, FALSE);
    s->ctrl_watch = g_io_add_watch(s->ctrl_chan,
                                   G_IO_IN | G_IO_HUP | G_IO_ERR,
                                   esp_wifi_ctrl_read_cb, s);

    s->conn_state = WPA_CONN_ATTACH_SENT;
    if (wpa_ctrl_send(s, "ATTACH") < 0) {
        esp_wifi_post_event(s, WIFI_EVT_INIT_FAIL);
    }

    info_report("[ESP WIFI] ctrl socket opened: %s -> %s",
                local_path, ctrl_path);
}

static void wpa_ctrl_close(ESPWifiState *s)
{
    if (s->ctrl_fd < 0) {
        return;
    }
    wpa_ctrl_send(s, "DETACH");
    if (s->ctrl_watch) {
        g_source_remove(s->ctrl_watch);
        s->ctrl_watch = 0;
    }
    if (s->ctrl_chan) {
        g_io_channel_shutdown(s->ctrl_chan, FALSE, NULL);
        g_io_channel_unref(s->ctrl_chan);
        s->ctrl_chan = NULL;
    }
    close(s->ctrl_fd);
    s->ctrl_fd = -1;
    if (s->ctrl_local[0]) {
        unlink(s->ctrl_local);
        s->ctrl_local[0] = '\0';
    }
    s->conn_state = WPA_CONN_NONE;
}

/* ---------- Packet relay socket (NEXT-003: TCP/IP data plane) ------------- */

/*
 * Protocol: length-prefixed Ethernet frames over a Unix STREAM socket.
 * Each frame is preceded by a 4-byte big-endian length field.
 * Maximum frame size: WIFI_PKT_BUF_SIZE (1516 bytes).
 */

static gboolean esp_wifi_pkt_read_cb(GIOChannel *chan,
                                     GIOCondition cond,
                                     gpointer data);

static void pkt_relay_close(ESPWifiState *s)
{
    if (s->pkt_watch) {
        g_source_remove(s->pkt_watch);
        s->pkt_watch = 0;
    }
    if (s->pkt_chan) {
        g_io_channel_shutdown(s->pkt_chan, FALSE, NULL);
        g_io_channel_unref(s->pkt_chan);
        s->pkt_chan = NULL;
    }
    if (s->pkt_fd >= 0) {
        close(s->pkt_fd);
        s->pkt_fd = -1;
    }
    s->pkt_rx_hdr_pos    = 0;
    s->pkt_rx_data_pos   = 0;
    s->pkt_rx_expected   = 0;
}

static void pkt_relay_open(ESPWifiState *s)
{
    const char *path = getenv("ESP_WIFI_PKT_SOCKET");
    if (!path || !path[0]) {
        /* Packet relay not configured — data-plane silently disabled */
        return;
    }

    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) {
        warn_report("[ESP WIFI PKT] socket(): %s", strerror(errno));
        return;
    }

    struct sockaddr_un addr;
    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    snprintf(addr.sun_path, sizeof(addr.sun_path), "%s", path);

    if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        warn_report("[ESP WIFI PKT] connect(%s): %s", path, strerror(errno));
        close(fd);
        return;
    }

    int flags = fcntl(fd, F_GETFL, 0);
    fcntl(fd, F_SETFL, flags | O_NONBLOCK);

    s->pkt_fd   = fd;
    s->pkt_chan = g_io_channel_unix_new(fd);
    g_io_channel_set_encoding(s->pkt_chan, NULL, NULL);
    g_io_channel_set_buffered(s->pkt_chan, FALSE);

    s->pkt_watch = g_io_add_watch(
        s->pkt_chan,
        G_IO_IN | G_IO_HUP | G_IO_ERR,
        esp_wifi_pkt_read_cb,
        s);

    info_report("[ESP WIFI PKT] connected to relay socket %s", path);
}

/**
 * Send a TX Ethernet frame to the relay daemon (4-byte BE length prefix + data).
 */
static void pkt_relay_send(ESPWifiState *s, const uint8_t *buf, uint32_t len)
{
    if (s->pkt_fd < 0 || len == 0 || len > WIFI_PKT_BUF_SIZE) {
        return;
    }

    uint8_t hdr[4];
    hdr[0] = (len >> 24) & 0xff;
    hdr[1] = (len >> 16) & 0xff;
    hdr[2] = (len >>  8) & 0xff;
    hdr[3] = (len      ) & 0xff;

    /* Best-effort blocking write; relay daemon must drain fast enough */
    ssize_t r = send(s->pkt_fd, hdr, 4, MSG_NOSIGNAL | MSG_MORE);
    if (r != 4) {
#if WIFI_WARN
        warn_report("[ESP WIFI PKT] send header failed: %s", strerror(errno));
#endif
        pkt_relay_close(s);
        return;
    }
    r = send(s->pkt_fd, buf, len, MSG_NOSIGNAL);
    if (r != (ssize_t)len) {
#if WIFI_WARN
        warn_report("[ESP WIFI PKT] send data failed: %s", strerror(errno));
#endif
        pkt_relay_close(s);
    }
}

/**
 * GIO callback: incoming data from relay daemon → RX buffer → EVT_RX_READY.
 * Uses a state machine to handle partial reads.
 */
static gboolean esp_wifi_pkt_read_cb(GIOChannel *chan,
                                     GIOCondition cond,
                                     gpointer data)
{
    ESPWifiState *s = ESP_WIFI(data);

    if (cond & (G_IO_HUP | G_IO_ERR)) {
#if WIFI_WARN
        warn_report("[ESP WIFI PKT] relay socket HUP/ERR");
#endif
        pkt_relay_close(s);
        return FALSE;
    }

    int fd = g_io_channel_unix_get_fd(chan);

    while (1) {
        if (s->pkt_rx_hdr_pos < 4) {
            /* Still reading the 4-byte length prefix */
            ssize_t n = recv(fd,
                             s->pkt_rx_hdr + s->pkt_rx_hdr_pos,
                             4 - s->pkt_rx_hdr_pos,
                             0);
            if (n <= 0) {
                if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
                    break; /* no more data */
                }
                pkt_relay_close(s);
                return FALSE;
            }
            s->pkt_rx_hdr_pos += (int)n;
            if (s->pkt_rx_hdr_pos < 4) {
                break; /* header incomplete */
            }
            /* Decode length */
            s->pkt_rx_expected = ((int)s->pkt_rx_hdr[0] << 24) |
                                 ((int)s->pkt_rx_hdr[1] << 16) |
                                 ((int)s->pkt_rx_hdr[2] <<  8) |
                                  (int)s->pkt_rx_hdr[3];
            if (s->pkt_rx_expected <= 0 ||
                s->pkt_rx_expected > WIFI_PKT_BUF_SIZE) {
#if WIFI_WARN
                warn_report("[ESP WIFI PKT] bad frame len %d from relay",
                            s->pkt_rx_expected);
#endif
                pkt_relay_close(s);
                return FALSE;
            }
            s->pkt_rx_data_pos = 0;
        }

        /* Reading frame body */
        int remaining = s->pkt_rx_expected - s->pkt_rx_data_pos;
        ssize_t n = recv(fd,
                         s->pkt_rx_data + s->pkt_rx_data_pos,
                         remaining,
                         0);
        if (n <= 0) {
            if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
                break;
            }
            pkt_relay_close(s);
            return FALSE;
        }
        s->pkt_rx_data_pos += (int)n;

        if (s->pkt_rx_data_pos < s->pkt_rx_expected) {
            break; /* frame incomplete */
        }

        /* Full frame received — write directly to firmware's RX DMA buffer */
        if (s->rx_len == 0 && s->rx_addr != 0) {
            if (s->pkt_rx_expected <= WIFI_PKT_BUF_SIZE) {
                cpu_physical_memory_write(s->rx_addr,
                                         s->pkt_rx_data,
                                         s->pkt_rx_expected);
                s->rx_len = (uint32_t)s->pkt_rx_expected;
                esp_wifi_post_event(s, WIFI_EVT_RX_READY);
            }
        }
        /* else: drop frame (firmware hasn't consumed previous frame yet) */

        /* Reset for next frame */
        s->pkt_rx_hdr_pos  = 0;
        s->pkt_rx_data_pos = 0;
        s->pkt_rx_expected = 0;
    }

    return TRUE;
}

static void esp_wifi_handle_cmd(ESPWifiState *s, uint32_t cmd)
{
    switch (cmd) {
    case WIFI_CMD_INIT:
        wpa_ctrl_open(s);
        break;

    case WIFI_CMD_DEINIT:
        wpa_ctrl_close(s);
        s->status = WIFI_STATE_UNINIT;
        s->event  = WIFI_EVT_NONE;
        esp_wifi_update_irq(s);
        break;

    case WIFI_CMD_SET_MODE_STA:
        /* Synchronous no-op: just acknowledge */
        esp_wifi_post_event(s, WIFI_EVT_INIT_DONE);
        break;

    case WIFI_CMD_START:
        if (s->status == WIFI_STATE_IDLE) {
            s->status = WIFI_STATE_STARTED;
            /* BUG-005 fix: open packet relay early so ARP/DHCP replies
             * are not dropped in the window between START and CONNECT. */
            if (s->pkt_fd < 0) {
                pkt_relay_open(s);
            }
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
            s->conn_state = WPA_CONN_IDLE;
            esp_wifi_post_event(s, WIFI_EVT_STOP_DONE);
        }
        break;

    case WIFI_CMD_CONNECT:
        if (s->status == WIFI_STATE_STARTED) {
            s->conn_state = WPA_CONN_SCAN_SENT;
            wpa_ctrl_send(s, "SCAN");
            /* Relay should already be open from CMD_START; keep fallback. */
            if (s->pkt_fd < 0) {
                pkt_relay_open(s);
            }
        } else {
#if WIFI_WARN
            warn_report("[ESP WIFI] CMD_CONNECT in invalid state %u", s->status);
#endif
        }
        break;

    case WIFI_CMD_DISCONNECT:
        if (s->status == WIFI_STATE_CONNECTING ||
            s->status == WIFI_STATE_CONNECTED) {
            if (s->net_id >= 0) {
                char cmd_str[32];
                snprintf(cmd_str, sizeof(cmd_str),
                         "DISABLE_NETWORK %d", s->net_id);
                wpa_ctrl_send(s, cmd_str);
            }
            s->status     = WIFI_STATE_STARTED;
            s->conn_state = WPA_CONN_IDLE;
            esp_wifi_post_event(s, WIFI_EVT_DISCONNECTED);
        }
        break;

    case WIFI_CMD_SCAN:
        if (s->ctrl_fd >= 0) {
            s->conn_state = WPA_CONN_SCAN_SENT;
            wpa_ctrl_send(s, "SCAN");
        } else {
            s->scan_count = 0;
            esp_wifi_post_event(s, WIFI_EVT_SCAN_DONE);
        }
        break;

    case WIFI_CMD_GET_MAC:
        {
            const char *env = getenv("ESP_WIFI_CTRL_SOCKET");
            char iface[32] = "wlo1";
            if (env) {
                const char *slash = strrchr(env, '/');
                if (slash && strlen(slash + 1) < sizeof(iface)) {
                    strncpy(iface, slash + 1, sizeof(iface) - 1);
                }
            }
            char sysfs_path[64];
            snprintf(sysfs_path, sizeof(sysfs_path),
                     "/sys/class/net/%s/address", iface);
            FILE *f = fopen(sysfs_path, "r");
            if (f) {
                unsigned int m[6] = {0};
                if (fscanf(f, "%02x:%02x:%02x:%02x:%02x:%02x",
                           &m[0], &m[1], &m[2], &m[3], &m[4], &m[5]) == 6) {
                    for (int i = 0; i < 6; i++) {
                        s->mac[i] = (uint8_t)m[i];
                    }
                }
                fclose(f);
            }
        }
        esp_wifi_post_event(s, WIFI_EVT_INIT_DONE); /* ACK for wifi_qemu_send_cmd */
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

    if (addr >= WIFI_REG_SSID_BASE && addr < WIFI_REG_SSID_BASE + 32) {
        uint32_t idx = (addr - WIFI_REG_SSID_BASE) / 4;
        memcpy(&r, s->ssid + idx * 4, 4);
        return r;
    }
    if (addr >= WIFI_REG_PASS_BASE && addr < WIFI_REG_PASS_BASE + 64) {
        uint32_t idx = (addr - WIFI_REG_PASS_BASE) / 4;
        memcpy(&r, s->pass + idx * 4, 4);
        return r;
    }
    if (addr >= WIFI_REG_SCAN_SSID_BASE && addr < WIFI_REG_SCAN_SSID_BASE + 32) {
        if (s->scan_idx < s->scan_count) {
            uint32_t idx = (addr - WIFI_REG_SCAN_SSID_BASE) / 4;
            memcpy(&r, s->scan_results[s->scan_idx].ssid + idx * 4, 4);
        }
        return r;
    }
    if (addr >= WIFI_REG_CTRL_SOCK_BASE && addr < WIFI_REG_CTRL_SOCK_BASE + 64) {
        uint32_t idx = (addr - WIFI_REG_CTRL_SOCK_BASE) / 4;
        memcpy(&r, s->ctrl_sock_path + idx * 4, 4);
        return r;
    }

    /* --- Packet DMA registers (no large MMIO buffers) --- */

    switch (addr) {
    case WIFI_REG_VER:
        r = ((uint32_t)ESP_WIFI_VERSION_MAJOR << 16) | ESP_WIFI_VERSION_MINOR;
        break;
    case WIFI_REG_CMD:        r = 0;              break;
    case WIFI_REG_STATUS:     r = s->status;      break;
    case WIFI_REG_EVENT:      r = s->event;       break;
    case WIFI_REG_IRQ_ENABLE: r = s->irq_enable;  break;
    case WIFI_REG_SSID_LEN:   r = s->ssid_len;    break;
    case WIFI_REG_PASS_LEN:   r = s->pass_len;    break;
    case WIFI_REG_MAC0:       memcpy(&r, s->mac, 4); break;
    case WIFI_REG_MAC1:
        r = ((uint32_t)s->mac[4] << 24) | ((uint32_t)s->mac[5] << 16);
        break;
    case WIFI_REG_IP_ADDR:    r = s->ip_addr;     break;
    case WIFI_REG_IP_MASK:    r = s->ip_mask;     break;
    case WIFI_REG_IP_GW:      r = s->ip_gw;       break;
    case WIFI_REG_SCAN_COUNT: r = s->scan_count;  break;
    case WIFI_REG_SCAN_IDX:   r = s->scan_idx;    break;
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
    case WIFI_REG_CTRL_SOCK_LEN: r = s->ctrl_sock_path_len; break;
    case WIFI_REG_TX_ADDR: r = s->tx_addr; break;
    case WIFI_REG_TX_LEN:  r = s->tx_len;  break;
    case WIFI_REG_RX_ADDR: r = s->rx_addr; break;
    case WIFI_REG_RX_LEN:  r = s->rx_len;  break;
    default:
#if WIFI_WARN
        warn_report("[ESP WIFI] unhandled read 0x%" HWADDR_PRIx, addr);
#endif
        break;
    }
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

    if (addr >= WIFI_REG_SSID_BASE && addr < WIFI_REG_SSID_BASE + 32) {
        uint32_t idx = (addr - WIFI_REG_SSID_BASE) / 4;
        memcpy(s->ssid + idx * 4, &v, 4);
        return;
    }
    if (addr >= WIFI_REG_PASS_BASE && addr < WIFI_REG_PASS_BASE + 64) {
        uint32_t idx = (addr - WIFI_REG_PASS_BASE) / 4;
        memcpy(s->pass + idx * 4, &v, 4);
        return;
    }
    if (addr >= WIFI_REG_CTRL_SOCK_BASE && addr < WIFI_REG_CTRL_SOCK_BASE + 64) {
        uint32_t idx = (addr - WIFI_REG_CTRL_SOCK_BASE) / 4;
        memcpy(s->ctrl_sock_path + idx * 4, &v, 4);
        return;
    }

    /* --- Packet DMA write registers --- */

    switch (addr) {
    case WIFI_REG_CMD:
        if (v != 0) { esp_wifi_handle_cmd(s, v); }
        break;
    case WIFI_REG_EVENT:
        if (v == 0) { s->event = WIFI_EVT_NONE; esp_wifi_update_irq(s); }
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
    case WIFI_REG_TX_ADDR:
        s->tx_addr = v;
        break;
    case WIFI_REG_TX_LEN:
        if (v > 0 && v <= WIFI_PKT_BUF_SIZE && s->tx_addr != 0) {
            /* Read frame from firmware's DRAM buffer via DMA */
            uint8_t dma_buf[WIFI_PKT_BUF_SIZE];
            cpu_physical_memory_read(s->tx_addr, dma_buf, v);
            pkt_relay_send(s, dma_buf, v);
            s->tx_len = 0; /* idle */
        }
        break;
    case WIFI_REG_RX_ADDR:
        s->rx_addr = v;
        break;
    case WIFI_REG_RX_LEN:
        if (v == 0) {
            /* Firmware consumed the RX frame */
            s->rx_len = 0;
        }
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
    wpa_ctrl_close(s);
    pkt_relay_close(s);

    s->status             = WIFI_STATE_UNINIT;
    s->event              = WIFI_EVT_NONE;
    s->irq_enable         = 0;
    s->ssid_len           = 0;
    s->pass_len           = 0;
    s->scan_count         = 0;
    s->scan_idx           = 0;
    s->ip_addr            = 0;
    s->ip_mask            = 0;
    s->ip_gw              = 0;
    s->ctrl_sock_path_len = 0;
    s->net_id             = -1;
    s->conn_state         = WPA_CONN_NONE;
    s->tx_len             = 0;
    s->rx_len             = 0;

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

    s->ctrl_fd    = -1;
    s->ctrl_chan  = NULL;
    s->ctrl_watch = 0;
    s->net_id     = -1;
    s->conn_state = WPA_CONN_NONE;

    /* Packet relay init */
    s->pkt_fd          = -1;
    s->pkt_chan         = NULL;
    s->pkt_watch        = 0;
    s->tx_addr          = 0;
    s->tx_len           = 0;
    s->rx_addr          = 0;
    s->rx_len           = 0;
    s->pkt_rx_hdr_pos   = 0;
    s->pkt_rx_data_pos  = 0;
    s->pkt_rx_expected  = 0;
}

/* ---------- Class / type registration ------------------------------------- */

static void esp_wifi_class_init(ObjectClass *klass, void *data)
{
    DeviceClass *dc = DEVICE_CLASS(klass);
    dc->realize       = esp_wifi_realize;
    dc->legacy_reset  = esp_wifi_reset;
    dc->desc          = "ESP32 Virtual Wi-Fi STA device (wpa_supplicant bridge)";
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
