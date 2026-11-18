"""Servers mode (D17) with stand-in ``build`` and ``bench`` MCP servers: one script that speaks MCP over stdio as
``mcp/build`` and ``mcp/bench`` do, keeps an audit log and a state folder of its own, and does what a test's spec
says. The bench stand-in writes its requests into a bench state directory of the test's own and waits there for a
decision the test writes, as the person at the console would. No Docker, no QEMU."""

import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_bench import Rig
from test_checks import until
from teamkit import act, finish, make_deps, mod, sh

checks, team_mod, board, servers, scorecard, audit, gitwork = (
    mod("checks"), mod("team"), mod("board"), mod("servers"), mod("scorecard"), mod("audit"), mod("gitwork"))

FAKE = r'''
import json, os, secrets, subprocess, sys, time, tomllib
which, cfg = sys.argv[1], tomllib.load(open(sys.argv[sys.argv.index("--config") + 1], "rb"))
P = cfg["paths"]
state = P["state"]
os.makedirs(state, exist_ok=True)
session = f"developer:{os.getpid()}:{secrets.token_hex(4)}"
CLASS = {"workspace_status": "read-only", "run_check": "controlled-write", "lease_acquire": "controlled-write",
         "lease_release": "controlled-write", "request_deploy": "physical", "request_replay": "physical"}

def spec():
    return json.load(open(cfg["fake"]["spec"]))

def audit(**kw):
    line = {"t": time.strftime("%Y-%m-%dT%H:%M:%SZ"), "role": "developer", **kw}
    if which == "bench":
        line["session"] = session
    with open(state + "/audit.jsonl", "a") as f:
        f.write(json.dumps(line) + "\n")

def send(msg):
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()

def git(*a):
    return subprocess.run(["git", "-C", P["workspace"], *a], capture_output=True, text=True).stdout.strip()

class Refused(Exception):
    pass

def build_tool(name, args):
    if name == "workspace_status":
        return {"outcome": "ok", "head": git("rev-parse", "HEAD"), "changes": git("status", "--porcelain").splitlines()}
    check, sp, head = args["check"], spec(), git("rev-parse", "HEAD")
    if check == sp.get("exit_on"):
        sys.exit(3)  # the server dies in the middle of the call
    if check == sp.get("sleep_on"):
        time.sleep(30)
    if check in sp.get("refuse", []):
        raise Refused(sp.get("refuse_why", "the repair count is over its limit; a person decides, then resets it"))
    with open(state + "/judged.log", "a") as f:
        f.write(json.dumps({"check": check, "head": head, "files": git("ls-files").split(),
                            "triage": open(P["triage"]).read() if os.path.exists(P["triage"]) else None}) + "\n")
    v = sp.get(check, {})
    verdict = v.get("verdict", "PASS")
    data = {"check": check, "verdict": verdict, "commit": v.get("commit", head), "reasons": v.get("reasons", []),
            "tier": None,
            "summary": f"{check}: {verdict}", "inputs": {}, "details": {}}
    if check == "build" and verdict == "PASS":
        digest = "bc93723c" + head[:56]
        data["details"]["digest"] = digest
        os.makedirs(state + "/results/artifacts", exist_ok=True)
        open(state + "/results/artifacts/vstatd", "w").write("ELF " + head)
        json.dump(data, open(state + "/results/build.json", "w"))
    out = {"outcome": "ok", "exit_status": 0, "check": check, "commit": head, "verdict": verdict,
           "summary": f"$ checks/{check}.sh\n{check}: {verdict}\n", "result": data}
    if check == "build" and "repair" in sp:  # as mcp/build reports its repair count after each cross attempt
        out["repair"] = {"failures_in_a_row": sp["repair"][0], "limit_retries": sp["repair"][1]}
    return out

LEASE = state + "/lease.json"

def bench_tool(name, args):
    sp = spec()
    if name == "lease_acquire":
        open(LEASE, "w").write(session)
        return {"outcome": "ok", "yours": True}
    if name == "lease_release":
        if os.path.exists(LEASE):
            os.unlink(LEASE)
        return {"outcome": "ok", "released": True}
    if not (os.path.exists(LEASE) and open(LEASE).read() == session):
        raise Refused("this session does not hold the lease; call lease_acquire first")
    if name in sp.get("role_refused", []):
        raise Refused("role 'developer' is not granted physical")
    if name == "run_check" and args["check"] in sp.get("bench_refuse", []):
        raise Refused("the bench has no baseline; the bench owner records one")
    if name == "run_check":
        check = args["check"]
        v = sp.get(check, {})
        runs = sorted(os.listdir(state + "/runs")) if os.path.isdir(state + "/runs") else []
        if not runs:
            raise Refused("no replay yet; call request_replay first")
        verdict = v.get("verdict", "PASS")
        data = {"check": check, "verdict": verdict, "commit": None, "reasons": v.get("reasons", []),
                "tier": "emulation", "summary": f"{check}: {verdict}", "inputs": {}, "details": {}}
        return {"outcome": "ok", "check": check, "run": runs[-1], "verdict": verdict, "summary": "", "result": data}
    action = name[len("request_"):]
    built = json.load(open(P["build_results"] + "/build.json"))
    how = sp.get(action, "ok")
    if how == "crash":
        sys.exit(4)  # the server dies while the action waits
    rid = None
    if how in ("wait", "refuse"):
        bs = P["bench_state"]
        rid = "20261116T120000-" + action + "-" + secrets.token_hex(2)
        os.makedirs(bs + "/requests", exist_ok=True)
        json.dump({"id": rid, "action": action, "digest": built["details"]["digest"], "detail": "vstatd",
                   "requested_at": "2026-11-16T12:00:00Z", "expires": time.time() + 30,
                   "requested_by": f"bench MCP server (role developer, session {session})"},
                  open(bs + "/requests/" + rid + ".json", "w"))
        with open(bs + "/actions.jsonl", "a") as f:
            f.write(json.dumps({"at": "2026-11-16T12:00:00Z", "event": "request", "id": rid, "action": action,
                                "requested_by": f"bench MCP server (role developer, session {session})"}) + "\n")
        if how == "refuse":
            raise Refused("refused (alice@cc1-host (ttys003)): not this build (not retried)")
        while not os.path.exists(bs + "/decisions/" + rid + ".json"):
            time.sleep(0.05)
        dec = json.load(open(bs + "/decisions/" + rid + ".json"))
        if dec["verdict"] != "approved":
            raise Refused(f"refused ({dec['by']}): {dec['reason']} (not retried)")
    out = {"outcome": "ok", "action": action, "request": rid, "log_tail": ""}
    if action == "deploy":
        return {**out, "digest": built["details"]["digest"], "commit": built["commit"]}
    os.makedirs(state + "/runs", exist_ok=True)
    run = f"run-{len(os.listdir(state + '/runs')) + 1}"
    os.makedirs(state + "/runs/" + run)
    json.dump({"replay_finished": True}, open(state + "/runs/" + run + "/run-result.json", "w"))
    return {**out, "run": run, "digest": built["details"]["digest"], "result": {"replay_finished": True}}

for line in sys.stdin:
    msg = json.loads(line)
    rid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": rid, "result": {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}},
                                                       "serverInfo": {"name": which, "version": "0"}}})
    elif method == "tools/call":
        name, args = params["name"], params.get("arguments") or {}
        entry = {"tool": name, "class": CLASS.get(name), "args": args}
        audit(**entry, outcome="started")
        try:
            out = (build_tool if which == "build" else bench_tool)(name, args)
        except Refused as e:
            audit(**entry, outcome="refused", detail=str(e))
            send({"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": f"Error executing tool {name}: refused: {e}"}], "isError": True}})
            continue
        audit(**entry, outcome="ok", **{k: out[k] for k in ("verdict", "request") if out.get(k)})
        send({"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": json.dumps(out)}],
                                                       "structuredContent": {"result": out}}})
'''


class Servers:
    """The two stand-in servers' configuration files, folders and spec, as the build server's host would have them."""

    def __init__(self, tmp: Path, bench_state: Path, baseline: Path) -> None:
        self.tmp = tmp
        self.script = tmp / "fake_server.py"
        self.script.write_text(FAKE, encoding="utf-8")
        self.spec = tmp / "servers.json"
        self.set()
        srv = tmp / "server"
        self.workspace, self.triage_dir = srv / "worktree", srv / "triage"
        self.triage_dir.mkdir(parents=True)
        self.build_state, self.bench_state = tmp / "build-state", tmp / "bench-server-state"
        self.build_conf, self.bench_conf = tmp / "build.toml", tmp / "bench.toml"
        self.build_conf.write_text(
            f'[paths]\nworkspace = "{self.workspace}"\ntriage = "{self.triage_dir / "triage.json"}"\n'
            f'state = "{self.build_state}"\n[fake]\nspec = "{self.spec}"\n', encoding="utf-8")
        self.bench_conf.write_text(
            f'[paths]\nstate = "{self.bench_state}"\nbench_state = "{bench_state}"\n'
            f'build_results = "{self.build_state / "results"}"\ntriage = "{self.triage_dir / "triage.json"}"\n'
            f'baseline = "{baseline}"\n[timeouts]\napproval = 20\ndeploy = 5\nreplay = 5\n'
            f'[fake]\nspec = "{self.spec}"\n',
            encoding="utf-8")

    def set(self, **spec) -> None:
        self.spec.write_text(json.dumps(spec), encoding="utf-8")

    def team_part(self) -> dict:
        return {"connectors": "servers",
                "servers": {"build": [sys.executable, str(self.script), "build", "--config", str(self.build_conf)],
                            "bench": [sys.executable, str(self.script), "bench", "--config", str(self.bench_conf)]}}

    def judged(self) -> list:
        log = self.build_state / "judged.log"
        return [json.loads(ln) for ln in log.read_text().splitlines()] if log.exists() else []

    def audit_lines(self, which: str) -> list:
        log = (self.build_state if which == "build" else self.bench_state) / "audit.jsonl"
        return [json.loads(ln) for ln in log.read_text().splitlines()] if log.exists() else []


def servers_rig(tmp_path, monkeypatch, *, rid="r1116servers", static=True):
    """test_bench's rig (bench state, baseline, doctor, a release check in the stand-in build container), its team
    switched to servers mode: build and static before the bench on the build server, logdiff and runtime-limits
    after it on the bench server; the release check stays direct (D17)."""
    rig = Rig(tmp_path, monkeypatch, release=True)
    srv = Servers(tmp_path, rig.state, rig.baseline)
    team = dict(rig.run.team)
    static_check = rig.bench.check("static", owner="dev", args=["project", "triage"])
    keep = [c for c in team["checks"] if c["name"] != "unit"]
    team.update(srv.team_part(), checks=[keep[0], *([static_check] if static else []), *keep[1:]])
    team.pop("evidence_page", None)
    team = team_mod.check_team(team)
    src = tmp_path / "src-tree"
    state = team_mod.new_state(rid, "", team, "{run}", tmp_path / "work", src, time.time(), source=src)
    rig.run = team_mod.TeamRun(state, make_deps(tmp_path, rig.mgr, servers.run_tests))
    return rig, srv


def approve_triage(run) -> None:
    """The approved triage beside the run's repository, as the triage gate leaves it (D4)."""
    root = Path(run.s["repo"]).parent
    (root / "triage.json").write_text(json.dumps({"approved": {"by": "alice"}, "findings": []}), encoding="utf-8")
    (root / "triage.json.sha256").write_text("ab" * 32 + "\n", encoding="utf-8")


async def setup_run(run, mgr):
    await run.tick()  # the repository and the worktrees
    approve_triage(run)


def test_the_team_file_switch(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    team = dict(rig.run.team)
    assert team_mod.check_team(dict(team)).get("connectors", "direct") == "direct"
    with pytest.raises(ValueError, match="connectors 只能是"):
        team_mod.check_team({**team, "connectors": "mcp"})
    with pytest.raises(ValueError, match="要有 servers"):
        team_mod.check_team({**team, "connectors": "servers"})
    srv = Servers(tmp_path, rig.state, rig.baseline)
    unit = rig.bench.check("unit", owner="dev", when="after_bench")
    with pytest.raises(ValueError, match="检查 unit 不归任何服务器"):
        team_mod.check_team({**team, **srv.team_part(), "checks": [*team["checks"], unit]})
    shipped = json.loads((Path(team_mod.__file__).parents[2] / "team" / "team-vstatd.json").read_text())
    assert shipped["connectors"] == "direct"
    team_mod.check_team({**shipped, "connectors": "servers"})  # every check of the shipped team has its server
    with pytest.raises(ValueError, match="每条都带 --config"):
        team_mod.check_team({**team, "connectors": "servers", "servers": {"build": ["x"], "bench": ["y"]}})


def test_a_whole_round_through_the_servers(tmp_path, monkeypatch):
    rig, srv = servers_rig(tmp_path, monkeypatch)
    run, mgr = rig.run, rig.mgr
    srv.set(deploy="wait")

    async def go():
        await setup_run(run, mgr)
        await until(run, mgr, lambda: rig.view()["state"]["pending"])
        root = Path(run.s["repo"]).parent
        req = rig.view()["state"]["pending"][0]
        assert req["requested_by"].startswith("bench MCP server (role developer, session developer:")
        assert req["requested_by"] in servers.requesters(root)  # the board ties the waiting request to the run
        assert rig.view()["board_decides"] is False  # approved at the console only
        rig.decide("approved")
        await until(run, mgr, lambda: run.ended)
        assert run.s["status"] == "done", [e["text"] for e in run.events][-4:]
        return root
    root = asyncio.run(go())
    head = run.s["bench"]["head"]
    judged = srv.judged()
    # the before-bench round, then the rerun: each on the round's commit, with the run's approved triage
    assert [(j["check"], j["head"]) for j in judged] == [("build", head), ("static", head)] * 2
    assert all(json.loads(j["triage"])["approved"] == {"by": "alice"} for j in judged)
    assert (srv.triage_dir / "triage.json.sha256").read_text() == "ab" * 32 + "\n"
    b = run.s["bench"]
    assert [(a["action"], a["outcome"]) for a in b["actions"]] == [("deploy", "ok"), ("replay", "ok")]
    assert b["actions"][0]["request"] and b["run_dir"] == str(srv.bench_state / "runs" / "run-1")
    assert b["artifact"] == str(srv.build_state / "results" / "artifacts" / "vstatd")
    assert [r["verdict"] for r in b["after"]["checks"]] == ["PASS", "PASS"]
    assert run.s["rerun"]["release"]["verdict"] == "PASS"
    assert json.loads((root / "results" / "1" / "build.json").read_text())["commit"] == head  # the server's result
    assert rig.calls() == []  # cc1.sh never ran: the bench server did the actions
    bench_tools = [ln["tool"] for ln in srv.audit_lines("bench") if ln["outcome"] != "started"]
    assert bench_tools == ["lease_acquire", "request_deploy", "lease_release", "lease_acquire", "request_replay",
                           "lease_release", "lease_acquire", "run_check", "run_check", "lease_release",
                           "lease_acquire", "run_check", "run_check", "lease_release"]
    calls = scorecard.build([run.s], tmp_path / "data" / "runs", rig.state)["runs"][0]["tool_calls"]
    assert calls == {"read-only": 2, "controlled-write": 16, "physical": 2, "refused": 0}
    trail = audit.build(run.s, run.events, scorecard.records(rig.state))
    asked = [x for x in trail["entries"]
             if x["step"] == "bench" and x["actor"] == "app" and "20261116T" in x["evidence"]]
    assert len(asked) == 1  # the deploy request the bench server made for this run, in its audit trail


def test_a_check_failure_goes_to_its_owner_and_a_refusal_to_a_person(tmp_path, monkeypatch):
    rig, srv = servers_rig(tmp_path, monkeypatch)
    run, mgr = rig.run, rig.mgr
    srv.set(static={"verdict": "FAIL", "reasons": ["src/a.cpp:1: new finding nullPointer"]})

    async def go():
        await setup_run(run, mgr)
        await until(run, mgr, lambda: run.s["tests"].get("rounds"))
        assert run.s["tests"]["rounds"] == {"static": 1}  # D7: one repair round, back to the file's owner
        fix = run.lane("dev")["attempts"][-1]
        assert fix["kind"] == "fix" and "nullPointer" in fix["task"]
        srv.set(refuse=["static"])  # the build server refuses: a person decides, no role is sent anything
        await until(run, mgr, lambda: run.ended)
        assert run.s["status"] == "failed" and run.s["servers_held"] == "checks"
        held = run.s["tests"]["held"]
        assert held["checks"] == ["static"] and "build 服务器拒绝了" in held["why"]
        assert run.lane("dev")["attempts"][-1] is fix  # nothing went back to the role
        srv.set()
        assert await run.retry(by="alice") == ["servers"]
        await until(run, mgr, lambda: run.ended)
        assert run.s["status"] == "done", [e["text"] for e in run.events][-4:]
        assert run.s["tests"]["rounds"] == {"static": 1}

    asyncio.run(go())


def test_a_refused_build_and_the_checks_it_blocked_are_run_again_on_retry(tmp_path, monkeypatch):
    rig, srv = servers_rig(tmp_path, monkeypatch)
    run, mgr = rig.run, rig.mgr
    srv.set(refuse=["build"], static={"verdict": "BLOCKED", "reasons": ["no build to judge"]})

    async def go():
        await setup_run(run, mgr)
        await until(run, mgr, lambda: run.ended)
        assert run.s["tests"]["held"]["checks"] == ["build", "static"] and run.s["servers_held"] == "checks"
        run.s["servers_held"] = None  # as a run held before this was recognised: 重试 still sees it
        srv.set()  # a person reset the build server's repair count
        assert await run.retry(by="alice") == ["servers"]
        await until(run, mgr, lambda: run.ended)
        assert run.s["status"] == "done", [e["text"] for e in run.events][-4:]

    asyncio.run(go())


# mcp/build's refusal at its bound (core.py charge_cross_attempt), as r1117e6af got it
BOUND = ("cross attempts failed 4 times in a row: the first attempt and the 3 retries of TR §5.1. A person decides, "
         "then resets the count (buildserver.admin reset-repair, see mcp/build/README.md, Running)")
RESET = ("-I -m buildserver.admin reset-repair --config {conf} "
         "--reason \"a person decided after {n} failed cross builds\"")


def tilde(p) -> str:
    home = str(Path.home())
    return "~" + str(p)[len(home):] if str(p).startswith(home + "/") else str(p)


def run_checks(srv, check="build"):
    return [ln for ln in srv.audit_lines("build")
            if ln["tool"] == "run_check" and ln["args"]["check"] == check and ln["outcome"] != "started"]


def test_one_failure_before_the_build_servers_bound_the_round_waits_for_a_person(tmp_path, monkeypatch):
    rig, srv = servers_rig(tmp_path, monkeypatch, static=False)
    run, mgr = rig.run, rig.mgr
    srv.set(build={"verdict": "FAIL", "reasons": ["src/a.cpp:1: error: x"]}, repair=[3, 3])

    async def go():
        await setup_run(run, mgr)
        await until(run, mgr, lambda: run.s["tests"].get("rounds"))
        t = run.s["tests"]
        assert t["rounds"] == {"build": 1} and t["repair"] == {"failures_in_a_row": 3, "limit_retries": 3}
        srv.set(repair=[0, 3])  # the fix would pass, but the server is not asked before a person decides
        await until(run, mgr, lambda: run.ended)
        assert len(run_checks(srv)) == 1
        assert run.s["status"] == "failed" and run.s["servers_held"] == "checks"
        held = t["held"]
        assert "build 服务器的交叉构建已连续失败 3 次、上限 3" in held["why"] and "拒绝" not in held["why"]
        assert len(held["commands"]) == 1
        assert held["commands"][0].endswith(RESET.format(conf=tilde(srv.build_conf), n=3))
        assert t["rounds"] == {"build": 1}  # the hold takes no repair round (D7)
        view = board.detail(run, mgr=mgr, scrub=lambda x: x, now=time.time())["tests"]["held"]
        assert view["commands"] == held["commands"]  # the board shows it with the hold
        assert await run.retry(by="alice") == ["servers"]  # the person decided: this round runs
        await until(run, mgr, lambda: run.ended)
        assert run.s["status"] == "done", [e["text"] for e in run.events][-4:]
        assert len(run_checks(srv)) == 3  # the round, then the rerun
        assert t["repair"] == {"failures_in_a_row": 0, "limit_retries": 3} and "repair_go" not in t

    asyncio.run(go())


def test_a_refusal_at_the_build_servers_bound_says_so_with_the_reset_command(tmp_path, monkeypatch):
    rig, srv = servers_rig(tmp_path, monkeypatch, static=False)
    run, mgr = rig.run, rig.mgr
    srv.set(refuse=["build"], refuse_why=BOUND)  # a new run: the count was left at the bound by another

    async def go():
        await setup_run(run, mgr)
        await until(run, mgr, lambda: run.ended)
        t = run.s["tests"]
        assert run.s["servers_held"] == "checks" and t["repair"] == {"failures_in_a_row": 4, "limit_retries": 3}
        assert "build 服务器的交叉构建已连续失败 4 次、上限 3" in t["held"]["why"]
        assert t["held"]["commands"][0].endswith(RESET.format(conf=tilde(srv.build_conf), n=4))
        srv.set(repair=[0, 3])  # a person reset the count
        assert await run.retry(by="alice") == ["servers"]
        await until(run, mgr, lambda: run.ended)
        assert run.s["status"] == "done", [e["text"] for e in run.events][-4:]

    asyncio.run(go())


def test_the_reset_command_and_direct_mode():
    words = ["~/s/venv/bin/python", "-I", "-m", "buildserver", "--config", "~/s/build.toml", "--role", "developer"]
    assert servers.reset_command({"servers": {"build": words}}, 4) == "~/s/venv/bin/python " + RESET.format(
        conf="~/s/build.toml", n=4)
    home = str(Path.home())
    full = [f"{home}/s/venv/bin/python", "-I", "-m", "buildserver", "--config", f"{home}/s/build.toml"]
    assert servers.reset_command({"servers": {"build": full}}, 4).startswith("~/s/venv/bin/python -I")
    assert "--config ~/s/build.toml " in servers.reset_command({"servers": {"build": full}}, 4)
    assert servers.repair_count({"repair": {"failures_in_a_row": True, "limit_retries": 3}}) is None
    run = SimpleNamespace(team={"checks": [{"name": "build", "when": "before_bench"}]},
                          s={"tests": {"repair": {"failures_in_a_row": 4, "limit_retries": 3}}})
    assert team_mod.TeamRun._repair_stop(run) is None and team_mod.TeamRun._reset_command(run) is None  # direct


def test_a_refusal_at_the_console_holds_the_bench(tmp_path, monkeypatch):
    rig, srv = servers_rig(tmp_path, monkeypatch, static=False)
    run, mgr = rig.run, rig.mgr
    srv.set(deploy="refuse")

    async def go():
        await setup_run(run, mgr)
        await until(run, mgr, lambda: run.ended)
        held = run.s["bench"]["held"]
        assert run.s["status"] == "failed" and held["step"] == "deploy"
        assert held["why"].startswith("部署没做成（refused）：") and "not this build" in held["why"]
        tools = [ln["tool"] for ln in srv.audit_lines("bench") if ln["outcome"] != "started"]
        assert tools == ["lease_acquire", "request_deploy", "lease_release"]  # nothing retried, no replay

    asyncio.run(go())


def test_one_run_at_a_time(tmp_path, monkeypatch):
    rig, srv = servers_rig(tmp_path, monkeypatch, static=False)
    st = servers.setup(rig.run.team)
    runs = tmp_path / "data" / "runs"
    (runs / "r1116other").mkdir(parents=True)
    (runs / "r1116other" / "run.json").write_text(json.dumps({"id": "r1116other", "status": "running"}))
    servers.take(st, "r1116other", runs)
    with pytest.raises(servers.Unavailable, match="正被运行 r1116other 用着"):
        servers.take(st, "r1116mine", runs)
    (runs / "r1116other" / "run.json").write_text(json.dumps({"id": "r1116other", "status": "done"}))
    servers.take(st, "r1116mine", runs)
    assert json.loads(st.holder.read_text())["run"] == "r1116mine"


def test_tests_first_on_a_temporary_commit(tmp_path, monkeypatch):
    rig, srv = servers_rig(tmp_path, monkeypatch, static=False)
    team = rig.run.team

    async def go():
        src = tmp_path / "tf-src"
        (src / "src").mkdir(parents=True)
        (src / "tests").mkdir()
        (src / "src" / "a.cpp").write_text("int a;\n")
        (src / "tests" / "old_test.cpp").write_text("TEST(Old, Kept) {}\n")
        repo, wt = tmp_path / "runs" / "rtf" / "repo", tmp_path / "runs" / "rtf" / "wt" / "_run"
        base = await gitwork.create_repo(src, repo, "", "x", existing=True)
        await gitwork.add_worktree(repo, wt, "team/rtf/run", base)
        (wt / "src" / "a.cpp").write_text("int a = 1;\n")
        (wt / "tests" / "fix_test.cpp").write_text("TEST(Fix, F001_signal) { /* F-001 */ }\n")
        sh(wt, "add", "-A")
        sh(wt, "commit", "-q", "-m", "F-001 test and fix")
        head = sh(wt, "rev-parse", "HEAD").strip()
        triage = {"base": base, "findings": [{"id": "F-001", "decision": "fix", "evidence": "unit-test"}]}
        approve_triage_at(wt.parents[1])
        res = tmp_path / "runs" / "rtf" / "results" / "tests-first" / "1"
        srv.set(unit={"verdict": "FAIL", "reasons": ["plain: FAILED Fix.F001_signal"]})
        ok = await servers.tests_first(wt, team, base=base, head=head, triage=triage, results=res)
        srv.set(unit={"verdict": "PASS"})
        passed = await servers.tests_first(wt, team, base=base, head=head, triage=triage, results=res)
        return base, head, ok, passed
    base, head, ok, passed = asyncio.run(go())
    assert ok["ok"] and ok["failed"] == ["Fix.F001_signal"]
    assert not passed["ok"] and "在需求提交" in passed["reasons"][0] and "通过了" in passed["reasons"][0]
    temp = srv.judged()[0]
    assert temp["check"] == "unit" and temp["head"] not in (base, head)  # judged a commit on no branch
    assert sorted(temp["files"]) == ["src/a.cpp", "tests/fix_test.cpp", "tests/old_test.cpp"]
    assert sh(srv.workspace, "show", f"{temp['head']}:src/a.cpp") == "int a;\n"  # the base's code
    assert sh(srv.workspace, "rev-parse", "HEAD").strip() == head  # the work tree moved back


def approve_triage_at(root: Path) -> None:
    (root / "triage.json").write_text(json.dumps({"approved": {"by": "alice"}, "findings": []}), encoding="utf-8")


def test_a_server_finds_docker_with_the_gateways_path(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")  # what Kiro Crew's gateway has
    monkeypatch.setattr(servers, "DOCKER_BIN", "/opt/alice/bin/docker")
    assert servers.env()["PATH"] == "/opt/alice/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    monkeypatch.setattr(servers, "DOCKER_BIN", "docker")  # none found: PATH as it is
    assert servers.env()["PATH"] == "/usr/bin:/bin:/usr/sbin:/sbin"


def test_the_board_does_not_decide_in_servers_mode(tmp_path, monkeypatch):
    rig, srv = servers_rig(tmp_path, monkeypatch, static=False)
    assert rig.view()["board_decides"] is False
    direct = Rig(tmp_path / "d", monkeypatch) if (tmp_path / "d").mkdir() is None else None
    assert direct.view()["board_decides"] is True


def test_the_board_offers_retry_for_a_server_hold(tmp_path, monkeypatch):
    rig, srv = servers_rig(tmp_path, monkeypatch, static=False)
    run, mgr = rig.run, rig.mgr
    srv.set(refuse=["build"])

    async def go():
        await setup_run(run, mgr)
        await until(run, mgr, lambda: run.ended)
    asyncio.run(go())
    assert run.servers_retry() == "checks"
    assert not [k for k in run.order if run.lane(k)["status"] == "failed"]  # no role to retry: the board needs this


def test_the_board_decides_in_servers_mode_only_with_the_switch(tmp_path, monkeypatch):
    rig, srv = servers_rig(tmp_path, monkeypatch, static=False)
    team = rig.run.team
    assert servers.board_decides(team) is False
    on = team_mod.check_team({**team, "servers": {**team["servers"], "board_decides": True}})
    assert servers.board_decides(on) is True
    rig.run.team = on
    assert rig.view()["board_decides"] is True
    with pytest.raises(ValueError, match="board_decides 可选"):
        team_mod.check_team({**team, "servers": {**team["servers"], "board_decides": "yes"}})
    assert servers.board_decides({"connectors": "direct"}) is True


# --- from the review of #46 -------------------------------------------------------------------------------------- #

def test_the_work_tree_must_be_one_the_app_made(tmp_path, monkeypatch):
    """move_tree checks out with --force and cleans: a repository the app did not make (paths.workspace pointing at
    a project) is refused, and its untracked files stay."""
    rig, srv = servers_rig(tmp_path, monkeypatch, static=False)
    st = servers.setup(rig.run.team)
    st.workspace.mkdir(parents=True)
    sh(st.workspace, "init", "-q")
    (st.workspace / "notes.txt").write_text("alice's notes\n")

    async def go():
        await rig.run.tick()
        with pytest.raises(servers.Unavailable, match="不是 app 建的 git 仓库"):
            await servers.move_tree(st, Path(rig.run.s["run_wt"]), await gitwork.head(Path(rig.run.s["run_wt"])))
    asyncio.run(go())
    assert (st.workspace / "notes.txt").read_text() == "alice's notes\n"


def test_a_failed_run_frees_the_servers_unless_it_waits_for_a_person(tmp_path, monkeypatch):
    rig, srv = servers_rig(tmp_path, monkeypatch, static=False)
    st, runs = servers.setup(rig.run.team), tmp_path / "data" / "runs"
    (runs / "r1116other").mkdir(parents=True)
    state = {"id": "r1116other", "status": "failed", "tests": {"held": {"checks": ["build"]}}}
    (runs / "r1116other" / "run.json").write_text(json.dumps(state))
    servers.take(st, "r1116other", runs)
    with pytest.raises(servers.Unavailable, match="正被运行 r1116other 用着"):
        servers.take(st, "r1116mine", runs)  # held for a person: 重试 carries it on with the servers
    state["tests"]["held"] = None  # failed for another reason (a role out of rounds): nothing to carry on
    (runs / "r1116other" / "run.json").write_text(json.dumps(state))
    servers.take(st, "r1116mine", runs)
    assert json.loads(st.holder.read_text())["run"] == "r1116mine"


def test_the_after_bench_round_must_judge_this_steps_replay(tmp_path, monkeypatch):
    rig, srv = servers_rig(tmp_path, monkeypatch, static=False)
    (srv.bench_state / "runs" / "run-2").mkdir(parents=True)  # another session's replay, after this step's run-1

    async def go():
        await rig.run.tick()
        approve_triage(rig.run)
        root = Path(rig.run.s["repo"]).parent
        return await servers.run_tests(Path(rig.run.s["run_wt"]), rig.run.team, head="x", phase="after_bench",
                                       results=root / "results" / "after-1", triage=root / "triage.json",
                                       run=srv.bench_state / "runs" / "run-1", baseline=rig.baseline)
    wall = asyncio.run(go())
    assert [r["verdict"] for r in wall["checks"]] == ["BLOCKED", "BLOCKED"]
    assert "不是这一步的 run-1" in wall["checks"][0]["reasons"][0] and wall["server_held"] == ["logdiff", "runtime-limits"]


def test_a_refused_after_bench_check_still_gives_the_lease_back(tmp_path, monkeypatch):
    rig, srv = servers_rig(tmp_path, monkeypatch, static=False)
    (srv.bench_state / "runs" / "run-1").mkdir(parents=True)
    srv.set(bench_refuse=["logdiff"])

    async def go():
        await rig.run.tick()
        approve_triage(rig.run)
        root = Path(rig.run.s["repo"]).parent
        return await servers.run_tests(Path(rig.run.s["run_wt"]), rig.run.team, head="x", phase="after_bench",
                                       results=root / "results" / "after-1", triage=root / "triage.json",
                                       run=srv.bench_state / "runs" / "run-1", baseline=rig.baseline)
    wall = asyncio.run(go())
    assert {r["name"]: r["verdict"] for r in wall["checks"]} == {"logdiff": "BLOCKED", "runtime-limits": "PASS"}
    assert not (srv.bench_state / "lease.json").exists()
    assert [ln["tool"] for ln in srv.audit_lines("bench") if ln["outcome"] != "started"][-1] == "lease_release"


@pytest.mark.parametrize("how", ["exit", "timeout"])
def test_a_server_that_dies_or_hangs_mid_round_blocks_the_rest_for_a_person(tmp_path, monkeypatch, how):
    rig, srv = servers_rig(tmp_path, monkeypatch)
    run, mgr = rig.run, rig.mgr
    if how == "timeout":
        monkeypatch.setattr(servers, "MARGIN_S", 0)
        for c in run.team["checks"]:
            c["timeout_s"] = 1
    srv.set(**({"exit_on": "build"} if how == "exit" else {"sleep_on": "build"}))

    async def go():
        await setup_run(run, mgr)
        await until(run, mgr, lambda: run.ended, timeout=40)
    asyncio.run(go())
    rows = {r["name"]: r for r in run.s["tests"]["checks"]}
    assert [r["verdict"] for r in rows.values()] == ["BLOCKED", "BLOCKED"]
    assert ("exited" if how == "exit" else "no answer within") in rows["build"]["reasons"][0]
    assert run.s["servers_held"] == "checks" and run.s["tests"]["server_held"] == ["build", "static"]
    assert not any(e.get("code") == "bounce.checks" for e in run.events)  # nothing went to a role


@pytest.mark.parametrize("how, kind", [("crash", "failed"), ("role", "refused")])
def test_a_deploy_the_server_crashes_on_or_refuses_for_the_role_holds_the_bench(tmp_path, monkeypatch, how, kind):
    rig, srv = servers_rig(tmp_path, monkeypatch, static=False)
    run, mgr = rig.run, rig.mgr
    srv.set(**({"deploy": "crash"} if how == "crash" else {"role_refused": ["request_deploy"]}))

    async def go():
        await setup_run(run, mgr)
        await until(run, mgr, lambda: run.ended)
    asyncio.run(go())
    held = run.s["bench"]["held"]
    assert held["step"] == "deploy" and held["why"].startswith(f"部署没做成（{kind}）")
    assert ("exited" if how == "crash" else "not granted physical") in held["why"]
    assert run.s["bench"]["actions"][-1]["outcome"] == kind and rig.calls() == []


def test_tests_first_with_ten_failed_tests_listed_goes_to_a_person(tmp_path, monkeypatch):
    rig, srv = servers_rig(tmp_path, monkeypatch, static=False)
    team = rig.run.team
    listed = [f"plain: FAILED Other.T{i}" for i in range(servers.UNIT_LISTED)]

    async def go():
        wt, base, head, triage = await make_tests_first_repo(tmp_path)
        srv.set(unit={"verdict": "FAIL", "reasons": listed})
        with pytest.raises(servers.Unavailable, match="只列出前 10 个失败的测试"):
            await servers.tests_first(wt, team, base=base, head=head, triage=triage, results=tmp_path / "tf")
        srv.set(unit={"verdict": "FAIL", "reasons": ["plain: FAILED Fix.F001_signal"], "commit": "0" * 40})
        with pytest.raises(servers.Unavailable, match="不是测试先行的提交"):
            await servers.tests_first(wt, team, base=base, head=head, triage=triage, results=tmp_path / "tf")
    asyncio.run(go())


async def make_tests_first_repo(tmp_path):
    src = tmp_path / "tf2-src"
    (src / "src").mkdir(parents=True)
    (src / "tests").mkdir()
    (src / "src" / "a.cpp").write_text("int a;\n")
    repo, wt = tmp_path / "runs" / "rtf2" / "repo", tmp_path / "runs" / "rtf2" / "wt" / "_run"
    base = await gitwork.create_repo(src, repo, "", "x", existing=True)
    await gitwork.add_worktree(repo, wt, "team/rtf2/run", base)
    (wt / "tests").mkdir(exist_ok=True)
    (wt / "tests" / "fix_test.cpp").write_text("TEST(Fix, F001_signal) { /* F-001 */ }\n")
    sh(wt, "add", "-A")
    sh(wt, "commit", "-q", "-m", "F-001 test")
    approve_triage_at(wt.parents[1])
    triage = {"base": base, "findings": [{"id": "F-001", "decision": "fix", "evidence": "unit-test"}]}
    return wt, base, sh(wt, "rev-parse", "HEAD").strip(), triage


def test_a_run_without_a_triage_leaves_none_on_the_servers(tmp_path, monkeypatch):
    rig, srv = servers_rig(tmp_path, monkeypatch, static=False)
    st = servers.setup(rig.run.team)
    (srv.triage_dir / "triage.json").write_text('{"approved": {"by": "an earlier run"}}')
    (srv.triage_dir / "triage.json.sha256").write_text("cd" * 32 + "\n")
    servers.put_triage(st, tmp_path / "no-such-run" / "triage.json")
    assert sorted(p.name for p in srv.triage_dir.iterdir()) == []  # no other run's triage is judged


def test_the_board_cannot_decide_in_servers_mode_without_the_switch(tmp_path, monkeypatch):
    rig, srv = servers_rig(tmp_path, monkeypatch, static=False)
    service, httpkit = mod("service"), mod("httpkit")
    team_file = tmp_path / "team-servers.json"
    team_file.write_text(json.dumps({k: v for k, v in rig.run.team.items() if k != "skip_owners"}), encoding="utf-8")
    data = tmp_path / "svc"
    data.mkdir()
    (data / "sample.json").write_text(json.dumps({"sample": str(Path(team_mod.__file__).parents[3])}))
    ctx = SimpleNamespace(name="vstatd-team", logger=logging.getLogger("kcteam-test"), data_dir=str(data))
    svc = service.Service(ctx, manager=rig.mgr, work_root=tmp_path / "work", tick_s=60, team_file=team_file)
    with pytest.raises(httpkit.AppError) as off:
        asyncio.run(svc.bench_decide("20261116T120000-deploy-ab12", "approve", "bc9372", ""))
    assert off.value.code == "decide_off" and off.value.status == 409
