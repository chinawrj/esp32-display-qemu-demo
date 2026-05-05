idf_component_register(
    SRCS "main.c" "qemu_vram.c" "fb_dump.c" "wifi_ui.c" "lwip_probe.c"
    INCLUDE_DIRS "include"
    REQUIRES esp_wifi esp_netif esp_event nvs_flash
)
