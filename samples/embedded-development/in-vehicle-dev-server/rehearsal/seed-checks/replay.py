#!/usr/bin/env python3
# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Tiny host replayer for the seed checks: plays cc1-gwd for a host build of vstatd.

Not the bench's drive player (build plan item 3). It starts vstatd with its sockets in a temporary directory, sends a
short synthetic record stream in real time and reports the runtime log and the peak memory of the process.

    replay.py --vstatd build/vstatd --scenario drive --clients 16 --log run.jsonl

Scenarios:
  drive  every message at its cycle time for --seconds; the first frames come 200 ms after the connection
  demo   drive, plus a pause of VCU_Speed (timeout and recovery), an out-of-range speed (INVALID), a bad record, a
         short frame, a gateway loss and a reconnection, and one app that sends GET, LIST and erroneous requests

Prints one JSON object: counts of each log event, VmHWM in KiB (host), the exit status and the app's answers.
"""

import argparse
import json
import os
import pathlib
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time

# CAN ID, cycle in ms (VSTATD-IF §3.2).
MESSAGES = [(0x100, 100), (0x101, 20), (0x102, 50), (0x103, 1000), (0x200, 100), (0x300, 100), (0x301, 100),
            (0x400, 1000), (0x401, 1000)]
SUBSCRIBED = ["Vehicle.Speed", "Vehicle.Powertrain.Transmission.SelectedGear",
              "Vehicle.Powertrain.TractionBattery.StateOfCharge.Displayed", "Vehicle.Exterior.AirTemperature"]


def payload(can_id, t, speed_raw=None):
    """Eight data bytes as hex for a message at time t (seconds since the drive started)."""
    b = [0] * 8
    if can_id == 0x100:
        b[0] = 4                      # ON
        v = 675                       # 13.50 V
        b[1], b[2] = v & 0xFF, v >> 8
    elif can_id == 0x101:
        v = speed_raw if speed_raw is not None else min(int(t * 1000), 5000)  # 0 to 50 km/h
        b[0], b[1] = v & 0xFF, v >> 8
    elif can_id == 0x102:
        b[0], b[1], b[2] = 1, 127, 0  # gear 1, drive, brake off
    elif can_id == 0x103:
        v = 123456 + int(t * 10)
        b[0], b[1], b[2] = v & 0xFF, (v >> 8) & 0xFF, v >> 16
    elif can_id == 0x200:
        b[0] = 160                    # 80.0 percent
        v = 30000                     # 300 km
        b[1], b[2] = v & 0xFF, v >> 8
        b[3] = 0
    elif can_id == 0x300:
        b[0] = 0b00000001             # low beam on
    elif can_id == 0x301:
        b[0] = 0b01000000             # doors closed, trunk closed, driver belted
    elif can_id == 0x400:
        b[0:4] = [115, 115, 112, 112]  # 230, 230, 224, 224 kPa
    elif can_id == 0x401:
        b[0] = 120                    # 20.0 Celsius
    return "".join(f"{x:02X}" for x in b)


class Gateway:
    def __init__(self, path):
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.listener.bind(path)
        self.listener.listen(4)
        self.conn = None
        self.lock = threading.Lock()

    def accept(self, timeout=10.0):
        self.listener.settimeout(timeout)
        conn, _ = self.listener.accept()
        with self.lock:
            self.conn = conn

    def send(self, text):
        with self.lock:
            if self.conn is not None:
                try:
                    self.conn.sendall(text.encode())
                except OSError:
                    pass

    def drop(self):
        with self.lock:
            if self.conn is not None:
                self.conn.close()
                self.conn = None


class App(threading.Thread):
    """One cockpit app: sends its requests and keeps reading so that its queue never fills."""

    def __init__(self, path, requests):
        super().__init__(daemon=True)
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(path)
        self.sock.sendall("".join(r + "\n" for r in requests).encode())
        self.lines = []
        self.stop = False

    def run(self):
        buf = b""
        self.sock.settimeout(0.2)
        while not self.stop:
            try:
                data = self.sock.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            if not data:
                break
            buf += data
            *done, buf = buf.split(b"\n")
            self.lines.extend(x.decode() for x in done)

    def close(self):
        self.stop = True
        self.sock.close()


def drive(gw, seconds, t0, pause=None, invalid_at=None):
    """Sends every message at its cycle and a heartbeat every 100 ms, until `seconds` after t0."""
    start = time.monotonic() - t0
    due = {cid: start for cid, _ in MESSAGES}
    hb = start
    while True:
        t = time.monotonic() - t0
        if t >= seconds:
            return
        for cid, cycle in MESSAGES:
            if t >= due[cid]:
                due[cid] += cycle / 1000.0
                if cid == 0x101 and pause and pause[0] <= t < pause[1]:
                    continue
                raw = 30001 if (cid == 0x101 and invalid_at and invalid_at <= t < invalid_at + 0.02) else None
                gw.send(f"F {int(t * 1e6)} {cid:X} 8 {payload(cid, t, raw)}\n")
        if t >= hb:
            hb += 0.1
            gw.send(f"H {int(t * 1e6)}\n")
        time.sleep(0.002)


def wait_for(path, text, timeout):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if path.exists() and text in path.read_text():
            return True
        time.sleep(0.01)
    return False


def vm_hwm_kib(pid):
    for line in pathlib.Path(f"/proc/{pid}/status").read_text().splitlines():
        if line.startswith("VmHWM:"):
            return int(line.split()[1])
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--vstatd", required=True)
    ap.add_argument("--scenario", choices=("drive", "demo"), default="drive")
    ap.add_argument("--clients", type=int, default=0)
    ap.add_argument("--seconds", type=float, default=3.0)
    ap.add_argument("--log", default=None, help="copy of the runtime log")
    args = ap.parse_args()

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="vstatd-replay-"))
    gw_path, ipc_path, log_path = tmp / "can.sock", tmp / "vstatd.sock", tmp / "run.jsonl"
    gw = Gateway(str(gw_path))
    env = dict(os.environ, VSTATD_GATEWAY_SOCKET=str(gw_path), VSTATD_IPC_SOCKET=str(ipc_path))
    with open(log_path, "w") as out:
        proc = subprocess.Popen([args.vstatd], stdout=out, stderr=subprocess.STDOUT, env=env)
    if not wait_for(log_path, '"SERVICE_READY"', 5):
        proc.kill()
        raise SystemExit("vstatd did not get ready")
    apps = [App(str(ipc_path), [f"SUB {p} 100" for p in SUBSCRIBED]) for _ in range(args.clients)]
    for a in apps:
        a.start()
    gw.accept()
    t0 = time.monotonic()
    time.sleep(0.2)  # the first frames come 200 ms after the connection
    answers = []
    if args.scenario == "drive":
        drive(gw, args.seconds, t0)
    else:
        drive(gw, 1.0, t0)
        tester = App(str(ipc_path), ["GET Vehicle.Speed", "SUB Vehicle.Speed 50", "LIST", "FOO", "SUB Vehicle.Speed 10",
                                     "GET Vehicle.Unknown", "UNSUB Vehicle.Speed"])
        tester.start()
        drive(gw, 1.6, t0, pause=(1.2, 1.4), invalid_at=1.5)
        gw.send("this is not a record\nF 1 101 2 C409\n")
        drive(gw, 1.8, t0)
        gw.drop()                     # gateway loss (closed)
        gw.accept()                   # vstatd reconnects after 100 ms
        t1 = time.monotonic()
        time.sleep(0.2)
        drive(gw, 0.6, t1)
        tester.close()
        answers = tester.lines
    hwm = vm_hwm_kib(proc.pid)
    proc.send_signal(signal.SIGTERM)
    status = proc.wait(timeout=5)
    for a in apps:
        a.close()
    events = {}
    lines = log_path.read_text().splitlines()
    for line in lines:
        ev = json.loads(line)["ev"]
        events[ev] = events.get(ev, 0) + 1
    if args.log:
        pathlib.Path(args.log).write_text("\n".join(lines) + "\n")
    print(json.dumps({"events": events, "vm_hwm_kib_host": hwm, "exit_status": status, "clients": args.clients,
                      "app_answers": answers}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
