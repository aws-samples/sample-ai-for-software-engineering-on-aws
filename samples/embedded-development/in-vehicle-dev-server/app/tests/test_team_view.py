"""GET /team (组队预览 in the start form): the default team's roles in flow order, its checks, the knowledge source and
whether each Kiro agent template's file is installed (only stat-ed)."""

import asyncio

from http_fakes import call
from teamkit import mod, ts_types
from test_knowledge import scenario


def test_team_is_owner_only(tmp_path):
    _, routes, _ = scenario(tmp_path)

    async def go():
        assert (await call(routes, "GET", "/team", user=None)).status == 401
        r = await call(routes, "GET", "/team", owner=False)
        assert (r.status, r.code) == (403, "owner_only")

    asyncio.run(go())


def test_the_roles_checks_templates_and_knowledge_of_the_default_team(tmp_path):
    svc, routes, _ = scenario(tmp_path)
    svc.agents_dir = tmp_path / "agents"
    svc.agents_dir.mkdir()
    (svc.agents_dir / "embedded-developer-agent.json").write_text("{}", encoding="utf-8")

    async def go():
        out = (await call(routes, "GET", "/team")).body
        types = ts_types()[0]
        assert set(types["TeamPreview"]) == set(out)
        assert set(types["TeamRoleView"]) == set(out["roles"][0]) and set(types["TeamCheckView"]) == set(out["checks"][0])
        assert out["error"] == "" and out["name"] == "AIDLC-Embedded团队" and out["knowledge"] is None
        roles = {r["key"]: r for r in out["roles"]}
        assert list(roles) == ["triage", "architect", "tester", "dev-fix", "dev-refactor", "reviewer"]
        assert {k: r["gate"] for k, r in roles.items() if r["gate"]} == {"triage": "分诊", "architect": "开工"}
        assert roles["dev-fix"]["writable"] == "按架构师的分工" and roles["reviewer"]["writable"] == "只读"
        assert roles["tester"]["writable"] == "tests/**、docs/aidlc/tests.md"
        assert roles["reviewer"]["aidlc_agent"] == "aidlc-architecture-reviewer-agent" and roles["reviewer"]["phase"] == "review"
        assert {t["name"]: t["present"] for t in out["templates"]} == {
            "embedded-architect-agent": False, "embedded-architecture-reviewer-agent": False,
            "embedded-developer-agent": True, "embedded-quality-agent": False}
        checks = {c["name"]: c for c in out["checks"]}
        assert [c["name"] for c in out["checks"] if c["when"] == "after_bench"] == ["runtime-limits", "logdiff"]
        assert checks["build"] == {"name": "build", "when": "before_bench", "owner": "dev-fix", "max_rounds": 3}
        assert checks["release"]["when"] == "release" and checks["release"]["owner"] is None
        svc.crew["knowledge"] = [{"name": "vstatd", "item_count": 14, "sync_status": "synced"}]
        kb = (await call(routes, "GET", "/team")).body["knowledge"]
        assert kb["name"] == "vstatd" and kb["present"] is True

    asyncio.run(go())


def test_without_a_scenario_folder_it_says_so(tmp_path, monkeypatch):
    monkeypatch.delenv("VSTATD_SAMPLE", raising=False)
    monkeypatch.setattr(mod("paths"), "APP_ROOT", tmp_path / "nowhere" / "app")
    _, routes, _ = scenario(tmp_path, record=False)

    async def go():
        out = (await call(routes, "GET", "/team")).body
        assert out["roles"] == [] and "setup.sh" in out["error"]

    asyncio.run(go())
