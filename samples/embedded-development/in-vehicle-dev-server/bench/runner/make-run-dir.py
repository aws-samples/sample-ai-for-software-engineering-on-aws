#!/usr/bin/env python3
# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Writes a run or baseline directory in the format of checks/README.md, "Run and baseline directories".

    make-run-dir.py --kind run|baseline --out <dir> --log <journal copy> --result '<RESULT json of run-replay>' \
        --qemu-command <file> --deployed <file> --replay-id <id>
"""
import argparse
import json
import pathlib
import shutil
import sys


def main():
    ap = argparse.ArgumentParser()
    for k in ("--kind", "--out", "--log", "--result", "--qemu-command", "--deployed", "--replay-id"):
        ap.add_argument(k, required=True)
    ap.add_argument("--approval", default="")
    a = ap.parse_args()
    if a.kind not in ("run", "baseline"):
        sys.exit("--kind must be run or baseline")
    res = json.loads(a.result)
    fin = res.get("finish") or {}
    figures = fin.get("figures") if isinstance(fin.get("figures"), dict) else {}
    ended = bool((fin.get("end") or {}).get("end_of_drive"))
    deployed = json.loads(pathlib.Path(a.deployed).read_text())
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(a.log, out / f"{a.kind}.jsonl")
    result = {
        "replay_id": a.replay_id,
        "target": "emulated-cc1",
        "qemu_command": pathlib.Path(a.qemu_command).read_text().strip(),
        "replay_finished": ended,
        "replay_end": "player-end-of-drive",
        # cc1-bench finish reads the figures only once the drive has ended (CC1-PN §8.5): true when it did and gave them
        "figures_after_replay_end": ended and "vm_hwm_kib" in figures,
        **figures,
        "approved_digest": deployed["approved_digest"],
        "readback_digest": deployed["readback_digest"],
        "vstatd_restarts": res["restarts"],
        "journal_marker": res["marker"],
        "approval_request": a.approval,
    }
    (out / f"{a.kind}-result.json").write_text(json.dumps(result, indent=1) + "\n")
    print(out)


if __name__ == "__main__":
    main()
