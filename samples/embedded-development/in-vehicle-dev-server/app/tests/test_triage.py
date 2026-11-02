"""The triage gate (D4) and traced commits (D13), on the scenario's own backlog and knowledge; checks/trace.sh and
the checks' triage loader run for real on what the app writes."""

import asyncio
import copy
import json
import subprocess
import sys
import time
from pathlib import Path

from teamkit import FakeManager, FakeTests, act, finish, make_deps, mod, sh

triage, team_mod, constants = mod("triage"), mod("team"), mod("constants")
SAMPLE = constants.APP_ROOT.parent
KNOWLEDGE = SAMPLE / "knowledge"
FIX_LABELLED = [i for i, r in triage.backlog(KNOWLEDGE).items() if r["label"] == "fix"]


def proposal(base: str) -> dict:
    """Fixes (one touching behaviour), a justification, deferrals and the refactor added under TR §4.4."""
    picked = {
        "F-003": {"decision": "fix", "evidence": "static-analysis", "behaviour": False},
        "F-018": {"decision": "fix", "evidence": "unit-test", "behaviour": True,
                  "cites": ["[VSTATD-IF p.8 §5.2]"], "facts": ["IPC-REQUESTS"]},
        "F-008": {"decision": "justify", "cites": ["[VSTATD-IF p.7 §4.2]"],
                  "note": "条件实现宽限期，分析器看不到回调里设的标志"},
    }
    findings = [{"id": i, **picked.get(i, {"decision": "defer", "reason": "下一批", "pick_up_when": "本批交付以后"})}
                for i in FIX_LABELLED]
    findings.append({"id": "F-031", "decision": "fix", "evidence": "build", "behaviour": False,
                     "added": {"found_by": "工作项：拆分 Service::run()", "tool": "work item",
                               "location": "src/service.cpp › Service::run"}})
    return {"batch": "vstatd 本批", "base": base, "findings": findings, "allowed_log_differences": [],
            "requirements": [{"id": "REQ-1", "real_target_only": False, "evidence": ["logdiff"]}]}


def checks_loader(path: Path) -> list:
    """What checks/lib/common.py's load_triage says about a triage file (the checks' own rules)."""
    code = ("import json, sys; sys.path.insert(0, sys.argv[1]); import common; "
            "print(json.dumps(common.load_triage(sys.argv[2])[1]))")
    out = subprocess.run([sys.executable, "-c", code, str(SAMPLE / "checks" / "lib"), str(path)],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def test_the_questions_are_the_justifications_deferrals_disagreements_and_added_entries():
    t = proposal("a" * 40)
    assert triage.problems(t, KNOWLEDGE) == []
    rows = triage.backlog(KNOWLEDGE)
    qs = {q["id"]: q for q in triage.questions(t, rows)}
    assert set(qs) == set(FIX_LABELLED) - {"F-003", "F-018"} | {"F-031"}
    j = qs["F-008"]
    assert j["cites"] == ["[VSTATD-IF p.7 §4.2]"] and j["recommend"] == "A" and "（待办标的是 fix）" in j["q"]
    assert j["decision"] == "justify" and qs["F-021"]["decision"] == "defer"
    assert "src/supervisor.cpp › Supervisor::check" in j["q"] and j["why"].startswith("条件实现宽限期")
    assert [o["key"] for o in j["options"]] == ["A", "B"] and j["options"][1]["text"].startswith("不同意：本批修复")
    assert "什么时候再处理：本批交付以后" in qs["F-021"]["why"] and qs["F-021"]["cites"] == []
    assert qs["F-031"]["q"].startswith("F-031 是分诊新加的（工作项：拆分 Service::run()），定为 fix")
    assert [r["id"] for r in triage.listed(t, rows)] == ["F-003", "F-018"]


def test_malformed_triage_files_are_named_by_the_checks_rules():
    t = proposal("a" * 40)
    t["findings"] = [f for f in t["findings"] if f["id"] != "F-001"]
    t["findings"][0] = {"id": "F-002", "decision": "justify", "cites": ["[VSTATD-IF p.3 §4.2]"]}
    t["findings"][-1]["id"] = "F-033"
    t["findings"].append({"id": "F-009", "decision": "fix", "evidence": "build", "behaviour": False})
    t["findings"].append({"id": "F-018", "decision": "fix", "evidence": "unit-test", "behaviour": True, "cites": ["[VSTATD-IF p.8 §5.2]"]})
    got = triage.problems(t, KNOWLEDGE)
    assert "F-009：待办里标的是 later，不在本批" in got
    assert "F-001：待办里标了 fix，但分诊里没有它的决定（TR §4.1）" in got
    assert "新加的发现按 TR §4.4 从 F-031 起依次编号：F-033" in got
    assert "F-002：引用 '[VSTATD-IF p.3 §4.2]'：§4.2 在第 7 页" in got
    assert "F-018：有不止一个决定" in got and any(p.startswith("F-018：涉及行为的修复要引") for p in got)
    assert triage.problems({"base": "HEAD"}, KNOWLEDGE)[0] == "base 要写需求提交（40 位十六进制）"


def test_commit_messages_and_the_merge_trailer():
    t = proposal("a" * 40)
    assert triage.commit_problem("[dev] tidy up", t) == "没写发现编号"
    assert triage.commit_problem("[dev] F-021 later", t) == "引用的 F-021 在分诊里不是修复也不是说明"
    assert triage.commit_problem("[dev] F-018 strtol", t).startswith("F-018 涉及行为，提交说明要写它的事实条目之一（IPC-REQUESTS）")
    assert triage.commit_problem("[dev] F-018 IPC-REQUESTS strtol", t) is None
    assert triage.trailer(["[dev] F-031 split", "[dev] F-018 IPC-REQUESTS", "[dev] F-003"], t) == \
        "Findings: F-003 F-018 F-031\nFacts: IPC-REQUESTS"


# --- through the gate -------------------------------------------------------------------------------------------- #

def mini(tmp: Path):
    src = tmp / "src-tree"
    (src / "src").mkdir(parents=True)
    (src / "src" / "service.cpp").write_text("int run() { return 0; }\n", encoding="utf-8")
    roles = [{"key": "triage", "title": "分诊", "depends_on": [], "gate": "human", "gate_label": "分诊",
              "writable": ["docs/aidlc/triage.json", "docs/aidlc/triage.md"],
              "triage": {"file": "docs/aidlc/triage.json", "knowledge": str(KNOWLEDGE)}, "brief": "分诊"},
             {"key": "dev", "title": "开发", "depends_on": ["triage"], "writable": ["src/**"], "brief": "改"}]
    team = team_mod.check_team({"roles": roles, "defaults": {"max_fix_rounds": 3}})
    mgr = FakeManager()
    state = team_mod.new_state("r1102tri", "", team, "{run}", tmp / "work", src, time.time(), source=src)
    return team_mod.TeamRun(state, make_deps(tmp, mgr, FakeTests([]))), mgr


def write_triage(a, t, msg="[triage] 分诊"):
    act(a, {"docs/aidlc/triage.json": json.dumps(t, ensure_ascii=False), "docs/aidlc/triage.md": "# 分诊\n"}, msg=msg)
    finish(a)


async def ticks(run, cond, n=40):
    for _ in range(n):
        await run.tick()
        if cond():
            return
    raise AssertionError([e["text"] for e in run.events][-5:])


def test_the_triage_gate_and_a_history_that_trace_sh_passes(tmp_path):
    run, mgr = mini(tmp_path)

    async def go():
        await run.tick()
        base = run.s["base"]
        bad = proposal(base)
        bad["findings"].pop(0)
        write_triage(mgr.by_role("triage"), bad)
        await ticks(run, lambda: len(run.lane("triage")["attempts"]) == 2)
        assert "F-001：待办里标了 fix，但分诊里没有它的决定（TR §4.1）" in run.lane("triage")["attempts"][-1]["task"]
        assert run.lane("triage").get("gate") is None and not run.s.get("questions")

        t = proposal(base)
        write_triage(mgr.by_role("triage"), t, "[triage] 补上 F-001")
        await ticks(run, lambda: run.lane("triage").get("gate") == "pending")
        qs = run.s["questions"]["triage"]
        assert len(qs) == 21 and qs[[q["id"] for q in qs].index("F-008")]["cites"] == ["[VSTATD-IF p.7 §4.2]"]
        assert [r["id"] for r in run.s["triage_listed"]] == ["F-003", "F-018"]

        # the person takes neither the deferral of F-021 nor the justification of F-008: back to the triage role, no
        # triage is approved; the send-back names the justification overturned (the scorecard counts it)
        assert await run.gate("triage", "approve", answers={"F-021": {"choice": "B"}, "F-008": {"choice": "B"}}, by="李工")
        assert run.lane("triage").get("gate") is None and run._approved_triage() is None
        sent = [e for e in run.events if e["kind"] == "bounce"][-1]["data"]
        assert sorted(sent["answers"]) == ["F-008", "F-021"] and sent["justified"] == ["F-008"]
        assert "F-021「" in run.lane("triage")["attempts"][-1]["task"] and "B. 不同意：本批修复" in run.lane("triage")["attempts"][-1]["task"]
        f021 = next(f for f in t["findings"] if f["id"] == "F-021")
        f021.clear()
        f021.update(id="F-021", decision="fix", evidence="static-analysis", behaviour=False)
        write_triage(mgr.by_role("triage"), t, "[triage] F-021 改为修复")
        await ticks(run, lambda: run.lane("triage").get("gate") == "pending")
        assert "F-021" not in {q["id"] for q in run.s["questions"]["triage"]}

        assert await run.gate("triage", "approve", by="李工")
        path = Path(run.s["repo"]).parent / "triage.json"
        approved = json.loads(path.read_text(encoding="utf-8"))
        assert approved["approved"]["by"] == "李工" and approved["approved"]["at"].endswith("Z")
        run_wt = Path(run.s["run_wt"])
        assert sh(run_wt, "log", "-1", "--format=%s").strip() == "[run] 人在关卡上的决定"  # decided, then the base
        assert approved["base"] == sh(run_wt, "rev-parse", "HEAD").strip() != base and run._traced()
        assert checks_loader(path) == []  # the checks accept the approved triage and its record
        assert (path.parent / "triage.json.sha256").read_text().split()[0] == run.s["triage"]["sha256"]

        await ticks(run, lambda: bool(run.lane("dev")["attempts"]))
        dev = mgr.by_role("dev")
        act(dev, {"src/service.cpp": "int run() { return 1; }\n"}, msg="[dev] split the run loop")
        act(dev, {"src/fd.cpp": "// F-003\n"}, commit=False)
        finish(dev)
        await ticks(run, lambda: len(run.lane("dev")["attempts"]) == 2)
        assert "这些改动没有提交：src/fd.cpp" in run.lane("dev")["attempts"][-1]["task"]
        assert run.lane("dev")["attempts"][-1]["kind"] == "trace"

        dev = mgr.by_role("dev")
        act(dev, {}, msg="[dev] F-003: close the fd")  # commits what was left; the first commit still cites nothing
        finish(dev)
        await ticks(run, lambda: len(run.lane("dev")["attempts"]) == 3)
        task = run.lane("dev")["attempts"][-1]["task"]
        assert "「[dev] split the run loop」：没写发现编号" in task and "git reset --soft $(git merge-base HEAD" in task

        dev = mgr.by_role("dev")
        wt = Path(dev.cwd)
        sh(wt, "reset", "-q", "--soft", sh(wt, "merge-base", "HEAD", run.s["branch"]).strip())
        sh(wt, "reset", "-q")
        sh(wt, "checkout", "--", "src/service.cpp")  # it commits its work again, one finding at a time
        act(dev, {"src/fd.cpp": "// F-003\n"}, msg="[dev] F-003: close the fd")
        act(dev, {"src/service.cpp": "int run() { return 1; }\n"}, msg="[dev] F-031: split Service::run()")
        act(dev, {"src/session.cpp": "// strtol\n"}, msg="[dev] F-018 IPC-REQUESTS: strtol for the interval")
        act(dev, {"src/fd2.cpp": "// F-021\n"}, msg="[dev] F-021: check fcntl")
        finish(dev)
        await ticks(run, lambda: run.ended)
        assert run.s["status"] == "done", [e["text"] for e in run.events][-4:]
        merge = sh(run_wt, "log", "-1", "--format=%B")
        assert merge.startswith("[run] 合入开发（第 3 轮）") and "Findings: F-003 F-018 F-021 F-031\nFacts: IPC-REQUESTS" in merge

        res = tmp_path / "trace-results"
        p = subprocess.run([str(SAMPLE / "checks" / "trace.sh"), "--project", str(run_wt), "--results", str(res),
                            "--triage", str(path)], capture_output=True, text=True)
        out = json.loads((res / "trace.json").read_text())
        assert p.returncode == 0 and out["verdict"] == "PASS", out["reasons"]
        assert [c["findings"] for c in out["details"]["commits"]] == [["F-003"], ["F-031"], ["F-018"], ["F-021"],
                                                                       ["F-003", "F-018", "F-021", "F-031"]]

    asyncio.run(go())


def test_the_triage_role_that_runs_out_of_rounds_on_a_malformed_file_fails(tmp_path):
    run, mgr = mini(tmp_path)
    run.team["defaults"]["max_fix_rounds"] = 1

    async def go():
        await run.tick()
        bad = copy.deepcopy(proposal(run.s["base"]))
        bad["base"] = "HEAD"
        for n in range(2):
            write_triage(mgr.by_role("triage"), bad, f"[triage] {n}")
            bad["batch"] += "!"
            await ticks(run, lambda: len(run.lane("triage")["attempts"]) == n + 2 or run.ended)
        assert run.lane("triage")["status"] == "failed" and run.ended
        assert "分诊文件 docs/aidlc/triage.json 不合格式" in run.events[-2]["text"] + run.events[-1]["text"]

    asyncio.run(go())
