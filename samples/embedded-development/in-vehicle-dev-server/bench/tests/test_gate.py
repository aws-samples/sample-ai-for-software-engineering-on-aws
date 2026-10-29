#!/usr/bin/env python3
# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Tests of the bench's gate and operator console, one or more per guardrail. No QEMU needed.

    python3 bench/tests/test_gate.py
"""
import importlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest

HERE = pathlib.Path(__file__).resolve().parent
BENCH = HERE.parent
sys.path.insert(0, str(BENCH / "lib"))
GATE, CONSOLE = BENCH / "lib" / "gate.py", BENCH / "console.py"
D, D2 = "a" * 64, "b" * 64


class Gate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["CC1_BENCH_STATE"] = self.tmp.name
        os.environ["CC1_APPROVAL_TIMEOUT_S"] = "3"
        fake = pathlib.Path(self.tmp.name) / "fake-cc1.sh"
        fake.write_text('#!/bin/sh\necho \'{"qemu_running":true,"reachable":true,"vstatd":"inactive"}\'\n')
        fake.chmod(0o755)
        os.environ["CC1_BENCH_SCRIPT"] = str(fake)
        import benchstate
        self.bs = importlib.reload(benchstate)

    def tearDown(self):
        self.tmp.cleanup()

    def run_tool(self, tool, *args):
        return subprocess.run([sys.executable, str(tool), *args], capture_output=True, text=True, timeout=20)

    def authorize_async(self, action="deploy", digest=D):
        return subprocess.Popen([sys.executable, str(GATE), "authorize", action, digest], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)

    def next_request(self):
        end = time.time() + 5
        while time.time() < end:
            p = self.bs.pending()
            if p:
                return p[0]
            time.sleep(0.05)
        self.fail("no request appeared")

    def ready(self, voltage=13.5, kl15="on"):
        self.bs.set_target("known", "test")
        self.bs.set_supply(voltage, kl15, by="test")

    def approved(self, action="deploy", digest=D):
        r = self.bs.new_request(action, digest)
        self.bs.decide(r["id"], "approved", "test", digest_prefix=digest[:6])
        return r["id"]

    # ---- physical gate (CC1-PN §8.1) ----
    def test_supply_not_set_refuses_without_a_request(self):
        self.bs.set_target("known", "test")
        r = self.run_tool(GATE, "authorize", "deploy", D)
        self.assertEqual(r.returncode, 1)
        self.assertIn("has not been set", r.stderr)
        self.assertEqual(self.bs.pending(), [])

    def test_voltage_limits(self):
        for v, ok in ((10.99, False), (11.0, True), (14.8, True), (14.81, False)):
            self.bs.set_supply(v, "on", by="test")
            self.assertEqual(self.bs.physical_check("deploy")[0], ok, v)

    def test_kl15_off_refuses_every_physical_action(self):
        self.bs.set_supply(13.5, "off", by="test")
        for action in ("deploy", "restart", "replay"):
            ok, why = self.bs.physical_check(action)
            self.assertFalse(ok)
            self.assertIn("KL15", why)

    def test_stop_and_reads_have_no_physical_precondition(self):
        self.assertTrue(self.bs.physical_check("stop-vstatd")[0])

    def test_supply_change_after_approval_is_caught(self):
        self.ready()
        p = self.authorize_async()
        r = self.next_request()
        self.bs.set_supply(kl15="off", by="test")
        self.bs.decide(r["id"], "approved", "test", digest_prefix=D[:6])
        out, err = p.communicate(timeout=10)
        self.assertEqual(p.returncode, 1)
        self.assertIn("after the approval", err)

    # ---- action gate: a person, the exact digest ----
    def test_approval_needs_the_digest(self):
        self.ready()
        p = self.authorize_async()
        r = self.next_request()
        for prefix in ("", "aaaaa", D2[:6]):
            res = self.run_tool(CONSOLE, "approve", r["id"], "--digest", prefix)
            self.assertEqual(res.returncode, 1, prefix)
        res = self.run_tool(CONSOLE, "approve", r["id"], "--digest", D[:8])
        self.assertEqual(res.returncode, 0, res.stderr)
        out, err = p.communicate(timeout=10)
        self.assertEqual(p.returncode, 0, err)
        self.assertEqual(out.strip(), r["id"])

    def test_refusal(self):
        self.ready()
        p = self.authorize_async()
        r = self.next_request()
        self.run_tool(CONSOLE, "refuse", r["id"], "--reason", "not this build")
        out, err = p.communicate(timeout=10)
        self.assertEqual(p.returncode, 1)
        self.assertIn("not this build", err)

    def test_no_answer_is_a_refusal(self):
        self.ready()
        p = self.authorize_async()
        r = self.next_request()
        out, err = p.communicate(timeout=15)
        self.assertEqual(p.returncode, 1)
        self.assertIn("within 3 s", err)
        self.assertEqual(self.bs.decision(r["id"])["by"], "bench (timeout)")
        res = self.run_tool(CONSOLE, "approve", r["id"], "--digest", D[:6])
        self.assertEqual(res.returncode, 1)

    def test_an_approval_for_another_digest_does_not_count(self):
        self.ready()
        p = self.authorize_async()
        r = self.next_request()
        (pathlib.Path(self.tmp.name) / "decisions" / f"{r['id']}.json").write_text(json.dumps(
            {"id": r["id"], "verdict": "approved", "action": "deploy", "digest": D2, "by": "x", "reason": ""}))
        out, err = p.communicate(timeout=10)
        self.assertEqual(p.returncode, 1)
        self.assertIn("not for this action and digest", err)

    def test_an_approval_is_used_once(self):
        self.ready()
        rid = self.approved()
        self.bs.begin(rid, "deploy", D, os.getpid())
        self.bs.end(rid, True, "test")
        with self.assertRaises(self.bs.GateError):
            self.bs.begin(rid, "deploy", D, os.getpid())

    def test_begin_needs_an_approval_for_this_action_and_digest(self):
        self.ready()
        rid = self.approved("deploy", D)
        for action, digest in (("deploy", D2), ("replay", D)):
            with self.assertRaises(self.bs.GateError):
                self.bs.begin(rid, action, digest, os.getpid())

    # ---- one action at a time, unknown after an interruption ----
    def test_one_action_at_a_time(self):
        self.ready()
        r1, r2 = self.approved(), self.approved()
        self.bs.begin(r1, "deploy", D, os.getpid())
        with self.assertRaises(self.bs.GateError) as e:
            self.bs.begin(r2, "deploy", D, os.getpid())
        self.assertIn("busy", str(e.exception))

    def test_interrupted_action_leaves_the_target_unknown(self):
        self.ready()
        rid = self.approved()
        dead = subprocess.Popen(["true"])
        dead.wait()
        self.bs.begin(rid, "deploy", D, dead.pid)
        t = self.bs.target()
        self.assertEqual(t["state"], "unknown")
        self.assertIn("interrupted", t["why"])
        r = self.run_tool(GATE, "authorize", "replay", D)
        self.assertEqual(r.returncode, 1)
        self.assertIn("Only reads and a reconcile", r.stderr)
        self.assertEqual(self.run_tool(GATE, "can-power").returncode, 1)
        self.assertEqual(self.run_tool(GATE, "target").returncode, 1)

    def test_failed_action_leaves_the_target_unknown(self):
        self.ready()
        rid = self.approved()
        self.bs.begin(rid, "deploy", D, os.getpid())
        self.bs.end(rid, False, "digest mismatch")
        self.assertEqual(self.bs.target()["state"], "unknown")

    def test_reconcile_by_a_person(self):
        self.bs.set_target("unknown", "test")
        r = self.run_tool(CONSOLE, "reconcile", "--yes")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.bs.target()["state"], "known")
        self.assertTrue(any(e["event"] == "reconcile" for e in self.bs.records()))

    def test_reconcile_waits_for_a_running_action(self):
        self.ready()
        self.bs.begin(self.approved(), "deploy", D, os.getpid())
        r = self.run_tool(CONSOLE, "reconcile", "--yes")
        self.assertEqual(r.returncode, 1)
        self.assertIn("still running", r.stderr)

    # ---- the action record ----
    def test_the_action_record_only_grows(self):
        self.ready()
        rid = self.approved()
        before = (pathlib.Path(self.tmp.name) / "actions.jsonl").read_text()
        self.bs.begin(rid, "deploy", D, os.getpid())
        self.bs.end(rid, True, "test")
        after = (pathlib.Path(self.tmp.name) / "actions.jsonl").read_text()
        self.assertTrue(after.startswith(before))
        events = [e["event"] for e in self.bs.records()]
        for ev in ("supply", "request", "decision", "target", "action"):
            self.assertIn(ev, events)

    def test_every_decision_names_who_and_the_digest(self):
        self.ready()
        self.approved()
        dec = [e for e in self.bs.records() if e["event"] == "decision"][-1]
        self.assertEqual(dec["digest"], D)
        self.assertEqual(dec["by"], "test")

    def test_scripted_scenario(self):
        f = pathlib.Path(self.tmp.name) / "drop.scenario"
        f.write_text("0 voltage 13.5\n0 kl15 on\n0.2 voltage 10.5  # supply dip\n")
        r = self.run_tool(CONSOLE, "scenario", str(f))
        self.assertEqual(r.returncode, 0, r.stderr)
        s = self.bs.supply()
        self.assertEqual((s["voltage_v"], s["kl15"], s["set_by"]), (10.5, "on", "scenario drop.scenario"))
        self.assertFalse(self.bs.physical_check("deploy")[0])

    def test_state_dir_is_private(self):
        self.bs.state_dir()
        self.assertEqual(os.stat(self.tmp.name).st_mode & 0o777, 0o700)


if __name__ == "__main__":
    unittest.main(verbosity=2)
