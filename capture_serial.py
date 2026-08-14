#!/usr/bin/env python3
"""ESP32 串口日志抓取工具（替代 pio device monitor）

背景：`pio device monitor` 需要 TTY 终端，在 Claude Code 等非交互/后台 shell 里会报
`termios.error: (19, 'Operation not supported by device')`。本工具用 pyserial 直接读写，
并复刻了验证过可靠的复位序列（open 会打断设备，随后 DTR/RTS 脉冲把它拉回 app 模式）。

依赖 PlatformIO venv 的 python（自带 pyserial）：
    ~/.platformio/penv/bin/python tools/capture_serial.py ...

用法：
    # 自动找 /dev/cu.usbmodem* 端口，复位后抓 30 秒
    ~/.platformio/penv/bin/python tools/capture_serial.py

    # 显式端口 / 时长 / 输出文件（流式写入，长抓取用 run_in_background + 轮询文件）
    ~/.platformio/penv/bin/python tools/capture_serial.py \
        --port /dev/cu.usbmodem14701 --seconds 120 --out /tmp/boot.log

    # 先 esptool 复位（能救回“冻死”的设备），再打开抓取
    ~/.platformio/penv/bin/python tools/capture_serial.py --esptool-reset --seconds 60

    # 只识别芯片型号（S3 vs C3），不改动设备状态以外（esptool chip_id 结束时硬复位）
    ~/.platformio/penv/bin/python tools/capture_serial.py --chip-id

    # 不复位，直接读（抓取期间会打断设备进下载模式，一般要用 --reset 配合）
    ~/.platformio/penv/bin/python tools/capture_serial.py --no-reset

串口波特率：两个 usage 应用都是 115200（monitor_speed）。
"""

import argparse
import glob
import os
import subprocess
import sys
import time

import serial

PENV_PYTHON = os.path.expanduser("~/.platformio/penv/bin/python")
ESPTOOL = os.path.expanduser("~/.platformio/packages/tool-esptoolpy/esptool.py")
DEFAULT_BAUD = 115200


def find_port():
    """返回第一个候选 USB 串口，找不到则退出。"""
    candidates = (
        glob.glob("/dev/cu.usbmodem*")
        + glob.glob("/dev/cu.wchusbserial*")
        + glob.glob("/dev/cu.usbserial*")
    )
    if not candidates:
        sys.exit("No USB serial device found (looked for /dev/cu.usbmodem*|usbserial*)")
    return candidates[0]


def esptool_run(port, *args):
    """跑 esptool 子命令；统一 --after hard_reset，结束时把设备复位回 app 模式。"""
    cmd = [PENV_PYTHON, ESPTOOL, "--port", port, "--after", "hard_reset", "--baud", "460800"]
    cmd += list(args)
    print(f"esptool: {' '.join(cmd)}", flush=True)
    subprocess.run(cmd, check=False)


def reset_into_app(ser):
    """验证过的复位序列：IO0 拉高（DTR False），RTS 脉冲 EN。

    open 端口常把原生 USB 的 ESP32 带进下载模式，这个序列把它拉回 app 模式，
    随后会输出完整启动日志。
    """
    ser.setDTR(False)
    time.sleep(0.1)
    ser.setRTS(True)
    time.sleep(0.2)
    ser.setRTS(False)
    time.sleep(0.3)


def capture(port, seconds, out_path, do_reset):
    """打开端口、可选复位、流式读取 seconds 秒，增量写 out_path（None 则打 stdout）。"""
    out = open(out_path, "w", buffering=1) if out_path else None
    ser = serial.Serial(port, DEFAULT_BAUD, timeout=0.3)
    time.sleep(0.2)
    if do_reset:
        reset_into_app(ser)

    start = time.time()
    while time.time() - start < seconds:
        data = ser.read(4096)
        if data:
            t = time.time() - start
            line = f"[t={t:6.1f}s] " + data.decode("utf-8", errors="replace")
            if out:
                out.write(line)
            else:
                sys.stdout.write(line)
                sys.stdout.flush()
    ser.close()
    if out:
        out.close()
    print(f"\n=== capture done ({seconds}s) ===", flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", default=None, help="串口路径；缺省自动探测")
    ap.add_argument("--seconds", type=float, default=30.0, help="抓取时长（秒）")
    ap.add_argument("--out", default=None, help="输出文件（增量写入；不传则打 stdout）")
    ap.add_argument("--reset", dest="do_reset", action="store_true", default=True,
                    help="先复位进 app 模式再抓取（默认）")
    ap.add_argument("--no-reset", dest="do_reset", action="store_false",
                    help="不复位直接读")
    ap.add_argument("--esptool-reset", action="store_true",
                    help="抓取前先用 esptool 硬复位（可救回冻死设备）")
    ap.add_argument("--chip-id", action="store_true",
                    help="只识别芯片型号（esptool chip_id），然后结束")
    args = ap.parse_args()

    port = args.port or find_port()
    print(f"port: {port}")

    if args.chip_id:
        esptool_run(port, "chip_id")
        return

    if args.esptool_reset:
        # 先 esptool 复位（可靠，能救冻死设备），再打开抓取（打开会再打断，
        # 所以抓取仍带 --reset 序列把设备拉回 app 模式）。
        esptool_run(port, "chip_id")

    capture(port, args.seconds, args.out, args.do_reset)


if __name__ == "__main__":
    main()
