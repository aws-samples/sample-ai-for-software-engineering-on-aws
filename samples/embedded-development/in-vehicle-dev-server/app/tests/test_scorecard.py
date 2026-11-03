"""The scorecard (D8): figures from a run's recorded state, events, approved triage, results directories and the
bench's action record; with nothing behind a figure it is empty (None), never 0."""

import asyncio
import json
import logging
from pathlib import Path
from types import SimpleNamespace

from http_fakes import AppRoute, FakeWeb, call, owner_check
from teamkit import FakeManager, mod, ts_types

scorecard, service, handlers = mod("scorecard"), mod("service"), mod("handlers")
T0 = 1_800_000_000.0  # 2027-01-15T08:00:00Z
CHECKS = [{"name": n, "when": "before_bench"} for n in ("build", "static", "unit")] + [
    {"name": "logdiff", "when": "after_bench"}, {"name": "release", "when": "release"}]
ROLES = [{"key": "triage", "writable": ["docs/aidlc/triage.json"]}, {"key": "dev-fix", "writable": []},
         {"key": "reviewer", "writable": []}]


def write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False), encoding="utf-8")


def recorded(tmp: Path, rid: str = "r1115done") -> dict:
    """A run as the app records it, from the requirement to sign-off."""
    root = tmp / "work" / "runs" / rid
    write(root / "triage.json", {"base": "a" * 40, "approved": {"by": "李工", "at": "2027-01-15T08:30:00Z"}, "findings": [
        {"id": "F-003", "decision": "fix"}, {"id": "F-018", "decision": "fix"}, {"id": "F-008", "decision": "justify"},
        {"id": "F-012", "decision": "justify"}, {"id": "F-021", "decision": "defer"},
        {"id": "F-031", "decision": "fix", "added": {"found_by": "工作项"}}]})
    for n, verdicts in ((1, {"build": "FAIL", "static": "BLOCKED", "unit": "BLOCKED"}),
                        (2, {"build": "PASS", "static": "FAIL", "unit": "FAIL"}),
                        (3, {"build": "PASS", "static": "PASS", "unit": "PASS"})):
        for name, v in verdicts.items():
            write(root / "results" / str(n) / f"{name}.json", {"verdict": v})
    write(root / "results" / "tests-first" / "1" / "unit.json", {"verdict": "FAIL"})  # not a round of the checks
    write(root / "results" / "after-1" / "logdiff.json", {"verdict": "FAIL", "details": {"differences": 3, "unexplained": 2}})
    write(root / "results" / "after-2" / "logdiff.json", {"verdict": "PASS", "details": {"differences": 1, "unexplained": 0}})
    write(root / "results" / "rerun" / "logdiff.json", {"verdict": "PASS", "details": {"differences": 1, "unexplained": 0}})
    events = [{"seq": 1, "at": T0, "kind": "run", "text": "运行开始"},
              {"seq": 2, "at": T0 + 900, "kind": "bounce", "text": "人在分诊关卡改了 2 条决定",
               "data": {"answers": ["F-012", "F-021"], "justified": ["F-012"]}}]
    write(tmp / "data" / "runs" / rid / "events.jsonl", "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events))
    review = {"kind": "work", "summary": "要改：F-008 的说明不成立", "reply": "DONE: 要改\nF-1 F-008 的说明引的页不成立；F-003 也看了\n"
              "- **推翻说明**：F-008\n\n复核通过：F-012 的说明成立，结论不变"}  # F-012 named to confirm it: no overturn
    return {"id": rid, "title": "vstatd 本批", "status": "done", "started_at": T0, "repo": str(root / "repo"),
            "team": {"checks": CHECKS, "roles": ROLES, "bench": {"deploy": ["cc1.sh"]}},
            "lanes": {"reviewer": {"attempts": [review, {"kind": "review", "summary": "可以交付", "reply": "F-012 无害"}]}},
            "tests": {"history": [{"at": T0 + 3000, "passed": 0, "failed": 3}, {"at": T0 + 3600, "passed": 1, "failed": 2},
                                  {"at": T0 + 5400, "passed": 3, "failed": 0}], "rounds": {"build": 1, "static": 1, "unit": 1}},
            "rerun": {"differs": [{"name": "unit", "was": "PASS", "now": "FAIL"}]},
            "signoff": {"by": "王经理", "at": T0 + 9000}}


def actions(rid: str) -> list:
    me, other = f"vstatd-team {rid}", "vstatd-team r1114else"
    return [{"event": "request", "id": "q1", "requested_by": me}, {"event": "decision", "id": "q1", "verdict": "refused"},
            {"event": "request", "id": "q2", "requested_by": me}, {"event": "decision", "id": "q2", "verdict": "approved"},
            {"event": "target", "state": "unknown"}, {"event": "reconcile", "by": "bench owner"},
            {"event": "request", "id": "q3", "requested_by": other}, {"event": "decision", "id": "q3", "verdict": "approved"},
            {"event": "reconcile", "by": "bench owner"},  # after another run's request: that run's
            {"event": "request", "id": "q4", "requested_by": me},
            {"event": "decision", "id": "q4", "verdict": "refused", "by": "bench (timeout)"}]


def test_the_figures_of_a_recorded_run(tmp_path):
    s = recorded(tmp_path)
    write(tmp_path / "bench" / "actions.jsonl", "".join(json.dumps(a) + "\n" for a in actions(s["id"])) + "not json\n")
    out = scorecard.build([s], tmp_path / "data" / "runs", tmp_path / "bench")
    r = out["runs"][0]
    assert r["findings"] == {"fixed": 2, "justified": 2, "deferred": 1}  # the refactor added under TR §4.4 left out
    assert r["overturned"] == {"ids": ["F-008", "F-012"], "by_person": ["F-012"], "by_reviewer": ["F-008"]}
    assert r["times"] == {"triage_s": 1800.0, "first_pass_s": 5400.0, "signoff_s": 9000.0}
    assert r["build_rounds"] == 1 and r["caught"] == {"build": 1, "static": 1, "unit": 1}
    assert r["logdiff"] == {"differences": 4, "unexplained": 2}  # the rerun judged the last replay again: not counted
    assert r["bench"] == {"approved": 1, "refused": 2, "reconciled": 1}
    assert r["rerun_differs"] == ["unit"] and r["signed"]
    assert out["total"] == {"runs": 1, "findings": {"fixed": 2, "justified": 2, "deferred": 1}, "overturned": 2,
                            "build_rounds": 1, "caught": {"build": 1, "static": 1, "unit": 1},
                            "logdiff": {"differences": 4, "unexplained": 2},
                            "bench": {"approved": 1, "refused": 2, "reconciled": 1}, "rerun_differs": 1}
    assert "times" not in out["total"]
    types, _ = ts_types()  # exactly the Scorecard of ui/src/types.ts
    for name, obj in (("Scorecard", out), ("ScoreRun", r), ("ScoreTotal", out["total"]), ("ScoreTimes", r["times"]),
                      ("ScoreFindings", r["findings"]), ("ScoreOverturned", r["overturned"]), ("ScoreLogdiff", r["logdiff"]),
                      ("ScoreBench", r["bench"])):
        assert set(obj) == types[name], (name, set(obj) ^ types[name])


def test_a_run_that_got_nowhere_has_empty_figures_and_sums_take_only_what_exists(tmp_path):
    done = recorded(tmp_path)
    early = {"id": "r1116new", "title": "刚开始", "status": "running", "started_at": T0 + 20000,
             "repo": str(tmp_path / "work" / "runs" / "r1116new" / "repo"),
             "team": {"checks": CHECKS, "roles": ROLES, "bench": {"deploy": ["cc1.sh"]}}, "lanes": {},
             "tests": {"history": [], "rounds": {}}}
    hidden = {**recorded(tmp_path, "r1110gone"), "hidden": True}
    out = scorecard.build([done, early, hidden], tmp_path / "data" / "runs", tmp_path / "no-bench")
    assert [r["id"] for r in out["runs"]] == ["r1116new", "r1115done"]  # newest first, not what a person removed
    r = out["runs"][0]
    assert r["findings"] is None and r["overturned"] is None and r["build_rounds"] is None and r["caught"] is None
    assert r["times"] == {"triage_s": None, "first_pass_s": None, "signoff_s": None}
    assert r["logdiff"] is None and r["bench"] is None and r["rerun_differs"] is None and not r["signed"]
    assert out["total"]["runs"] == 2 and out["total"]["findings"] == {"fixed": 2, "justified": 2, "deferred": 1}
    assert out["total"]["bench"] is None  # no action record: the bench figures stay empty


def test_no_runs_every_figure_is_empty_through_the_route(tmp_path):
    ctx = SimpleNamespace(name="vstatd-team", logger=logging.getLogger("kcteam-test"), data_dir=str(tmp_path / "data"))
    svc = service.Service(ctx, manager=FakeManager(), work_root=tmp_path / "work", tick_s=60)
    routes = handlers.build_routes(svc, AppRoute, web=FakeWeb, is_owner=owner_check)

    async def go():
        r = await call(routes, "GET", "/scorecard")
        assert r.status == 200 and r.body["runs"] == []
        assert r.body["total"] == {"runs": 0, "findings": None, "overturned": None, "build_rounds": None, "caught": None,
                                   "logdiff": None, "bench": None, "rerun_differs": None}

    asyncio.run(go())
