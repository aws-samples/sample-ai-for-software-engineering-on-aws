"""Servers mode (D17) with stand-in ``build`` and ``bench`` MCP servers: one script that speaks MCP over stdio as
``mcp/build`` and ``mcp/bench`` do, keeps an audit log and a state folder of its own, and does what a test's spec
says. The bench stand-in writes its requests into a bench state directory of the test's own and waits there for a
decision the test writes, as the person at the console would. No Docker, no QEMU."""

import asyncio
import json
import sys
import time
from pathlib import Path

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
    if check in sp.get("refuse", []):
        raise Refused("the repair count is over its limit; a person decides, then resets it")
    with open(state + "/judged.log", "a") as f:
        f.write(json.dumps({"check": check, "head": head, "files": git("ls-files").split(),
                            "triage": open(P["triage"]).read() if os.path.exists(P["triage"]) else None}) + "\n")
    v = sp.get(check, {})
    verdict = v.get("verdict", "PASS")
    data = {"check": check, "verdict": verdict, "commit": head, "reasons": v.get("reasons", []), "tier": None,
            "summary": f"{check}: {verdict}", "inputs": {}, "details": {}}
    if check == "build" and verdict == "PASS":
        digest = "bc93723c" + head[:56]
        data["details"]["digest"] = digest
        os.makedirs(state + "/results/artifacts", exist_ok=True)
        open(state + "/results/artifacts/vstatd", "w").write("ELF " + head)
        json.dump(data, open(state + "/results/build.json", "w"))
    return {"outcome": "ok", "exit_status": 0, "check": check, "commit": head, "verdict": verdict,
            "summary": f"$ checks/{check}.sh\n{check}: {verdict}\n", "result": data}

def bench_tool(name, args):
    sp = spec()
    if name in ("lease_acquire", "lease_release"):
        return {"outcome": "ok", "yours": True}
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
    assert calls == {"read-only": 2, "controlled-write": 16, "physical": 2}
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
