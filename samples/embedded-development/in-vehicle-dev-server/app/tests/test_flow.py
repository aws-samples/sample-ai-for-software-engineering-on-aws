"""GET /runs/<rid>/flow (交付详情): one run's measured segments (agent attempts, human gates, the operator console, check
rounds, the rerun), its moments and totals, from its state, events and the bench's action record only."""

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from http_fakes import AppRoute, FakeWeb, call, owner_check
from teamkit import FakeManager, mod, ts_types

flow, service, handlers = mod("flow"), mod("service"), mod("handlers")
T0 = 1_800_000_000.0
ROLES = [{"key": "triage", "title": "分诊", "icon": "scope", "gate": "human", "gate_label": "分诊"},
         {"key": "architect", "title": "架构师", "icon": "architect", "gate": "human", "gate_label": "开工"},
         {"key": "dev-fix", "title": "开发 · 修复", "icon": "backend"}, {"key": "dev-refactor", "title": "开发 · 重构", "icon": "frontend"}]


def iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def att(n, a, b, credits=None, label="", kind="work"):
    return {"n": n, "kind": kind, "label": label, "started": T0 + a, "ended": None if b is None else T0 + b, "credits": credits, "error": None}


def ev(seq, t, kind, role=None, frm=None, text="", data=None):
    return {"seq": seq, "at": T0 + t, "kind": kind, "role": role, "from": frm, "to": None, "text": text, "data": data}


def recorded(tmp: Path, rid="r1201done"):
    root = tmp / "work" / "runs" / rid
    for d in ("1", "2", "after-1", "tests-first/1"):
        (root / "results" / d).mkdir(parents=True)
    s = {"id": rid, "title": "vstatd 本批", "status": "done", "started_at": T0, "ended_at": T0 + 5600, "repo": str(root / "repo"),
         "team": {"roles": ROLES}, "signoff": {"by": "王经理", "at": T0 + 6000},
         "lanes": {"triage": {"attempts": [att(1, 60, 600, 1.5), att(2, 905, 1200, 0.5, "按意见重写", "revise")]},
                   "architect": {"attempts": [att(1, 1810, 2400, 3)]},
                   "dev-fix": {"attempts": [att(1, 2510, 3000, 2), att(2, 3510, 3700)]},
                   "dev-refactor": {"attempts": [att(1, 2520, 3300), {"n": 2, "started": None, "ended": None, "credits": None}]}}}
    events = [ev(1, 0, "run", text="运行开始"), ev(2, 610, "gate", "triage", "triage"),
              ev(3, 700, "talk", "triage", "person", "人在分诊关卡和分诊讨论"), ev(4, 610.5, "gate", "triage", "triage"),
              ev(5, 900, "bounce", "triage", "person", "人在分诊关卡退回：F-012 sk-ABCDEFGHIJKLMNOPQRSTUV"),
              ev(6, 1210, "gate", "triage", "triage"), ev(7, 1800, "approved", "triage", "person", "人批准了分诊"),
              ev(8, 2410, "gate", "architect", "architect"), ev(9, 2500, "approved", "architect", "person", "人批准了开工"),
              ev(10, 3500, "tests", text="测试 1/2", data={"cases": [["build", "fail"], ["static", "pass"]], "phase": "before_bench", "ms": 400_000}),
              ev(11, 3501, "bounce", "dev-fix", "tests", "build 失败，打回开发 · 修复"),
              ev(12, 4000, "tests", text="测试 2/2", data={"cases": [["build", "pass"], ["static", "pass"]], "phase": "before_bench", "ms": 200_000}),
              ev(13, 4050, "tests", text="测试先行", data={"first": ["T1"]}),  # tests first: not a round of the checks
              ev(14, 5000, "tests", data={"checks": [["runtime-limits", "PASS"], ["logdiff", "PASS"]], "phase": "after_bench", "ms": 300_000}),
              ev(15, 5001, "bench", data={"step": "rerun"}), ev(16, 5600, "tests", data={"checks": [["build", "PASS"]], "differs": [], "phase": "rerun"}),
              ev(17, 6000, "signoff", text="王经理 签字放行")]
    me = f"vstatd-team {rid}"
    recs = [{"at": iso(T0 + 4100), "event": "request", "id": "q1", "action": "deploy", "requested_by": me, "timeout_s": 300},
            {"at": iso(T0 + 4150), "event": "request", "id": "q9", "action": "deploy", "requested_by": "vstatd-team r1199else"},
            {"at": iso(T0 + 4160), "event": "decision", "id": "q1", "verdict": "approved"},
            {"at": iso(T0 + 4200), "event": "request", "id": "q2", "action": "replay", "requested_by": me, "timeout_s": 300},
            {"at": iso(T0 + 4500), "event": "decision", "id": "q2", "verdict": "approved"},
            {"at": iso(T0 + 4510), "event": "decision", "id": "q9", "verdict": "refused"}]
    return s, events, recs


def test_the_segments_moments_and_totals_of_a_recorded_run(tmp_path):
    s, events, recs = recorded(tmp_path)
    out = flow.build(s, events, recs, T0 + 99_999)
    seg = [(x["kind"], x["from"], x["to"], x["role"], x["result"]) for x in out["segments"]]
    assert seg == [
        ("agent", 60.0, 600.0, "triage", None), ("gate", 610.0, 900.0, "triage", "退回"), ("agent", 905.0, 1200.0, "triage", None),
        ("gate", 1210.0, 1800.0, "triage", "批准"), ("agent", 1810.0, 2400.0, "architect", None), ("gate", 2410.0, 2500.0, "architect", "批准"),
        ("agent", 2510.0, 3000.0, "dev-fix", None), ("agent", 2520.0, 3300.0, "dev-refactor", None), ("checks", 3100.0, 3500.0, None, "不过"),
        ("agent", 3510.0, 3700.0, "dev-fix", None), ("checks", 3800.0, 4000.0, None, "通过"), ("console", 4100.0, 4160.0, None, "批准"),
        ("console", 4200.0, 4500.0, None, "批准"), ("checks", 4700.0, 5000.0, None, "通过"), ("rerun", 5001.0, 5600.0, None, "一致")]
    labels = {(x["kind"], x["from"]): x["label"] for x in out["segments"]}
    assert labels[("agent", 905.0)] == "分诊 · 按意见重写" and labels[("agent", 60.0)] == "分诊 · 第 1 轮"
    assert labels[("gate", 2410.0)] == "等人批准 · 开工" and labels[("console", 4200.0)] == "操作台 · replay"
    assert labels[("checks", 3100.0)] == "检查 第 1 轮" and labels[("checks", 4700.0)] == "台架之后的检查"
    assert not any(x["open"] for x in out["segments"])
    assert [(m["at"], m["kind"]) for m in out["marks"]] == [(900.0, "bounce"), (1800.0, "approved"), (2500.0, "approved"),
                                                           (3500.0, "check_fail"), (3501.0, "bounce"), (6000.0, "signoff")]
    assert out["marks"][3]["label"] == "检查不过：build" and out["marks"][-1]["label"] == "王经理 签字放行"
    assert out["totals"] == {"elapsed_s": 6000.0, "agent_s": 2405.0, "person_s": 1330.0, "gate_s": 970.0, "console_s": 360.0,
                             "check_s": 1499.0, "credits": 7.0, "check_rounds": 3, "send_backs": 2}
    assert out["end"] == 6000.0 and out["signed"] and not out["live"]
    assert [r["key"] for r in out["roles"]] == ["triage", "architect", "dev-fix", "dev-refactor"]
    types = ts_types()[0]
    for name, obj in (("RunFlow", out), ("FlowSegment", out["segments"][0]), ("FlowMark", out["marks"][0]), ("FlowTotals", out["totals"])):
        assert set(obj) == types[name], (name, set(obj) ^ types[name])


def test_a_live_run_has_open_segments_and_empty_figures_where_nothing_is_recorded(tmp_path):
    rid = "r1202live"
    s = {"id": rid, "title": "x", "status": "running", "started_at": T0, "team": {"roles": ROLES},
         "lanes": {"triage": {"attempts": [att(1, 60, 600)]}, "architect": {"attempts": [att(1, 700, None)]}}}
    events = [ev(1, 610, "gate", "triage", "triage")]
    recs = [{"at": iso(T0 + 650), "event": "request", "id": "q1", "action": "deploy", "requested_by": f"vstatd-team {rid}", "timeout_s": 30},
            {"at": iso(T0 + 800), "event": "request", "id": "q2", "action": "replay", "requested_by": f"vstatd-team {rid}", "timeout_s": 900}]
    out = flow.build(s, events, recs, T0 + 1000)
    seg = {(x["kind"], x["from"]): (x["to"], x["open"], x["result"]) for x in out["segments"]}
    assert seg[("agent", 700.0)] == (1000.0, True, None) and seg[("gate", 610.0)] == (1000.0, True, None)
    assert seg[("console", 650.0)] == (680.0, False, "超时") and seg[("console", 800.0)] == (1000.0, True, None)
    t = out["totals"]
    assert t["check_s"] is None and t["credits"] is None and t["check_rounds"] is None and t["send_backs"] == 0
    assert t["elapsed_s"] == 1000.0 and out["live"] and out["marks"] == []
    empty = flow.build({"id": "r1203none", "status": "running", "started_at": T0}, [], [], T0 + 5)
    assert empty["segments"] == [] and empty["totals"]["agent_s"] is None and empty["totals"]["person_s"] is None


def test_the_route_is_owner_only_scrubs_the_moments_and_knows_its_runs(tmp_path, monkeypatch):
    s, events, recs = recorded(tmp_path)
    ctx = SimpleNamespace(name="vstatd-team", logger=logging.getLogger("kcteam-test"), data_dir=str(tmp_path / "data"))
    svc = service.Service(ctx, manager=FakeManager(), work_root=tmp_path / "work", tick_s=60)
    svc.runs[s["id"]] = SimpleNamespace(rid=s["id"], s=s)
    d = tmp_path / "data" / "runs" / s["id"]
    d.mkdir(parents=True)
    (d / "events.jsonl").write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events), encoding="utf-8")
    monkeypatch.setattr(mod("scorecard"), "records", lambda d=None: recs)
    routes = handlers.build_routes(svc, AppRoute, web=FakeWeb, is_owner=owner_check)

    async def go():
        path = f"/runs/{s['id']}/flow"
        assert (await call(routes, "GET", path, user=None)).status == 401
        assert (await call(routes, "GET", path, owner=False)).code == "owner_only"
        out = (await call(routes, "GET", path)).body
        assert out["totals"]["console_s"] == 360.0 and out["totals"]["send_backs"] == 2
        assert "sk-ABCDEFGHIJKLMNOPQRSTUV" not in json.dumps(out, ensure_ascii=False)
        r = await call(routes, "GET", "/runs/r9999none/flow")
        assert (r.status, r.code) == (404, "not_found")

    asyncio.run(go())
