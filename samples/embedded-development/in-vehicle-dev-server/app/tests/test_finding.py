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
