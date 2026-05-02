/*
 * ESP RGB display WebSocket framebuffer export (NEXT-001)
 *
 * Day 5 deliverable — pixel fan-out: per-client QLIST, announce_surface
 * broadcasts a JSON header as a TEXT frame, broadcast_frame sends the
 * full DisplaySurface as a BINARY frame with an 8-byte header.
 * Wire protocol documented in docs/qemu-native-ws.md §1.
 *
 * Architecture: one QIONetListener bound to 127.0.0.1:$ESP_RGB_WS_PORT
 * (default 9334). On accept, wrap socket in QIOChannelWebsock for the
 * RFC 6455 handshake only. Post-handshake the underlying master channel
 * (raw TCP QIOChannelSocket) is saved in the per-client struct and used
 * directly for all subsequent writes so we can choose TEXT vs BINARY
 * opcode freely (qio_channel_websock_writev always emits BINARY).
 *
 * All I/O runs on QEMU's default GMainContext inside the BQL; no extra
 * threads are created.
 *
 * Marker: ESP_RGB_WS_PATCH (used by tools/build-qemu.sh idempotency
 * check).
 */

#include "qemu/osdep.h"
#include "qemu/error-report.h"
#include "qemu/iov.h"
#include "qemu/module.h"
#include "qemu/queue.h"
#include "qapi/error.h"
#include "hw/sysbus.h"           /* needed by esp_rgb.h (SysBusDevice) */
#include "exec/memory.h"         /* needed by esp_rgb.h (MemoryRegion) */
#include "io/channel-socket.h"
#include "io/channel-websock.h"
#include "io/net-listener.h"
#include "io/task.h"
#include "qapi/qapi-types-sockets.h"
#include "ui/console.h"
#include "ui/surface.h"
#include "hw/display/esp_rgb_ws.h"

#define ESP_RGB_WS_DEFAULT_PORT 9334
#define ESP_RGB_WS_BIND_ADDR    "127.0.0.1"

/* RFC 6455 server-to-client opcodes (no client masking for server writes) */
#define WS_OPCODE_TEXT   0x1u
#define WS_OPCODE_BINARY 0x2u

/* ---------------------------------------------------------------------------
 * Per-client state
 * --------------------------------------------------------------------------- */

typedef struct ESPRgbWsClient {
    QIOChannel *master;          /* underlying TCP channel; owned ref      */
    uint32_t    seq;             /* per-client monotonic frame counter      */
    QLIST_ENTRY(ESPRgbWsClient) next;
} ESPRgbWsClient;

/* Module-level global (one esp_rgb device per QEMU run in practice).
 * Protected by the BQL — all callbacks and display refreshes run there. */
static struct {
    QIONetListener *listener;
    bool            disabled;
    ESPRgbState    *dev;         /* back-reference set in start()           */
    char           *json_header; /* cached JSON; NULL until first announce  */
    QLIST_HEAD(, ESPRgbWsClient) clients;
    int             total_accepted; /* monotonic, for log messages          */
    uint64_t        dropped_frames; /* frames skipped due to send error     */
} g_ws;

/* ---------------------------------------------------------------------------
 * RFC 6455 frame encoder (server side — no masking)
 * --------------------------------------------------------------------------- */

/*
 * ws_send_frame — write a single RFC 6455 frame to the raw TCP channel.
 *
 * The payload is provided as an iovec array so callers can avoid extra
 * copies (e.g. frame_header + pixel_buffer as two iov segments).
 * Uses qio_channel_writev_full_all() which loops until every byte is
 * written or returns -1 on error. This is safe to call from the BQL
 * because loopback TCP writes complete in microseconds at the sizes we
 * use (≤ ~130 KB for a 240×135×4 surface).
 *
 * Returns 0 on success, -1 on error (caller should remove the client).
 */
static int ws_send_frame(QIOChannel *ch, unsigned opcode,
                         const struct iovec *iov, size_t niov)
{
    size_t   payload_len = iov_size(iov, niov);
    uint8_t  ws_hdr[10];
    size_t   ws_hlen;
    Error   *err = NULL;
    struct iovec *full_iov;
    int      r;

    /* Build RFC 6455 frame header: FIN=1, no RSV, opcode, no mask. */
    ws_hdr[0] = (uint8_t)(0x80u | (opcode & 0x0Fu));
    if (payload_len < 126u) {
        ws_hdr[1] = (uint8_t) payload_len;
        ws_hlen = 2;
    } else if (payload_len <= 0xFFFFu) {
        ws_hdr[1] = 126;
        ws_hdr[2] = (uint8_t)(payload_len >> 8);
        ws_hdr[3] = (uint8_t)(payload_len & 0xFFu);
        ws_hlen = 4;
    } else {
        uint64_t l = (uint64_t) payload_len;
        ws_hdr[1] = 127;
        ws_hdr[2] = (uint8_t)(l >> 56);
        ws_hdr[3] = (uint8_t)(l >> 48);
        ws_hdr[4] = (uint8_t)(l >> 40);
        ws_hdr[5] = (uint8_t)(l >> 32);
        ws_hdr[6] = (uint8_t)(l >> 24);
        ws_hdr[7] = (uint8_t)(l >> 16);
        ws_hdr[8] = (uint8_t)(l >>  8);
        ws_hdr[9] = (uint8_t)(l >>  0);
        ws_hlen = 10;
    }

    /* Build a new iov that prepends the WS header. */
    full_iov = g_new(struct iovec, niov + 1);
    full_iov[0].iov_base = ws_hdr;
    full_iov[0].iov_len  = ws_hlen;
    for (size_t i = 0; i < niov; i++) {
        full_iov[i + 1] = iov[i];
    }

    r = qio_channel_writev_full_all(ch, full_iov, niov + 1,
                                    NULL, 0, 0, &err);
    g_free(full_iov);
    if (r < 0) {
        error_free(err);
        return -1;
    }
    return 0;
}

static int ws_send_text(QIOChannel *ch, const char *text, size_t len)
{
    struct iovec iov = { .iov_base = (void *)(uintptr_t) text,
                         .iov_len  = len };
    return ws_send_frame(ch, WS_OPCODE_TEXT, &iov, 1);
}

/* ---------------------------------------------------------------------------
 * Client lifecycle helpers
 * --------------------------------------------------------------------------- */

static void client_remove(ESPRgbWsClient *c)
{
    QLIST_REMOVE(c, next);
    object_unref(OBJECT(c->master));
    g_free(c);
}

/* ---------------------------------------------------------------------------
 * Accept / handshake callbacks
 * --------------------------------------------------------------------------- */

static void esp_rgb_ws_handshake_done(QIOTask *task, gpointer opaque)
{
    QIOChannelWebsock *wioc = QIO_CHANNEL_WEBSOCK(opaque);
    ESPRgbWsClient    *c;
    Error             *err = NULL;

    if (qio_task_propagate_error(task, &err)) {
        warn_report("esp_rgb_ws: handshake failed: %s",
                    error_get_pretty(err));
        error_free(err);
        object_unref(OBJECT(wioc));
        return;
    }

    g_ws.total_accepted++;
    info_report("esp_rgb_ws: client #%d handshake complete",
                g_ws.total_accepted);

    /*
     * Save a ref to the underlying TCP channel. All subsequent writes
     * go directly to this channel so we can choose TEXT vs BINARY opcode
     * freely — qio_channel_websock_writev always emits BINARY frames.
     */
    c = g_new0(ESPRgbWsClient, 1);
    c->master = QIO_CHANNEL(object_ref(OBJECT(wioc->master)));
    c->seq    = 0;
    QLIST_INSERT_HEAD(&g_ws.clients, c, next);

    /* Send the cached JSON header immediately if one is available. */
    if (g_ws.json_header) {
        if (ws_send_text(c->master, g_ws.json_header,
                         strlen(g_ws.json_header)) < 0) {
            warn_report("esp_rgb_ws: client #%d: header send failed, removing",
                        g_ws.total_accepted);
            client_remove(c);
        }
    }

    /* Release the websock wrapper — we no longer need it. */
    object_unref(OBJECT(wioc));
}

static void esp_rgb_ws_accept(QIONetListener *listener,
                              QIOChannelSocket *cioc,
                              gpointer opaque)
{
    QIOChannelWebsock *wioc;
    (void) listener;
    (void) opaque;

    info_report("esp_rgb_ws: incoming connection, starting WS handshake");

    wioc = qio_channel_websock_new_server(QIO_CHANNEL(cioc));
    qio_channel_set_name(QIO_CHANNEL(wioc), "esp-rgb-ws-server");

    qio_channel_websock_handshake(wioc,
                                  esp_rgb_ws_handshake_done,
                                  wioc,
                                  NULL);
}

/* ---------------------------------------------------------------------------
 * Timer-driven broadcast (fires every 500 ms regardless of display refresh)
 *
 * QEMU's gfx_update callback (rgb_update) is only called when a display
 * listener (SDL/GTK/VNC) is registered. With -nographic or -display none
 * there is no listener and gfx_update never fires. We register a GLib
 * periodic timer here so WS clients receive frames in any boot mode.
 * --------------------------------------------------------------------------- */

static gboolean esp_rgb_ws_timer_cb(gpointer unused)
{
    (void) unused;
    if (!g_ws.disabled && g_ws.dev && !QLIST_EMPTY(&g_ws.clients)) {
        esp_rgb_ws_broadcast_frame(g_ws.dev);
    }
    return G_SOURCE_CONTINUE;  /* keep repeating */
}

/* ---------------------------------------------------------------------------
 * Port resolution
 * --------------------------------------------------------------------------- */

static int esp_rgb_ws_resolve_port(void)
{
    const char *env = getenv("ESP_RGB_WS_PORT");
    long  n;
    char *end;

    if (!env || !env[0]) {
        return ESP_RGB_WS_DEFAULT_PORT;
    }
    n = strtol(env, &end, 10);
    if (*end != '\0' || n <= 0 || n > 65535) {
        warn_report("esp_rgb_ws: ESP_RGB_WS_PORT=%s invalid; using %d",
                    env, ESP_RGB_WS_DEFAULT_PORT);
        return ESP_RGB_WS_DEFAULT_PORT;
    }
    return (int) n;
}

/* ---------------------------------------------------------------------------
 * Public API
 * --------------------------------------------------------------------------- */

void esp_rgb_ws_start(ESPRgbState *s)
{
    SocketAddress addr;
    Error *err = NULL;
    int   port;
    char  port_str[8];

    if (getenv("ESP_RGB_WS_DISABLE")) {
        g_ws.disabled = true;
        info_report("esp_rgb_ws: disabled by ESP_RGB_WS_DISABLE");
        return;
    }
    if (g_ws.listener) {
        warn_report("esp_rgb_ws: listener already running, skipping");
        return;
    }

    g_ws.dev = s;
    QLIST_INIT(&g_ws.clients);

    port = esp_rgb_ws_resolve_port();
    snprintf(port_str, sizeof(port_str), "%d", port);

    memset(&addr, 0, sizeof(addr));
    addr.type              = SOCKET_ADDRESS_TYPE_INET;
    addr.u.inet.host       = (char *) ESP_RGB_WS_BIND_ADDR;
    addr.u.inet.port       = port_str;
    addr.u.inet.has_ipv4   = true;
    addr.u.inet.ipv4       = true;
    addr.u.inet.has_ipv6   = true;
    addr.u.inet.ipv6       = false;

    g_ws.listener = qio_net_listener_new();
    qio_net_listener_set_name(g_ws.listener, "esp-rgb-ws-listener");

    if (qio_net_listener_open_sync(g_ws.listener, &addr, 1, &err) < 0) {
        warn_report("esp_rgb_ws: bind %s:%d failed: %s",
                    ESP_RGB_WS_BIND_ADDR, port, error_get_pretty(err));
        error_free(err);
        object_unref(OBJECT(g_ws.listener));
        g_ws.listener = NULL;
        return;
    }

    qio_net_listener_set_client_func(g_ws.listener,
                                     esp_rgb_ws_accept,
                                     NULL,
                                     NULL);

    /* Start a periodic timer to fan-out frames even when QEMU runs with
     * -nographic or -display none (where gfx_update is never called). */
    g_timeout_add(500, esp_rgb_ws_timer_cb, NULL);

    info_report("esp_rgb_ws: listening on ws://%s:%d/ (NEXT-001 v1)",
                ESP_RGB_WS_BIND_ADDR, port);
}

void esp_rgb_ws_announce_surface(ESPRgbState *s)
{
    ESPRgbWsClient *c, *next_c;
    char            json[256];
    const char     *fmt_str;
    int             stride_bytes;

    fmt_str      = (s->bpp == BPP_16) ? "r5g6b5" : "x8r8g8b8";
    stride_bytes = (int) s->width * ((s->bpp == BPP_16) ? 2 : 4);

    snprintf(json, sizeof(json),
             "{\"version\":1,\"w\":%u,\"h\":%u,\"format\":\"%s\","
             "\"stride_bytes\":%d,\"fps_target\":30}",
             s->width, s->height, fmt_str, stride_bytes);

    /* Always update the cached header — may be called before the listener
     * is up (during esp_rgb_init), in which case new clients will pick it
     * up from handshake_done(). */
    g_free(g_ws.json_header);
    g_ws.json_header = g_strdup(json);

    /* Only broadcast to clients if the listener is active. */
    if (g_ws.disabled || !g_ws.listener) {
        return;
    }

    info_report("esp_rgb_ws: announce_surface w=%u h=%u fmt=%s",
                s->width, s->height, fmt_str);

    QLIST_FOREACH_SAFE(c, &g_ws.clients, next, next_c) {
        c->seq = 0;
        if (ws_send_text(c->master, json, strlen(json)) < 0) {
            warn_report("esp_rgb_ws: announce: client send failed, removing");
            client_remove(c);
        }
    }
}

void esp_rgb_ws_broadcast_frame(ESPRgbState *s)
{
    ESPRgbWsClient *c, *next_c;
    DisplaySurface *surf;
    void           *pixels;
    uint32_t        w, h, bpp, pixel_size;

    if (g_ws.disabled || !g_ws.listener) {
        return;
    }
    if (QLIST_EMPTY(&g_ws.clients)) {
        return;
    }

    surf = qemu_console_surface(s->con);
    if (!surf) {
        return;
    }

    pixels     = surface_data(surf);
    w          = (uint32_t) surface_width(surf);
    h          = (uint32_t) surface_height(surf);
    bpp        = (uint32_t) surface_bytes_per_pixel(surf);
    pixel_size = w * h * bpp;

    QLIST_FOREACH_SAFE(c, &g_ws.clients, next, next_c) {
        uint8_t frame_hdr[8];

        /* Binary frame header: [u32 LE seq][u32 LE pixel_size] */
        frame_hdr[0] = (uint8_t)(c->seq >>  0);
        frame_hdr[1] = (uint8_t)(c->seq >>  8);
        frame_hdr[2] = (uint8_t)(c->seq >> 16);
        frame_hdr[3] = (uint8_t)(c->seq >> 24);
        frame_hdr[4] = (uint8_t)(pixel_size >>  0);
        frame_hdr[5] = (uint8_t)(pixel_size >>  8);
        frame_hdr[6] = (uint8_t)(pixel_size >> 16);
        frame_hdr[7] = (uint8_t)(pixel_size >> 24);

        struct iovec iov[2] = {
            { .iov_base = frame_hdr, .iov_len = 8          },
            { .iov_base = pixels,    .iov_len = pixel_size  },
        };

        if (ws_send_frame(c->master, WS_OPCODE_BINARY, iov, 2) < 0) {
            warn_report("esp_rgb_ws: broadcast: client send failed, removing");
            g_ws.dropped_frames++;
            client_remove(c);
        } else {
            c->seq++;
        }
    }
}
