"""v2：构思之后的人工批准关卡，架构师写的分工文件决定开发角色的目录，用不到的角色跳过。"""

import asyncio
import json

from teamkit import FakeManager, FakeTests, act, finish, make_run, mod, read

team_mod = mod("team")


def phased_team() -> dict:
    role = lambda key, title, deps, **kw: {"key": key, "title": title, "emoji": "", "depends_on": deps,  # noqa: E731
                                           "outputs": [], "brief": f"{title}的活", **kw}
    return team_mod.check_team({
        "version": 1, "test_command": ["node", "tests/enterprise/_run.cjs"],
        "ownership": {"file": "docs/inception/ownership.json", "from": "architect"},
        "roles": [
            role("scope", "意图与范围", [], writable=["docs/ideation/**"], phase="ideation", stage="1.4 范围定义",
                 gate="human", gate_label="范围"),
            role("architect", "架构师", ["scope"], writable=["docs/inception/**"], phase="inception"),
            role("backend", "后端", ["architect"], writable_from="ownership", phase="construction"),
            role("mobile", "安卓", ["architect"], writable_from="ownership", phase="construction"),
            role("reviewer", "评审", ["backend", "mobile"], writable=[], phase="review"),
        ],
        "defaults": {"model": "claude-sonnet-5.5", "effort": "high", "max_fix_rounds": 2},
        "test_owners": [],
    })


def own(roles, areas=None):
    return {"docs/inception/ownership.json": json.dumps({"roles": roles, "test_areas": areas or {}}, ensure_ascii=False)}


def test_a_gate_waits_for_the_person_and_the_ownership_file_dispatches_the_team(tmp_path):
    tests = FakeTests([("api-x.test.js#AC-1", "backend", lambda wt: "v2" in read(wt, "backend/server.js"))])

    async def go():
        mgr = FakeManager()
        run = make_run(tmp_path, mgr, tests, team=phased_team(), requirement="下个月推给全公司用")
        assert run.roles["backend"]["writable"] == [team_mod.PENDING_GLOB]
        await run.tick()
        act(mgr.by_role("scope"), {"docs/ideation/scope.md": "SEC-1 SEC-2\n"})
        finish(mgr.by_role("scope"), "范围 2 条")
        await run.tick()
        assert run.lane("scope")["gate"] == "pending" and run.s["status"] == "gating"
        assert [mgr.role_of(a) for a in mgr.live()] == []  # nothing starts behind the gate
        await run.tick()
        assert not run.ended  # waiting for a person is not the end

        assert await run.gate("scope", "approve", "去掉 SEC-2，这次只做 SEC-1")
        await run.tick()
        arch = mgr.by_role("architect")
        assert "去掉 SEC-2，这次只做 SEC-1" in arch.task  # the person's word travels downstream

        act(arch, own({"backend": ["tests/x/**"]}))  # a role may never be given the tests
        finish(arch)
        await run.tick()
        redo = run.lane("architect")["attempts"][-1]
        assert redo["kind"] == "revise" and "分工文件" in redo["task"] and run.lane("architect")["status"] == "fixing"
        assert not run.lane("architect").get("merged_sha")  # a wrong ownership file is not merged

        act(mgr.by_role("architect"), own({"backend": ["backend/**"], "mobile": []}, {"api": "backend"}))
        finish(mgr.by_role("architect"), "分工写好了")
        await run.tick()
        await run.tick()
        assert run.roles["backend"]["writable"] == ["backend/**"] and run.lane("mobile")["status"] == "skipped"
        assert run.team["test_owners"] == [{"glob": "tests/**/*-api-*", "role": "backend"}]
        assert any(e["kind"] == "skipped" and e["role"] == "mobile" for e in run.events)
        assert any(e["kind"] == "ownership" for e in run.events)
        be = mgr.by_role("backend")
        assert "`backend/**`" in be.task

        act(be, {"backend/server.js": "// v2\n"})
        finish(be)
        for _ in range(4):
            await run.tick()
            for a in mgr.live():
                if mgr.role_of(a) == "reviewer":
                    finish(a, "可以交付")
        assert run.s["status"] == "done" and run.lane("mobile")["status"] == "skipped"

    asyncio.run(go())


def test_a_person_can_send_the_gated_work_back(tmp_path):
    async def go():
        mgr = FakeManager()
        run = make_run(tmp_path, mgr, FakeTests([]), team=phased_team(), requirement="上架")
        await run.tick()
        act(mgr.by_role("scope"), {"docs/ideation/scope.md": "STORE-1\n"})
        finish(mgr.by_role("scope"))
        await run.tick()
        assert not await run.gate("architect", "approve")  # only a role behind a gate can be approved
        assert await run.gate("scope", "revise", "漏了账号删除")
        att = run.lane("scope")["attempts"][-1]
        assert att["kind"] == "revise" and "漏了账号删除" in att["task"] and run.lane("scope")["gate"] is None
        act(mgr.by_role("scope"), {"docs/ideation/scope.md": "STORE-1\nCOMP-1\n"})
        finish(mgr.by_role("scope"))
        await run.tick()
        assert run.lane("scope")["gate"] == "pending"  # merged again: the person looks again

    asyncio.run(go())


def test_ownership_problems_are_named():
    problem = team_mod.ownership_problem
    assert team_mod.ok_glob("server/**") and not team_mod.ok_glob("**") and not team_mod.ok_glob("../x")
    assert not team_mod.ok_glob("tests/enterprise/**")


def test_the_v2_team_file_loads():
    team = team_mod.load_team(mod("constants").TEAM_DIR / "team-aidlc.json")
    phases = [r["phase"] for r in team["roles"]]
    assert phases[0] == "ideation" and phases[-2:] == ["review", "operation"]  # the review, then the deployment
    assert any(r.get("gate") == "human" for r in team["roles"])
    assert team["ownership"]["from"] == "architect"


def test_every_event_of_a_run_and_each_test_run_with_its_cases(tmp_path):
    store = mod("store")
    p = tmp_path / "events.jsonl"
    p.write_text('{"seq": 1, "kind": "run", "text": "a"}\n{"seq": 2, "kind": "tests", "text": "b", "data": {"cases": [["x#AC-1", "fail"]]}}\n'
                 '{"seq": 2, "kind": "tests", "text": "b2"}\n{"torn', encoding="utf-8")
    evs = store.all_events(p)
    assert [e["seq"] for e in evs] == [1, 2] and evs[1]["text"] == "b2"  # the later copy of a seq wins, a torn line is skipped
