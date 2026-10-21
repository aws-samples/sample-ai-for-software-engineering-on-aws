"""The 产出 view (each role's task, reply, tool calls and files) and 打开网站 (the finished product on a local port)."""

import asyncio
import json
import os
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from http_fakes import call
from teamkit import OUTPUTS, FakeManager, drive, make_run, mod
from test_service import make

outputs, site_mod, httpkit, constants = mod("outputs"), mod("site"), mod("httpkit"), mod("constants")


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
        assert att["task"].startswith("[aidlc-team run=r1006test role=pm ") and att["calls"] == []

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


SERVER = textwrap.dedent("""
    import http from 'node:http'
    const port = Number(process.env.PORT)
    console.log('listening on', port, process.env.HOST)
    http.createServer((req, res) => { res.end('<h1>活动报名</h1>') }).listen(port, process.env.HOST)
""")


def site_dir(tmp_path, server=SERVER, start="node backend/server.js"):
    wt = tmp_path / "site"
    (wt / "backend").mkdir(parents=True)
    (wt / "backend" / "server.js").write_text(server, encoding="utf-8")
    (wt / "package.json").write_text('{"type": "module", "scripts": {"start": "%s"}}' % start, encoding="utf-8")
    return wt


def test_the_site_starts_on_a_free_port_answers_and_stops(tmp_path):
    async def go():
        wt = site_dir(tmp_path)
        site = site_mod.Site()
        st = await site.start("r1", wt)
        try:
            assert st["state"] == "running" and st["url"] == f"http://127.0.0.1:{st['port']}/" and st["entry"] == "backend/server.js"
            assert await site_mod.answers_http(st["port"])
            await asyncio.sleep(0.2)
            assert any("listening on" in ln and "127.0.0.1" in ln for ln in site.status("r1")["log"])
            assert site.status("other")["state"] == "off"
        finally:
            await site.stop()
        assert site.status("r1")["state"] == "off" and not await site_mod.answers_http(st["port"])

    asyncio.run(go())


def test_a_site_that_listens_beyond_loopback_is_stopped(tmp_path, monkeypatch):
    """The board asks what the site listens on: all interfaces, or a network address, and it is stopped with why."""
    assert site_mod.beyond_loopback(["127.0.0.1:8090", "[::1]:8090", "*:8090", "192.168.1.5:8091"]) == ["*:8090", "192.168.1.5:8091"]
    assert site_mod.beyond_loopback(["127.0.0.1:8090", "localhost:8090"]) == []

    async def go():
        st = await site.start("r1", site_dir(tmp_path))
        assert st["state"] == "failed" and "*:4321" in st["error"] and not site.running

    monkeypatch.setattr(site_mod, "wide_listeners", lambda pgid: ["*:4321"])
    site = site_mod.Site()
    asyncio.run(go())


def test_a_site_on_loopback_passes_the_listen_check(tmp_path):
    async def go():
        site = site_mod.Site()
        st = await site.start("r1", site_dir(tmp_path))
        try:
            assert st["state"] == "running" and site_mod.wide_listeners(site.proc.pid) == []
        finally:
            await site.stop()

    asyncio.run(go())


def test_a_site_left_running_by_an_app_that_was_killed_is_stopped_so_the_next_deploy_gets_its_port(tmp_path):
    """An update kills the app, not its site (its own session): the next app stops that one, and only that one."""
    async def go():
        wt = site_dir(tmp_path)
        state = tmp_path / "data" / "site.json"
        old = site_mod.Site(state_file=state)
        st = await old.start("r1", wt)
        assert st["state"] == "running" and json.loads(state.read_text())["pid"] == old.proc.pid
        port, pid = st["port"], old.proc.pid
        old.proc = None  # the app is gone; its site is not
        new = site_mod.Site(state_file=state)
        try:
            again = await new.start("r1", wt, port=port)
            assert again["state"] == "running" and again["port"] == port and new.proc.pid != pid
            assert await site_mod._cwd_of(pid) is None
        finally:
            await new.stop()
        assert not state.exists()
        # a pid that is not that site (here: this test's own process) is left alone
        state.write_text(json.dumps({"pid": os.getpid(), "port": port, "run": "r1", "cwd": str(wt.resolve())}))
        other = site_mod.Site(state_file=state)
        try:
            assert (await other.start("r2", wt))["state"] == "running"
        finally:
            await other.stop()

    asyncio.run(go())


def test_a_site_that_cannot_start_says_why(tmp_path):
    async def go():
        wt = site_dir(tmp_path, server="console.error('Error: Cannot find module ./app.js'); process.exit(1)\n")
        site = site_mod.Site(ready_s=5)
        st = await site.start("r1", wt)
        assert st["state"] == "failed" and "Cannot find module" in st["error"] and not site.running
        assert site_mod.entry_of(site_dir(tmp_path / "b", start="node ../../evil.js")) == "backend/server.js"
        empty = tmp_path / "empty"
        empty.mkdir()
        assert site_mod.entry_of(empty) is None
        st = await site.start("r2", empty)
        assert st["state"] == "failed" and "找不到服务的入口" in st["error"]

    asyncio.run(go())


def test_output_and_site_routes(tmp_path):
    mgr = FakeManager()
    svc, routes = make(tmp_path, mgr, tick_s=60)

    async def go():
        await svc.start()
        try:
            rid = (await call(routes, "POST", "/runs", json_body={})).body["run"]
            r = await call(routes, "POST", f"/runs/{rid}/site")
            assert (r.status, r.code) == (409, "run_active")
            r = await call(routes, "GET", f"/runs/{rid}/roles/pm")
            assert r.status == 200 and r.body["attempts"][0]["live"] is True and r.body["files"] == []
            r = await call(routes, "GET", f"/runs/{rid}/roles/pm/file?path=../x")
            assert (r.status, r.code) == (400, "invalid_path")
            r = await call(routes, "GET", f"/runs/{rid}/roles/ghost")
            assert r.status == 404
            assert (await call(routes, "GET", f"/runs/{rid}/site")).body["state"] == "off"
            assert (await call(routes, "GET", "/runs/r1006zzzz/site")).status == 404
            for method, path in (("GET", f"/runs/{rid}/roles/pm"), ("GET", f"/runs/{rid}/roles/pm/file"),
                                 ("GET", f"/runs/{rid}/site"), ("POST", f"/runs/{rid}/site"), ("POST", f"/runs/{rid}/site/stop")):
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
        assert set(site_mod.Site().status("r1")) == objects["SiteStatus"]

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
            assert r.status == 200 and r.body == {"ok": True, "path": run_wt, "app": "finder"}
            r = await call(routes, "POST", f"/runs/{rid}/open", json_body={"role": "pm", "app": "kiro"})
            assert r.status == 200 and r.body["path"].endswith("/wt/pm")
            assert opened == [["/usr/bin/open", run_wt], ["/usr/bin/open", "-a", "Kiro", r.body["path"]]]
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
