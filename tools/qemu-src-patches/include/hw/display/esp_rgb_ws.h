/*
 * ESP RGB display WebSocket framebuffer export (NEXT-001)
 *
 * Public surface for the WebSocket transport that mirrors the esp_rgb
 * device's DisplaySurface to host clients (Chrome, pytest, etc.) over
 * 127.0.0.1:9334. Three hooks called from esp_rgb.c:
 *
 *   esp_rgb_ws_start()              — open listener once, in esp_rgb_init()
 *   esp_rgb_ws_announce_surface()   — broadcast JSON header, in update_rgb_surface()
 *   esp_rgb_ws_broadcast_frame()    — broadcast pixel frame, in rgb_update()
 *
 * All three are no-ops when ESP_RGB_WS_DISABLE is set in the environment
 * or when the listener failed to bind. Default port is 9334; override
 * with ESP_RGB_WS_PORT.
 *
 * v1 (Day 4): listener + RFC 6455 handshake only. announce_/broadcast_
 * are stubs that log "would-emit" once and return. Pixel fan-out
 * lands in Day 5.
 *
 * Marker comment: ESP_RGB_WS_PATCH (so tools/build-qemu.sh can detect
 * idempotency).
 */

#pragma once

#include "hw/display/esp_rgb.h"

/* Start the WebSocket listener for this device instance. Safe to call
 * multiple times — only the first call binds. Reads ESP_RGB_WS_PORT
 * (default 9334) and ESP_RGB_WS_DISABLE from the environment. */
void esp_rgb_ws_start(ESPRgbState *s);

/* Notify all connected clients that the DisplaySurface format/size
 * changed. Sends a JSON text frame and resets per-client seq counters. */
void esp_rgb_ws_announce_surface(ESPRgbState *s);

/* Broadcast the current DisplaySurface pixels to all connected clients
 * as a binary frame: [u32 le seq][u32 le size][bytes pixels]. Drops on
 * EAGAIN per the R1 backpressure mitigation in docs/qemu-native-ws.md. */
void esp_rgb_ws_broadcast_frame(ESPRgbState *s);
