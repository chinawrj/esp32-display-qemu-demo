#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_system.h"

static const char *TAG = "app_main";

void app_main(void)
{
    ESP_LOGI(TAG, "========================================");
    ESP_LOGI(TAG, "  esp32-display-qemu-demo starting...");
    ESP_LOGI(TAG, "========================================");
    
    ESP_LOGI(TAG, "Hello World from QEMU!");
    ESP_LOGI(TAG, "Project: esp32-display-qemu-demo");
    ESP_LOGI(TAG, "Target: esp32-qemu");
    
    /* Simple loop to keep the application running */
    for (int i = 0; i < 10; i++) {
        ESP_LOGI(TAG, "Loop iteration: %d", i);
        vTaskDelay(1000 / portTICK_PERIOD_MS);
    }
    
    ESP_LOGI(TAG, "========================================");
    ESP_LOGI(TAG, "  Application completed successfully");
    ESP_LOGI(TAG, "========================================");
}
