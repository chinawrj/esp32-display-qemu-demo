#pragma once

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Emit base64 of `data` to stdout in 60-char `FB=`-prefixed lines, surrounded
 * by `<<<FB_BEGIN ...>>>` / `<<<FB_END>>>` sentinels. Designed to be parseable
 * from a serial log. `width`/`height` are recorded in the BEGIN sentinel for
 * downstream tooling (RGB565 layout assumed). */
void fb_dump_base64(const uint8_t *data, size_t len, int width, int height);

#ifdef __cplusplus
}
#endif
