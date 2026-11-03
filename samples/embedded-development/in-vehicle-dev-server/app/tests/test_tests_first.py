"""Tests first (D6, TR §4.1): the tester's new tests run on the triage's base commit in the build container (a
stand-in ``docker`` here, which writes the GoogleTest report a spec asks for), and must fail there before the
developers start."""

import asyncio
import json
import sys
import time
from pathlib import Path

from teamkit import FakeManager, FakeTests, act, finish, make_deps, mod

checks, team_mod = mod("checks"), mod("team")

FAKE_DOCKER = """#!{python}
import json, os, re, sys
a = sys.argv[1:]
if a[0] == "rm":
    sys.exit(0)
script = a[-1]
with open(os.environ["FAKE_DOCKER_LOG"], "a") as f:
    f.write(script + "\\n")
spec = json.load(open(os.environ["FAKE_FIRST"]))
if spec.get("build_fails"):
    print("tests/test_new.cpp:3:1: error: 'parse_interval' was not declared")
    sys.exit(1)
report = re.search(r"--gtest_output=json:(\\S+)", script).group(1)
tree = re.search(r"cmake -S (\\S+)", script).group(1)
suites = {{}}
for n in spec["ran"]:
    suite, name = n.split(".")
    suites.setdefault(suite, []).append({{"name": name, "result": "COMPLETED",
                                         **({{"failures": [{{"failure": "x"}}]}} if n in spec.get("failing", []) else {{}})}})
json.dump({{"tests": len(spec["ran"]), "testsuites": [{{"name": s, "testsuite": t}} for s, t in suites.items()]}}, open(report, "w"))
json.dump(sorted(os.listdir(tree + "/tests")) + [open(tree + "/src/a.cpp").read()], open(os.environ["FAKE_TREE"], "w"))
sys.exit(1 if spec.get("failing") else 0)
"""

TRIAGE = [{"id": "F-013", "decision": "fix", "evidence": "unit-test", "behaviour": False},
          {"id": "F-018", "decision": "fix", "evidence": "unit-test", "behaviour": False},
          {"id": "F-003", "decision": "fix", "evidence": "static-analysis", "behaviour": False}]
NEW_TESTS = ("#include <gtest/gtest.h>\nTEST(Fixes, F013_PassByConstRef) { EXPECT_TRUE(false); }\n"
             "TEST(Fixes, IntervalRejectsJunk) {\n  // F-018\n  EXPECT_TRUE(false);\n}\n")


class Setup:
    def __init__(self, tmp: Path, monkeypatch) -> None:
        docker = tmp / "docker"
        docker.write_text(FAKE_DOCKER.format(python=sys.executable), encoding="utf-8")
        docker.chmod(0o755)
        self.spec, self.tree, self.log = tmp / "first.json", tmp / "tree.json", tmp / "docker.log"
        for k, v in (("FAKE_DOCKER_LOG", self.log), ("FAKE_FIRST", self.spec), ("FAKE_TREE", self.tree)):
            monkeypatch.setenv(k, str(v))
        src = tmp / "src-tree"
        (src / "src").mkdir(parents=True)
        (src / "tests").mkdir()
        (src / "src" / "a.cpp").write_text("int a;\n", encoding="utf-8")
        (src / "tests" / "test_old.cpp").write_text("TEST(Old, Works) {}\n", encoding="utf-8")
        role = lambda key, deps, writable: {"key": key, "title": key, "depends_on": deps, "writable": writable,  # noqa: E731
                                            "brief": f"{key}的活"}
        team = team_mod.check_team({
            "roles": [role("tester", [], ["tests/**"]), role("dev", ["tester"], ["src/**"]), role("reviewer", ["dev"], [])],
            "defaults": {"max_fix_rounds": 2}, "check_runner": {"docker": [str(docker), "run", "--rm"], "image": "img"},
            "checks": []})
        self.mgr = FakeManager()
        state = team_mod.new_state("r1102first", "", team, "{run}", tmp / "work", src, time.time(), source=src)
        self.run = team_mod.TeamRun(state, make_deps(tmp, self.mgr, FakeTests([])))

    def ran(self, ran, failing=(), build_fails=False) -> None:
        self.spec.write_text(json.dumps({"ran": list(ran), "failing": list(failing), "build_fails": build_fails}),
                             encoding="utf-8")

    def approve_triage(self) -> None:
        root = Path(self.run.s["repo"]).parent
        (root / "triage.json").write_text(json.dumps({"base": self.run.s["base"], "approved": {"by": "x", "at": "y"},
                                                      "findings": TRIAGE}), encoding="utf-8")


async def until(run, cond, timeout=20.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        await run.tick()
        if cond():
            return
        await asyncio.sleep(0.05)
    raise AssertionError([e["text"] for e in run.events][-5:])


def test_a_new_test_that_passes_on_the_base_goes_back_to_the_tester(tmp_path, monkeypatch):
    t = Setup(tmp_path, monkeypatch)
    run, mgr = t.run, t.mgr
    t.ran(["Old.Works", "Fixes.F013_PassByConstRef", "Fixes.IntervalRejectsJunk"], failing=["Fixes.F013_PassByConstRef"])

    async def go():
        await run.tick()
        t.approve_triage()
        tester = mgr.by_role("tester")
        act(tester, {"tests/test_new.cpp": NEW_TESTS, "src/a.cpp": "int a = 1;\n"}, msg="[tester] F-013 F-018 tests")
        finish(tester)
        await until(run, lambda: len(run.lane("tester")["attempts"]) == 2)
        first = run.lane("tester")["first"]
        assert first["status"] == "sent_back"
        assert first["reasons"] == ["F-018：测试 Fixes.IntervalRejectsJunk 在需求提交 " + run.s["base"][:12]
                                    + " 上通过了，它要先失败（TR §4.1）"]
        assert first["tests"] == {"F-013": ["Fixes.F013_PassByConstRef"], "F-018": ["Fixes.IntervalRejectsJunk"]}
        # the tests of the tester's head, on the base's code: its own change to src/ is not in the tree
        assert json.loads(t.tree.read_text()) == ["test_new.cpp", "test_old.cpp", "int a;\n"]
        script = t.log.read_text().splitlines()[-1]
        assert "ninja -C " in script and " vstatd_tests && " in script and "/results/tests-first/1/" in script
        task = run.lane("tester")["attempts"][-1]["task"]
        assert "Fixes.IntervalRejectsJunk 在需求提交" in task and "TR §4.1" in task
        assert run.lane("dev")["status"] == "waiting" and not run._ready("dev")
        t.ran(["Old.Works", "Fixes.F013_PassByConstRef", "Fixes.IntervalRejectsJunk"],
              failing=["Fixes.F013_PassByConstRef", "Fixes.IntervalRejectsJunk"])
        again = mgr.by_role("tester")
        act(again, {"tests/test_new.cpp": NEW_TESTS + "// F-018 asserts E05\n"}, msg="[tester] F-018 fails first")
        finish(again)
        await until(run, lambda: run.lane("dev")["status"] != "waiting")
        assert run.lane("tester")["first"]["status"] == "passed"
        assert "/results/tests-first/2" in run.lane("tester")["first"]["results"]

    asyncio.run(go())


def test_when_every_new_test_fails_on_the_base_the_developers_start(tmp_path, monkeypatch):
    t = Setup(tmp_path, monkeypatch)
    run, mgr = t.run, t.mgr
    t.ran(["Old.Works", "Fixes.F013_PassByConstRef", "Fixes.IntervalRejectsJunk"],
          failing=["Fixes.F013_PassByConstRef", "Fixes.IntervalRejectsJunk"])

    async def go():
        await run.tick()
        t.approve_triage()
        tester = mgr.by_role("tester")
        act(tester, {"tests/test_new.cpp": NEW_TESTS}, msg="[tester] F-013 F-018 tests")
        finish(tester)
        await until(run, lambda: run.lane("dev")["status"] != "waiting")
        assert run.lane("tester")["first"]["status"] == "passed" and len(run.lane("tester")["attempts"]) == 1
        assert any("新测试在需求提交上都失败了，开发开工" in e["text"] for e in run.events)

    asyncio.run(go())


def test_a_missing_test_or_one_that_does_not_build_on_the_base_goes_back_and_the_rounds_run_out(tmp_path, monkeypatch):
    t = Setup(tmp_path, monkeypatch)
    run, mgr = t.run, t.mgr
    t.ran([], build_fails=True)

    async def go():
        await run.tick()
        t.approve_triage()
        for n in range(3):  # the work round and two send-backs (max_fix_rounds 2)
            a = mgr.by_role("tester")
            act(a, {"tests/test_new.cpp": "TEST(Fixes, F013) { EXPECT_TRUE(false); }\n" + "//" * n},
                msg=f"[tester] F-013 round {n}")
            finish(a)
            await until(run, lambda: len(run.lane("tester")["attempts"]) == n + 2 or run.ended)
        first = run.lane("tester")["first"]
        assert first["reasons"][0] == "F-018：分诊定为修复、证据是单元测试，但没有新写或改过的测试写了这个编号"
        assert "在需求提交 " in first["reasons"][1] and "没有跑起来（退出码 1）" in first["reasons"][1]
        assert run.lane("tester")["status"] == "failed" and run.lane("dev")["status"] == "waiting"
        assert run.ended and run.s["status"] == "failed"

    asyncio.run(go())
