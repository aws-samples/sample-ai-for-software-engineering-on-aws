#!/usr/bin/env python3
# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""checks/unit.sh: the unit tests on the build server, in the three builds of [TR §2.2].

Builds the tests of the committed tree three times (plain, ThreadSanitizer, AddressSanitizer with
UndefinedBehaviorSanitizer), verifies from compile_commands.json that every file of a sanitizer build has the
sanitizer in effect, runs each test binary in a clean environment with the sanitizers set to stop at the first
report, and judges by exit status and the GoogleTest JSON report. Pass: in every build at least one test runs, none
fails, none is skipped or disabled, no sanitizer reports anything, and every test of the batch's base commit runs; no
source disables or tunes a sanitizer; every finding triaged as fix with evidence unit-test has a test, new or changed
in the batch and run in the plain build, that names it in its name or body (`F-nnn`, `Fnnn` or `F_nnn`).
"""

import json
import pathlib
import re
import shlex
import shutil
import sys

import common as c

BUILDS = (("plain", None), ("tsan", "thread"), ("asan", "address,undefined"))
TEST_DEF = re.compile(r"^\s*(?:TEST|TEST_F|TEST_P|TYPED_TEST|TYPED_TEST_P)\(\s*(\w+)\s*,\s*(\w+)\s*\)", re.M)
SANITIZER = re.compile(r"(WARNING: ThreadSanitizer: .*|ERROR: AddressSanitizer: .*|ERROR: LeakSanitizer: .*|"
                       r"SUMMARY: \w+Sanitizer: .*|.*runtime error: .*)")
SANITIZER_ENV = {"TSAN_OPTIONS": "halt_on_error=1:second_deadlock_stack=1",
                 "ASAN_OPTIONS": "halt_on_error=1:detect_leaks=1",
                 "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1", "LSAN_OPTIONS": ""}


def normalize(name):
    """Suite.Name of a test as GoogleTest runs it (Prefix/Suite.Name/0 for parameterised tests)."""
    suite, _, test = name.partition(".")
    return f"{suite.rsplit('/', 1)[-1]}.{test.split('/', 1)[0]}"


def test_blocks(text):
    """Suite.Name -> the text of its definition, from the macro to the closing brace of its body."""
    code = re.sub(r'"(?:\\.|[^"\\\n])*"', lambda m: '"' + " " * (len(m.group(0)) - 2) + '"', text)
    code = re.sub(r"'(?:\\.|[^'\\\n])*'", lambda m: "'" + " " * (len(m.group(0)) - 2) + "'", code)
    code = re.sub(r"//[^\n]*", lambda m: " " * len(m.group(0)), code)
    blocks = {}
    for m in TEST_DEF.finditer(text):
        start = code.find("{", m.end())
        depth, end = 0, len(text)
        for i in range(start, len(code)) if start >= 0 else ():
            depth += {"{": 1, "}": -1}.get(code[i], 0)
            if depth == 0:
                end = i + 1
                break
        blocks[f"{m.group(1)}.{m.group(2)}"] = text[m.start():end]
    return blocks


def base_blocks(project, base):
    blocks = {}
    files = c.git(project, "ls-tree", "-r", "--name-only", base, "--", "tests").stdout.split()
    for f in files:
        if f.endswith(".cpp"):
            blocks.update(test_blocks(c.git(project, "show", f"{base}:./{f}").stdout))
    return blocks


def sanitizers_in_effect(entry):
    args = entry.get("arguments") or shlex.split(entry["command"])
    on = set()
    for a in args:
        for prefix, add in (("-fsanitize=", True), ("-fno-sanitize=", False)):
            if a.startswith(prefix):
                for s in a[len(prefix):].split(","):
                    (on.add if add else on.discard)(s)
    return on


def judge_report(report, rc, log_text, build, r):
    """Verdict of one build's run from its exit status and its GoogleTest JSON report."""
    sanitizer = sorted(set(SANITIZER.findall(log_text)))[:5]
    for s in sanitizer:
        r.reason(f"{build}: {s.strip()}")
    try:
        data = json.loads(pathlib.Path(report).read_text())
    except (OSError, ValueError):
        data = None
    if not isinstance(data, dict):
        if rc == 0:
            r.reason(f"{build}: the test binary exited 0 but wrote no report")
            return c.BLOCKED, set()
        r.reason(f"{build}: test binary exited with {rc} before writing its report")
        return c.FAIL, set()
    names, skipped, failed = set(), [], []
    for suite in data.get("testsuites", []):
        for t in suite.get("testsuite", []):
            name = f"{suite['name']}.{t['name']}"
            names.add(normalize(name))
            if t.get("result") != "COMPLETED" or t.get("status") == "NOTRUN":
                skipped.append(name)
            if t.get("failures"):
                failed.append(name)
    total = data.get("tests", 0)
    for n in failed[:10]:
        r.reason(f"{build}: FAILED {n}")
    for n in skipped[:10]:
        r.reason(f"{build}: skipped or disabled {n} (a test that did not run is not a pass)")
    disabled = data.get("disabled", 0)
    if disabled and not skipped:
        r.reason(f"{build}: {disabled} disabled test(s)")
    r.data["details"].setdefault("runs", {})[build] = {"exit_status": rc, "tests": total, "failures": len(failed),
                                                       "skipped_or_disabled": len(skipped) or disabled,
                                                       "sanitizer_reports": len(sanitizer)}
    if total == 0 and rc == 0:
        r.reason(f"{build}: no test ran")
        return c.BLOCKED, names
    if rc != 0 or failed or skipped or disabled or sanitizer:
        if rc == 0 and not (failed or skipped or disabled):
            r.reason(f"{build}: sanitizer output with exit status 0")
        return c.FAIL, names
    return c.PASS, names


def body(args, r):
    project = pathlib.Path(args.project).resolve()
    commit, why = c.judged_commit(project, args.local)
    if why:
        r.reason(why)
        return c.BLOCKED, "cannot judge the tree"
    r.data["commit"], r.data["local"] = commit, args.local
    triage, problems = c.load_triage(args.triage)
    r.input("triage", args.triage)
    if problems:
        for p in problems:
            r.reason(f"triage: {p}")
        return c.BLOCKED, "no valid approved triage"
    base = triage["base"]
    if c.git(project, "cat-file", "-e", f"{base}^{{commit}}").returncode != 0:
        r.reason(f"base commit {base} of the triage is not in the project's history")
        return c.BLOCKED, "unknown base commit"
    before = base_blocks(project, base)
    if not before:
        r.reason(f"no test definitions found in tests/ of the base commit {base[:12]}")
        return c.BLOCKED, "cannot tell which tests must still run"
    r.data["tools"]["compiler"] = c.version("g++")
    work = pathlib.Path(args.results).resolve() / "work" / "unit"
    shutil.rmtree(work, ignore_errors=True)
    tree = c.materialize(project, args.local, work / "tree")
    verdicts = []
    for p in c.hiding_problems(tree, ("src", "tests")):
        r.reason(p)
        verdicts.append(c.FAIL)

    ran = {}
    for build, sanitize in BUILDS:
        bdir = work / build
        cfg = ["cmake", "-S", tree, "-B", bdir, "-G", "Ninja"]
        if sanitize:
            cfg.append(f"-DVSTATD_SANITIZE={sanitize}")
        if c.run(cfg, r.log) != 0 or c.run(["ninja", "-C", bdir, "vstatd_tests"], r.log) != 0:
            r.reason(f"{build}: the test build failed; see unit.log")
            verdicts.append(c.FAIL)
            continue
        if sanitize:
            db = bdir / "compile_commands.json"
            entries = json.loads(db.read_text()) if db.is_file() else []
            want = set(sanitize.split(","))
            off = [e["file"] for e in entries if not want <= sanitizers_in_effect(e)]
            if not entries or off:
                r.reason(f"{build}: {len(off) if entries else 'no'} file(s) compiled with -fsanitize={sanitize} in "
                         f"effect missing" + (f", e.g. {pathlib.Path(off[0]).name}" if off else ""))
                verdicts.append(c.FAIL)
                continue
        env = c.clean_env(**SANITIZER_ENV)
        report = bdir / "gtest.json"
        cmd = [bdir / "tests" / "vstatd_tests", f"--gtest_output=json:{report}"]
        if sanitize == "thread":
            cmd = ["setarch", "-R", *cmd]
        out = bdir / "test.log"
        rc = c.run(cmd, out, env=env)
        text = out.read_text(errors="replace")
        with open(r.log, "a") as f:
            f.write(text)
        verdict, names = judge_report(report, rc, text, build, r)
        verdicts.append(verdict)
        ran[build] = names
        missing = sorted(set(before) - names)
        if names and missing:
            r.reason(f"{build}: {len(missing)} test(s) of the base commit no longer run, e.g. {missing[0]}")
            verdicts.append(c.FAIL)

    after = {}
    for f in sorted((tree / "tests").rglob("*.cpp")):
        after.update(test_blocks(f.read_text(errors="replace")))
    for fid, f in sorted(c.decisions(triage).items()):
        if f["decision"] == "fix" and f.get("evidence") == "unit-test":
            pattern = c.id_pattern(fid)
            tests = [n for n, text in after.items() if pattern.search(text) and before.get(n) != text
                     and n in ran.get("plain", set())]
            r.data["details"].setdefault("tests_for_fixes", {})[fid] = tests
            if not tests:
                r.reason(f"{fid}: triaged as fix with evidence unit-test, but no test that is new or changed in the "
                         f"batch and runs names it (TR §4.1)")
                verdicts.append(c.FAIL)
    for v in (c.FAIL, c.BLOCKED):
        if v in verdicts:
            return v, "see reasons"
    return c.PASS, ", ".join(f"{b}: {d['tests']} tests" for b, d in r.data["details"]["runs"].items())


def add_args(p):
    p.add_argument("--project", default=".", help="the vstatd project (a git work tree)")
    p.add_argument("--triage", required=True, help="the approved triage (JSON, checks/README.md)")
    p.add_argument("--local", action="store_true", help="judge a dirty tree; release.sh rejects the result")


if __name__ == "__main__":
    sys.exit(c.main("unit", "unit test", add_args, body))
