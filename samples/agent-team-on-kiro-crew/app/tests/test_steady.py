"""更稳: a person who sends something back at a gate notes what it kept from going live (拦下的风险: what, and how much,
in yuan); the run keeps it, the board and the 签字单 show it, and the CTO view counts it with what the checks, the
independent review and people sent back before release."""

import asyncio
from datetime import datetime

import pytest
from teamkit import FakeManager, make_deps, mod

team_mod, cto, constants = mod("team"), mod("cto"), mod("constants")
NOW = datetime(2026, 10, 20, 12, 0).timestamp()
REQ = "双十一官方商城大促：挑 20 款家电打折加满减，活动页显示倒计时、划线价和到手价，运营在后台配好就能一键上线。"


def promo_run(tmp_path):
    t = team_mod.load_team(constants.TEAM_DIR / "team-taoyuan-promo.json")
    state = team_mod.new_state("r1020bbbb", REQ, t, "{brief}", tmp_path / "work", constants.APP_ROOT / "starters" / "mall", NOW - 3600)
    return team_mod.TeamRun(state, make_deps(tmp_path, FakeManager(), None, now=lambda: NOW))


def test_a_risk_is_clean_or_nothing():
    clean = team_mod.clean_risk
    assert clean({"what": "  价保退差超过  30 万审批线 ", "amount": "206000"}) == {"what": "价保退差超过 30 万审批线", "amount": 206000.0}
    assert clean({"what": "", "amount": None}) is None and clean("206000") is None and clean(None) is None
    assert clean({"amount": 8000}) == {"what": "未写明", "amount": 8000.0}
    assert clean({"what": "越权读取客户手机号", "amount": -5}) == {"what": "越权读取客户手机号", "amount": None}
    assert (team_mod.money(206000), team_mod.money(8000), team_mod.money(None)) == ("¥20.6 万", "¥8,000", "")


def test_a_send_back_keeps_its_risk_and_an_approval_does_not(tmp_path):
    run = promo_run(tmp_path)

    async def no_session(*a, **k):  # sending work back starts the named members' sessions: not what this test is about
        return None
    run._start = no_session
    risk = {"what": "价保退差超过 30 万审批线", "amount": 206000}
    run.lane("product")["gate"] = "pending"
    assert asyncio.run(run.gate("product", "approve", "批准。", risk=risk))
    assert "risks" not in run.s  # 批准 keeps nothing from going live

    lane = run.lane("compliance")  # the release gate is a review gate: the note says whom to send back to
    lane.update(gate="pending", status="done")
    assert not asyncio.run(run.gate("compliance", "revise", "价保超了", risk=risk))  # 退回 without 打回给谁 is refused…
    assert "risks" not in run.s  # …and notes nothing

    note = "按上线前体检退回。\n打回：后端开发 #1。价保退差超过 30 万要 CFO 审批"
    assert asyncio.run(run.gate("compliance", "revise", note, risk=risk))
    (r,) = run.s["risks"]
    assert (r["what"], r["amount"], r["gate"], r["role"], r["at"]) == ("价保退差超过 30 万审批线", 206000.0, "上线", "compliance", NOW)
    back = [e for e in run.events if e["kind"] == "bounce" and e["from"] == "person"][-1]
    assert back["data"] == {"risk": {"what": "价保退差超过 30 万审批线", "amount": 206000.0, "gate": "上线"}}

    board = mod("board").detail(run, mgr=FakeManager(), scrub=str, now=NOW)
    assert board["risks"] == [{"what": "价保退差超过 30 万审批线", "amount": 206000.0, "gate": "上线", "role": "compliance", "at": NOW}]
    assert next(x for x in board["roles"] if x["key"] == "compliance")["gate_revise_risk"] == {"what": "价保退差超过 30 万审批线", "amount": 206100.0}


def test_the_promotion_team_presets_the_risk_of_sending_its_release_back():
    t = team_mod.load_team(constants.TEAM_DIR / "team-taoyuan-promo.json")
    roles = {r["key"]: r for r in t["roles"]}
    assert team_mod.clean_risk(roles["compliance"]["gate_revise_risk"]) == {"what": "价保退差超过 30 万审批线", "amount": 206100.0}
    bad = {**t, "roles": [{**r, "gate_revise_risk": {"what": "", "amount": "很多"}} if r["key"] == "compliance" else r for r in t["roles"]]}
    with pytest.raises(ValueError, match="gate_revise_risk"):
        team_mod.check_team(bad)


def test_a_signed_run_brings_what_it_caught_and_its_risks_to_the_cto_view(tmp_path):
    run = promo_run(tmp_path)
    t0 = run.s["started_at"]
    run.s["risks"] = [{"what": "价保退差超过 30 万审批线", "amount": 206000.0, "gate": "上线", "role": "compliance", "at": t0 + 600, "note": ""}]
    run.s.update(status="done", ended_at=t0 + 1020)
    run.s["signoff"] = {"by": "研发负责人", "note": "", "at": t0 + 1100, "tests": "40/40"}
    events = [
        {"seq": 1, "at": t0 + 300, "kind": "bounce", "role": "backend1", "from": "tests", "text": "AC-5 失败，打回后端开发 #1"},
        {"seq": 2, "at": t0 + 590, "kind": "gate", "role": "compliance", "from": None, "text": "上线关卡：等人批准"},
        {"seq": 3, "at": t0 + 600, "kind": "bounce", "role": "compliance", "from": "person", "text": "人在上线关卡退回：打回：后端开发 #1"},
        {"seq": 4, "at": t0 + 601, "kind": "bounce", "role": "backend1", "from": "compliance", "text": "按人的意见打回后端开发 #1"},
    ]
    (item,) = [i for i in cto.build({run.rid: run}, NOW, events_of=lambda r: events, history={
        "meta": {"today": "2026-10-20", "agentStart": "2026-07-29", "weeks": [], "lines": ["电商"], "peoplePerLine": 12},
        "items": [], "wip": []})["items"] if i["real"]]
    assert item["caught"] == {"person": 1, "review": 0, "checks": 1}  # the person's send-back is not counted as a review too
    assert item["risks"] == [{"what": "价保退差超过 30 万审批线", "amount": 206000.0, "gate": "上线", "role": "compliance", "at": 600.0}]
    assert cto.flow(run, events, NOW)["risks"] == item["risks"]
