idf_component_register(
    SRCS "esp_wifi_shim.c"
    INCLUDE_DIRS "include"
    REQUIRES esp_event esp_netif nvs_flash
)
