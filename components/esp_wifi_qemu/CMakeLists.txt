idf_component_register(
    SRCS "esp_wifi_shim.c" "esp_wifi_config.c" "esp_wifi_scan.c"
         "esp_wifi_netif.c" "esp_wifi_extras.c"
    INCLUDE_DIRS "include"
    PRIV_INCLUDE_DIRS "."
    REQUIRES esp_wifi esp_event esp_netif nvs_flash freertos log
)

# When QEMU virtual Wi-Fi is active the shim overrides libnet80211 symbols.
# Allow duplicate definitions so the linker picks ours (linked earlier).
if(CONFIG_ESP_WIFI_QEMU)
    target_link_options(${COMPONENT_LIB} INTERFACE
        "-Wl,--allow-multiple-definition")
endif()
