"""审计记录 (D14): GET /runs/<rid>/audit and GET /audit/bench, from a run's events and the bench's actions.jsonl."""

import asyncio
import json
import logging
from types import SimpleNamespace

from http_fakes import AppRoute, FakeWeb, call, owner_check
from teamkit import FakeManager, mod, ts_types
from test_flow import T0, ev, iso, recorded

audit, service, handlers = mod("audit"), mod("service"), mod("handlers")
BOARD_BY = "Kiro Crew 看板（you，vstatd-team）"


def bench_file(tmp_path, rid):
    me = f"vstatd-team {rid}"
    recs = [{"at": iso(T0 + 4100), "event": "request", "id": "q1", "action": "deploy", "digest": "bc9372" + "0" * 58,
             "detail": "vstatd, 133240 bytes", "requested_by": me, "timeout_s": 300},
            {"at": iso(T0 + 4160), "event": "decision", "id": "q1", "verdict": "approved", "action": "deploy", "digest": "bc9372" + "0" * 58,
             "by": BOARD_BY, "reason": ""},
            {"at": iso(T0 + 4161), "event": "gate", "id": "q1", "action": "deploy", "stage": "after the approval", "passed": True, "why": "13.5 V"},
            {"at": iso(T0 + 4170), "event": "action", "id": "q1", "action": "deploy", "result": "ok", "detail": "installed"},
            {"at": iso(T0 + 4171), "event": "target", "state": "known", "why": "done", "last_request": "q1"},
            {"at": iso(T0 + 4200), "event": "request", "id": "q2", "action": "replay", "requested_by": me, "timeout_s": 300},
            {"at": iso(T0 + 4500), "event": "decision", "id": "q2", "verdict": "refused", "action": "replay", "by": "you@mac (/dev/ttys003)", "reason": "wrong drive"},
            {"at": iso(T0 + 10), "event": "request", "id": "b1", "action": "replay", "requested_by": "bench tools", "timeout_s": 300},
            {"at": iso(T0 + 20), "event": "decision", "id": "b1", "verdict": "approved", "action": "replay", "by": BOARD_BY, "reason": ""},
            {"at": iso(T0 + 30), "event": "action", "id": "b1", "action": "replay", "result": "ok", "detail": "replay to baseline"},
            {"at": iso(T0 + 31), "event": "supply", "voltage_v": 13.5, "by": "you@mac (/dev/ttys003)"},
            {"at": iso(T0 + 4150), "event": "request", "id": "q9", "action": "deploy", "requested_by": "vstatd-team r1199else"}]
    d = tmp_path / "bench"
    d.mkdir()
    (d / "actions.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs), encoding="utf-8")
    return d


def rig(tmp_path, monkeypatch):
    s, events, _ = recorded(tmp_path)
    s["answers"] = {"architect": [{"id": "Q1", "choice": "B", "differs": True}, {"id": "Q2", "choice": "A", "differs": False}]}
    s["merges"] = [{"role": "dev-fix", "sha": "abc1234def5678", "status": "merged", "at": T0 + 3400}]
    s["team"]["name"] = "vstatd"
    s["base"] = "1111222233334444"
    events += [ev(18, 3400, "merged", "dev-fix", "dev-fix", "开发 · 修复的分支合入运行分支"),
               ev(19, 2000, "plan", "triage", None, "分诊批准（王经理），记在 triage.json（sha256 0123456789abcdef）"),
               ev(20, 300, "done", "triage", None, "分诊完成：F-012 引用 VSTATD-IF-3.2")]
    ctx = SimpleNamespace(name="vstatd-team", logger=logging.getLogger("kcteam-test"), data_dir=str(tmp_path / "data"))
    svc = service.Service(ctx, manager=FakeManager(), work_root=tmp_path / "work", tick_s=60)
    svc.runs[s["id"]] = SimpleNamespace(rid=s["id"], s=s)
    d = tmp_path / "data" / "runs" / s["id"]
    d.mkdir(parents=True)
    (d / "events.jsonl").write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events), encoding="utf-8")
    monkeypatch.setenv("CC1_BENCH_STATE", str(bench_file(tmp_path, s["id"])))
    return s, handlers.build_routes(svc, AppRoute, web=FakeWeb, is_owner=owner_check)


def test_the_run_trail_ties_events_and_its_bench_requests_together(tmp_path, monkeypatch):
    s, routes = rig(tmp_path, monkeypatch)

    async def go():
        path = f"/runs/{s['id']}/audit"
        assert (await call(routes, "GET", path, user=None)).status == 401
        assert (await call(routes, "GET", path, owner=False)).code == "owner_only"
        assert (await call(routes, "GET", "/runs/r9999none/audit")).code == "not_found"
        assert (await call(routes, "GET", path + "?format=pdf")).code == "invalid_format"
        out = (await call(routes, "GET", path)).body
        types = ts_types()[0]
        assert set(out) == types["AuditTrail"] and set(out["entries"][0]) == types["AuditEntry"]
        assert ts_types()[1]["AuditActor"] == set(audit.ACTORS)
        e = out["entries"]
        assert [x["at"] for x in e] == sorted(x["at"] for x in e)
        by = lambda what: next(x for x in e if what in x["what"])  # noqa: E731
        assert (by("运行开始")["actor"], by("运行开始")["step"]) == ("person", "")
        assert (by("人在分诊关卡退回")["actor"], by("人在分诊关卡退回")["step"]) == ("person", "gate-triage")
        assert "sk-ABCDEFGHIJKLMNOPQRSTUV" not in json.dumps(out, ensure_ascii=False)
        tri = by("分诊批准")
        assert (tri["actor"], tri["who"], tri["step"]) == ("person", "王经理", "gate-triage") and "sha256 0123456789abcdef" in tri["evidence"]
        arch = by("人批准了开工")
        assert arch["step"] == "gate-start" and "Q1=B（与建议不同）" in arch["evidence"] and "Q2=A" in arch["evidence"]
        done = by("分诊完成")
        assert (done["actor"], done["who"], done["step"]) == ("agent", "分诊", "triage") and done["evidence"] == "F-012 VSTATD-IF-3.2"
        assert by("合入运行分支")["evidence"] == "commit abc1234def56"
        r1 = by("测试 1/2")
        assert (r1["actor"], r1["step"], r1["evidence"]) == ("app", "before", "build=fail static=pass")
        assert by("测试先行")["step"] == "tests-first"
        assert [x["step"] for x in e if x["actor"] == "app" and "runtime-limits" in x["evidence"]] == ["after"]
        dec = [x for x in e if x["step"] == "bench" and x["actor"] == "person"]
        assert [(x["who"], x["what"]) for x in dec] == [(BOARD_BY, "看板批准部署"), ("you@mac (/dev/ttys003)", "操作台拒绝回放：wrong drive")]
        assert by("向操作台请求部署")["actor"] == "app" and "摘要 bc9372" in by("向操作台请求部署")["evidence"]
        assert by("部署结果 ok")["actor"] == "bench" and by("目标状态 known")["evidence"] == "请求 q1"
        assert not any("q9" in x["evidence"] or "b1" in x["evidence"] for x in e)
        assert by("运行开始")["seq"] == 1 and by("部署结果 ok")["seq"] is None
        sig = e[-1]
        assert (sig["actor"], sig["who"], sig["step"]) == ("person", "王经理", "signoff")

        md = await call(routes, "GET", path + "?format=md")
        assert md.content_type == "text/markdown" and 'filename="audit-r1201done.md"' in md.headers["Content-Disposition"]
        assert md.text.startswith("# 审计记录 · r1201done") and "- 基线提交：1111222233334444" in md.text and "- 团队：vstatd" in md.text
        assert "## 关卡：分诊" in md.text and "| 人 · Kiro Crew 看板（you，vstatd-team） | 看板批准部署 |" in md.text
        js = await call(routes, "GET", path + "?format=json")
        assert js.content_type == "application/json" and json.loads(js.text)["entries"] == e

    asyncio.run(go())


def test_the_bench_trail_has_only_the_requests_no_run_made(tmp_path, monkeypatch):
    _, routes = rig(tmp_path, monkeypatch)

    async def go():
        assert (await call(routes, "GET", "/audit/bench", owner=False)).code == "owner_only"
        e = (await call(routes, "GET", "/audit/bench")).body["entries"]
        assert [(x["actor"], x["who"], x["what"]) for x in e] == [
            ("bench", "bench tools", "向操作台请求回放"), ("person", BOARD_BY, "看板批准回放"), ("bench", "台架", "回放结果 ok：replay to baseline")]
        md = await call(routes, "GET", "/audit/bench?format=md")
        assert "看板批准回放" in md.text

    asyncio.run(go())
