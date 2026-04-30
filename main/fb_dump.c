#include "fb_dump.h"

#include <stdio.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char b64_alphabet[] =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

void fb_dump_base64(const uint8_t *data, size_t len, int width, int height)
{
    printf("\n<<<FB_BEGIN size=%u w=%d h=%d fmt=RGB565>>>\n",
           (unsigned)len, width, height);

    char line[64 + 8];  /* up to 60 b64 chars + "FB=" prefix + NUL */
    size_t lp = 0;
    line[lp++] = 'F'; line[lp++] = 'B'; line[lp++] = '=';
    const size_t prefix = lp;

    for (size_t i = 0; i < len; i += 3) {
        uint32_t b0 = data[i];
        uint32_t b1 = (i + 1 < len) ? data[i + 1] : 0;
        uint32_t b2 = (i + 2 < len) ? data[i + 2] : 0;
        uint32_t triple = (b0 << 16) | (b1 << 8) | b2;

        line[lp++] = b64_alphabet[(triple >> 18) & 0x3F];
        line[lp++] = b64_alphabet[(triple >> 12) & 0x3F];
        line[lp++] = (i + 1 < len) ? b64_alphabet[(triple >> 6) & 0x3F] : '=';
        line[lp++] = (i + 2 < len) ? b64_alphabet[triple & 0x3F] : '=';

        if (lp >= prefix + 60) {
            line[lp] = '\0';
            puts(line);
            lp = prefix;
        }
    }
    if (lp > prefix) {
        line[lp] = '\0';
        puts(line);
    }
    /* Brief settle so the UART FIFO drains before the END marker */
    vTaskDelay(pdMS_TO_TICKS(50));
    printf("<<<FB_END>>>\n");
}
