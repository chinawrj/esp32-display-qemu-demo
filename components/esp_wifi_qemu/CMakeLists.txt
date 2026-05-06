idf_component_register(
    SRCS "esp_wifi_shim.c" "esp_wifi_config.c" "esp_wifi_scan.c" "esp_wifi_netif.c"
         "esp_wifi_extras.c" "esp_wifi_internal.c" "esp_wifi_ap.c" "esp_wifi_promisc.c"
    INCLUDE_DIRS "include"
    PRIV_INCLUDE_DIRS "."
    REQUIRES esp_wifi esp_event esp_netif nvs_flash freertos log
)

# When QEMU virtual Wi-Fi is active the shim overrides libnet80211 symbols.
# --whole-archive scoped to THIS archive ensures all stubs are exported even
# if not directly referenced.  --no-whole-archive immediately after prevents
# pulling the entire real esp_wifi (librtc IRAM functions) into IRAM which
# would overflow ESP32 IRAM by ~2 KB.
# --allow-multiple-definition handles the duplicate symbol between our stubs
# and the real esp_wifi archive that still appears in LINK_LIBRARIES.
if(CONFIG_ESP_WIFI_QEMU)
    target_link_options(${COMPONENT_LIB} INTERFACE
        "-Wl,--whole-archive"
        "$<TARGET_LINKER_FILE:${COMPONENT_LIB}>"
        "-Wl,--no-whole-archive"
        "-Wl,--allow-multiple-definition")
endif()
