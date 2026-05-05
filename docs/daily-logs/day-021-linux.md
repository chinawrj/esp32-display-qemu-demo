# Day 21 — 2026-05-05 (Linux)

## Morning Planning

### 昨日回顾 (Day 20)
- ✅ `main/lwip_probe.c` + `.h` 创建
- ✅ `main/Kconfig.projbuild` 新增 DEMO_LWIP_PROBE_ENABLE/HOST/PORT
- ✅ `tools/echo_server.py` 创建
- ✅ `tools/run-direct-demo.sh` 接入 wifi_packet_relay + echo_server
- ✅ `tests/test_qemu_lwip_probe.py` 12 个 source 测试全 pass
- ❌ 运行时测试 `TestLwipProbeRuntime` 未通过 (pre-existing 控制面问题 + IP 地址不匹配)

### 今日目标
1. **Wi-Fi 仿真全栈架构审查** — 逐层找出缺失功能和架构缺陷
2. **修复关键 Bug** — IP 地址不匹配 (阻塞 NEXT-004 运行时验收)
3. **修复次要 Bug** — RX buffer 注册时机 + esp_netif_receive 内存泄漏
4. **更新 BACKLOG.md** — 记录所有发现的问题

### 验收检查点
- [ ] 架构审查文档写入日志
- [ ] mock_wpa 分配 10.0.2.x 地址，relay 地址空间一致
- [ ] RX buffer 在 START 前注册
- [ ] esp_netif_receive 的 eb 参数正确
- [ ] 非运行时测试无回归

---

## 架构审查 — Wi-Fi 仿真全栈

### 层次结构

```
┌──────────────────────────────────────────────────────────────┐
│  Layer 4: 应用层 (main/main.c, main/lwip_probe.c)            │
│           调用 esp_wifi_* 公开 API                           │
├──────────────────────────────────────────────────────────────┤
│  Layer 3: 固件 Shim (components/esp_wifi_qemu/)              │
│           esp_wifi_shim.c · esp_wifi_config.c                │
│           esp_wifi_scan.c · esp_wifi_netif.c                 │
├──────────────────────────────────────────────────────────────┤
│  Layer 2: QEMU 设备 (tools/qemu-src-patches/hw/net/esp_wifi) │
│           MMIO 0x3ff75000, 大小 0x124 bytes                  │
│           wpa_supplicant ctrl socket 桥接                    │
│           DMA 数据面 (TX_ADDR/TX_LEN/RX_ADDR/RX_LEN)         │
├──────────────────────────────────────────────────────────────┤
│  Layer 1: 宿主工具 (tools/)                                  │
│           mock_wpa_supplicant.py (ctrl plane)                │
│           wifi_packet_relay.py   (data plane, SLIRP NAT)     │
│           echo_server.py         (NEXT-004 probe target)     │
└──────────────────────────────────────────────────────────────┘
```

---

## 发现的问题

### BUG-001 — IP 地址空间不匹配 (**CRITICAL, 阻塞 NEXT-004**)

**层次**: Layer 1 (mock_wpa) ↔ Layer 1 (wifi_packet_relay) 不一致

**描述**:
- `mock_wpa_supplicant.py` 在 STATUS 响应中分配 IP `192.168.1.100`
- QEMU 设备 `wpa_parse_status()` 从 STATUS 读取 IP，并**推导**掩码 `/24`、网关 `192.168.1.1`
- 固件的 lwIP 配置的路由表: `ip=192.168.1.100/24, gw=192.168.1.1`
- `wifi_packet_relay.py` 的 SLIRP 网络: 网关 `10.0.2.2`，`10.0.2.100 → 127.0.0.1`
- `CONFIG_DEMO_LWIP_PROBE_HOST` 默认值 `10.0.2.100`

**后果**: 固件 lwIP 向 `10.0.2.100:9988` 发 TCP SYN 时，路由查找得到 "通过网关 192.168.1.1 发送"。ARP 请求 `Who has 192.168.1.1?`，但 relay 只响应 ARP for `10.0.2.2`，ARP 永远不会得到回应，TCP 连接永远建立不了。

**根因**: 控制面 IP 地址 (`192.168.1.x`) 和数据面 SLIRP 地址 (`10.0.2.x`) 来自两个独立的未对齐设计。

**修复方案**:
- 修改 `mock_wpa_supplicant.py` STATUS 响应: 分配 `10.0.2.15`
- 修改 `wpa_parse_status()` in `esp_wifi.c`: 解析 STATUS 中的 `ip_address`，并显式设置 `mask=255.255.255.0, gw=10.0.2.2` (SLIRP 标准值)
- 或者更好: 解析 STATUS 中的 `address` 字段得到 MAC，并让 relay 来分配 IP (通过 DHCP，未来特性)
- 最简方案: 统一使用 `10.0.2.15/24 gw=10.0.2.2`

---

### BUG-002 — RX buffer 注册时机过晚 (**HIGH**)

**层次**: Layer 3 (esp_wifi_netif.c)

**描述**:
`esp_wifi_netif_init()` 在 `WIFI_EVT_GOT_IP` 事件时才被调用，此时才写入 `WIFI_REG_RX_ADDR`。在这之前如果 QEMU 设备收到 RX 数据包，`s->rx_addr == 0`，帧被静默丢弃:

```c
// esp_wifi.c
if (s->rx_len == 0 && s->rx_addr != 0) {  // rx_addr=0 时直接跳过
    cpu_physical_memory_write(s->rx_addr, ...);
```

ARP 响应 (relay → firmware) 就在 GOT_IP 之前发生，可能丢失。

**修复**: 在 `WIFI_CMD_START` 或更早调用 `esp_wifi_netif_init()` 注册 RX buffer，而不是等 GOT_IP。

---

### BUG-003 — esp_netif_receive() eb 参数为 NULL (内存泄漏) (**HIGH**)

**层次**: Layer 3 (esp_wifi_netif.c)

**描述**:
```c
uint8_t *buf = (uint8_t *)malloc(rx_len);
...
esp_err_t ret = esp_netif_receive(s_sta_netif, buf, rx_len, NULL);
```

`esp_netif_receive(netif, buf, len, eb)` 的第 4 个参数 `eb` 是额外缓冲指针，ESP-IDF 内部在处理完毕后会调用 `driver_free_rx_buffer(handle, eb)` 来释放。当 `eb=NULL` 时，`qemu_wifi_free_rx_buf` 收到 `NULL` → 没有任何内存被释放 → **malloc'd buf 泄漏**。

```c
static void qemu_wifi_free_rx_buf(void *h, void *buffer) {
    (void)h;
    (void)buffer;  // BUG: 什么都不做，但 buffer 是 malloc 的
}
```

**修复**:
1. `esp_netif_receive(s_sta_netif, buf, rx_len, buf)` — 将 buf 作为 eb 传入
2. `qemu_wifi_free_rx_buf`: `if (buffer) free(buffer);`

---

### BUG-004 — wifi_qemu_send_cmd() 接受任意事件 (竞态条件) (**HIGH**)

**层次**: Layer 3 (esp_wifi_shim.c)

**描述**:
`wifi_qemu_send_cmd()` 轮询 `WIFI_REG_EVENT`，一旦 event != WIFI_EVT_NONE 就认为命令成功，不检查事件类型。这导致两个问题:

1. **跨命令事件消耗**: 若 WIFI_EVT_INIT_DONE 因网络延迟在 `WIFI_CMD_SET_MODE_STA` 的等待窗口内到达，`wifi_qemu_send_cmd(CMD_SET_MODE_STA)` 会消耗本属于 INIT 的事件。
2. **事件任务竞争**: `wifi_event_task` 每 10ms 也轮询 `WIFI_REG_EVENT`，可能比 `wifi_qemu_send_cmd` 先 ACK 掉同步事件，导致调用方超时。

**修复**: `wifi_qemu_send_cmd` 应返回期望的特定事件 code，并在 QEMU 侧为每条命令定义明确的响应事件码。短期修复: `wifi_event_task` 只在没有同步命令进行中时才消费事件 (用 semaphore 互斥)。

---

### BUG-005 — pkt_relay_open() 在 CMD_CONNECT 时打开，不是 CMD_INIT (**MEDIUM**)

**层次**: Layer 2 (esp_wifi.c)

**描述**:
```c
case WIFI_CMD_CONNECT:
    ...
    if (s->pkt_fd < 0) {
        pkt_relay_open(s);
    }
```

relay 在 CONNECT 时才打开，但 ARP resolution 发生在 TCP connect 阶段，即 GOT_IP 之后、relay 打开时刻之间可能没有问题。但如果 `pkt_relay_open` 失败 (socket 不存在)，没有重试机制，数据面永久禁用。

**修复**: 在 `CMD_START` 或 `CMD_INIT` 时尝试打开，并添加失败时的警告和重试逻辑。

---

### BUG-006 — pkt_relay_send() 使用阻塞 I/O (**MEDIUM**)

**层次**: Layer 2 (esp_wifi.c)

**描述**:
```c
ssize_t r = send(s->pkt_fd, hdr, 4, MSG_NOSIGNAL | MSG_MORE);
```

relay socket 是非阻塞 fd (`fcntl(fd, F_SETFL, flags | O_NONBLOCK)`)，但 `pkt_relay_send()` 使用阻塞式 `send`。如果 send buffer 满了，返回 EAGAIN 而不是真正阻塞，但当前代码把 `r != 4` 当作错误处理，会关闭连接。

实际上这是半对的行为 (EAGAIN → close是过激的)，但更大的问题是 TX 帧被悄悄丢弃而没有背压。

**修复**: 对 EAGAIN/EWOULDBLOCK 使用非阻塞重试，或实现 TX 环形队列。

---

### BUG-007 — ip_mask 和 ip_gw 推导规则固化 (/24, .1) (**MEDIUM**)

**层次**: Layer 2 (esp_wifi.c `wpa_parse_status`)

**描述**:
```c
s->ip_mask = htonl(0xffffff00u);           // 永远 /24
s->ip_gw   = htonl((a & 0xffffff00u) | 1u); // 永远是 .1
```

这对 SLIRP 地址 `10.0.2.15` 推导 gw=`10.0.2.1`，但 relay 的网关是 `10.0.2.2`。

**修复**: 修改 mock_wpa STATUS 格式加入 `gateway=10.0.2.2` 字段，并在 `wpa_parse_status()` 中解析。

---

### GAP-001 — 没有 DHCP 支持 (DATA PLANE) (**MEDIUM**)

**层次**: Layer 1 (wifi_packet_relay.py)

**描述**:
relay 不响应 DHCP DISCOVER/REQUEST。IP 地址仅来自 ctrl plane (wpa STATUS)。这意味着:
- lwIP 的 DHCP 客户端 (如果启用) 永远无法获取地址
- 地址配置是硬编码的，不是通过标准 DHCP 协商的

**修复**: relay 实现一个简单的 DHCP 服务器，分配固定地址 `10.0.2.15/24`，网关 `10.0.2.2`，DNS `8.8.8.8`。(或者禁用固件 DHCP，改用 `esp_netif_set_ip_info()` 静态配置，已有此路径)

---

### GAP-002 — 没有 IPv6 / ICMPv6 支持 (**LOW**)

relay 仅处理 IPv4。如果固件启用 IPv6，所有 IPv6 帧被静默丢弃。

---

### GAP-003 — 缺少 esp_wifi_restore(), get_bandwidth(), set_bandwidth() 等 API stubs (**LOW**)

如果应用代码调用了这些 API，会调用到 real ESP32 Wi-Fi 驱动（通过链接），在 QEMU 中产生未定义行为。需要 no-op stubs。

---

### GAP-004 — ctrl socket 路径仅支持环境变量，不支持通过 MMIO 下传 (**LOW**)

`WIFI_REG_CTRL_SOCK_LEN/BASE` 寄存器存在但固件端从不写入。路径始终通过 `ESP_WIFI_CTRL_SOCKET` 环境变量传递。这没有问题，但文档里应该明确这是唯一支持的方式。

---

### ARCH-001 — 事件寄存器是单值，无队列，无事件类型过滤 (**ARCHITECTURE**)

本质上是 BUG-004 的根本原因。WIFI_REG_EVENT 只能存一个事件，新事件会覆盖旧的，且消费端无法区分事件归属于哪条命令。长期应改为:
- 独立的命令响应寄存器 (CMD_RESULT) 和异步事件队列 (EVT_QUEUE)
- 或者: 事件类型分层: 0x01-0x09 为同步响应，0x10+ 为异步事件

---

### ARCH-002 — ctrl plane 和 data plane IP 地址空间完全独立 (**ARCHITECTURE**)

更深层的架构缺陷: wpa_supplicant ctrl socket 协议只提供 IP 地址字符串，没有路由信息。SLIRP relay 有自己的固定地址空间。两者之间没有自动协商机制。

**正确方案**: relay 应该充当 DHCP 服务器，作为 IP 地址的唯一权威源 (数据面和控制面统一)。

---

## 修复优先级

| ID | 层次 | 严重度 | 影响 | 今日修复 |
|----|------|--------|------|---------|
| BUG-001 | mock_wpa + QEMU | CRITICAL | 阻塞 NEXT-004 TCP 连接 | ✅ |
| BUG-002 | 固件 netif | HIGH | ARP 响应丢失 | ✅ |
| BUG-003 | 固件 netif | HIGH | RX 内存泄漏 | ✅ |
| BUG-004 | 固件 shim | HIGH | 命令/事件竞态 | 明日 |
| BUG-005 | QEMU 设备 | MEDIUM | relay 打开时机 | 明日 |
| BUG-006 | QEMU 设备 | MEDIUM | TX 丢包 | 明日 |
| BUG-007 | QEMU 设备 | MEDIUM | 网关推导错误 | ✅ (随 BUG-001 修复) |
| GAP-001 | relay | MEDIUM | 无 DHCP | 计划 |
| GAP-002 | relay | LOW | 无 IPv6 | 积压 |
| GAP-003 | 固件 | LOW | API stubs | 积压 |
| GAP-004 | 文档 | LOW | 文档改进 | 积压 |
| ARCH-001 | 协议 | ARCHITECTURE | 长期技术债 | 积压 |
| ARCH-002 | 架构 | ARCHITECTURE | 长期技术债 | 积压 |

---

## 执行记录

### BUG-001 + BUG-007 修复: IP 地址空间统一

1. **`tools/mock_wpa_supplicant.py`**: 默认 IP 改为 `10.0.2.15`，STATUS 响应中加入 `gateway=10.0.2.2` 和 `subnet_mask=255.255.255.0`，`__init__` 加入 `gateway`/`netmask` 参数，argparse 加入 `--gateway`/`--netmask` 选项。

2. **`tools/qemu-src-patches/hw/net/esp_wifi.c`**: `wpa_parse_status()` 新增解析 `gateway=` 和 `subnet_mask=` 字段；旧的 /24 + .1 推导降级为 fallback（仅在 STATUS 未提供时才运行）。

3. **`tools/run-direct-demo.sh`**: `MOCK_IP` 默认值从 `192.168.1.100` 改为 `10.0.2.15`，注释同步更新。

4. **`tests/test_qemu_integrated_demo.py`**: `_MOCK_IP = "10.0.2.15"`，docstring 和 runtime 断言同步更新。

5. **`tests/test_qemu_lwip_probe.py`**: `_MOCK_IP = "10.0.2.15"`。

6. **`tests/test_qemu_wifi_sta.py`**: `mock_ip = "10.0.2.15"`，docstring 同步更新。

### BUG-002 修复: RX buffer 早期注册

7. **`components/esp_wifi_qemu/esp_wifi_netif.c`**: 新增 `esp_wifi_netif_register_rx_buf()`，只写 `WIFI_REG_RX_ADDR`，不依赖 netif 句柄。

8. **`components/esp_wifi_qemu/esp_wifi_shim.c`**: `esp_wifi_start()` 中在 `WIFI_CMD_START` 成功后调用 `esp_wifi_netif_register_rx_buf()`，使 QEMU 设备在 DHCP/ARP 阶段就能交付帧。

### BUG-003 修复: RX 内存泄漏

9. **`components/esp_wifi_qemu/esp_wifi_netif.c`**: `qemu_wifi_free_rx_buf()` 改为 `if (buffer) free(buffer)`；`esp_netif_receive()` 的 `eb` 参数从 `NULL` 改为 `buf`，并在 `receive` 失败时手动 free。

### BACKLOG.md 更新

10. 追加了 BUG-004～BUG-006、GAP-001、GAP-003、ARCH-001、ARCH-002 条目。

### 测试结果

```
非运行时测试: 53 passed, 5 skipped (预期 infra skips)
Wi-Fi 源测试: 27 passed, 12 deselected
集成 demo:    9 passed, 1 failed (TestIntegratedDemo::test_got_ip_with_mock_ap — 预存问题，固件在 QEMU 2 次 LVGL flush 后挂起，需要 QEMU 重新编译才能验证修复效果)
```

---

## Evening Review

### 完成情况

| 目标 | 状态 |
|------|------|
| Wi-Fi 仿真全栈架构审查 | ✅ |
| IP 地址不匹配修复 (BUG-001, BUG-007) | ✅ |
| RX buffer 注册时机修复 (BUG-002) | ✅ |
| esp_netif_receive 内存泄漏修复 (BUG-003) | ✅ |
| BACKLOG.md 更新 | ✅ |
| 非运行时测试零回归 | ✅ |

### 明日计划 (Day 22)

1. **重新编译 QEMU** — `bash tools/build-qemu.sh`，集成 `esp_wifi.c` 的 STATUS 解析改动
2. **BUG-004 修复** — `wifi_event_task` / `wifi_qemu_send_cmd` 竞态，加入 `s_cmd_in_flight` 标志
3. **BUG-005 修复** — `pkt_relay_open()` 移到 `CMD_START` 时机
4. **运行时验证** — `test_got_ip_with_mock_ap` + `TestLwipProbeRuntime` 应在修复后 pass
5. **如果有时间**: GAP-001 (DHCP in relay)

### 健康指标

- 编译警告: 待验证 (QEMU 未重编)
- 单文件最大行数: `esp_wifi.c` 979 行 (触发警告阈值 250，但属于 QEMU 设备 C 文件，不计入 ESP-IDF 组件计数)
- TODO/FIXME: < 5
- 连续功能天数: 21 天，BUG-004+ 明日继续
