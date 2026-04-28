# esp32-display-qemu-demo

🎨 **Run LVGL UI on ESP32 QEMU Emulator — No Hardware Required**

A project to develop and test ESP32 display interfaces using the official QEMU emulator, featuring LVGL (Light and Versatile Graphics Library) for modern, lightweight UI rendering.

## 🎯 Project Goals

- ✅ Build and compile ESP32 firmware without real hardware
- ✅ Run LVGL UI demos on QEMU emulator
- ✅ Verify display rendering through QEMU framebuffer
- ✅ Create reproducible development environment
- ✅ Implement automated testing pipeline

## 📋 Prerequisites

### Required

- **macOS/Linux**: Development machine
- **ESP-IDF v5.5+**: [Install Guide](https://docs.espressif.com/projects/esp-idf/en/latest/esp32/get-started/)
- **QEMU**: `qemu-system-xtensa` emulator
- **Python 3.10+**: For build tools
- **tmux**: For multi-window terminal management

### Optional

- **VS Code**: With MCP servers configured (see `.vscode/mcp.json`)
- **Patchright**: For browser automation testing

## 🚀 Quick Start

### 1. Setup Environment

```bash
cd esp32-display-qemu-demo

# Activate environment
source .env.sh

# First time: install Python venv
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Build Hello World

```bash
# Set ESP32 as target
idf.py set-target esp32

# Compile
idf.py build

# Verify: check build/esp32-display-qemu-demo.elf
ls -lh build/*.elf
```

### 3. Run on QEMU

```bash
# In tmux or terminal
qemu-system-xtensa \
  -machine esp32 \
  -drive file=build/esp32-display-qemu-demo.bin,if=mtd,format=raw \
  -nographic \
  -serial mon:stdio
```

### 4. Watch Serial Output

You should see logs like:
```
I (0) cpu_start: ESP-IDF v5.5.4-dirty 2nd stage bootloader
I (24) boot: Chip is ESP32 (revision v1.0)
...
I (342) app_main: ========================================
I (342) app_main: esp32-display-qemu-demo starting...
I (343) app_main: ========================================
```

## 📁 Project Structure

```
esp32-display-qemu-demo/
├── CMakeLists.txt              # Top-level ESP-IDF build config
├── main/
│   ├── CMakeLists.txt         # Main component build config
│   ├── main.c                 # Application entry point
│   └── include/               # Header files
├── frontend/
│   ├── index.html             # Web interface (future)
│   └── style.css
├── tools/
│   ├── setup-idf.sh           # ESP-IDF environment setup
│   ├── build-script.sh        # Build automation
│   └── qemu-run.sh            # QEMU execution helper
├── tests/
│   ├── test_serial.py         # Serial output validation
│   └── test_qemu.py           # QEMU integration tests
├── docs/
│   └── daily-logs/            # Daily development logs
├── build/                      # Generated build artifacts
├── .env.sh                     # Environment loader
├── sdkconfig                   # Current build config
├── sdkconfig.defaults          # Default configuration
└── README.md                   # This file
```

## 🛠️ Development Workflow

### Daily Development Loop

```bash
# 1. Start tmux session
tmux attach-session -t esp32-display-qemu-demo

# 2. In 'edit' window: modify code
# 3. In 'build' window: compile
idf.py build

# 4. In 'monitor' window: run QEMU and monitor
qemu-system-xtensa -machine esp32 -drive file=build/*.bin,if=mtd -nographic -serial mon:stdio

# 5. Check output for errors/logs
```

### Build Commands

```bash
# Clean rebuild
idf.py fullclean
idf.py build

# Configure with menuconfig
idf.py menuconfig

# Set different target
idf.py set-target esp32s3

# Monitor serial output
idf.py monitor
```

## 📊 Milestones

| Milestone | Status | Objectives |
|-----------|--------|-----------|
| M1: Environment | 🔄 In Progress | ✅ Setup ESP-IDF, ✅ Create Hello World, ✅ Initialize tmux |
| M2: LVGL Integration | ⏳ Pending | Add LVGL component, configure display, compile |
| M3: LVGL Demo | ⏳ Pending | Integrate demo app, render on QEMU, create startup script |
| M4: Testing & Docs | ⏳ Pending | Automated tests, code refactor, finalize documentation |

## 🧪 Testing

### Serial Output Verification

```bash
# Test: Wait for specific log message
idf.py monitor | grep -m 1 "app_main.*started"
```

### Automated Tests

```bash
source .venv/bin/activate

# Run all tests
pytest tests/

# Run specific test
pytest tests/test_qemu.py::test_qemu_boot
```

## 📝 Logging

The application uses ESP-IDF's standard logging system:

```c
#include "esp_log.h"

static const char *TAG = "my_component";

ESP_LOGI(TAG, "Hello %s", "World");   // Info
ESP_LOGW(TAG, "Warning message");      // Warning
ESP_LOGE(TAG, "Error occurred");       // Error
```

### Log Levels

Set in menuconfig: `Component config` → `Log output` → `Default log verbosity`

- **Error**: Only errors (minimal output)
- **Warn**: Warnings and errors
- **Info**: General info (default)
- **Debug**: Detailed debugging
- **Verbose**: Maximum detail

## 🐛 Troubleshooting

### Build Fails: "esp_log not found"

**Solution**: Ensure CMakeLists.txt doesn't explicitly require unavailable components.

```cmake
# ❌ WRONG
idf_component_register(REQUIRES esp_log esp_system)

# ✅ CORRECT - Let ESP-IDF link automatic deps
idf_component_register()
```

### QEMU Not Found

```bash
# Check QEMU installation
which qemu-system-xtensa
qemu-system-xtensa --version

# Install QEMU
brew install qemu  # macOS
apt install qemu-system-misc  # Linux
```

### Python Module Not Found

```bash
# Ensure venv is activated
source .venv/bin/activate

# Reinstall requirements
pip install -r requirements.txt
```

## 📚 Resources

- [ESP-IDF Documentation](https://docs.espressif.com/projects/esp-idf/en/latest/)
- [LVGL Documentation](https://docs.lvgl.io/)
- [QEMU Xtensa Support](https://wiki.qemu.org/System/Targets/Xtensa)
- [ESP32 Datasheet](https://www.espressif.com/sites/default/files/documentation/esp32_datasheet_en.pdf)

## 📜 License

This project is part of the ESP32-QEMU learning initiative. See LICENSE file for details.

## 📞 Support

For issues or questions:

1. Check daily logs in `docs/daily-logs/`
2. Review troubleshooting section above
3. Consult ESP-IDF documentation
4. Check QEMU emulator documentation

---

**Last Updated**: 2026-04-29  
**Status**: Active Development (M1 in progress)
