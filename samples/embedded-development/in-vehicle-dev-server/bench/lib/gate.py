#!/usr/bin/env python3
# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""The bench's gate, called by bench/cc1.sh. See benchstate.py.

  gate.py authorize ACTION DIGEST [--detail D]   physical gate + approval at the console; prints the request ID
  gate.py begin RID ACTION DIGEST --pid N        start the approved action (one at a time, approval used once)
  gate.py end RID ok|failed [--detail D]         the target is known again, or unknown after a failure
  gate.py target | supply | statedir             reads (target: exit 0 only when known)
  gate.py can-power                              exit 0 when QEMU may be started or stopped (target off or known)
  gate.py fresh-boot | off | unknown --why W     target state changes made by the bench itself
  gate.py record EVENT [--detail D]              one more entry in the action record
"""
import argparse
import json
import sys

import benchstate as bs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd")
    ap.add_argument("args", nargs="*")
    ap.add_argument("--detail", default="")
    ap.add_argument("--why", default="")
    ap.add_argument("--pid", type=int, default=0)
    a = ap.parse_args()
    try:
        if a.cmd == "authorize":
            action, digest = a.args
            print(bs.authorize(action, digest, a.detail))
        elif a.cmd == "begin":
            rid, action, digest = a.args
            bs.begin(rid, action, digest, a.pid)
        elif a.cmd == "end":
            rid, result = a.args
            bs.end(rid, result == "ok", a.detail)
        elif a.cmd == "target":
            t = bs.target()
            print(json.dumps(t))
            if t["state"] != "known":
                print(f"the target is {t['state']}: {t['why']}", file=sys.stderr)
                return 1
        elif a.cmd == "supply":
            print(json.dumps(bs.supply()))
        elif a.cmd == "statedir":
            print(bs.state_dir())
        elif a.cmd == "can-power":
            t = bs.target()
            if t["state"] not in ("off", "known"):
                print(f"refused: the target is {t['state']}: {t['why']}. Reconcile at the operator console first",
                      file=sys.stderr)
                return 1
        elif a.cmd == "fresh-boot":
            bs.set_target("known", "booted from the pristine image; no build installed", note=a.detail)
        elif a.cmd == "off":
            bs.set_target("off", a.why or "the emulated CC-1 was stopped")
        elif a.cmd == "unknown":
            bs.set_target("unknown", a.why)
        elif a.cmd == "record":
            bs.record(a.args[0], detail=a.detail, by="bench tools")
        else:
            print(__doc__, file=sys.stderr)
            return 2
    except bs.GateError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 1
    except ValueError:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
