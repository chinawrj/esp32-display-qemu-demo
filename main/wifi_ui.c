#include "wifi_ui.h"

#include <string.h>
#include "esp_log.h"
#include "lvgl.h"

static const char *TAG = "wifi_ui";

static lv_obj_t     *s_label          = NULL;
static volatile bool  s_dirty         = false;
static char           s_buf[64]       = "Wi-Fi: connecting...";

void wifi_ui_init(void)
{
    s_label = lv_label_create(lv_screen_active());
    lv_obj_set_style_text_color(s_label, lv_color_white(), 0);
    lv_obj_set_style_bg_color(s_label, lv_color_black(), 0);
    lv_obj_set_style_bg_opa(s_label, LV_OPA_50, 0);
    lv_obj_align(s_label, LV_ALIGN_TOP_MID, 0, 2);
    lv_label_set_text(s_label, s_buf);
    lv_obj_null_on_delete(&s_label);
    ESP_LOGI(TAG, "wifi_ui: label created");
}

void wifi_ui_set_status(const char *msg)
{
    strlcpy(s_buf, msg, sizeof(s_buf));
    s_dirty = true;
    ESP_LOGI(TAG, "wifi_ui: status queued: %s", msg);
}

void wifi_ui_tick(void)
{
    if (s_dirty && s_label) {
        lv_label_set_text(s_label, s_buf);
        s_dirty = false;
    }
}
