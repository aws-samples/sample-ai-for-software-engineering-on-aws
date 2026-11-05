#!/usr/bin/env python3
# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Tests of the bench MCP server's guardrails, one or more per row of the README's table. No QEMU, no Docker: a
stand-in bench/cc1.sh answers like the real one (a request in the action record, `refused: ...` on stderr), and
stand-in after-bench checks run without a container (sandbox.runner = "none").

    python3 tests/test_guardrails.py

The MCP-layer tests need the MCP SDK the server pins and are skipped without it.
"""
import hashlib
import json
import os
import pathlib
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ["BENCHSERVER_UNSANDBOXED_FOR_TESTS"] = "1"
from benchserver import core  # noqa: E402
from benchserver.core import BenchService, ConfigError, Refused  # noqa: E402

# A stand-in cc1.sh: records its argv and environment; a physical action writes its request to the action record
# and then does what $FAKE/mode says (refuse, fail, hang), else succeeds.
FAKE_CC1 = r"""#!/usr/bin/env bash
F=__FAKE__; S=$CC1_BENCH_STATE
printf '%s\n' "$*" >> "$F/calls"; env > "$F/env-cc1"
mode=$(cat "$F/mode" 2>/dev/null)
case $1 in
  target) echo '{"state": "known", "why": "booted"}' ;;
  supply) echo '{"voltage_v": 13.5, "kl15": "on"}' ;;
  probe)  echo '{"qemu_running": true, "reachable": true}' ;;
  deploy|restart|replay)
    echo $$ > "$F/pid"
    rid="req-$1-$RANDOM"; d=$(cat "$F/digest" 2>/dev/null)
    [[ $1 == deploy ]] && d=$(shasum -a 256 "$2" | cut -d' ' -f1)
    if [[ $mode == other-first ]]; then  # another requester's refused request lands first (the app's own)
      printf '{"event": "request", "id": "app-1", "action": "%s", "digest": "%s", "requested_by": "vstatd-team r1"}\n' \
        "$1" "$d" >> "$S/actions.jsonl"
      printf '{"event": "decision", "id": "app-1", "verdict": "refused", "by": "bob", "reason": "app request"}\n' \
        >> "$S/actions.jsonl"
      printf '{"event": "gate", "id": "app-1", "action": "%s", "passed": false, "why": "theirs"}\n' "$1" \
        >> "$S/actions.jsonl"
    fi
    printf '{"event": "request", "id": "%s", "action": "%s", "digest": "%s", "requested_by": "%s"}\n' \
      "$rid" "$1" "$d" "$CC1_REQUESTER" >> "$S/actions.jsonl"
    case $mode in
      refuse) echo "deploy of x: approve or refuse it at the operator console" >&2
              printf '{"event": "decision", "id": "%s", "verdict": "refused", "by": "%s", "reason": "%s"}\n' \
                "$rid" "alice@bench (ttys001)" "not this build" >> "$S/actions.jsonl"
              echo "refused: refused (alice@bench (ttys001)): not this build" >&2; exit 1 ;;
      target-says-refused)  # approved and begun, as the bench records it; then the target prints "refused: ..."
              printf '{"event": "target", "state": "busy", "request": "%s"}\n' "$rid" >> "$S/actions.jsonl"
              echo "refused: printed by the agents' vstatd on the target" >&2; exit 1 ;;
      fail|other-first) echo "$1 failed" >&2; exit 1 ;;
      busy)   printf '{"event": "decision", "id": "%s", "verdict": "approved", "by": "alice"}\n' "$rid" \
                >> "$S/actions.jsonl"
              echo "refused: the target is busy: replay in progress (one action at a time)" >&2; exit 1 ;;
      hang)   sleep 30 ;;
    esac
    if [[ $1 == deploy ]]; then cp "$2" "$F/deployed-file"; echo "$2" > "$F/deployed-from"; fi
    if [[ $1 == replay ]]; then
      while (( $# )); do [[ $1 == --out ]] && out=$2; shift; done
      mkdir -p "$out"; echo '{"msg": "SERVICE_START"}' > "$out/run.jsonl"
      printf '{"replay_id": "drive-01@x", "replay_finished": true, "vm_hwm_kib": 5896, "approved_digest": "%s"}\n' \
        "$(cat "$F/digest" 2>/dev/null)" > "$out/run-result.json"
    fi
    echo "$1 ok" ;;
  *) exit 2 ;;
esac
"""

# A stand-in after-bench check: records its argv and environment, and writes a result naming its inputs with their
# SHA-256, the verdict in $FAKE/verdict (default PASS); $FAKE/check-mode makes it misbehave.
FAKE_CHECK = r"""#!/usr/bin/env python3
import hashlib, json, os, pathlib, sys, time
F = pathlib.Path("__FAKE__")
name = pathlib.Path(sys.argv[0]).name[:-3]
(F / f"argv-{name}").write_text("\n".join(sys.argv[1:]))
(F / f"env-{name}").write_text("\n".join(f"{k}={v}" for k, v in os.environ.items()))
a = dict(zip(sys.argv[1::2], sys.argv[2::2]))
r, run, base = pathlib.Path(a["--results"]), pathlib.Path(a["--run"]), pathlib.Path(a["--baseline"])
v = (F / "verdict").read_text().strip() if (F / "verdict").exists() else "PASS"
mode = (F / "check-mode").read_text().strip() if (F / "check-mode").exists() else ""
h = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
inputs = {"run_result": run / "run-result.json", "run_log": run / "run.jsonl",
          "baseline_result": base / "baseline-result.json", "baseline_log": base / "baseline.jsonl"}
if "--triage" in a:
    inputs["triage"] = pathlib.Path(a["--triage"])
rec = {k: {"path": str(p), "sha256": h(p)} for k, p in inputs.items()}
started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
if mode == "stale":
    started = "2000-01-01T00:00:00Z"
if mode == "other-run":
    rec["run_result"]["path"] = "/elsewhere/run-result.json"
if mode == "wrong-hash":
    rec["baseline_log"]["sha256"] = "0" * 64
out = {"check": name, "verdict": "PASS" if mode == "lie" else v, "commit": None, "local": mode == "local",
       "started": started, "inputs": rec, "details": {"approved_digest": "d"}, "summary": "", "reasons": []}
if mode != "silent":
    (r / f"{name}.json").write_text(json.dumps(out))
(r / f"{name}.log").write_text(f"{name}: {v}\n")
print(f"{name}: {v}")
sys.exit({"PASS": 0, "FAIL": 1, "BLOCKED": 3}[v])
"""


class Env(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="benchserver-test-")).resolve()  # macOS: /var is /private/var
        os.chmod(self.tmp, 0o700)
        self.fake = self.tmp / "fake"
        self.fake.mkdir()
        sample = self.tmp / "sample"
        self.bench, self.checks = sample / "bench", sample / "checks"
        self.bench.mkdir(parents=True)
        self.checks.mkdir()
        (self.bench / "cc1.sh").write_text(FAKE_CC1.replace("__FAKE__", str(self.fake)))
        for c in core.CHECKS:
            (self.checks / f"{c}.sh").write_text(FAKE_CHECK.replace("__FAKE__", str(self.fake)))
            (self.checks / f"{c}.sh").chmod(0o755)
        self.st = self.tmp / "srv" / "state"
        self.bstate = self.tmp / "srv" / "cc1-bench"
        self.results = self.tmp / "build" / "results"
        (self.results / "artifacts").mkdir(parents=True)
        self.baseline = self.tmp / "srv" / "baseline"
        self.baseline.mkdir(parents=True)
        (self.baseline / "baseline-result.json").write_text('{"vm_hwm_kib": 5860}\n')
        (self.baseline / "baseline.jsonl").write_text('{"msg": "SERVICE_START"}\n')
        (self.tmp / "srv" / "triage").mkdir()
        self.triage = self.tmp / "srv" / "triage" / "triage.json"
        self.triage.write_text('{"findings": []}\n')
        self.config = self.write_config()
        os.environ["AWS_SECRET_ACCESS_KEY"] = "not-a-real-secret"

    def tearDown(self):
        os.environ.pop("AWS_SECRET_ACCESS_KEY", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_config(self, extra="", **paths):
        p = {"bench": self.bench, "checks": self.checks, "state": self.st, "bench_state": self.bstate,
             "build_results": self.results, "baseline": self.baseline, "triage": self.triage, **paths}
        cfg = self.tmp / "config.toml"
        cfg.write_text("[paths]\n" + "".join(f'{k} = "{v}"\n' for k, v in p.items()) + f"""
[sandbox]
runner = "none"
[lease]
ttl_s = 600
[roles.developer]
classes = ["read-only", "controlled-write", "physical"]
[roles.reviewer]
classes = ["read-only"]
[timeouts]
approval = 2
deploy = 3
restart = 3
replay = 3
check = 20
[environment]
path = "{os.environ['PATH']}"
""" + extra)
        return cfg

    def service(self, role="developer"):
        return BenchService(self.config, role)

    def audit(self):
        return [json.loads(line) for line in (self.st / "audit.jsonl").read_text().splitlines()]

    def outcomes(self):
        return [(e["tool"], e["outcome"]) for e in self.audit()]

    def calls(self):
        p = self.fake / "calls"
        return p.read_text().splitlines() if p.exists() else []

    def publish_build(self, verdict="PASS", local=False, content=b"vstatd binary", digest=None):
        (self.results / "artifacts" / "vstatd").write_bytes(content)
        d = digest or hashlib.sha256(content).hexdigest()
        (self.results / "build.json").write_text(json.dumps({
            "check": "build", "verdict": verdict, "local": local, "commit": "c0ffee",
            "details": {"digest": d, "artifact": str(self.results / "artifacts" / "vstatd")}}))
        (self.fake / "digest").write_text(d)
        return d

    def with_lease(self, role="developer"):
        s = self.service(role)
        s.call("lease_acquire")
        return s


class Roles(Env):
    def test_an_unknown_role_is_granted_nothing_and_every_refusal_is_audited(self):
        s = self.service("intruder")
        for tool in ("bench_status", "lease_acquire", "request_deploy"):
            with self.assertRaises(Refused):
                s.call(tool)
        self.assertEqual(self.outcomes(), [("bench_status", "refused"), ("lease_acquire", "refused"),
                                           ("request_deploy", "refused")])
        self.assertEqual(self.calls(), [])

    def test_a_reviewer_reads_but_takes_no_lease_and_requests_nothing(self):
        s = self.service("reviewer")
        status = s.call("bench_status")
        self.assertEqual(status["target"]["state"], "known")
        for tool in ("lease_acquire", "request_replay"):
            with self.assertRaises(Refused):
                s.call(tool)
        self.assertNotIn("replay", " ".join(self.calls()))

    def test_unknown_permission_classes_stop_the_server(self):
        self.write_config('[roles.ops]\nclasses = ["admin"]\n')
        with self.assertRaises(ConfigError):
            BenchService(self.config, "ops")


class ClosedArguments(Env):
    def test_tools_take_no_path_command_or_digest(self):
        s = self.service()
        cases = [("request_deploy", {"path": "/tmp/evil"}), ("request_replay", {"drive": "x.rec"}),
                 ("run_check", {}), ("run_check", {"check": "release"}), ("run_check", {"check": ["logdiff"]}),
                 ("reconcile", {}), ("approve", {"id": "x"})]
        for tool, args in cases:
            with self.assertRaises(Refused, msg=(tool, args)):
                s.call(tool, **args)
        self.assertEqual([o for _, o in self.outcomes() if o != "started"], ["refused"] * len(cases))
        self.assertEqual(self.calls(), [])

    def test_the_exact_tools_of_the_readme(self):
        self.assertEqual(sorted(core.TOOLS), sorted(["bench_status", "read_actions", "read_result", "lease_acquire",
                                                      "lease_release", "run_check", "request_deploy",
                                                      "request_restart", "request_replay"]))


class Calls(Env):
    def test_arguments_named_like_the_call_itself_are_refused_and_audited(self):
        s = self.service()
        for args in ({"tool": "x"}, {"self": "x"}):
            with self.assertRaisesRegex(Refused, "unexpected arguments"):
                s.call("bench_status", **args)
        self.assertEqual(self.outcomes(), [("bench_status", "refused")] * 2)

    def test_an_unexpected_argument_with_a_long_name_is_capped_in_the_reason_too(self):
        with self.assertRaises(Refused):
            self.service().call("bench_status", **{"n" * 100_000: "x"})
        self.assertLess(len((self.st / "audit.jsonl").read_text()), 2000)

    def test_concurrent_reads_each_read_their_own_output(self):
        import threading
        sessions = [self.service("reviewer") for _ in range(4)]
        seen, errors = [], []

        def read(svc):
            for _ in range(5):
                try:
                    seen.append((svc.call("bench_status")["target"], svc.call("read_actions")))
                except Exception as e:  # noqa: BLE001
                    errors.append(e)
        threads = [threading.Thread(target=read, args=(svc,)) for svc in sessions]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual({json.dumps(t, sort_keys=True) for t, _ in seen},
                         {json.dumps({"state": "known", "why": "booted"})})
        self.assertEqual(list((self.st / "logs").glob("read-*")), [])  # each read's log is removed once read

    def test_a_session_ending_during_a_read_audits_it(self):
        s = self.service("reviewer")
        s.current[0] = {"tool": "bench_status", "class": "read-only", "args": {}}
        s.end_session()
        self.assertEqual(self.audit()[-1]["outcome"], "error")

    def test_the_raw_arguments_of_a_malformed_call_are_capped_in_the_audit(self):
        with self.assertRaises(Refused):
            self.service().call("x" * 5000, **{"y" * 5000: "z" * 5000, **{f"a{i}": i for i in range(50)}})
        line = (self.st / "audit.jsonl").read_text()
        self.assertLess(len(line), 4000)
        self.assertEqual(len(self.audit()[-1]["args"]), 20)

    def test_reads_do_not_wait_for_a_call_in_progress(self):
        """A read-only call takes no lock: another session sees the request waiting at the console."""
        import threading
        a, b = self.with_lease(), self.service("reviewer")
        held, done = threading.Event(), threading.Event()

        def hold():
            with a.exclusive():
                held.set()
                done.wait(10)
        t = threading.Thread(target=hold)
        t.start()
        held.wait(5)
        t0 = time.monotonic()
        try:
            b.call("bench_status")
            b.call("read_actions")
        finally:
            done.set()
            t.join()
        self.assertLess(time.monotonic() - t0, 3)

    def test_only_run_check_reaps_containers(self):
        s = self.with_lease()
        s.sandbox.reap = lambda: (_ for _ in ()).throw(RuntimeError("no docker"))
        s.call("bench_status")  # needs no Docker
        with self.assertRaises(RuntimeError):
            s.call("run_check", check="logdiff")


class Paths(Env):
    def test_the_state_may_not_lie_in_the_sample(self):
        self.write_config(state=self.bench.parent / "state")
        with self.assertRaises(ConfigError):
            self.service()

    def test_a_folder_others_can_write_stops_the_server(self):
        os.chmod(self.baseline, 0o777)
        with self.assertRaises(ConfigError):
            self.service()

    def test_the_triage_and_the_baseline_files_themselves_are_checked(self):
        sha = self.triage.with_name("triage.json.sha256")
        sha.write_text("0" * 64 + "\n")
        for f in (self.triage, sha, self.baseline / "baseline.jsonl"):
            os.chmod(f, 0o666)
            with self.assertRaisesRegex(ConfigError, "writable by other users", msg=f):
                self.service()
            os.chmod(f, 0o644)

    def test_trusted_readers_own_the_build_results_and_the_triage_only(self):
        """Two uids: the server runs as another user (os.getuid patched) than the one who owns the test's folders,
        who stands for buildsrv."""
        import pwd
        owner = pwd.getpwuid(os.getuid()).pw_name
        real = os.getuid
        for path, name in ((self.results, "build_results"), (self.triage.parent, "triage")):
            core.check_trusted(path, name, (real(),))
        try:
            core.os.getuid = lambda: real() + 4242
            for path, name in ((self.results, "build_results"), (self.triage.parent, "triage"),
                               (self.triage, "triage")):
                with self.assertRaisesRegex(ConfigError, "not root, the server's user"):
                    core.check_trusted(path, name)
                core.check_trusted(path, name, (real(),))  # a trusted reader's
            self.config = self.write_config(f'[trust]\nreaders = ["{owner}"]\n')
            with self.assertRaisesRegex(ConfigError, "paths.state"):  # the server's own paths are not the readers'
                self.service()
        finally:
            core.os.getuid = real
        self.config = self.write_config('[trust]\nreaders = ["no-such-user-here"]\n')
        with self.assertRaisesRegex(ConfigError, "trust.readers"):
            self.service()

    def test_running_checks_without_a_container_needs_the_test_flag(self):
        os.environ.pop("BENCHSERVER_UNSANDBOXED_FOR_TESTS")
        try:
            with self.assertRaises(ConfigError):
                self.service()
        finally:
            os.environ["BENCHSERVER_UNSANDBOXED_FOR_TESTS"] = "1"


class Lease(Env):
    def test_physical_calls_and_checks_need_the_lease(self):
        s = self.service()
        self.publish_build()
        for tool, args in (("request_deploy", {}), ("request_restart", {}), ("request_replay", {}),
                           ("run_check", {"check": "logdiff"})):
            with self.assertRaises(Refused, msg=tool):
                s.call(tool, **args)
        self.assertEqual(self.calls(), [])

    def test_one_session_at_a_time_and_only_the_holder_releases(self):
        a, b = self.with_lease(), self.service()
        with self.assertRaises(Refused):
            b.call("lease_acquire")
        with self.assertRaises(Refused):
            b.call("lease_release")
        self.publish_build()
        with self.assertRaises(Refused):
            b.call("request_deploy")
        self.assertTrue(a.call("lease_release")["released"])
        self.assertTrue(b.call("lease_acquire")["yours"])

    def test_a_lapsed_lease_can_be_taken(self):
        self.with_lease()
        data = json.loads((self.st / "lease.json").read_text())
        data["expires"] = time.time() - 1
        (self.st / "lease.json").write_text(json.dumps(data))
        self.assertTrue(self.service().call("lease_acquire")["yours"])

    def test_the_lease_goes_when_the_session_ends(self):
        s = self.with_lease()
        s.end_session()
        self.assertFalse((self.st / "lease.json").exists())
        self.assertEqual(self.audit()[-1]["detail"], "released: the session ended")

    def test_a_lease_whose_session_died_can_be_taken_at_once(self):
        self.with_lease()
        gone = subprocess.Popen([sys.executable, "-c", "pass"])
        gone.wait()
        data = json.loads((self.st / "lease.json").read_text())
        data["holder"] = f"developer:{gone.pid}:0123456789abcdef"  # expires in 10 minutes, its process is gone
        (self.st / "lease.json").write_text(json.dumps(data))
        b = self.service()
        self.assertTrue(b.call("lease_acquire")["yours"])
        self.assertEqual(json.loads((self.st / "lease.json").read_text())["holder"], b.holder)

    def test_a_server_that_is_terminated_mid_action_stops_its_cc1_and_gives_the_lease_back(self):
        self.publish_build()
        (self.fake / "mode").write_text("hang")  # cc1.sh waits as for an approval
        code = ("import sys; sys.path.insert(0, sys.argv[1]); from benchserver.core import BenchService, end_on_exit; "
                "s = BenchService(sys.argv[2], 'developer'); end_on_exit(s); s.call('lease_acquire'); "
                "s.call('request_deploy')")
        server = subprocess.Popen([sys.executable, "-c", code, str(pathlib.Path(__file__).resolve().parents[1]),
                                   str(self.config)])
        pid_file = self.fake / "pid"
        for _ in range(100):
            if pid_file.exists():
                break
            time.sleep(0.05)
        cc1 = int(pid_file.read_text())
        server.send_signal(signal.SIGTERM)
        self.assertEqual(server.wait(timeout=10), 128 + signal.SIGTERM)
        for _ in range(100):  # the stand-in cc1.sh and its sleep end
            try:
                os.kill(cc1, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        else:
            self.fail("cc1.sh still running after the server ended")
        self.assertFalse((self.st / "lease.json").exists())
        ended = [e for e in self.audit() if e["tool"] == "request_deploy"]
        self.assertEqual([e["outcome"] for e in ended], ["started", "error"])
        self.assertIn("SIGTERM during the call; stopped 1 process(es)", ended[-1]["detail"])
        self.assertEqual(self.audit()[-1]["detail"], "released: the server got signal SIGTERM")


class Deploy(Env):
    def test_only_a_build_the_build_server_judged_pass(self):
        s = self.with_lease()
        with self.assertRaises(Refused):  # nothing published
            s.call("request_deploy")
        for kw in ({"verdict": "FAIL"}, {"local": True}, {"digest": "0" * 64}):
            self.publish_build(**kw)
            with self.assertRaises(Refused, msg=kw):
                s.call("request_deploy")
        self.assertNotIn("deploy", " ".join(self.calls()))

    def test_the_server_deploys_its_own_copy_of_the_judged_build_and_names_itself_as_requester(self):
        s = self.with_lease()
        digest = self.publish_build()
        out = s.call("request_deploy")
        self.assertEqual(out["digest"], digest)
        self.assertTrue(out["request"].startswith("req-deploy-"))
        src = (self.fake / "deployed-from").read_text().strip()
        self.assertEqual(pathlib.Path(src), self.st / "builds" / digest)  # not the build server's file
        env = (self.fake / "env-cc1").read_text()
        self.assertIn(f"CC1_REQUESTER=bench MCP server (role developer, session {s.holder})", env)
        self.assertIn(f"CC1_BENCH_STATE={self.bstate}", env)
        self.assertIn("CC1_APPROVAL_TIMEOUT_S=2", env)
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", env)
        last = self.audit()[-1]
        self.assertEqual((last["outcome"], last["digest"], last["request"]), ("ok", digest, out["request"]))

    def test_a_result_of_another_check_is_not_a_build(self):
        s = self.with_lease()
        self.publish_build()
        data = json.loads((self.results / "build.json").read_text())
        (self.results / "build.json").write_text(json.dumps({**data, "check": "static"}))
        with self.assertRaisesRegex(Refused, "no result of checks/build.sh"):
            s.call("request_deploy")

    def test_the_target_printing_refused_is_a_failure_not_a_refusal(self):
        s = self.with_lease()
        self.publish_build()
        (self.fake / "mode").write_text("target-says-refused")
        out = s.call("request_deploy")
        self.assertEqual(out["outcome"], "failed")
        self.assertTrue(out["request"].startswith("req-deploy-"))

    def test_the_request_is_found_in_a_large_action_record(self):
        s = self.with_lease()
        self.publish_build()
        self.bstate.mkdir(parents=True, exist_ok=True)
        old = json.dumps({"event": "action", "id": "old", "detail": "x" * 200}) + "\n"
        (self.bstate / "actions.jsonl").write_text(old * 2000)  # about 450 KiB, more than the 256 KiB read for status
        out = s.call("request_deploy")
        self.assertTrue(out["request"].startswith("req-deploy-"))

    def test_another_requesters_refused_request_is_not_this_calls(self):
        s = self.with_lease()
        self.publish_build()
        (self.fake / "mode").write_text("other-first")
        out = s.call("request_deploy")  # our deploy failed; the app's refusal just before it is not ours
        self.assertEqual(out["outcome"], "failed")
        self.assertTrue(out["request"].startswith("req-deploy-"))
        self.assertEqual(self.audit()[-1]["request"], out["request"])

    def test_an_approved_action_the_busy_target_did_not_begin_is_refused_not_failed(self):
        s = self.with_lease()
        self.publish_build()
        (self.fake / "mode").write_text("busy")
        with self.assertRaisesRegex(Refused, "busy.*nothing ran on the target"):
            s.call("request_deploy")

    def test_a_refusal_at_the_console_is_final_and_not_retried(self):
        s = self.with_lease()
        self.publish_build()
        (self.fake / "mode").write_text("refuse")
        with self.assertRaises(Refused) as e:
            s.call("request_deploy")
        self.assertIn("not this build", str(e.exception))
        self.assertIn("not retried", str(e.exception))
        self.assertEqual([c.split()[0] for c in self.calls()].count("deploy"), 1)
        self.assertEqual(self.audit()[-1]["outcome"], "refused")

    def test_an_action_that_does_not_finish_is_stopped_and_not_retried(self):
        s = self.with_lease()
        self.publish_build()
        (self.fake / "mode").write_text("hang")
        t0 = time.monotonic()
        with self.assertRaises(Refused) as e:
            s.call("request_deploy")
        self.assertLess(time.monotonic() - t0, 25)
        self.assertIn("unknown", str(e.exception))
        self.assertEqual([c.split()[0] for c in self.calls()].count("deploy"), 1)


class Replay(Env):
    def test_each_replay_gets_a_new_run_folder_in_the_servers_state(self):
        s = self.with_lease()
        self.publish_build()
        self.assertEqual(s.call("request_replay")["run"], "run-1")
        self.assertEqual(s.call("request_replay")["run"], "run-2")
        self.assertIn(f"replay --kind run --out {self.st / 'runs' / 'run-2'}", self.calls()[-1])
        self.assertEqual(s.call("bench_status")["last_run"]["run"], "run-2")

    def test_a_failed_action_is_reported_and_not_retried(self):
        s = self.with_lease()
        (self.fake / "mode").write_text("fail")
        out = s.call("request_replay")
        self.assertEqual(out["outcome"], "failed")
        self.assertEqual([c.split()[0] for c in self.calls()].count("replay"), 1)


class Checks(Env):
    def replayed(self):
        s = self.with_lease()
        self.publish_build()
        s.call("request_replay")
        return s

    def test_no_check_before_a_replay(self):
        with self.assertRaises(Refused):
            self.with_lease().call("run_check", check="runtime-limits")

    def test_fixed_arguments_and_a_clean_environment(self):
        s = self.replayed()
        out = s.call("run_check", check="logdiff")
        self.assertEqual(out["verdict"], "PASS")
        argv = (self.fake / "argv-logdiff").read_text().splitlines()
        run = self.st / "runs" / "run-1"
        self.assertEqual(argv[0::2], ["--results", "--run", "--baseline", "--triage"])
        self.assertEqual(argv[3:8:2], [str(run), str(self.baseline), str(self.triage)])
        self.assertNotIn("--triage", (self.fake / "argv-runtime-limits").read_text() if
                         (self.fake / "argv-runtime-limits").exists() else "--results")
        s.call("run_check", check="runtime-limits")
        self.assertNotIn("--triage", (self.fake / "argv-runtime-limits").read_text())
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", (self.fake / "env-logdiff").read_text())
        published = json.loads((self.st / "results" / "logdiff.json").read_text())
        self.assertEqual(published["verdict"], "PASS")
        self.assertEqual(s.call("read_result", check="logdiff")["result"]["verdict"], "PASS")

    def test_a_result_that_is_not_this_runs_is_published_as_error(self):
        s = self.replayed()
        for mode in ("lie", "stale", "other-run", "wrong-hash", "local", "silent"):
            (self.fake / "verdict").write_text("FAIL")
            (self.fake / "check-mode").write_text(mode)
            out = s.call("run_check", check="runtime-limits")
            self.assertEqual(out["verdict"], "ERROR", mode)
            published = json.loads((self.st / "results" / "runtime-limits.json").read_text())
            self.assertEqual(published["verdict"], "ERROR", mode)
            self.assertTrue(published["reasons"][0].startswith("bench server:"), mode)

    def test_a_result_is_read_whole_while_it_is_published(self):
        s = self.with_lease()
        self.publish_build()
        s.call("request_replay")
        s.call("run_check", check="logdiff")
        with s.publishing():  # a check replacing its files holds this; a read waits for it
            import threading
            got = []
            reader = self.service("reviewer")
            t = threading.Thread(target=lambda: got.append(reader.call("read_result", check="logdiff")))
            t.start()
            t.join(1)
            self.assertEqual(got, [])
        t.join(5)
        self.assertEqual(got[0]["result"]["verdict"], "PASS")

    def test_a_fail_is_published_as_it_is(self):
        s = self.replayed()
        (self.fake / "verdict").write_text("FAIL")
        self.assertEqual(s.call("run_check", check="runtime-limits")["verdict"], "FAIL")
        self.assertEqual(json.loads((self.st / "results" / "runtime-limits.json").read_text())["verdict"], "FAIL")


class Reads(Env):
    def test_status_shows_pending_requests_and_the_lease_without_its_holder(self):
        s = self.with_lease()
        (self.bstate / "requests").mkdir(exist_ok=True)
        (self.bstate / "requests" / "r1.json").write_text(json.dumps({
            "id": "r1", "action": "deploy", "digest": "d" * 64, "expires": time.time() + 100,
            "requested_by": "someone"}))
        st = s.call("bench_status")
        self.assertEqual([r["id"] for r in st["pending_requests"]], ["r1"])
        self.assertTrue(st["lease"]["yours"])
        self.assertNotIn("holder", st["lease"])
        self.assertEqual(st["supply"]["kl15"], "on")

    def test_the_action_record_is_read_not_written(self):
        s = self.service("reviewer")
        (self.bstate / "actions.jsonl").write_text('{"event": "decision", "verdict": "approved"}\nnot json\n')
        before = (self.bstate / "actions.jsonl").read_bytes()
        self.assertEqual(s.call("read_actions")["actions"], [{"event": "decision", "verdict": "approved"}])
        self.assertEqual((self.bstate / "actions.jsonl").read_bytes(), before)


class McpLayer(Env):
    def setUp(self):
        super().setUp()
        try:
            from mcp import Client  # noqa: F401
            from benchserver.server import make_server  # noqa: F401
        except ImportError:
            self.skipTest("MCP SDK 2.x not installed")

    def run_client(self, fn, role="developer"):
        import asyncio
        from mcp import Client
        from benchserver.server import make_server
        server = make_server(self.service(role))

        async def go():
            async with Client(server) as client:
                return await fn(client)
        return asyncio.run(go())

    def test_exactly_the_documented_tools(self):
        async def f(c):
            return sorted(t.name for t in (await c.list_tools()).tools)
        self.assertEqual(self.run_client(f), sorted(core.TOOLS))

    def test_refusals_are_errors_and_audited_including_what_the_sdk_would_reject(self):
        async def f(c):
            out = []
            for name, args in (("request_deploy", {}), ("request_deploy", {"path": "/x"}), ("approve", {}),
                               ("run_check", {}), ("bench_status", {"tool": "x"}),
                               ("read_result", {"check": "logdiff", "self": "x"})):
                try:
                    r = await c.call_tool(name, args)
                    out.append(("result", r.is_error))
                except Exception as e:  # noqa: BLE001
                    out.append(("raised", type(e).__name__))
            return out
        out = self.run_client(f)
        self.assertEqual(out[0], ("result", True))  # no lease
        self.assertTrue(all(o[0] == "raised" or o[1] for o in out[1:]))
        self.assertEqual([o for _, o in self.outcomes() if o != "started"], ["refused"] * 6)
        self.assertEqual(self.calls(), [])

    def test_a_client_that_goes_away_mid_action_leaves_no_cc1_and_no_lease(self):
        """Over stdio, as an agent starts the server: the client gives up while request_deploy waits as for an
        approval, and the SDK ends the server (stdin closed, then SIGTERM)."""
        import asyncio
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        self.publish_build()
        (self.fake / "mode").write_text("hang")
        params = StdioServerParameters(command=sys.executable, args=["-m", "benchserver", "--config", str(self.config),
                                                                     "--role", "developer"],
                                       cwd=str(pathlib.Path(__file__).resolve().parents[1]), env=dict(os.environ))

        async def go():
            async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
                await s.initialize()
                await s.call_tool("lease_acquire", {})
                try:
                    await s.call_tool("request_deploy", {}, read_timeout_seconds=1.0)
                except Exception:  # noqa: BLE001 - the client gives up
                    pass
        asyncio.run(go())
        cc1 = int((self.fake / "pid").read_text())
        for _ in range(100):
            try:
                os.kill(cc1, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        else:
            self.fail("cc1.sh still running after the client went away")
        self.assertFalse((self.st / "lease.json").exists())
        self.assertEqual([e["outcome"] for e in self.audit() if e["tool"] == "request_deploy"], ["started", "error"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
