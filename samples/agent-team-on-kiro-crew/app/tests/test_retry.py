"""重试: a start KiroCrew never ran is queued again by itself; a failed role is retried by the person, and an ended
run carries on from where it stopped."""

import asyncio

from http_fakes import call
from teamkit import OUTPUTS, FakeManager, act, drive, finish, make_run, mini_team, mod
from test_service import make

gitwork = mod("gitwork")
GAVE_UP = "agent stopped: nothing was done"
TAG = "[aidlc-team run=r1006test role="


def kinds(run, kind):
    return [e for e in run.events if e["kind"] == kind]


def gave_up(a):
    a.error, a.done = GAVE_UP, True



def test_retry_gives_failed_roles_another_round_and_the_run_carries_on(tmp_path):
    async def go():
        mgr = FakeManager()
        run = make_run(tmp_path, mgr)
        stuck = {"tester", "ops"}

        def behave(a, role):
            if role in stuck:  # KiroCrew never lets them start
                gave_up(a)
                return
            if role == "reviewer":
                finish(a, "可以交付")
            else:
                act(a, OUTPUTS[role])
                finish(a)

        await drive(run, mgr, behave)
        assert run.s["status"] == "failed" and {k for k in run.order if run.lane(k)["status"] == "failed"} == stuck
        assert run.lane("backend")["status"] == "waiting"
        assert await run.retry(["backend"]) == []  # not failed: nothing to retry

        stuck.clear()
        assert await run.retry() == ["tester", "ops"]
        assert not run.ended and kinds(run, "run")[-1]["text"] == "重试：测试、运维"
        tester = run.lane("tester")
        assert tester["attempt"] == 2 and [a["kind"] for a in tester["attempts"]] == ["work", "work"]
        task = mgr.by_role("tester").task
        assert task.startswith(TAG + "tester ") and task.split("\n", 1)[0].endswith(" attempt=2]")
        assert "这是第 2 次开工：上一次没做完（agent stopped" in task
        assert "测试第 2 轮：重新开工" in [e["text"] for e in kinds(run, "spawned")]
        await drive(run, mgr, behave)
        assert run.s["status"] == "done" and run.s["tests"]["failed"] == 0
        assert all(run.lane(k)["status"] in ("merged", "done") for k in run.order)

    asyncio.run(go())


def test_a_stopped_run_is_retried_and_a_merged_role_that_failed_later_is_sent_back(tmp_path):
    async def go():
        mgr = FakeManager()
        run = make_run(tmp_path, mgr, team=mini_team())
        await run.tick()
        act(mgr.by_role("pm"), {"docs/product/acceptance.md": "AC-6\n"})
        finish(mgr.by_role("pm"))
        await run.tick()  # backend and frontend start
        assert await run.stop()
        assert run.s["status"] == "stopped" and run.lane("backend")["status"] == "failed"
        assert set(await run.retry()) == {"backend", "frontend"} and run.s["status"] == "running"

        def behave(a, role):
            if role == "reviewer":
                finish(a, "可以交付")
            else:
                act(a, {"backend": {"backend/server.js": "// v2\n"}, "frontend": {"frontend/index.html": "<h1/>\n"}}[role])
                finish(a)

        await drive(run, mgr, behave)
        assert run.s["status"] == "done"
        assert [a["kind"] for a in run.lane("backend")["attempts"]] == ["work", "work"]

    asyncio.run(go())


def test_retry_route(tmp_path):
    mgr = FakeManager()
    svc, routes = make(tmp_path, mgr, tick_s=60)

    async def go():
        await svc.start()
        try:
            rid = (await call(routes, "POST", "/runs", json_body={})).body["run"]
            r = await call(routes, "POST", f"/runs/{rid}/retry", json_body={})
            assert (r.status, r.code) == (409, "nothing_to_retry")
            r = await call(routes, "POST", f"/runs/{rid}/retry", json_body={"roles": "pm"})
            assert (r.status, r.code) == (400, "invalid_roles")
            gave_up(mgr.by_role("pm"))
            for _ in range(3):
                await svc.runs[rid].tick()
                if mgr.live():
                    gave_up(mgr.live()[0])
            assert svc.runs[rid].s["status"] == "failed"
            r = await call(routes, "POST", f"/runs/{rid}/retry", json_body={"roles": ["pm"]})
            assert r.status == 200 and r.body["roles"] == ["pm"] and r.body["status"] == "running"
            assert (await call(routes, "POST", f"/runs/{rid}/retry", user=None)).status == 401
        finally:
            await svc.stop()

    asyncio.run(go())


def test_a_custom_requirement_gets_its_own_title_in_the_readme():
    readme = "# 活动报名小站\n\n## 需求\n\n做一个小网站。\n\n## 约束\n\n- 零依赖\n"
    out = gitwork.with_requirement(readme, "给 devlake 完善 kiro 插件", "给 devlake 完善 kiro 插件")
    assert out.startswith("# 给 devlake 完善 kiro 插件\n") and "## 约束" in out and "做一个小网站" not in out


def test_the_wall_clock_leaves_out_the_time_a_run_spent_ended_before_its_retry(tmp_path):
    board = mod("board")
    team_mod = mod("team")

    async def go():
        t = [1000.0]
        mgr = FakeManager()
        run = make_run(tmp_path, mgr, team=mini_team(), now=lambda: t[0])
        await run.tick()
        gave_up(mgr.by_role("pm"))
        t[0] += 90
        await run.tick()
        assert run.s["status"] == "failed" and run.s["ended_at"] == 1090.0
        t[0] = 5090.0  # an hour later, the person retries
        assert await run.retry() == ["pm"] and run.s["paused_s"] == 4000.0
        t[0] = 5190.0
        view = board.build({run.rid: run}, None, mgr=mgr, scrub=str, now=t[0])
        assert view["run"]["wall_s"] == 190.0  # 1000→1090 and 5090→5190, not the hour in between

    asyncio.run(go())
    events = [{"kind": "run", "text": "运行开始：x", "at": 1000.0}, {"kind": "run", "text": "运行失败：测试没做完", "at": 1090.0},
              {"kind": "tests", "text": "测试 0/0", "at": 2000.0}, {"kind": "run", "text": "重试：测试", "at": 5090.0}]
    assert team_mod.paused_from(events) == 4000.0  # an older run, retried before paused_s was kept
