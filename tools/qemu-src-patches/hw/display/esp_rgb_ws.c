/*
 * ESP RGB display WebSocket framebuffer export (NEXT-001)
 *
 * Day 4 deliverable — listener + RFC 6455 handshake only. No pixel
 * fan-out yet (announce_/broadcast_ are intentionally stubs that log
 * once and return). Wire protocol is documented in
 * docs/qemu-native-ws.md §1.
 *
 * Architecture: one QIONetListener bound to 127.0.0.1:$ESP_RGB_WS_PORT
 * (default 9334). On accept, wrap the socket in a QIOChannelWebsock
 * server and run qio_channel_websock_handshake(). Once the handshake
 * completes, the client is added to a per-device list (no list yet
 * in v1; lands in Day 5 with the fan-out path). The listener and all
 * clients live on QEMU's default GMainContext; no extra threads.
 *
 * Marker: ESP_RGB_WS_PATCH (used by tools/build-qemu.sh idempotency
 * check).
 */

#include "qemu/osdep.h"
#include "qemu/error-report.h"
#include "qemu/module.h"
#include "qapi/error.h"
#include "hw/sysbus.h"           /* needed by esp_rgb.h (SysBusDevice) */
#include "exec/memory.h"         /* needed by esp_rgb.h (MemoryRegion) */
#include "io/channel-socket.h"
#include "io/channel-websock.h"
#include "io/net-listener.h"
#include "io/task.h"
#include "qapi/qapi-types-sockets.h"
#include "hw/display/esp_rgb_ws.h"

#define ESP_RGB_WS_DEFAULT_PORT 9334
#define ESP_RGB_WS_BIND_ADDR    "127.0.0.1"

/* Single global listener — there is one esp_rgb device per QEMU run
 * in practice. If we ever instantiate multiples, they would race on
 * the bind; the second start() call would log a warning and skip. */
static QIONetListener *g_ws_listener;
static bool g_ws_disabled;
static int g_ws_clients_total;  /* monotonic, for log line numbering */

/* Stub log-once flags — Day 4 announce_/broadcast_ both log a single
 * line per device boot to confirm the hook fires, then go quiet. */
static bool g_logged_announce;
static bool g_logged_broadcast;

static void esp_rgb_ws_handshake_done(QIOTask *task, gpointer opaque)
{
    QIOChannelWebsock *wioc = QIO_CHANNEL_WEBSOCK(opaque);
    Error *err = NULL;

    if (qio_task_propagate_error(task, &err)) {
        warn_report("esp_rgb_ws: handshake failed: %s",
                    error_get_pretty(err));
        error_free(err);
        object_unref(OBJECT(wioc));
        return;
    }

    info_report("esp_rgb_ws: client #%d handshake complete",
                g_ws_clients_total);
    /* TODO Day 5: register client into broadcast list and send the
     * cached JSON header immediately. For Day 4 we just close the
     * channel — the test only asserts the upgrade succeeds. */
    object_unref(OBJECT(wioc));
}

static void esp_rgb_ws_accept(QIONetListener *listener,
                              QIOChannelSocket *cioc,
                              gpointer opaque)
{
    QIOChannelWebsock *wioc;

    g_ws_clients_total++;
    info_report("esp_rgb_ws: accepted client #%d, starting WS handshake",
                g_ws_clients_total);

    wioc = qio_channel_websock_new_server(QIO_CHANNEL(cioc));
    qio_channel_set_name(QIO_CHANNEL(wioc), "esp-rgb-ws-server");

    /* The websock channel takes its own ref on the master via the
     * constructor's internal book-keeping; we no longer need the
     * accept-time ref. */
    qio_channel_websock_handshake(wioc,
                                  esp_rgb_ws_handshake_done,
                                  wioc,
                                  NULL);
}

static int esp_rgb_ws_resolve_port(void)
{
    const char *env = getenv("ESP_RGB_WS_PORT");
    long n;
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

void esp_rgb_ws_start(ESPRgbState *s)
{
    SocketAddress addr;
    Error *err = NULL;
    int port;
    char port_str[8];

    (void) s;  /* unused in Day 4 — no per-device state yet */

    if (getenv("ESP_RGB_WS_DISABLE")) {
        g_ws_disabled = true;
        info_report("esp_rgb_ws: disabled by ESP_RGB_WS_DISABLE");
        return;
    }
    if (g_ws_listener) {
        /* Idempotent: a second esp_rgb device would re-call us. */
        warn_report("esp_rgb_ws: listener already running, skipping");
        return;
    }

    port = esp_rgb_ws_resolve_port();
    snprintf(port_str, sizeof(port_str), "%d", port);

    memset(&addr, 0, sizeof(addr));
    addr.type = SOCKET_ADDRESS_TYPE_INET;
    addr.u.inet.host = (char *) ESP_RGB_WS_BIND_ADDR;
    addr.u.inet.port = port_str;
    addr.u.inet.has_ipv4 = true;
    addr.u.inet.ipv4 = true;
    addr.u.inet.has_ipv6 = true;
    addr.u.inet.ipv6 = false;

    g_ws_listener = qio_net_listener_new();
    qio_net_listener_set_name(g_ws_listener, "esp-rgb-ws-listener");

    if (qio_net_listener_open_sync(g_ws_listener, &addr, 1, &err) < 0) {
        warn_report("esp_rgb_ws: bind %s:%d failed: %s",
                    ESP_RGB_WS_BIND_ADDR, port, error_get_pretty(err));
        error_free(err);
        object_unref(OBJECT(g_ws_listener));
        g_ws_listener = NULL;
        return;
    }

    qio_net_listener_set_client_func(g_ws_listener,
                                     esp_rgb_ws_accept,
                                     NULL,
                                     NULL);

    info_report("esp_rgb_ws: listening on ws://%s:%d/ (NEXT-001 v1)",
                ESP_RGB_WS_BIND_ADDR, port);
}

void esp_rgb_ws_announce_surface(ESPRgbState *s)
{
    if (g_ws_disabled || !g_ws_listener) {
        return;
    }
    if (!g_logged_announce) {
        info_report("esp_rgb_ws: announce_surface hook fired "
                    "(w=%u h=%u bpp=%d) — fan-out lands Day 5",
                    s->width, s->height, (int) s->bpp);
        g_logged_announce = true;
    }
}

void esp_rgb_ws_broadcast_frame(ESPRgbState *s)
{
    if (g_ws_disabled || !g_ws_listener) {
        return;
    }
    if (!g_logged_broadcast) {
        info_report("esp_rgb_ws: broadcast_frame hook fired "
                    "(area=%ux%u) — fan-out lands Day 5",
                    s->to_x - s->from_x, s->to_y - s->from_y);
        g_logged_broadcast = true;
    }
}
