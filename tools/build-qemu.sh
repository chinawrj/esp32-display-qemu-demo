#!/usr/bin/env bash
# Build espressif/qemu locally for xtensa target.
#
# Produces: tools/qemu-src/build/qemu-system-xtensa
#
# Usage:
#   bash tools/build-qemu.sh           # clone (if needed) + configure + build
#   bash tools/build-qemu.sh clean     # rm -rf build/ then rebuild
#   bash tools/build-qemu.sh distclean # rm -rf tools/qemu-src/ entirely
#
# Prerequisites (macOS, brew):
#   brew install pixman glib ninja pkg-config libgcrypt sdl2
#
# IMPORTANT — host toolchain requirements:
#   * Clang ≥ 10 (XCode ≥ 14) OR GCC ≥ 7.4.
#     QEMU 9.2 upstream demands XCode Clang ≥ 15, but we patch
#     tools/qemu-src/meson.build to relax this to XCode 14 so macOS 12
#     (Apple Clang 14) builds. Apple's SDK headers use clang-specific
#     attribute syntax that GCC cannot parse, so Homebrew GCC is NOT a
#     viable substitute — Apple Clang is required on macOS.
#   * Python with `distlib` available — script auto-uses the project .venv.

set -eo pipefail

REPO_URL="git@github.com:chinawrj/qemu.git"  # personal fork of espressif/qemu
BRANCH="esp-develop-based-on-9.2.2"          # matches the prebuilt esp_develop_9.2.2_20250817
SRC_DIR="$(cd "$(dirname "$0")"/.. && pwd)/tools/qemu-src"
JOBS="$(sysctl -n hw.ncpu 2>/dev/null || nproc 2>/dev/null || echo 4)"

case "${1:-}" in
  distclean) rm -rf "$SRC_DIR"; echo "[build-qemu] removed $SRC_DIR"; exit 0 ;;
  clean)     rm -rf "$SRC_DIR/build"; echo "[build-qemu] removed $SRC_DIR/build" ;;
esac

# Host compiler selection — QEMU's meson check has been relaxed (in our fork)
# to allow Apple Clang 14 on macOS 12. Honor user-supplied CC/CXX, otherwise
# let configure auto-detect (defaults to /usr/bin/cc → Apple clang).
# (Using Homebrew GCC bottle was attempted but it cannot parse Apple SDK
#  headers' clang-specific attribute syntax.)
export CC CXX

echo "[build-qemu] src dir : $SRC_DIR"
echo "[build-qemu] branch  : $BRANCH"
echo "[build-qemu] jobs    : $JOBS"
echo "[build-qemu] CC      : ${CC:-<default cc>}"
echo "[build-qemu] CXX     : ${CXX:-<default c++>}"

if [ ! -d "$SRC_DIR/.git" ]; then
  echo "[build-qemu] cloning (shallow, no submodules yet)..."
  git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$SRC_DIR"
else
  echo "[build-qemu] reusing existing clone at $SRC_DIR"
fi

cd "$SRC_DIR"

# Idempotently relax QEMU's hard XCode 15 / Apple Clang 15 requirement to
# Clang 14, so macOS 12 (Apple Clang 14) can compile QEMU 9.2. Clang 14
# actually builds QEMU fine — the upstream guard is conservative.
if grep -q "XCode Clang v15.0" meson.build 2>/dev/null; then
  echo "[build-qemu] patching meson.build: relax XCode Clang v15 -> v14"
  # macOS sed needs an explicit backup-suffix arg
  sed -i.bak \
    -e 's/__clang_major__ < 15 || (__clang_major__ == 15/__clang_major__ < 14 || (__clang_major__ == 14/g' \
    -e 's/XCode Clang v15.0/XCode Clang v14.0/g' \
    meson.build
fi

# Idempotently patch hw/display/esp_rgb.c so the device's VRAM can optionally
# be backed by a host file (shared mmap) when env ESP_RGB_VRAM_FILE is set.
# This lets a host process read the live framebuffer without changing default
# behaviour. Marker: ESP_RGB_VRAM_FILE_PATCH.
if [ -f hw/display/esp_rgb.c ] && ! grep -q "ESP_RGB_VRAM_FILE_PATCH" hw/display/esp_rgb.c; then
  echo "[build-qemu] patching hw/display/esp_rgb.c: opt-in file-backed VRAM"
  python3 - <<'PY'
import re, pathlib
p = pathlib.Path("hw/display/esp_rgb.c")
src = p.read_text()
old = '    /* Create a memory region that can be used as a framebuffer by the guest */\n    memory_region_init_ram(&s->vram, OBJECT(s), "esp-rgb-vram", ESP_RGB_MAX_VRAM_SIZE, &error_abort);\n'
new = '''    /* Create a memory region that can be used as a framebuffer by the guest */
    /* ESP_RGB_VRAM_FILE_PATCH: if env ESP_RGB_VRAM_FILE is set, back VRAM with
     * a shared host file so external tools can mmap and stream live pixels. */
    {
        const char *vram_file = getenv("ESP_RGB_VRAM_FILE");
        if (vram_file && vram_file[0]) {
            memory_region_init_ram_from_file(&s->vram, OBJECT(s),
                "esp-rgb-vram", ESP_RGB_MAX_VRAM_SIZE, 0,
                RAM_SHARED, vram_file, 0, &error_abort);
            info_report("esp_rgb: VRAM backed by shared file %s (%u bytes)",
                vram_file, (unsigned)ESP_RGB_MAX_VRAM_SIZE);
        } else {
            memory_region_init_ram(&s->vram, OBJECT(s),
                "esp-rgb-vram", ESP_RGB_MAX_VRAM_SIZE, &error_abort);
        }
    }
'''
assert old in src, "anchor not found in hw/display/esp_rgb.c"
p.write_text(src.replace(old, new, 1))
PY
fi

# ESP_RGB_WS_PATCH (NEXT-001): install esp_rgb_ws.{c,h} from the
# tracked tools/qemu-src-patches/ tree and add the new source to
# hw/display/meson.build. Both steps are idempotent. Canonical sources
# live in the repo so a fresh clone of qemu-src reproduces today's
# binary. See docs/qemu-native-ws.md.
PATCH_ROOT="$(cd "$SRC_DIR/.." && pwd)/qemu-src-patches"
if [ -d "$PATCH_ROOT" ]; then
  echo "[build-qemu] installing ESP_RGB_WS_PATCH source files"
  install -m 0644 "$PATCH_ROOT/hw/display/esp_rgb_ws.c" \
    "$SRC_DIR/hw/display/esp_rgb_ws.c"
  install -m 0644 "$PATCH_ROOT/include/hw/display/esp_rgb_ws.h" \
    "$SRC_DIR/include/hw/display/esp_rgb_ws.h"

  if ! grep -q "esp_rgb_ws.c" "$SRC_DIR/hw/display/meson.build"; then
    echo "[build-qemu] patching hw/display/meson.build: register esp_rgb_ws.c"
    # macOS sed needs an explicit backup-suffix arg
    sed -i.bak \
      -e "s|files('esp_rgb.c')|files('esp_rgb.c', 'esp_rgb_ws.c')|" \
      "$SRC_DIR/hw/display/meson.build"
  fi
fi

# ESP_RGB_WS_PATCH hooks in esp_rgb.c: idempotently add the include and
# the three esp_rgb_ws_*() call-sites. Marker: ESP_RGB_WS_PATCH.
if [ -f "$SRC_DIR/hw/display/esp_rgb.c" ] && \
   ! grep -q "ESP_RGB_WS_PATCH" "$SRC_DIR/hw/display/esp_rgb.c"; then
  echo "[build-qemu] patching hw/display/esp_rgb.c: inject ESP_RGB_WS_PATCH hooks"
  python3 - <<'PY'
import pathlib
p = pathlib.Path("hw/display/esp_rgb.c")
src = p.read_text()

# 1. Add include after sysemu/dma.h
src = src.replace(
    '#include "sysemu/dma.h"\n\n#define RGB_WARNING',
    '#include "sysemu/dma.h"\n'
    '/* ESP_RGB_WS_PATCH (NEXT-001): WebSocket framebuffer export */\n'
    '#include "hw/display/esp_rgb_ws.h"\n\n'
    '#define RGB_WARNING',
    1,
)

# 2. Add announce_surface call in update_rgb_surface()
src = src.replace(
    '    surface->flags = QEMU_ALLOCATED_FLAG;\n'
    '    dpy_gfx_replace_surface(s->con, surface);\n'
    '};',
    '    surface->flags = QEMU_ALLOCATED_FLAG;\n'
    '    dpy_gfx_replace_surface(s->con, surface);\n'
    '    /* ESP_RGB_WS_PATCH: notify clients that DisplaySurface format/size changed */\n'
    '    esp_rgb_ws_announce_surface(s);\n'
    '};',
    1,
)

# 3. Add broadcast_frame call after dpy_gfx_update in rgb_update()
src = src.replace(
    '            dpy_gfx_update(s->con, s->from_x, s->from_y, width, height);\n'
    '        }\n'
    '#if RGB_WARNING\n'
    '        else {\n'
    '            warn_report("[ESP RGB] Invalid drawing area");\n'
    '        }\n'
    '#endif\n'
    '\n'
    '        /* Automatically clear the update flag',
    '            dpy_gfx_update(s->con, s->from_x, s->from_y, width, height);\n'
    '            /* ESP_RGB_WS_PATCH: push updated pixels to WS clients */\n'
    '            esp_rgb_ws_broadcast_frame(s);\n'
    '        }\n'
    '#if RGB_WARNING\n'
    '        else {\n'
    '            warn_report("[ESP RGB] Invalid drawing area");\n'
    '        }\n'
    '#endif\n'
    '\n'
    '        /* Automatically clear the update flag',
    1,
)

# 4. Add esp_rgb_ws_start() at end of esp_rgb_init()
src = src.replace(
    '    /* Create an AddressSpace out of the MemoryRegion to be able to perform DMA */\n'
    '    address_space_init(&s->vram_as, &s->vram, "esp.rgb.vram_as");\n'
    '}',
    '    /* Create an AddressSpace out of the MemoryRegion to be able to perform DMA */\n'
    '    address_space_init(&s->vram_as, &s->vram, "esp.rgb.vram_as");\n'
    '\n'
    '    /* ESP_RGB_WS_PATCH: open WebSocket listener (no-op if ESP_RGB_WS_DISABLE set) */\n'
    '    esp_rgb_ws_start(s);\n'
    '}',
    1,
)

p.write_text(src)
PY
fi

# ESP_RGB_WS_PATCH_V2: add unconditional (throttled) broadcast_frame() at the
# end of rgb_update() so clients receive frames even when the firmware writes
# directly to VRAM without triggering the MMIO update path.
# The call inside the existing update_area block stays for the MMIO path.
if [ -f "$SRC_DIR/hw/display/esp_rgb.c" ] && \
   grep -q "ESP_RGB_WS_PATCH" "$SRC_DIR/hw/display/esp_rgb.c" && \
   ! grep -q "ESP_RGB_WS_PATCH_V2" "$SRC_DIR/hw/display/esp_rgb.c"; then
  echo "[build-qemu] patching esp_rgb.c: ESP_RGB_WS_PATCH_V2 unconditional broadcast"
  python3 - <<'PY'
import pathlib
p = pathlib.Path("hw/display/esp_rgb.c")
src = p.read_text()

# Insert an unconditional, throttled broadcast_frame() at the END of
# rgb_update() — after the closing brace of the if (s->update_area) block.
# The anchor is unique: the comment that follows the update_area block.
src = src.replace(
    '        /* Automatically clear the update flag, the guest can re-use the given color_content buffer.\n'
    '         * It must set it again to trigger another update. */\n'
    '        s->update_area = false;\n'
    '    }\n'
    '}\n'
    '\n'
    '\n'
    'static void rgb_invalidate',
    '        /* Automatically clear the update flag, the guest can re-use the given color_content buffer.\n'
    '         * It must set it again to trigger another update. */\n'
    '        s->update_area = false;\n'
    '    }\n'
    '    /* ESP_RGB_WS_PATCH_V2: unconditional throttled broadcast so VRAM-direct\n'
    '     * firmware (qemu_vram_mirror path) also streams frames to WS clients. */\n'
    '    esp_rgb_ws_broadcast_frame(s);\n'
    '}\n'
    '\n'
    '\n'
    'static void rgb_invalidate',
    1,
)

p.write_text(src)
PY
fi

# ESP_WIFI_PATCH (NEXT-002): install esp_wifi.{c,h} from qemu-src-patches,
# register the device in hw/net/meson.build, and wire it into esp32.h / esp32.c.
# Marker: ESP_WIFI_PATCH
if [ -d "$PATCH_ROOT" ] && \
   [ -f "$PATCH_ROOT/hw/net/esp_wifi.c" ] && \
   [ -f "$PATCH_ROOT/include/hw/net/esp_wifi.h" ]; then

  echo "[build-qemu] installing ESP_WIFI_PATCH source files"
  install -d "$SRC_DIR/hw/net"
  install -d "$SRC_DIR/include/hw/net"
  install -m 0644 "$PATCH_ROOT/hw/net/esp_wifi.c" \
    "$SRC_DIR/hw/net/esp_wifi.c"
  install -m 0644 "$PATCH_ROOT/include/hw/net/esp_wifi.h" \
    "$SRC_DIR/include/hw/net/esp_wifi.h"

  # Register esp_wifi.c in hw/net/meson.build (unconditional build)
  if ! grep -q "esp_wifi.c" "$SRC_DIR/hw/net/meson.build"; then
    echo "[build-qemu] patching hw/net/meson.build: register esp_wifi.c"
    echo "" >> "$SRC_DIR/hw/net/meson.build"
    echo "# ESP_WIFI_PATCH (NEXT-002): virtual Wi-Fi STA device" >> "$SRC_DIR/hw/net/meson.build"
    echo "system_ss.add(files('esp_wifi.c'))" >> "$SRC_DIR/hw/net/meson.build"
  fi

  # Patch include/hw/xtensa/esp32.h: add ESPWifiState field to Esp32SocState
  if ! grep -q "ESP_WIFI_PATCH" "$SRC_DIR/include/hw/xtensa/esp32.h"; then
    echo "[build-qemu] patching include/hw/xtensa/esp32.h: add ESPWifiState wifi"
    python3 - "$SRC_DIR/include/hw/xtensa/esp32.h" <<'PY'
import sys, pathlib
p = pathlib.Path(sys.argv[1])
src = p.read_text()
src = src.replace(
    '#include "hw/display/esp_rgb.h"',
    '#include "hw/display/esp_rgb.h"\n'
    '#include "hw/net/esp_wifi.h"  /* ESP_WIFI_PATCH (NEXT-002) */',
    1,
)
src = src.replace(
    '    ESPRgbState rgb;',
    '    ESPRgbState rgb;\n'
    '    ESPWifiState wifi;  /* ESP_WIFI_PATCH (NEXT-002) */',
    1,
)
p.write_text(src)
PY
  fi

  # Patch hw/xtensa/esp32.c: include header + object_initialize_child + realize + reset
  if ! grep -q "ESP_WIFI_PATCH" "$SRC_DIR/hw/xtensa/esp32.c"; then
    echo "[build-qemu] patching hw/xtensa/esp32.c: wire in esp_wifi device"
    python3 - "$SRC_DIR/hw/xtensa/esp32.c" <<'PY'
import sys, pathlib
p = pathlib.Path(sys.argv[1])
src = p.read_text()

# 1. Add #include after esp32.h include
src = src.replace(
    '#include "hw/xtensa/esp32.h"',
    '#include "hw/xtensa/esp32.h"\n'
    '#include "hw/misc/esp32_reg.h"  /* ESP_WIFI_PATCH: ETS_WIFI_MAC_INTR_SOURCE */\n'
    '/* ESP_WIFI_PATCH (NEXT-002): virtual Wi-Fi device already in esp32.h */',
    1,
)

# 2. Add object_initialize_child after rgb init
src = src.replace(
    '    object_initialize_child(obj, "rgb", &s->rgb, TYPE_ESP_RGB);',
    '    object_initialize_child(obj, "rgb", &s->rgb, TYPE_ESP_RGB);\n\n'
    '    /* ESP_WIFI_PATCH (NEXT-002): virtual Wi-Fi STA device */\n'
    '    object_initialize_child(obj, "wifi", &s->wifi, TYPE_ESP_WIFI);',
    1,
)

# 3. Add realize + IRQ connect after rgb periph registration
src = src.replace(
    '    esp32_soc_add_periph_device(sys_mem, &s->rgb, DR_REG_FRAMEBUF_BASE);',
    '    esp32_soc_add_periph_device(sys_mem, &s->rgb, DR_REG_FRAMEBUF_BASE);\n\n'
    '    /* ESP_WIFI_PATCH (NEXT-002): realize and map virtual Wi-Fi device */\n'
    '    qdev_realize(DEVICE(&s->wifi), &s->periph_bus, &error_fatal);\n'
    '    esp32_soc_add_periph_device(sys_mem, &s->wifi, DR_REG_WDEV_BASE);\n'
    '    sysbus_connect_irq(SYS_BUS_DEVICE(&s->wifi), 0,\n'
    '                       qdev_get_gpio_in(intmatrix_dev, ETS_WIFI_MAC_INTR_SOURCE));',
    1,
)

# 4. Add device_cold_reset alongside rgb reset
src = src.replace(
    '        device_cold_reset(DEVICE(&s->rgb));',
    '        device_cold_reset(DEVICE(&s->rgb));\n'
    '        device_cold_reset(DEVICE(&s->wifi));  /* ESP_WIFI_PATCH */',
    1,
)

p.write_text(src)
PY
  fi
fi

# Only init submodules required for xtensa-softmmu. Skipping the giant
# edk2/SeaBIOS/etc. roms saves >2 GB and many minutes of cloning.
SUBMODULES_NEEDED=(
  "subprojects/dtc"
  "subprojects/keycodemapdb"
  "subprojects/berkeley-softfloat-3"
  "subprojects/berkeley-testfloat-3"
)
for sm in "${SUBMODULES_NEEDED[@]}"; do
  if [ -f ".gitmodules" ] && grep -q "path = ${sm}\$" .gitmodules; then
    if [ ! -f "${sm}/.git" ] && [ ! -d "${sm}/.git" ]; then
      echo "[build-qemu] init submodule: $sm"
      git submodule update --init --depth 1 "$sm" || true
    fi
  fi
done

if [ ! -f build/build.ninja ]; then
  echo "[build-qemu] configuring..."
  mkdir -p build
  cd build
  # QEMU 9.2.x's mkvenv.py needs the `distlib` module. Python 3.14 in
  # Homebrew is PEP-668 EXTERNALLY-MANAGED so we point configure at the
  # project venv (which has distlib installed via requirements).
  PROJECT_VENV_PY="$(cd "$SRC_DIR/../.." && pwd)/.venv/bin/python3"
  PY_FLAG=""
  if [ -x "$PROJECT_VENV_PY" ]; then
    PY_FLAG="--python=${PROJECT_VENV_PY}"
    echo "[build-qemu] using python: $PROJECT_VENV_PY"
  fi
  CC_FLAG=""
  CXX_FLAG=""
  OBJCC_FLAG=""
  if [ -n "${CC:-}" ]; then CC_FLAG="--cc=${CC}"; fi
  if [ -n "${CXX:-}" ]; then CXX_FLAG="--cxx=${CXX}"; fi
  # On macOS QEMU also probes the Objective-C compiler (still clang 14 from
  # CommandLineTools). Point it at gcc-NN too — gcc happily handles the
  # tiny amount of ObjC code involved (and we --disable-cocoa anyway).
  if [ -n "${CC:-}" ]; then OBJCC_FLAG="--objcc=${CC}"; fi
  ../configure $PY_FLAG $CC_FLAG $CXX_FLAG $OBJCC_FLAG \
    --target-list=xtensa-softmmu \
    --enable-gcrypt \
    --enable-sdl \
    --disable-cocoa \
    --disable-werror \
    --disable-docs \
    --disable-tools \
    --disable-vnc \
    --disable-guest-agent
  cd ..
else
  echo "[build-qemu] reusing existing build/ (run 'clean' to rebuild from scratch)"
fi

echo "[build-qemu] building (ninja -C build -j${JOBS})..."
ninja -C build -j"${JOBS}"

BIN="$SRC_DIR/build/qemu-system-xtensa"
if [ ! -x "$BIN" ]; then
  echo "[build-qemu] FAILED: $BIN not produced"
  exit 1
fi

echo "[build-qemu] OK"
"$BIN" --version | head -2
echo "[build-qemu] export QEMU_BIN=$BIN  # to use this binary with tools/run-qemu.sh"
