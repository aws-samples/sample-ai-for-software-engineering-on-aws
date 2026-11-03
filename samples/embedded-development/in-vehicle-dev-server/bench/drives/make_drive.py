#!/usr/bin/env python3
# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Writes the recorded drive of the replay (build plan item 3). Synthetic, written for the sample.

The drive is described in VSS terms: the value of each published signal path over time. Each value is turned into a
CAN frame through knowledge/vss-mapping.yaml and knowledge/cc1-gateway.dbc (cantools), so the frames always agree with
the DBC and every value is inside the signal's range unless it is meant not to be.

    make_drive.py [--out drives/drive-01.rec]

The timing serves the seeded difficulties (rehearsal/facilitator-notes.md) and is the bench's half of the interface
with the reference project:
- every message's first frame comes 150 ms to 1.0 s after the gateway connects, inside 100 ms to 1.5 s and before the
  2.0 s start-up grace period ends (VSTATD-IF p.7 §4.2), so the baseline has no SIGNAL_TIMEOUT at start-up;
- after one gateway loss and reconnection, BCM_Exterior (timeout 3 s) stays silent for 7 s, longer than the grace
  period plus its timeout, so the baseline has one SIGNAL_TIMEOUT and SIGNAL_RECOVERED after the grace period.
Requires cantools and PyYAML.
"""
import argparse
import hashlib
import pathlib

import cantools
import yaml

HERE = pathlib.Path(__file__).resolve().parent
KNOWLEDGE = HERE.parent.parent / "knowledge"

# Two connections: 20 s, a gateway loss (the player closes the socket), then 16 s and the end of the drive.
SEGMENTS = [20_000, 16_000]
# First frame of each message after a connection is accepted, in ms.
FIRST = {0x100: 150, 0x101: 200, 0x102: 250, 0x103: 300, 0x200: 400, 0x300: 500, 0x301: 600, 0x400: 800,
         0x401: 1000}
FIRST_AFTER_RECONNECT = {**FIRST, 0x401: 7000}


def ramp(t, t0, v0, t1, v1):
    if t <= t0:
        return v0
    if t >= t1:
        return v1
    return v0 + (v1 - v0) * (t - t0) / (t1 - t0)


def blinking(t, start, end):
    return start <= t < end and int((t - start) / 0.5) % 2 == 0


def speed(seg, t):
    return ramp(t, 4.0, 0.0, 12.0, 60.0) if seg == 0 else ramp(t, 8.0, 60.0, 14.0, 0.0)


def distance_m(seg, t):
    """Odometer: 12 345.6 km plus the integral of the speed profile, in whole 100 m."""
    total = 0.0
    step = 0.01
    for s, length in enumerate(SEGMENTS):
        end = t if s == seg else length / 1000
        x = 0.0
        while x < end:
            total += speed(s, x) / 3.6 * step
            x += step
        if s == seg:
            break
    return 12_345_600 + int(total // 100) * 100


def vss_values(seg, t):
    """The value of every signal path at time t (seconds since the connection was accepted)."""
    v = speed(seg, t)
    parked = (seg == 0 and t < 2.0) or (seg == 1 and t >= 15.0)
    dist = distance_m(seg, t)
    return {
        "Vehicle.LowVoltageSystemState": "ON",
        "Vehicle.LowVoltageBattery.CurrentVoltage": 13.5 if (seg == 0 and t < 3.0) else 14.1,
        "Vehicle.Speed": round(v, 2),
        "Vehicle.Powertrain.Transmission.CurrentGear": 0 if parked else 1 + min(int(v / 15), 5),
        "Vehicle.Powertrain.Transmission.SelectedGear": 126 if parked else 127,
        "Vehicle.Chassis.ParkingBrake.IsEngaged": (seg == 0 and t < 2.0) or (seg == 1 and t >= 15.2),
        "Vehicle.TraveledDistance": dist,
        "Vehicle.Powertrain.TractionBattery.StateOfCharge.Displayed":
            80.0 if seg == 0 and t < 16.0 else (79.5 if seg == 0 or t < 10.0 else 79.0),
        "Vehicle.Powertrain.Range": 300_000 - (dist - 12_345_600) // 1000 * 1000,
        "Vehicle.Powertrain.TractionBattery.Charging.IsCharging": False,
        "Vehicle.Body.Lights.Beam.Low.IsOn": not (seg == 0 and t < 3.0),
        "Vehicle.Body.Lights.Beam.High.IsOn": False,
        "Vehicle.Body.Lights.DirectionIndicator.Left.IsSignaling": seg == 0 and blinking(t, 13.0, 15.0),
        "Vehicle.Body.Lights.DirectionIndicator.Right.IsSignaling": seg == 1 and blinking(t, 9.0, 11.0),
        "Vehicle.Body.Lights.Hazard.IsSignaling": False,
        "Vehicle.Cabin.Door.Row1.DriverSide.IsOpen": seg == 0 and t < 1.2,
        "Vehicle.Cabin.Door.Row1.PassengerSide.IsOpen": False,
        "Vehicle.Body.Trunk.Rear.IsOpen": False,
        "Vehicle.Cabin.Seat.Row1.DriverSide.IsBelted": not ((seg == 0 and t < 1.6) or (seg == 1 and t >= 15.5)),
        "Vehicle.Chassis.Axle.Row1.Wheel.Left.Tire.Pressure": 226 if (seg == 1 and t >= 6.0) else 230,
        "Vehicle.Chassis.Axle.Row1.Wheel.Right.Tire.Pressure": 230,
        "Vehicle.Chassis.Axle.Row2.Wheel.Left.Tire.Pressure": 224,
        "Vehicle.Chassis.Axle.Row2.Wheel.Right.Tire.Pressure": 224,
        "Vehicle.Exterior.AirTemperature": 20.0 if seg == 0 else 21.5,
    }


def to_signal_value(entry, value):
    """VSS value -> the value cantools encodes (physical, or the raw code of an enumeration or flag)."""
    mapping = entry.get("map")
    if mapping:
        inverse = {str(v).lower() if isinstance(v, bool) else str(v): int(k) for k, v in mapping.items()}
        key = str(value).lower() if isinstance(value, bool) else str(value)
        return inverse[key]
    return value


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(HERE / "drive-01.rec"))
    args = ap.parse_args()

    db = cantools.database.load_file(str(KNOWLEDGE / "cc1-gateway.dbc"))
    mapping = yaml.safe_load((KNOWLEDGE / "vss-mapping.yaml").read_text())["signals"]
    by_message = {}
    for path, entry in mapping.items():
        by_message.setdefault(entry["dbc_message"], []).append((path, entry))

    lines = [
        "# cc1 recorded drive 01: synthetic, generated by bench/drives/make_drive.py; do not edit by hand.",
        "# Sources: knowledge/cc1-gateway.dbc, knowledge/vss-mapping.yaml (VSS v6.1 names). Format: bench/player/cc1-bench.cpp.",
    ]
    for m in db.messages:
        lines.append(f"CYCLE {m.frame_id:X} {m.cycle_time}")
    for seg, length in enumerate(SEGMENTS):
        first = FIRST if seg == 0 else FIRST_AFTER_RECONNECT
        events = []
        for m in db.messages:
            t_ms = first[m.frame_id]
            while t_ms < length:
                values = vss_values(seg, t_ms / 1000)
                data = {e["dbc_signal"]: to_signal_value(e, values[p]) for p, e in by_message[m.name]}
                payload = m.encode(data, scaling=True, strict=True)
                events.append((t_ms, m.frame_id, f"F {t_ms * 1000} {m.frame_id:X} {m.length} {payload.hex().upper()}"))
                t_ms += m.cycle_time
        events.sort()
        lines.append(f"# connection {seg + 1}: {length} ms")
        lines.extend(e[2] for e in events)
        lines.append(f"{'DROP' if seg + 1 < len(SEGMENTS) else 'END'} {length * 1000}")
    text = "\n".join(lines) + "\n"
    pathlib.Path(args.out).write_text(text)
    print(f"{args.out}: {sum(1 for l in lines if l.startswith('F '))} frames, "
          f"sha256 {hashlib.sha256(text.encode()).hexdigest()}")


if __name__ == "__main__":
    main()
