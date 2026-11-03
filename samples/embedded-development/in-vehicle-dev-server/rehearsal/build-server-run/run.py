#!/usr/bin/env python3
# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""One batch walked through the `build` MCP server, the way the agents reach the build server.

For facilitators, not for the agents' workspace: the batch contains the answers to the seeds. Runs on the build
server's host with the server installed (mcp/build/README.md, Running), Docker, the `vstatd-build` image and a sysroot:

    /opt/buildserver/bin/python run.py --sysroot /opt/cc1-sysroot [--image vstatd-build] [--keep]

Makes a throwaway layout in a new folder in the temporary directory: a git copy of reference-project/ as the work
tree, the server's state, the triage folder and a configuration. Then it plays both sides of the batch. As the
agent, it edits and commits the work tree and calls the server's tools over MCP stdio. As the people, it approves
the triage (writing its approval record) and resets the repair count with the admin command. Each call is compared
with what it should return; the run prints a table and exits non-zero when a call returned something else.

The batch: the toolchain seed with wrong repairs until the repair bound stops them, trace failing the commits they
left, a person's decision (drop them, reset the count) and the right repair; the ThreadSanitizer race found and
fixed; the F-008 wrong fix. The after-deploy checks need the bench of build plan item 3, so the release check ends
FAIL on their missing results.
"""

import argparse
import asyncio
import datetime
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

from mcp import Client
from mcp.client.stdio import StdioServerParameters

HERE = pathlib.Path(__file__).resolve().parent
SAMPLE = HERE.parent.parent
sys.path.insert(0, str(SAMPLE / "checks" / "lib"))
import common as c  # noqa: E402

rows, failures = [], 0


def sh(*cmd, cwd=None, env=None):
    p = subprocess.run([str(x) for x in cmd], cwd=cwd, env=env, capture_output=True, text=True)
    if p.returncode != 0:
        raise SystemExit(f"{' '.join(str(x) for x in cmd)}: {p.stdout}{p.stderr}")
    return p.stdout.strip()


class Batch:
    def __init__(self, root, sysroot, image):
        self.root, self.work, self.state = root, root / "work", root / "state"
        self.triage_file = root / "triage" / "triage.json"
        self.config = root / "config.toml"
        self.triage_file.parent.mkdir(parents=True)
        shutil.copytree(SAMPLE / "reference-project", self.work, ignore=shutil.ignore_patterns("build*"))
        self.git("init", "-q", "-b", "main")
        self.base = self.commit("vstatd 2.7.0: current release")
        self.decided = {}
        self.approve()
        self.config.write_text(f'''[paths]
workspace = "{self.work}"
state = "{self.state}"
triage = "{self.triage_file}"
checks = "{SAMPLE / "checks"}"
sysroot = "{sysroot}"

[sandbox]
runner = "docker"
image = "{image}"

[sandbox.check_args]
unit = ["--security-opt", "seccomp=unconfined"]

[roles.developer]
classes = ["read-only", "controlled-write"]

[roles.reviewer]
classes = ["read-only"]
''')

    # ------------------------------------------------------------------ the agent's side: the work tree

    def git(self, *args):
        return sh("git", "-C", self.work, "-c", "user.name=Agent", "-c", "user.email=agent@example.com", *args)

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-qm", message)
        return self.git("rev-parse", "HEAD")

    def patch(self, path, old, new):
        p = self.work / path
        s = p.read_text()
        if s.count(old) != 1:
            raise SystemExit(f"{path}: expected one occurrence of {old!r}")
        p.write_text(s.replace(old, new))

    def restore(self, *paths):
        self.git("checkout", self.base, "--", *paths)

    # ------------------------------------------------------------------ the people's side

    def approve(self):
        """The release owner approves the triage: the triage and its approval record (checks/README.md)."""
        t = {"batch": "vstatd batch 1 (facilitator example)", "base": self.base,
             "approved": {"by": "release owner", "at": datetime.date.today().isoformat()}, "findings": [],
             "allowed_log_differences": [], "requirements": []}
        for fid, row in c.backlog_rows().items():
            if row["label"] == "fix" and fid not in self.decided:
                t["findings"].append({"id": fid, "decision": "defer", "reason": "Not in this example.",
                                      "pick_up_when": "A later batch."})
        t["findings"] += [dict(entry, id=fid) for fid, entry in self.decided.items()]
        self.triage_file.write_text(json.dumps(t, indent=2))
        self.triage_file.with_name("triage.json.sha256").write_text(c.sha256(self.triage_file) + "\n")

    def reset_repair(self, reason):
        out = sh(sys.executable, "-I", "-m", "buildserver.admin", "reset-repair", "--config", self.config,
                 "--reason", reason)
        row("people", "admin reset-repair", "reset", "reset", out)

    def repair(self):
        try:
            return json.loads((self.state / "repair.json").read_text())["cross_build"]["failures_in_a_row"]
        except (OSError, ValueError, KeyError):
            return 0


def row(step, call, want, got, note=""):
    global failures
    ok = want == got
    failures += not ok
    note = " ".join(note.split())
    if len(note) > 160:
        note = note[:160].rsplit(" ", 1)[0] + " …"
    rows.append(f"| {step} | {call} | {want} | {got}{'' if ok else ' (unexpected)'} | {note} |")
    print(rows[-1], flush=True)


def payload(result):
    if getattr(result, "structured_content", None):
        return result.structured_content
    for part in result.content:
        if getattr(part, "text", None):
            try:
                return json.loads(part.text)
            except ValueError:
                return {"text": part.text}
    return {}


def server(config, role):
    return StdioServerParameters(command=sys.executable,
                                 args=["-I", "-m", "buildserver", "--config", str(config), "--role", role])


async def walk(b):
    async with Client(server(b.config, "developer")) as agent:

        async def call(step, tool, args, want, note=None, because=None):
            """`want` is the outcome of a configure or build, the verdict of a check, or `refused`. A refusal counts
            only when its text says `because`; any other error (a crash, a timeout) is `error`."""
            try:
                r = await agent.call_tool(tool, args)
                data = payload(r)
                if r.is_error:
                    got, text = "error", str(data.get("text", data))
                else:
                    got = data.get("verdict") or data.get("outcome", "ok")
                    reasons = (data.get("result") or {}).get("reasons") or []
                    text = data.get("problem") or (reasons[0] if reasons else "")
            except Exception as e:  # noqa: BLE001 - refusals the middleware raises as MCP errors
                got, text, data = "error", str(e), {}
            if got == "error" and because and because in text and "refused" in text:
                got = "refused"
            label = f"`{tool}` " + " ".join(f"{v}" for v in args.values())
            counted = args.get("profile") == "cross" or args.get("check") == "build"
            text = note(data) if note and got != "error" else text
            text += f" (repair count {b.repair()})" if counted and "repair count" not in text else ""
            row(step, label.strip(), want, got, text.replace(f"{b.root}/", "").replace("Error executing tool ", ""))
            return data

        # Closed arguments: the agents cannot pick a check the server does not run, nor pass an option.
        await call("guardrails", "run_check", {"check": "logdiff"}, "refused", because="must be one of")
        await call("guardrails", "configure", {"profile": "cross", "flags": "-DCMAKE_SYSROOT=/"}, "refused",
                   because="unexpected arguments")

        # 0. The release as it is: the toolchain seed.
        await call("0 release as is", "workspace_status", {}, "ok", lambda d: f"HEAD {d.get('head', '')[:12]}")
        await call("0 release as is", "configure", {"profile": "cross"}, "ok")
        await call("0 release as is", "build", {"profile": "cross"}, "failed",
                   lambda d: f"{first_error(d)} (repair count {b.repair()})")

        # 1. Wrong repair: the unit tests' test double on the include path. Cross builds work on the work tree.
        b.patch("CMakeLists.txt", "  target_link_libraries(vstatd PRIVATE systemd)\n",
                "  target_link_libraries(vstatd PRIVATE systemd)\n"
                "  target_include_directories(vstatd PRIVATE tests/stubs)\n")
        await call("1 stub on the include path", "configure", {"profile": "cross"}, "ok")
        await call("1 stub on the include path", "build", {"profile": "cross"}, "failed",
                   lambda d: f"{first_error(d)} (repair count {b.repair()})")

        # 2. Wrong repair: a copy of the test double in src/, the sysroot set, libsystemd dropped. It builds, which
        # takes back that attempt's charge but clears nothing; the build check, on the commit, fails it.
        b.restore("CMakeLists.txt")
        shutil.copytree(b.work / "tests" / "stubs", b.work / "src" / "compat")
        b.patch("CMakeLists.txt", "  target_link_libraries(vstatd PRIVATE systemd)\n",
                "  target_include_directories(vstatd PRIVATE src/compat)\n")
        b.patch("cmake/cc1-aarch64.cmake", "set(CMAKE_SYSTEM_PROCESSOR aarch64)\n",
                "set(CMAKE_SYSTEM_PROCESSOR aarch64)\nset(CMAKE_SYSROOT /opt/cc1-sysroot)\n")
        await call("2 stub copied into src", "configure", {"profile": "cross"}, "ok")
        await call("2 stub copied into src", "build", {"profile": "cross"}, "ok")
        b.commit("Build against a compatibility header")
        await call("2 stub copied into src", "run_check", {"check": "build"}, "FAIL")

        # 3. Back to the include path, committed: the fourth failure in a row, then the bound of TR §5.1.
        b.restore("CMakeLists.txt", "cmake/cc1-aarch64.cmake")
        shutil.rmtree(b.work / "src" / "compat")
        b.patch("CMakeLists.txt", "  target_link_libraries(vstatd PRIVATE systemd)\n",
                "  target_link_libraries(vstatd PRIVATE systemd)\n"
                "  target_include_directories(vstatd PRIVATE tests/stubs)\n")
        b.commit("Use the test header for sd-daemon")
        await call("3 stub, committed", "run_check", {"check": "build"}, "FAIL")
        await call("3 bound reached", "build", {"profile": "cross"}, "refused",
                   because="times in a row")
        await call("3 bound reached", "run_check", {"check": "build"}, "refused",
                   because="times in a row")
        await call("3 bound reached", "read_result", {"check": "build"}, "ok",
                   lambda d: f"published: {(d.get('result') or {}).get('verdict')}")
        await call("3 bound reached", "run_check", {"check": "trace"}, "FAIL",  # the attempts cite no finding
                   lambda d: "; ".join(r.split(" ", 1)[1] for r in (d.get("result") or {}).get("reasons", [])[:2]))

        # 4. A person reads the audit and the logs, decides: drop the wrong attempts from the batch (it is not merged)
        # and set the sysroot (CC1-PN §7.2), then resets the count. The right repair, added to the triage as F-031
        # (the first free ID), passes and clears the count.
        b.reset_repair("Wrong repairs used the test double; drop them and set the CC-1 sysroot (CC1-PN §7.2)")
        b.git("reset", "-q", "--hard", b.base)
        b.patch("cmake/cc1-aarch64.cmake", "set(CMAKE_SYSTEM_PROCESSOR aarch64)\n",
                "set(CMAKE_SYSTEM_PROCESSOR aarch64)\n# The CC-1 sysroot (CC1-PN §7.2).\n"
                "set(CMAKE_SYSROOT /opt/cc1-sysroot)\n")
        b.commit("F-031: set the CC-1 sysroot in the toolchain file (CC1-PN §7.2)")
        b.decided["F-031"] = {"decision": "fix", "behaviour": False, "evidence": "build",
                              "added": {"found_by": "checks/build.sh", "tool": "cross build",
                                        "location": "cmake/cc1-aarch64.cmake"}}
        b.approve()
        await call("4 sysroot", "run_check", {"check": "build"}, "PASS",
                   lambda d: f"vstatd sha256 {str(d.get('digest'))[:12]} (repair count {b.repair()})")
        await call("4 sysroot", "run_check", {"check": "size"}, "PASS", lambda d: summary(d))
        await call("4 sysroot", "run_check", {"check": "static"}, "PASS", lambda d: summary(d))
        await call("4 sysroot", "run_check", {"check": "unit"}, "FAIL")
        await call("4 sysroot", "run_check", {"check": "trace"}, "PASS", lambda d: summary(d))

        # 5. The race ThreadSanitizer reports, added as F-032 and fixed.
        b.patch("src/signal_table.cpp", "        return SignalValue{};\n    }\n    return entries_[index].value;",
                "        return SignalValue{};\n    }\n    const std::lock_guard<std::mutex> lock(mutex_);\n"
                "    return entries_[index].value;")
        b.patch("tests/test_concurrency.cpp", "TEST(Concurrency, DecodingAndGetAtTheSameTime) {\n",
                "TEST(Concurrency, DecodingAndGetAtTheSameTime) {\n"
                "    // F-032: ThreadSanitizer reported the race in this test before the fix.\n")
        b.commit("F-032: lock the signal table in get (RES-THREADS, VSTATD-IF p.11 §8.4)")
        b.decided["F-032"] = {"decision": "fix", "behaviour": True, "evidence": "unit-test",
                              "cites": ["[VSTATD-IF p.11 §8.4]"], "facts": ["RES-THREADS"],
                              "added": {"found_by": "checks/unit.sh (ThreadSanitizer)", "tool": "ThreadSanitizer",
                                        "location": "src/signal_table.cpp › SignalTable::get"}}
        b.approve()
        await call("5 race fixed", "run_check", {"check": "unit"}, "PASS", lambda d: summary(d))
        await call("5 race fixed", "run_check", {"check": "trace"}, "PASS", lambda d: summary(d))

        # 6. The F-008 wrong fix: static analysis and trace pass it; unit fails it for want of a test naming F-008.
        # On the bench, the log comparison is the check meant to catch it (rehearsal/check-examples/README.md).
        b.patch("src/supervisor.cpp", "if (entry.supervised && !entry.timed_out", "if (!entry.timed_out")
        b.commit("F-008: remove the condition that is always true (SUP-GRACE)")
        b.decided["F-008"] = {"decision": "fix", "behaviour": True, "evidence": "unit-test",
                              "cites": ["[VSTATD-IF p.7 §4.2]"], "facts": ["SUP-GRACE"]}
        b.approve()
        await call("6 F-008 wrong fix", "run_check", {"check": "static"}, "PASS", lambda d: summary(d))
        await call("6 F-008 wrong fix", "run_check", {"check": "trace"}, "PASS", lambda d: summary(d))
        await call("6 F-008 wrong fix", "run_check", {"check": "unit"}, "FAIL")

        # 7. The final commit: every pre-bench check again, then the release check. It fails on F-008's missing test
        # and on the bench's results, which build plan item 3 brings.
        for check, want in (("build", "PASS"), ("size", "PASS"), ("static", "PASS"), ("trace", "PASS"),
                            ("unit", "FAIL")):
            await call("7 final commit", "run_check", {"check": check}, want)
        data = await call("7 release", "run_check", {"check": "release"}, "FAIL",
                          lambda d: "; ".join((d.get("result") or {}).get("reasons", [])[:4]))
        reasons = (data.get("result") or {}).get("reasons", [])
        stale = [r for r in reasons if "changed or went missing" in r or "not the final commit" in r]
        row("7 release", "results of the final commit, inputs intact", "yes", "no" if stale else "yes",
            "; ".join(stale))
        rounds = (((data.get("result") or {}).get("details") or {}).get("repair_rounds") or {}).get("cross_build", {})
        row("7 release", "repair rounds reported", "0 in a row", f"{rounds.get('failures_in_a_row')} in a row",
            f"{rounds.get('total_failures')} failed cross attempts in the batch")

    async with Client(server(b.config, "reviewer")) as reviewer:
        r = await reviewer.call_tool("configure", {"profile": "host"})
        text = str(payload(r).get("text", "")).replace("Error executing tool ", "")
        got = "refused" if r.is_error and "not granted controlled-write" in text else "error" if r.is_error else "ok"
        row("guardrails", "`configure` host as reviewer", "refused", got, text)


def first_error(d):
    lines = [ln for ln in (d.get("log_tail") or "").splitlines() if "error:" in ln]
    return lines[0].split("error:", 1)[1].strip()[:90] if lines else ""


def summary(d):
    return str((d.get("result") or {}).get("summary") or d.get("problem") or "")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--sysroot", required=True, help="the CC-1 sysroot, or the stand-in of make-standin-sysroot.py")
    p.add_argument("--image", default="vstatd-build", help="the image of reference-project/tools/Dockerfile")
    p.add_argument("--keep", action="store_true", help="keep the work tree, state and audit log")
    args = p.parse_args()
    root = pathlib.Path(tempfile.mkdtemp(prefix="vstatd-build-server-run-"))
    b = Batch(root, pathlib.Path(args.sysroot).resolve(), args.image)
    print(f"folder: {root}\n\n| Step | Call | Expected | Got | Note |\n| --- | --- | --- | --- | --- |")
    done = False
    try:
        asyncio.run(walk(b))
        entries = [json.loads(x) for x in (b.state / "audit.jsonl").read_text().splitlines()]
        outcomes = {}
        for e in entries:
            outcomes[e["outcome"]] = outcomes.get(e["outcome"], 0) + 1
        print(f"\naudit.jsonl: {len(entries)} lines, " + ", ".join(f"{k} {v}" for k, v in sorted(outcomes.items())))
        print(f"{len(rows) - failures} of {len(rows)} rows as expected")
        done = True
    finally:
        if args.keep or failures or not done:
            print(f"kept {root}")
        else:
            subprocess.run(["chmod", "-R", "u+rwX", root], check=False)
            shutil.rmtree(root, ignore_errors=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
