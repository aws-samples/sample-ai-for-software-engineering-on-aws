#!/usr/bin/env python3
# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Tests of bench/runner/make-run-dir.py: the run result says what the replay's finish did. No QEMU needed.

    python3 bench/tests/test_make_run_dir.py
"""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "runner" / "make-run-dir.py"
FIGURES = {"vm_hwm_kib": 5896, "threads_at_end": 3, "cpu_ms": 2500}


class MakeRunDir(unittest.TestCase):
    def make(self, finish):
        tmp = pathlib.Path(self.enterContext(tempfile.TemporaryDirectory()))
        (tmp / "log.jsonl").write_text("{}\n")
        (tmp / "qemu.txt").write_text("qemu-system-aarch64 -icount shift=3,sleep=off\n")
        (tmp / "deployed.json").write_text(json.dumps({"approved_digest": "a" * 64, "readback_digest": "a" * 64}))
        res = {"invocation": "i", "marker": "m", "restarts": 0, "finish": finish}
        subprocess.run([sys.executable, str(SCRIPT), "--kind", "run", "--out", str(tmp / "run"), "--log", str(tmp / "log.jsonl"),
                        "--result", json.dumps(res), "--qemu-command", str(tmp / "qemu.txt"),
                        "--deployed", str(tmp / "deployed.json"), "--replay-id", "drive-01"], check=True, capture_output=True)
        return json.loads((tmp / "run" / "run-result.json").read_text())

    def test_figures_read_after_the_end_of_the_drive(self):
        r = self.make({"end": {"end_of_drive": True}, "figures": FIGURES})
        self.assertTrue(r["replay_finished"])
        self.assertTrue(r["figures_after_replay_end"])
        self.assertEqual(r["vm_hwm_kib"], 5896)

    def test_no_end_of_drive_or_no_figures_is_not_after_the_end(self):
        r = self.make({"end": {}, "figures": FIGURES})
        self.assertFalse(r["replay_finished"])
        self.assertFalse(r["figures_after_replay_end"])
        r = self.make({"end": {"end_of_drive": True}, "figures": {}})
        self.assertTrue(r["replay_finished"])
        self.assertFalse(r["figures_after_replay_end"])
        self.assertNotIn("vm_hwm_kib", r)


if __name__ == "__main__":
    unittest.main()
