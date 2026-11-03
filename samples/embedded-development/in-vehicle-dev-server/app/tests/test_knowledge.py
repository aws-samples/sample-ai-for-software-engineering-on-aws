"""GET /knowledge and /knowledge/file (知识库 on the home page): the scenario's documents with figures counted from the
files, one of them as text for the viewer (never outside the knowledge folder, never the PDF), and on the board how
often the roles cite each document."""

import asyncio
import json
import logging
import shutil
import time
from types import SimpleNamespace

from http_fakes import AppRoute, FakeWeb, call, owner_check
from teamkit import FakeManager, FakeTests, make_deps, mod, ts_types

service, handlers, constants, paths, board, team_mod = (mod("service"), mod("handlers"), mod("constants"), mod("paths"),
                                                        mod("board"), mod("team"))
KNOWLEDGE = constants.APP_ROOT.parent / "knowledge"


def scenario(tmp_path, record=True):
    sample = tmp_path / "sample"
    for d in ("checks", "reference-project"):
        (sample / d).mkdir(parents=True)
    shutil.copytree(KNOWLEDGE, sample / "knowledge")
    data = tmp_path / "data"
    data.mkdir()
    if record:
        (data / paths.SAMPLE_FILE).write_text(json.dumps({"sample": str(sample)}), encoding="utf-8")
    ctx = SimpleNamespace(name="vstatd-team", logger=logging.getLogger("kcteam-test"), data_dir=str(data))
    svc = service.Service(ctx, manager=FakeManager(), work_root=tmp_path / "work", tick_s=60)
    return svc, handlers.build_routes(svc, AppRoute, web=FakeWeb, is_owner=owner_check), sample


def test_knowledge_is_owner_only(tmp_path):
    _, routes, _ = scenario(tmp_path)

    async def go():
        for path in ("/knowledge", "/knowledge/file?path=team-rules.md"):
            assert (await call(routes, "GET", path, user=None)).status == 401, path
            r = await call(routes, "GET", path, owner=False)
            assert (r.status, r.code) == (403, "owner_only"), path

    asyncio.run(go())


def test_the_documents_with_figures_from_the_files_and_the_source_state(tmp_path):
    svc, routes, sample = scenario(tmp_path)

    async def go():
        out = (await call(routes, "GET", "/knowledge")).body
        assert out["error"] == "" and out["source"] is None  # Crew's sources not read yet
        docs = {d["path"]: d for d in out["docs"]}
        assert set(ts_types()[0]["KnowledgeDoc"]) == set(out["docs"][0])
        assert list(docs) == ["vstatd-interface.md", "vstatd-interface.pdf", "cc1-platform-notes.md", "team-rules.md",
                              "findings-backlog.md", "cc1-gateway.dbc", "vss-mapping.yaml", "facts/signals.yaml",
                              "facts/messages.yaml", "facts/rules.yaml"]
        figures = {p: {c["label"]: c["n"] for c in d["counts"]} for p, d in docs.items()}
        assert figures["vstatd-interface.md"] == {"节": 41, "页": 11}
        assert figures["findings-backlog.md"] == {"发现": 30, "fix": 22, "later": 8}
        assert figures["cc1-gateway.dbc"] == {"报文": 9, "信号": 24}
        assert figures["vss-mapping.yaml"] == {"信号路径": 24}
        assert [figures[f"facts/{n}.yaml"]["条目"] for n in ("signals", "messages", "rules")] == [24, 9, 39]
        assert {p: d["key"] for p, d in docs.items() if d["key"]} == {"vstatd-interface.md": "VSTATD-IF",
                                                                      "cc1-platform-notes.md": "CC1-PN", "team-rules.md": "TR"}
        pdf = docs["vstatd-interface.pdf"]
        assert pdf["text"] is False and pdf["rendered_from"] == "vstatd-interface.md" and pdf["counts"] == []
        # counted at request time
        with (sample / "knowledge" / "findings-backlog.md").open("a", encoding="utf-8") as f:
            f.write("| F-031 | cppcheck | x | `a.cpp` | m | later |\n")
        again = {d["path"]: d for d in (await call(routes, "GET", "/knowledge")).body["docs"]}
        assert {c["label"]: c["n"] for c in again["findings-backlog.md"]["counts"]} == {"发现": 31, "fix": 22, "later": 9}
        svc.crew["knowledge"] = [{"name": "vstatd", "item_count": 14, "sync_status": "synced"}]
        src = (await call(routes, "GET", "/knowledge")).body["source"]
        assert src["name"] == "vstatd" and src["present"] is True and src["items"] == 14

    asyncio.run(go())


def test_without_a_scenario_folder_the_list_says_so(tmp_path, monkeypatch):
    monkeypatch.delenv("VSTATD_SAMPLE", raising=False)
    monkeypatch.setattr(paths, "APP_ROOT", tmp_path / "nowhere" / "app")
    _, routes, _ = scenario(tmp_path, record=False)
    out = asyncio.run(call(routes, "GET", "/knowledge")).body
    assert out["docs"] == [] and "setup.sh" in out["error"]


def test_one_document_as_text_and_what_is_refused(tmp_path):
    _, routes, sample = scenario(tmp_path)
    outside = tmp_path / "secret.txt"
    outside.write_text("not knowledge\n", encoding="utf-8")
    (sample / "knowledge" / "facts" / "rules.yaml").unlink()
    (sample / "knowledge" / "facts" / "rules.yaml").symlink_to(outside)

    async def get(path):
        return await call(routes, "GET", "/knowledge/file", query={"path": path})

    async def go():
        r = await get("team-rules.md")
        assert r.status == 200 and r.body["text"] == (KNOWLEDGE / "team-rules.md").read_text(encoding="utf-8")
        assert r.body["title"] == "团队规则" and r.body["size"] == (KNOWLEDGE / "team-rules.md").stat().st_size
        assert (await get("facts/signals.yaml")).body["text"].startswith("# Fact entries")
        for bad, code in (("../knowledge/team-rules.md", "invalid_path"), (str(KNOWLEDGE / "team-rules.md"), "invalid_path"),
                          ("facts/../team-rules.md", "invalid_path"), ("", "invalid_path"), ("README.md", "not_found"),
                          ("tools/check_knowledge.py", "not_found"), ("facts/rules.yaml", "invalid_path")):
            r = await get(bad)
            assert r.status in (400, 404) and r.code == code, (bad, r.status, r.code)
            assert "not knowledge" not in json.dumps(r.body, ensure_ascii=False)
        r = await get("vstatd-interface.pdf")
        assert (r.status, r.code) == (415, "binary_file") and "vstatd-interface.md" in r.body["error"]
        (sample / "knowledge" / "team-rules.md").write_text("x" * 1_000_001, encoding="utf-8")
        assert (await get("team-rules.md")).status == 413

    asyncio.run(go())


def test_the_board_counts_each_documents_citations_in_the_roles_replies(tmp_path):
    roles = [{"key": "triage", "title": "分诊", "depends_on": [], "gate": "human", "gate_label": "分诊",
              "writable": ["docs/aidlc/triage.json"], "brief": "分诊",
              "triage": {"file": "docs/aidlc/triage.json", "knowledge": str(KNOWLEDGE)}},
             {"key": "dev", "title": "开发", "depends_on": ["triage"], "writable": ["src/**"], "brief": "改"}]
    team = team_mod.check_team({"roles": roles, "defaults": {}})
    src = tmp_path / "src-tree"
    src.mkdir()
    state = team_mod.new_state("r1103kb", "", team, "{run}", tmp_path / "work", src, time.time(), source=src)
    run = team_mod.TeamRun(state, make_deps(tmp_path, FakeManager(), FakeTests([])))
    run.lane("triage")["attempts"] = [{"n": 1, "kind": "work", "reply": "F-008 justify [VSTATD-IF p.7 §4.2]；[TR §4.1] 和 [TR §4.4]",
                                       "summary": "DONE: 分诊"}]
    run.lane("dev")["attempts"] = [{"n": 1, "kind": "work", "summary": "按 [CC1-PN §6.3] 改 [VSTATD-IF p.8 §5.2]"},
                                   {"n": 2, "kind": "fix", "reply": "没有引用 [TRACE]"}]
    out = board.build({run.rid: run}, None, mgr=None, scrub=lambda s: s, now=time.time())["run"]["knowledge"]["docs"]
    assert set(out[0]) == ts_types()[0]["KnowledgeChip"]
    assert [(d["key"], d["path"], d["cites"]) for d in out] == [
        ("VSTATD-IF", "vstatd-interface.md", 2), ("CC1-PN", "cc1-platform-notes.md", 1), ("TR", "team-rules.md", 2)]
    run.team["roles"][0].pop("triage")  # a team without a triage has no such documents
    assert board.cited_docs(run) == []
