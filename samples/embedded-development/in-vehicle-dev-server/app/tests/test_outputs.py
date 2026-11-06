"""The 产出 view (each role's task, reply, tool calls and files)."""

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from http_fakes import call
from teamkit import OUTPUTS, FakeManager, drive, make_run, mod
from test_service import make

outputs, httpkit, constants = mod("outputs"), mod("httpkit"), mod("constants")


async def finished_run(tmp_path, mgr):
    run = make_run(tmp_path, mgr)
    await drive(run, mgr)
    assert run.s["status"] == "done"
    return run


def test_each_role_shows_its_task_reply_and_delivered_files(tmp_path):
    async def go():
        mgr = FakeManager()
        run = await finished_run(tmp_path, mgr)
        pm = await outputs.role_output(run, "pm", mgr=mgr, scrub=str)
        assert pm["title"] == "产品经理" and pm["branch"] == "team/r1006test/pm" and pm["base"] and pm["head"]
        assert pm["files"] == [{"path": "docs/product/acceptance.md", "added": 2, "removed": 0, "status": "A",
                                "output": True, "owner": "pm"}]
        [att] = pm["attempts"]
        assert att["reply"].endswith("DONE: 做完了") and att["summary"] == "做完了" and not att["live"]
        assert att["task"].startswith("[vstatd-team run=r1006test role=pm ") and att["calls"] == []

        designer = await outputs.role_output(run, "designer", mgr=mgr, scrub=str)
        assert {f["path"]: f["output"] for f in designer["files"]} == {"docs/design/pages.md": True, "frontend/styles/main.css": True}

        reviewer = await outputs.role_output(run, "reviewer", mgr=mgr, scrub=str)
        assert reviewer["files"] == [] and reviewer["attempts"][0]["reply"].endswith("DONE: 可以交付")

        product = await outputs.role_output(run, "run", mgr=mgr, scrub=str)
        owners = {f["path"]: f["owner"] for f in product["files"]}
        assert owners["backend/server.js"] == "backend" and owners["tests/api-signup.test.js"] == "tester"
        assert owners["frontend/styles/main.css"] == "designer" and product["title"] == "整个产品" and product["ended"]
        assert set(owners) == {p for files in OUTPUTS.values() for p in files}

        view = await outputs.file_view(run, "pm", "docs/product/acceptance.md", "content")
        assert (view["text"], view["lang"], view["binary"]) == (OUTPUTS["pm"]["docs/product/acceptance.md"], "markdown", False)
        diff = await outputs.file_view(run, "backend", "backend/server.js", "diff")
        assert diff["lang"] == "diff" and "+// v2" in diff["text"]
        whole = await outputs.file_view(run, "run", "./Dockerfile", "content")
        assert whole["text"] == "FROM node:22\n" and whole["path"] == "Dockerfile" and whole["lang"] == "dockerfile"

        for bad in ("../x", "/etc/passwd", "a/../b", "a//b", "", 5, "x\ny"):
            with pytest.raises(httpkit.AppError) as e:
                await outputs.file_view(run, "pm", bad, "content")
            assert e.value.code == "invalid_path"
        with pytest.raises(httpkit.AppError) as e:
            await outputs.file_view(run, "pm", "docs/nope.md", "content")
        assert e.value.status == 404
        with pytest.raises(httpkit.AppError) as e:
            await outputs.role_output(run, "nobody", mgr=mgr, scrub=str)
        assert e.value.status == 404

    asyncio.run(go())


def test_older_runs_get_their_replies_filled_in_once(tmp_path):
    async def go():
        mgr = FakeManager()
        run = await finished_run(tmp_path, mgr)
        for att in run.lane("pm")["attempts"]:  # as a run from before replies and calls were kept
            att.pop("reply"), att.pop("calls")
        mgr.agents[run.lane("pm")["attempts"][0]["agent"]].result = "DONE: 写好了验收标准\n\n- AC-1 首页"
        pm = await outputs.role_output(run, "pm", mgr=mgr, scrub=lambda s: s.replace("AC-1", "AC-一"))
        att = pm["attempts"][0]
        assert att["reply"] == "DONE: 写好了验收标准\n\n- AC-一 首页" and att["calls"] == []
        mgr.agents[run.lane("pm")["attempts"][0]["agent"]].result = "换了"
        await outputs.role_output(run, "pm", mgr=mgr, scrub=str)
        assert run.lane("pm")["attempts"][0]["reply"].startswith("DONE: 写好了")  # kept, on disk too

    asyncio.run(go())


def test_output_routes(tmp_path):
    mgr = FakeManager()
    svc, routes = make(tmp_path, mgr, tick_s=60)

    async def go():
        await svc.start()
        try:
            rid = (await call(routes, "POST", "/runs", json_body={})).body["run"]
            r = await call(routes, "GET", f"/runs/{rid}/roles/pm")
            assert r.status == 200 and r.body["attempts"][0]["live"] is True and r.body["files"] == []
            r = await call(routes, "GET", f"/runs/{rid}/roles/pm/file?path=../x")
            assert (r.status, r.code) == (400, "invalid_path")
            r = await call(routes, "GET", f"/runs/{rid}/roles/ghost")
            assert r.status == 404
            for method, path in (("GET", f"/runs/{rid}/roles/pm"), ("GET", f"/runs/{rid}/roles/pm/file")):
                assert (await call(routes, method, path, user=None)).status == 401, path
        finally:
            await svc.stop()

    asyncio.run(go())


def test_the_outputs_contract_matches_types_ts(tmp_path):
    from teamkit import ts_types

    objects, _ = ts_types()

    async def go():
        mgr = FakeManager()
        run = await finished_run(tmp_path, mgr)
        out = await outputs.role_output(run, "pm", mgr=mgr, scrub=str)
        assert set(out) == objects["RoleOutput"]
        assert set(out["files"][0]) == objects["OutputFile"] and set(out["attempts"][0]) == objects["OutputAttempt"]
        view = await outputs.file_view(run, "pm", "docs/product/acceptance.md", "content")
        assert set(view) == objects["FileView"]

    asyncio.run(go())



def test_open_folder_opens_only_the_runs_own_folders(tmp_path):
    opened = []

    async def opener(cmd):
        opened.append(cmd)
        return 0

    mgr = FakeManager()
    svc, routes = make(tmp_path, mgr, tick_s=60, opener=opener)

    async def go():
        await svc.start()
        try:
            rid = (await call(routes, "POST", f"/runs", json_body={})).body["run"]
            run_wt = svc.runs[rid].s["run_wt"]
            r = await call(routes, "POST", f"/runs/{rid}/open", json_body={})
            assert r.status == 200 and r.body == {"ok": True, "path": mod("display").View().text(run_wt), "app": "finder"}
            r = await call(routes, "POST", f"/runs/{rid}/open", json_body={"role": "pm", "app": "kiro"})
            assert r.status == 200 and r.body["path"].endswith("/wt/pm")
            # the reply shows the folder with ~ (display.py); the folder opened is the real one
            assert opened == [["/usr/bin/open", run_wt], ["/usr/bin/open", "-a", "Kiro", os.path.expanduser(r.body["path"])]]
            r = await call(routes, "POST", f"/runs/{rid}/open", json_body={"role": "backend"})  # not started: no worktree
            assert (r.status, r.code) == (404, "no_folder")
            r = await call(routes, "POST", f"/runs/{rid}/open", json_body={"app": "terminal"})
            assert (r.status, r.code) == (400, "invalid_app")
            r = await call(routes, "POST", f"/runs/{rid}/open", json_body={"role": "../../etc"})
            assert r.status == 404 and len(opened) == 2
            out = await call(routes, "GET", f"/runs/{rid}/roles/pm")
            assert out.body["folder"].endswith("/wt/pm")
        finally:
            await svc.stop()

    asyncio.run(go())
