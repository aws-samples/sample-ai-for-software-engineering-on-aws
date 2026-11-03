#!/usr/bin/env python3
# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""The operator console of the bench (scenario page, section 4; CC1-PN §8.1, §8.2).

A separate terminal process, outside the agents' tools. A person sees each requested physical action with the digest
of the build it is for, and approves or refuses it; sets the simulated supply and ignition; and reconciles the target
after an interrupted action. Every step goes to the action record.

  console.py                                   interactive
  console.py status [--json]                   supply, target and pending requests
  console.py supply [--voltage V] [--kl15 on|off]
  console.py approve ID --digest PREFIX        PREFIX: at least the first 6 characters of the digest shown
  console.py refuse ID [--reason R]
  console.py reconcile [--yes]                 after checking the target's actual state
  console.py log [-n N]
  console.py scenario FILE                     scripted supply changes: lines "<seconds> voltage <V>" or "<seconds> kl15 on|off"
"""
import argparse
import json
import os
import pathlib
import select
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "lib"))
import benchstate as bs  # noqa: E402

CC1 = os.environ.get("CC1_BENCH_SCRIPT", str(pathlib.Path(__file__).resolve().parent / "cc1.sh"))


def probe():
    out = subprocess.run([CC1, "probe"], capture_output=True, text=True, timeout=120)
    try:
        return json.loads(out.stdout)
    except ValueError:
        return {"probe_error": (out.stderr or out.stdout).strip()[-300:]}


def view():
    s, t = bs.supply(), bs.target()
    lines = [f"CC-1 operator console  ·  state {bs.state_dir()}", ""]
    if s:
        lines.append(f"Supply  {s.get('voltage_v', '?'):>6} V   KL15 {s.get('kl15', '?')}   (set {s.get('set_at')} by {s.get('set_by')})")
    else:
        lines.append("Supply  not set: physical actions are refused")
    lines.append(f"Target  {t['state']}: {t['why']}")
    lines.append("")
    pend = bs.pending()
    if not pend:
        lines.append("No pending requests.")
    for i, r in enumerate(pend, 1):
        left = int(r["expires"] - time.time())
        state = "EXPIRED" if r["expired"] else f"{left} s left"
        lines += [f"[{i}] {r['what']}  ({r['action']}, {state})",
                  f"    digest   {r['digest']}",
                  f"    detail   {r['detail']}",
                  f"    request  {r['id']} from {r['requested_by']} at {r['requested_at']}"]
    lines += ["", "a <n> <digest prefix> approve   r <n> [reason] refuse   v <volts>   k on|off   c reconcile   l log   q quit"]
    return "\n".join(lines), pend


def reconcile(yes=False, by=None):
    t = bs.target()
    if t["state"] == "busy":
        raise bs.GateError(f"an action is still running: {t['why']}")
    facts = probe()
    print(json.dumps(facts, indent=1))
    if not yes:
        if input("Is this the target's actual state, checked by you? Type yes: ").strip() != "yes":
            print("not reconciled")
            return
    state = "known" if facts.get("qemu_running") and facts.get("reachable") else "off"
    by = by or bs.who()
    bs.record("reconcile", by=by, state=state, facts=facts)
    bs.set_target(state, f"reconciled at the operator console by {by}", facts=facts)
    print(f"target {state}")


def scenario(path):
    name = pathlib.Path(path).name
    steps = []
    for n, line in enumerate(pathlib.Path(path).read_text().splitlines(), 1):
        line = line.split("#")[0].strip()
        if not line:
            continue
        t, what, value = line.split()
        steps.append((float(t), what, value))
    t0 = time.monotonic()
    for t, what, value in sorted(steps):
        time.sleep(max(0.0, t0 + t - time.monotonic()))
        if what == "voltage":
            bs.set_supply(voltage=float(value), by=f"scenario {name}")
        elif what == "kl15":
            bs.set_supply(kl15=value, by=f"scenario {name}")
        else:
            raise bs.GateError(f"{name}: unknown step {what}")
        print(f"{t:>6.1f} s  {what} {value}")


def interactive():
    last = None
    while True:
        text, pend = view()
        if text != last:
            print("\033[2J\033[H" + text + "\n> ", end="", flush=True)
            last = text
        ready, _, _ = select.select([sys.stdin], [], [], 1.0)
        if not ready:
            continue
        line = sys.stdin.readline()
        if not line:
            return
        words = line.split()
        try:
            if not words:
                pass
            elif words[0] == "q":
                return
            elif words[0] == "a" and len(words) == 3:
                bs.decide(pend[int(words[1]) - 1]["id"], "approved", bs.who(), digest_prefix=words[2])
            elif words[0] == "r" and len(words) >= 2:
                bs.decide(pend[int(words[1]) - 1]["id"], "refused", bs.who(), " ".join(words[2:]))
            elif words[0] == "v" and len(words) == 2:
                bs.set_supply(voltage=float(words[1]))
            elif words[0] == "k" and len(words) == 2:
                bs.set_supply(kl15=words[1])
            elif words[0] == "c":
                reconcile()
                input("press Enter")
            elif words[0] == "l":
                for e in bs.records()[-20:]:
                    print(json.dumps(e))
                input("press Enter")
            else:
                print("?")
                time.sleep(1)
        except (bs.GateError, IndexError, ValueError) as e:
            print(f"not done: {e}")
            time.sleep(2)
        last = None


def main():
    if len(sys.argv) == 1:
        interactive()
        return 0
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=["status", "supply", "approve", "refuse", "reconcile", "log", "scenario"])
    ap.add_argument("arg", nargs="?")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--voltage", type=float)
    ap.add_argument("--kl15", choices=["on", "off"])
    ap.add_argument("--digest", default="")
    ap.add_argument("--reason", default="")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("-n", type=int, default=20)
    a = ap.parse_args()
    try:
        if a.cmd == "status":
            if a.json:
                print(json.dumps({"supply": bs.supply(), "target": bs.target(), "pending": bs.pending()}))
            else:
                print(view()[0])
        elif a.cmd == "supply":
            print(json.dumps(bs.set_supply(voltage=a.voltage, kl15=a.kl15)))
        elif a.cmd == "approve":
            print(json.dumps(bs.decide(a.arg, "approved", bs.who(), digest_prefix=a.digest)))
        elif a.cmd == "refuse":
            print(json.dumps(bs.decide(a.arg, "refused", bs.who(), a.reason)))
        elif a.cmd == "reconcile":
            reconcile(a.yes)
        elif a.cmd == "log":
            for e in bs.records()[-a.n:]:
                print(json.dumps(e))
        elif a.cmd == "scenario":
            scenario(a.arg)
    except bs.GateError as e:
        print(f"not done: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
