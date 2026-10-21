"""The session runner: a role's agent is a Kiro Crew chat session the app opens, sends to, watches and cleans up."""

import asyncio
import itertools
import logging

from teamkit import mod

sessions, routing, gateway_mod = mod("sessions"), mod("routing"), mod("gateway")
GatewayError = gateway_mod.GatewayError


class FakeGateway:
    """The chat API the runner calls, in memory: a turn starts busy and ends with the scripted rows."""

    def __init__(self) -> None:
        self.folder_rows, self.slot_rows, self.msgs = [], {}, {}
        self.calls, self.script = [], []
        self.ids = itertools.count(1)

    async def folders(self):
        return list(self.folder_rows)

    async def create_folder(self, name, parent_id=None, project_dir=None):
        f = {"id": f"f{next(self.ids)}", "name": name, "parent_id": parent_id, "owner_app": "aidlc-team"}
        self.folder_rows.append(f)
        self.calls.append(("folder", name, parent_id))
        return f

    async def hide_folder(self, fid):
        for f in self.folder_rows:
            if f["id"] == fid:
                f["hidden"] = True
        self.calls.append(("hide_folder", fid))

    async def slots(self):
        return list(self.slot_rows.values())

    absent = ()  # Crew members that are not there (a slot asking for one as a member gets 409)

    async def create_slot(self, name, title, folder_id, model="", memory_mode="incognito", agent="", agent_kind=""):
        if agent and agent_kind == "member" and agent in self.absent:
            raise GatewayError(409, "no such member", "agent_choice_unavailable")
        self.calls.append(("agent", agent, agent_kind))
        self.slot_rows[name] = {"key": name, "title": title, "folder_id": folder_id, "app": "aidlc-team", "running": False}
        self.msgs[name] = []
        self.calls.append(("slot", name, title, model))
        return {"key": name}

    async def set_project(self, key, project):
        self.slot_rows[key]["project"] = project

    async def trust(self, key):
        self.slot_rows[key]["trust"] = True

    async def send(self, key, message, send_id):
        self.calls.append(("send", key, send_id))
        self.msgs[key].append({"role": "user", "content": message, "meta": {"sendId": send_id}})
        rows = self.script.pop(0) if self.script else [{"role": "assistant", "content": "DONE: 好了", "meta": {}}]
        self.slot_rows[key]["running"] = True
        self.slot_rows[key]["_pending"] = rows
        return {"ok": True}

    def finish(self, key):
        row = self.slot_rows[key]
        self.msgs[key].extend(row.pop("_pending", []))
        row["running"] = False

    async def messages(self, key, limit=120):
        return list(self.msgs[key])[-limit:]

    async def stop(self, key):
        self.calls.append(("stop", key))
        self.slot_rows[key]["running"] = False

    async def delete_slot(self, key):
        self.slot_rows.pop(key, None)
        self.calls.append(("delete_slot", key))


def make(tmp_path, gw=None):
    gw = gw or FakeGateway()
    return gw, sessions.SessionManager(gw, app="aidlc-team", state_file=tmp_path / "sessions.json",
                                       log=logging.getLogger("t"))


async def settle(mgr, gw, key, polls=3):
    for _ in range(polls):
        await mgr.poll()
    gw.finish(key)
    for _ in range(polls):
        await mgr.poll()


def test_a_role_session_is_opened_in_the_run_folder_sent_its_task_and_read_back(tmp_path):
    async def go():
        gw, mgr = make(tmp_path)
        gw.script = [[{"role": "tool", "content": "🔧 pwd", "meta": {"tool_name": "shell", "input": '{"command": "pwd"}'}},
                      {"role": "assistant", "content": "改好了\nDONE: 商品列表页写完", "meta": {"turn_stats": {"credits": 1.25}}}]]
        info = mgr.spawn_session("[aidlc-team run=r1 role=catalog]\n写页面", parent_session_key="aidlc-team:r1",
                                 cwd=str(tmp_path / "runs" / "r1" / "wt" / "catalog"), model="claude-sonnet-5.5",
                                 title="前端·商品列表 agent", folder="网上小店 · r1")
        assert sessions.agent_fields(info)["queued"] is True
        await asyncio.sleep(0)
        await asyncio.gather(*mgr._tasks)
        key = info.slot
        assert gw.slot_rows[key]["trust"] and gw.slot_rows[key]["project"].endswith("/wt/catalog")
        assert [c[1] for c in gw.calls if c[0] == "folder"] == ["AI-DLC 团队", "网上小店 · r1"]
        await settle(mgr, gw, key)
        f = sessions.agent_fields(mgr.get(info.id))
        assert f["done"] and f["outcome"] == "completed" and "DONE: 商品列表页写完" in f["result"]
        assert (f["tool_count"], f["last_tool"]) == (1, "Running pwd")
        assert mgr.credits_of(info.id) == 1.25 and mgr.recent(info.id)[0]["tool"] == "Running"
        assert (tmp_path / "sessions.json").exists()

    asyncio.run(go())


def test_a_role_boots_its_crew_member_or_the_template_of_that_name_and_its_knowledge_lookups_are_kept(tmp_path):
    async def go():
        gw, mgr = make(tmp_path)
        gw.absent = ("taoyuan-motion-agent",)
        gw.script = [[{"role": "tool", "content": "🔧 Running: @kirocrew-core/local_knowledge_search",
                       "meta": {"tool_name": "local_knowledge_search", "mcp_server": "kirocrew-core",
                                "input": '{"query": "年会抽奖规则 RULE-1"}'}},
                      {"role": "assistant", "content": "DONE: 写好了需求", "meta": {}}]] * 2
        product = mgr.spawn_session("t", parent_session_key="aidlc-team:r9", cwd=str(tmp_path / "a" / "b" / "c"),
                                    title="产品 agent", agent="aidlc-product-agent")
        motion = mgr.spawn_session("t", parent_session_key="aidlc-team:r9", cwd=str(tmp_path / "a" / "b" / "d"),
                                   title="动效 agent", agent="taoyuan-motion-agent")
        await asyncio.sleep(0)
        await asyncio.gather(*mgr._tasks)
        asked = [c[1:] for c in gw.calls if c[0] == "agent"]
        assert ("aidlc-product-agent", "member") in asked and ("taoyuan-motion-agent", "template") in asked
        assert (product.agent_kind, motion.agent_kind) == ("member", "template")
        assert mgr.agent_of(motion.id) == {"name": "taoyuan-motion-agent", "kind": "template"}
        await settle(mgr, gw, product.slot)
        hits = mgr.knowledge_hits(product.id)
        assert [(h["tool"], h["detail"]) for h in hits] == [("查知识库", "年会抽奖规则 RULE-1")]

    asyncio.run(go())


def test_a_turn_kiro_crew_refused_to_start_is_sent_again(tmp_path):
    async def go():
        gw, mgr = make(tmp_path)
        gw.script = [[{"role": "error", "content": "Execution memory is unavailable", "meta": {"code": "memory_unavailable"}}],
                     [{"role": "assistant", "content": "DONE: ok", "meta": {}}]]
        info = mgr.spawn_session("t", parent_session_key="aidlc-team:r2", cwd=str(tmp_path / "a" / "b" / "c"), title="x")
        await asyncio.sleep(0)
        await asyncio.gather(*mgr._tasks)
        gw.finish(info.slot)
        await mgr.poll()  # the error row, nothing else: sent again
        assert [c[0] for c in gw.calls].count("send") == 2 and info.resends == 1
        await settle(mgr, gw, info.slot)
        assert info.done and info.error is None and "DONE: ok" in info.result

    asyncio.run(go())


def test_a_fix_round_continues_the_same_session_and_a_deleted_session_fails_the_turn(tmp_path):
    async def go():
        gw, mgr = make(tmp_path)
        first = mgr.spawn_session("t", parent_session_key="aidlc-team:r3", cwd=str(tmp_path / "a" / "b" / "c"), title="后端 agent")
        await asyncio.sleep(0)
        await asyncio.gather(*mgr._tasks)
        await settle(mgr, gw, first.slot)
        fix = await mgr.continue_conversation_async(first.id, "修 SEC-1", parent_session_key="aidlc-team:r3", cwd="", model=None)
        assert fix.slot == first.slot and fix.id != first.id and not fix.done
        assert sessions.find_agent(mgr, fix.id) is fix and mgr.slot_of(fix.id) == first.slot
        gw.slot_rows.pop(first.slot)
        for _ in range(sessions.MISSING_POLLS):
            await mgr.poll()
        assert fix.done and "找不到这个会话" in fix.error
        gone = await mgr.continue_conversation_async("s-nope", "x", parent_session_key="aidlc-team:r3", cwd="", model=None)
        assert gone.done and gone.error.startswith("conversation_gone")

    asyncio.run(go())


def test_state_survives_a_reload_and_cleanup_keeps_a_running_run(tmp_path):
    async def go():
        gw, mgr = make(tmp_path)
        a = mgr.spawn_session("t", parent_session_key="aidlc-team:old", cwd=str(tmp_path / "a" / "b" / "c"), title="a")
        b = mgr.spawn_session("t", parent_session_key="aidlc-team:live", cwd=str(tmp_path / "a" / "b" / "d"), title="b")
        await asyncio.sleep(0)
        await asyncio.gather(*mgr._tasks)
        await mgr.poll()
        _, again = make(tmp_path, gw)
        again.load()
        assert again.get(a.id).slot == a.slot and again.get(b.id).slot == b.slot
        done = await again.cleanup({"aidlc-team:live"})
        assert done == {"sessions": 1, "folders": 1} and a.slot not in gw.slot_rows and b.slot in gw.slot_rows
        assert [f["name"] for f in gw.folder_rows if f.get("hidden")] == ["aidlc-team:old"]  # the old run folder, not the live one
        assert again.get(a.id).slot is None and again.get(b.id).slot == b.slot

    asyncio.run(go())


def test_the_orchestrator_picks_the_team_by_keywords_and_says_why():
    pick = routing.route("双十一官方商城大促：挑 20 款家电打折加满减")
    assert pick["team"]["file"] == "team-taoyuan-promo.json" and pick["matched"] == ["双十一", "大促", "满减", "官方商城"]
    assert "1.1 意图捕获" in pick["team"]["stages"]
    fix = routing.route("大促活动页的到手价算错了，帮我修复")
    assert fix["team"]["file"] == "team-bugfix.json" and [o["file"] for o in fix["others"]] == ["team-taoyuan-promo.json"]
    assert routing.route("debug 一下这个 fixture")["team"]["file"] == "team-aidlc.json"  # word boundaries
    assert routing.route("")["team"]["scope"] == "feature"


def test_a_turn_cut_short_by_a_transient_model_error_or_a_hang_is_continued_in_the_same_session(tmp_path):
    async def go():
        clock = [1000.0]
        gw = FakeGateway()
        mgr = sessions.SessionManager(gw, app="aidlc-team", state_file=tmp_path / "sessions.json",
                                      log=logging.getLogger("t"), now=lambda: clock[0])
        tool = {"role": "tool", "content": "🔧 cat a.js", "meta": {"tool_name": "shell", "input": '{"command": "cat a.js"}'}}
        gw.script = [[tool, {"role": "error", "content": "❌ The model backend hit a transient error (HTTP 5xx).", "meta": {}}],
                     [tool, {"role": "assistant", "content": "DONE: 测试写完", "meta": {}}]]
        info = mgr.spawn_session("写测试", parent_session_key="aidlc-team:r7", cwd=str(tmp_path / "a" / "b" / "c"), title="测试 agent")
        await asyncio.sleep(0)
        await asyncio.gather(*mgr._tasks)
        gw.finish(info.slot)
        await mgr.poll()  # worked a while, then the backend failed: told to carry on, not failed
        assert info.nudges == 1 and not info.done and "接着做" in info.last_tool
        assert "你上一轮被中断了" in gw.msgs[info.slot][-1]["content"]
        await settle(mgr, gw, info.slot)
        assert info.done and info.error is None and "DONE: 测试写完" in info.result

        # a hang: busy and nothing new for STUCK_S: stopped, then continued
        gw.script = [[tool], [{"role": "assistant", "content": "DONE: 好了", "meta": {}}]]
        hung = mgr.spawn_session("写页面", parent_session_key="aidlc-team:r7", cwd=str(tmp_path / "a" / "b" / "d"), title="前端 agent")
        await asyncio.sleep(0)
        await asyncio.gather(*mgr._tasks)
        await mgr.poll()
        clock[0] += sessions.STUCK_S + 5
        await mgr.poll()
        assert ("stop", hung.slot) in gw.calls and hung.nudges == 1 and not hung.done
        await settle(mgr, gw, hung.slot)
        assert hung.done and "DONE: 好了" in hung.result

    asyncio.run(go())
