#!/usr/bin/env python3
"""ESP32 串口工具 —— 最小 stdio MCP server（除 pyserial 外零依赖）

用 PlatformIO venv 的 python 运行（自带 pyserial）：
    ~/.platformio/penv/bin/python tools/esp32_mcp_server.py

在 .mcp.json 注册后，Claude Code 可直接调用这些工具，不用再复刻抓取日志的
复位序列/路径等细节：
    esp32_list_devices / esp32_chip_id / esp32_capture / esp32_reset

协议：newline-delimited JSON-RPC 2.0 over stdin/stdout（MCP stdio transport）。
复用 tools/capture_serial.py 的 find_port / reset_into_app 与 esptool 路径常量。
"""

import glob
import json
import os
import subprocess
import sys
import time

import serial

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import capture_serial as cs  # noqa: E402  复用端口探测 / 复位序列 / esptool 路径

PROTOCOL_VERSION = "2024-11-05"


def respond(msg_id, result):
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": result}) + "\n")
    sys.stdout.flush()


def respond_error(msg_id, code, message):
    sys.stdout.write(json.dumps(
        {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}) + "\n")
    sys.stdout.flush()


# ── 工具实现 ──────────────────────────────────────────────────────

def tool_list_devices(args):
    cands = (glob.glob("/dev/cu.usbmodem*")
             + glob.glob("/dev/cu.wchusbserial*")
             + glob.glob("/dev/cu.usbserial*"))
    return "\n".join(cands) if cands else "No USB serial device found under /dev/cu.*"


def tool_chip_id(args):
    port = args.get("port") or cs.find_port()
    try:
        r = subprocess.run(
            [cs.PENV_PYTHON, cs.ESPTOOL, "--port", port, "--after", "hard_reset",
             "--baud", "460800", "chip_id"],
            capture_output=True, text=True, timeout=90)
    except subprocess.TimeoutExpired:
        return f"esptool chip_id timed out on {port}"
    out = (r.stdout or "") + (r.stderr or "")
    # 只保留关键行：芯片型号 / MAC / 复位结果
    keep = [l for l in out.splitlines()
            if any(k in l for k in ("Detecting chip", "Chip is", "MAC:", "Hard resetting", "Connection", "Serial port"))]
    return f"port: {port}\n" + "\n".join(keep) if keep else out


def tool_capture(args):
    port = args.get("port") or cs.find_port()
    seconds = float(args.get("seconds", 20))
    do_reset = bool(args.get("reset", True))
    esptool_reset = bool(args.get("esptool_reset", False))

    if esptool_reset:
        # esptool 复位能救回“冻死”的芯片；随后 open 会打断，再用 reset 序列拉回 app 模式
        subprocess.run(
            [cs.PENV_PYTHON, cs.ESPTOOL, "--port", port, "--after", "hard_reset",
             "--baud", "460800", "chip_id"],
            capture_output=True, text=True, timeout=90)

    ser = serial.Serial(port, 115200, timeout=0.3)
    time.sleep(0.2)
    if do_reset:
        cs.reset_into_app(ser)

    buf = []
    start = time.time()
    while time.time() - start < seconds:
        data = ser.read(4096)
        if data:
            buf.append(data.decode("utf-8", errors="replace"))
    ser.close()

    text = "".join(buf)
    if not text:
        return (f"No serial output in {seconds:.0f}s on {port}. "
                f"Device may be in download mode — retry with esptool_reset=true.")
    return text


def tool_reset(args):
    port = args.get("port") or cs.find_port()
    ser = serial.Serial(port, 115200, timeout=0.3)
    cs.reset_into_app(ser)
    ser.close()
    return f"Reset into app mode sent on {port} (chip should emit a fresh boot log)."


# ── 工具注册表 ────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "esp32_list_devices",
        "description": "List USB serial devices on this Mac (ESP32 usage boards appear as /dev/cu.usbmodem*).",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "esp32_chip_id",
        "description": "Identify the connected ESP32 chip (ESP32-S3 vs ESP32-C3) via esptool. Ends by hard-resetting the board into app mode.",
        "inputSchema": {"type": "object",
                        "properties": {"port": {"type": "string", "description": "Serial port; default auto-detect"}},
                        "required": []},
    },
    {
        "name": "esp32_capture",
        "description": ("Capture serial output for N seconds (boot log / runtime logs). "
                        "By default resets the board into app mode first so a fresh boot log is captured. "
                        "Use esptool_reset=true to recover a frozen (hung loop) board."),
        "inputSchema": {"type": "object",
                        "properties": {
                            "seconds": {"type": "number", "description": "Capture duration in seconds", "default": 20},
                            "port": {"type": "string", "description": "Serial port; default auto-detect"},
                            "reset": {"type": "boolean", "description": "Pulse DTR/RTS reset before capturing", "default": True},
                            "esptool_reset": {"type": "boolean", "description": "Recover a frozen board via esptool first", "default": False},
                        },
                        "required": []},
    },
    {
        "name": "esp32_reset",
        "description": "Hard-reset the board into app mode via DTR/RTS pulse (recover from a hung/frozen loop).",
        "inputSchema": {"type": "object",
                        "properties": {"port": {"type": "string", "description": "Serial port; default auto-detect"}},
                        "required": []},
    },
]

HANDLERS = {
    "esp32_list_devices": tool_list_devices,
    "esp32_chip_id": tool_chip_id,
    "esp32_capture": tool_capture,
    "esp32_reset": tool_reset,
}


# ── JSON-RPC 分发 ─────────────────────────────────────────────────

def handle_call(msg_id, params):
    name = (params or {}).get("name")
    args = (params or {}).get("arguments") or {}
    handler = HANDLERS.get(name)
    if not handler:
        respond_error(msg_id, -32602, f"Unknown tool: {name}")
        return
    try:
        text = handler(args)
        respond(msg_id, {"content": [{"type": "text", "text": str(text)}]})
    except Exception as e:  # noqa: BLE001 工具错误要回给客户端，不能崩掉 server
        respond_error(msg_id, -32603, f"{name} failed: {e}")


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg_id = msg.get("id")
        method = msg.get("method")
        params = msg.get("params") or {}

        if method == "initialize":
            requested = params.get("protocolVersion", PROTOCOL_VERSION)
            respond(msg_id, {
                "protocolVersion": requested,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "esp32-serial", "version": "0.1.0"},
            })
        elif method in ("notifications/initialized", "notifications/cancelled"):
            continue  # 通知无需响应
        elif method == "ping":
            respond(msg_id, {})
        elif method == "tools/list":
            respond(msg_id, {"tools": TOOLS})
        elif method == "tools/call":
            handle_call(msg_id, params)
        elif method is None:
            respond_error(msg_id, -32600, "Invalid Request")
        else:
            respond_error(msg_id, -32601, f"Method not found: {method}")


if __name__ == "__main__":
    main()
