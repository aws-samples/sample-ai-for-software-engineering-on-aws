#!/usr/bin/env python3
# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Tests of the checks with small synthetic inputs: a passing and a failing example for each check, and a test for
each verdict rule of checks/README.md. Runs anywhere with Python 3 and git:

    python3 checks/test/test_checks.py

The checks' full runs on the reference project need the build environment; see checks/README.md.
"""

import copy
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

CHECKS = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CHECKS / "lib"))
import common as c  # noqa: E402
import check_logdiff  # noqa: E402
import check_static  # noqa: E402
import check_unit  # noqa: E402

SAMPLE = CHECKS.parent
EXAMPLE_TRIAGE = json.loads((CHECKS / "examples" / "triage.json").read_text())
DIGEST = "ab" * 32


def write_triage(path, t):
    """A triage file and its approval record (checks/README.md)."""
    path.write_text(json.dumps(t))
    path.with_name(path.name + ".sha256").write_text(c.sha256(path) + "\n")
    return path


def sh(*cmd, cwd=None, env=None):
    p = subprocess.run([str(x) for x in cmd], cwd=cwd, env=env, capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def check(name, *args, env=None):
    return sh(CHECKS / f"{name}.sh", *args, env=env)


class Repo:
    """A small git work tree standing in for the project."""

    def __init__(self, root):
        self.path = pathlib.Path(root) / "project"
        (self.path / "src").mkdir(parents=True)
        (self.path / "cmake").mkdir()
        (self.path / "tests").mkdir()
        (self.path / "src" / "a.cpp").write_text("int main() { return 0; }\n")
        (self.path / "cmake" / "cc1-aarch64.cmake").write_text("set(CMAKE_SYSTEM_NAME Linux)\n")
        (self.path / "tests" / "test_a.cpp").write_text("TEST(A, Works) {}\n")
        for args in (("init", "-q", "-b", "main"), ("config", "user.email", "t@example.com"),
                     ("config", "user.name", "Test"), ("add", "-A"), ("commit", "-qm", "Current release")):
            subprocess.run(["git", "-C", self.path, *args], check=True, capture_output=True)
        self.base = self.head()

    def head(self):
        return c.git(self.path, "rev-parse", "HEAD").stdout.strip()

    def commit(self, message, path="src/a.cpp", text=None):
        f = self.path / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text if text is not None else f.read_text() + "// change\n")
        subprocess.run(["git", "-C", self.path, "add", "-A"], check=True)
        subprocess.run(["git", "-C", self.path, "commit", "-qm", message], check=True)


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="vstatd-checks-test-"))
        self.results = self.tmp / "results"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def triage(self, base, **changes):
        t = copy.deepcopy(EXAMPLE_TRIAGE)
        t["base"] = base
        t.update(changes)
        return write_triage(self.tmp / "triage.json", t)


# ------------------------------------------------------------------------------------------------ settings

class Settings(unittest.TestCase):
    def test_limits_state_their_source(self):
        pn = (SAMPLE / "knowledge" / "cc1-platform-notes.md").read_text()
        tr = (SAMPLE / "knowledge" / "team-rules.md").read_text()
        lim = c.limits()
        self.assertEqual(lim["peak_rss_kib"], 8 * 1024)
        self.assertIn("| Peak resident memory (RSS) during the recorded drive | 8 MiB |", pn)
        self.assertIn("| Threads at the end of the replay | at most 4 |", pn)
        self.assertEqual(lim["stripped_size_bytes"], int(1.5 * 1024 * 1024))
        self.assertIn("| Binary size, stripped | 1.5 MiB |", pn)
        self.assertIn("differ by at most 20 ms", " ".join(pn.split()))
        self.assertIn("the `version` field of `SERVICE_START`", pn)
        self.assertIn("`" + " ".join(lim["cross_flags"]) + "`", tr)
        self.assertIn("cppcheck 2.13", tr)
        self.assertIn("clang-tidy 18", tr)
        self.assertIn("at most 3 times and a failing log comparison at most 2 times", tr)
        self.assertIn("expected in `/opt/cc1-sysroot`", (SAMPLE / "reference-project" / "README.md").read_text())
        self.assertEqual(lim["sysroot"], "/opt/cc1-sysroot")
        self.assertIn('`sd_notify("READY=1")` from libsystemd', pn)

    def test_copies_match_the_reference_project(self):
        ref = SAMPLE / "reference-project"
        self.assertEqual((CHECKS / "lib" / "match_backlog.py").read_bytes(),
                         (ref / "tools" / "match-backlog.py").read_bytes())
        self.assertEqual((CHECKS / "lib" / "clang-tidy.yaml").read_bytes(), (ref / ".clang-tidy").read_bytes())

    def test_example_triage_is_valid(self):
        t, problems = c.load_triage(CHECKS / "examples" / "triage.json")
        self.assertEqual(problems, [])

    def test_unapproved_or_incomplete_triage(self):
        t = copy.deepcopy(EXAMPLE_TRIAGE)
        t["approved"] = {}
        t["findings"] = [f for f in t["findings"] if f["id"] != "F-001"]
        t["findings"].append({"id": "F-009", "decision": "fix", "behaviour": False, "evidence": "static-analysis"})
        t["findings"].append({"id": "F-032", "decision": "fix", "behaviour": False, "evidence": "build",
                              "added": {"found_by": "checks/build.sh"}})
        t["findings"].append("F-033")
        with tempfile.TemporaryDirectory() as d:
            _, problems = c.load_triage(write_triage(pathlib.Path(d) / "t.json", t))
        text = "\n".join(problems)
        self.assertIn("not approved", text)
        self.assertIn("F-001: labelled fix in the backlog but has no decision", text)
        self.assertIn("F-009: labelled later", text)
        self.assertIn("take the next free IDs from F-031", text)
        self.assertIn("without an ID", text)

    def test_triage_changed_after_approval(self):
        with tempfile.TemporaryDirectory() as d:
            p = write_triage(pathlib.Path(d) / "t.json", EXAMPLE_TRIAGE)
            p.write_text(p.read_text().replace("release owner", "agent"))
            self.assertIn("the triage changed after it was approved", "\n".join(c.load_triage(p)[1]))
            p.with_name("t.json.sha256").unlink()
            self.assertIn("no approval record", "\n".join(c.load_triage(p)[1]))

    def test_citations(self):
        self.assertIsNone(c.citation_problem("[VSTATD-IF p.7 §4.2]"))
        self.assertIsNone(c.citation_problem("[CC1-PN §3]"))
        self.assertIn("no section", c.citation_problem("[CC1-PN §9.9]"))
        self.assertIn("give the page", c.citation_problem("[VSTATD-IF §4.2]"))
        self.assertIn("not of the form", c.citation_problem("VSTATD-IF 4.2"))
        self.assertIn("is on page 7", c.citation_problem("[VSTATD-IF p.9 §4.2]"))
        self.assertIsNone(c.citation_problem("[VSTATD-IF p.7 §4]"))
        justify = {"decision": "justify", "cites": ["[TR §4.1]"]}
        self.assertIn("must cite VSTATD-IF or CC1-PN", "\n".join(c.citation_problems(justify)))

    def test_id_pattern(self):
        p = c.id_pattern("F-012")
        self.assertTrue(p.search("// F-012: test") and p.search("TEST(A, F012Fixed)") and p.search("F_012"))
        self.assertFalse(p.search("F-0121") or p.search("XF-012"))


# ------------------------------------------------------------------------------------------------ build, size

FAKE_CMAKE = """#!/bin/sh
case "$1" in --version) echo "cmake version 3.28.3"; exit 0;; esac
[ -n "$FAKE_CMAKE_FAIL" ] && { echo "CMake Error: fake"; exit 1; }
while [ $# -gt 0 ]; do case "$1" in -S) src=$2; shift;; -B) b=$2; shift;; esac; shift; done
mkdir -p "$b"
cat > "$b/compile_commands.json" <<EOF
[{"directory": "$b", "file": "$src/src/a.cpp",
  "command": "/usr/bin/aarch64-linux-gnu-g++ --sysroot=/opt/cc1-sysroot $FAKE_FLAGS -c $src/src/a.cpp"}]
EOF
"""
FAKE_NINJA = """#!/bin/sh
[ -n "$FAKE_NINJA_OK" ] && { touch "$2/vstatd"; exit 0; }
echo "src/a.cpp:1:1: error: fake compiler error"
exit 1
"""
GOOD_FLAGS = "-Wall -Wextra -Werror -O2 -fstack-protector-strong -D_FORTIFY_SOURCE=2"


class Build(Tmp):
    def setUp(self):
        super().setUp()
        self.repo = Repo(self.tmp)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        for name, text in (("cmake", FAKE_CMAKE), ("ninja", FAKE_NINJA)):
            (self.bin / name).write_text(text)
            (self.bin / name).chmod(0o755)

    def env(self, **extra):
        return dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}", **extra)

    def build(self, **extra):
        return check("build", "--project", self.repo.path, "--results", self.results, env=self.env(**extra))

    def test_configuration_failure_is_fail(self):
        rc, out = self.build(FAKE_CMAKE_FAIL="1", FAKE_FLAGS=GOOD_FLAGS)
        self.assertEqual(rc, 1, out)

    def test_flags_switched_off_is_fail(self):
        rc, out = self.build(FAKE_FLAGS="-Wall -Wextra -O2 -fstack-protector-strong -D_FORTIFY_SOURCE=2 -Wno-error",
                             FAKE_NINJA_OK="1")
        self.assertEqual(rc, 1, out)
        self.assertIn("missing -Werror", out)
        self.assertIn("warnings switched off", out)

    def test_compiler_error_status_is_not_lost(self):
        rc, out = self.build(FAKE_FLAGS=GOOD_FLAGS)
        self.assertEqual(rc, 1, out)
        self.assertIn("fake compiler error", out)

    def test_flags_undone_later_fail(self):
        rc, out = self.build(FAKE_FLAGS=GOOD_FLAGS + " -O0 -U_FORTIFY_SOURCE", FAKE_NINJA_OK="1")
        self.assertEqual(rc, 1, out)
        self.assertIn("-O2 not in effect (-O0)", out)
        self.assertIn("-D_FORTIFY_SOURCE=2 not in effect", out)

    def test_pragma_switching_warnings_off_fails(self):
        self.repo.commit("F-013: x", text="#pragma GCC diagnostic ignored \"-Wall\"\nint main() { return 0; }\n")
        rc, out = self.build(FAKE_FLAGS=GOOD_FLAGS, FAKE_NINJA_OK="1")
        self.assertEqual(rc, 1, out)
        self.assertIn("hides code from the checks", out)

    def test_dirty_tree_is_blocked(self):
        (self.repo.path / "src" / "a.cpp").write_text("changed\n")
        rc, out = self.build(FAKE_FLAGS=GOOD_FLAGS)
        self.assertEqual(rc, 3, out)

    def test_option_cannot_loosen(self):
        rc, out = check("build", "--project", self.repo.path, "--results", self.results, "--no-werror",
                        env=self.env())
        self.assertEqual(rc, 2, out)


class Size(Tmp):
    def setUp(self):
        super().setUp()
        self.repo = Repo(self.tmp)
        self.results.mkdir()

    def build_result(self, size, digest=None, verdict="PASS", commit=None):
        art = self.results / "artifacts" / "vstatd"
        art.parent.mkdir(exist_ok=True)
        art.write_bytes(b"\0" * size)
        (self.results / "build.json").write_text(json.dumps({
            "check": "build", "verdict": verdict, "commit": commit or self.repo.head(), "local": False,
            "details": {"artifact": str(art), "digest": digest or c.sha256(art)}}))

    def size(self):
        return check("size", "--project", self.repo.path, "--results", self.results)

    def test_within_limit_passes(self):
        self.build_result(c.limits()["stripped_size_bytes"])
        self.assertEqual(self.size()[0], 0)

    def test_over_limit_fails(self):
        self.build_result(c.limits()["stripped_size_bytes"] + 1)
        self.assertEqual(self.size()[0], 1)

    def test_no_build_or_other_commit_or_changed_artifact_is_blocked(self):
        self.assertEqual(self.size()[0], 3)
        self.build_result(1000, commit="1" * 40)
        self.assertEqual(self.size()[0], 3)
        self.build_result(1000, digest=DIGEST)
        self.assertEqual(self.size()[0], 3)


# ------------------------------------------------------------------------------------------------ static, unit

class Static(unittest.TestCase):
    rows = {"F-013": {"id": "F-013", "tool": "cppcheck", "check": "passedByValue", "file": "src/ipc_server.cpp",
                      "func": "IpcServer::broadcast", "msg": "m13", "note": None, "label": "fix"},
            "F-018": {"id": "F-018", "tool": "clang-tidy", "check": "cert-err34-c", "file": "src/client_session.cpp",
                      "func": "parse_interval", "msg": "m18", "note": None, "label": "fix"},
            "F-019": {"id": "F-019", "tool": "cppcheck", "check": "uselessCallsSubstr", "file": "src/client_session.cpp",
                      "func": "ClientSession::parse_line", "msg": "m19", "note": None, "label": "later"}}

    def finding(self, fid, line=10):
        r = self.rows[fid]
        return (r["tool"], r["check"], r["file"], r["func"], r["msg"], line, "")

    def test_consistent_with_triage_passes(self):
        decided = {"F-013": {"decision": "fix"}, "F-018": {"decision": "defer"}}
        reasons, _ = check_static.judge([self.finding("F-018"), self.finding("F-019")], self.rows, decided, {})
        self.assertEqual(reasons, [])

    def test_new_finding_fails(self):
        new = ("cppcheck", "nullPointer", "src/a.cpp", "f", "Null pointer dereference", 3, "")
        reasons, _ = check_static.judge([self.finding("F-018"), self.finding("F-019"), new], self.rows,
                                        {"F-013": {"decision": "fix"}, "F-018": {"decision": "defer"}}, {})
        self.assertTrue(any("new finding" in x for x in reasons))

    def test_fix_still_reported_fails(self):
        reasons, _ = check_static.judge([self.finding("F-013"), self.finding("F-018"), self.finding("F-019")],
                                        self.rows, {"F-013": {"decision": "fix"}, "F-018": {"decision": "defer"}}, {})
        self.assertTrue(any("F-013: triaged as fix but still reported" in x for x in reasons))

    def test_deferred_or_later_finding_gone_fails(self):
        reasons, _ = check_static.judge([], self.rows, {"F-013": {"decision": "fix"}, "F-018": {"decision": "defer"}}, {})
        self.assertTrue(any(x.startswith("F-018: no longer reported") for x in reasons))
        self.assertTrue(any(x.startswith("F-019: no longer reported") for x in reasons))

    def test_justified_needs_a_named_suppression(self):
        decided = {"F-013": {"decision": "fix"}, "F-018": {"decision": "justify"}}
        reasons, _ = check_static.judge([self.finding("F-019")], self.rows, decided, {})
        self.assertTrue(any("no suppression names it" in x for x in reasons))
        reasons, _ = check_static.judge([self.finding("F-019")], self.rows, decided, {"F-018": ["src/x.cpp:1"]})
        self.assertEqual(reasons, [])

    def suppressions(self, files, decided):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d)
            (p / "src").mkdir()
            for name, text in files.items():
                (p / "src" / name).write_text(text)
            return check_static.suppression_problems(p, decided, c.backlog_rows())

    def test_suppressions_follow_tr_3_2(self):
        problems, named = self.suppressions({
            "client_session.cpp": "int parse_interval(const char* s) {\n"
                                  "    return atoi(s);  // NOLINT(cert-err34-c) F-018 justified\n"
                                  "}\n",
            "a.cpp": "int b = atoi(s);  // NOLINT\n"
                     "f(line);  // cppcheck-suppress passedByValue ; F-013 justified\n"
                     "int g(const char* x) {\n    return atoi(x);  // NOLINTNEXTLINE(cert-err34-c) F-018 justified\n}\n"},
            {"F-018": {"decision": "justify"}, "F-013": {"decision": "fix"}})
        self.assertEqual(list(named), ["F-018"])
        text = "\n".join(problems)
        self.assertEqual(len(problems), 3, text)
        self.assertIn("not in a form of TR §3.2", text)
        self.assertIn("does not justify", text)

    def test_a_justification_covers_its_own_finding_once(self):
        problems, _ = self.suppressions({
            "client_session.cpp": "int parse_interval(const char* s) {\n"
                                  "    return atoi(s);  // NOLINT(cert-err34-c) F-018 justified\n"
                                  "}\n"
                                  "int other(const char* s) {\n"
                                  "    return atoi(s);  // NOLINT(cert-err34-c) F-018 justified\n"
                                  "}\n"}, {"F-018": {"decision": "justify"}})
        self.assertIn("not in src/client_session.cpp › other", "\n".join(problems))

    def test_hidden_code_is_found(self):
        with tempfile.TemporaryDirectory() as d:
            (pathlib.Path(d) / "src").mkdir()
            (pathlib.Path(d) / "src" / "a.cpp").write_text("#ifndef __CPPCHECK__\nint x;\n#endif\n")
            (pathlib.Path(d) / "tests").mkdir()
            (pathlib.Path(d) / "tests" / "t.cpp").write_text(
                'extern "C" const char* __tsan_default_suppressions() { return "race:x"; }\n')
            problems = c.hiding_problems(d)
        self.assertEqual(len(problems), 2)


class UnitReport(Tmp):
    def report(self, tests):
        p = self.tmp / "gtest.json"
        suites = {}
        for name, result, failed in tests:
            s, t = name.split(".")
            suites.setdefault(s, []).append({"name": t, "status": "RUN", "result": result,
                                             **({"failures": [{"failure": "x"}]} if failed else {})})
        p.write_text(json.dumps({"tests": len(tests), "disabled": 0, "testsuites": [
            {"name": s, "testsuite": ts} for s, ts in suites.items()]}))
        return p

    def judge(self, report, rc=0, log=""):
        r = c.Result("unit", self.results, "unit test")
        return check_unit.judge_report(report, rc, log, "plain", r)[0], r

    def test_all_passed(self):
        self.assertEqual(self.judge(self.report([("A.B", "COMPLETED", False)]))[0], c.PASS)

    def test_failed_test(self):
        self.assertEqual(self.judge(self.report([("A.B", "COMPLETED", True)]), rc=1)[0], c.FAIL)

    def test_skipped_is_not_a_pass(self):
        self.assertEqual(self.judge(self.report([("A.B", "COMPLETED", False), ("A.C", "SKIPPED", False)]))[0], c.FAIL)

    def test_no_test_ran_is_blocked(self):
        self.assertEqual(self.judge(self.report([]))[0], c.BLOCKED)

    def test_sanitizer_stop_before_report(self):
        v, r = self.judge(self.tmp / "missing.json", rc=66,
                          log="WARNING: ThreadSanitizer: data race (pid=1)\nSUMMARY: ThreadSanitizer: data race x\n")
        self.assertEqual(v, c.FAIL)
        self.assertTrue(any("ThreadSanitizer" in x for x in r.data["reasons"]))

    def test_sanitizer_output_with_exit_status_0_fails(self):
        v, _ = self.judge(self.report([("A.B", "COMPLETED", False)]), log="x.cpp:3:1: runtime error: overflow\n")
        self.assertEqual(v, c.FAIL)

    def test_no_report_with_exit_status_0_is_blocked(self):
        self.assertEqual(self.judge(self.tmp / "missing.json")[0], c.BLOCKED)

    def test_base_tests_are_found(self):
        repo = Repo(self.tmp)
        self.assertEqual(set(check_unit.base_blocks(repo.path, repo.base)), {"A.Works"})

    def test_test_blocks_end_at_the_body(self):
        blocks = check_unit.test_blocks('TEST(A, B) {\n  f("}");  // F-031\n}\n// F-032\nTEST_P(P, C) {}\n')
        self.assertEqual(set(blocks), {"A.B", "P.C"})
        self.assertIn("F-031", blocks["A.B"])
        self.assertNotIn("F-032", blocks["A.B"] + blocks["P.C"])

    def test_parameterised_names_and_sanitizers_in_effect(self):
        self.assertEqual(check_unit.normalize("Inst/Suite.Name/3"), "Suite.Name")
        on = check_unit.sanitizers_in_effect({"command": "g++ -fsanitize=thread -fno-sanitize=thread -c a.cpp"})
        self.assertEqual(on, set())
        on = check_unit.sanitizers_in_effect({"arguments": ["g++", "-fsanitize=address,undefined", "-c", "a.cpp"]})
        self.assertEqual(on, {"address", "undefined"})


# ------------------------------------------------------------------------------------------------ trace

class Trace(Tmp):
    def setUp(self):
        super().setUp()
        self.repo = Repo(self.tmp)

    def trace(self, triage=None):
        return check("trace", "--project", self.repo.path, "--results", self.results,
                     "--triage", triage or self.triage(self.repo.base))

    def test_traced_batch_passes(self):
        self.repo.commit("F-013: pass the line by const reference")
        self.repo.commit("F-018: parse the interval with strtol (IPC-REQUESTS, ERR-CODES)")
        rc, out = self.trace()
        self.assertEqual(rc, 0, out)

    def test_untraced_commit_fails(self):
        self.repo.commit("F-013: pass the line by const reference")
        self.repo.commit("F-018: strtol (IPC-REQUESTS)")
        self.repo.commit("Tidy up")
        rc, out = self.trace()
        self.assertEqual(rc, 1, out)
        self.assertIn("cites no finding", out)

    def test_deferred_or_unknown_finding_fails(self):
        self.repo.commit("F-013 and F-001: tidy")
        self.repo.commit("F-018: strtol (ERR-CODES); also F-099")
        rc, out = self.trace()
        self.assertEqual(rc, 1, out)
        self.assertIn("F-001, which the approved triage does not fix or justify", out)
        self.assertIn("F-099, which is neither in the backlog", out)

    def test_behaviour_without_fact_and_fix_without_commit_fail(self):
        self.repo.commit("F-018: parse the interval with strtol")
        rc, out = self.trace()
        self.assertEqual(rc, 1, out)
        self.assertIn("touches behaviour; the commit cites none of its fact entries", out)
        self.assertIn("F-013: triaged as fix, but no commit cites it", out)

    def test_justification_without_citation_fails(self):
        t = copy.deepcopy(EXAMPLE_TRIAGE)
        f18 = next(f for f in t["findings"] if f["id"] == "F-018")
        f18.update(decision="justify", cites=["[VSTATD-IF p.8 §5.9]"])
        self.repo.commit("F-013: const reference")
        t["base"] = self.repo.base
        rc, out = self.trace(write_triage(self.tmp / "t2.json", t))
        self.assertEqual(rc, 1, out)
        self.assertIn("no section §5.9", out)

    def test_empty_batch_and_unapproved_triage_are_blocked(self):
        self.assertEqual(self.trace()[0], 3)
        self.repo.commit("F-013: const reference")
        self.assertEqual(self.trace(self.triage(self.repo.base, approved={}))[0], 3)


# ------------------------------------------------------------------------------------------------ run checks

BASELINE = [
    {"t_ms": 4, "ev": "SERVICE_START", "version": "2.7.0"},
    {"t_ms": 6, "ev": "SERVICE_READY"},
    {"t_ms": 412, "ev": "GATEWAY_CONNECTED"},
    {"t_ms": 831, "ev": "SIGNAL_VALUE", "path": "Vehicle.Speed", "value": "0.00", "status": "AVAILABLE"},
    {"t_ms": 840, "ev": "SIGNAL_VALUE", "path": "Vehicle.Powertrain.Transmission.CurrentGear", "value": "0",
     "status": "AVAILABLE"},
    {"t_ms": 840, "ev": "SIGNAL_VALUE", "path": "Vehicle.Powertrain.Transmission.SelectedGear", "value": "0",
     "status": "AVAILABLE"},
    {"t_ms": 1200, "ev": "CLIENT_CONNECTED", "client": "1"},
    {"t_ms": 5130, "ev": "SIGNAL_VALUE", "path": "Vehicle.Speed", "value": "12.30", "status": "AVAILABLE"},
    {"t_ms": 9000, "ev": "CLIENT_DISCONNECTED", "client": "1"},
    {"t_ms": 9010, "ev": "SERVICE_STOP", "reason": "signal"},
]
RESULT = {"replay_id": "drive-01", "target": "emulated-cc1",
          "qemu_command": "qemu-system-aarch64 -M virt -cpu cortex-a57 -smp 4 -m 512 -icount shift=3,sleep=off",
          "replay_finished": True, "replay_end": "player-end-of-drive",
          "figures_after_replay_end": True, "vm_hwm_kib": 7400, "threads_at_end": 3, "cpu_ms": 2100,
          "approved_digest": DIGEST, "readback_digest": DIGEST}


class RunChecks(Tmp):
    def write(self, name, entries, result, lines=None):
        d = self.tmp / name
        d.mkdir(exist_ok=True)
        log = "run.jsonl" if name == "run" else "baseline.jsonl"
        text = lines if lines is not None else "".join(json.dumps(e, separators=(",", ":")) + "\n" for e in entries)
        (d / log).write_text(text)
        (d / ("run-result.json" if name == "run" else "baseline-result.json")).write_text(json.dumps(result))
        return d

    def go(self, check_name, run=None, result=None, lines=None, triage=None, baseline_result=None, extra=(), env=None):
        b = self.write("baseline", BASELINE, baseline_result or dict(RESULT, vm_hwm_kib=7300, cpu_ms=2000))
        r = self.write("run", BASELINE if run is None else run, dict(RESULT, **(result or {})), lines)
        args = ["--run", r, "--baseline", b, "--results", self.results, *extra]
        if check_name == "logdiff":
            args += ["--triage", triage or self.triage("0" * 40)]
        return check(check_name, *args, env=env)


class RuntimeLimits(RunChecks):
    def test_within_limits_passes(self):
        rc, out = self.go("runtime-limits")
        self.assertEqual(rc, 0, out)
        self.assertIn("emulation", out)

    def test_over_peak_rss_or_threads_fails(self):
        self.assertEqual(self.go("runtime-limits", result={"vm_hwm_kib": 8193})[0], 1)
        self.assertEqual(self.go("runtime-limits", result={"threads_at_end": 5})[0], 1)

    def test_run_not_ended_is_blocked(self):
        self.assertEqual(self.go("runtime-limits", result={"replay_finished": False})[0], 3)
        self.assertEqual(self.go("runtime-limits", result={"figures_after_replay_end": False})[0], 3)
        self.assertEqual(self.go("runtime-limits", run=BASELINE[:-1])[0], 3)

    def test_end_by_script_exit_is_blocked(self):
        self.assertEqual(self.go("runtime-limits", result={"replay_end": "replay script exited 0"})[0], 3)

    def test_not_the_approved_build_fails(self):
        self.assertEqual(self.go("runtime-limits", result={"readback_digest": "cd" * 32})[0], 1)

    def test_missing_figures_or_icount_is_blocked(self):
        self.assertEqual(self.go("runtime-limits", result={"vm_hwm_kib": None})[0], 3)
        self.assertEqual(self.go("runtime-limits", result={"qemu_command": "qemu-system-aarch64 -icount shift=auto"})[0], 3)

    def test_limit_cannot_be_loosened(self):
        self.assertEqual(self.go("runtime-limits", result={"vm_hwm_kib": 9000}, extra=["--peak-rss-kib", "99999"])[0], 2)
        env = dict(os.environ, PEAK_RSS_KIB="99999", VSTATD_PEAK_RSS_KIB="99999")
        self.assertEqual(self.go("runtime-limits", result={"vm_hwm_kib": 9000}, env=env)[0], 1)


class LogDiff(RunChecks):
    def test_same_log_passes(self):
        self.assertEqual(self.go("logdiff")[0], 0)

    def test_timing_within_window_and_ignored_version_pass(self):
        run = copy.deepcopy(BASELINE)
        run[0]["version"] = "2.7.1"
        for e in run[2:]:
            e["t_ms"] += 20
        self.assertEqual(self.go("logdiff", run=run)[0], 0)

    def test_timing_outside_window_fails(self):
        run = copy.deepcopy(BASELINE)
        run[7]["t_ms"] += 21
        rc, out = self.go("logdiff", run=run)
        self.assertEqual(rc, 1, out)

    def test_extra_timeout_fails_and_is_shown(self):
        run = copy.deepcopy(BASELINE)
        run[3:3] = [{"t_ms": 480, "ev": "SIGNAL_TIMEOUT", "message": "VCU_Speed"},
                    {"t_ms": 480, "ev": "SIGNAL_VALUE", "path": "Vehicle.Speed", "value": "-", "status": "UNAVAILABLE"},
                    {"t_ms": 831, "ev": "SIGNAL_RECOVERED", "message": "VCU_Speed"}]
        rc, out = self.go("logdiff", run=run)
        self.assertEqual(rc, 1, out)
        diff = (self.results / "logdiff.diff").read_text()
        self.assertIn('+ {"t_ms":480,"ev":"SIGNAL_TIMEOUT","message":"VCU_Speed"}', diff)

    def test_missing_entry_fails(self):
        rc, out = self.go("logdiff", run=BASELINE[:7] + BASELINE[8:])
        self.assertEqual(rc, 1, out)
        self.assertIn("only in the baseline", out)

    def test_allowed_difference_passes(self):
        run = BASELINE[:7] + BASELINE[8:]
        t = self.triage("0" * 40, allowed_log_differences=[
            {"finding": "F-018", "side": "baseline", "entry": BASELINE[7]}])
        rc, out = self.go("logdiff", run=run, triage=t)
        self.assertEqual(rc, 0, out)

    def test_allowed_difference_needs_a_decided_finding(self):
        t = self.triage("0" * 40, allowed_log_differences=[
            {"finding": "F-001", "side": "baseline", "entry": BASELINE[7]}])
        self.assertEqual(self.go("logdiff", run=BASELINE[:7] + BASELINE[8:], triage=t)[0], 3)

    def test_order_within_a_step_fails(self):
        run = copy.deepcopy(BASELINE)
        run[4], run[5] = run[5], run[4]
        rc, out = self.go("logdiff", run=run)
        self.assertEqual(rc, 1, out)
        self.assertIn("order within one decoding step", out)

    def test_bad_line_fails(self):
        text = "".join(json.dumps(e) + "\n" for e in BASELINE[:3]) + "Segmentation fault\n" + json.dumps(BASELINE[-1])
        self.assertEqual(self.go("logdiff", lines=text)[0], 1)

    def test_fields_out_of_order_unknown_event_or_duplicate_key_fail(self):
        base = "".join(json.dumps(e, separators=(",", ":")) + "\n" for e in BASELINE)
        swapped = base.replace('"path":"Vehicle.Speed","value":"12.30"', '"value":"12.30","path":"Vehicle.Speed"')
        self.assertEqual(self.go("logdiff", lines=swapped)[0], 1)
        self.assertEqual(self.go("logdiff", lines=base.replace("CLIENT_CONNECTED", "CLIENT_JOINED"))[0], 1)
        self.assertEqual(self.go("logdiff", lines=base.replace('"client":"1"}', '"client":"1","client":"2"}', 1))[0], 1)
        self.assertEqual(self.go("logdiff", lines="null\n" + base)[0], 1)

    def test_empty_or_unfinished_log_is_blocked(self):
        self.assertEqual(self.go("logdiff", lines="")[0], 3)
        self.assertEqual(self.go("logdiff", run=BASELINE[:-1])[0], 3)

    def test_not_comparable_is_blocked(self):
        self.assertEqual(self.go("logdiff", result={"replay_id": "drive-02"})[0], 3)
        self.assertEqual(self.go("logdiff", result={"qemu_command": "qemu -icount shift=4,sleep=off"})[0], 3)

    def test_pairing_takes_the_first_matching_entry(self):
        b = [{"t_ms": 100, "ev": "X"}, {"t_ms": 110, "ev": "X"}]
        r = [{"t_ms": 95, "ev": "X"}, {"t_ms": 125, "ev": "X"}]
        pairs, ob, orun, order = check_logdiff.compare(b, r, 20, {})
        self.assertEqual((pairs, ob, orun, order), ({0: 0, 1: 1}, [], [], []))


# ------------------------------------------------------------------------------------------------ release

class Release(Tmp):
    def setUp(self):
        super().setUp()
        self.repo = Repo(self.tmp)
        self.repo.commit("F-013: const reference")
        self.t = self.triage(self.repo.base)
        self.results.mkdir()
        self.run_log = self.tmp / "run.jsonl"
        self.run_log.write_text("x\n")
        for name in ("build", "static", "unit", "size", "trace", "runtime-limits", "logdiff"):
            self.result(name)

    def result(self, name, **changes):
        tier = {"unit": "unit test", "runtime-limits": "emulation", "logdiff": "emulation"}.get(name, "n/a")
        data = {"check": name, "verdict": "PASS", "commit": None if name in ("runtime-limits", "logdiff")
                else self.repo.head(), "local": False, "tier": tier, "inputs": {}, "details": {}}
        if name in ("static", "unit", "trace", "logdiff"):
            data["inputs"]["triage"] = {"path": str(self.t), "sha256": c.sha256(self.t)}
        if name in ("build", "size"):
            data["details"]["digest"] = DIGEST
        if name in ("runtime-limits", "logdiff"):
            data["details"].update(deployed_digest=DIGEST, approved_digest=DIGEST)
            data["inputs"]["run_log"] = {"path": str(self.run_log), "sha256": c.sha256(self.run_log)}
        data.update(changes)
        (self.results / f"{name}.json").write_text(json.dumps(data))

    def release(self, triage=None):
        return check("release", "--project", self.repo.path, "--results", self.results, "--triage", triage or self.t)

    def test_complete_consistent_set_passes(self):
        rc, out = self.release()
        self.assertEqual(rc, 0, out)
        rc, out = check("evidence-page", "--results", self.results, "--triage", self.t)
        self.assertEqual(rc, 0, out)
        page = (self.results / "evidence.md").read_text()
        self.assertIn("| `logdiff` | **PASS** | emulation |", page)
        self.assertIn("## What emulation cannot show", page)
        self.assertIn("Release check: **PASS**", page)

    def test_missing_result_fails(self):
        (self.results / "logdiff.json").unlink()
        self.assertEqual(self.release()[0], 1)

    def test_not_passed_fails(self):
        self.result("unit", verdict="BLOCKED")
        self.assertEqual(self.release()[0], 1)

    def test_other_commit_fails(self):
        self.result("static", commit=self.repo.base)
        self.assertEqual(self.release()[0], 1)

    def test_local_result_fails(self):
        self.result("trace", local=True)
        self.assertEqual(self.release()[0], 1)

    def test_other_build_on_the_bench_fails(self):
        self.result("logdiff", details={"deployed_digest": "cd" * 32, "approved_digest": "cd" * 32})
        self.assertEqual(self.release()[0], 1)

    def test_input_changed_after_the_check_fails(self):
        self.run_log.write_text("y\n")
        self.assertEqual(self.release()[0], 1)

    def test_other_triage_fails(self):
        other = write_triage(self.tmp / "other.json", json.loads(self.t.read_text().replace("release owner", "someone else")))
        self.assertEqual(self.release(other)[0], 1)

    def test_runs_of_the_two_after_deploy_checks_differ(self):
        other = self.tmp / "other-run.jsonl"
        other.write_text("z\n")
        self.result("logdiff", inputs={"triage": {"path": str(self.t), "sha256": c.sha256(self.t)},
                                       "run_log": {"path": str(other), "sha256": c.sha256(other)}})
        rc, out = self.release()
        self.assertEqual(rc, 1, out)
        self.assertIn("judged different runs or baselines", out)

    def test_real_target_only_requirement_is_blocked_by_tier(self):
        t = self.triage(self.repo.base, requirements=[
            {"id": "REQ-CPU", "real_target_only": True, "evidence": ["runtime-limits"]}])
        for name in ("static", "unit", "trace", "logdiff"):
            self.result(name, inputs={"triage": {"path": str(t), "sha256": c.sha256(t)}})
        rc, out = self.release(t)
        self.assertEqual(rc, 1, out)
        self.assertIn("reported as blocked, not passed", out)
        check("evidence-page", "--results", self.results, "--triage", t)
        self.assertIn("## Blocked by evidence tier", (self.results / "evidence.md").read_text())

    def test_dirty_final_tree_fails(self):
        (self.repo.path / "src" / "a.cpp").write_text("dirty\n")
        self.assertEqual(self.release()[0], 1)


if __name__ == "__main__":
    unittest.main(verbosity=1)
