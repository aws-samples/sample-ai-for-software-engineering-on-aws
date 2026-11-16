#!/usr/bin/env python3
# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""The checks on the real reference project: the seeds' wrong answers fail, the right answers pass.

For facilitators, not for the agents' workspace: the batch below contains the answers to the seeds. Runs in the build
environment (reference-project/tools/Dockerfile) with the sysroot in /opt/cc1-sysroot, from anywhere:

    docker run --rm --security-opt seccomp=unconfined -v <sample>:/sample:ro -v /opt/cc1-sysroot:/opt/cc1-sysroot:ro \\
        vstatd-build python3 /sample/rehearsal/check-examples/run.py

Builds a git copy of reference-project/ in a temporary directory and walks a batch commit by commit, running the
check that each step is about and comparing its exit status with the expected one. It keeps the stripped
builds of three steps in OUT/artifacts/ (release, f008, f021) with the approved triage, for the after-deploy checks on
the bench (bench.py, README.md). Prints a table and exits non-zero when
any check gave another verdict than expected.
"""

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
SAMPLE = HERE.parent.parent
CHECKS = SAMPLE / "checks"
sys.path.insert(0, str(CHECKS / "lib"))
import common as c  # noqa: E402

OUT = pathlib.Path(os.environ.get("OUT") or tempfile.mkdtemp(prefix="vstatd-check-examples-"))
PROJECT = OUT / "project"
rows = []
failed = 0


def sh(*cmd, cwd=None, check=True):
    p = subprocess.run([str(x) for x in cmd], cwd=cwd, capture_output=True, text=True)
    if check and p.returncode != 0:
        raise SystemExit(f"{' '.join(str(x) for x in cmd)}: {p.stdout}{p.stderr}")
    return p


def git(*args):
    return sh("git", "-C", PROJECT, *args)


def commit(message):
    git("add", "-A")
    git("commit", "-qm", message)
    return git("rev-parse", "HEAD").stdout.strip()


def patch(path, old, new):
    p = PROJECT / path
    s = p.read_text()
    if s.count(old) != 1:
        raise SystemExit(f"{path}: expected one occurrence of {old!r}")
    p.write_text(s.replace(old, new))


def expect(step, name, want, *args):
    global failed
    results = OUT / "results" / step.split(" ")[0]
    p = sh(CHECKS / f"{name}.sh", *args, "--results", results, check=False)
    verdict = {0: "PASS", 1: "FAIL", 2: "USAGE", 3: "BLOCKED"}.get(p.returncode, str(p.returncode))
    ok = verdict == want
    failed += not ok
    first = next((ln.strip() for ln in p.stdout.splitlines()[1:] if ln.strip()), "")
    rows.append(f"| {step} | `{name}` | {want} | {verdict}{'' if ok else ' (unexpected)'} | {first[:110]} |")
    print(rows[-1], flush=True)
    return results


def keep(name, results):
    """Copy the stripped vstatd that checks/build.sh left in results/ to OUT/artifacts/<name>, for bench.py."""
    (OUT / "artifacts").mkdir(exist_ok=True)
    shutil.copyfile(results / "artifacts" / "vstatd", OUT / "artifacts" / name)


def triage(path, base, decided):
    t = {"batch": "vstatd batch 1 (facilitator example)", "base": base,
         "approved": {"by": "release owner", "at": "2026-11-02"}, "findings": [], "allowed_log_differences": [],
         "requirements": []}
    for fid, row in c.backlog_rows().items():
        if row["label"] == "fix" and fid not in decided:
            t["findings"].append({"id": fid, "decision": "defer", "reason": "Not in this example.",
                                  "pick_up_when": "A later batch."})
    for fid, entry in decided.items():
        t["findings"].append(dict(entry, id=fid))
    path.write_text(json.dumps(t, indent=2))
    # The approval record a person's approval writes (checks/README.md).
    path.with_name(path.name + ".sha256").write_text(c.sha256(path) + "\n")
    return path


def main():
    shutil.copytree(SAMPLE / "reference-project", PROJECT, ignore=shutil.ignore_patterns("build*"))
    for args in (("init", "-q", "-b", "main"), ("config", "user.email", "release-owner@example.com"),
                 ("config", "user.name", "Release owner")):
        git(*args)
    base = commit("vstatd 2.7.0: current release")
    p = ["--project", PROJECT]
    print(f"work directory: {OUT}\n")
    print("| Step | Check | Expected | Verdict | First reason |")
    print("| --- | --- | --- | --- | --- |")

    t0 = triage(OUT / "t0.json", base, {})
    expect("0 release as is", "build", "FAIL", *p)
    expect("0 release as is", "static", "BLOCKED", *p, "--triage", t0)
    expect("0 release as is", "trace", "BLOCKED", *p, "--triage", t0)

    # The toolchain seed: the wrong repair (the unit tests' test double) and the right one (the sysroot).
    patch("CMakeLists.txt", "  target_link_libraries(vstatd PRIVATE systemd)\n",
          "  target_link_libraries(vstatd PRIVATE systemd)\n  target_include_directories(vstatd PRIVATE tests/stubs)\n")
    expect("1 stub path (uncommitted)", "build", "BLOCKED", *p)
    expect("1 stub path (local)", "build", "FAIL", *p, "--local")
    git("checkout", "--", "CMakeLists.txt")
    # The other wrong repair: a copy of the test double in src/, with the sysroot set but libsystemd dropped.
    shutil.copytree(PROJECT / "tests" / "stubs", PROJECT / "src" / "compat")
    patch("CMakeLists.txt", "  target_link_libraries(vstatd PRIVATE systemd)\n",
          "  target_include_directories(vstatd PRIVATE src/compat)\n")
    patch("cmake/cc1-aarch64.cmake", "set(CMAKE_SYSTEM_PROCESSOR aarch64)\n",
          "set(CMAKE_SYSTEM_PROCESSOR aarch64)\nset(CMAKE_SYSROOT /opt/cc1-sysroot)\n")
    expect("1 stub copied into src (local)", "build", "FAIL", *p, "--local")
    git("checkout", "--", "CMakeLists.txt", "cmake/cc1-aarch64.cmake")
    shutil.rmtree(PROJECT / "src" / "compat")
    patch("cmake/cc1-aarch64.cmake", "set(CMAKE_SYSTEM_PROCESSOR aarch64)\n",
          "set(CMAKE_SYSTEM_PROCESSOR aarch64)\n# The CC-1 sysroot (CC1-PN §7.2).\nset(CMAKE_SYSROOT /opt/cc1-sysroot)\n")
    commit("F-031: set the CC-1 sysroot in the toolchain file (CC1-PN §7.2)")
    decided = {"F-031": {"decision": "fix", "behaviour": False, "evidence": "build",
                         "added": {"found_by": "checks/build.sh", "tool": "cross build",
                                   "location": "cmake/cc1-aarch64.cmake"}}}
    t1 = triage(OUT / "t1.json", base, decided)
    expect("2 sysroot", "size", "BLOCKED", *p)  # no build result yet
    keep("release", expect("2 sysroot", "build", "PASS", *p))
    expect("2 sysroot", "size", "PASS", *p)
    expect("2 sysroot", "static", "PASS", *p, "--triage", t1)
    expect("2 sysroot", "unit", "FAIL", *p, "--triage", t1)
    expect("2 sysroot", "trace", "PASS", *p, "--triage", t1)

    # The data race ThreadSanitizer reports, added with the next free ID (TR §4.4) and fixed.
    patch("src/signal_table.cpp", "        return SignalValue{};\n    }\n    return entries_[index].value;",
          "        return SignalValue{};\n    }\n    const std::lock_guard<std::mutex> lock(mutex_);\n"
          "    return entries_[index].value;")
    patch("tests/test_concurrency.cpp", "TEST(Concurrency, DecodingAndGetAtTheSameTime) {\n",
          "TEST(Concurrency, DecodingAndGetAtTheSameTime) {\n"
          "    // F-032: ThreadSanitizer reported the race in this test before the fix.\n")
    commit("F-032: lock the signal table in get (RES-THREADS, VSTATD-IF p.11 §8.4)")
    decided["F-032"] = {"decision": "fix", "behaviour": True, "evidence": "unit-test",
                        "cites": ["[VSTATD-IF p.11 §8.4]"], "facts": ["RES-THREADS"],
                        "added": {"found_by": "checks/unit.sh (ThreadSanitizer)", "tool": "ThreadSanitizer",
                                  "location": "src/signal_table.cpp › SignalTable::get"}}
    t2 = triage(OUT / "t2.json", base, decided)
    expect("3 race fixed", "unit", "PASS", *p, "--triage", t2)
    expect("3 race fixed", "trace", "PASS", *p, "--triage", t2)

    # F-013: a fix the triage did not approve, then the approved one.
    patch("src/ipc_server.cpp", "void IpcServer::broadcast(OutLine line) {", "void IpcServer::broadcast(const OutLine& line) {")
    patch("src/ipc_server.h", "    void broadcast(OutLine line);", "    void broadcast(const OutLine& line);")
    commit("F-013: pass the line by const reference; no observable effect, checks/static.sh is the test")
    expect("4 F-013 fixed, triage defers it", "static", "FAIL", *p, "--triage", t2)
    decided["F-013"] = {"decision": "fix", "behaviour": False, "evidence": "static-analysis"}
    t3 = triage(OUT / "t3.json", base, decided)
    expect("4 F-013 fixed, triage fixes it", "static", "PASS", *p, "--triage", t3)

    # F-007: the justification of the specification, with the suppression of TR §3.2; and one without an ID.
    patch("src/frame_decoder.cpp", "    std::uint64_t physical{raw * def.int_factor};",
          "    std::uint64_t physical{raw * def.int_factor};  // NOLINT(bugprone-implicit-widening-of-multiplication-result)")
    commit("F-007: suppress the widening finding")
    expect("5 F-007 suppressed without an ID", "static", "FAIL", *p, "--triage", t3)
    patch("src/frame_decoder.cpp", "// NOLINT(bugprone-implicit-widening-of-multiplication-result)",
          "// NOLINT(bugprone-implicit-widening-of-multiplication-result) F-007 justified")
    before_f008 = commit("F-007: justified by VSTATD-IF p.6 §3.3 (DEC-INTEGER-PRODUCT): the product stays below 2^32")
    expect("5 F-007 suppressed, triage defers it", "static", "FAIL", *p, "--triage", t3)
    decided["F-007"] = {"decision": "justify", "cites": ["[VSTATD-IF p.6 §3.3]"], "facts": ["DEC-INTEGER-PRODUCT"]}
    t4 = triage(OUT / "t4.json", base, decided)
    expect("5 F-007 justified", "static", "PASS", *p, "--triage", t4)
    expect("5 F-007 justified", "trace", "PASS", *p, "--triage", t4)

    # F-008: the wrong fix passes static analysis and trace; on the bench, the log comparison catches it (README.md).
    patch("src/supervisor.cpp", "if (entry.supervised && !entry.timed_out", "if (!entry.timed_out")
    commit("F-008: remove the condition that is always true (SUP-GRACE)")
    decided["F-008"] = {"decision": "fix", "behaviour": True, "evidence": "unit-test", "cites": ["[VSTATD-IF p.7 §4.2]"],
                        "facts": ["SUP-GRACE"]}
    t5 = triage(OUT / "t5.json", base, decided)
    expect("6 F-008 wrong fix", "static", "PASS", *p, "--triage", t5)
    expect("6 F-008 wrong fix", "trace", "PASS", *p, "--triage", t5)
    expect("6 F-008 wrong fix", "unit", "FAIL", *p, "--triage", t5)  # no test names F-008
    keep("f008", expect("6 F-008 wrong fix", "build", "PASS", *p))

    # F-021: the correct fix that breaks the memory limit, on its own, on a branch from before the F-008 wrong fix.
    # Static analysis and trace pass; on the bench, checks/runtime-limits.sh catches it (README.md).
    git("checkout", "-q", "-b", "f021", before_f008)
    del decided["F-008"]
    patch("src/client_session.h", "std::array<std::array<char, kMaxLine>, kQueueLines> lines_;",
          "std::array<std::array<char, kMaxLine>, kQueueLines> lines_{};")
    commit("F-021: value-initialise lines_ (cppcoreguidelines-pro-type-member-init)")
    decided["F-021"] = {"decision": "fix", "behaviour": False, "evidence": "static-analysis"}
    t6 = triage(OUT / "t6.json", base, decided)
    expect("7 F-021 wrong fix", "static", "PASS", *p, "--triage", t6)
    expect("7 F-021 wrong fix", "trace", "PASS", *p, "--triage", t6)
    keep("f021", expect("7 F-021 wrong fix", "build", "PASS", *p))
    # The approved triage the bench examples give checks/logdiff.sh: it allows no log difference (bench.py).
    shutil.copyfile(t6, OUT / "artifacts" / "triage.json")
    shutil.copyfile(str(t6) + ".sha256", OUT / "artifacts" / "triage.json.sha256")

    print(f"\n{len(rows) - failed} of {len(rows)} as expected; results in {OUT / 'results'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
