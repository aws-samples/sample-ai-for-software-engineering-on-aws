"""The service (background loop, restart) and the HTTP routes, with the stdlib aiohttp fakes."""

import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from http_fakes import AppRoute, FakeWeb, call, owner_check
from teamkit import FakeManager, act, default_tests, finish, mod

service, handlers, toollog, constants, team_mod = mod("service"), mod("handlers"), mod("toollog"), mod("constants"), mod("team")
NEW_ROUTES = [("GET", "/board"), ("GET", "/runs"), ("POST", "/runs"), ("POST", "/runs/r1006abcd/stop")]


def make(tmp_path, mgr, **kw):
    ctx = SimpleNamespace(name="aidlc-team", logger=logging.getLogger("kcteam-test"), data_dir=str(tmp_path / "data"))
    svc = service.Service(ctx, manager=mgr, work_root=tmp_path / "work", run_tests=default_tests(), **kw)
    return svc, handlers.build_routes(svc, AppRoute, web=FakeWeb, is_owner=owner_check)


def test_new_routes_are_owner_only(tmp_path):
    svc, routes = make(tmp_path, FakeManager())

    async def go():
        assert (await call(routes, "GET", "/health", user=None)).status == 200
        for method, path in NEW_ROUTES:
            assert (await call(routes, method, path, user=None)).status == 401, path
            r = await call(routes, method, path, owner=False)
            assert (r.status, r.code) == (403, "owner_only"), path
            r = await call(routes, method, path, app="some-app")
            assert (r.status, r.code) == (403, "app_token_forbidden"), path
        r = await call(routes, "POST", "/runs", json_body={"requirement": "x"})
        assert (r.status, r.code) == (503, "not_started")

    asyncio.run(go())


def test_create_board_runs_and_stop_through_the_routes(tmp_path):
    mgr = FakeManager()
    svc, routes = make(tmp_path, mgr, tick_s=60)

    async def go():
        await svc.start()
        try:
            r = await call(routes, "POST", "/runs", json_body={"requirement": 5})
            assert (r.status, r.code) == (400, "invalid_requirement")
            r = await call(routes, "POST", "/runs", json_body={"requirement": "x" * 8001})
            assert (r.status, r.code) == (400, "requirement_too_long")
            r = await call(routes, "POST", "/runs", raw=b"[1]")
            assert (r.status, r.code) == (400, "invalid_json")
            r = await call(routes, "POST", "/runs", json_body={"requirement": "  读书会报名\n1. 列出活动  "})
            assert r.status == 200
            rid = r.body["run"]
            assert [mgr.role_of(a) for a in mgr.live()] == ["pm"]  # set up and started before the answer
            assert "1. 列出活动" in (tmp_path / "work" / "runs" / rid / "repo" / "README.md").read_text()
            r = await call(routes, "POST", "/runs", json_body={})
            assert (r.status, r.code) == (409, "run_active")
            board = (await call(routes, "GET", "/board")).body
            assert board["run"]["id"] == rid and board["run"]["title"] == "读书会报名" and board["run"]["status"] == "running"
            assert board["run"]["roles"][0]["status"] == "running"
            assert (await call(routes, "GET", f"/board?run={rid}")).body["run"]["id"] == rid
            assert [c["id"] for c in (await call(routes, "GET", "/runs")).body["runs"]] == [rid]
            r = await call(routes, "POST", f"/runs/{rid}/stop")
            assert r.status == 200 and r.body == {"ok": True, "run": rid, "status": "stopped"} and not mgr.live()
            r = await call(routes, "POST", f"/runs/{rid}/stop")
            assert (r.status, r.code) == (409, "run_ended")
            r = await call(routes, "POST", f"/runs/{rid}/signoff", json_body={"by": "研发负责人"})
            assert (r.status, r.code) == (409, "not_signable") and "运行停下了" in r.body["error"]  # nothing was delivered
            for bad in ("r1006zzzz", "x.y"):
                r = await call(routes, "POST", f"/runs/{bad}/stop")
                assert (r.status, r.code) == (404, "not_found")
            assert (await call(routes, "POST", "/runs", json_body={})).status == 200  # the next run may start
        finally:
            await svc.stop()

    asyncio.run(go())


def test_the_background_loop_moves_runs_survives_errors_and_a_restart_reloads(tmp_path):
    mgr = FakeManager()
    svc, _ = make(tmp_path, mgr, tick_s=0.01)

    async def until(cond, tries=300):
        for _ in range(tries):
            if cond():
                return True
            await asyncio.sleep(0.01)
        return False

    async def go():
        await svc.start()
        rid = await svc.create_run("")
        run = svc.runs[rid]
        act(mgr.by_role("pm"), {"docs/product/acceptance.md": "AC-1\n"})
        finish(mgr.by_role("pm"))
        assert await until(lambda: len(mgr.spawned) == 3)  # nobody called tick: the loop did
        calls = []

        async def boom():
            calls.append(1)
            raise RuntimeError("git went away")

        run.tick = boom
        assert await until(lambda: len(calls) >= 3)  # a failing tick is logged, the loop goes on
        del run.tick
        await svc.stop()
        assert svc._loop is None and not svc._ticks
        again, _ = make(tmp_path, mgr, tick_s=0.01)
        await again.start()
        try:
            assert again.runs[rid].lane("architect")["status"] == "running" and again.runs[rid].events[-1]["seq"] >= 8
            finish(mgr.by_role("architect"))
            assert await until(lambda: again.runs[rid].lane("architect")["status"] == "merged")
        finally:
            await again.stop()

    asyncio.run(go())


def sel_line(aid, op, kind="", reason=None, event="tool_invocation"):
    meta = {"subagent_id": aid, **({"reason": reason} if reason else {})}
    return json.dumps({"event_type": event, "source": "subagent", "caller_identity": f"subagent:{aid}", "operation": op,
                       "tool_kind": kind, "timestamp": "2026-10-05T17:12:41.440200+00:00", "metadata": meta}) + "\n"



def test_the_demo_default_model_stays_opus():
    """A smoke run passes {"model"} to POST /runs; the team file itself keeps the demo default."""
    import json as _json
    from backend.team.constants import TEAM_FILE

    team = _json.loads(TEAM_FILE.read_text(encoding="utf-8"))
    assert team["defaults"]["model"] == "claude-opus-5.5"  # the demo default is untouched


def test_a_run_that_ends_keeps_the_team_roster_of_that_moment(tmp_path):
    svc, _ = make(tmp_path, FakeManager())

    class Run:  # what the pulse looks at: a run of a team that has a workspace
        def __init__(self):
            self.rid, self.ended, self.team, self.s, self.saved = "r1012roster", False, {"workspace": "taoyuan"}, {}, 0
            self.order = []  # no roles: the pulse has nothing to watch

        async def save(self):
            self.saved += 1

        async def tick(self):
            pass

    async def go():
        svc.crew.update(at=float("inf"), members=[{"name": "aidlc-product-agent", "workspace": "taoyuan"},
                                                  {"name": "dev-orchestrator", "workspace": "another-workspace"}])
        svc.sessions.poll = lambda: asyncio.sleep(0)
        run = svc.runs["r1012roster"] = Run()
        await svc.pulse()  # going: nothing kept yet
        assert "crew_members" not in run.s
        run.ended = True
        svc.crew["members"].append({"name": "taoyuan-motion-agent", "workspace": "taoyuan"})
        await svc.pulse()  # it ended since the last pulse: the roster of now is kept with it
        assert run.s["crew_members"] == ["aidlc-product-agent", "taoyuan-motion-agent"] and run.saved == 1
        svc.crew["members"].append({"name": "taoyuan-later-agent", "workspace": "taoyuan"})
        await svc.pulse()  # and stays as it was
        assert run.s["crew_members"] == ["aidlc-product-agent", "taoyuan-motion-agent"]
        for t in list(svc._ticks.values()):
            await t

    asyncio.run(go())


def test_a_run_finds_the_id_of_its_company_knowledge_source_so_the_roles_search_only_that(tmp_path):
    svc, _ = make(tmp_path, FakeManager())
    assert svc.knowledge_id("鹿鸣银行") == ""  # Crew's sources not read yet
    svc.crew["knowledge"] = [{"name": "桃源科技", "id": "kb-ty"}, {"name": "鹿鸣银行", "id": "kb-lm"}]
    assert (svc.knowledge_id("鹿鸣银行"), svc.knowledge_id("桃源科技"), svc.knowledge_id("别家"), svc.knowledge_id("")) == ("kb-lm", "kb-ty", "", "")


def test_a_run_recorded_on_another_mac_imports_to_be_looked_at_and_replayed_only(tmp_path):
    """A run recorded on one Mac, POST /runs/import on another: the record comes in as an ended run that the board
    shows and replays; what needs the code or the sessions (retry, folder, site, file view) says it is not here."""
    mgr = FakeManager()
    src, src_routes = make(tmp_path / "a", mgr, tick_s=60)

    async def record():
        await src.start()
        try:
            rid = (await call(src_routes, "POST", "/runs", json_body={"requirement": "读书会报名"})).body["run"]
            await call(src_routes, "POST", f"/runs/{rid}/stop")
            d = tmp_path / "a" / "data" / "runs" / rid
            state = json.loads((d / "run.json").read_text(encoding="utf-8"))
            events = [json.loads(x) for x in (d / "events.jsonl").read_text(encoding="utf-8").splitlines()]
            return rid, state, events
        finally:
            await src.stop()

    rid, state, events = asyncio.run(record())
    state["imported"] = {"from": "另一台 Mac", "exported_at": 1791770000}
    dst, routes = make(tmp_path / "b", FakeManager(), tick_s=60)

    async def go():
        await dst.start()
        try:
            r = await call(routes, "POST", "/runs/import", json_body={"run": state, "events": events})
            assert r.status == 200 and r.body["run"] == rid and r.body["events"] == len(events)
            r = await call(routes, "POST", "/runs/import", json_body={"run": state, "events": events})
            assert (r.status, r.code) == (409, "exists")
            # imported again with its signature and labels: replaced, its events not doubled
            signed = {**state, "signoff": {"by": "研发负责人", "note": "导入时补签", "at": state["ended_at"], "tests": "0/0"},
                      "delivery": {"name": "读书会报名", "kind": "新应用", "size": "小", "line": "内部系统"}}
            r = await call(routes, "POST", "/runs/import", json_body={"run": signed, "events": events, "replace": True})
            assert r.status == 200 and dst.runs[rid].s["signoff"]["by"] == "研发负责人"
            assert len((tmp_path / "b" / "data" / "runs" / rid / "events.jsonl").read_text(encoding="utf-8").splitlines()) == len(events)
            real = [i for i in (await call(routes, "GET", "/cto")).body["items"] if i["real"] == rid]
            assert real and (real[0]["t"], real[0]["kind"], real[0]["size"], real[0]["line"]) == ("读书会报名", "app", "S", 4)
            dst.runs[rid].s["imported"] = None  # a run of this Mac is never replaced
            r = await call(routes, "POST", "/runs/import", json_body={"run": signed, "events": events, "replace": True})
            assert (r.status, r.code) == (409, "exists")
            dst.runs[rid].s["imported"] = state["imported"]
            r = await call(routes, "POST", "/runs/import", json_body={"run": {**state, "id": "r1", "status": "running"}, "events": []})
            assert (r.status, r.code) == (400, "invalid_import")
            board = (await call(routes, "GET", f"/board?run={rid}")).body
            assert board["run"]["id"] == rid and board["run"]["imported"]["from"] == "另一台 Mac"
            r = await call(routes, "GET", f"/cto/flow?run={rid}")
            assert r.status == 200 and r.body["run"] == rid and isinstance(r.body["segments"], list) and r.body["labels"]["t"] == "读书会报名"
            assert (await call(routes, "GET", "/cto/flow?run=r1006zzzz")).status == 404
            assert [e["seq"] for e in (await call(routes, "GET", f"/runs/{rid}/events")).body["events"]] == [e["seq"] for e in events]
            for method, path in (("POST", f"/runs/{rid}/retry"), ("POST", f"/runs/{rid}/site"), ("POST", f"/runs/{rid}/open")):
                r = await call(routes, method, path, json_body={})
                assert (r.status, r.code) == (409, "imported"), path
        finally:
            await dst.stop()
        # the record is on disk: the app restarting still has it
        again, routes2 = make(tmp_path / "b", FakeManager(), tick_s=60)
        await again.start()
        try:
            assert (await call(routes2, "GET", f"/board?run={rid}")).body["run"]["imported"]
        finally:
            await again.stop()

    asyncio.run(go())


def test_a_run_signed_before_the_signature_merged_its_pr_is_merged_once_when_the_app_starts(tmp_path):
    import subprocess

    def git(cwd, *args):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True,
                              capture_output=True, text=True).stdout.strip()

    svc, _ = make(tmp_path, FakeManager(), tick_s=60)

    async def record():
        await svc.start()
        rid = await svc.create_run("读书会报名")
        await svc.stop()
        run = svc.runs[rid]
        (Path(run.s["run_wt"]) / "app.js").write_text("// 团队的改动\n")
        git(run.s["run_wt"], "add", "-A"), git(run.s["run_wt"], "commit", "-qm", "run")
        run.s.update(status="done", ended_at=run.s["started_at"] + 60)
        run.s["signoff"] = {"by": "研发负责人", "note": "", "at": run.s["ended_at"], "tests": "0/0"}  # no "merged": signed before
        await run.save()
        return rid, run.s["repo"], run.s["branch"]

    rid, repo, branch = asyncio.run(record())
    assert git(repo, "rev-parse", "main") != git(repo, "rev-parse", branch)
    again, _ = make(tmp_path, FakeManager(), tick_s=60)

    async def restart():
        await again.start()
        await again.stop()

    asyncio.run(restart())
    sig = again.runs[rid].s["signoff"]
    assert sig["merged"] == git(repo, "rev-parse", "--short", "main") and git(repo, "rev-parse", "main") == git(repo, "rev-parse", branch)
    assert again.runs[rid].pr()["state"] == "merged"
