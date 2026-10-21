"""The sequencer against a fake SubagentManager, real git in a temp dir and a fake test runner."""

import asyncio
from pathlib import Path

import json

from teamkit import (FIXTURE, FakeManager, act, default_tests, drive, finish, make_run, mini_team, mod, read, reload,
                     richest, same_shape, sh, team_mod, ts_types)

TAG = "[aidlc-team run=r1006test role="


def kinds(run, kind):
    return [e for e in run.events if e["kind"] == kind]


def status(run):
    return {k: run.lane(k)["status"] for k in run.order}


def check_board(run, mgr):
    """The board of a real run is shaped like the UI fixture, with values from the TS unions."""
    out = json.loads(json.dumps(mod("board").build({run.rid: run}, None, mgr=mgr, scrub=str, now=1.0)))
    ref = json.loads(FIXTURE.read_text(encoding="utf-8"))
    same_shape({k: v for k, v in out["run"].items() if k != "roles"}, {k: v for k, v in ref["run"].items() if k != "roles"})
    for lane in out["run"]["roles"]:
        same_shape(lane, richest(ref["run"]["roles"]), f"lane {lane['key']}")
    _, unions = ts_types()
    assert out["run"]["status"] in unions["RunStatus"] and {e["kind"] for e in out["run"]["events"]} <= unions["TeamEventKind"]
    assert {ln["status"] for ln in out["run"]["roles"]} <= unions["LaneStatus"]
    return out


def test_full_run_parallel_stages_merges_bounce_conflict_and_review(tmp_path):
    async def go():
        mgr, tests = FakeManager(), default_tests()
        run = make_run(tmp_path, mgr, tests, requirement="活动报名小站\n\n1. 首页列出所有活动。")
        await run.tick()
        assert run.s["status"] == "running" and run.s["base"]
        repo = Path(run.s["repo"])
        assert "1. 首页列出所有活动。" in read(repo, "README.md")
        assert sh(repo, "log", "-1", "--format=%s").strip() == "需求：活动报名小站"
        [(pm_id, pm_task, kw)] = mgr.spawned
        assert pm_task.startswith(TAG + "pm branch=team/r1006test/pm worktree=")
        assert kw["cwd"].endswith("/wt/pm") and kw["parent_session_key"] == "aidlc-team:r1006test"
        assert kw["model"] == "claude-opus-5.5" and kw["folder"].endswith(" · r1006test") and kw["title"].endswith(" agent")
        assert "docs/product/**" in pm_task and "把 README 里的需求" in pm_task

        act(mgr.get(pm_id), {"docs/product/acceptance.md": "AC-1\nAC-6\n"})
        finish(mgr.get(pm_id), "2 条验收标准")
        await run.tick()  # pm merged; architect and designer start together
        assert [mgr.role_of(a) for a in mgr.live()] == ["architect", "designer"]
        assert [(e["from"], e["to"]) for e in kinds(run, "handoff")] == [("pm", "architect"), ("pm", "designer")]
        assert run.lane("pm")["status"] == "merged" and run.lane("pm")["summary"] == "2 条验收标准"
        assert "docs/product/acceptance.md" in mgr.by_role("architect").task  # upstream outputs are its inputs

        act(mgr.by_role("architect"), {"contracts/api.md": "# API\n"})
        finish(mgr.by_role("architect"))
        act(mgr.by_role("designer"), {"docs/design/pages.md": "# 页面\n", "frontend/styles/main.css": "a{}\n"}, commit=False)
        await run.tick()  # architect merged: tester and ops start; designer still works
        assert sorted(mgr.role_of(a) for a in mgr.live()) == ["designer", "ops", "tester"]
        assert run.lane("designer")["lines"]["added"] == 2  # uncommitted work shows up live

        finish(mgr.by_role("designer"))
        await run.tick()
        assert run.lane("designer")["status"] == "merged"
        assert any("app 替UI 设计提交了 2 个文件" in e["text"] for e in kinds(run, "committed"))
        assert tests.calls == 0  # nothing to test yet

        act(mgr.by_role("tester"), {"tests/api-signup.test.js": "//\n", "tests/web-render.test.js": "//\n"})
        finish(mgr.by_role("tester"), "2 个测试，全红")
        await run.tick()  # tester merged: backend and frontend start, ops still works; the app tests the run branch
        assert sorted(mgr.role_of(a) for a in mgr.live()) == ["backend", "frontend", "ops"]
        assert tests.calls == 1 and kinds(run, "tests")[-1]["text"] == "测试 0/2：实现还没写，全红"
        assert not kinds(run, "bounce")

        backend1, frontend1 = mgr.by_role("backend"), mgr.by_role("frontend")
        act(backend1, {"backend/server.js": "// v1\n"})
        finish(backend1)
        act(frontend1, {"frontend/index.html": "<h1/>\n", "backend/server.js": "// 前端顺手改的\n"})
        act(mgr.by_role("ops"), {"ops/start.sh": "x\n", "Dockerfile": "FROM node\n"})
        finish(mgr.by_role("ops"))
        await run.tick()  # backend and ops merged, AC-6 red; nobody is sent back while the frontend is not in
        assert run.lane("ops")["status"] == "merged" and run.lane("backend")["status"] == "merged"
        assert tests.calls == 2 and run.s["tests"]["failed"] == 2 and not kinds(run, "bounce")
        assert [e["text"] for e in kinds(run, "violation")] == ["前端改了不属于它的 backend/server.js"]  # seen live
        lanes = {ln["key"]: ln for ln in check_board(run, mgr)["run"]["roles"]}
        assert lanes["frontend"]["violations"] == ["backend/server.js"] and lanes["frontend"]["files"]

        finish(frontend1)
        await run.tick()  # frontend conflicts on backend/server.js: aborted, recorded, sent back
        assert [m["status"] for m in run.s["merges"] if m["role"] == "frontend"] == ["conflict"]
        assert run.s["merges"][-1]["note"] == "backend/server.js"
        assert kinds(run, "conflict")[0]["text"] == "前端合入冲突：backend/server.js"
        [bounce] = kinds(run, "bounce")
        assert (bounce["from"], bounce["to"]) == ("run", "frontend")
        assert run.lane("frontend")["violations"] == ["backend/server.js"] and len(kinds(run, "violation")) == 1
        assert not sh(run.s["run_wt"], "status", "--porcelain")  # the merge was aborted cleanly
        [(conv, frontend2_id, conflict_task, ckw)] = mgr.continued
        assert conv == frontend1.id and ckw["cwd"] == frontend1.cwd
        assert "冲突的文件：backend/server.js" in conflict_task and "git rm" in conflict_task
        assert tests.calls == 2 and run.s["status"] == "fixing"

        act(mgr.get(frontend2_id), {"backend/server.js": None}, msg="[frontend] 不改后端的文件")
        finish(mgr.get(frontend2_id))
        await run.tick()  # frontend merged, every implementation is in: AC-6 goes back into the backend's conversation
        assert run.lane("frontend")["status"] == "merged" and run.s["tests"]["failed"] == 1
        bounce = kinds(run, "bounce")[-1]
        assert (bounce["from"], bounce["to"], bounce["text"]) == ("tests", "backend", "AC-6 失败，打回后端")
        assert bounce["data"] == {"cases": ["AC-6"]}
        assert run.lane("backend")["status"] == "fixing" and run.lane("backend")["attempt"] == 2
        conv, backend2_id, fix_task, ckw = mgr.continued[-1]
        assert conv == backend1.id and ckw["cwd"] == backend1.cwd
        assert fix_task.startswith(TAG + "backend ") and fix_task.split("\n", 1)[0].endswith(" attempt=2]")
        assert "AC-6: 用例（tests/api-signup.test.js）：expected 409, got 201" in fix_task
        assert "快进到运行分支的最新提交" in fix_task  # its branch caught up: the tests and the frontend are in its worktree
        assert read(Path(backend1.cwd), "frontend/index.html") and read(Path(backend1.cwd), "tests/api-signup.test.js")
        lanes = {ln["key"]: ln for ln in check_board(run, mgr)["run"]["roles"]}
        assert lanes["backend"]["status"] == "fixing" and lanes["backend"]["agent"]["id"] == backend2_id

        backend2 = mgr.get(backend2_id)
        act(backend2, {"backend/server.js": "// v2\n"})
        finish(backend2, "名额判断改成 >=")
        await run.tick()  # backend merged, all green; the reviewer waits for the next tick
        assert kinds(run, "tests")[-1]["text"] == "测试 2/2：全绿"
        assert run.lane("reviewer")["status"] == "waiting"
        await run.tick()
        reviewer = mgr.by_role("reviewer")
        # a snapshot of the run branch of its own: merges going on meanwhile do not change what it reads
        assert reviewer.cwd.endswith("/wt/reviewer") and "你是只读的" in reviewer.task and "git add" not in reviewer.task
        assert sh(Path(reviewer.cwd), "rev-parse", "HEAD") == sh(Path(run.s["run_wt"]), "rev-parse", "HEAD")
        assert run.s["status"] == "reviewing"
        finish(reviewer, "可以交付")
        await run.tick()
        assert run.s["status"] == "done" and run.ended
        assert kinds(run, "review")[0]["text"] == "审查：可以交付"
        assert kinds(run, "run")[-1]["text"] == "运行完成：审查说可以交付"
        assert [m["role"] + ":" + m["status"] for m in run.s["merges"]] == [
            "pm:merged", "architect:merged", "designer:merged", "tester:merged", "backend:merged", "ops:merged",
            "frontend:conflict", "frontend:merged", "backend:merged"]
        assert set(status(run).values()) == {"merged", "done"}
        assert [e["seq"] for e in run.events] == list(range(1, len(run.events) + 1))
        end = check_board(run, mgr)["run"]
        assert [h["passed"] for h in end["tests"]["history"]] == [0, 0, 1, 2]  # no test run when a merge conflicted
        assert end["merges"][6]["status"] == "conflict" and end["roles"][-1]["agent"]["id"] == reviewer.id
        assert read(Path(run.s["run_wt"]), "backend/server.js") == "// v2\n"
        lane = run.lane("backend")
        assert [a["kind"] for a in lane["attempts"]] == ["work", "fix"] and lane["summary"] == "名额判断改成 >="
        assert {c["subject"] for c in lane["commits"]} == {"[agent] work"} and len(lane["commits"]) == 2
        assert lane["files"] == [{"path": "backend/server.js", "added": 2, "removed": 1, "status": "A"}]  # both rounds
        assert lane["violations"] == [] and lane["lines"] == {"added": 2, "removed": 1}

    asyncio.run(go())


def test_restart_mid_run_then_the_reviewer_saying_needs_changes_fails_the_run(tmp_path):
    async def go():
        mgr, tests = FakeManager(), default_tests()
        run = make_run(tmp_path, mgr, tests, team=mini_team())
        await run.tick()
        act(mgr.by_role("pm"), {"docs/product/x.md": "x\n"})
        finish(mgr.by_role("pm"))
        await run.tick()
        assert sorted(mgr.role_of(a) for a in mgr.live()) == ["backend", "frontend"]
        spawned = len(mgr.spawned)
        again = reload(tmp_path, mgr, tests)  # a fresh TeamRun from run.json, as after an app restart
        assert again.events[-1]["seq"] == run.events[-1]["seq"]
        await again.tick()
        assert len(mgr.spawned) == spawned and status(again)["backend"] == "running"  # found again by id
        act(mgr.by_role("backend"), {"backend/server.js": "// v2\n"})
        finish(mgr.by_role("backend"))
        await again.tick()
        assert again.lane("backend")["status"] == "merged" and again.s["tests"]["passed"] == 1
        assert again.events[-1]["seq"] > run.events[-1]["seq"]

        def behave(a, role):
            if role == "reviewer":
                finish(a, "要改：后端没校验邮箱（后端）")
            else:
                act(a, {"frontend/index.html": "<h1/>\n"})
                finish(a)

        await drive(again, mgr, behave)
        assert again.s["status"] == "failed" and again.lane("reviewer")["status"] == "done"
        assert again.lane("reviewer")["summary"] == "要改：后端没校验邮箱（后端）"
        assert kinds(again, "run")[-1]["text"] == "运行结束：评审要改"

    asyncio.run(go())


def test_a_spawn_whose_id_was_never_saved_is_adopted_not_started_twice(tmp_path):
    async def go():
        mgr = FakeManager()
        run = make_run(tmp_path, mgr)
        await run.tick()
        [(pm_id, _, _)] = mgr.spawned
        run.lane("pm")["attempts"][-1]["agent"] = None  # as if the app stopped between the spawn and the save
        await run.save()
        again = reload(tmp_path, mgr, default_tests())
        await again.tick()
        assert len(mgr.spawned) == 1 and again.lane("pm")["attempts"][-1]["agent"] == pm_id
        assert again.lane("pm")["status"] == "running"

    asyncio.run(go())


def test_stop_cancels_every_live_agent(tmp_path):
    async def go():
        mgr = FakeManager()
        run = make_run(tmp_path, mgr)
        await run.tick()
        finish(mgr.by_role("pm"))
        await run.tick()
        live = sorted(a.id for a in mgr.live())
        assert len(live) == 2
        assert await run.stop() is True
        assert sorted(mgr.cancelled) == live and not mgr.live()
        assert run.s["status"] == "stopped" and run.s["ended_at"]
        assert status(run)["architect"] == "failed" and status(run)["tester"] == "waiting"
        assert run.events[-1]["text"] == "运行已停止"
        n = len(mgr.spawned)
        await run.tick()
        assert len(mgr.spawned) == n and await run.stop() is False
        assert reload(tmp_path, mgr, default_tests()).s["status"] == "stopped"

    asyncio.run(go())


def test_fix_rounds_run_out_in_fresh_agents_when_continuing_is_impossible(tmp_path):
    async def go():
        mgr = FakeManager()
        mgr.gone = True  # every continuation answers conversation_gone: a fresh agent, same worktree
        run = make_run(tmp_path, mgr, team=mini_team())
        heads = []

        def behave(a, role):
            if role == "backend":
                heads.append((a.cwd, a.task.split("\n", 1)[0]))
                act(a, {"backend/server.js": f"// v1 {a.id}\n"})  # never fixes AC-6
            elif role == "frontend":
                act(a, {"frontend/index.html": "<h1/>\n"})
            finish(a, "可以交付" if role == "reviewer" else "做了")

        await drive(run, mgr, behave)
        lane = run.lane("backend")
        assert lane["attempt"] == 3 and [a["kind"] for a in lane["attempts"]] == ["work", "fix", "fix"]
        assert len({cwd for cwd, _ in heads}) == 1 and [h.endswith("attempt=3]") for _, h in heads] == [False, False, True]
        assert [a["conv"] for a in lane["attempts"]] == [a["agent"] for a in lane["attempts"]]  # each one fresh
        assert len([e for e in kinds(run, "bounce") if e["to"] == "backend"]) == 2
        assert run.s["tests"]["failed"] == 1 and run.lane("reviewer")["status"] == "done"
        assert run.s["status"] == "done"

    asyncio.run(go())


def test_tests_that_cannot_run_stop_the_run_instead_of_bouncing(tmp_path):
    async def go():
        async def no_node(wt, team):
            raise mod("checks").TestsUnavailable("跑不了 node（/nope）：No such file")

        mgr = FakeManager()
        run = make_run(tmp_path, mgr, no_node, team=mini_team())
        await run.tick()
        finish(mgr.by_role("pm"))
        await run.tick()
        act(mgr.by_role("backend"), {"backend/server.js": "//\n"})
        finish(mgr.by_role("backend"))
        await run.tick()
        assert run.s["status"] == "failed" and kinds(run, "run")[-1]["text"].startswith("运行失败：app 跑不了测试")
        assert not mgr.live() and not kinds(run, "bounce") and mgr.cancelled == [mgr.by_role("frontend").id]

    asyncio.run(go())


def test_refused_spawn_fails_the_lane_and_the_stuck_run(tmp_path):
    async def go():
        mgr = FakeManager()
        mgr.refuse = "spawn refused: cwd is not under any allowed root"
        run = make_run(tmp_path, mgr)
        await run.tick()
        assert run.lane("pm")["status"] == "failed" and run.s["status"] == "failed"
        assert "cwd is not under any allowed root" in kinds(run, "failed")[0]["text"]
        assert kinds(run, "run")[-1]["text"].startswith("运行失败：产品经理没做完")

    asyncio.run(go())


def test_a_lost_agent_fails_after_the_grace(tmp_path):
    async def go():
        clock = [1_000_000.0]
        mgr = FakeManager()
        run = make_run(tmp_path, mgr, now=lambda: clock[0])
        await run.tick()
        att = run.lane("pm")["attempts"][-1]
        assert att["agent"] and run.lane("pm")["status"] == "running"
        del mgr.agents[att["agent"]]
        await run.tick()
        assert run.lane("pm")["status"] == "running"
        clock[0] += team_mod.LOST_GRACE_S + 1
        await run.tick()
        assert run.lane("pm")["status"] == "failed" and run.s["status"] == "failed"

    asyncio.run(go())


def test_live_status_follows_kirocrew_and_tool_events_are_throttled(tmp_path):
    async def go():
        clock = [2_000_000.0]
        mgr = FakeManager()
        run = make_run(tmp_path, mgr, now=lambda: clock[0])
        await run.tick()
        pm = mgr.by_role("pm")
        pm.queued, pm.queued_reason = True, "concurrency_limit"
        await run.tick()
        assert run.lane("pm")["status"] == "queued"
        pm.queued, pm._awaiting_approval = False, True
        await run.tick()
        assert run.lane("pm")["status"] == "awaiting_approval"
        pm._awaiting_approval, pm.stalled = False, True
        await run.tick()
        assert run.lane("pm")["status"] == "stalled"
        pm.stalled, pm.last_tool = False, "Editing docs/product/acceptance.md"
        await run.tick()
        pm.last_tool = "Running: ls"
        clock[0] += 1
        await run.tick()  # within 3 s of the last tool event: not repeated
        clock[0] += 3
        await run.tick()
        assert [e["text"] for e in kinds(run, "tool")] == ["产品经理：Editing docs/product/acceptance.md", "产品经理：Running: ls"]
        assert run.lane("pm")["status"] == "running"

    asyncio.run(go())


def test_parse_done_and_title():
    assert team_mod.parse_done("想了想\n**DONE: 可以交付**\n") == "可以交付"
    assert team_mod.parse_done("DONE: 第一\n...\nDONE：第二") == "第二"
    assert team_mod.parse_done("没有总结") is None
    assert team_mod.title_of("\n# 读书会报名\n更多", Path("/nonexistent")) == "读书会报名"



def test_a_fix_round_that_changes_nothing_is_not_merged_or_sent_back_again(tmp_path):
    async def go():
        mgr = FakeManager()
        run = make_run(tmp_path, mgr, team=mini_team())

        def behave(a, role):
            if role == "backend":
                if " attempt=" in a.task.split("\n", 1)[0]:
                    finish(a, "AC-6 要改的文件不归我")  # changes nothing
                    return
                act(a, {"backend/server.js": "// v1\n"})
            elif role == "frontend":
                act(a, {"frontend/index.html": "<h1/>\n"})
            finish(a, "要改：AC-6 没过" if role == "reviewer" else "做了")

        await drive(run, mgr, behave)
        lane = run.lane("backend")
        assert [a["kind"] for a in lane["attempts"]] == ["work", "fix"] and lane["stuck"] is True
        assert [m["role"] for m in run.s["merges"]].count("backend") == 1
        assert len([e for e in kinds(run, "bounce") if e["to"] == "backend"]) == 1
        assert "后端第 2 轮没有改动：AC-6 要改的文件不归我" in [e["text"] for e in kinds(run, "failed")]
        assert run.lane("reviewer")["status"] == "done" and run.s["status"] == "failed"  # the reviewer said 要改

    asyncio.run(go())


def test_a_reply_without_done_still_gets_a_summary():
    assert team_mod.gist("## 结果\n\n**后端做完了**：接口都通了\n- 细节") == "后端做完了：接口都通了"
    assert team_mod.gist("```\n|a|b|\n```\n") is None and team_mod.gist("") is None
    assert team_mod.gist("x" * 130).endswith("…")


def test_the_team_routes_project_checks_to_ops_and_the_demo_test_script_takes_a_glob():
    constants, checks, gitwork = mod("constants"), mod("checks"), mod("gitwork")
    team = team_mod.load_team(constants.TEAM_FILE)
    assert checks.owner_of("tests/ops-scripts.test.js", team) == "ops"
    assert checks.owner_of("tests/api-signup.test.js", team) == "backend"
    ops = next(r for r in team["roles"] if r["key"] == "ops")
    assert gitwork.matches("package.json", ops["writable"])
    pkg = json.loads((constants.TARGET_TEMPLATE / "package.json").read_text(encoding="utf-8"))
    assert "tests/**/*.test.js" in pkg["scripts"]["test"]  # node 22+ does not take a directory there


def qa_team() -> dict:
    """pm → tester ∥ backend → reviewer: the tester writes tests/api-*, the backend makes them pass."""
    role = lambda key, title, deps, writable: {"key": key, "title": title, "emoji": "", "depends_on": deps,  # noqa: E731
                                               "writable": writable, "outputs": [], "brief": f"{title}的活"}
    return team_mod.check_team({
        "version": 1, "test_command": ["node", "--test", "tests/"],
        "roles": [role("pm", "产品经理", [], ["docs/product/**"]), role("tester", "测试", ["pm"], ["tests/api-*"]),
                  role("backend", "后端", ["pm"], ["backend/**"]), role("reviewer", "评审", ["tester", "backend"], [])],
        "defaults": {"model": "claude-opus-5.5", "effort": "high", "max_fix_rounds": 2},
        "test_owners": [{"glob": "tests/api-*", "role": "backend"}],
    })


def test_a_test_the_implementer_says_is_wrong_goes_back_to_its_author_and_the_end_says_how_green_it_is(tmp_path):
    from teamkit import FakeTests

    # AC-10 passes once the tester stops sharing state between cases (its file says "fresh")
    tests = FakeTests([("api-orders.test.js#AC-10", "backend", lambda wt: "fresh" in read(wt, "tests/api-orders.test.js"))])

    async def go():
        mgr = FakeManager()
        run = make_run(tmp_path, mgr, tests, team=qa_team())
        seen = []

        def behave(a, role):
            head = a.task.split("\n", 1)[0]
            if role == "backend":
                if " attempt=" in head:
                    finish(a, "没有改动：AC-10 失败是测试自身的问题，用例共用了一个服务")
                    return
                act(a, {"backend/server.js": "// v1\n"})
            elif role == "tester":
                if " attempt=" in head:
                    seen.append(a.task)
                    act(a, {"tests/api-orders.test.js": "// AC-10 fresh server per case\n"})
                else:
                    act(a, {"tests/api-orders.test.js": "// AC-10 shared server\n"})
            elif role == "pm":
                act(a, {"docs/product/acceptance.md": "AC-10\n"})
            finish(a, "可以交付" if role == "reviewer" else "做了")

        await drive(run, mgr, behave)
        bounces = [e["text"] for e in kinds(run, "bounce")]
        assert any("说测试本身有问题，打回测试" in t for t in bounces), bounces
        assert seen and "这些测试是你写的" in seen[0] and "测试自身的问题，用例共用了一个服务" in seen[0]
        assert run.s["tests"]["failed"] == 0 and run.s["status"] == "done"
        assert kinds(run, "run")[-1]["text"] == "运行完成：审查说可以交付"

    asyncio.run(go())


def test_a_run_that_ends_red_says_so(tmp_path):
    from teamkit import FakeTests

    tests = FakeTests([("api-orders.test.js#AC-10", "backend", lambda wt: False)])  # nobody can turn it green

    async def go():
        mgr = FakeManager()
        run = make_run(tmp_path, mgr, tests, team=qa_team())

        def behave(a, role):
            if role in ("backend", "tester"):
                act(a, {"backend/server.js" if role == "backend" else "tests/api-orders.test.js": f"// {a.id}\n"})
            elif role == "pm":
                act(a, {"docs/product/acceptance.md": "AC-10\n"})
            finish(a, "可以交付" if role == "reviewer" else "做了")

        await drive(run, mgr, behave, ticks=80)
        assert run.s["status"] == "done"
        assert kinds(run, "run")[-1]["text"] == "运行结束：审查说可以交付，但测试还有 1 项没过，交给人决定"
        reviewer_task = run.lane("reviewer")["attempts"][-1]["task"]
        assert "app 刚跑的测试：0/1 通过，没过的：AC-10: 用例" in reviewer_task

    asyncio.run(go())


def deploy_team() -> dict:
    """pm → backend → reviewer → deploy: the deployment comes after the review lets the work through."""
    role = lambda key, title, deps, writable, **kw: {"key": key, "title": title, "emoji": "", "depends_on": deps,  # noqa: E731
                                                     "writable": writable, "outputs": [], "brief": f"{title}的活", **kw}
    return team_mod.check_team({
        "version": 1, "test_command": ["node", "--test", "tests/"],
        "roles": [role("pm", "产品经理", [], ["docs/product/**"]), role("backend", "后端", ["pm"], ["backend/**"]),
                  role("reviewer", "评审", ["backend"], []),
                  role("deploy", "部署", ["reviewer"], ["deploy/**"], deploy={"mode": "local", "port": 8080})],
        "defaults": {"model": "claude-opus-5.5", "effort": "high", "max_fix_rounds": 2},
        "test_owners": [{"glob": "tests/api-*", "role": "backend"}],
    })


def test_the_deploy_role_runs_after_the_review_and_the_app_deploys_what_it_configured(tmp_path):
    from teamkit import FakeTests, make_deps

    tests = FakeTests([("api-x.test.js#AC-1", "backend", lambda wt: "v1" in read(wt, "backend/server.js"))])
    calls = []

    async def go():
        mgr = FakeManager()
        run = make_run(tmp_path, mgr, tests, team=deploy_team())

        async def deploy(rid, wt, spec):
            calls.append((rid, read(wt, "deploy/local.json"), spec["port"]))
            if len(calls) == 1:
                return {"ok": False, "error": "健康检查 GET /api/products 返回 404，不是 200"}
            return {"ok": True, "url": "http://127.0.0.1:8080/", "note": ""}

        run.d.deploy = deploy
        order = []

        def behave(a, role):
            order.append(role)
            if role == "backend":
                act(a, {"backend/server.js": "// v1\n"})
            elif role == "pm":
                act(a, {"docs/product/acceptance.md": "AC-1\n"})
            elif role == "deploy":
                act(a, {"deploy/local.json": '{"port": 8080, "health": "/api/products"}\n' if " attempt=" in a.task.split("\n", 1)[0] else '{"port": 8080}\n'})
            finish(a, "可以交付" if role == "reviewer" else "做了")

        await drive(run, mgr, behave)
        assert order.index("reviewer") < order.index("deploy")  # the review first, and it did not end the run
        assert len(calls) == 2 and '"health"' in calls[1][1]  # the first deployment failed and went back to the role
        assert any("部署没成功，打回部署" in e["text"] for e in kinds(run, "bounce"))
        assert run.lane("deploy")["deployed"]["url"] == "http://127.0.0.1:8080/"
        assert [e["text"] for e in kinds(run, "deployed")] == ["部署到本机：http://127.0.0.1:8080/（编排器按部署写的配置起的服务，健康检查通过）"]
        assert run.s["status"] == "done" and kinds(run, "run")[-1]["text"] == "运行完成：审查说可以交付，已部署到本机 http://127.0.0.1:8080/"

    asyncio.run(go())


def test_nothing_red_is_deployed(tmp_path):
    from teamkit import FakeTests

    tests = FakeTests([("api-x.test.js#AC-1", "backend", lambda wt: False)])

    async def go():
        mgr = FakeManager()
        run = make_run(tmp_path, mgr, tests, team=deploy_team())
        run.d.deploy = lambda *a: (_ for _ in ()).throw(AssertionError("must not deploy"))

        def behave(a, role):
            if role == "backend":
                act(a, {"backend/server.js": f"// {a.id}\n"})
            elif role == "pm":
                act(a, {"docs/product/acceptance.md": "AC-1\n"})
            finish(a, "可以交付" if role == "reviewer" else "做了")

        await drive(run, mgr, behave, ticks=80)
        assert run.lane("deploy")["status"] == "waiting" and run.s["status"] == "done"
        assert kinds(run, "run")[-1]["text"] == "运行结束：审查说可以交付，但测试还有 1 项没过，没有部署，交给人决定"

    asyncio.run(go())


def test_a_person_signs_a_review_off_at_its_gate_and_can_send_work_back_to_a_named_member(tmp_path):
    from teamkit import FakeTests

    tests = FakeTests([("api-x.test.js#AC-1", "backend", lambda wt: "v1" in read(wt, "backend/server.js"))])
    team = deploy_team()
    reviewer = next(r for r in team["roles"] if r["key"] == "reviewer")
    reviewer.update(gate="human", gate_label="合规")

    async def go():
        mgr = FakeManager()
        run = make_run(tmp_path, mgr, tests, team=team)
        deployed = []

        async def deploy(rid, wt, spec):
            deployed.append(read(wt, "backend/server.js"))
            return {"ok": True, "url": "http://127.0.0.1:8080/", "note": ""}

        run.d.deploy = deploy
        tasks = []

        async def until(cond, ticks=40):
            for _ in range(ticks):
                await run.tick()
                if cond():
                    return
                for a in mgr.live():
                    role = mgr.role_of(a)
                    tasks.append((role, a.task))
                    if role == "backend":
                        act(a, {"backend/server.js": "// v1\n" if "负责人" not in a.task else "// v1\n// 仅限行政部使用\n"})
                    elif role == "pm":
                        act(a, {"docs/product/acceptance.md": "AC-1\n"})
                    elif role == "deploy":
                        act(a, {"deploy/local.json": '{"port": 8080, "health": "/"}\n'})
                    finish(a, "可以交付" if role == "reviewer" else "做了")
            raise AssertionError(run.s["status"])

        await until(lambda: run.lane("reviewer").get("gate") == "pending")
        assert run.lane("deploy")["status"] == "waiting" and not run.ended  # nothing goes out before the person signs
        assert not await run.gate("reviewer", "revise", "按风险提示退回。")  # 退回 has to name whom
        assert await run.gate("reviewer", "revise", "按风险提示 2 退回。\n打回：后端。加一行使用范围说明。")
        assert any(e["text"] == "按人的意见打回后端" for e in kinds(run, "bounce"))
        await until(lambda: run.lane("reviewer").get("gate") == "pending" and run.lane("reviewer")["attempt"] == 2)
        fix = next(t for r, t in tasks if r == "backend" and "负责人" in t)
        assert "加一行使用范围说明" in fix and "打回你（后端）" in fix
        again = [t for r, t in tasks if r == "reviewer"][-1]
        assert "负责人在关卡上退回" in again and "加一行使用范围说明" in again
        assert await run.gate("reviewer", "approve", "批准上线。导出名单只发给行政部。")
        await until(lambda: run.ended)
        assert deployed and "仅限行政部使用" in deployed[-1]  # what went out is what the person sent back for
        assert run.s["status"] == "done" and run.s["gate_notes"]["reviewer"] == "批准上线。导出名单只发给行政部。"

    asyncio.run(go())


def optional_team() -> dict:
    """pm (gated, writes the 分工提案) → backend ∥ motion (an optional post) → reviewer."""
    role = lambda key, title, deps, writable, **kw: {"key": key, "title": title, "emoji": "", "depends_on": deps,  # noqa: E731
                                                     "writable": writable, "outputs": [], "brief": f"{title}的活", **kw}
    return team_mod.check_team({
        "version": 1, "test_command": ["node", "--test", "tests/"],
        "roles": [role("pm", "产品经理", [], ["docs/product/**"], gate="human", gate_label="需求", plan="docs/product/plan.json",
                       member="aidlc-product-agent"),
                  role("backend", "后端", ["pm"], ["backend/**"], member="aidlc-developer-agent"),
                  role("motion", "动效", ["pm"], ["web/motion/**"], optional=True, member="taoyuan-motion-agent"),
                  role("reviewer", "评审", ["backend", "motion"], [])],
        "defaults": {"model": "claude-opus-5.5", "effort": "high", "max_fix_rounds": 2},
        "test_owners": [{"glob": "tests/api-*", "role": "backend"}, {"glob": "tests/ux-motion*", "role": "motion"}],
    })


def optional_tests():
    from teamkit import FakeTests
    return FakeTests([("api-x.test.js#AC-1", "backend", lambda wt: "v1" in read(wt, "backend/server.js")),
                      ("ux-motion.test.js#UX-1", "motion", lambda wt: "flip" in read(wt, "web/motion/motion.js"))])


async def until(run, mgr, behave, cond, ticks=40):
    """Tick until *cond*; every live agent does its role's work (*behave*) in between."""
    for _ in range(ticks):
        await run.tick()
        if cond():
            return
        for a in mgr.live():
            behave(a, mgr.role_of(a))
    raise AssertionError(run.s["status"])


def test_an_optional_member_not_on_crew_sits_the_run_out_and_its_checks_are_not_run(tmp_path):
    tasks = []

    def behave(a, role):
        tasks.append((role, a.task))
        if role == "pm":
            act(a, {"docs/product/plan.json": '{"backend": "接口", "motion": "倒计时翻页"}\n'})
        elif role == "backend":
            act(a, {"backend/server.js": "// v1\n"})
        finish(a, "可以交付" if role == "reviewer" else "做了")

    async def go():
        mgr = FakeManager()
        run = make_run(tmp_path, mgr, optional_tests(), team=optional_team())
        assert run.leave_out_unhired(None) == []  # Crew not read: everyone stays in
        assert run.leave_out_unhired({"aidlc-product-agent", "aidlc-developer-agent"}) == ["motion"]
        assert run.lane("motion")["status"] == "skipped" and run.lane("motion")["summary"] == "未入职"
        assert kinds(run, "skipped")[-1]["text"] == ("动效：Crew「代理」里还没有 taoyuan-motion-agent（未入职），这次不参与；"
                                                    "归它的检查（tests/ux-motion*）这次不跑")
        await until(run, mgr, behave, lambda: run.lane("pm").get("gate") == "pending")
        assert await run.gate("pm", "approve")
        await until(run, mgr, behave, lambda: run.ended)
        assert run.s["status"] == "done" and (run.s["tests"]["passed"], run.s["tests"]["total"]) == (1, 1)  # UX-1 not run
        assert "motion" not in {r for r, _ in tasks}
        backend = next(t for r, t in tasks if r == "backend")
        assert "这次不参加的成员：动效（未入职）。它们负责的部分保持模板原样" in backend
        assert run.lane("motion")["status"] == "skipped"
        out = check_board(run, mgr)
        assert next(ln for ln in out["run"]["roles"] if ln["key"] == "motion")["optional"] is True

    asyncio.run(go())


def test_the_planner_leaves_an_optional_member_out_and_it_sits_out_once_the_person_approves(tmp_path):
    tasks = []
    plan = '{"backend": "接口", "motion": "不用", "skip": {"motion": "这次只改价格，页面不动", "backend": "也不要"}}\n'

    def behave(a, role):
        tasks.append(role)
        if role == "pm":
            act(a, {"docs/product/plan.json": plan})
        elif role == "backend":
            act(a, {"backend/server.js": "// v1\n"})
        finish(a, "可以交付" if role == "reviewer" else "做了")

    async def go():
        mgr = FakeManager()
        run = make_run(tmp_path, mgr, optional_tests(), team=optional_team())
        assert run.leave_out_unhired({"aidlc-product-agent", "aidlc-developer-agent", "taoyuan-motion-agent"}) == []
        await until(run, mgr, behave, lambda: run.lane("pm").get("gate") == "pending")
        # a required member cannot be left out; the optional one is proposed, not yet out (the person has not approved)
        assert run.s["plan_skip"] == {"motion": "这次只改价格，页面不动"} and run.s["plan"] == {"backend": "接口"}
        assert kinds(run, "plan")[-1]["text"] == "产品经理提议分工：后端 · 接口；这次不要：动效（这次只改价格，页面不动）"
        assert run.lane("motion")["status"] == "waiting"
        assert await run.gate("pm", "approve", "就这样")
        assert run.lane("motion")["status"] == "skipped" and run.lane("motion")["summary"] == "这次用不到：这次只改价格，页面不动"
        assert kinds(run, "skipped")[-1]["text"] == ("动效：这次用不到（产品经理提议，人在需求关卡批准）：这次只改价格，页面不动；"
                                                    "归它的检查（tests/ux-motion*）这次不跑")
        await until(run, mgr, behave, lambda: run.ended)
        assert run.s["status"] == "done" and run.s["tests"]["total"] == 1 and "motion" not in tasks

    asyncio.run(go())


def test_a_gated_review_that_still_says_needs_changes_waits_for_the_person_who_sends_it_back_or_overrules_it(tmp_path):
    from teamkit import FakeTests

    tests = FakeTests([("api-x.test.js#AC-1", "backend", lambda wt: "v1" in read(wt, "backend/server.js"))])
    team = deploy_team()
    team["defaults"]["max_review_rounds"] = 1
    next(r for r in team["roles"] if r["key"] == "reviewer").update(gate="human", gate_label="上线")
    tasks = []

    def behave(a, role):
        tasks.append((role, a.task))
        if role == "backend":
            act(a, {"backend/server.js": f"// v1\n// {a.id}\n"})
        elif role == "pm":
            act(a, {"docs/product/acceptance.md": "AC-1\n"})
        elif role == "deploy":
            act(a, {"deploy/local.json": '{"port": 8080, "health": "/"}\n'})
        if role == "reviewer":
            finish(a, "要改：F-1 价保退差超过 30 万\n打回：后端")
        else:
            finish(a, "做了")

    async def go():
        mgr = FakeManager()
        run = make_run(tmp_path, mgr, tests, team=team)
        deployed = []

        async def deploy(rid, wt, spec):
            deployed.append(rid)
            return {"ok": True, "url": "http://127.0.0.1:8080/", "note": ""}

        run.d.deploy = deploy
        overruled = lambda: run.lane("reviewer").get("gate") == "pending" and run.lane("reviewer").get("overrule")  # noqa: E731
        await until(run, mgr, behave, overruled)
        # one round as the review said, then the rounds are used up: the person decides, the run does not end
        assert run.s["review_rounds"] == 1 and not run.ended and run.s["status"] == "gating"
        assert kinds(run, "gate")[-1]["text"] == "等人决定上线：审查打回 1 轮后仍要改，人可以再退回一轮，或写明理由推翻审查放行"
        assert run.lane("deploy")["status"] == "waiting" and run.sign_block() == "运行结束以后才能签字"
        assert not await run.gate("reviewer", "approve", "  ")  # overruling the review takes a reason
        assert await run.gate("reviewer", "revise", "价保按 28 万预留")  # names nobody: back to whom the review named
        assert kinds(run, "bounce")[-2]["text"] == "人在上线关卡退回：按审查意见再改一轮：价保按 28 万预留"
        assert run.s["review_rounds"] == 2 and run.s["review_note"] == "价保按 28 万预留"
        await until(run, mgr, behave, lambda: overruled() and run.lane("reviewer")["attempt"] == 3)
        fix = [t for r, t in tasks if r == "backend"][-1]
        assert "F-1 价保退差超过 30 万" in fix and "价保按 28 万预留" in fix
        assert await run.gate("reviewer", "approve", "风险我担：价保按 28 万预留，活动后财务复核")
        await until(run, mgr, behave, lambda: run.ended)
        assert deployed and run.s["status"] == "done" and run.sign_block() == ""
        assert run.s["overruled"] == {"role": "reviewer", "note": "风险我担：价保按 28 万预留，活动后财务复核",
                                      "review": "要改：F-1 价保退差超过 30 万"}
        assert kinds(run, "approved")[-1]["text"] == "人推翻审查结论，批准了上线：风险我担：价保按 28 万预留，活动后财务复核"
        assert kinds(run, "run")[-1]["text"] == "运行完成：人推翻了审查结论放行，已部署到本机 http://127.0.0.1:8080/"
        board = mod("board").detail(run, mgr=mgr, scrub=str, now=1.0)
        assert board["overruled"]["note"].startswith("风险我担") and board["sign_block"] == ""

    asyncio.run(go())


def test_only_a_run_that_delivered_can_be_signed_off(tmp_path):
    run = make_run(tmp_path, FakeManager(), team=deploy_team())
    assert run.sign_block() == "运行结束以后才能签字"
    run.s["status"] = "failed"
    assert run.sign_block() == "运行失败了，没有交付，不能签字放行（可以重试失败的角色）"
    run.s["status"] = "stopped"
    assert run.sign_block() == "运行停下了，没有交付，不能签字放行"
    run.s["status"], run.s["tests"]["failed"] = "done", 2
    assert run.sign_block() == "没有部署，不能签字放行（测试还有 2 项没过）"
    run.lane("deploy")["deployed"] = {"url": "http://127.0.0.1:8080/", "at": 1.0}
    assert run.sign_block() == ""
    without = make_run(tmp_path / "b", FakeManager(), team=mini_team())
    without.s["status"] = "done"
    assert without.sign_block() == ""  # a team that deploys nothing: done is delivered


def test_a_role_whose_crew_member_is_missing_waits_and_starts_once_it_is_added(tmp_path):
    """A role names a Crew member 「代理」 does not have: it is held with one event instead of silently booting the
    template of that name; adding the member lets it start on the next tick."""
    team = mini_team()
    team["workspace"] = "taoyuan"
    for r in team["roles"]:
        r["member"] = "aidlc-product-agent" if r["key"] == "pm" else "aidlc-developer-agent"
    members: set[str] = {"aidlc-developer-agent"}
    mgr = FakeManager()
    run = make_run(tmp_path, mgr, team=team)
    run.d.members = lambda ws: set(members) if ws == "taoyuan" else None

    async def go():
        await run.tick()
        assert run.lane("pm")["status"] == "waiting" and run.lane("pm")["awaiting_member"] == "aidlc-product-agent"
        held = kinds(run, "member")
        assert len(held) == 1 and held[0]["text"] == "产品经理没开工：Crew「代理」里还没有成员 aidlc-product-agent，加上就自动开工"
        await run.tick()  # still missing: no second event
        assert len(kinds(run, "member")) == 1 and not mgr.spawned
        members.add("aidlc-product-agent")
        await run.tick()
        assert run.lane("pm")["status"] == "running" and not run.lane("pm").get("awaiting_member")
        assert kinds(run, "member")[-1]["text"] == "成员 aidlc-product-agent 加上了，产品经理开工"

    asyncio.run(go())


def test_members_not_read_or_an_optional_post_never_holds_a_role(tmp_path):
    """No member list yet (Crew not read): the role starts; an optional post is decided when the run is handed over."""
    team = mini_team()
    team["workspace"] = "taoyuan"
    team["roles"][0].update(member="aidlc-product-agent")
    mgr = FakeManager()
    run = make_run(tmp_path, mgr, team=team)
    run.d.members = lambda ws: None

    async def go():
        await run.tick()
        assert run.lane("pm")["status"] == "running" and not run.lane("pm").get("awaiting_member")

    asyncio.run(go())
    team = optional_team()
    run = make_run(tmp_path / "b", FakeManager(), optional_tests(), team=team)
    run.d.members = lambda ws: {"aidlc-product-agent", "aidlc-developer-agent"}
    assert run._member_missing("motion") is None and run._member_missing("pm") is None
