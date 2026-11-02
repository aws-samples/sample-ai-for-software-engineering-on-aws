"""The check adapter (D7, D11) with stand-in checks: small scripts that keep the protocol of checks/README.md (exit
status 0 PASS, 1 FAIL, 2 usage error, 3 BLOCKED; ``<results>/<check>.json``), run through a stand-in ``docker`` that
drops its options and runs the command."""

import asyncio
import json
import sys
import time
from pathlib import Path

from teamkit import FakeManager, act, finish, make_run, mod, sh

checks, team_mod, gitwork = mod("checks"), mod("team"), mod("gitwork")

FAKE_DOCKER = """#!/usr/bin/env python3
import os, sys
a = sys.argv[1:]
if a[0] == "rm":
    sys.exit(0)
with open(os.environ["FAKE_DOCKER_LOG"], "a") as f:
    f.write(" ".join(a) + "\\n")
i = a.index("stand-in-image")
os.execv(a[i + 1], a[i + 1:])
"""

STAND_IN = """#!{python}
import json, sys, time
a = sys.argv[1:]
res = a[a.index("--results") + 1]
time.sleep({sleep})
spec = json.load(open("{spec}"))
if spec.get("write", True):
    json.dump({{"check": "{name}", "verdict": spec.get("verdict"), "reasons": spec.get("reasons", []), "tier": spec.get("tier"),
               "summary": spec.get("summary", ""), "args": a}}, open(res + "/{name}.json", "w"))
sys.exit(spec["rc"])
"""

VERDICT = {0: "PASS", 1: "FAIL", 2: "USAGE", 3: "BLOCKED"}


class Bench:
    """A scenario folder with stand-in checks whose outcome a test sets (``set(name, rc, reasons)``)."""

    def __init__(self, tmp: Path, monkeypatch) -> None:
        self.dir = tmp / "sample"
        (self.dir / "checks").mkdir(parents=True)
        docker = tmp / "docker"
        docker.write_text(FAKE_DOCKER, encoding="utf-8")
        docker.chmod(0o755)
        self.log = tmp / "docker.log"
        monkeypatch.setenv("FAKE_DOCKER_LOG", str(self.log))
        self.runner = {"docker": [str(docker), "run", "--rm"], "image": "stand-in-image"}

    def check(self, name: str, *, owner: str | None, args=("project",), rounds: int = 2, sleep: float = 0.0,
              when: str = "before_bench", timeout: float = 30) -> dict:
        spec = self.dir / "checks" / f"{name}.spec.json"
        script = self.dir / "checks" / f"{name}.sh"
        script.write_text(STAND_IN.format(python=sys.executable, sleep=sleep, spec=spec, name=name), encoding="utf-8")
        script.chmod(0o755)
        self.set(name, 0)
        return {"name": name, "command": [str(script)], "args": list(args), "when": when, "owner": owner,
                "max_rounds": rounds, "timeout_s": timeout}

    def set(self, name: str, rc: int, reasons=(), verdict: str | None = None, write: bool = True, tier=None) -> None:
        (self.dir / "checks" / f"{name}.spec.json").write_text(json.dumps(
            {"rc": rc, "verdict": verdict or VERDICT.get(rc), "reasons": list(reasons), "write": write, "tier": tier}),
            encoding="utf-8")


def team_of(bench: Bench, *checks_: dict) -> dict:
    role = lambda key, deps, writable: {"key": key, "title": key, "depends_on": deps, "writable": writable,  # noqa: E731
                                        "brief": f"{key}的活"}
    return team_mod.check_team({
        "roles": [role("dev", [], ["src/a.*"]), role("dev2", [], ["src/b.*"]), role("reviewer", ["dev", "dev2"], [])],
        "defaults": {"max_fix_rounds": 9}, "check_runner": bench.runner, "checks": list(checks_)})


def repo(tmp: Path) -> tuple[Path, str]:
    """A run branch worktree (wt/_run) with src/a.cpp and src/b.cpp committed."""
    async def go():
        src = tmp / "src-tree"
        (src / "src").mkdir(parents=True)
        (src / "src" / "a.cpp").write_text("int a;\n", encoding="utf-8")
        (src / "src" / "b.cpp").write_text("int b;\n", encoding="utf-8")
        r = tmp / "runs" / "r1" / "repo"
        base = await gitwork.create_repo(src, r, "", "x", existing=True)
        wt = tmp / "runs" / "r1" / "wt" / "_run"
        await gitwork.add_worktree(r, wt, "team/r1/run", base)
        return wt, base
    return asyncio.run(go())


def run_round(bench, team, wt, head, n=1, **kw):
    return asyncio.run(checks.run_checks(wt, team, head=head, results=wt.parents[1] / "results" / str(n), **kw))


def test_each_exit_status_is_the_verdict_and_the_result_file_must_agree(tmp_path, monkeypatch):
    bench = Bench(tmp_path, monkeypatch)
    names = ["pass", "fail", "usage", "blocked", "liar", "silent", "crash"]
    team = team_of(bench, *[bench.check(n, owner="dev") for n in names])
    bench.set("fail", 1, ["no path here"])
    bench.set("usage", 2, write=False)
    bench.set("blocked", 3, ["the triage is not approved"], tier="unit test")
    bench.set("liar", 0, verdict="FAIL")  # exit 0, but its result says FAIL
    bench.set("silent", 1, write=False)  # no result file
    bench.set("crash", 139, write=False)
    wt, head = repo(tmp_path)
    wall = run_round(bench, team, wt, head)
    got = {r["name"]: r["verdict"] for r in wall["checks"]}
    assert got == {"pass": "PASS", "fail": "FAIL", "usage": "USAGE", "blocked": "BLOCKED", "liar": "BLOCKED",
                   "silent": "BLOCKED", "crash": "BLOCKED"}
    rows = {r["name"]: r for r in wall["checks"]}
    assert rows["usage"]["reasons"] == ["检查配置错误（退出码 2）"]
    assert rows["liar"]["reasons"] == ["退出码是 PASS，结果文件 liar.json 说 FAIL：对不上"]
    assert rows["crash"]["reasons"] == ["检查没跑起来（退出码 139）"]
    cases = {c["id"]: c for c in wall["cases"]}
    assert (cases["pass"]["status"], cases["pass"]["owner"]) == ("pass", "dev")
    assert (cases["fail"]["status"], cases["fail"]["owner"], cases["fail"]["message"]) == ("fail", "dev", "no path here")
    assert (cases["blocked"]["status"], cases["blocked"]["verdict"], cases["blocked"]["owner"]) == ("blocked", "BLOCKED", None)
    assert cases["blocked"]["tier"] == "unit test" and cases["usage"]["owner"] is None  # a person, not a role
    assert (wall["passed"], wall["failed"], wall["total"], wall["head"]) == (1, 6, 7, head)
    assert set(cases["fail"]) == {"id", "ac", "name", "file", "status", "owner", "ms", "message", "verdict", "tier"}


def test_a_check_gets_its_arguments_its_results_dir_and_a_snapshot_at_the_head(tmp_path, monkeypatch):
    bench = Bench(tmp_path, monkeypatch)
    team = team_of(bench, bench.check("static", owner="dev", args=["project", "triage"]),
                   bench.check("logdiff", owner="dev", args=["run", "baseline", "triage"], when="after_bench"))
    wt, head = repo(tmp_path)
    triage = tmp_path / "runs" / "r1" / "triage.json"
    sh(wt, "commit", "-q", "--allow-empty", "-m", "later")  # the run branch moved on: the round judges *head*
    wall = run_round(bench, team, wt, head, n=4, triage=triage)
    assert [r["name"] for r in wall["checks"]] == ["static"]  # the phase's checks only
    results = tmp_path / "runs" / "r1" / "results" / "4"
    args = json.loads((results / "static.json").read_text())["args"]
    project = tmp_path / "runs" / "r1" / "wt" / "_checks"
    assert args == ["--results", str(results), "--project", str(project), "--triage", str(triage)]
    assert sh(project, "rev-parse", "HEAD").strip() == head and sh(wt, "rev-parse", "HEAD").strip() != head
    line = bench.log.read_text().splitlines()[-1]
    root = tmp_path / "runs" / "r1"
    assert f"-v {bench.dir}:{bench.dir}:ro -v {root}:{root} " in line and "-e GIT_CONFIG_VALUE_0=*" in line
    assert "--name vstatd-check-" in line
    after = run_round(bench, team, wt, head, n=5, phase="after_bench", triage=triage)
    assert after["checks"][0]["verdict"] == "USAGE" and after["checks"][0]["reasons"] == ["没有 --run（logdiff 要它）"]


def test_a_failure_goes_to_the_owner_of_the_file_it_names_else_to_the_checks_default_owner(tmp_path, monkeypatch):
    bench = Bench(tmp_path, monkeypatch)
    team = team_of(bench, bench.check("build", owner="dev2"))
    wt, head = repo(tmp_path)
    project = wt.parent / "_checks"
    bench.set("build", 1, ["src/a.cpp:12:10: fatal error: systemd/sd-daemon.h: No such file or directory",
                           f"tsan: SUMMARY: ThreadSanitizer: data race {wt.parents[1]}/results/1/work/unit/tree/src/b.cpp:90 in X",
                           "collect2: error: ld returned 1 exit status", "src/gone.cpp:3: not in the project"])
    wall = run_round(bench, team, wt, head)
    assert checks.files_named(wall["checks"][0]["reasons"], project) == ["src/a.cpp", "src/b.cpp"]
    cases = {c["id"]: c for c in wall["cases"]}
    assert set(cases) == {"build#dev", "build#dev2"} and wall["checks"][0]["owners"] == ["dev", "dev2"]
    assert cases["build#dev"]["file"] == "src/a.cpp" and "sd-daemon.h" in cases["build#dev"]["message"]
    assert cases["build#dev2"]["message"].count("；") == 2  # the race in its file, and the two that name no file of the project


def test_a_check_that_hangs_is_blocked_and_its_container_removed(tmp_path, monkeypatch):
    bench = Bench(tmp_path, monkeypatch)
    team = team_of(bench, bench.check("unit", owner="dev", sleep=5, timeout=0.5))
    wt, head = repo(tmp_path)
    t0 = time.monotonic()
    wall = run_round(bench, team, wt, head)
    assert time.monotonic() - t0 < 4
    assert wall["checks"][0]["verdict"] == "BLOCKED" and wall["checks"][0]["reasons"] == ["超过 0.5 秒没跑完"]


# --- in the orchestrator ------------------------------------------------------------------------------------------ #

def make(tmp_path, monkeypatch, *specs):
    bench = Bench(tmp_path, monkeypatch)
    team = team_of(bench, *[bench.check(**s) for s in specs])
    mgr = FakeManager()
    run = make_run(tmp_path, mgr, checks.run_checks, team=team)
    return bench, mgr, run


def work(a, role):
    if role == "dev":
        act(a, {"src/a.cpp": f"// {a.id}\n"})
    elif role == "dev2":
        act(a, {"src/b.cpp": f"// {a.id}\n"})
    finish(a, "可以交付" if role == "reviewer" else "做了")


async def until(run, mgr, cond, timeout=20.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        await run.tick()
        if cond():
            return
        for a in mgr.live():
            work(a, mgr.role_of(a))
        await asyncio.sleep(0.05)
    raise AssertionError(f"{run.s['status']}: {[e['text'] for e in run.events][-5:]}")


def test_the_tick_is_not_held_while_the_checks_run(tmp_path, monkeypatch):
    bench, mgr, run = make(tmp_path, monkeypatch, {"name": "build", "owner": "dev", "sleep": 1.5})

    async def go():
        await until(run, mgr, lambda: run._tests is not None)
        t0 = time.monotonic()
        await run.tick()
        assert time.monotonic() - t0 < 0.5 and run._tests is not None and run.s["needs_test"]  # still running
        assert run.lane("reviewer")["status"] == "waiting"
        await until(run, mgr, lambda: run.ended)
        assert run.s["status"] == "done" and run.s["tests"]["checks"][0]["verdict"] == "PASS"
        assert run.s["tests"]["results"] == str(Path(run.s["repo"]).parent / "results" / "1")

    asyncio.run(go())


def test_a_failure_goes_back_to_its_owner_until_the_check_is_out_of_rounds_then_to_a_person(tmp_path, monkeypatch):
    bench, mgr, run = make(tmp_path, monkeypatch, {"name": "build", "owner": "dev2", "rounds": 2})
    bench.set("build", 1, ["src/a.cpp:3:1: error: expected ';'"])

    async def go():
        await until(run, mgr, lambda: run.ended)
        fixes = [a.task for a in mgr.agents.values() if mgr.role_of(a) == "dev" and " attempt=" in a.task.split("\n")[0]]
        assert len(fixes) == 2 and "build.sh（src/a.cpp）：src/a.cpp:3:1: error: expected ';'" in fixes[0]
        assert "/results/1/<检查>.json" in fixes[0] and "node --test" not in fixes[0]
        assert run.s["tests"]["rounds"] == {"build": 2} and not any(mgr.role_of(a) == "dev2" and " attempt=" in a.task for a in mgr.agents.values())
        assert run.s["status"] == "failed" and run.lane("reviewer")["status"] == "waiting"
        assert run.events[-1]["text"].startswith("运行停下，交给人决定：build 修了 2 轮仍不过：src/a.cpp:3:1")
        assert run.sign_block().startswith("运行失败了")

    asyncio.run(go())


def test_blocked_goes_to_a_person_not_to_a_role_unless_another_check_failed_first(tmp_path, monkeypatch):
    bench, mgr, run = make(tmp_path, monkeypatch, {"name": "build", "owner": "dev"}, {"name": "size", "owner": "dev2"})
    bench.set("build", 1, ["collect2: error: ld returned 1 exit status"])
    bench.set("size", 3, ["no result of checks/build.sh in the results directory"])

    async def go():
        await until(run, mgr, lambda: run.s["tests"].get("rounds"))
        assert run.s["tests"]["rounds"] == {"build": 1} and not run.s["tests"].get("held")  # the failure goes back first
        assert run.lane("dev")["status"] in ("fixing", "queued") and run.lane("dev2")["status"] == "merged"
        bench.set("build", 0)
        await until(run, mgr, lambda: run.ended)
        assert run.s["status"] == "failed" and run.s["tests"]["held"]["checks"] == ["size"]
        assert [a for a in mgr.agents.values() if mgr.role_of(a) == "dev2" and " attempt=" in a.task] == []
        assert "size 没法判定：no result of checks/build.sh" in run.events[-1]["text"]

    asyncio.run(go())


def test_a_misconfigured_check_stops_the_run_for_a_person(tmp_path, monkeypatch):
    bench, mgr, run = make(tmp_path, monkeypatch, {"name": "build", "owner": "dev"}, {"name": "static", "owner": "dev"})
    bench.set("build", 1, ["src/a.cpp:1: error"])
    bench.set("static", 2, write=False)

    async def go():
        await until(run, mgr, lambda: run.ended)
        assert run.s["tests"]["held"]["checks"] == ["static"] and not run.s["tests"]["rounds"]
        assert "static 检查配置错误" in run.events[-1]["text"]

    asyncio.run(go())


def test_a_merge_while_the_checks_run_starts_them_again_on_the_new_head(tmp_path, monkeypatch):
    bench, mgr, run = make(tmp_path, monkeypatch, {"name": "build", "owner": "dev", "sleep": 1.0})

    async def go():
        await until(run, mgr, lambda: run._tests is not None)
        old = run._tests[1]
        sh(Path(run.s["run_wt"]), "commit", "-q", "--allow-empty", "-m", "[run] moved")
        run._head = None
        await run.tick()
        assert old.cancelled() or old.done()
        assert run._tests is not None and run._tests[0] == sh(Path(run.s["run_wt"]), "rev-parse", "HEAD").strip()
        await until(run, mgr, lambda: run.ended)
        assert run.s["tests"]["round"] == 2

    asyncio.run(go())


def test_stopping_the_run_cancels_its_checks(tmp_path, monkeypatch):
    bench, mgr, run = make(tmp_path, monkeypatch, {"name": "build", "owner": "dev", "sleep": 5})

    async def go():
        await until(run, mgr, lambda: run._tests is not None)
        task = run._tests[1]
        assert await run.stop()
        await asyncio.sleep(0.1)
        assert task.cancelled() and run._tests is None

    asyncio.run(go())
