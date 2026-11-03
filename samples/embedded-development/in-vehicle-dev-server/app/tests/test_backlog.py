"""GET /backlog (需求清单 on the home page) and the board's backlog view: the work item and the backlog rows, then the
triage's findings with the person's answers and what the latest static and trace results recorded of each."""

import asyncio
import json
import time

from http_fakes import call
from teamkit import ROOT, FakeManager, FakeTests, make_deps, mod, ts_types
from test_knowledge import KNOWLEDGE, scenario

board, team_mod = mod("board"), mod("team")


def test_the_work_item_and_the_backlog(tmp_path):
    _, routes, sample = scenario(tmp_path)

    async def go():
        assert (await call(routes, "GET", "/backlog", user=None)).status == 401
        assert (await call(routes, "GET", "/backlog", owner=False)).code == "owner_only"
        out = (await call(routes, "GET", "/backlog")).body
        assert set(out) == ts_types()[0]["BacklogIndex"] and out["error"] == ""
        header = (ROOT / "ui" / "src" / "board" / "Header.tsx").read_text(encoding="utf-8")
        assert out["work_item"] and f"text: '{out['work_item']}'" in header  # the StartForm's default, the same text
        assert len(out["rows"]) == 30 and out["next_id"] == "F-031"
        assert set(out["rows"][0]) == ts_types()[0]["BacklogRow"]
        assert [r["label"] for r in out["rows"]].count("fix") == 22
        first = out["rows"][0]
        assert first["id"] == "F-001" and "`" not in first["location"] and first["tool"] in ("cppcheck", "clang-tidy")
        with (sample / "knowledge" / "findings-backlog.md").open("a", encoding="utf-8") as f:
            f.write("| F-031 | cppcheck | x | `a.cpp` | m | later |\n")
        assert (await call(routes, "GET", "/backlog")).body["next_id"] == "F-032"

    asyncio.run(go())


def mini(tmp_path):
    roles = [{"key": "triage", "title": "分诊", "depends_on": [], "gate": "human", "gate_label": "分诊",
              "writable": ["docs/aidlc/triage.json"], "brief": "分诊",
              "triage": {"file": "docs/aidlc/triage.json", "knowledge": str(KNOWLEDGE)}},
             {"key": "dev", "title": "开发", "depends_on": ["triage"], "writable": ["src/**"], "brief": "改"}]
    team = team_mod.check_team({"roles": roles, "defaults": {}})
    src = tmp_path / "src-tree"
    src.mkdir()
    state = team_mod.new_state("r1104bl", "", team, "{run}", tmp_path / "work", src, time.time(), source=src)
    root = tmp_path / "runs" / "r1104bl"
    (root / "repo").mkdir(parents=True)
    (root / "wt" / "_run" / "docs" / "aidlc").mkdir(parents=True)
    state.update(repo=str(root / "repo"), run_wt=str(root / "wt" / "_run"))
    return team_mod.TeamRun(state, make_deps(tmp_path, FakeManager(), FakeTests([]))), root


def view(run):
    return board.build({run.rid: run}, None, mgr=None, scrub=lambda s: s, now=time.time())["run"]["backlog"]


TRIAGE = {"batch": "b", "base": "a" * 40, "findings": [
    {"id": "F-003", "decision": "fix", "evidence": "static-analysis", "behaviour": False},
    {"id": "F-008", "decision": "justify", "cites": ["[VSTATD-IF p.7 §4.2]"]},
    {"id": "F-021", "decision": "defer", "reason": "下一批", "pick_up_when": "本批交付以后"},
    {"id": "F-031", "decision": "fix", "evidence": "build", "behaviour": False, "added": {"found_by": "工作项"}}]}


def test_the_board_has_the_backlog_then_the_triage_with_what_the_app_recorded(tmp_path):
    run, root = mini(tmp_path)
    types, _ = ts_types()
    b = view(run)
    assert set(b) == types["BacklogView"] and b["triage"] is None and b["next_id"] == "F-031" and len(b["rows"]) == 30

    (root / "wt" / "_run" / "docs" / "aidlc" / "triage.json").write_text(json.dumps(TRIAGE), encoding="utf-8")
    run.s["answers"] = {"triage": [{"id": "F-008", "choice": "A", "option": "同意说明（评审还会复核引用）", "text": "", "differs": False},
                                   {"id": "F-021", "choice": "other", "option": "", "text": "本批修", "differs": True}]}
    t = view(run)["triage"]
    assert set(t) == types["TriageView"] and t["state"] == "proposed" and t["approved"] is None
    rows = {r["id"]: r for r in t["findings"]}
    assert set(rows["F-003"]) == types["TriageRow"]
    assert rows["F-008"]["answer"] == "A 同意说明（评审还会复核引用）" and rows["F-021"]["answer"] == "其他：本批修"
    assert rows["F-003"]["answer"] is None and rows["F-003"]["evidence"] == "static-analysis" and rows["F-003"]["behaviour"] is False
    assert rows["F-008"]["cites"] == ["[VSTATD-IF p.7 §4.2]"] and rows["F-008"]["evidence"] is None and rows["F-008"]["behaviour"] is None
    assert rows["F-031"]["added"] and not rows["F-003"]["added"]
    assert all(r["static"] is None and r["trace"] is None for r in rows.values())  # no check results yet

    results = root / "results" / "3"
    results.mkdir(parents=True)
    (results / "static.json").write_text(json.dumps({"details": {"findings": [
        {"id": "F-003", "status": "gone"}, {"id": "F-008", "status": "reported"}, {"id": None, "status": "new"}]}}), encoding="utf-8")
    (results / "trace.json").write_text(json.dumps({"details": {"traced": {"F-003": ["1a2b3c4d5e6f"], "F-031": ["0f9e8d7c6b5a", "aa11bb22cc33"]}}}),
                                        encoding="utf-8")
    run.s["tests"]["results"] = str(results)
    (root / "triage.json").write_text(json.dumps({**TRIAGE, "approved": {"by": "李工", "at": "2026-11-02T09:00:00Z"}}), encoding="utf-8")
    t = view(run)["triage"]
    assert t["state"] == "approved" and t["approved"] == {"by": "李工", "at": "2026-11-02T09:00:00Z"}
    rows = {r["id"]: r for r in t["findings"]}
    assert (rows["F-003"]["static"], rows["F-008"]["static"], rows["F-021"]["static"]) == ("gone", "reported", None)
    assert rows["F-031"]["trace"] == ["0f9e8d7c6b5a", "aa11bb22cc33"] and rows["F-008"]["trace"] == []


def test_a_team_without_a_triage_has_no_backlog_view(tmp_path):
    run, _ = mini(tmp_path)
    run.team["roles"][0].pop("triage")
    assert view(run) is None
