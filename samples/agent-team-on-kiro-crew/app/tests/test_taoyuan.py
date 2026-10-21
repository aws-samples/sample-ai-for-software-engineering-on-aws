"""桃源科技（示例里的虚构公司）：三支团队按需求里的词组队，都查桃源的知识库、命中公司规范；两套公司检查在模板上
红绿分明（大促：空模板红、按约定写完全绿；网页：模板绿、漏出完整手机号就红）。"""

import asyncio
import json
import os
import shutil
from pathlib import Path

import pytest
from teamkit import mod

team_mod, routing, standards, checks, constants, gitwork = (mod("team"), mod("routing"), mod("standards"), mod("checks"),
                                                            mod("constants"), mod("gitwork"))
APP = constants.APP_ROOT
PROMO_REQ = "双十一官方商城大促：挑 20 款家电打折加满减，活动页显示倒计时、划线价和到手价，运营在后台配好就能一键上线。"
DIRECTORY_REQ = "给总部做一个内部通讯录：按部门查人，正式员工和外包都要有，离职的不显示；行政部要能导出名单。"
PASSWORD_REQ = "员工账号设置密码时按公司账号安全规范校验，输入时显示密码强度。"
FIX_REQ = "双十一活动页的到手价算错了，帮我修复。"
NODE = pytest.mark.skipif(not os.access(constants.NODE_BIN, os.X_OK), reason="node is not installed")


def team(name):
    return team_mod.load_team(constants.TEAM_DIR / name)


def test_each_requirement_gets_its_team_and_the_company_standards_it_touches():
    promo = routing.route(PROMO_REQ)
    assert promo["team"]["file"] == "team-taoyuan-promo.json" and "双十一" in promo["matched"]
    got = {s["id"] for s in standards.match(PROMO_REQ, team("team-taoyuan-promo.json"))}
    assert {"PRC", "MGN", "PP", "BR", "DATA-MALL", "DATA-CAMPAIGN"} <= got
    fix = routing.route(FIX_REQ)
    assert fix["team"]["file"] == "team-bugfix.json" and [o["file"] for o in fix["others"]] == ["team-taoyuan-promo.json"]
    # anything else is the AI-DLC team's, and it looks the company's rules up too
    for req, want in ((DIRECTORY_REQ, {"PII", "DATA-EMP", "FE", "BR"}), (PASSWORD_REQ, {"ACC", "DATA-WEAK", "FE"})):
        pick = routing.route(req)
        assert pick["team"]["file"] == "team-aidlc.json" and pick["matched"] == [], req
        got = {s["id"]: s for s in standards.match(req, team("team-aidlc.json"))}
        assert want <= set(got) and "PRC" not in got, (req, sorted(got))
    assert "taoyuan-motion-agent" in promo["roster"]  # the company's own expert, after the official 14


def test_every_role_is_a_crew_member_and_each_team_has_its_gates_and_deployment():
    want = {"team-taoyuan-promo.json": (["product", "compliance"], True), "team-aidlc.json": (["scope", "pm", "reviewer"], True),
            "team-bugfix.json": ([], False)}
    for name, (gates, deploys) in want.items():
        t = team(name)
        assert t["workspace"] == "taoyuan" and t["knowledge"]["source"] == "桃源科技", name
        assert "runner" not in t and all("effort" not in r and "max_turns" not in r for r in t["roles"]), name
        for r in t["roles"]:
            assert r["member"] and r["icon"] and (r.get("assignment") or r.get("mission")), (name, r["key"])
        writers = {r["key"] for r in t["roles"] if r["writable"] or r.get("writable_from")}
        assert {o["role"] for o in t["test_owners"]} <= writers, name
        assert [r["key"] for r in t["roles"] if r.get("gate") == "human"] == gates, name
        assert bool(t["roles"][-1].get("deploy")) is deploys, name
    roles = team("team-taoyuan-promo.json")["roles"]
    c = next(r for r in roles if r["key"] == "compliance")
    assert team_mod.review_targets(c["gate_revise_preset"], roles) == ["backend1"]


def test_the_ai_dlc_team_works_from_the_company_web_template_and_its_checks():
    t = team("team-aidlc.json")
    assert t["fallback"] and t["starter"] == "starters/web" and team_mod.spec_packs(t) == ["packs/taoyuan-web"]
    assert t["standards"] == "packs/taoyuan/standards.json" and set(t["standards_always"]) == {"FE", "BR"}
    assert (constants.TEAM_DIR / t["task_template"]).read_text(encoding="utf-8").count("{standards}") == 1
    ops = t["roles"][-1]
    assert ops["key"] == "ops" and ops["depends_on"] == ["reviewer"] and ops["deploy"]["port"] == 8085
    assert {r["key"] for r in t["roles"] if r.get("writable_from")} == {"backend", "frontend", "mobile"}


def test_the_bugfix_team_reads_any_project_and_changes_anything_but_the_tests():
    t = team("team-bugfix.json")
    assert t["needs_source"] and not team_mod.spec_packs(t) and len(t["roles"]) == 2  # 两人小队
    fixer = next(r for r in t["roles"] if r["key"] == "fixer")
    assert gitwork.matches("server/lib/pricing.js", fixer["writable"]) and gitwork.matches("README.md", fixer["writable"])
    assert not gitwork.matches("tests/regress-total.test.js", fixer["writable"])
    assert not gitwork.matches("tests/enterprise/prc-line.test.js", fixer["writable"])


def lines(found):
    return standards.task_lines(found, "桃源科技")


def test_a_role_task_names_the_standards_to_look_up_in_the_knowledge_base():
    text = lines(standards.match(DIRECTORY_REQ, team("team-aidlc.json")))
    assert "知识库来源「桃源科技」" in text and "《个人信息展示规范》：PII-1" in text and "数据《员工花名册》" in text
    assert lines([]) == "（这次需求不涉及公司规范）"


def _wall(wt, t):
    return asyncio.run(checks.run_tests(wt, t if isinstance(t, dict) else team(t)))


@NODE
def test_the_promo_checks_are_red_on_the_bare_template_and_green_on_a_plain_implementation(tmp_path):
    wt = tmp_path / "promo"
    shutil.copytree(APP / "starters" / "mall", wt)
    shutil.copytree(APP / "packs" / "taoyuan-promo" / "tests" / "enterprise", wt / "tests" / "enterprise")
    bare = _wall(wt, "team-taoyuan-promo.json")
    assert bare["total"] >= 24 and bare["failed"] >= bare["total"] // 2
    assert not [c for c in bare["cases"] if "跑不起来" in c["name"] or "超时" in c["name"]]
    assert {c["owner"] for c in bare["cases"]} == {"product", "backend1", "frontend1", "frontend2", "motion"}
    ref = APP / "packs" / "taoyuan-promo" / "_reference"
    shutil.copytree(ref / "server", wt / "server", dirs_exist_ok=True)
    shutil.copytree(ref / "web", wt / "web", dirs_exist_ok=True)
    done = _wall(wt, "team-taoyuan-promo.json")
    failing = [f"{c['name']}：{c['message']}" for c in done["cases"] if c["status"] == "fail"]
    assert done["total"] == bare["total"] == 28 and not failing, failing
    assert {c["ac"].split("-")[0] for c in done["cases"]} >= {"PRC", "MGN", "PP", "FE", "UX", "BR", "DATA"}
    # the person's decision at the 上线 gate changes the plan: the checks follow it, still green
    cfg = wt / "server" / "config" / "campaign.json"
    plan = json.loads(cfg.read_text(encoding="utf-8"))
    for item in plan["items"]:
        item["pct"] = {"TV65": 90, "X9": 80}.get(item["sku"], item["pct"])
    cfg.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    again = _wall(wt, "team-taoyuan-promo.json")
    assert again["failed"] == 0, [c["name"] for c in again["cases"] if c["status"] == "fail"]
    (wt / "server" / "lib" / "pricing.js").unlink()
    red = _wall(wt, "team-taoyuan-promo.json")
    assert {c["owner"] for c in red["cases"] if c["status"] == "fail"} == {"backend1"}


@NODE
def test_the_web_checks_pass_on_the_template_and_a_leaked_phone_number_goes_to_the_area_that_owns_it(tmp_path):
    wt = tmp_path / "web"
    shutil.copytree(APP / "starters" / "web", wt)
    shutil.copytree(APP / "packs" / "taoyuan-web" / "tests" / "enterprise", wt / "tests" / "enterprise")
    # what the architect's ownership file makes of the test areas (team._resolve_ownership)
    t = {**team("team-aidlc.json"), "test_owners": [{"glob": "tests/**/*-server-*", "role": "backend"},
                                                     {"glob": "tests/**/*-web-*", "role": "frontend"}]}
    bare = _wall(wt, t)
    assert bare["total"] >= 8 and bare["failed"] == 0, [c["name"] for c in bare["cases"] if c["status"] == "fail"]
    assert {c["owner"] for c in bare["cases"]} == {"backend", "frontend"}
    assert {c["ac"].split("-")[0] for c in bare["cases"]} >= {"FE", "UX", "BR", "PII"}
    (wt / "server" / "routes" / "index.js").write_text(
        "export const routes = [{ method: 'GET', path: '/api/people', handler: async () => ({ people: [{ name: '甲', phone: '19900001234' }] }) }]\n",
        encoding="utf-8")
    red = _wall(wt, t)
    assert [(c["ac"], c["owner"]) for c in red["cases"] if c["status"] == "fail"] == [("PII-1", "backend")]


def test_the_split_the_product_role_proposes_becomes_the_assignments_and_the_tasks(tmp_path):
    t = team("team-taoyuan-promo.json")
    gated = next(r for r in t["roles"] if r.get("gate") == "human")
    assert gated["plan"] in gated["writable"] and "backend1" in gated["brief"]
    state = team_mod.new_state("r1011plan", PROMO_REQ, t, "{brief}", tmp_path, APP / "starters" / "mall", 0.0)
    wt = Path(state["run_wt"])
    (wt / "docs" / "aidlc" / "2-inception").mkdir(parents=True)
    (wt / gated["plan"]).write_text(json.dumps({"backend1": "价格引擎：划线价、毛利底线、价保", "nobody": "x", "frontend1": "  活动页  "},
                                               ensure_ascii=False))

    class D:  # the bits of Deps a TeamRun reads here
        store = None
        now = staticmethod(lambda: 0.0)
        log = None
    run = team_mod.TeamRun.__new__(team_mod.TeamRun)
    run.s, run.team, run.d, run.events = state, t, D(), []
    run.roles = {r["key"]: r for r in t["roles"]}
    run.order = [r["key"] for r in t["roles"]]
    run.emit = lambda kind, text, **kw: run.events.append((kind, text))
    run._read_plan("product", gated["plan"])
    assert state["plan"] == {"backend1": "价格引擎：划线价、毛利底线、价保", "frontend1": "活动页"}
    assert run.assignment("backend1") == "价格引擎：划线价、毛利底线、价保"
    assert run.assignment("motion") == next(r for r in t["roles"] if r["key"] == "motion")["assignment"]
    assert run.events[-1][0] == "plan" and "后端开发 #1 · 价格引擎" in run.events[-1][1]


def test_a_finished_run_shows_the_team_as_it_was_when_it_ended_and_a_live_one_the_team_now(tmp_path):
    board = mod("board")

    class Crew:  # what the service knows of Crew's 「代理」 page right now
        names = {"aidlc-product-agent", "taoyuan-motion-agent", "taoyuan-new-agent"}

        def member_names(self, workspace=None):
            return set(self.names)

    class Run:
        def __init__(self, ended, s):
            self.team, self.ended, self.s = {"workspace": "taoyuan"}, ended, s

    live = Run(False, {})
    assert board.crew_members(live, Crew()) == sorted(Crew.names)  # a run going: who is on the page now
    over = Run(True, {"crew_members": ["aidlc-product-agent", "taoyuan-motion-agent"]})
    assert board.crew_members(over, Crew()) == ["aidlc-product-agent", "taoyuan-motion-agent"]  # the new one joined later
    assert board.crew_members(Run(True, {}), Crew()) is None  # ended before rosters were kept: not made up from today's
    no_ws = Run(False, {}); no_ws.team = {}
    assert board.crew_members(no_ws, Crew()) is None


def test_every_role_of_the_promo_team_is_a_post_on_the_company_roster():
    t = team("team-taoyuan-promo.json")
    people = {p["key"]: p for p in routing.roster_of(t)}
    assert len(people) == 13
    for r in t["roles"]:
        p = people[r["key"]]
        assert (p["title"], p["member"]) == (r["title"], r["member"]), r["key"]


def test_only_the_motion_designer_is_an_optional_post_and_the_planner_is_told_how_to_leave_it_out():
    t = team("team-taoyuan-promo.json")
    assert [r["key"] for r in t["roles"] if r.get("optional")] == ["motion"]
    planner = next(r for r in t["roles"] if r.get("plan"))
    assert '"skip": {"motion": "一句理由"}' in planner["brief"] and "未入职" in planner["brief"]
