idf_component_register(
    SRCS "esp_wifi_shim.c" "esp_wifi_config.c" "esp_wifi_scan.c"
         "esp_wifi_netif.c" "esp_wifi_extras.c" "esp_wifi_internal.c"
    INCLUDE_DIRS "include"
    PRIV_INCLUDE_DIRS "."
    REQUIRES esp_wifi esp_event esp_netif nvs_flash freertos log
)

# When QEMU virtual Wi-Fi is active the shim overrides libnet80211 symbols.
# --whole-archive forces all our object files to be linked (not just those
# referenced by other objects), so our stubs win over the matching symbols
# in libnet80211.a regardless of link order.  --allow-multiple-definition
# suppresses the duplicate-symbol error that would otherwise occur.
if(CONFIG_ESP_WIFI_QEMU)
    target_link_options(${COMPONENT_LIB} INTERFACE
        "-Wl,--whole-archive"
        "$<TARGET_FILE:${COMPONENT_LIB}>"
        "-Wl,--no-whole-archive"
        "-Wl,--allow-multiple-definition")
endif()
