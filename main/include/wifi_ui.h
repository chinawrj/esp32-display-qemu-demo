#pragma once

/**
 * @brief Initialize the Wi-Fi status LVGL label.
 *
 * Must be called after lv_display_create() but before the main LVGL loop.
 * Creates a small translucent label at the top of the screen showing the
 * current Wi-Fi connection state.
 */
void wifi_ui_init(void);

/**
 * @brief Queue a Wi-Fi status text update.
 *
 * Thread-safe: safe to call from Wi-Fi event handler tasks.
 * The label is updated on the next wifi_ui_tick() call from the LVGL task.
 *
 * @param msg  Status message (≤ 63 chars). Truncated if longer.
 */
void wifi_ui_set_status(const char *msg);

/**
 * @brief Apply any pending status update to the LVGL label.
 *
 * Must be called from the same task that calls lv_timer_handler().
 * Typically placed at the top of the main LVGL tick loop.
 */
void wifi_ui_tick(void);
