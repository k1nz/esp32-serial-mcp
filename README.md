# esp32-serial-mcp

> 🌐 **中文(默认)** | [**English**](README.en.md)

ESP32 串口调试工具的最小 stdio MCP server + CLI,解决在 Claude Code 等非交互环境里
`pio device monitor` 不可用(`termios.error`)的问题。

提供 4 个 MCP 工具:

| 工具 | 说明 |
| ---- | ---- |
| `esp32_list_devices` | 列出本机 USB 串口设备(ESP32 板子显示为 `/dev/cu.usbmodem*`) |
| `esp32_chip_id` | 用 esptool 识别芯片型号(ESP32-S3 vs ESP32-C3),结束时硬复位回 app 模式 |
| `esp32_capture` | 抓取串口输出 N 秒(默认先复位抓全新启动日志;`esptool_reset=true` 可救冻死板子) |
| `esp32_reset` | DTR/RTS 脉冲硬复位进 app 模式(从卡死/冻结恢复) |

## 依赖

只需要 PlatformIO venv 里的 python(自带 pyserial),零额外安装:

```sh
~/.platformio/penv/bin/python esp32_mcp_server.py   # MCP server
~/.platformio/penv/bin/python capture_serial.py     # CLI 抓取
```

> 若 pyserial 不在你的 python 里:`pip install pyserial`。

## CLI 用法

```sh
# 自动找端口,复位后抓 30 秒
~/.platformio/penv/bin/python capture_serial.py

# 显式端口 / 时长 / 输出文件(流式写入,长抓取配合 run_in_background + 轮询文件)
~/.platformio/penv/bin/python capture_serial.py --port /dev/cu.usbmodem14701 --seconds 120 --out /tmp/boot.log

# 先 esptool 复位(救回冻死设备)再抓取
~/.platformio/penv/bin/python capture_serial.py --esptool-reset --seconds 60

# 识别芯片型号
~/.platformio/penv/bin/python capture_serial.py --chip-id
```

## MCP 注册

在项目根目录 `.mcp.json`(或 `~/.claude.json` 的 `mcpServers`)加入:

```json
{
  "mcpServers": {
    "esp32-serial": {
      "command": "<你的 python 路径,如 /Users/you/.platformio/penv/bin/python>",
      "args": ["<本仓库绝对路径>/esp32_mcp_server.py"]
    }
  }
}
```

本仓库自带的 `.mcp.json` 已填好当前机器的路径;换机器/路径时改一下即可。
Claude Code 连接后,直接调 `esp32_capture` 等工具即可,无需复刻复位序列等细节。

## 设计要点

- **为什么抓取前要复位**:`open` 串口会把原生 USB 的 ESP32 带进下载模式;工具随后用
  DTR/RTS 脉冲(`DTR=False; RTS=True→False`)把芯片拉回 app 模式,输出完整启动日志。
- **冻死设备**:若 loop() 卡死,esptool 的复位比裸 pyserial 复位可靠,用 `--esptool-reset` 先救。
- **注意**:arduino-esp32 的 loop 任务看门狗默认关闭(`enableLoopWDT()` 不会被核心调用),
  所以 loop() 阻塞会永久冻结而不重启。固件侧建议在 setup 末尾调用
  `esp_task_wdt_init(70, true); enableLoopWDT();` 自恢复。
- 协议:newline-delimited JSON-RPC 2.0 over stdin/stdout(MCP stdio transport),手写实现,
  除 pyserial 外零依赖。
