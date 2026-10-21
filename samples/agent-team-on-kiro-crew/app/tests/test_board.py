"""GET /board is exactly the Board type of ui/src/types.ts, shaped like the UI's fixture."""

import json
import time

from teamkit import FIXTURE, FakeManager, info, make_deps, mini_team, mod, richest, same_shape, ts_types

board, team_mod, toollog, constants = mod("board"), mod("team"), mod("toollog"), mod("constants")
NOW = 1_791_231_500.0


def rich_run(tmp_path, mgr, tools, rid="r1006rich", started=NOW - 1500):
    """A run in the middle of things, filled in by hand: no git needed to check the shape."""
    team = team_mod.load_team(constants.TEAM_FILE)
    state = team_mod.new_state(rid, "活动报名小站", team, "{run}", tmp_path / "work", constants.TARGET_TEMPLATE, started)
    state.update(status="fixing", base="5e1f0aa0c0ffee", seq=0)
    run = team_mod.TeamRun(state, make_deps(tmp_path, mgr, None, now=lambda: NOW))
    pm = run.lane("pm")
    pm.update(status="merged", attempt=1, worktree="/w/pm", branch=f"team/{rid}/pm", fork="5e1f0aa", started_at=started,
              done_at=started + 180, summary="12 条验收标准", file_count=1, lines={"added": 64, "removed": 0},
              files=[{"path": "docs/product/acceptance.md", "added": 64, "removed": 0, "status": "A"}],
              commits=[{"sha": "a1c9e02", "subject": "[pm] 验收标准", "at": started + 176}])
    pm["attempts"] = [{"n": 1, "kind": "work", "agent": "s-pm", "conv": "s-pm", "requested_at": started,
                       "started": started, "ended": started + 180, "error": None, "summary": "12 条验收标准",
                       "credits": 6.1, "snap": {"turns": 9, "tool_count": 9, "last_tool": "Writing docs/product/acceptance.md",
                                                "last_activity": started + 175, "recent_tools": [], "text_tail": None}}]
    be = run.lane("backend")
    be.update(status="fixing", attempt=2, worktree="/w/backend", branch=f"team/{rid}/backend", fork="d91b6c7",
              started_at=started + 850, violations=["frontend/app.js"],
              files=[{"path": "backend/server.js", "added": 186, "removed": 0, "status": "A"}])
    be["attempts"] = [
        {"n": 1, "kind": "work", "agent": "s-be", "requested_at": started + 850, "started": started + 850,
         "ended": started + 1180, "credits": 9.3},
        {"n": 2, "kind": "fix", "label": "修 AC-6", "agent": "s-be2", "requested_at": started + 1380,
         "started": started + 1380, "ended": None, "credits": None}]
    mgr.agents["s-be2"] = info("s-be2", "[aidlc-team run=x role=backend]", started=started + 1380, turns=11,
                               tool_count=14, last_tool="Editing backend/validate.js", streaming_text="AC-6 失败是因为……")
    mgr.add([("s-be2", {"at": NOW - 5, "tool": "Editing", "kind": "edit", "detail": "backend/validate.js"})])
    state["tests"].update(at=NOW - 30, passed=1, failed=1, total=2, history=[{"at": NOW - 30, "passed": 1, "failed": 1}],
                          cases=[{"id": "api-signup.test.js#AC-6", "ac": "AC-6", "name": "AC-6: 名额满了不能报名",
                                  "file": "tests/api-signup.test.js", "status": "fail", "owner": "backend", "ms": 7,
                                  "message": "expected 409, got 201"},
                                 {"id": "web-render.test.js#AC-1", "ac": "AC-1", "name": "AC-1: 首页", "file": "tests/web-render.test.js",
                                  "status": "pass", "owner": "frontend", "ms": 23, "message": None}])
    state["merges"] = [{"role": "pm", "sha": "a1c9e02", "at": started + 182, "status": "merged", "files": 1, "note": None},
                       {"role": "frontend", "sha": "f5c2d90", "at": started + 1305, "status": "conflict", "files": 4,
                        "note": "backend/server.js"}]
    run.emit("run", "运行开始：活动报名小站")
    run.emit("handoff", "产品经理把 acceptance.md 交给架构师", role="architect", frm="pm", to="architect")
    run.emit("bounce", "AC-6 失败，打回后端", role="backend", frm="tests", to="backend")
    return run


def build(runs, mgr, tools=None, selected=None):
    return board.build({r.rid: r for r in runs}, selected, mgr=mgr, scrub=lambda s: s, now=NOW)


def test_board_has_exactly_the_keys_of_the_ts_contract_and_the_fixture(tmp_path):
    mgr, tools = FakeManager(), None
    out = json.loads(json.dumps(build([rich_run(tmp_path, mgr, tools)], mgr, tools), ensure_ascii=False))
    ref = json.loads(FIXTURE.read_text(encoding="utf-8"))
    same_shape({k: v for k, v in out.items() if k != "run"}, {k: v for k, v in ref.items() if k != "run"})
    same_shape({k: v for k, v in out["run"].items() if k != "roles"}, {k: v for k, v in ref["run"].items() if k != "roles"},
               "board.run")
    for lane in out["run"]["roles"]:
        same_shape(lane, richest(ref["run"]["roles"]), f"lane {lane['key']}")

    types, unions = ts_types()
    run = out["run"]
    backend = next(ln for ln in run["roles"] if ln["key"] == "backend")
    checks = [("Board", out), ("RunCard", out["runs"][0]), ("RunDetail", run), ("TestWall", run["tests"]),
              ("AgentLive", backend["agent"]), ("ToolCall", backend["agent"]["recent_tools"][0]),
              ("FileChange", backend["files"][0]), ("TestCase", run["tests"]["cases"][0]), ("Merge", run["merges"][1]),
              ("TeamEvent", run["events"][0])] + [("Lane", ln) for ln in run["roles"]]
    for name, obj in checks:
        assert set(obj) == types[name], (name, set(obj) ^ types[name])
    assert run["status"] in unions["RunStatus"]
    assert {ln["status"] for ln in run["roles"]} <= unions["LaneStatus"]
    assert {e["kind"] for e in run["events"]} <= unions["TeamEventKind"]
    assert [ln["key"] for ln in run["roles"]] == [r["key"] for r in team_mod.load_team(constants.TEAM_FILE)["roles"]]
    assert run["edges"] == ref["run"]["edges"]


def test_board_values_come_from_state_and_from_kirocrew_live(tmp_path):
    mgr, tools = FakeManager(), None
    run = rich_run(tmp_path, mgr, tools)
    out = build([run], mgr, tools)["run"]
    lanes = {ln["key"]: ln for ln in out["roles"]}
    be, pm = lanes["backend"], lanes["pm"]
    assert be["status"] == "fixing" and be["attempt"] == 2 and be["agent"]["id"] == "s-be2"
    assert be["agent"]["last_tool"] == "Editing backend/validate.js" and be["agent"]["text_tail"] == "AC-6 失败是因为……"
    assert be["agent"]["recent_tools"][0]["detail"] == "backend/validate.js" and be["agent"]["elapsed_s"] == 120
    assert be["active_s"] == 330 + 120 and be["credits"] == 9.3 and be["owns_tests"] == ["api-signup.test.js#AC-6"]
    assert pm["agent"]["turns"] == 9 and pm["agent"]["credits"] == 6.1 and pm["active_s"] == 180  # kept when it ended
    assert lanes["reviewer"]["agent"] is None and lanes["reviewer"]["attempt"] == 1
    assert out["base"] == "5e1f0aa" and out["wall_s"] == 1500 and out["serial_s"] == 630 and out["credits"] == 15.4
    mgr.agents["s-be2"].stalled = True
    assert {ln["key"]: ln["status"] for ln in build([run], mgr, tools)["run"]["roles"]}["backend"] == "stalled"


def test_which_run_the_board_shows_and_the_runs_order(tmp_path):
    mgr, tools = FakeManager(), None
    old = rich_run(tmp_path, mgr, tools, rid="r1001aaaa", started=NOW - 9000)
    new = rich_run(tmp_path, mgr, tools, rid="r1002bbbb", started=NOW - 100)
    assert [c["id"] for c in build([old, new], mgr, tools)["runs"]] == ["r1002bbbb", "r1001aaaa"]
    assert build([old, new], mgr, tools)["run"]["id"] == "r1002bbbb"
    new.s["status"] = "done"
    assert build([old, new], mgr, tools)["run"]["id"] == "r1001aaaa"  # the newest active one
    old.s["status"] = "stopped"
    assert build([old, new], mgr, tools)["run"]["id"] == "r1002bbbb"  # else the newest
    assert build([old, new], mgr, tools, "r1001aaaa")["run"]["id"] == "r1001aaaa"
    assert build([], None, None) == {"at": NOW, "runs": [], "run": None}
    for i in range(250):
        old.emit("tool", f"后端：{i}", role="backend")
    events = build([old], mgr, tools)["run"]["events"]
    assert len(events) == 200 and events[-1]["text"] == "后端：249" and events[0]["seq"] < events[-1]["seq"]
    card = build([old], mgr, tools)["runs"][0]
    assert card["roles_done"] == 1 and card["roles_total"] == 8 and card["tests"] == {"passed": 1, "failed": 1, "total": 2}


def test_a_fresh_run_before_setup_is_a_valid_board(tmp_path):
    team = mini_team()
    state = team_mod.new_state("r1006fresh", "", team, "{run}", tmp_path, constants.TARGET_TEMPLATE, time.time())
    run = team_mod.TeamRun(state, make_deps(tmp_path, FakeManager(), None))
    out = board.build({run.rid: run}, None, mgr=None, scrub=lambda s: s, now=time.time())["run"]
    types, _ = ts_types()
    assert set(out) == types["RunDetail"] and out["base"] == "" and out["credits"] is None
    assert all(ln["status"] == "waiting" and ln["agent"] is None for ln in out["roles"])


def test_tool_calls_read_like_what_the_agent_did():
    toollog = mod("toollog")
    wt = f"{mod('constants').WORK_ROOT}/runs/r1/wt/ops"
    assert toollog.short(f"Running: cd {wt} && git status --short") == "Running: git status --short"
    assert toollog.short(f"Running: cd {wt}; ls ops") == "Running: ls ops"


def test_done_is_found_even_glued_to_the_previous_sentence():
    team_mod = mod("team")
    assert team_mod.parse_done("I left a stray line; fixing it.DONE: 已写好接口契约") == "已写好接口契约"
    assert team_mod.parse_done("UNDONE: 不算") is None
