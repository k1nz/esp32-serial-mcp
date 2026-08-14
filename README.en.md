# esp32-serial-mcp

> 🌐 [**中文**](README.md) | **English**

A minimal stdio MCP server + CLI for debugging ESP32 over serial, solving the
`termios.error` problem that makes `pio device monitor` unusable in
non-interactive environments like Claude Code.

Provides 4 MCP tools:

| Tool | Description |
| ---- | ----------- |
| `esp32_list_devices` | List local USB serial devices (ESP32 boards show up as `/dev/cu.usbmodem*`) |
| `esp32_chip_id` | Identify the chip model via esptool (ESP32-S3 vs ESP32-C3); hard-resets back to app mode when done |
| `esp32_capture` | Capture serial output for N seconds (resets first by default to grab a fresh boot log; `esptool_reset=true` can revive a hung board) |
| `esp32_reset` | DTR/RTS pulse hard-reset into app mode (recover from hangs/freezes) |

## Dependencies

Only the Python from the PlatformIO venv is needed (it ships with pyserial) —
zero extra installs:

```sh
~/.platformio/penv/bin/python esp32_mcp_server.py   # MCP server
~/.platformio/penv/bin/python capture_serial.py     # CLI capture
```

> If pyserial is missing from your Python: `pip install pyserial`.

## CLI Usage

```sh
# Auto-detect the port, reset, then capture 30 seconds
~/.platformio/penv/bin/python capture_serial.py

# Explicit port / duration / output file (streamed writes; pair long captures
# with run_in_background + polling the file)
~/.platformio/penv/bin/python capture_serial.py --port /dev/cu.usbmodem14701 --seconds 120 --out /tmp/boot.log

# Reset via esptool first (revives a hung board), then capture
~/.platformio/penv/bin/python capture_serial.py --esptool-reset --seconds 60

# Identify the chip model
~/.platformio/penv/bin/python capture_serial.py --chip-id
```

## MCP Registration

Add the following to `.mcp.json` in your project root (or the `mcpServers` key
of `~/.claude.json`):

```json
{
  "mcpServers": {
    "esp32-serial": {
      "command": "<your python path, e.g. /Users/you/.platformio/penv/bin/python>",
      "args": ["<absolute path to this repo>/esp32_mcp_server.py"]
    }
  }
}
```

The `.mcp.json` shipped in this repo already contains the path for the current
machine; adjust it when moving machines/paths. Once Claude Code connects, just
call tools like `esp32_capture` — no need to replicate the reset sequence
yourself.

## Design Notes

- **Why reset before capturing**: `open`-ing the serial port puts native-USB
  ESP32s into download mode; the tool then uses a DTR/RTS pulse
  (`DTR=False; RTS=True→False`) to pull the chip back into app mode and capture
  the full boot log.
- **Hung boards**: if `loop()` blocks, an esptool reset is more reliable than a
  bare pyserial reset — use `--esptool-reset` first.
- **Note**: arduino-esp32 leaves the loop-task watchdog disabled by default
  (`enableLoopWDT()` is never called by the core), so a blocked `loop()`
  freezes the board permanently without restarting. On the firmware side, call
  `esp_task_wdt_init(70, true); enableLoopWDT();` at the end of `setup()` for
  self-recovery.
- **Protocol**: newline-delimited JSON-RPC 2.0 over stdin/stdout (MCP stdio
  transport), hand-written implementation, zero dependencies beyond pyserial.
