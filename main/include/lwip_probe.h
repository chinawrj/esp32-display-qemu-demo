#pragma once
/*
 * lwip_probe.h — NEXT-004: lwIP TCP socket probe.
 *
 * After Wi-Fi connects and an IP is assigned, call lwip_probe_start() to
 * spawn a background FreeRTOS task that opens a TCP connection to HOST:PORT,
 * sends "PING\n", and logs "lwip probe ok:" on receiving any response.
 *
 * The probe validates end-to-end data-plane connectivity:
 *   firmware lwIP → QEMU esp_wifi DMA → wifi_packet_relay.py → localhost echo
 */

#include <stdint.h>

/**
 * @brief Start the lwIP probe task.
 *
 * Creates a FreeRTOS task that retries the TCP connection until success or
 * max attempts are exhausted.  Non-blocking; returns immediately.
 *
 * @param host  IP address string of the target host (e.g. "10.0.2.100").
 * @param port  TCP port to connect to (e.g. 9988).
 */
void lwip_probe_start(const char *host, uint16_t port);
