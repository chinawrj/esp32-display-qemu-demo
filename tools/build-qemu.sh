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
