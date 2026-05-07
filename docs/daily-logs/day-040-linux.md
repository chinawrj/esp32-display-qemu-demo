# Day 40 — 2026-05-07

## 目标
完全接管宿主机 Wi-Fi 网卡，将 real-scan 后端从 nmcli 替换为直连 wpa_supplicant
的 `wpa_cli`，彻底踢出 nmcli。

## 完成内容

### 1. 将 chinawrj 加入 netdev 组
`/var/run/wpa_supplicant` 目录权限 `0750 root:netdev`，需要 netdev 组才能访问。

```bash
sudo usermod -a -G netdev chinawrj
# 新登录会话自动生效；当前会话通过 sg netdev 桥接
```

### 2. 替换扫描后端：nmcli → wpa_cli
**移除**：`_nmcli_to_wpa_scan_results()` — 调用 nmcli，需要 NetworkManager
  中间层，质量值 0-100 需要手动转换为 dBm。

**新增**三个静态方法：

| 方法 | 作用 |
|------|------|
| `_need_sg_netdev()` | 检查当前进程是否在 netdev 组中；未在则用 `sg netdev` 桥接 |
| `_run_wpa_cli(ctrl_dir, iface, *args)` | 封装 wpa_cli 调用，自动处理 sg 回退 |
| `_wpa_cli_scan_results(ctrl_dir, iface)` | 触发真实硬件扫描，代理 wpa_cli 原生输出 |

**关键改进**：
- wpa_cli `scan_results` 输出已是 `bssid\tfreq\tsignal(dBm)\tflags\tssid` 格式，
  与 wpa_supplicant 协议完全一致，零转换直接代理。
- `wpa_cli scan` 触发真实频道扫描，等待 5 秒确保 2.4G + 5G 双频扫完。
- 按 BSSID 去重（与之前一致）。

### 3. 新增 CLI 选项
- `--wpa-ctrl-dir`：wpa_supplicant ctrl 目录（默认 `/var/run/wpa_supplicant`）
- `--wpa-iface`：Wi-Fi 接口名（默认自动检测，`_auto_detect_iface()` 解析 `ip link`）

### 4. 更新测试
更新/新增 6 个 real-scan 测试（`test_stock_sample_build.py`）：

| 测试 | 内容 |
|------|------|
| `test_mock_has_real_scan_flag` | `--real-scan` flag 存在（不变）|
| `test_mock_real_scan_calls_wpa_cli` | 检查 `_wpa_cli_scan_results` + `wpa_cli` |
| `test_mock_real_scan_proxies_wpa_cli_output` | 确认无 nmcli 质量转换公式 |
| `test_mock_real_scan_has_wpa_iface_option` | `--wpa-iface`/`--wpa-ctrl-dir`/`_need_sg_netdev` |
| `test_mock_real_scan_deduplicates_bssids` | BSSID 去重仍存在（不变）|
| `test_run_stock_qemu_exposes_real_scan_env` | REAL_SCAN env var（不变）|

## 测试结果

```
87 passed in 105.96s (test_stock_sample_build + test_qemu_wifi_sta)
```

## 实机运行结果

```
REAL_SCAN=1 VERIFY_PROFILE=scan bash tools/run-stock-qemu.sh .../scan/build_qemu 55

[mock-wpa] wpa_cli scan: 14 AP(s)
I (8467) scan: Total APs scanned = 14, actual AP number ap_info holds = 10
I (8467) scan: SSID  NETGEAR51-5G
I (8477) scan: SSID  Telecom-5G
I (8487) scan: SSID  NETGEAR51
I (8497) scan: SSID  Telecom
I (8497) scan: SSID  WG602
I (8497) scan: SSID  DIRECT-54-HP M281 LaserJet
...
✅ QEMU Wi-Fi init  ✅ STA started  ✅ Scan results  ✅ No crash
4 check(s) passed, 0 failed.
```

数据来源：宿主机 wlo1 (Intel Wi-Fi 网卡) 通过 wpa_supplicant 直接扫描，
**完全旁路 nmcli / NetworkManager**。

## 已知问题（延续自 Day 39）
隐藏 AP（空 SSID）在固件日志中显示为 raw bssid 行，不影响功能和扫描计数。

## 北极星对齐
- ✅ stock ESP-IDF scan sample 在 QEMU 中 zero-diff 运行，宿主机真实 AP 可见
- 扫描数据来自真实 Wi-Fi 驱动，不经任何中间层
- 下一步：调查 BSSID 去重后 14 AP 中 hidden SSID 的显示问题（cosmetic）
