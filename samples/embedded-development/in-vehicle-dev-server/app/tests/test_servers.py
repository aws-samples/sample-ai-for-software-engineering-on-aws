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
import hashlib, json, os, secrets, subprocess, sys, time, tomllib
which, cfg = sys.argv[1], tomllib.load(open(sys.argv[sys.argv.index("--config") + 1], "rb"))
P = cfg["paths"]
state = P["state"]
os.makedirs(state, exist_ok=True)
session = f"developer:{os.getpid()}:{secrets.token_hex(4)}"
CLASS = {"workspace_status": "read-only", "run_check": "controlled-write", "read_result": "read-only",
         "lease_acquire": "controlled-write",
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

PAGE = state + "/results/evidence.md"


def build_tool(name, args):
    if name == "workspace_status":
        return {"outcome": "ok", "head": git("rev-parse", "HEAD"), "changes": git("status", "--porcelain").splitlines()}
    check, sp, head = args["check"], spec(), git("rev-parse", "HEAD")
    if name == "read_result":
        if sp.get("read") == "refuse":
            raise Refused("read_result release is not granted to this session")
        if sp.get("read") == "exit":
            sys.exit(3)  # the server dies while the page is read back
        out = {"check": check, "result": None, "log_tail": ""}
        if check == "release":
            # as core.py _read_result does: the text decoded with errors="replace", the digest of the bytes
            raw = open(PAGE, "rb").read() if os.path.exists(PAGE) else None
            out["evidence_page"] = raw.decode(errors="replace") if raw else None
            out["evidence_sha256"] = hashlib.sha256(raw).hexdigest() if raw else None
            if sp.get("page") == "changed":  # another call published over the page between the two calls
                out["evidence_page"] = "# Evidence page: another call's\n"
                out["evidence_sha256"] = hashlib.sha256(out["evidence_page"].encode()).hexdigest()
            if sp.get("page") == "readnodigest":  # an answer without the digest: the app computes its own
                del out["evidence_sha256"]
        return out
    if check == sp.get("exit_on"):
        sys.exit(3)  # the server dies in the middle of the call
    if check == sp.get("sleep_on"):
        time.sleep(30)
    if check in sp.get("refuse", []):
        raise Refused(sp.get("refuse_why", "the repair count is over its limit; a person decides, then resets it"))
    if check in sp.get("error_on", []):  # as mcp/build answers when release cannot read the bench's results
        return {"outcome": "refused", "exit_status": None, "check": check, "commit": head, "verdict": "ERROR",
                "summary": "", "problem": "the bench results are not published: no results.lock"}
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
    if check == "release" and verdict == "PASS":
        # as mcp/build does after a release that passed: checks/evidence-page.sh writes the page, the server
        # publishes it beside the results, and the answer carries its outcome and digest, never the page itself
        if sp.get("page") == "none":
            out["evidence_page"] = "not published: checks/evidence-page.sh wrote no page"
        else:
            judged = sorted(n[:-5] for n in os.listdir(state + "/results") if n.endswith(".json"))
            page = "# Evidence page: vstatd\n\n" + ", ".join(judged + ["release"]) + "\n"
            raw = page.encode()
            if sp.get("page") == "replaced":  # a byte the server can only read back with errors="replace"
                raw += b"\xff\n"
            os.makedirs(state + "/results", exist_ok=True)
            open(PAGE, "wb").write(raw)
            out["evidence_page"] = "published"
            out["evidence_sha256"] = hashlib.sha256(raw).hexdigest()
            if sp.get("page") == "nodigest":  # published, but the answer carries no digest
                del out["evidence_sha256"]
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
    """test_bench's rig (bench state, baseline, doctor, a release check), its team switched to servers mode: build
    and static before the bench on the build server, logdiff and runtime-limits after it on the bench server, and
    the rerun's release on the build server, which publishes the evidence page with it (D17)."""
    rig = Rig(tmp_path, monkeypatch, release=True)
    srv = Servers(tmp_path, rig.state, rig.baseline)
    team = dict(rig.run.team)
    static_check = rig.bench.check("static", owner="dev", args=["project", "triage"])
    keep = [c for c in team["checks"] if c["name"] != "unit"]
    team.update(srv.team_part(), checks=[keep[0], *([static_check] if static else []), *keep[1:]])
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
    # the before-bench round, then the rerun and its release: each on the round's commit, with the run's approved triage
    assert [(j["check"], j["head"]) for j in judged] == [("build", head), ("static", head)] * 2 + [("release", head)]
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
    assert calls == {"read-only": 4, "controlled-write": 17, "physical": 2, "refused": 0}
    trail = audit.build(run.s, run.events, scorecard.records(rig.state))
    asked = [x for x in trail["entries"]
             if x["step"] == "bench" and x["actor"] == "app" and "20261116T" in x["evidence"]]
    assert len(asked) == 1  # the deploy request the bench server made for this run, in its audit trail


def _rerun_session(srv) -> list:
    """The build server's calls of the last session: the rerun's release, with the page read back after it."""
    lines = [ln for ln in srv.audit_lines("build") if ln["outcome"] != "started"]
    return [(ln["tool"], ln["args"], ln.get("class")) for ln in lines if ln["tool"] != "workspace_status"][-2:]


def test_the_reruns_release_and_its_evidence_page_come_from_the_build_server(tmp_path, monkeypatch):
    rig, srv = servers_rig(tmp_path, monkeypatch)
    run, mgr = rig.run, rig.mgr

    async def go():
        await setup_run(run, mgr)
        await until(run, mgr, lambda: run.ended)
        assert run.s["status"] == "done", [e["text"] for e in run.events][-4:]
    asyncio.run(go())
    results = Path(run.s["repo"]).parent / "results" / "rerun"
    # the release check is run_check release on the build server, and the page is read back in the same session
    assert _rerun_session(srv) == [("run_check", {"check": "release"}, "controlled-write"),
                                   ("read_result", {"check": "release"}, "read-only")]
    # the server's result is kept where direct mode keeps it (test_release: <rerun>/release.json), with its log
    assert json.loads((results / "release.json").read_text()) == {
        "check": "release", "verdict": "PASS", "commit": run.s["bench"]["head"], "reasons": [], "tier": None,
        "summary": "release: PASS", "inputs": {}, "details": {}}
    assert (results / "release.run.log").read_text().startswith("$ checks/release.sh")
    assert run.s["rerun"]["release"] == {"verdict": "PASS", "summary": "release: PASS", "reasons": []}
    # the page the server published, beside the release result, and on the sign-off dialog
    page = (srv.build_state / "results" / "evidence.md").read_text()
    assert (results / "evidence.md").read_text() == page and run.s["rerun"]["evidence"] == str(results / "evidence.md")
    assert board.release_view(run)["evidence"] == page and page.startswith("# Evidence page: vstatd")
    assert "release" in page and run.sign_block() == ""
    # nothing of the release or the page ran in the app's build container
    ran = rig.bench.log.read_text() if rig.bench.log.exists() else ""
    assert "release" not in ran and "evidence" not in ran


@pytest.mark.parametrize("how, tools", [("none", ["run_check"])])
def test_a_page_the_server_did_not_publish_is_left_out(tmp_path, monkeypatch, how, tools):
    """The release verdict stands; the sign-off dialog then has no page and a person decides."""
    rig, srv = servers_rig(tmp_path, monkeypatch, rid=f"r1120page{how}")
    run, mgr = rig.run, rig.mgr
    srv.set(page=how)

    async def go():
        await setup_run(run, mgr)
        await until(run, mgr, lambda: run.ended)
    asyncio.run(go())
    results = Path(run.s["repo"]).parent / "results" / "rerun"
    assert run.s["status"] == "done" and run.s["rerun"]["release"]["verdict"] == "PASS"
    assert not (results / "evidence.md").exists() and run.s["rerun"]["evidence"] is None
    assert board.release_view(run)["evidence"] is None and run.sign_block() == ""
    last = [ln["tool"] for ln in srv.audit_lines("build")
            if ln["outcome"] != "started" and ln["tool"] != "workspace_status"]
    assert last[-len(tools):] == tools  # "none": nothing to read back


def _release_held_for_a_person(run, srv, held="独立重跑后 release 检查没判出结果：") -> None:
    """D7 and D9: no page, sign-off shut, the bench held at the rerun for a person, nothing sent to a role."""
    assert not (Path(run.s["repo"]).parent / "results" / "rerun" / "evidence.md").exists()
    assert run.s["rerun"]["evidence"] is None and board.release_view(run)["evidence"] is None
    assert run.sign_block().startswith("独立重跑后 release.sh 没通过")
    assert run.s["status"] == "failed" and run.s["bench"]["held"]["step"] == "rerun"
    assert run.s["bench"]["held"]["why"].startswith(held)  # BLOCKED: release.sh did not run, or not to the end
    assert not any(e.get("code") == "bounce.checks" for e in run.events)  # nothing went to a role


@pytest.mark.parametrize("how, why", [("refuse", "build 服务器拒绝了"), ("exit", "exited"), ("hang", "no answer within"),
                                      ("error", "the bench results are not published")])
def test_a_server_that_refuses_dies_or_hangs_on_the_release_holds_sign_off(tmp_path, monkeypatch, how, why):
    """The ``error`` answer is mcp/build's when release cannot read the bench's results: an answer, with no result."""
    rig, srv = servers_rig(tmp_path, monkeypatch)
    run, mgr = rig.run, rig.mgr
    if how == "hang":
        monkeypatch.setattr(servers, "MARGIN_S", 0)
        for c in run.team["checks"]:
            c["timeout_s"] = 1
    srv.set(**{"refuse": ["release"]} if how == "refuse" else {"exit_on": "release"} if how == "exit" else
            {"error_on": ["release"]} if how == "error" else {"sleep_on": "release"})

    async def go():
        await setup_run(run, mgr)
        await until(run, mgr, lambda: run.ended, timeout=40)
        rel = run.s["rerun"]["release"]
        assert rel["verdict"] == "BLOCKED" and why in rel["reasons"][0]  # D7: no retry of its own
        _release_held_for_a_person(run, srv)
        if how == "error":  # the bench panel's 重试 runs the rerun again, the release on the build server included
            srv.set()
            assert await run.retry(by="alice") == ["bench"]
            await until(run, mgr, lambda: run.ended, timeout=40)
            assert run.s["status"] == "done" and run.s["rerun"]["release"]["verdict"] == "PASS"
            assert run.s["rerun"]["evidence"] and run.sign_block() == ""
    asyncio.run(go())


def test_a_release_that_fails_on_the_build_server_has_no_evidence_page(tmp_path, monkeypatch):
    """Unlike direct mode, whose evidence-page.sh still writes a page: mcp/build publishes one only after a release
    that passed, so the app reads none back, not even a page an earlier release left on the server."""
    rig, srv = servers_rig(tmp_path, monkeypatch)
    run, mgr = rig.run, rig.mgr
    srv.set(release={"verdict": "FAIL", "reasons": ["logdiff: judged another build"]})
    (srv.build_state / "results").mkdir(parents=True, exist_ok=True)
    (srv.build_state / "results" / "evidence.md").write_text("# Evidence page: an earlier release\n")

    async def go():
        await setup_run(run, mgr)
        await until(run, mgr, lambda: run.ended)
    asyncio.run(go())
    assert run.s["rerun"]["release"] == {"verdict": "FAIL", "summary": "release: FAIL",
                                         "reasons": ["logdiff: judged another build"]}
    assert _rerun_session(srv)[-1] == ("run_check", {"check": "release"}, "controlled-write")  # nothing read back
    _release_held_for_a_person(run, srv, held="独立重跑后 release.sh 没通过：logdiff: judged another build")


@pytest.mark.parametrize("how, why", [("changed", "证据页摘要核对不上"), ("replaced", "证据页摘要核对不上"),
                                      ("nodigest", "没报它的摘要")])
def test_a_published_page_whose_digest_does_not_check_out_blocks_the_release(tmp_path, monkeypatch, how, why):
    """The digest judged is the one of the text read back: a page another call published over in between, bytes the
    server could only read with errors="replace", or a run_check answer with no digest: no page, BLOCKED (D7)."""
    rig, srv = servers_rig(tmp_path, monkeypatch, rid=f"r1120digest{how}")
    run, mgr = rig.run, rig.mgr
    srv.set(page=how)

    async def go():
        await setup_run(run, mgr)
        await until(run, mgr, lambda: run.ended)
    asyncio.run(go())
    rel = run.s["rerun"]["release"]
    assert rel["verdict"] == "BLOCKED" and why in rel["reasons"][0]
    assert "release 检查本身判的是 PASS" in rel["reasons"][0]  # the release passed; the page is what is missing
    assert [t for t, _, _ in _rerun_session(srv)] == ["run_check", "read_result"]
    _release_held_for_a_person(run, srv)


@pytest.mark.parametrize("how, why", [("refuse", "is not granted to this session"), ("exit", "exited with 3")])
def test_a_read_result_the_server_refuses_or_dies_on_blocks_the_release(tmp_path, monkeypatch, how, why):
    """read_result is read-only, but a page the app cannot read back is a page it cannot show at sign-off, so the
    release is BLOCKED for a person (D7). The reason names read_result and that the release itself passed."""
    rig, srv = servers_rig(tmp_path, monkeypatch, rid=f"r1120read{how}")
    run, mgr = rig.run, rig.mgr
    srv.set(read=how)

    async def go():
        await setup_run(run, mgr)
        await until(run, mgr, lambda: run.ended, timeout=40)
    asyncio.run(go())
    rel = run.s["rerun"]["release"]
    assert rel["verdict"] == "BLOCKED" and "read_result release 没成功" in rel["reasons"][0]
    assert "release 检查本身判的是 PASS" in rel["reasons"][0] and why in rel["reasons"][0]
    results = Path(run.s["repo"]).parent / "results" / "rerun"
    assert json.loads((results / "release.json").read_text())["verdict"] == "PASS"  # the server's own verdict is kept
    _release_held_for_a_person(run, srv)


def test_the_page_is_judged_by_its_own_digest_not_the_servers_second_claim(tmp_path, monkeypatch):
    """read_result's own evidence_sha256 is read but not judged: a page whose text matches the digest run_check
    reported is kept even when that second answer carries none."""
    rig, srv = servers_rig(tmp_path, monkeypatch, rid="r1120readnodigest")
    run, mgr = rig.run, rig.mgr
    srv.set(page="readnodigest")

    async def go():
        await setup_run(run, mgr)
        await until(run, mgr, lambda: run.ended)
    asyncio.run(go())
    results = Path(run.s["repo"]).parent / "results" / "rerun"
    assert run.s["status"] == "done" and run.s["rerun"]["release"]["verdict"] == "PASS"
    page = (srv.build_state / "results" / "evidence.md").read_text()
    assert (results / "evidence.md").read_text() == page and run.sign_block() == ""


def test_a_team_that_asks_for_no_page_reads_none_back(tmp_path, monkeypatch):
    """The team file's evidence_page says whether the team wants a page at all (team._rerun runs no page without
    it): the app then makes no read_result call and writes no evidence.md beside the release result."""
    rig, srv = servers_rig(tmp_path, monkeypatch, rid="r1120nopage")
    run, mgr = rig.run, rig.mgr
    run.team.pop("evidence_page")

    async def go():
        await setup_run(run, mgr)
        await until(run, mgr, lambda: run.ended)
    asyncio.run(go())
    results = Path(run.s["repo"]).parent / "results" / "rerun"
    assert run.s["status"] == "done" and run.s["rerun"]["release"]["verdict"] == "PASS"
    assert not (results / "evidence.md").exists() and run.s["rerun"]["evidence"] is None
    assert board.release_view(run)["evidence"] is None and run.sign_block() == ""
    assert [t for t, _, _ in _rerun_session(srv)][-1:] == ["run_check"]  # nothing read back


def test_the_release_check_of_a_servers_team_must_be_the_build_servers_own(tmp_path, monkeypatch):
    rig, srv = servers_rig(tmp_path, monkeypatch)
    team = {**rig.run.team, "checks": [{**c, "name": "signoff"} if c["when"] == "release" else c
                                       for c in rig.run.team["checks"]]}
    with pytest.raises(ValueError, match="检查 signoff 不归任何服务器"):
        team_mod.check_team(team)


def test_in_direct_mode_the_release_stays_in_the_apps_build_container(tmp_path, monkeypatch):
    """The same team file without ``connectors``: the release round goes to checks.py and no server is started.
    The whole direct flow, the page included, is test_release.py's."""
    rig, srv = servers_rig(tmp_path, monkeypatch)
    team = team_mod.check_team({k: v for k, v in rig.run.team.items() if k not in ("connectors", "servers")})
    assert not servers.on(team) and team.get("evidence_page")

    async def go():
        await rig.run.tick()
        approve_triage(rig.run)
        root = Path(rig.run.s["repo"]).parent
        head = sh(Path(rig.run.s["run_wt"]), "rev-parse", "HEAD").strip()
        return await servers.run_tests(Path(rig.run.s["run_wt"]), team, head=head, phase="release",
                                       results=root / "results" / "direct", triage=root / "triage.json")
    wall = asyncio.run(go())
    assert [r["name"] for r in wall["checks"]] == ["release"] and wall["checks"][0]["verdict"] == "PASS"
    assert "release.sh" in rig.bench.log.read_text() and not srv.audit_lines("build")


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
        assert "build 服务器的交叉构建已连续失败 3 次、上限 3" in held["why"]
        assert "再失败一次" in held["why"] and "最后一次尝试" in held["why"]  # one attempt is left: no reset yet
        assert "commands" not in held
        assert t["rounds"] == {"build": 1}  # the hold takes no repair round (D7)
        view = board.detail(run, mgr=mgr, scrub=lambda x: x, now=time.time())["tests"]["held"]
        assert not view.get("commands")
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


def test_at_the_bound_one_attempt_is_left_and_only_past_it_is_the_reset_command_given():
    words = ["~/s/venv/bin/python", "-I", "-m", "buildserver", "--config", "~/s/build.toml"]
    at, past = servers.at_bound(3, 3), servers.at_bound(4, 3)
    assert "再失败一次，build 服务器就会拒绝" in at and "点「重试」用掉最后一次尝试" in at and "重置" not in at
    assert "已经拒绝" in past and "重置计数" in past and "最后一次" not in past
    run = SimpleNamespace(team={"connectors": "servers", "servers": {"build": words},
                                "checks": [{"name": "build", "when": "before_bench"}]},
                          s={"tests": {"repair": {"failures_in_a_row": 3, "limit_retries": 3}}})
    assert team_mod.TeamRun._reset_command(run) is None and team_mod.TeamRun._repair_stop(run) == (3, 3)
    run.s["tests"]["repair"]["failures_in_a_row"] = 4
    assert team_mod.TeamRun._reset_command(run) == "~/s/venv/bin/python " + RESET.format(conf="~/s/build.toml", n=4)


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


def test_with_the_switch_the_board_decides_a_request_made_outside_a_run_while_the_runs_are_over(tmp_path, monkeypatch):
    """台架现在 on an ended run's panel: POST /bench/decide names no run, so a request from bench tools (a person
    recording the baseline) is decided by the bench's own decide() whatever the runs' state."""
    rig, srv = servers_rig(tmp_path, monkeypatch, static=False)
    service = mod("service")
    team = {k: v for k, v in rig.run.team.items() if k != "skip_owners"}
    team["servers"] = {**team["servers"], "board_decides": True}
    team_file = tmp_path / "team-servers.json"
    team_file.write_text(json.dumps(team), encoding="utf-8")
    data = tmp_path / "svc"
    data.mkdir()
    (data / "sample.json").write_text(json.dumps({"sample": str(Path(team_mod.__file__).parents[3])}))
    ctx = SimpleNamespace(name="vstatd-team", logger=logging.getLogger("kcteam-test"), data_dir=str(data))
    svc = service.Service(ctx, manager=rig.mgr, work_root=tmp_path / "work", tick_s=60, team_file=team_file)
    rig.run.s.update(status="done", ended_at=time.time() - 600)
    svc.runs[rig.run.s["id"]] = rig.run
    state, rid, digest = Path(rig.state), "20261118T212800-deploy-6bb0", "e5b2a7" + "0" * 58
    (state / "requests").mkdir(parents=True, exist_ok=True)
    (state / "decisions").mkdir(exist_ok=True)
    (state / "requests" / f"{rid}.json").write_text(json.dumps(
        {"id": rid, "action": "deploy", "digest": digest, "detail": "", "requested_at": "2026-11-18T13:28:00.000Z",
         "expires": time.time() + 200, "timeout_s": 300, "requested_by": "bench tools"}), encoding="utf-8")
    res = asyncio.run(svc.bench_decide(rid, "approve", "e5b2a7", ""))
    assert res["decision"]["verdict"] == "approved" and (state / "decisions" / f"{rid}.json").exists()


# --- from the review of #57: a run keeps who approves its bench requests ---------------------------------------- #

def _service_for(rig, tmp_path, name):
    """A Service whose team file is the rig's servers-mode team (console-only approval) and its data directory."""
    service = mod("service")
    team_file = tmp_path / f"team-{name}.json"
    team_file.write_text(json.dumps({k: v for k, v in rig.run.team.items() if k != "skip_owners"}), encoding="utf-8")
    data = tmp_path / f"svc-{name}"
    data.mkdir()
    (data / "sample.json").write_text(json.dumps({"sample": str(Path(team_mod.__file__).parents[3])}))
    ctx = SimpleNamespace(name="vstatd-team", logger=logging.getLogger("kcteam-test"), data_dir=str(data))
    return service.Service(ctx, manager=rig.mgr, work_root=tmp_path / f"work-{name}", tick_s=60, team_file=team_file)


def test_a_run_in_progress_keeps_console_only_approval_whatever_is_saved_on_settings(tmp_path, monkeypatch):
    """A servers-mode run that started with console-only approval: switching 设置 to direct mode, or turning
    board_decides on, while it is in progress must not let 批准 on the board decide its pending request. Once the
    run is over the saved settings are what counts."""
    httpkit = mod("httpkit")
    rig, srv = servers_rig(tmp_path, monkeypatch, static=False)
    assert not rig.run.ended and servers.board_decides(rig.run.team) is False
    before = {k: rig.run.s.get(k) for k in ("status", "ended_at")}
    state, digest = Path(rig.state), "e5b2a7" + "0" * 58
    (state / "requests").mkdir(parents=True, exist_ok=True)
    (state / "decisions").mkdir(exist_ok=True)
    for n, patch in enumerate(({"mode": "direct"}, {"board_decides": True})):
        svc = _service_for(rig, tmp_path, f"s{n}")
        svc.runs[rig.run.s["id"]] = rig.run
        assert asyncio.run(svc.save_settings({"settings": patch}))["ok"] is True
        team, _ = svc._default_team()
        assert servers.board_decides(team) is True, patch  # the next run would be approved on the board
        rid = f"20261118T21280{n}-deploy-6bb0"
        (state / "requests" / f"{rid}.json").write_text(json.dumps(
            {"id": rid, "action": "deploy", "digest": digest, "detail": "", "requested_at": "2026-11-18T13:28:00Z",
             "expires": time.time() + 200, "timeout_s": 300, "requested_by": "vstatd-team r1116servers"}),
            encoding="utf-8")
        with pytest.raises(httpkit.AppError) as off:
            asyncio.run(svc.bench_decide(rid, "approve", "e5b2a7", ""))
        assert (off.value.code, off.value.status) == ("decide_off", 409), patch
        assert not (state / "decisions" / f"{rid}.json").exists(), patch
        rig.run.s.update(status="done", ended_at=time.time())  # the run is over: the saved settings decide
        assert asyncio.run(svc.bench_decide(rid, "approve", "e5b2a7", ""))["decision"]["verdict"] == "approved"
        rig.run.s.update(before)


def test_a_restart_leaves_a_loaded_runs_approval_rules_as_the_run_started(tmp_path, monkeypatch):
    """Service.start loads every run as it was saved: board_decides turned on in 设置 since does not reach a run that
    started with console-only approval."""
    rig, srv = servers_rig(tmp_path, monkeypatch, static=False)
    svc = _service_for(rig, tmp_path, "restart")
    assert asyncio.run(svc.save_settings({"settings": {"board_decides": True}}))["ok"] is True
    rid = rig.run.s["id"]
    svc._deps.store.write(rid, json.dumps(rig.run.s, ensure_ascii=False), [])

    async def restart():
        await svc.start()
        await svc.stop()
    asyncio.run(restart())
    loaded = svc.runs[rid].team
    assert loaded["servers"].get("board_decides", False) is False and servers.board_decides(loaded) is False
    team, _ = svc._default_team()
    assert servers.board_decides(team) is True  # the next run gets the setting


def test_a_team_file_that_cannot_be_read_does_not_stop_a_run_in_progress_from_being_decided(tmp_path, monkeypatch):
    """#64: bench_decide answered bad_team when the team file could not be read, although the run in progress's own
    team says who approves. It is used then; with no run in progress the answer is still bad_team."""
    httpkit = mod("httpkit")
    rig, srv = servers_rig(tmp_path, monkeypatch, static=False)
    rig.run.team["servers"] = {**rig.run.team["servers"], "board_decides": True}  # this run is approved on the board
    svc = _service_for(rig, tmp_path, "broken")
    svc.team_file.write_text("{ not json", encoding="utf-8")
    state, rid, digest = Path(rig.state), "20261118T212800-deploy-6bb0", "e5b2a7" + "0" * 58
    (state / "requests").mkdir(parents=True, exist_ok=True)
    (state / "decisions").mkdir(exist_ok=True)
    (state / "requests" / f"{rid}.json").write_text(json.dumps(
        {"id": rid, "action": "deploy", "digest": digest, "detail": "", "requested_at": "2026-11-18T13:28:00Z",
         "expires": time.time() + 200, "timeout_s": 300, "requested_by": "vstatd-team r1116servers"}), encoding="utf-8")
    with pytest.raises(httpkit.AppError) as e:  # no run in progress: nothing else says who approves
        asyncio.run(svc.bench_decide(rid, "approve", "e5b2a7", ""))
    assert (e.value.code, e.value.status) == ("bad_team", 500)
    svc.runs[rig.run.s["id"]] = rig.run
    assert not rig.run.ended
    res = asyncio.run(svc.bench_decide(rid, "approve", "e5b2a7", ""))
    assert res["decision"]["verdict"] == "approved" and (state / "decisions" / f"{rid}.json").exists()
