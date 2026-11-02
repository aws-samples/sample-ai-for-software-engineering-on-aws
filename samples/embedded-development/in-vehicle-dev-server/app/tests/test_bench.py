"""The bench (D3, D10) with a stand-in ``cc1.sh`` and ``doctor.sh`` and a bench state directory of a test's own: the
stand-in plays the bench (it writes requests and the action record), the test plays the person at the console. No
QEMU."""

import asyncio
import json
import sys
import time
from pathlib import Path

from test_checks import Bench, until
from teamkit import FakeManager, make_deps, mod

checks, team_mod, board, bench_mod = mod("checks"), mod("team"), mod("board"), mod("bench")

CC1 = """#!{python}
import json, os, sys, time
a = sys.argv[1:]
state = os.environ["CC1_BENCH_STATE"]
spec = json.load(open(os.environ["FAKE_CC1"])).get(a[0], "ok")
with open(os.environ["FAKE_CC1_LOG"], "a") as f:
    f.write(json.dumps({{"argv": a, "requester": os.environ.get("CC1_REQUESTER")}}) + "\\n")
def record(**kw):
    with open(state + "/actions.jsonl", "a") as f:
        f.write(json.dumps({{"at": "now", **kw}}) + "\\n")
if spec == "wait":  # a request at the console, decided by the person (the test)
    rid = "20261102T120000-" + a[0] + "-ab12"
    os.makedirs(state + "/requests", exist_ok=True)
    json.dump({{"id": rid, "action": a[0], "digest": "bc93723c" + "0" * 56, "detail": "vstatd, 133240 bytes",
               "requested_at": "2026-11-02T12:00:00Z", "expires": time.time() + 30, "requested_by": os.environ.get("CC1_REQUESTER")}},
              open(state + "/requests/" + rid + ".json", "w"))
    record(event="request", id=rid, action=a[0])
    while not os.path.exists(state + "/decisions/" + rid + ".json"):
        time.sleep(0.05)
    dec = json.load(open(state + "/decisions/" + rid + ".json"))
    if dec["verdict"] != "approved":
        print("refused: refused (" + dec["by"] + "): " + dec["reason"], file=sys.stderr)
        sys.exit(1)
    spec = "ok"
if spec == "refuse":
    print("refused: refused (lilin@cc1-host (ttys003)): not this build", file=sys.stderr)
    sys.exit(1)
if spec == "timeout":
    print("refused: refused (bench (timeout)): no answer at the operator console within 300 s", file=sys.stderr)
    sys.exit(1)
if spec == "unknown":
    json.dump({{"state": "unknown", "why": "replay of bc93723c was interrupted"}}, open(state + "/target.json", "w"))
    print("replay failed", file=sys.stderr)
    sys.exit(1)
if a[0] == "replay":
    out = a[a.index("--out") + 1]
    os.makedirs(out, exist_ok=True)
    open(out + "/run.jsonl", "w").write("{{}}\\n")
    json.dump({{"replay_finished": True}}, open(out + "/run-result.json", "w"))
record(event="action", action=a[0], result="ok")
print(a[0] + " ok")
"""

DOCTOR = """#!{python}
import json, os, sys
ok = json.load(open(os.environ["FAKE_CC1"])).get("doctor", "ok") == "ok"
print("PASS  Docker 27, 6 CPUs")
if not ok:
    print("FAIL  no target image in the volume cc1-images: run bench/build-target.sh")
print("doctor: ready" if ok else "doctor: 1 problem(s)")
sys.exit(0 if ok else 1)
"""

BUILD = """#!{python}
import json, os, sys
a = sys.argv[1:]
res = a[a.index("--results") + 1]
os.makedirs(res + "/artifacts", exist_ok=True)
open(res + "/artifacts/vstatd", "w").write("ELF")
json.dump({{"check": "build", "verdict": "PASS", "reasons": [], "summary": "vstatd sha256 bc93723c"}}, open(res + "/build.json", "w"))
"""


EVIDENCE = """#!{python}
import json, os, sys
a = sys.argv[1:]
res = a[a.index("--results") + 1]
got = sorted(n[:-5] for n in os.listdir(res) if n.endswith(".json") and n != "repair-rounds.json")
open(res + "/evidence.md", "w").write("# Evidence page: vstatd\\n\\n" + ", ".join(got) + "\\n")
"""


class Rig:
    def __init__(self, tmp: Path, monkeypatch, *, cc1=None, doctor="ok", target="known", baseline=True,
                 release=False) -> None:
        self.bench = Bench(tmp, monkeypatch)
        self.state = tmp / "bench-state"
        self.state.mkdir()
        if target:
            (self.state / "target.json").write_text(json.dumps({"state": target, "why": "booted"}), encoding="utf-8")
        self.baseline = tmp / "baseline"
        if baseline:
            self.baseline.mkdir()
            (self.baseline / "baseline-result.json").write_text("{}", encoding="utf-8")
        self.spec, self.log = tmp / "cc1.json", tmp / "cc1.log"
        self.set(doctor=doctor, **(cc1 or {}))
        for k, v in (("CC1_BENCH_STATE", self.state), ("FAKE_CC1", self.spec), ("FAKE_CC1_LOG", self.log)):
            monkeypatch.setenv(k, str(v))
        scripts = {}
        for name, text in (("cc1.sh", CC1), ("doctor.sh", DOCTOR), ("build-check.sh", BUILD), ("evidence-page.sh", EVIDENCE)):
            p = tmp / name
            p.write_text(text.format(python=sys.executable), encoding="utf-8")
            p.chmod(0o755)
            scripts[name] = str(p)
        build = self.bench.check("build", owner="dev")
        build["command"] = [scripts["build-check.sh"]]
        logdiff = self.bench.check("logdiff", owner="dev", args=["run", "baseline", "triage"], when="after_bench")
        limits = self.bench.check("runtime-limits", owner="dev", args=["run", "baseline"], when="after_bench")
        more = [self.bench.check("unit", owner="dev"),
                self.bench.check("release", owner=None, args=["project", "triage"], when="release")] if release else []
        role = lambda key, deps, writable: {"key": key, "title": key, "depends_on": deps, "writable": writable,  # noqa: E731
                                            "brief": f"{key}的活"}
        cc1 = scripts["cc1.sh"]
        team = team_mod.check_team({
            "roles": [role("dev", [], ["src/a.*"]), role("reviewer", ["dev"], [])], "defaults": {"max_fix_rounds": 9},
            "check_runner": self.bench.runner, "checks": [build, *more[:1], logdiff, limits, *more[1:]],
            **({"evidence_page": [scripts["evidence-page.sh"]]} if release else {}),
            "bench": {"deploy": [cc1, "deploy", "{artifact}"], "replay": [cc1, "replay", "--kind", "run", "--out", "{run}"],
                      "doctor": [scripts["doctor.sh"]], "build": ["/s/bench/build-target.sh"], "start": [cc1, "start"],
                      "baseline": str(self.baseline)}})
        self.mgr = FakeManager()
        src = tmp / "src-tree"
        (src / "src").mkdir(parents=True)
        (src / "src" / "a.cpp").write_text("int a;\n", encoding="utf-8")
        state = team_mod.new_state("r1102bench", "", team, "{run}", tmp / "work", src, time.time(), source=src)
        self.run = team_mod.TeamRun(state, make_deps(tmp, self.mgr, checks.run_checks))

    def set(self, **spec) -> None:
        self.spec.write_text(json.dumps(spec), encoding="utf-8")

    def calls(self) -> list:
        return [json.loads(ln) for ln in self.log.read_text().splitlines()] if self.log.exists() else []

    def decide(self, verdict: str, reason: str = "") -> None:
        req = next((self.state / "requests").glob("*.json"))
        (self.state / "decisions").mkdir(exist_ok=True)
        (self.state / "decisions" / req.name).write_text(json.dumps({"verdict": verdict, "by": "李工", "reason": reason}),
                                                          encoding="utf-8")

    def view(self) -> dict:
        return board.bench_view(self.run)


def test_a_deploy_waits_for_the_console_then_the_replay_feeds_the_checks_after_the_bench(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, cc1={"deploy": "wait"})
    run, mgr = rig.run, rig.mgr

    async def go():
        await until(run, mgr, lambda: rig.view()["state"]["pending"])
        view = rig.view()
        assert view["step"] == "deploy" and view["running"] == "deploy" and view["doctor"]["ok"]
        req = view["state"]["pending"][0]
        assert req["action"] == "deploy" and req["digest"].startswith("bc93723c") and not req["expired"]
        assert req["requested_by"] == "vstatd-team r1102bench"
        t0 = time.monotonic()
        await run.tick()
        assert time.monotonic() - t0 < 0.5 and not run.ended  # the tick is not held while the person decides
        rig.decide("approved")
        await until(run, mgr, lambda: run.ended)
        assert run.s["status"] == "done", [e["text"] for e in run.events][-4:]
        b = run.s["bench"]
        assert [(a["action"], a["outcome"]) for a in b["actions"]] == [("deploy", "ok"), ("replay", "ok")]
        root = Path(run.s["repo"]).parent
        deploy, replay = rig.calls()
        assert deploy["argv"] == ["deploy", str(root / "results" / "1" / "artifacts" / "vstatd")]
        assert replay["argv"] == ["replay", "--kind", "run", "--out", str(root / "bench" / "run-1")]
        args = json.loads((root / "results" / "after-1" / "logdiff.json").read_text())["args"]
        assert args[args.index("--run") + 1] == str(root / "bench" / "run-1")
        assert args[args.index("--baseline") + 1] == str(rig.baseline)
        assert [r["verdict"] for r in b["after"]["checks"]] == ["PASS", "PASS"] and b["step"] == "done"
        assert [a.get("event") for a in rig.view()["state"]["actions"]] == ["request", "action", "action"]
        assert not (rig.state / "decisions" / "x").exists() and sorted(p.name for p in rig.state.iterdir()) == [
            "actions.jsonl", "decisions", "requests", "target.json"]  # the app wrote nothing there

    asyncio.run(go())


def test_a_refusal_at_the_console_goes_to_a_person_and_a_retry_carries_on(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, cc1={"deploy": "refuse"})
    run, mgr = rig.run, rig.mgr

    async def go():
        await until(run, mgr, lambda: run.ended)
        held = run.s["bench"]["held"]
        assert run.s["status"] == "failed" and held["step"] == "deploy"
        assert held["why"] == "部署没做成（refused）：lilin@cc1-host (ttys003) 在操作台上拒绝了：not this build"
        assert [c["argv"][0] for c in rig.calls()] == ["deploy"]  # nothing retried, no replay
        assert run.events[-1]["text"].startswith("运行停下，交给人决定：部署没做成")
        rig.set()
        assert await run.retry() == ["bench"]
        await until(run, mgr, lambda: run.ended)
        assert run.s["status"] == "done" and [c["argv"][0] for c in rig.calls()] == ["deploy", "deploy", "replay"]

    asyncio.run(go())


def test_a_timeout_at_the_console_and_an_unknown_target_go_to_a_person(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, cc1={"replay": "timeout"})
    run, mgr = rig.run, rig.mgr

    async def go():
        await until(run, mgr, lambda: run.ended)
        assert run.s["bench"]["held"]["why"].startswith("回放没做成（timeout）：操作台上没人批准：no answer at the operator console")
        rig.set(replay="unknown")
        await run.retry()
        await until(run, mgr, lambda: run.ended)
        assert run.s["bench"]["held"]["why"] == "回放没做成（unknown）：目标状态未知：replay of bc93723c was interrupted"
        assert [a["outcome"] for a in run.s["bench"]["actions"]] == ["ok", "timeout", "unknown"]
        assert rig.view()["state"]["target"]["state"] == "unknown"

    asyncio.run(go())


def test_a_bench_that_is_not_ready_stops_the_run_before_its_first_action(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, doctor="fail", target=None, baseline=False)
    run, mgr = rig.run, rig.mgr

    async def go():
        await until(run, mgr, lambda: run.ended)
        held = run.s["bench"]["held"]
        assert held["step"] == "doctor" and rig.calls() == []
        assert held["why"].startswith("台架没准备好：bench/doctor.sh 没通过：no target image in the volume cc1-images")
        assert "台架上的 CC-1 没开机" in held["why"] and f"没有基线目录 {rig.baseline}" in held["why"]
        cc1 = run.team["bench"]["deploy"][0]
        assert held["commands"] == ["/s/bench/build-target.sh", f"{cc1} start",
                                    f"部署当前版本以后运行 {cc1} replay --kind baseline --out {rig.baseline}"]
        view = rig.view()
        assert view["doctor"]["fails"] == ["no target image in the volume cc1-images: run bench/build-target.sh"]
        assert view["state"]["target"]["state"] == "off" and not (tmp_path / "bench-state" / "requests").exists()

    asyncio.run(go())


def test_a_failing_check_after_the_bench_goes_to_its_owner_and_the_bench_starts_over(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    run, mgr = rig.run, rig.mgr
    rig.bench.set("logdiff", 1, ["only in the run: {\"ev\":\"SIGNAL_TIMEOUT\",\"message\":\"VCU_Speed\"}"])

    async def go():
        await until(run, mgr, lambda: run.s["tests"].get("rounds"))
        assert run.s["tests"]["rounds"] == {"logdiff": 1} and run.lane("reviewer")["status"] == "waiting"
        fix = run.lane("dev")["attempts"][-1]
        assert fix["kind"] == "fix" and "/results/after-1/<检查>.json" in fix["task"] and "SIGNAL_TIMEOUT" in fix["task"]
        rig.bench.set("logdiff", 0)
        await until(run, mgr, lambda: run.ended)
        assert run.s["status"] == "done" and run.s["bench"]["n"] == 2
        assert len(run.lane("reviewer")["attempts"]) == 2  # it looked again at the fix before the bench
        assert [c["argv"][0] for c in rig.calls()] == ["deploy", "replay", "deploy", "replay"]

    asyncio.run(go())
