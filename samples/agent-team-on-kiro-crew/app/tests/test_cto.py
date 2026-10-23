"""CTO 视图：交付标签（团队默认、第一个关卡的角色提议、人在关卡上确认），和 GET /cto 的数据（模拟历史平移到今天、
签过字的运行算实测、还没签字的运行是需求流动看板上的卡片）。"""

import asyncio
import json
import subprocess
from datetime import date, datetime
from pathlib import Path

import pytest
from teamkit import FakeManager, make_deps, mod

team_mod, cto, delivery, constants = mod("team"), mod("cto"), mod("delivery"), mod("constants")
PROMO_REQ = "双十一官方商城大促：挑 20 款家电打折加满减，活动页显示倒计时、划线价和到手价，运营在后台配好就能一键上线。"
NOW = datetime(2026, 10, 20, 12, 0).timestamp()


def promo_run(tmp_path, rid="r1020aaaa", started=NOW - 3600):
    t = team_mod.load_team(constants.TEAM_DIR / "team-taoyuan-promo.json")
    state = team_mod.new_state(rid, PROMO_REQ, t, "{brief}", tmp_path / "work", constants.APP_ROOT / "starters" / "mall", started)
    return team_mod.TeamRun(state, make_deps(tmp_path, FakeManager(), None, now=lambda: NOW))


def kinds(run, kind):
    return [e["text"] for e in run.events if e["kind"] == kind]


def test_the_labels_are_the_team_defaults_until_the_planner_proposes_and_a_person_confirms(tmp_path):
    run = promo_run(tmp_path)
    assert run.delivery() == {"name": "双十一官方商城大促", "kind": "新功能", "size": "中", "line": "电商", "why": ""}
    rel = run.roles["product"]["delivery"]
    assert rel in run.roles["product"]["writable"] and "delivery.json" in run.roles["product"]["brief"]
    run.s["run_wt"] = str(tmp_path / "wt")  # the run branch's worktree, where the planner wrote its file
    (tmp_path / "wt" / "docs" / "aidlc" / "2-inception").mkdir(parents=True)
    (tmp_path / "wt" / rel).write_text(json.dumps({"name": "  双十一家电大促活动页  ", "kind": "大促", "size": "大",
                                                   "line": "电商", "why": "官方商城的大促活动页"}, ensure_ascii=False))
    run._read_delivery("product", rel)
    assert run.delivery() == {"name": "双十一家电大促活动页", "kind": "新功能", "size": "大", "line": "电商", "why": "官方商城的大促活动页"}
    assert "产品经理提议交付标签：新功能 · 大 · 电商（双十一家电大促活动页）" in kinds(run, "plan")

    run.lane("product")["gate"] = "pending"
    assert asyncio.run(run.gate("product", "approve", "批准。", {"size": "中", "kind": "新应用", "line": "外星"}))
    assert run.s["delivery"] == {"name": "双十一家电大促活动页", "kind": "新应用", "size": "中", "line": "电商", "why": "官方商城的大促活动页"}
    assert any(t.startswith("人确认交付标签：新应用 · 中 · 电商") for t in kinds(run, "plan"))


def test_no_proposal_or_a_wrong_one_keeps_the_defaults(tmp_path):
    run = promo_run(tmp_path)
    run.s["run_wt"] = str(tmp_path)
    run._read_delivery("product", "docs/aidlc/2-inception/delivery.json")
    assert run.delivery()["kind"] == "新功能" and "没有提出交付标签" in kinds(run, "plan")[-1]
    (tmp_path / "bad.json").write_text("[1, 2]")
    run._read_delivery("product", "bad.json")
    assert "delivery_proposed" not in run.s
    assert delivery.short_name("给财务部做一个品类毛利看板：按过去 30 天的订单算") == "给财务部做一个品类毛利看板"
    assert delivery.defaults({}, "修一下", on_source=True)["kind"] == "新功能"


def test_a_run_from_before_teams_had_defaults_takes_its_team_file_s_by_name(tmp_path):
    run = promo_run(tmp_path)
    run.team = {k: v for k, v in run.team.items() if k != "delivery_defaults"}  # the team as it was when it ran
    assert (run.delivery()["kind"], run.delivery()["line"]) == ("新功能", "电商")
    run.team = {**run.team, "name": "一支已经没有的团队"}
    assert (run.delivery()["kind"], run.delivery()["line"]) == ("新应用", "内部系统")


@pytest.mark.parametrize("change, says", [
    ({"delivery_defaults": {"kind": "大促"}}, "delivery_defaults.kind"),
    ({"roles": [{"key": "pm", "gate": "human", "delivery": "../x.json"}]}, "相对路径"),
    ({"roles": [{"key": "pm", "delivery": "d.json"}]}, "人的关卡"),
])
def test_a_team_file_with_wrong_delivery_settings_is_refused(change, says):
    team = {"version": 1, "roles": [{"key": "pm"}], **change}
    with pytest.raises(ValueError, match=says):
        team_mod.check_team(team)


def git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


def test_a_run_has_an_issue_and_once_it_delivered_a_pr_that_the_signature_merges_into_main(tmp_path):
    run = promo_run(tmp_path)
    assert run.issue() == {"id": delivery.issue_id(run.rid), "kind": "需求", "reporter": "运营部", "created_at": NOW - 3600}
    assert run.issue()["id"] == delivery.issue_id(run.rid) != delivery.issue_id("r1020bbbb")
    run.s["delivery"] = {"name": "调拨单修复", "kind": "修复", "size": "小", "line": "供应链"}
    assert (run.issue()["kind"], run.issue()["reporter"]) == ("缺陷", "供应链管理部")
    run.s["issue"] = {"reporter": "信息安全组"}  # an imported run brings who raised it
    assert run.issue()["reporter"] == "信息安全组" and run.issue()["id"] == delivery.issue_id(run.rid)
    assert run.pr() is None  # nothing delivered yet
    run.s.update(status="done", ended_at=NOW - 60, verdict="审查说可以合入")
    assert run.pr() is None  # finished, but its deployment never went out
    run.lane("deploy")["deployed"] = {"url": "http://127.0.0.1:8090/", "at": NOW - 90}
    run.lane("backend1").update(file_count=3, lines={"added": 40, "removed": 2})
    run.lane("frontend1").update(file_count=2, lines={"added": 25, "removed": 0})
    pr = run.pr()
    assert {k: pr[k] for k in ("number", "head", "base", "state", "files", "added", "removed", "review", "sha")} == {
        "number": delivery.pr_number(run.rid), "head": f"team/{run.rid}/run", "base": "main", "state": "open",
        "files": 5, "added": 65, "removed": 2, "review": "审查说可以合入", "sha": ""}

    assert asyncio.run(run.merge_pr()) == ""  # no repository here (a run imported from another computer)
    repo = Path(run.s["repo"])
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    (repo / "README.md").write_text("a\n")
    git(repo, "add", "-A"), git(repo, "commit", "-qm", "base")
    git(repo, "checkout", "-qb", run.s["branch"])
    (repo / "app.py").write_text("print(1)\n")
    git(repo, "add", "-A"), git(repo, "commit", "-qm", "run")
    git(repo, "checkout", "-q", "main")
    sha = asyncio.run(run.merge_pr())
    assert sha and git(repo, "rev-parse", "main") == git(repo, "rev-parse", run.s["branch"])
    run.s["signoff"] = {"by": "研发负责人", "note": "", "at": NOW, "tests": "37/37", "merged": sha}
    assert (run.pr()["state"], run.pr()["merged_by"], run.pr()["sha"]) == ("merged", "研发负责人", sha)
    run.s["signoff"]["merged"] = ""  # signed, not merged here (an imported run)
    assert (run.pr()["state"], run.pr()["sha"]) == ("signed", "")


def history():
    return {"meta": {"today": "2026-10-16", "agentStart": "2026-07-25", "weeks": ["2026-05-02", "2026-07-25"],
                     "lines": list(delivery.LINES), "peoplePerLine": 12},
            "items": [{"t": "调拨单重复生成（华南仓）", "line": 3, "kind": "fix", "size": "S", "period": "agent",
                       "ship": "2026-10-16", "cyc": 1.0, "signer": "Zhao Qiang", "real": None}],
            "wip": [{"t": "加班申请审批（法务部）", "line": 4, "kind": "feat", "size": "M", "state": "pool", "col": "需求池", "mins": 4}]}


def signed(run, at, by="研发负责人"):
    run.s.update(status="done", ended_at=run.s["started_at"] + 1020)
    run.s["signoff"] = {"by": by, "note": "", "at": at, "tests": "37/37"}
    return run


def test_the_history_moves_to_today_and_a_signed_run_joins_it_as_measured(tmp_path):
    run = signed(promo_run(tmp_path), NOW - 600)
    run.s["delivery"] = {"name": "双十一家电大促活动页", "kind": "新功能", "size": "中", "line": "电商"}
    events = [
        {"seq": 5, "kind": "approved", "role": "product", "from": "person", "text": "人批准了需求：批准。补充一条：每人每款限购 2 台。"},
        {"seq": 9, "kind": "bounce", "role": "compliance", "from": "person",
         "text": "人在上线关卡退回：按上线前体检退回。\n打回：后端开发 #1。价保退差超过 30 万要 CFO 审批，这次不报：65 寸智能电视 Q7 从 8 折改 9 折。"},
        {"seq": 10, "kind": "bounce", "role": "backend1", "from": "compliance", "text": "按人的意见打回后端开发 #1"},
        {"seq": 14, "kind": "approved", "role": "compliance", "from": "person", "text": "人批准了上线"},
    ]
    out = cto.build({run.rid: run}, NOW, events_of=lambda r: events, history=history())
    assert out["meta"]["today"] == "2026-10-20" and out["meta"]["agentStart"] == "2026-07-29"
    assert out["meta"]["weeks"] == ["2026-05-06", "2026-07-29"]
    sim, real = [i for i in out["items"] if not i["real"]], [i for i in out["items"] if i["real"]]
    assert sim[0]["ship"] == "2026-10-20"  # the history's last day is today
    assert real == [{"t": "双十一家电大促活动页", "line": 0, "kind": "feat", "size": "M", "issue": delivery.issue_id(run.rid),
                     "reporter": "运营部", "created": date.fromtimestamp(NOW - 3600).isoformat(), "period": "agent",
                     "ship": date.fromtimestamp(NOW - 600).isoformat(), "cyc": round(3000 / 86400, 3), "mins": 17,
                     "signer": "研发负责人", "real": run.rid, "tests": "37/37", "members": 8,
                     "decisions": [["批准需求", "补充一条：每人每款限购 2 台。"],
                                   ["退回上线", "价保退差超过 30 万要 CFO 审批，这次不报：65 寸智能电视 Q7 从 8 折改 9 折。"],
                                   ["批准上线", "无补充意见"]],
                     "pr": delivery.pr_number(run.rid), "defects": [],
                     "caught": {"person": 0, "review": 0, "checks": 0}, "risks": []}]  # these events carry no moments
    assert out["meta"]["realAvgMins"] == 17 and out["wip"] == history()["wip"]
    run.s["decisions"] = [["批准需求", "补充规则"]]  # an imported run brings its own list
    assert cto.build({run.rid: run}, NOW, events_of=lambda r: events, history=history())["items"][1]["decisions"] == [["批准需求", "补充规则"]]


def test_runs_not_signed_off_are_cards_that_open_the_run(tmp_path):
    runs = {}

    def add(rid):
        runs[rid] = promo_run(tmp_path / rid, rid)
        return runs[rid]

    at_gate = add("r1020gate")
    at_gate.lane("compliance")["gate"] = "pending"
    at_gate.events.append({"seq": 1, "kind": "gate", "role": "compliance", "at": NOW - 1800, "text": "等人批准：上线"})
    planner = add("r1020plan")
    planner.lane("product")["gate"] = "pending"
    working = add("r1020work")
    working.lane("backend1").update(status="running", started_at=NOW - 300)
    working.lane("frontend1").update(status="running", started_at=NOW - 200)
    delivered = add("r1020done")
    delivered.s.update(status="done", ended_at=NOW - 7200)
    delivered.lane("deploy")["deployed"] = {"url": "http://127.0.0.1:8090/", "at": NOW - 7300}
    failed = add("r1020fail")
    failed.s.update(status="failed", ended_at=NOW - 60)
    hidden = add("r1020hide")
    hidden.s.update(status="done", ended_at=NOW - 60, hidden=True)
    hidden.lane("deploy")["deployed"] = {"url": "x", "at": NOW}
    cards = {c["real"]: c for c in cto.build(runs, NOW, events_of=lambda r: [], history=history())["wip"] if c.get("real")}
    assert set(cards) == {"r1020gate", "r1020plan", "r1020work", "r1020done"}
    gate = cards["r1020gate"]
    assert (gate["state"], gate["col"], gate["gate"], gate["role"], gate["hours"]) == ("wait", "运维", "上线关卡", "compliance", 0.5)
    assert gate["focus"] == "独立审查已出结论，待负责人决定" and gate["live"] and gate["t"] == "双十一官方商城大促"
    assert (cards["r1020plan"]["col"], cards["r1020plan"]["gate"]) == ("启动", "需求关卡")
    assert "交付标签" in cards["r1020plan"]["focus"]
    assert (cards["r1020work"]["state"], cards["r1020work"]["col"], cards["r1020work"]["members"]) == ("agent", "构建", 2)
    assert (cards["r1020done"]["gate"], cards["r1020done"]["col"], cards["r1020done"]["hours"]) == ("签字放行", "运维", 2.0)


def test_the_value_stream_of_a_run_says_where_its_time_went_and_what_happened(tmp_path):
    run = promo_run(tmp_path, started=NOW - 6000)
    t0 = run.s["started_at"]
    at = lambda n: t0 + n  # noqa: E731
    ev = [
        {"seq": 1, "at": at(0), "kind": "spawned", "role": "product", "from": None, "text": "编排器派活：产品经理"},
        {"seq": 2, "at": at(50), "kind": "gate", "role": "product", "from": "product", "text": "等人批准：需求"},
        {"seq": 3, "at": at(250), "kind": "approved", "role": "product", "from": "person", "text": "人批准了需求：批准。补充一条：每人每款限购 2 台。"},
        {"seq": 4, "at": at(251), "kind": "spawned", "role": "backend1", "from": None, "text": "派活"},
        {"seq": 5, "at": at(251), "kind": "spawned", "role": "tester", "from": None, "text": "派活"},
        {"seq": 6, "at": at(500), "kind": "gate", "role": "compliance", "from": "compliance", "text": "等人批准：上线"},
        {"seq": 7, "at": at(700), "kind": "bounce", "role": "compliance", "from": "person", "text": "人在上线关卡退回：按上线前体检退回。\n打回：后端开发 #1。价保要 CFO 审批。"},
        {"seq": 8, "at": at(700), "kind": "bounce", "role": "backend1", "from": "compliance", "text": "按人的意见打回后端开发 #1"},
        {"seq": 9, "at": at(701), "kind": "spawned", "role": "backend1", "from": None, "text": "后端开发 #1第 2 轮"},
        {"seq": 10, "at": at(720), "kind": "bounce", "role": "backend1", "from": "tests", "text": "AC-7 失败，打回后端开发 #1"},
        {"seq": 11, "at": at(800), "kind": "gate", "role": "compliance", "from": "compliance", "text": "等人批准：上线"},
        {"seq": 12, "at": at(900), "kind": "approved", "role": "compliance", "from": "person", "text": "人批准了上线"},
        {"seq": 13, "at": at(901), "kind": "spawned", "role": "deploy", "from": None, "text": "派活"},
        {"seq": 14, "at": at(950), "kind": "deployed", "role": "deploy", "from": None, "text": "部署到本机"},
    ]
    run.s.update(status="done", ended_at=at(960))
    run.lane("deploy")["deployed"] = {"url": "http://127.0.0.1:8090/", "at": at(950)}
    f = cto.flow(run, ev, at(1500))  # delivered, not signed yet: it waits for the signature
    got = [(x["from"], x["to"], x["who"], x["col"], x["label"], x["decision"]) for x in f["segments"]]
    assert got == [(0.0, 50.0, "agent", "启动", "启动", None), (50.0, 250.0, "person", "启动", "等人批准 · 需求关卡", "批准"),
                   (251.0, 500.0, "agent", "构建", "构建", None), (500.0, 700.0, "person", "运维", "等人批准 · 上线关卡", "退回"),
                   (701.0, 800.0, "agent", "构建", "返工", None), (800.0, 900.0, "person", "运维", "等人批准 · 上线关卡", "批准"),
                   (901.0, 960.0, "agent", "运维", "运维", None), (960.0, 1500.0, "person", "运维", "签字放行", None)]
    assert f["segments"][2]["roles"] == ["backend1", "tester"] and f["segments"][2]["phase"] == "construction"
    assert [m["key"] for m in f["team"]] == run.order and f["team"][0] == {"key": "product", "title": "产品经理", "icon": run.roles["product"].get("icon") or "product", "skipped": False, "credits": 0}
    assert [m["kind"] for m in f["marks"]] == ["gate", "approved", "gate", "bounce", "check", "gate", "approved", "deployed"]
    assert f["sent_back"] == {"person": 1, "review": 0, "checks": 1} and f["rework"] == 1 and f["gates"] == 3
    assert (f["agent_s"], f["person_s"]) == (457.0, 1040.0) and f["end"] == 960.0
    assert [(d["at"], d["gate"], d["note"]) for d in f["decisions"]] == [
        (250.0, "批准需求", "补充一条：每人每款限购 2 台。"), (700.0, "退回上线", "价保要 CFO 审批。"), (900.0, "批准上线", "无补充意见")]
    run.s["signoff"] = {"by": "研发负责人", "note": "", "at": at(1200), "tests": "37/37", "merged": "abc1234"}
    f = cto.flow(run, ev, at(1500))
    assert f["segments"][-1]["to"] == 1200.0 and f["segments"][-1]["decision"] == "签字" and f["end"] == 1200.0
    assert [m["kind"] for m in f["marks"]][-2:] == ["signoff", "merged"] and f["pr"]["state"] == "merged"
    run.s["decisions"] = [["批准需求", "补充限购"], ["退回上线", "价保"], ["批准上线", "按 28 万预留"]]  # an imported run's own words
    assert [d["note"] for d in cto.flow(run, ev, at(1500))["decisions"]] == ["补充限购", "价保", "按 28 万预留"]


def test_the_offline_page_carries_the_data_and_when_it_was_made(tmp_path):
    page = tmp_path / "offline.html"
    page.write_text('<html data-snapshot=""><script id="data" type="application/json">/*__DATA__*/{}</script></html>')
    data = {"meta": {"today": "2026-10-20"}, "items": [{"t": "</script><b>"}], "wip": []}
    out = cto.offline(data, generated="2026-10-20 12:00", path=page)
    assert out["name"] == "CTO视图-离线版-2026-10-20.html"
    assert 'data-snapshot="2026-10-20 12:00"' in out["html"] and "<\\/script><b>" in out["html"]
    shipped = cto.OFFLINE.read_text(encoding="utf-8")
    assert 'data-snapshot=""' in shipped and "/*__DATA__*/{}" in shipped


def test_the_shipped_history_is_the_data_the_page_reads():
    h = json.loads(cto.HISTORY.read_text(encoding="utf-8"))
    assert {"today", "agentStart", "weeks", "lines", "peoplePerLine", "eq", "human", "dayRate"} <= set(h["meta"])
    assert h["meta"]["lines"] == list(delivery.LINES) and len(h["meta"]["weeks"]) == 24
    assert {i["kind"] for i in h["items"]} == {"app", "feat", "fix"} and {i["size"] for i in h["items"]} == {"S", "M", "L"}
    assert {i["period"] for i in h["items"]} == {"base", "agent"} and not any(i["real"] for i in h["items"])
    assert {w["state"] for w in h["wip"]} == {"pool", "agent", "wait"}
    assert all(0 <= i["line"] < len(delivery.LINES) for i in h["items"] + h["wip"])
    issues = {i["issue"]: i for i in h["items"] + h["wip"]}
    assert len(issues) == len(h["items"]) + len(h["wip"]) and all(i["reporter"] for i in issues.values())
    assert all(i["created"] <= i["ship"] for i in h["items"]) and len({i["pr"] for i in h["items"]}) == len(h["items"])
    assert all(int(k[3:]) < 3000 for k in issues) and all(i["pr"] < 5000 for i in h["items"])  # apart from the runs' own
    linked = [(i, issues[d]) for i in h["items"] for d in i.get("defects", [])]
    assert linked and all(f["origin"] == i["issue"] and f["kind"] == "fix" and f["ship"] > i["ship"] for i, f in linked)
