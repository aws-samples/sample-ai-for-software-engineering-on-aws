"""人在关卡上逐条回答角色提出的问题、和它讨论（它回答，需要时改自己的文档，关卡一直开着），决定交给后面的每个角色。"""

import asyncio
import json
from pathlib import Path

from teamkit import FakeManager, FakeTests, act, finish, make_run, mod, read, sh

team_mod = mod("team")

QUESTIONS = {"questions": [
    {"id": "1", "q": "助手怎么沟通：规则库，还是外部大模型？", "options": [{"key": "A", "text": "站内规则加商品数据"}, {"key": "B", "text": "调外部大模型"}],
     "recommend": "A", "why": "不出公司"},
    {"id": "2", "q": "小桃子能不能当客服头像？", "options": [{"key": "A", "text": "用"}, {"key": "B", "text": "不用"}], "recommend": "B"},
    {"id": "3", "q": "只有一个选项的不算", "options": [{"key": "A", "text": "唯一"}]},
]}


def talk_team(discuss: bool = True) -> dict:
    role = lambda key, title, deps, **kw: {"key": key, "title": title, "emoji": "", "depends_on": deps,  # noqa: E731
                                           "outputs": [], "brief": f"{title}的活", **kw}
    return team_mod.check_team({
        "version": 1, "test_command": ["node", "--test", "tests/"],
        "roles": [
            role("scope", "范围", [], writable=["docs/ideation/**"], phase="ideation", gate="human", gate_label="范围",
                 questions="docs/ideation/questions.json"),
            role("architect", "架构师", ["scope"], writable=["docs/inception/**"], phase="inception"),
            role("reviewer", "评审", ["architect"], writable=[], phase="review", gate="human", gate_label="上线"),
        ],
        "defaults": {"model": "claude-sonnet-5.5", "max_fix_rounds": 1, "gate_discuss": discuss, "max_discuss_rounds": 2},
        "test_owners": [],
    })


async def to_scope_gate(run, mgr):
    await run.tick()
    act(mgr.by_role("scope"), {"docs/ideation/scope.md": "AC-1\n", "docs/ideation/questions.json": json.dumps(QUESTIONS, ensure_ascii=False)})
    finish(mgr.by_role("scope"), "范围 1 条")
    await run.tick()
    assert run.lane("scope")["gate"] == "pending"


def test_the_questions_are_answered_one_by_one_and_travel_downstream(tmp_path):
    async def go():
        mgr = FakeManager()
        run = make_run(tmp_path, mgr, FakeTests([]), team=talk_team(), requirement="电商客服助手")
        await to_scope_gate(run, mgr)
        qs = run.s["questions"]["scope"]
        assert [q["id"] for q in qs] == ["1", "2"]  # a question with one option is not a question
        assert qs[0]["recommend"] == "A" and qs[1]["options"][1] == {"key": "B", "text": "不用"}

        # 2 is answered against the recommendation; 1 is left out: it takes the recommendation
        assert await run.gate("scope", "approve", "不用安卓", answers={"2": {"choice": "A", "text": ""}})
        picked = run.s["answers"]["scope"]
        assert [(a["id"], a["choice"], a["differs"]) for a in picked] == [("1", "A", False), ("2", "A", True)]
        assert run.s["gate_notes"]["scope"] == "不用安卓"  # the note stays the person's words
        approved = [e["text"] for e in run.events if e["kind"] == "approved"][-1]
        assert "决定：1 选 A、2 选 A（与建议不同）" in approved

        doc = read(Path(run.s["run_wt"]), team_mod.DECISIONS_FILE)  # the decisions are in the run branch
        assert "决定 2「小桃子能不能当客服头像？」：A. 用（与建议不同）" in doc and "意见：不用安卓" in doc
        assert "人在关卡上的决定" in sh(run.s["run_wt"], "log", "-1", "--format=%s")

        await run.tick()
        task = mgr.by_role("architect").task  # the architect reads them one by one, the file named
        assert "人在关卡上逐条做的决定" in task and "决定 1「助手怎么沟通：规则库，还是外部大模型？」：A（站内规则加商品数据）" in task
        assert team_mod.DECISIONS_FILE in task and "不用安卓" in task

    asyncio.run(go())


def test_other_with_words_is_the_persons_own_answer(tmp_path):
    async def go():
        mgr = FakeManager()
        run = make_run(tmp_path, mgr, FakeTests([]), team=talk_team(), requirement="客服")
        await to_scope_gate(run, mgr)
        assert await run.gate("scope", "approve", "", answers={"1": {"choice": "other", "text": "先用规则，下期再评估大模型"},
                                                               "2": {"choice": "other", "text": ""}})
        a1, a2 = run.s["answers"]["scope"]
        assert (a1["choice"], a1["text"], a1["differs"]) == ("other", "先用规则，下期再评估大模型", True)
        assert a2["choice"] == "B"  # 其他 without words is no answer: the recommendation
        await run.tick()
        assert "其他：先用规则，下期再评估大模型" in mgr.by_role("architect").task

    asyncio.run(go())


def test_a_discussion_keeps_the_gate_open_and_the_role_answers_in_its_session(tmp_path):
    async def go():
        mgr = FakeManager()
        run = make_run(tmp_path, mgr, FakeTests([]), team=talk_team(), requirement="客服")
        await to_scope_gate(run, mgr)
        assert run.discuss_allowed("scope")
        assert not await run.gate("scope", "discuss", "   ")  # 讨论 has to say something
        assert await run.gate("scope", "discuss", "第 2 题为什么建议不用小桃子？")
        lane = run.lane("scope")
        assert lane["gate"] == "discussing" and lane["attempts"][-1]["kind"] == "discuss"
        conv, _, task, _ = mgr.continued[-1]  # its own session: it remembers what it wrote
        assert conv == lane["attempts"][0]["agent"] and "第 2 题为什么建议不用小桃子？" in task and "不要往下做" in task
        await run.tick()
        assert lane["status"] == "running" and run.s["status"] == "running"
        assert [mgr.role_of(a) for a in mgr.live()] == ["scope"]  # nothing after the gate starts meanwhile

        a = mgr.by_role("scope")
        a.result = "BR-4 只列了三种场景，头像不在其中。\n设计部确认后可以改。\n\nDONE: 解释了第 2 题"
        a.done = True
        await run.tick()
        assert lane["gate"] == "pending" and lane["status"] == "merged"  # only an answer: no new merge, the gate is open
        talk = run.s["talks"]["scope"]
        assert [t["who"] for t in talk] == ["person", "agent"]
        assert talk[1]["text"] == "BR-4 只列了三种场景，头像不在其中。\n设计部确认后可以改。" and talk[1]["changed"] is False
        assert not any(e["kind"] == "failed" for e in run.events)  # answering without changing a file is no failure

        # it changes its documents: merged again, the questions read again
        assert await run.gate("scope", "discuss", "那第 2 题改成建议用，写进范围")
        await run.tick()
        b = mgr.by_role("scope")
        q2 = json.loads(json.dumps(QUESTIONS))
        q2["questions"][1]["recommend"] = "A"
        act(b, {"docs/ideation/questions.json": json.dumps(q2, ensure_ascii=False)})
        finish(b, "第 2 题改成建议用")
        await run.tick()
        assert lane["gate"] == "pending" and run.s["talks"]["scope"][-1]["changed"] is True
        assert run.s["questions"]["scope"][1]["recommend"] == "A"
        assert not run.discuss_allowed("scope")  # 2 rounds for this gate (the team file says so)
        assert run.max_attempts("scope") == 1 + 1 + 2  # the discussions did not use up its fix rounds

        assert await run.gate("scope", "approve")
        await run.tick()
        assert mgr.by_role("architect")  # and the run goes on

    asyncio.run(go())


def test_a_reviewer_answers_without_its_verdict_changing(tmp_path):
    async def go():
        mgr = FakeManager()
        run = make_run(tmp_path, mgr, FakeTests([]), team=talk_team(), requirement="客服")
        await to_scope_gate(run, mgr)
        assert await run.gate("scope", "approve")
        await run.tick()
        act(mgr.by_role("architect"), {"docs/inception/architecture.md": "# 架构\n"})
        finish(mgr.by_role("architect"))
        for _ in range(3):
            await run.tick()
        finish(mgr.by_role("reviewer"), "可以交付")
        await run.tick()
        lane = run.lane("reviewer")
        assert lane["gate"] == "pending" and lane["passed"]
        assert await run.gate("reviewer", "discuss", "价保退差会不会超？")
        await run.tick()
        r = mgr.by_role("reviewer")
        assert "你是只读的" in r.task and "价保退差会不会超？" in r.task
        r.result = "不会，体检是 27.9 万。\nDONE: 要改：其实我又想了想"  # its word in a discussion is not a new verdict
        r.done = True
        await run.tick()
        assert lane["gate"] == "pending" and lane["passed"] and lane["status"] == "done"
        assert run.s["talks"]["reviewer"][-1]["text"] == "不会，体检是 27.9 万。"
        assert not any(e["kind"] == "bounce" for e in run.events)

    asyncio.run(go())


def test_no_discussion_where_the_team_does_not_offer_it(tmp_path):
    async def go():
        mgr = FakeManager()
        run = make_run(tmp_path, mgr, FakeTests([]), team=talk_team(discuss=False), requirement="客服")
        await to_scope_gate(run, mgr)
        assert not run.discuss_allowed("scope")
        assert not await run.gate("scope", "discuss", "能聊聊吗")
        assert run.lane("scope")["gate"] == "pending"

    asyncio.run(go())


def test_a_wrong_questions_file_is_no_questions(tmp_path):
    async def go():
        mgr = FakeManager()
        run = make_run(tmp_path, mgr, FakeTests([]), team=talk_team(), requirement="客服")
        await run.tick()
        act(mgr.by_role("scope"), {"docs/ideation/scope.md": "AC-1\n", "docs/ideation/questions.json": "不是 JSON"})
        finish(mgr.by_role("scope"))
        await run.tick()
        assert run.lane("scope")["gate"] == "pending" and run.s["questions"]["scope"] == []
        assert await run.gate("scope", "approve", "好")  # the person decides in the note, as before
        assert "answers" not in run.s

    asyncio.run(go())


def test_the_aidlc_team_has_a_gate_at_the_end_of_inception():
    t = team_mod.load_team(Path(mod("constants").APP_ROOT) / "team" / "team-aidlc.json")
    roles = {r["key"]: r for r in t["roles"]}
    gates = [(k, r["gate_label"]) for k, r in roles.items() if r.get("gate") == "human"]
    assert gates == [("scope", "范围"), ("pm", "启动"), ("reviewer", "上线")]
    assert set(roles["pm"]["depends_on"]) == {"architect", "designer"}  # it sums up the whole stage
    after = {k for k, r in roles.items() if r.get("phase") == "construction"}
    deps = lambda k: set(roles[k]["depends_on"]) | {x for d in roles[k]["depends_on"] for x in deps(d)}  # noqa: E731
    assert all("pm" in deps(k) for k in after)  # nothing is built before a person approves 启动
    assert roles["scope"]["questions"] in roles["scope"]["writable"] and roles["pm"]["questions"] in roles["pm"]["writable"]
    assert t["defaults"]["gate_discuss"] is True


def test_a_discussion_is_part_of_the_wait_at_its_gate_in_the_value_stream(tmp_path):
    async def go():
        mgr = FakeManager()
        run = make_run(tmp_path, mgr, FakeTests([]), team=talk_team(), requirement="客服")
        await to_scope_gate(run, mgr)
        assert await run.gate("scope", "discuss", "为什么？")
        await run.tick()
        finish(mgr.by_role("scope"), "解释了")
        await run.tick()
        assert await run.gate("scope", "approve")
        flow = mod("cto").flow(run, run.events, now=run.d.now())
        waits = [x for x in flow["segments"] if x["gate"] == "scope"]
        assert len(waits) == 1 and waits[0]["decision"] == "批准"  # one wait, from the gate to the decision

    asyncio.run(go())
