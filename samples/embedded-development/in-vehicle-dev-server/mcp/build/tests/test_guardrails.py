#!/usr/bin/env python3
# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Tests of the build server's guardrails, on a small git work tree with stand-in tools:

    python3 tests/test_guardrails.py

They run the server logic without a container (`sandbox.runner = "none"`, allowed only for these tests); the
isolation of the sandbox itself is probed by `tests/smoke.py --probe` in the build environment. Needs Python 3.11+
and git; the MCP-layer tests need the MCP SDK and are skipped without it.
"""

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
os.environ["BUILDSERVER_UNSANDBOXED_FOR_TESTS"] = "1"
from buildserver import admin, core  # noqa: E402
from buildserver.core import BuildService, ConfigError, Refused  # noqa: E402

LIMITS = {"repair_rounds": {"value": {"cross_build": 3, "log_comparison": 2}, "source": "[TR §5.1]"},
          "sysroot": {"value": "/opt/cc1-sysroot", "source": "[CC1-PN §7.2]"}}
FAKE_CMAKE = """#!/bin/sh
[ -f "$FAKE_STATE/cmake-fail" ] && { echo "CMake Error: fake"; exit 1; }
while [ $# -gt 0 ]; do case "$1" in -B) b=$2; shift;; esac; shift; done
: > "$b/build.ninja"; echo configured
"""
FAKE_NINJA = """#!/bin/sh
[ -f "$FAKE_STATE/ninja-sleep" ] && { sleep 30 & echo $! > "$FAKE_STATE/child.pid"; wait; }
[ -f "$FAKE_STATE/ninja-slow" ] && sleep 0.3
[ -f "$FAKE_STATE/ninja-fail" ] && { echo "error: fake"; exit 1; }
echo built
"""
# A stand-in check: records its argv and environment, writes a result for the commit it judged, and exits with the
# verdict in $FAKE_STATE/verdict (default FAIL). $FAKE_STATE/mode can make it misbehave.
FAKE_CHECK = """#!/bin/sh
name=$(basename "$0" .sh)
printf '%s\\n' "$@" > "$FAKE_STATE/argv-$name"; env > "$FAKE_STATE/env-$name"
while [ $# -gt 0 ]; do case "$1" in --results) r=$2; shift;; --project) p=$2; shift;; esac; shift; done
commit=$(git -C "$p" rev-parse HEAD); v=$(cat "$FAKE_STATE/verdict" 2>/dev/null || echo FAIL)
mode=$(cat "$FAKE_STATE/mode" 2>/dev/null)
case $v in PASS) rc=0;; FAIL) rc=1;; BLOCKED) rc=3;; esac
started=$(date -u +%Y-%m-%dT%H:%M:%SZ)
[ "$mode" = stale ] && started=2000-01-01T00:00:00Z
[ "$mode" = lie ] && v=PASS
[ "$mode" = tamper ] && echo '{"check": "build", "verdict": "PASS", "tampered": true}' > "$r/build.json"
[ "$mode" = silent ] && exit $rc
printf '{"check": "%s", "verdict": "%s", "commit": "%s", "started": "%s", "details": {"digest": "abc"}}\\n' \\
  "$name" "$v" "$commit" "$started" > "$r/$name.json"
echo "$name: $v" > "$r/$name.log"
echo "$name: $v"
[ "$mode" = fifo ] && { rm "$r/$name.log"; mkfifo "$r/$name.log"; }
if [ "$mode" = inputs ]; then
  mkdir -p "$r/work/$name" "$r/artifacts"; echo tool > "$r/work/$name/tool.txt"; echo "$name" > "$r/artifacts/vstatd"
  echo other > "$r/work/$name/other.txt"
  t=$(sha256sum "$r/work/$name/tool.txt" 2>/dev/null || shasum -a 256 "$r/work/$name/tool.txt"); t=${t%% *}
  a=$(sha256sum "$r/artifacts/vstatd" 2>/dev/null || shasum -a 256 "$r/artifacts/vstatd"); a=${a%% *}
  printf '{"check": "%s", "verdict": "%s", "commit": "%s", "started": "%s", "inputs": {"tool": {"path": "%s", ' \\
    "$name" "$v" "$commit" "$started" "$r/work/$name/tool.txt" > "$r/$name.json"
  printf '"sha256": "%s"}, "artifact": {"path": "%s", "sha256": "%s"}, "other": {"path": "%s", "sha256": "0"}}}\\n' \\
    "$t" "$r/artifacts/vstatd" "$a" "$r/work/$name/other.txt" >> "$r/$name.json"
fi
[ "$mode" = linklog ] && { rm "$r/$name.log"; ln -s "$FAKE_STATE/secret" "$r/$name.log"; }
[ "$mode" = linkdir ] && { mkdir -p "$FAKE_STATE/forged"; cp "$r/$name.json" "$FAKE_STATE/forged/"; rm -rf "$r"; \\
  ln -s "$FAKE_STATE/forged" "$r"; }
exit $rc
"""


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, text=True).stdout.strip()


class Env(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="buildserver-test-"))
        self.ws = self.tmp / "work"
        (self.ws / "cmake").mkdir(parents=True)
        (self.ws / "src.cpp").write_text("int main() {}\n")
        for a in (("init", "-q", "-b", "main"), ("config", "user.email", "t@example.com"), ("config", "user.name", "T"),
                  ("add", "-A"), ("commit", "-qm", "base")):
            git(self.ws, *a)
        self.fake = self.tmp / "fake"
        self.fake.mkdir()
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        for name, text in (("cmake", FAKE_CMAKE), ("ninja", FAKE_NINJA)):
            (self.bin / name).write_text(text.replace("$FAKE_STATE", str(self.fake)))
            (self.bin / name).chmod(0o755)
        self.checks = self.tmp / "sample" / "checks"
        self.checks.mkdir(parents=True)
        (self.checks / "limits.json").write_text(json.dumps(LIMITS))
        for c in core.CHECKS:
            (self.checks / f"{c}.sh").write_text(FAKE_CHECK.replace("$FAKE_STATE", str(self.fake)))
            (self.checks / f"{c}.sh").chmod(0o755)
        self.st = self.tmp / "srv" / "state"
        (self.tmp / "srv" / "triage").mkdir(parents=True)
        self.config = self.write_config()
        os.environ["AWS_SECRET_ACCESS_KEY"] = "not-a-real-secret"

    def tearDown(self):
        os.environ.pop("AWS_SECRET_ACCESS_KEY", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_config(self, runner="none", extra="", **paths):
        p = {"workspace": self.ws, "state": self.st, "triage": self.tmp / "srv" / "triage" / "triage.json",
             "checks": self.checks, "sysroot": self.tmp / "sysroot", **paths}
        text = "[paths]\n" + "".join(f'{k} = "{v}"\n' for k, v in p.items())
        text += (f'[sandbox]\nrunner = "{runner}"\n'
                 '[roles.developer]\nclasses = ["read-only", "controlled-write"]\n'
                 '[roles.reviewer]\nclasses = ["read-only"]\n'
                 '[timeouts]\nconfigure = 30\nbuild = 2\ncheck = 30\n'
                 f'[environment]\npath = "{self.bin}:/usr/bin:/bin"\n'
                 f'[tools]\ncmake = "{self.bin / "cmake"}"\nninja = "{self.bin / "ninja"}"\n')
        cfg = self.tmp / "config.toml"
        cfg.write_text(text + extra)
        return cfg

    def service(self, role="developer"):
        return BuildService(self.config, role)

    def audit(self):
        f = self.st / "audit.jsonl"
        return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []

    def outcomes(self):
        return [(e["tool"], e["outcome"]) for e in self.audit()]

    def flag(self, name, text=""):
        (self.fake / name).write_text(text)


class DenyByDefault(Env):
    def test_role_without_the_class_is_refused_and_audited(self):
        s = self.service("reviewer")
        self.assertEqual(len(s.call("workspace_status")["head"]), 40)
        with self.assertRaisesRegex(Refused, "not granted controlled-write"):
            s.call("configure", profile="cross")
        self.assertFalse((self.st / "builds" / "cross").exists())
        self.assertEqual(self.outcomes(), [("workspace_status", "started"), ("workspace_status", "ok"),
                                           ("configure", "refused")])

    def test_unknown_role_gets_nothing(self):
        s = self.service("intruder")
        for tool, args in (("workspace_status", {}), ("read_result", {"check": "build"})):
            with self.assertRaises(Refused):
                s.call(tool, **args)

    def test_arguments_named_like_the_call_itself_are_refused_and_audited(self):
        s = self.service()
        for args in ({"tool": "x"}, {"self": "x"}):
            with self.assertRaisesRegex(Refused, "unexpected arguments"):
                s.call("workspace_status", **args)
        self.assertEqual(self.outcomes(), [("workspace_status", "refused")] * 2)

    def test_unknown_tool_extra_and_missing_arguments_are_refused_and_audited(self):
        s = self.service()
        for tool, args, why in (("git_push", {}, "unknown tool"), ("configure", {"profile": "host", "extra": "-DX=1"},
                                                                    "unexpected arguments"),
                                ("run_check", {}, "missing arguments")):
            with self.assertRaisesRegex(Refused, why):
                s.call(tool, **args)
        self.assertEqual([o for _, o in self.outcomes()], ["refused"] * 3)


class ClosedArguments(Env):
    def test_profiles_targets_checks_and_kinds_come_from_fixed_lists(self):
        s = self.service()
        for tool, args in (("configure", {"profile": "../../etc"}), ("build", {"profile": "cross", "target": "rm"}),
                           ("run_check", {"check": "logdiff"}), ("run_check", {"check": "build; rm -rf /"}),
                           ("read_log", {"kind": "../x", "profile": "cross"})):
            with self.assertRaises(Refused, msg=f"{tool} {args}"):
                s.call(tool, **args)
        self.assertNotIn("ok", [o for _, o in self.outcomes()])


class ServerDirectories(Env):
    def test_server_paths_inside_the_work_tree_are_rejected(self):
        for name in ("state", "triage", "checks", "sysroot"):
            self.write_config(**{name: self.ws / "inside" / name})
            with self.assertRaisesRegex(ConfigError, f"paths.{name} lies inside"):
                self.service()

    def test_symlink_into_the_work_tree_is_rejected(self):
        (self.tmp / "link").symlink_to(self.ws)
        self.write_config(state=self.tmp / "link" / "state")
        with self.assertRaisesRegex(ConfigError, "paths.state lies inside"):
            self.service()

    def test_work_tree_and_triage_outside_the_state(self):
        self.write_config(triage=self.st / "triage.json")
        with self.assertRaisesRegex(ConfigError, "outside paths.state"):
            self.service()

    def test_relative_paths_are_rejected(self):
        self.write_config(state="srv/state")
        with self.assertRaisesRegex(ConfigError, "must be absolute"):
            self.service()

    def test_workspace_must_be_a_git_work_tree(self):
        self.write_config(workspace=self.tmp)
        with self.assertRaisesRegex(ConfigError, "not a git work tree"):
            self.service()

    def test_unknown_permission_class_and_unreadable_limits_are_rejected(self):
        self.config.write_text(self.config.read_text().replace('["read-only"]', '["physical"]'))
        with self.assertRaisesRegex(ConfigError, "unknown permission classes"):
            self.service("reviewer")
        self.write_config()
        (self.checks / "limits.json").write_text("{}")
        with self.assertRaisesRegex(ConfigError, "repair_rounds.cross_build and sysroot"):
            self.service()

    def test_folders_others_can_write_and_a_configuration_in_the_work_tree_are_rejected(self):
        shared = self.tmp / "shared"
        shared.mkdir()
        shared.chmod(0o777)
        self.write_config(state=shared / "state")
        with self.assertRaisesRegex(ConfigError, "writable by other users"):
            self.service()
        self.write_config()
        inside_cfg = self.ws / "config.toml"
        shutil.copy(self.config, inside_cfg)
        with self.assertRaisesRegex(ConfigError, "configuration lies inside"):
            BuildService(inside_cfg, "developer")

    def test_checks_or_a_triage_others_can_change_and_a_state_checks_can_read_are_rejected(self):
        (self.checks / "build.sh").chmod(0o777)
        with self.assertRaisesRegex(ConfigError, "paths.checks: .*build.sh is writable by other users"):
            self.service()
        (self.checks / "build.sh").chmod(0o755)
        approval = self.tmp / "srv" / "triage" / "triage.json.sha256"
        approval.write_text("0" * 64)
        approval.chmod(0o666)
        with self.assertRaisesRegex(ConfigError, "paths.triage: .*triage.json.sha256 is writable"):
            self.service()
        approval.chmod(0o644)
        self.write_config(state=self.tmp / "sample" / "state")
        with self.assertRaisesRegex(ConfigError, "outside the sample"):
            self.service()

    def test_a_work_tree_swapped_after_start_is_refused(self):
        s = self.service()
        self.ws.rename(self.tmp / "work-moved")
        shutil.copytree(self.tmp / "work-moved", self.ws)
        with self.assertRaisesRegex(Refused, "changed since the server started"):
            s.call("workspace_status")

    def test_the_sandbox_runs_as_a_user_other_than_root_with_known_options(self):
        self.write_config(extra='[sandbox.check_args]\nlogdiff = ["--privileged"]\n')
        with self.assertRaisesRegex(ConfigError, "unknown checks"):
            self.service()
        for user in ("0:0", "root"):
            with self.assertRaisesRegex(ConfigError, "must not be root"):
                core.Sandbox({"runner": "docker", "user": user}, "/usr/bin", "x")

    def test_running_without_a_sandbox_needs_the_test_switch(self):
        os.environ.pop("BUILDSERVER_UNSANDBOXED_FOR_TESTS")
        try:
            with self.assertRaisesRegex(ConfigError, "without isolation"):
                self.service()
        finally:
            os.environ["BUILDSERVER_UNSANDBOXED_FOR_TESTS"] = "1"
        self.write_config(runner="podman-maybe")
        with self.assertRaisesRegex(ConfigError, "sandbox.runner must be docker"):
            self.service()


class Checks(Env):
    def test_fixed_arguments_and_no_local(self):
        self.service().call("run_check", check="static")
        argv = (self.fake / "argv-static").read_text().split()
        run = self.st.resolve() / "run"
        self.assertEqual(argv, ["--project", str(run / "project"), "--results", str(run / "results"),
                                "--triage", str((self.tmp / "srv" / "triage" / "triage.json").resolve())])
        self.service().call("run_check", check="size")
        self.assertNotIn("--triage", (self.fake / "argv-size").read_text().split())
        self.assertNotIn("--local", argv)

    def test_the_committed_head_is_judged_on_a_clean_clone(self):
        (self.ws / "src.cpp").write_text("uncommitted\n")
        r = self.service().call("run_check", check="unit")
        self.assertEqual(r["commit"], git(self.ws, "rev-parse", "HEAD"))
        self.assertEqual((self.st / "run" / "project" / "src.cpp").read_text(), "int main() {}\n")
        self.assertEqual(r["verdict"], "FAIL")
        self.assertEqual(self.service("reviewer").call("read_result", check="unit")["result"]["verdict"], "FAIL")

    def test_a_result_that_disagrees_or_is_old_or_missing_is_not_published(self):
        s = self.service()
        self.flag("verdict", "PASS")
        s.call("run_check", check="trace")
        for mode, problem in (("lie", None), ("stale", "not this run's"), ("silent", "wrote no result")):
            self.flag("verdict", "FAIL")
            self.flag("mode", mode)
            r = s.call("run_check", check="trace")
            self.assertEqual(r["verdict"], "ERROR", mode)
            if problem:
                self.assertIn(problem, r["problem"])
            published = s.call("read_result", check="trace")
            self.assertEqual(published["result"]["verdict"], "ERROR", mode)
            self.assertIn("build server:", published["log_tail"])
            self.assertEqual(published["result"]["commit"], git(self.ws, "rev-parse", "HEAD"))
        self.flag("mode", "lie")
        self.flag("verdict", "BLOCKED")
        self.assertIn("the exit status says BLOCKED", s.call("run_check", check="trace")["problem"])

    def test_a_check_cannot_change_another_checks_published_result(self):
        s = self.service()
        self.flag("verdict", "FAIL")
        s.call("run_check", check="build")
        self.flag("mode", "tamper")
        s.call("run_check", check="static")
        self.assertEqual(json.loads((self.st / "results" / "build.json").read_text())["verdict"], "FAIL")

    def test_symlinks_the_check_leaves_are_not_followed(self):
        s = self.service()
        self.flag("secret", "host secret")
        self.flag("mode", "linklog")
        s.call("run_check", check="unit")
        self.assertNotIn("host secret", s.call("read_result", check="unit")["log_tail"])
        self.assertFalse((self.st / "results" / "unit.log").is_symlink())
        self.flag("mode", "linkdir")
        r = s.call("run_check", check="static")
        self.assertEqual((r["verdict"], r["problem"]), ("ERROR", "the check replaced its results folder"))
        self.assertEqual(s.call("read_result", check="static")["result"]["verdict"], "ERROR")

    def test_a_work_tree_without_a_commit_is_refused(self):
        shutil.rmtree(self.ws / ".git")
        git(self.ws, "init", "-q")
        with self.assertRaisesRegex(Refused, "committed HEAD"):
            self.service().call("run_check", check="build")
        self.assertEqual(self.outcomes()[-1], ("run_check", "refused"))

    def test_a_fifo_the_check_leaves_does_not_hang_the_server(self):
        self.flag("mode", "fifo")
        t = threading.Thread(target=lambda: self.service().call("run_check", check="unit"), daemon=True)
        t.start()
        t.join(20)
        self.assertFalse(t.is_alive())
        self.assertFalse((self.st / "results" / "unit.log").exists())

    def test_recorded_inputs_in_the_checks_own_folder_are_published_and_stale_ones_removed(self):
        s = self.service()
        self.flag("mode", "inputs")
        s.call("run_check", check="build")
        res = self.st / "results"
        self.assertEqual((res / "work" / "build" / "tool.txt").read_text(), "tool\n")
        self.assertEqual((res / "artifacts" / "vstatd").read_text(), "build\n")
        self.assertFalse((res / "work" / "build" / "other.txt").exists(), "an input whose digest differs")
        s.call("run_check", check="static")
        self.assertEqual((res / "work" / "static" / "tool.txt").read_text(), "tool\n")
        self.assertEqual((res / "artifacts" / "vstatd").read_text(), "build\n", "static may not publish artifacts")
        self.flag("mode", "")
        s.call("run_check", check="build")
        self.assertFalse((res / "artifacts").exists())
        self.assertFalse((res / "work" / "build").exists())

    def test_a_blocked_check_without_a_commit_is_published(self):
        (self.checks / "unit.sh").write_text(
            '#!/bin/sh\nwhile [ $# -gt 0 ]; do case "$1" in --results) r=$2; shift;; esac; shift; done\n'
            'printf \'{"check": "unit", "verdict": "BLOCKED", "commit": null, "started": "%s"}\' '
            '"$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$r/unit.json"; exit 3\n')
        self.assertEqual(self.service().call("run_check", check="unit")["verdict"], "BLOCKED")

    def test_work_tree_git_config_does_not_run(self):
        marker = self.tmp / "fsmonitor-ran"
        hook = self.tmp / "fsmonitor.sh"
        hook.write_text(f"#!/bin/sh\ntouch {marker}\n")
        hook.chmod(0o755)
        git(self.ws, "config", "core.fsmonitor", str(hook))
        s = self.service()
        s.call("workspace_status")
        s.call("run_check", check="build")
        self.assertFalse(marker.exists())

    def test_clean_environment(self):
        self.service().call("run_check", check="trace")
        env = (self.fake / "env-trace").read_text()
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", env)
        self.assertIn("PYTHONNOUSERSITE=1", env)
        self.assertIn("GIT_CONFIG_GLOBAL=/dev/null", env)


class Cleanup(Env):
    def test_a_build_folder_the_project_locked_is_still_cleared(self):
        s = self.service()
        s.call("configure", profile="host")
        bdir = self.st / "builds" / "host"
        (bdir / "sub").mkdir()
        (bdir / "sub").chmod(0o000)
        bdir.chmod(0o500)
        self.assertEqual(s.call("configure", profile="host")["outcome"], "ok")

    def test_a_failing_docker_refuses_the_call(self):
        docker = self.bin / "docker"
        docker.write_text("#!/bin/sh\necho 'cannot connect to the daemon' >&2\nexit 1\n")
        docker.chmod(0o755)
        sandbox = core.Sandbox({"runner": "docker"}, "/usr/bin", "label")
        path = os.environ["PATH"]
        os.environ["PATH"] = f"{self.bin}:{path}"
        try:
            with self.assertRaisesRegex(RuntimeError, "docker ps failed: cannot connect"):
                sandbox.reap()
        finally:
            os.environ["PATH"] = path


class Status(Env):
    def test_head_branch_and_changes_also_detached(self):
        (self.ws / "new.txt").write_text("x")
        r = self.service().call("workspace_status")
        self.assertEqual((r["head"], r["branch"], r["changes"]), (git(self.ws, "rev-parse", "HEAD"), "main",
                                                                  ["?? new.txt"]))
        git(self.ws, "checkout", "-q", "--detach")
        self.assertEqual(self.service().call("workspace_status")["branch"], "HEAD")
        shutil.rmtree(self.ws / ".git")
        git(self.ws, "init", "-q")
        r = self.service().call("workspace_status")
        self.assertEqual((r["outcome"], r["head"], r["problem"]), ("failed", "", "no commit, or not a git work tree"))


class BoundedRepair(Env):
    def rounds(self):
        return json.loads((self.st / "repair.json").read_text())["cross_build"]

    def test_first_attempt_and_three_retries_then_a_person_decides(self):
        s = self.service()
        s.call("configure", profile="cross")
        self.flag("ninja-fail")
        for n in range(1, 5):
            self.assertEqual(s.call("build", profile="cross")["repair"]["failures_in_a_row"], n)
        with self.assertRaisesRegex(Refused, "failed 4 times in a row"):
            s.call("build", profile="cross")
        published = json.loads((self.st / "results" / "repair-rounds.json").read_text())["cross_build"]
        self.assertEqual(published, {"failures_in_a_row": 4, "total_failures": 4, "limit_retries": 3})
        os.environ["SUDO_USER"] = "a-person"
        try:
            self.assertEqual(admin.main(["reset-repair", "--config", str(self.config), "--reason", "test"]), 0)
        finally:
            os.environ.pop("SUDO_USER")
        self.assertEqual(self.audit()[-1]["args"]["by"], "a-person")
        self.assertEqual(admin.main(["reset-repair", "--config", str(self.tmp / "missing.toml"), "--reason", "x"]), 2)
        (self.fake / "ninja-fail").unlink()
        self.assertEqual(s.call("build", profile="cross")["outcome"], "ok")
        self.assertEqual(self.rounds()["failures_in_a_row"], 0)
        self.assertIn(("admin.reset-repair", "ok"), self.outcomes())

    def test_the_build_check_counts_and_host_builds_do_not(self):
        s = self.service()
        s.call("configure", profile="host")
        self.flag("ninja-fail")
        s.call("build", profile="host")
        s.call("run_check", check="build")
        self.assertEqual(self.rounds()["failures_in_a_row"], 1)
        self.flag("verdict", "PASS")
        s.call("run_check", check="build")
        self.assertEqual(self.rounds(), {"failures_in_a_row": 0, "total_failures": 1, "limit_retries": 3})

    def test_a_successful_cross_build_does_not_clear_the_count_and_a_failed_configure_counts(self):
        s = self.service()
        s.call("configure", profile="cross")
        self.flag("ninja-fail")
        s.call("build", profile="cross")
        s.call("build", profile="cross")
        (self.fake / "ninja-fail").unlink()
        self.assertEqual(s.call("build", profile="cross", target="vstatd_tests")["repair"]["failures_in_a_row"], 2)
        self.flag("cmake-fail")
        self.assertEqual(s.call("configure", profile="cross")["repair"]["failures_in_a_row"], 3)
        s.call("configure", profile="host")
        self.assertEqual(self.rounds()["failures_in_a_row"], 3)
        (self.fake / "cmake-fail").unlink()
        self.flag("verdict", "PASS")
        self.assertEqual(s.call("run_check", check="build")["repair"]["failures_in_a_row"], 0)

    def test_an_attempt_is_charged_before_it_runs(self):
        s = self.service()
        s.call("configure", profile="cross")
        self.flag("ninja-sleep")
        self.assertEqual(s.call("build", profile="cross")["outcome"], "timeout")
        self.assertEqual(self.rounds()["failures_in_a_row"], 1)

    def test_an_unreadable_count_fails_closed(self):
        s = self.service()
        s.call("configure", profile="cross")
        (self.st / "repair.json").write_text("{}")
        with self.assertRaisesRegex(Refused, "repair count unreadable"):
            s.call("build", profile="cross")

    def test_concurrent_builds_are_serialised_and_all_counted(self):
        s = self.service()
        s.call("configure", profile="cross")
        self.flag("ninja-fail")
        self.flag("ninja-slow")
        threads = [threading.Thread(target=lambda: s.call("build", profile="cross")) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(self.rounds()["failures_in_a_row"], 3)
        lines = [e["outcome"] for e in self.audit() if e["tool"] == "build"]
        self.assertEqual(lines, ["started", "failed"] * 3, "calls overlapped")

    def test_the_lock_holds_across_processes(self):
        s = self.service()
        with s.exclusive():
            proc = subprocess.Popen([sys.executable, "-m", "buildserver.admin", "reset-repair", "--config",
                                     str(self.config), "--reason", "test"], cwd=HERE.parent,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(1.5)
            self.assertIsNone(proc.poll(), "the admin command did not wait for the lock")
        self.assertEqual(proc.wait(timeout=20), 0)


class Audit(Env):
    def test_started_and_finished_lines_for_every_call(self):
        s = self.service()
        s.call("workspace_status")
        s.call("configure", profile="host")
        s.call("read_log", kind="configure", profile="host")
        self.assertEqual([o for _, o in self.outcomes()], ["started", "ok"] * 3)
        for e in self.audit():
            self.assertTrue({"t", "role", "tool", "class", "args", "outcome"} <= set(e))

    def test_an_unexpected_failure_is_audited_and_reported_plainly(self):
        s = self.service()
        s._read_log = lambda **kw: 1 / 0
        with self.assertRaisesRegex(RuntimeError, "see the audit log"):
            s.call("read_log", kind="build", profile="host")
        self.assertEqual(self.audit()[-1]["outcome"], "error")
        self.assertIn("ZeroDivisionError", self.audit()[-1]["detail"])

    def test_check_verdict_and_digest_are_recorded(self):
        self.service().call("run_check", check="build")
        self.assertEqual((self.audit()[-1]["verdict"], self.audit()[-1]["digest"]), ("FAIL", "abc"))


class Processes(Env):
    def test_timeout_kills_the_process_group_and_does_not_retry(self):
        s = self.service()
        s.call("configure", profile="host")
        self.flag("ninja-sleep")
        t0 = time.monotonic()
        r = s.call("build", profile="host")
        self.assertEqual(r["outcome"], "timeout")
        self.assertLess(time.monotonic() - t0, 10)
        time.sleep(0.2)
        with self.assertRaises(ProcessLookupError):
            os.kill(int((self.fake / "child.pid").read_text()), 0)
        self.assertEqual(sum(1 for t, o in self.outcomes() if t == "build" and o == "started"), 1)
        self.assertIn("not retried", r["log_tail"])


class Files(Env):
    def test_log_tails_are_truncated(self):
        s = self.service()
        s.call("configure", profile="host")
        (self.st / "logs" / "host.build.log").write_text("x" * 50000)
        r = s.call("read_log", kind="build", profile="host")
        self.assertLess(len(r["log_tail"]), core.TAIL_BYTES + 100)
        self.assertTrue(r["log_tail"].startswith("[... truncated ...]"))

    def test_symlinks_are_not_followed(self):
        s = self.service()
        secret = self.tmp / "config-copy.toml"
        secret.write_text("secret")
        (self.st / "results" / "unit.log").symlink_to(secret)
        self.assertEqual(s.call("read_result", check="unit")["log_tail"], "")
        victim = self.tmp / "victim"
        victim.write_text("keep")
        s.call("configure", profile="host")
        log = self.st / "logs" / "host.build.log"
        log.unlink(missing_ok=True)
        log.symlink_to(victim)
        with self.assertRaises(RuntimeError):
            s.call("build", profile="host")
        self.assertEqual(victim.read_text(), "keep")


class Mounts(Env):
    """What each call mounts and how, checked on the arguments the sandbox would pass to docker."""

    def record(self, extra=""):
        self.write_config(extra='[sandbox.check_args]\nunit = ["--security-opt", "seccomp=unconfined"]\n' + extra)
        s = self.service()
        calls = []

        def run(cmd, log, timeout, ro=(), rw=(), workdir=None, extra=()):
            calls.append({"cmd": [str(c) for c in cmd], "ro": list(ro), "rw": list(rw), "extra": list(extra)})
            return {"outcome": "failed", "exit_status": 1}
        s.sandbox.run = run
        return s, calls

    def test_the_sysroot_only_for_cross_and_the_checks_that_configure_it(self):
        s, calls = self.record()
        s.call("configure", profile="host")
        s.call("configure", profile="cross")
        self.assertNotIn(s.sysroot_mount, calls[0]["ro"])
        self.assertIn(s.sysroot_mount, calls[1]["ro"])
        self.assertEqual(calls[0]["rw"], [self.st.resolve() / "builds" / "host"])

    def test_check_options_only_for_their_check(self):
        s, calls = self.record()
        sandbox = core.Sandbox({"runner": "docker", "check_args": {"unit": ["--security-opt", "seccomp=unconfined"]}},
                               "/usr/bin", "label")
        self.assertEqual(sandbox.check_args, {"unit": ["--security-opt", "seccomp=unconfined"]})
        argv = sandbox.argv(["true"], "n", ro=[self.ws], rw=[self.st])
        for opt in (["--network", "none"], ["--cap-drop", "ALL"], ["--security-opt", "no-new-privileges"],
                    ["--read-only"], ["--init"], ["--label", "buildserver.state=label"]):
            self.assertTrue(any(argv[i:i + len(opt)] == opt for i in range(len(argv))), opt)
        self.assertIn(f"type=bind,source={self.ws},target={self.ws},readonly", argv)
        self.assertIn(f"type=bind,source={self.st},target={self.st}", argv)
        self.assertNotIn("seccomp=unconfined", argv)
        with self.assertRaisesRegex(RuntimeError, "cannot mount"):
            sandbox.argv(["true"], "n", ro=[self.tmp / "a,b"])

    def test_docker_client_gets_its_settings_and_the_container_does_not(self):
        os.environ["DOCKER_HOST"] = "unix:///run/user/1000/docker.sock"
        try:
            sandbox = core.Sandbox({"runner": "docker"}, "/usr/bin", "label")
            self.assertEqual(sandbox.client_env()["DOCKER_HOST"], "unix:///run/user/1000/docker.sock")
            self.assertFalse(any("DOCKER_HOST" in a for a in sandbox.argv(["true"], "n")))
        finally:
            os.environ.pop("DOCKER_HOST")


class Screen(Env):
    """The MCP middleware on requests the SDK would reject on its own."""

    def setUp(self):
        super().setUp()
        try:
            from buildserver.server import make_screen  # noqa: F401
        except ImportError:
            self.skipTest("MCP SDK not installed")

    def test_odd_names_and_arguments_are_refused_and_audited(self):
        import asyncio
        import types
        from buildserver.server import make_screen
        from mcp.shared.exceptions import MCPError
        screen = make_screen(self.service())

        async def nxt(ctx):
            return "passed on"
        cases = [{"name": ["git_push"]}, {"name": "workspace_status", "arguments": []},
                 {"name": "workspace_status", "arguments": {"tool": "x"}},
                 {"name": "read_result", "arguments": {"check": "build", "self": "x"}},
                 {"name": "workspace_status", "arguments": ""}, {"name": "workspace_status", "arguments": 0},
                 {"name": "workspace_status", "arguments": False}, {"name": "configure", "arguments": {"profile": 1}}]
        for params in cases:
            with self.assertRaises(MCPError, msg=params):
                asyncio.run(screen(types.SimpleNamespace(method="tools/call", params=params), nxt))
        self.assertEqual([o for _, o in self.outcomes()], ["refused"] * len(cases))
        ok = {"name": "workspace_status", "arguments": None}
        self.assertEqual(asyncio.run(screen(types.SimpleNamespace(method="tools/call", params=ok), nxt)), "passed on")


class McpLayer(Env):
    def setUp(self):
        super().setUp()
        try:
            import asyncio  # noqa: F401
            from mcp import Client  # noqa: F401
            from buildserver.server import make_server  # noqa: F401
        except ImportError:
            self.skipTest("MCP SDK not installed")

    def run_client(self, coro_fn, role="developer"):
        import asyncio
        from mcp import Client
        from buildserver.server import make_server
        server = make_server(self.service(role))

        async def go():
            async with Client(server) as client:
                return await coro_fn(client)
        return asyncio.run(go())

    def test_exactly_the_documented_tools(self):
        async def f(c):
            return sorted(t.name for t in (await c.list_tools()).tools)
        self.assertEqual(self.run_client(f), sorted(core.TOOLS))

    def test_refusals_are_errors_and_audited_including_what_the_sdk_would_reject(self):
        async def f(c):
            out = []
            for name, args in (("configure", {"profile": "../x"}), ("configure", {"profile": "host", "x": "1"}),
                               ("git_push", {}), ("configure", {}), ("configure", {"profile": ["host"]})):
                try:
                    r = await c.call_tool(name, args)
                    out.append(("result", r.is_error))
                except Exception as e:  # noqa: BLE001
                    out.append(("raised", type(e).__name__))
            return out
        out = self.run_client(f)
        self.assertEqual(out[0], ("result", True))
        self.assertTrue(all(o[0] == "raised" or o[1] for o in out[1:]))
        self.assertFalse((self.st / "builds" / "host").exists())
        refused = [(e["tool"], e.get("detail", "")) for e in self.audit() if e["outcome"] == "refused"]
        self.assertEqual([t for t, _ in refused], ["configure", "configure", "git_push", "configure", "configure"])
        self.assertNotIn("error", [e["outcome"] for e in self.audit()])


if __name__ == "__main__":
    unittest.main(verbosity=1)
