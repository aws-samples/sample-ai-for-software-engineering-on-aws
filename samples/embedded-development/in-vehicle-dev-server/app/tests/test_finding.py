"""补登发现 (TR §4.4): on a run held for a person after the checks, the person registers what a check found and hands
it to a role (``POST /runs/{rid}/finding``). Stand-in checks as in test_checks.py; the knowledge is the scenario's own,
and the triage the app writes is read back with the checks' own ``common.load_triage``."""

import asyncio
import importlib.util
import json
import logging
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_checks import make, work
from teamkit import act, finish, mod, reload, sh

audit, handlers, httpkit, service, triage = mod("audit"), mod("handlers"), mod("httpkit"), mod("service"), mod("triage")
checks = mod("checks")

SAMPLE = Path(__file__).resolve().parents[2]
KNOWLEDGE = SAMPLE / "knowledge"
BUILD_REASON = ("/x/runs/r1/results/2/work/build/tree/src/a.cpp:12:10: fatal error: systemd/sd-daemon.h: "
                "No such file or directory")
TSAN_REASON = "tsan: SUMMARY: ThreadSanitizer: data race /x/results/2/work/unit/tree/src/a.cpp:90 in A::get() const"


def common():
    """checks/lib/common.py, loaded for these tests only (the app never imports the checks)."""
    spec = importlib.util.spec_from_file_location("vstatd_checks_common", SAMPLE / "checks" / "lib" / "common.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def approved_triage(run) -> Path:
    """An approved triage beside the run's repository: every backlog fix, and F-031 added for the work item."""
    rows = triage.backlog(KNOWLEDGE)
    findings = [{"id": i, "decision": "fix", "evidence": "build", "behaviour": False} for i, r in rows.items() if r["label"] == "fix"]
    findings.append({"id": "F-031", "decision": "fix", "evidence": "build", "behaviour": False,
                     "added": {"found_by": "工作项：拆分 Service::run()", "tool": "work item", "location": "src/service.cpp"}})
    t = {"batch": "test", "base": run.s["base"], "findings": findings, "allowed_log_differences": [], "requirements": [],
         "approved": {"by": "负责人", "at": "2026-11-03T06:20:33Z"}}
    path = Path(run.s["repo"]).parent / "triage.json"
    run.s["triage"] = {"path": str(path), "sha256": triage.write(path, t), "base": t["base"], "base_set": False,
                       "approved": t["approved"]}
    return path


def held_run(tmp_path, monkeypatch):
    """dev owns src/a.*; build and unit fail with one round each: held for a person after the second round."""
    bench, mgr, run = make(tmp_path, monkeypatch, {"name": "build", "owner": "dev", "rounds": 1},
                           {"name": "unit", "owner": "dev", "rounds": 1})
    run.team["roles"][2]["triage"] = {"file": "docs/triage.json", "knowledge": str(KNOWLEDGE)}  # whose knowledge it is
    bench.set("build", 1, [BUILD_REASON])
    bench.set("unit", 1, [TSAN_REASON])

    async def go():
        end = time.monotonic() + 30
        while not run.ended and time.monotonic() < end:
            await run.tick()
            for a in mgr.live():
                work(a, mgr.role_of(a))
            await asyncio.sleep(0.05)
    asyncio.run(go())
    assert run.s["status"] == "failed" and run.s["tests"]["held"]["checks"] == ["build", "unit"], run.events[-1]["text"]
    return bench, mgr, run, approved_triage(run)


def svc_of(tmp_path, run, mgr):
    ctx = SimpleNamespace(name="vstatd-team", logger=logging.getLogger("kcteam-test"), data_dir=str(tmp_path / "svc"))
    svc = service.Service(ctx, manager=mgr, work_root=tmp_path / "work", tick_s=60)
    svc.runs[run.rid] = run
    return svc


F032 = {"check": "build", "tool": "gcc", "location": "cmake/tc.cmake:1", "decision": "fix", "evidence": "build",
        "behaviour": False, "cites": ["[CC1-PN §7.2]"], "role": "dev", "paths": ["cmake/tc.cmake"],
        "note": "工具链文件要设 CMAKE_SYSROOT", "by": "王工", "continue": False}
F033 = {"check": "unit", "tool": "ThreadSanitizer", "location": "src/a.cpp:90", "decision": "fix", "evidence": "unit-test",
        "behaviour": True, "facts": ["RES-THREADS"], "cites": ["[VSTATD-IF p.11 §8.4]"], "role": "dev",
        "paths": ["src/a.*", "tests/test_a.cpp"], "note": "共享信号表加锁", "by": "王工"}


def test_two_findings_are_registered_then_the_role_gets_a_fix_round_naming_them(tmp_path, monkeypatch):
    bench, mgr, run, path = held_run(tmp_path, monkeypatch)
    svc = svc_of(tmp_path, run, mgr)
    before, session = len(mgr.continued), run.lane("dev")["conv"]

    async def go():
        first = await svc.finding(run.rid, handlers.finding_body(F032))
        assert first["id"] == "F-032" and first["held"] is True and first["status"] == "failed"
        assert run.s["tests"]["held"] and len(mgr.continued) == before  # recorded only: still held for the person
        t = json.loads(path.read_text(encoding="utf-8"))
        assert t["findings"][-1] == {"id": "F-032", "decision": "fix", "evidence": "build", "behaviour": False,
                                     "cites": ["[CC1-PN §7.2]"], "note": "工具链文件要设 CMAKE_SYSROOT",
                                     "added": {"found_by": "checks/build.sh", "tool": "gcc", "location": "cmake/tc.cmake:1"}}

        second = await svc.finding(run.rid, handlers.finding_body(F033))  # continue defaults to true
        assert second["id"] == "F-033" and second["held"] is False and second["status"] not in ("failed", "done", "stopped")
        t = json.loads(path.read_text(encoding="utf-8"))
        assert [f["id"] for f in t["findings"][-3:]] == ["F-031", "F-032", "F-033"] and t["base"] == run.s["base"]
        assert second["triage_sha256"] == (path.parent / "triage.json.sha256").read_text().strip() == run.s["triage"]["sha256"]
        _, problems = common().load_triage(path)  # the checks' own reading of the approved triage
        assert problems == []

        conv, _, task, _ = mgr.continued[-1]
        assert session and conv == session  # its own session, continued
        assert len(mgr.continued) == before + 1 and mgr.role_of(mgr.agents[mgr.continued[-1][1]]) == "dev"
        assert "F-032（build 发现，修复，证据 build）：cmake/tc.cmake:1" in task and "F-033（unit 发现" in task
        assert BUILD_REASON in task and TSAN_REASON in task
        assert "`cmake/tc.cmake`、`tests/test_a.cpp`" in task  # the paths added for it
        assert "F-032、F-033（behaviour 为 true，再写事实条目 RES-THREADS）" in task
        assert "F-033 的证据是单元测试" in task
        assert run.s["tests"]["granted"] == {"build": 1, "unit": 1} and run.s["tests"]["rounds"] == {"build": 2, "unit": 2}
        assert run.roles["dev"]["writable"] == ["src/a.*", "cmake/tc.cmake", "tests/test_a.cpp"]
        assert run.test_writers == []  # a test file a person gave it does not make the developer the test writer

        # the scope a person added holds at the merge: no violation, the files reach the run branch
        a = mgr.agents[mgr.continued[-1][1]]
        act(a, {"cmake/tc.cmake": "set(CMAKE_SYSROOT /opt/cc1-sysroot)\n", "tests/test_a.cpp": "// F-033\n",
                "src/a.cpp": "// fixed\n"}, msg="[dev] F-032 F-033 RES-THREADS")
        bench.set("build", 0)
        bench.set("unit", 0)
        finish(a, "修好了")
        end = time.monotonic() + 30
        while not run.ended and time.monotonic() < end:
            await run.tick()
            for x in mgr.live():
                work(x, mgr.role_of(x))
            await asyncio.sleep(0.05)
        assert run.s["status"] == "done", run.events[-1]["text"]
        assert run.lane("dev")["violations"] == []
        assert sh(Path(run.s["run_wt"]), "show", "HEAD:cmake/tc.cmake").startswith("set(CMAKE_SYSROOT")

    asyncio.run(go())
    again = reload(tmp_path, mgr, checks.run_checks)  # persisted with the run
    assert again.roles["dev"]["writable"] == ["src/a.*", "cmake/tc.cmake", "tests/test_a.cpp"]


def test_extending_a_finding_added_already_gives_its_role_paths_and_a_round_without_a_new_finding(tmp_path, monkeypatch):
    _, mgr, run, path = held_run(tmp_path, monkeypatch)
    svc = svc_of(tmp_path, run, mgr)

    async def go():
        await svc.finding(run.rid, handlers.finding_body({**F032, "location": "src/a.cpp:12", "paths": ["src/a.cpp"]}))
        sha, before = path.read_bytes(), len(mgr.continued)
        out = await svc.finding(run.rid, handlers.finding_body(
            {"extend": "F-032", "role": "dev", "paths": ["cmake/tc.cmake"], "note": "根因在工具链文件", "by": "王工"}))
        assert out["id"] == "F-032" and out["held"] is False
        assert path.read_bytes() == sha  # no new finding in the triage
        assert run.roles["dev"]["writable"] == ["src/a.*", "src/a.cpp", "cmake/tc.cmake"]
        assert run.s["tests"]["granted"] == {"build": 1}
        task = mgr.continued[-1][2]
        assert len(mgr.continued) == before + 1 and "F-032（build 发现" in task and "`cmake/tc.cmake`" in task and "根因在工具链文件" in task
        entry = [e for e in audit.build(run.s, list(run.events), [])["entries"] if "加可写路径" in e["what"]]
        assert len(entry) == 1 and entry[0]["actor"] == "person" and entry[0]["evidence"] == "F-032 检查 build 交给 dev 可写 cmake/tc.cmake"

    asyncio.run(go())


def test_the_app_proposes_the_files_the_role_said_it_cannot_change_and_the_test_file_of_a_unit_test_finding(tmp_path, monkeypatch):
    _, mgr, run, _ = held_run(tmp_path, monkeypatch)
    svc = svc_of(tmp_path, run, mgr)
    wt = Path(run.s["run_wt"])
    for p in ("cmake/tc.cmake", "tests/test_a.cpp"):
        (wt / p).parent.mkdir(parents=True, exist_ok=True)
        (wt / p).write_text("x\n")

    async def go():
        await svc.finding(run.rid, handlers.finding_body({**F032, "location": "src/a.cpp:12", "paths": ["src/a.cpp"]}))
        await svc.finding(run.rid, handlers.finding_body({**F032, "location": "src/a.cpp:12", "paths": []}))
        await svc.finding(run.rid, handlers.finding_body({**F033, "paths": ["src/a.*"], "continue": False}))
    asyncio.run(go())
    assert run.path_suggestions() == []  # the role said nothing yet, and no check wants a test naming one
    run.lane("dev")["attempts"].append({**run.lane("dev")["attempts"][-1], "reply": "F-032~F-033 的根因在 `cmake/tc.cmake`,这个文件不归我改。`CMakeLists.txt:46` 推测同样会失败。"})
    unit = next(r for r in run.s["tests"]["checks"] if r["name"] == "unit")
    unit["reasons"] = ["F-034: triaged as fix with evidence unit-test, but no test that is new or changed in the batch and runs names it (TR §4.1)"]
    assert run.path_suggestions() == [
        {"extend": "F-032", "check": "build", "role": "dev", "paths": ["cmake/tc.cmake"],
         "note": "dev说根因在 cmake/tc.cmake，这些它改不了。F-033 和 F-032 是同一个失败，提交说明一并写上 F-032、F-033"},
        {"extend": "F-034", "check": "unit", "role": "dev", "paths": ["tests/test_a.cpp"],
         "note": "F-034 的证据是单元测试，还没有测试写它的编号（TR §4.1）：在 tests/test_a.cpp 里加"}]
    held = svc.board(run.rid)["run"]["tests"]["held"]
    assert [s["extend"] for s in held["suggest"]] == ["F-032", "F-034"]


def test_extending_refuses_an_id_not_added_by_a_check(tmp_path, monkeypatch):
    _, mgr, run, _ = held_run(tmp_path, monkeypatch)
    svc = svc_of(tmp_path, run, mgr)

    async def go():
        for fid, why in (("F-099", "没有补登过的 F-099"), ("F-031", "不是检查发现的")):
            with pytest.raises(httpkit.AppError) as e:
                await svc.finding(run.rid, handlers.finding_body({"extend": fid, "role": "dev", "paths": ["x.cmake"], "by": "王工"}))
            assert e.value.status == 400 and why in str(e.value)
        assert run.s["tests"]["held"]

    asyncio.run(go())
    for bad in ({"extend": "32", "role": "dev", "paths": ["x"], "by": "王工"}, {"extend": "F-032", "role": "dev", "paths": [], "by": "王工"}):
        with pytest.raises(httpkit.AppError):
            handlers.finding_body(bad)


def test_the_audit_shows_the_registration_as_a_person_action(tmp_path, monkeypatch):
    _, mgr, run, _ = held_run(tmp_path, monkeypatch)
    asyncio.run(svc_of(tmp_path, run, mgr).finding(run.rid, handlers.finding_body(F032)))
    entry = [e for e in audit.build(run.s, list(run.events), [])["entries"] if "F-032" in e["what"]]
    assert len(entry) == 1 and entry[0]["actor"] == "person" and entry[0]["who"] == "王工" and entry[0]["step"] == "before"
    assert entry[0]["evidence"] == "F-032 检查 build 交给 dev 可写 cmake/tc.cmake"
    assert "工具链文件要设 CMAKE_SYSROOT" in entry[0]["what"]


def test_a_finding_the_triage_rules_refuse_comes_back_with_its_problems_and_changes_nothing(tmp_path, monkeypatch):
    _, mgr, run, path = held_run(tmp_path, monkeypatch)
    svc, sha = svc_of(tmp_path, run, mgr), path.read_bytes()

    async def go():
        body = handlers.finding_body({**F033, "facts": [], "cites": ["[VSTATD-IF §8.4]"]})
        with pytest.raises(httpkit.AppError) as e:
            await svc.finding(run.rid, body)
        assert e.value.status == 400 and e.value.code == "triage_problems"
        assert any("要写页码" in p for p in e.value.extra["problems"])
        assert any("事实条目" in p for p in e.value.extra["problems"])
        assert path.read_bytes() == sha and run.roles["dev"]["writable"] == ["src/a.*"] and run.s["tests"]["held"]
        with pytest.raises(httpkit.AppError) as e:
            await svc.finding(run.rid, handlers.finding_body({**F032, "role": "reviewer"}))
        assert e.value.status == 400 and "不是做实现的角色" in str(e.value)

    asyncio.run(go())
    for bad in ({**F032, "decision": "maybe"}, {**F032, "paths": ["../etc/x"]}, {**F032, "by": ""}, {**F032, "continue": "yes"}):
        with pytest.raises(httpkit.AppError):
            handlers.finding_body(bad)


def test_a_run_not_held_after_the_checks_refuses_with_409(tmp_path, monkeypatch):
    bench, mgr, run = make(tmp_path, monkeypatch, {"name": "build", "owner": "dev"})
    run.team["roles"][2]["triage"] = {"file": "docs/triage.json", "knowledge": str(KNOWLEDGE)}

    async def go():
        while not run.ended:
            await run.tick()
            for a in mgr.live():
                work(a, mgr.role_of(a))
            await asyncio.sleep(0.05)
        assert run.s["status"] == "done"
        approved_triage(run)
        with pytest.raises(httpkit.AppError) as e:
            await svc_of(tmp_path, run, mgr).finding(run.rid, handlers.finding_body(F032))
        assert e.value.status == 409 and e.value.code == "not_held"

    asyncio.run(go())
