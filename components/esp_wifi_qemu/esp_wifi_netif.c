/**
 * @file esp_wifi_netif.c
 * @brief QEMU virtual Wi-Fi — custom lwIP netif driver (TCP/IP data plane).
 *
 * Implements the TX/RX packet forwarding between the ESP-IDF lwIP stack and
 * the QEMU virtual Wi-Fi device MMIO registers, which bridge to the host
 * packet relay daemon (tools/wifi_packet_relay.py) via a Unix stream socket.
 *
 * TX path:  lwIP → esp_netif_transmit() → qemu_wifi_transmit() → MMIO TX buf
 * RX path:  QEMU MMIO RX buf → WIFI_EVT_RX_READY → esp_netif_receive() → lwIP
 *
 * Wire-format: raw Ethernet frames (14-byte header + payload), matching the
 * standard ESP-IDF Wi-Fi STA interface contract.
 *
 * NEXT-003: TCP/IP data plane for QEMU Wi-Fi simulator.
 */

#include "sdkconfig.h"

#if CONFIG_ESP_WIFI_QEMU

#include <string.h>
#include <stdint.h>
#include "esp_err.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_wifi_qemu.h"
#include "esp_wifi_private.h"

static const char *TAG = "wifi_netif";

/* ---------------------------------------------------------------------------
 * Forward declaration (defined in esp_wifi_shim.c / shared state)
 * -------------------------------------------------------------------------*/
extern esp_netif_t *s_sta_netif;   /* cached netif handle (set on GOT_IP) */

/* ---------------------------------------------------------------------------
 * Static DMA buffers in DRAM — QEMU reads/writes these directly via
 * cpu_physical_memory_read/write using the physical addresses we register.
 * Must be 4-byte aligned.
 * -------------------------------------------------------------------------*/
static uint8_t s_tx_buf[WIFI_PKT_BUF_SIZE] __attribute__((aligned(4)));
static uint8_t s_rx_buf[WIFI_PKT_BUF_SIZE] __attribute__((aligned(4)));

/* ---------------------------------------------------------------------------
 * BUG-002 fix: register RX DMA address early (before GOT_IP) so incoming
 * ARP/DHCP frames are never dropped because rx_addr==0 in QEMU device.
 * Called from esp_wifi_start() in esp_wifi_shim.c.
 * -------------------------------------------------------------------------*/
void esp_wifi_netif_register_rx_buf(void)
{
    wifi_qemu_write(WIFI_REG_RX_ADDR, (uint32_t)(uintptr_t)s_rx_buf);
    ESP_LOGD(TAG, "RX DMA buffer pre-registered at %p", (void *)s_rx_buf);
}

/* ---------------------------------------------------------------------------
 * TX callback — called by lwIP to transmit a frame onto the virtual wire
 * Also exposed as qemu_wifi_tx_raw() for esp_wifi_internal_tx() (the path
 * used by the IDF default wifi driver when app calls
 * esp_wifi_set_default_wifi_sta_handlers).
 * -------------------------------------------------------------------------*/
static esp_err_t qemu_wifi_transmit(void *h, void *buffer, size_t len)
{
    (void)h;
    return qemu_wifi_tx_raw(buffer, (uint16_t)len) == 0 ? ESP_OK : ESP_ERR_NO_MEM;
}

int qemu_wifi_tx_raw(const void *buffer, uint16_t len)
{
    if (!buffer || len == 0 || (size_t)len > WIFI_PKT_BUF_SIZE) {
        return -1;
    }
    /* Copy frame into DMA TX buffer */
    memcpy(s_tx_buf, buffer, len);
    /* Register TX buffer address (QEMU reads from it on TX_LEN write) */
    wifi_qemu_write(WIFI_REG_TX_ADDR, (uint32_t)(uintptr_t)s_tx_buf);
    /* Writing TX_LEN triggers the actual DMA read + transmission */
    wifi_qemu_write(WIFI_REG_TX_LEN, (uint32_t)len);
    ESP_LOGD(TAG, "TX %u bytes (raw)", (unsigned)len);
    return 0;
}

/* ---------------------------------------------------------------------------
 * RX buffer free callback — called by esp_netif when it is done with a frame.
 * We pass the malloc'd buf as the 'eb' argument to esp_netif_receive(), so
 * this callback is invoked with that pointer and must free it.
 * -------------------------------------------------------------------------*/
static void qemu_wifi_free_rx_buf(void *h, void *buffer)
{
    (void)h;
    free(buffer);  /* BUG-003 fix: free the malloc'd RX frame buffer */
}

/* ---------------------------------------------------------------------------
 * Driver config (static, no heap allocation needed)
 * -------------------------------------------------------------------------*/
static esp_netif_driver_ifconfig_t s_driver_cfg = {
    .handle              = (void *)0xdeadbeef, /* non-NULL sentinel */
    .transmit            = qemu_wifi_transmit,
    .transmit_wrap       = NULL,
    .driver_free_rx_buffer = qemu_wifi_free_rx_buf,
};

/* ---------------------------------------------------------------------------
 * Public API
 * -------------------------------------------------------------------------*/

/**
 * @brief Replace the default Wi-Fi driver on the STA netif with our DMA driver.
 *
 * Must be called AFTER esp_netif_create_default_wifi_sta() and AFTER the
 * GOT_IP event has set s_sta_netif.
 * Registers the static RX DMA buffer address with QEMU.
 *
 * @param netif  The esp_netif_t created for STA (must not be NULL).
 * @return ESP_OK or an error code.
 */
esp_err_t esp_wifi_netif_init(esp_netif_t *netif)
{
    if (!netif) {
        ESP_LOGE(TAG, "netif is NULL");
        return ESP_ERR_INVALID_ARG;
    }

    esp_err_t ret = esp_netif_set_driver_config(netif, &s_driver_cfg);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "set_driver_config failed: %s", esp_err_to_name(ret));
        return ret;
    }

    /* Register the RX DMA buffer address with QEMU. */
    wifi_qemu_write(WIFI_REG_RX_ADDR, (uint32_t)(uintptr_t)s_rx_buf);

    ESP_LOGI(TAG, "QEMU DMA netif driver installed (tx_buf=%p rx_buf=%p)",
             (void *)s_tx_buf, (void *)s_rx_buf);
    return ESP_OK;
}

/**
 * @brief Inject the RX Ethernet frame (already in s_rx_buf via QEMU DMA) into lwIP.
 *
 * Called from wifi_event_task() when WIFI_EVT_RX_READY is posted.
 * The frame is already in s_rx_buf (QEMU wrote it there via cpu_physical_memory_write).
 * Copy to a heap buffer, pass to esp_netif_receive(), clear WIFI_REG_RX_LEN.
 */
void esp_wifi_netif_rx_frame(void)
{
    uint32_t rx_len = wifi_qemu_read(WIFI_REG_RX_LEN);
    if (rx_len == 0 || rx_len > WIFI_PKT_BUF_SIZE) {
        wifi_qemu_write(WIFI_REG_RX_LEN, 0);
        return;
    }

    /* Allocate a heap buffer — esp_netif_receive takes ownership */
    uint8_t *buf = (uint8_t *)malloc(rx_len);
    if (!buf) {
        ESP_LOGE(TAG, "malloc(%u) failed for RX frame", (unsigned)rx_len);
        wifi_qemu_write(WIFI_REG_RX_LEN, 0);
        return;
    }

    /* Copy from DMA buffer (QEMU already wrote the frame here) */
    memcpy(buf, s_rx_buf, rx_len);

    /* Signal QEMU device that we consumed the frame */
    wifi_qemu_write(WIFI_REG_RX_LEN, 0);

    if (!s_sta_netif) {
        s_sta_netif = esp_netif_get_handle_from_ifkey("WIFI_STA_DEF");
    }
    if (!s_sta_netif) {
        free(buf);
        return;
    }

    /* esp_netif_receive takes ownership of buf. Pass buf as the 'eb'
     * (extra-buffer) argument so esp_netif calls qemu_wifi_free_rx_buf(handle, buf)
     * when done. BUG-003 fix: previously eb was NULL → buf was never freed. */
    esp_err_t ret = esp_netif_receive(s_sta_netif, buf, rx_len, buf);
    if (ret != ESP_OK) {
        ESP_LOGW(TAG, "esp_netif_receive failed: %s", esp_err_to_name(ret));
        free(buf);
    }
    ESP_LOGD(TAG, "RX %u bytes injected", (unsigned)rx_len);
}

#endif /* CONFIG_ESP_WIFI_QEMU */
