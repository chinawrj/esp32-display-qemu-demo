idf_component_register(SRCS "app_main.c"
                    PRIV_REQUIRES esp_wifi esp_netif esp_event nvs_flash lwip
                    INCLUDE_DIRS ".")
