/* esp_wifi_internal.c — GAP-F & GAP-A(CSI) stubs for QEMU Wi-Fi shim.
 *
 * These are esp_wifi_internal_* symbols called by the ESP-IDF netif glue
 * (esp_netif_attach_wifi_station / esp_wifi_default.c) and CSI symbols
 * called by advanced Wi-Fi samples.  In our QEMU shim the data-plane is
 * driven directly via MMIO, so these functions are no-ops or thin redirects.
 *
 * All functions are compiled ONLY when CONFIG_ESP_WIFI_QEMU=y.
 */

#include "sdkconfig.h"
#if CONFIG_ESP_WIFI_QEMU

#include <stdint.h>
#include <stddef.h>
#include "esp_err.h"
#include "esp_log.h"
#include "esp_wifi_types.h"
#include "esp_private/wifi.h"

static const char *TAG = "wifi_internal";

/* -----------------------------------------------------------------------
 * GAP-F: esp_wifi_internal_* — driver glue used by esp_netif
 * ----------------------------------------------------------------------- */

/**
 * Called by esp_netif to register the RX callback that should deliver
 * frames to lwIP.  In our shim the netif driver (esp_wifi_netif.c) is
 * installed manually at GOT_IP time, so we ignore this registration and
 * return OK to silence the error log.
 */
esp_err_t esp_wifi_internal_reg_rxcb(wifi_interface_t ifx, wifi_rxcb_t fn)
{
    (void)ifx; (void)fn;
    ESP_LOGD(TAG, "reg_rxcb if=%d (QEMU: ignored, using MMIO path)", (int)ifx);
    return ESP_OK;
}

/**
 * Called by esp_netif after it obtains a static IP to push the address
 * into the Wi-Fi driver.  QEMU shim already has the IP from mock_wpa STATUS;
 * this is a no-op.
 */
esp_err_t esp_wifi_internal_set_sta_ip(void)
{
    ESP_LOGD(TAG, "set_sta_ip (QEMU: no-op)");
    return ESP_OK;
}

/**
 * Free an RX buffer that was passed to the lwIP RX callback.
 * QEMU shim copies frame bytes into the netif pbuf, so the original
 * buffer (if any) is already handled; this is a safe no-op.
 */
void esp_wifi_internal_free_rx_buffer(void *buffer)
{
    (void)buffer;
}

/**
 * Register netstack reference/free callbacks used by zero-copy TX.
 * Not needed for QEMU shim which copies frames.
 */
esp_err_t esp_wifi_internal_reg_netstack_buf_cb(
        wifi_netstack_buf_ref_cb_t ref,
        wifi_netstack_buf_free_cb_t free_cb)
{
    (void)ref; (void)free_cb;
    ESP_LOGD(TAG, "reg_netstack_buf_cb (QEMU: no-op)");
    return ESP_OK;
}

/**
 * Transmit a raw Ethernet frame via Wi-Fi.
 * The QEMU shim drives TX through the esp_netif driver (qemu_wifi_transmit
 * in esp_wifi_netif.c), so this path is normally not reached.  Return 0 to
 * prevent callers from treating it as a fatal error.
 */
int esp_wifi_internal_tx(wifi_interface_t wifi_if, void *buffer, uint16_t len)
{
    (void)wifi_if; (void)buffer; (void)len;
    ESP_LOGD(TAG, "internal_tx if=%d len=%u (QEMU: no-op, using netif driver)", (int)wifi_if, (unsigned)len);
    return 0;
}

/**
 * Update MAC timing info.  Not meaningful in QEMU.
 */
esp_err_t esp_wifi_internal_update_mac_time(uint32_t time_delta)
{
    (void)time_delta;
    return ESP_OK;
}

/**
 * Set Wi-Fi driver log level.  Forwarded to ESP_LOG but otherwise
 * a no-op in the QEMU shim.
 */
esp_err_t esp_wifi_internal_set_log_level(wifi_log_level_t level)
{
    (void)level;
    return ESP_OK;
}

esp_err_t esp_wifi_internal_set_log_mod(wifi_log_module_t module,
                                         uint32_t submodule, bool enable)
{
    (void)module; (void)submodule; (void)enable;
    return ESP_OK;
}

/* -----------------------------------------------------------------------
 * GAP-A (CSI): Channel State Information — not available in QEMU
 * ----------------------------------------------------------------------- */

esp_err_t esp_wifi_set_csi_rx_cb(wifi_csi_cb_t cb, void *ctx)
{
    (void)cb; (void)ctx;
    ESP_LOGD(TAG, "set_csi_rx_cb (QEMU: unsupported)");
    return ESP_ERR_NOT_SUPPORTED;
}

esp_err_t esp_wifi_set_csi_config(const wifi_csi_config_t *config)
{
    (void)config;
    ESP_LOGD(TAG, "set_csi_config (QEMU: unsupported)");
    return ESP_ERR_NOT_SUPPORTED;
}

esp_err_t esp_wifi_set_csi(bool en)
{
    (void)en;
    ESP_LOGD(TAG, "set_csi en=%d (QEMU: unsupported)", (int)en);
    return ESP_ERR_NOT_SUPPORTED;
}

#endif /* CONFIG_ESP_WIFI_QEMU */
