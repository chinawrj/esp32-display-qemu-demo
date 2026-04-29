# Real-time framebuffer push (cdp-phase2b)

Status: **design — implementation blocked on `qemu-local-clone-build`.**

Today the firmware path captures framebuffers as base64-encoded blobs in the
UART log (`<<<FB_BEGIN ...>>>`), and the Chrome viewer can replay those logs
line-by-line via `tools/fb_server/log_producer.py`. That's a useful zero-mod
pipeline but it costs roughly **one frame per few seconds** (UART-bound).

For interactive demos and CDP-driven UI loops we want **live** push.

## Options considered

| Approach | Where bridge lives | Throughput | Mod required |
|---|---|---|---|
| **A. UART log replay** (today) | host `log_producer.py` | ~0.3 fps | none |
| **B. TCP from firmware** (`esp_lcd_chrome_panel` → host TCP) | new component | 30+ fps | firmware: add TCP client; QEMU: `-nic user,hostfwd=tcp:127.0.0.1:7799-:7799` |
| **C. QEMU chardev** (firmware writes to virtual UART2; host reads chardev pipe) | host bridge process | 30+ fps | firmware: tiny driver writing to UART2; QEMU: `-chardev socket,...` (already supported upstream) |
| **D. QEMU shmem device** (`-object memory-backend-file,share=on`; firmware mmaps) | host shmem reader | 60+ fps | QEMU: device addition; firmware: mmap-equivalent (depends on mem region exposure) — **deeper** |

## Recommendation

Adopt **C (QEMU chardev)** as the first real-time path. It needs:

- Upstream Espressif QEMU already supports `-serial`/`-chardev` for UART0..2.
- Firmware: an `esp_lcd_chrome_panel` `draw_bitmap()` that frames each dirty
  rect as `header(16B)+payload` and writes to UART2.
- Host: a small reader that connects to `unix:/tmp/qemu-fb.sock` and forwards
  framed payloads to the existing WebSocket protocol verbatim.

Why not B? TCP from guest works but pulls in lwIP / NIC config and adds a
moving piece (NAT'd virtual NIC). C reuses the chardev plumbing we already
need for UART0 logging anyway.

Why not D? Best peak throughput but requires a custom QEMU device — that's
exactly what `qemu-fb-shmem-bridge` covers and is currently blocked on the
local QEMU build.

## Acceptance for first slice

1. `components/esp_lcd_chrome_panel/` exists with `init`, `draw_bitmap`,
   `del`. It opens UART2 in non-blocking mode and writes `[hdr][payload]`.
2. `tools/fb_server/qemu_chardev_producer.py` reads from a Unix socket and
   forwards to WS.
3. `tools/run-qemu.sh` learns a `--chardev-fb` flag that adds
   `-chardev socket,id=fb,path=/tmp/qemu-fb.sock,server=on,wait=off
    -serial chardev:fb`.
4. `tests/cdp/test_realtime_push.py` boots the stack and asserts at least
   10 fb_update messages reach the page within 2 s.

Until `qemu-local-clone-build` is unblocked, this doc captures the
intended design so the next session can pick it up directly.
