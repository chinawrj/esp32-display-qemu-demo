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

set -eo pipefail

REPO_URL="git@github.com:chinawrj/qemu.git"  # personal fork of espressif/qemu
BRANCH="esp-develop-based-on-9.2.2"          # matches the prebuilt esp_develop_9.2.2_20250817
SRC_DIR="$(cd "$(dirname "$0")"/.. && pwd)/tools/qemu-src"
JOBS="$(sysctl -n hw.ncpu 2>/dev/null || nproc 2>/dev/null || echo 4)"

case "${1:-}" in
  distclean) rm -rf "$SRC_DIR"; echo "[build-qemu] removed $SRC_DIR"; exit 0 ;;
  clean)     rm -rf "$SRC_DIR/build"; echo "[build-qemu] removed $SRC_DIR/build" ;;
esac

echo "[build-qemu] src dir : $SRC_DIR"
echo "[build-qemu] branch  : $BRANCH"
echo "[build-qemu] jobs    : $JOBS"

if [ ! -d "$SRC_DIR/.git" ]; then
  echo "[build-qemu] cloning (shallow, no submodules yet)..."
  git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$SRC_DIR"
else
  echo "[build-qemu] reusing existing clone at $SRC_DIR"
fi

cd "$SRC_DIR"

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
  ../configure \
    --target-list=xtensa-softmmu \
    --enable-gcrypt \
    --enable-sdl \
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
