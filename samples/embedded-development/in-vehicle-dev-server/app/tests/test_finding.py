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

from http_fakes import AppRoute, FakeWeb, call, owner_check
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
        assert run.roles["dev"]["writable"] == ["src/a.*", "cmake/tc.cmake"]  # src/a.cpp: under src/a.* (#64)
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
         "note": "dev说：F-032~F-033 的根因在 cmake/tc.cmake,这个文件不归我改。F-033 和 F-032 是同一个失败，"
                 "提交说明一并写上 F-032、F-033"},
        {"extend": "F-034", "check": "unit", "role": "dev", "paths": ["tests/test_a.cpp"],
         "note": "F-034 的证据是单元测试，还没有测试写它的编号（TR §4.1）：在 tests/test_a.cpp 里加"}]
    held = svc.board(run.rid)["run"]["tests"]["held"]
    assert [s["extend"] for s in held["suggest"]] == ["F-032", "F-034"]


def unit_held(tmp_path, monkeypatch, files, reply=None):
    """A run held with a unit-test finding added for unit and no test naming it, as r11219de1 was: 测试 (dev2 here)
    owns tests/** and docs/aidlc/triage.json, *files* are in the run work tree and *reply* is the developer's last."""
    _, mgr, run, _ = held_run(tmp_path, monkeypatch)
    svc = svc_of(tmp_path, run, mgr)
    wt = Path(run.s["run_wt"])
    run.roles["dev2"].update({"title": "测试", "writable": ["src/b.*", "tests/**", "docs/aidlc/triage.json"]})
    for p in files:
        (wt / p).parent.mkdir(parents=True, exist_ok=True)
        (wt / p).write_text("x\n")
    asyncio.run(svc.finding(run.rid, handlers.finding_body({**F033, "paths": ["src/a.*"], "continue": False})))
    unit = next(r for r in run.s["tests"]["checks"] if r["name"] == "unit")
    unit["reasons"] = ["F-032: triaged as fix with evidence unit-test, but no test that is new or changed in the "
                       "batch and runs names it (TR §4.1)"]
    if reply:
        run.lane("dev")["attempts"].append({**run.lane("dev")["attempts"][-1], "reply": reply})
    return run


def test_the_test_file_of_a_unit_test_finding_is_proposed_to_the_role_that_owns_the_tests(tmp_path, monkeypatch):
    reply = ("**unit，F-032**\n- 根因在 `docs/aidlc/triage.json`，这个文件不归我改。\n"
             "- `cmake/tc.cmake` 也不归我。")
    run = unit_held(tmp_path, monkeypatch, ("tests/test_a.cpp", "docs/aidlc/triage.json", "cmake/tc.cmake"), reply)
    mine, tests = run.path_suggestions()
    assert (mine["extend"], mine["check"], mine["role"], mine["paths"]) == ("F-032", "unit", "dev", ["cmake/tc.cmake"])
    assert (tests["extend"], tests["check"], tests["role"]) == ("F-032", "unit", "dev2")
    assert tests["paths"] == ["tests/test_a.cpp"]
    assert tests["note"].endswith("在 tests/test_a.cpp 里加。这个文件本来就在测试的可改范围里，交给它一轮来写")
    # the developer is never proposed tests/** (#54): not the test file, not what it said is 测试's
    assert [p for s in run.path_suggestions() if s["role"] == "dev" for p in s["paths"]] == ["cmake/tc.cmake"]


def test_agreeing_to_the_test_file_gives_the_tester_a_round_and_the_developer_nothing(tmp_path, monkeypatch):
    run = unit_held(tmp_path, monkeypatch, ("tests/test_a.cpp",))
    mgr = run.d.manager()
    svc = svc_of(tmp_path, run, mgr)
    [s] = run.path_suggestions()
    before = len(mgr.continued)

    async def go():
        out = await svc.finding(run.rid, handlers.finding_body(
            {"extend": s["extend"], "role": s["role"], "paths": s["paths"], "note": s["note"], "by": "alice"}))
        assert out["id"] == "F-032" and out["held"] is False
    asyncio.run(go())
    rounds = {mgr.role_of(mgr.agents[a]): task for _, a, task, *_ in mgr.continued[before:]}
    assert sorted(rounds) == ["dev", "dev2"]  # dev for the finding it was given in unit_held, 测试 for the test
    task = rounds["dev2"]
    assert "你是开发团队里的「测试」" in task and "F-032（unit 发现" in task and "F-032 的证据是单元测试" in task
    assert run.roles["dev"]["writable"] == ["src/a.*"]  # the developer got no test file
    assert run.test_writers == ["dev2"]


def test_no_test_file_is_proposed_when_the_project_has_none(tmp_path, monkeypatch):
    run = unit_held(tmp_path, monkeypatch, ("docs/aidlc/triage.json",))
    assert run.path_suggestions() == []


def test_the_test_file_is_proposed_apart_from_the_ten_files_the_role_named(tmp_path, monkeypatch):
    """PROPOSED_MAX bounds what the role named; the test file is a proposal of its own, so it cannot drop it."""
    many = [f"cmake/f{i}.cmake" for i in range(11)]
    reply = "unit，F-032 的根因在 " + "、".join(f"`{p}`" for p in many) + "，都不归我改。"
    run = unit_held(tmp_path, monkeypatch, ("tests/test_a.cpp", *many), reply)
    mine, tests = run.path_suggestions()
    assert mine["role"] == "dev" and mine["paths"] == many[:10] and "tests/" not in mine["note"]
    assert tests["role"] == "dev2" and tests["paths"] == ["tests/test_a.cpp"]
    assert "在 tests/test_a.cpp 里加" in tests["note"]


def test_a_test_file_that_is_a_symlink_to_a_fenced_file_is_not_proposed(tmp_path, monkeypatch):
    """Passes on main too, where a path in another role's scope is never proposed. It matters here: the test file
    goes to the role whose scope has it, and only the fence on what the path resolves to keeps this one out."""
    run = unit_held(tmp_path, monkeypatch, ("mcp/build/core.py",))
    wt = Path(run.s["run_wt"])
    (wt / "tests").mkdir(parents=True, exist_ok=True)
    (wt / "tests" / "test_a.cpp").symlink_to(wt / "mcp" / "build" / "core.py")
    assert run.path_suggestions() == []  # FENCED by what the path resolves to, not only by what it says


def test_a_person_may_not_give_a_role_a_symlink_that_resolves_to_a_fenced_file(tmp_path, monkeypatch):
    _, mgr, run, path = held_run(tmp_path, monkeypatch)
    svc, sha = svc_of(tmp_path, run, mgr), path.read_bytes()
    wt = Path(run.s["run_wt"])
    (wt / "mcp" / "build").mkdir(parents=True, exist_ok=True)
    (wt / "mcp" / "build" / "core.py").write_text("x\n")
    (wt / "tests").mkdir(parents=True, exist_ok=True)
    (wt / "tests" / "test_a.cpp").symlink_to(wt / "mcp" / "build" / "core.py")

    async def go():
        with pytest.raises(httpkit.AppError) as e:
            await svc.finding(run.rid, handlers.finding_body({**F032, "paths": ["tests/test_a.cpp"]}))
        assert e.value.status == 400 and "不能交给角色" in str(e.value)
        assert path.read_bytes() == sha and run.roles["dev"]["writable"] == ["src/a.*"] and run.s["tests"]["held"]

    asyncio.run(go())


def test_a_person_may_not_give_a_role_a_symlink_that_resolves_outside_the_work_tree(tmp_path, monkeypatch):
    _, mgr, run, path = held_run(tmp_path, monkeypatch)
    svc, sha = svc_of(tmp_path, run, mgr), path.read_bytes()
    outside = tmp_path / "source-repo" / "checks" / "unit.sh"  # the source repo's own checks, say
    outside.parent.mkdir(parents=True)
    outside.write_text("x\n")
    (Path(run.s["run_wt"]) / "src" / "link.sh").symlink_to(outside)

    async def go():
        with pytest.raises(httpkit.AppError) as e:
            await svc.finding(run.rid, handlers.finding_body({**F032, "paths": ["src/link.sh"]}))
        assert e.value.status == 400 and "src/link.sh" in str(e.value)
        assert path.read_bytes() == sha and run.roles["dev"]["writable"] == ["src/a.*"] and run.s["tests"]["held"]

    asyncio.run(go())


def test_a_symlink_loop_is_refused_by_the_route_not_answered_with_a_500(tmp_path, monkeypatch):
    """From #64: a symbolic link loop raised RuntimeError in Path.resolve() on Python 3.12 and before, which
    resolves_fenced did not catch, so POST /runs/{rid}/finding answered 500; Python 3.13 leaves the loop unresolved
    and the path was given to the role. Either way it leads nowhere a role may be given: refused, nothing changed."""
    _, mgr, run, path = held_run(tmp_path, monkeypatch)
    svc, sha = svc_of(tmp_path, run, mgr), path.read_bytes()
    routes = handlers.build_routes(svc, AppRoute, web=FakeWeb, is_owner=owner_check)
    src = Path(run.s["run_wt"]) / "src"
    (src / "loop-a.sh").symlink_to(src / "loop-b.sh")
    (src / "loop-b.sh").symlink_to(src / "loop-a.sh")

    async def go():
        r = await call(routes, "POST", f"/runs/{run.rid}/finding", json_body={**F032, "paths": ["src/loop-a.sh"]})
        assert (r.status, r.body.get("code")) == (400, "invalid_finding"), r.body
        assert "src/loop-a.sh" in r.body["error"]
        assert path.read_bytes() == sha and run.roles["dev"]["writable"] == ["src/a.*"] and run.s["tests"]["held"]

    asyncio.run(go())


def test_a_symlink_loop_in_a_middle_part_of_a_path_or_glob_is_refused_too(tmp_path, monkeypatch):
    """From the review of #67: Python 3.13 left a loop unresolved only at the last part, so src/la/x.cpp and
    src/la/*.cpp (src/la a loop) were given to the role. A loop in any part is refused on every Python version."""
    _, mgr, run, path = held_run(tmp_path, monkeypatch)
    svc, sha = svc_of(tmp_path, run, mgr), path.read_bytes()
    routes = handlers.build_routes(svc, AppRoute, web=FakeWeb, is_owner=owner_check)
    src = Path(run.s["run_wt"]) / "src"
    (src / "la").symlink_to(src / "lb")
    (src / "lb").symlink_to(src / "la")

    async def go():
        for p in ("src/la/x.cpp", "src/la/*.cpp"):
            r = await call(routes, "POST", f"/runs/{run.rid}/finding", json_body={**F032, "paths": [p]})
            assert (r.status, r.body.get("code")) == (400, "invalid_finding"), (p, r.body)
            assert p in r.body["error"]
            assert path.read_bytes() == sha and run.roles["dev"]["writable"] == ["src/a.*"] and run.s["tests"]["held"]

    asyncio.run(go())


# As a role wrote it in r1117e6af: the finding in the paragraph's heading, the file in other sentences of it, and
# "不在我能改的文件里" / "加进我的可改范围" rather than 不归我.
SAID_1117 = ("我修了 `SignalTable::get()` 的数据竞争，build 仍然没有修好。\n\n"
             "**未修：build，F-032**\n"
             "- 真正的原因是 `cmake/tc.cmake` 没有设 `CMAKE_SYSROOT`。\n"
             "- 样例里 `docs/fix.md:126` 的修法是加一行。\n"
             "- 需要有人把 `cmake/tc.cmake` 加进我的可改范围，提交说明里写 F-032。\n\n"
             "**另外**\n- `unit` 里还有两条原因：`tests/test_a.cpp:32` 不归我，`src/a.cpp` 我能改，"
             "`cmake/gone.cmake` 不存在，`../out/x.cmake` 不在仓库里。`cmake/link.cmake` 也不归我。")


def test_the_proposal_finds_the_file_in_the_findings_paragraph_and_quotes_the_role(tmp_path, monkeypatch):
    _, mgr, run, _ = held_run(tmp_path, monkeypatch)
    svc = svc_of(tmp_path, run, mgr)
    wt = Path(run.s["run_wt"])
    for p in ("cmake/tc.cmake", "tests/test_a.cpp", "docs/fix.md"):
        (wt / p).parent.mkdir(parents=True, exist_ok=True)
        (wt / p).write_text("x\n")

    async def go():
        await svc.finding(run.rid, handlers.finding_body({**F032, "location": "src/a.cpp:12", "paths": ["src/a.cpp"],
                                                          "continue": False}))
    asyncio.run(go())
    run.lane("dev")["attempts"].append({**run.lane("dev")["attempts"][-1], "reply": SAID_1117})
    assert run.path_suggestions() == [
        {"extend": "F-032", "check": "build", "role": "dev", "paths": ["cmake/tc.cmake"],
         "note": "dev说：真正的原因是 cmake/tc.cmake 没有设 CMAKE_SYSROOT"}]


def test_a_new_finding_is_filled_in_with_the_files_the_role_said_for_its_check(tmp_path, monkeypatch):
    _, mgr, run, _ = held_run(tmp_path, monkeypatch)
    svc = svc_of(tmp_path, run, mgr)
    wt = Path(run.s["run_wt"])
    for p in ("cmake/tc.cmake", "tests/test_a.cpp", "docs/fix.md"):
        (wt / p).parent.mkdir(parents=True, exist_ok=True)
        (wt / p).write_text("x\n")
    (wt.parent / "out").mkdir(exist_ok=True)
    (wt.parent / "out" / "x.cmake").write_text("x\n")
    (wt / "cmake" / "link.cmake").symlink_to(wt.parent / "out" / "x.cmake")  # a file, but out of the project
    assert run.finding_prefill() == []  # the role said nothing yet: the dialog is as before
    run.lane("dev")["attempts"].append({**run.lane("dev")["attempts"][-1], "reply": SAID_1117})
    # in the project, outside dev's src/a.*, said in a sentence about the cause; per check, by its paragraph
    assert run.finding_prefill() == [
        {"check": "build", "role": "dev", "paths": ["cmake/tc.cmake"],
         "note": "dev说：真正的原因是 cmake/tc.cmake 没有设 CMAKE_SYSROOT"},
        {"check": "unit", "role": "dev", "paths": ["tests/test_a.cpp"],
         "note": "dev说：unit 里还有两条原因：tests/test_a.cpp:32 不归我，src/a.cpp 我能改，cmake/gone.cmake 不存在，"
                 "../out/x.cmake 不在仓库里"}]
    assert svc.board(run.rid)["run"]["tests"]["held"]["prefill"][0]["paths"] == ["cmake/tc.cmake"]


def proposals(tmp_path, monkeypatch, reply, files=()):
    """A run held with F-032 added for build, the files in its run work tree and *reply* the developer's last: what
    the board proposes for F-032 (给已补登的发现加路径) and fills in for each check (补登发现)."""
    _, mgr, run, _ = held_run(tmp_path, monkeypatch)
    wt = Path(run.s["run_wt"])
    for p in ("cmake/tc.cmake", "cmake/other.cmake", *files):
        (wt / p).parent.mkdir(parents=True, exist_ok=True)
        (wt / p).write_text("x\n")
    asyncio.run(svc_of(tmp_path, run, mgr).finding(run.rid, handlers.finding_body(
        {**F032, "location": "src/a.cpp:12", "paths": ["src/a.cpp"], "continue": False})))
    run.lane("dev")["attempts"].append({**run.lane("dev")["attempts"][-1], "reply": reply})
    return ({s["check"]: s["paths"] for s in run.path_suggestions()},
            {s["check"]: s["paths"] for s in run.finding_prefill()})


FENCED = ("checks/build.sh", "mcp/build/core.py", "bench/cc1.sh", "docs/aidlc/decisions.md", "src/b.cpp")


def test_the_proposal_never_offers_the_checks_the_servers_the_bench_the_decisions_or_another_roles_files(
        tmp_path, monkeypatch):
    reply = ("**build，F-032**\n- F-032 改不了：`checks/build.sh` 把阈值写死了，`mcp/build/core.py` 也是。\n"
             "- 根因在 `bench/cc1.sh`、`docs/aidlc/decisions.md` 和 `src/b.cpp`，不归我。\n"
             "- 真正的原因是 `cmake/tc.cmake`。")
    suggest, prefill = proposals(tmp_path, monkeypatch, reply, FENCED)  # src/b.cpp is dev2's
    assert suggest == {"build": ["cmake/tc.cmake"]} and prefill == {"build": ["cmake/tc.cmake"]}


def test_a_person_may_not_give_a_role_the_checks_the_servers_the_bench_or_the_decisions(tmp_path, monkeypatch):
    _, mgr, run, path = held_run(tmp_path, monkeypatch)
    svc, sha = svc_of(tmp_path, run, mgr), path.read_bytes()

    async def go():
        for paths in (["checks/build.sh"], ["cmake/tc.cmake", "mcp/**"], ["bench/"], [".kiro/settings/cli.json"],
                      ["docs/aidlc/decisions.md"], ["docs/**"], ["**/*.sh"], ["*/build.sh"]):
            with pytest.raises(httpkit.AppError) as e:
                await svc.finding(run.rid, handlers.finding_body({**F032, "paths": paths}))
            assert e.value.status == 400 and "不能交给角色" in str(e.value), paths
        assert path.read_bytes() == sha and run.roles["dev"]["writable"] == ["src/a.*"] and run.s["tests"]["held"]
        # another role's file, typed by the person, is the person's call (TR §4.1: a test for a developer's finding)
        await svc.finding(run.rid, handlers.finding_body({**F032, "paths": ["src/b.cpp", "docs/fix.md", "cmake/*"]}))
        assert run.roles["dev"]["writable"] == ["src/a.*", "src/b.cpp", "docs/fix.md", "cmake/*"]
        with pytest.raises(httpkit.AppError) as e:  # nor by extending a finding added already
            await svc.finding(run.rid, handlers.finding_body(
                {"extend": "F-032", "role": "dev", "paths": ["checks/lib/common.py"], "by": "王工"}))
        assert e.value.status == 400 and e.value.extra.get("detail") == "checks/lib/common.py"

    asyncio.run(go())


def test_a_path_goes_only_to_the_finding_or_check_named_nearest_before_it(tmp_path, monkeypatch):
    reply = ("**F-032**\n- 根因在 `cmake/tc.cmake`\n**F-099**\n- 根因在 `cmake/other.cmake`\n\n"
             "F-032 和 F-040 都没修好：F-040 的根因在 `cmake/x.cmake`。\n\n"
             "## unit\n- 根因在 `cmake/u.cmake`\n### build\n- 根因在 `cmake/b.cmake`")
    suggest, prefill = proposals(tmp_path, monkeypatch, reply, ("cmake/x.cmake", "cmake/u.cmake", "cmake/b.cmake"))
    assert suggest == {"build": ["cmake/tc.cmake"]}
    assert prefill == {"unit": ["cmake/u.cmake"], "build": ["cmake/b.cmake"]}


def test_a_fenced_code_block_in_a_reply_is_not_read(tmp_path, monkeypatch):
    reply = ("F-032 的根因在 `cmake/tc.cmake`。\n\n```sh\n# F-032 根因在 cmake/other.cmake\n\n"
             "# build 根因在 cmake/x.cmake\n```\n\n~~~\nbuild 根因在 cmake/y.cmake\n~~~")
    suggest, prefill = proposals(tmp_path, monkeypatch, reply, ("cmake/x.cmake", "cmake/y.cmake"))
    assert suggest == {"build": ["cmake/tc.cmake"]} and prefill == {}


def test_a_path_said_not_to_be_the_cause_is_left_out_and_at_most_ten_are_proposed(tmp_path, monkeypatch):
    many = [f"cmake/m{i}.cmake" for i in range(12)]
    reply = ("build，F-032：根因不在 `cmake/tc.cmake`，在 `cmake/other.cmake`；根因也不是 cmake/x.cmake。\n\n"
             "F-032 的根因在 " + "、".join(f"`{p}`" for p in many))
    suggest, _ = proposals(tmp_path, monkeypatch, reply, ("cmake/x.cmake", *many))
    assert suggest == {"build": ["cmake/other.cmake", *many[:9]]}


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


def test_a_refused_finding_passes_on_only_what_came_from_the_request_as_detail(tmp_path, monkeypatch):
    """invalid_finding: the check, the role or the finding the request named (from outside the app) is the detail
    the English board shows; the app's own Chinese reason is not in it."""
    import re
    cjk = re.compile(r"[\u3400-\u9fff\uff00-\uffef]")
    _, mgr, run, _ = held_run(tmp_path, monkeypatch)
    svc = svc_of(tmp_path, run, mgr)

    async def refused(body):
        with pytest.raises(httpkit.AppError) as e:
            await svc.finding(run.rid, handlers.finding_body(body))
        assert e.value.code == "invalid_finding"
        return e.value.extra.get("detail")

    async def go():
        assert await refused({**F032, "check": "no-such-check"}) == "no-such-check"
        assert await refused({**F032, "role": "reviewer"}) == "reviewer"
        assert await refused({"extend": "F-099", "role": "dev", "paths": ["src/b.*"], "by": "王工"}) == "F-099"
        for body in ({**F032, "check": "no-such-check"}, {**F032, "role": "reviewer"}):
            assert not cjk.search(await refused(body))
    asyncio.run(go())


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
        assert "detail" not in e.value.extra  # the app's own reason: said by its code in English, nothing passed on

    asyncio.run(go())


def test_a_fix_that_cites_an_id_the_triage_lacks_is_held_for_a_person_not_sent_back(tmp_path, monkeypatch):
    """The checks send dev back; it fixes the defect and cites F-032, which the triage does not have yet. The run is
    held for a person to register it (D15) instead of spending dev's rounds on its commit messages; once it is
    registered, the same commit passes trace.sh and is merged."""
    bench, mgr, run = make(tmp_path, monkeypatch, {"name": "build", "owner": "dev", "rounds": 3})
    run.team["roles"][2]["triage"] = {"file": "docs/triage.json", "knowledge": str(KNOWLEDGE)}
    bench.set("build", 1, [BUILD_REASON])
    svc = svc_of(tmp_path, run, mgr)

    async def tick_until(cond, dev_works=True):
        end = time.monotonic() + 30
        while not cond() and time.monotonic() < end:
            await run.tick()
            for a in mgr.live():
                if mgr.role_of(a) != "dev" or (dev_works and run.lane("dev")["attempts"][-1]["kind"] != "fix"):
                    work(a, mgr.role_of(a))  # dev's fix rounds are the test's own
            await asyncio.sleep(0.05)
        assert cond(), run.events[-1]["text"]

    async def go():
        await tick_until(lambda: run.s["tests"].get("rounds") == {"build": 1})  # dev is sent back by the build check
        approved_triage(run)
        run.s["triage"]["base_set"] = True  # from here on every commit cites a finding (D13)
        fix = run.lane("dev")["attempts"][-1]
        assert fix["kind"] == "fix"
        a = mgr.agents[fix["agent"]]
        act(a, {"src/a.cpp": "// sysroot set\n"}, msg="[dev] F-032: set CMAKE_SYSROOT (new defect, TR §4.4)")
        finish(a, "修好了，F-032 要补登")
        await tick_until(lambda: run.ended, dev_works=False)
        held = run.s["tests"]["held"]
        assert run.s["status"] == "failed" and held["unregistered"] == ["F-032"] and held["checks"] == ["build"]
        assert "要人按 TR §4.4 补登" in held["why"] and "F-032" in held["why"]
        assert [x["kind"] for x in run.lane("dev")["attempts"]] == ["work", "fix"]  # no trace round spent
        assert not any(e.get("code") == "bounce.trace" for e in run.events)

        body = {**F032, "location": "src/a.cpp:12", "paths": ["src/a.*"], "continue": True}
        reg = await svc.finding(run.rid, handlers.finding_body(body))
        assert reg["id"] == "F-032" and reg["held"] is False
        b = mgr.agents[run.lane("dev")["attempts"][-1]["agent"]]
        bench.set("build", 0)
        finish(b, "上一轮的提交已经修了，写的就是 F-032")  # nothing new: the commit it made cites F-032 now in the triage
        await tick_until(lambda: run.ended)
        assert run.s["status"] == "done", run.events[-1]["text"]
        assert [x["kind"] for x in run.lane("dev")["attempts"]] == ["work", "fix", "fix"]
        assert "sysroot set" in sh(Path(run.s["run_wt"]), "show", "HEAD:src/a.cpp")

    asyncio.run(go())


# --- #64: follow-ups from the review of #59 ---------------------------------------------------------------------- #

def test_a_path_the_roles_scope_covers_already_is_not_added_again(tmp_path, monkeypatch):
    """register_finding compared a path to the scope's globs literally: tests/test_a.cpp was added to a tester that
    has tests/**, and its task said its scope had grown while the proposal said the file was its already."""
    run = unit_held(tmp_path, monkeypatch, ("tests/test_a.cpp",))
    mgr = run.d.manager()
    svc = svc_of(tmp_path, run, mgr)
    [s] = run.path_suggestions()
    assert s["role"] == "dev2" and "本来就在测试的可改范围里" in s["note"]
    before = len(mgr.continued)

    async def go():
        await svc.finding(run.rid, handlers.finding_body(
            {"extend": s["extend"], "role": s["role"], "paths": s["paths"], "note": s["note"], "by": "alice"}))
    asyncio.run(go())
    assert run.roles["dev2"]["writable"] == ["src/b.*", "tests/**", "docs/aidlc/triage.json"]
    assert run.s["tests"]["held"] is None
    [task] = [t for _, a, t, *_ in mgr.continued[before:] if mgr.role_of(mgr.agents[a]) == "dev2"]
    assert "你的可写范围加了" not in task


def test_a_glob_asked_for_is_added_unless_the_scope_has_it_as_written(tmp_path, monkeypatch):
    """A glob is compared as written: src/** is wider than the scope's src/a.*, so it is added; a file under src/a.*
    is not."""
    _, mgr, run, _ = held_run(tmp_path, monkeypatch)
    svc = svc_of(tmp_path, run, mgr)

    async def go():
        await svc.finding(run.rid, handlers.finding_body({**F032, "paths": ["src/a.cpp", "src/**", "src/a.*"]}))
    asyncio.run(go())
    assert run.roles["dev"]["writable"] == ["src/a.*", "src/**"]
    assert run.s["tests"]["held"]["registered"][-1]["added_paths"] == ["src/**"]


def test_the_refusal_of_a_test_writer_says_it_is_accepted_when_adding_paths(tmp_path, monkeypatch):
    run = unit_held(tmp_path, monkeypatch, ())
    svc = svc_of(tmp_path, run, run.d.manager())

    async def go():
        with pytest.raises(httpkit.AppError) as e:  # a new finding: an implementing role only
            await svc.finding(run.rid, handlers.finding_body({**F032, "role": "dev2"}))
        assert e.value.status == 400 and "dev2 不是做实现的角色" in str(e.value)
        assert "写测试的角色（dev2）只能在给已补登的发现加路径（extend）时选" in str(e.value)

    asyncio.run(go())


def test_a_glob_is_fenced_by_what_it_matches_in_the_work_tree_not_only_by_what_it_says(tmp_path, monkeypatch):
    """fenced() judged a glob by its own text and a plain path by what it resolves to: src/* reached src/x, a
    symlink to mcp/ or out of the work tree, unseen. It is a guard, so a glob is refused when anything it matches
    resolves there."""
    _, mgr, run, path = held_run(tmp_path, monkeypatch)
    svc, sha = svc_of(tmp_path, run, mgr), path.read_bytes()
    wt = Path(run.s["run_wt"])
    (wt / "mcp" / "build").mkdir(parents=True, exist_ok=True)
    (wt / "mcp" / "build" / "core.py").write_text("x\n")
    (wt / "src" / "deep").mkdir(parents=True, exist_ok=True)
    (wt / "src" / "deep" / "srv").symlink_to(wt / "mcp")  # a folder link: judged itself, not walked into
    outside = tmp_path / "source-repo" / "checks"
    outside.mkdir(parents=True)
    (wt / "docs" / "notes").mkdir(parents=True, exist_ok=True)
    (wt / "docs" / "notes" / "c.sh").symlink_to(outside)
    (wt / "cmake").mkdir(exist_ok=True)
    (wt / "cmake" / "up").symlink_to(wt)  # the work tree itself: checks/ is below it
    team = mod("team")
    assert team.fenced(["src/**", "src/deep/*", "docs/notes/", "docs/*/c.?h", "cmake/u?"], wt) == [
        "src/**", "src/deep/*", "docs/notes/", "docs/*/c.?h", "cmake/u?"]
    assert team.fenced(["src/a.*", "src/*", "docs/*.md"], wt) == []  # nothing they match leads out

    async def go():
        with pytest.raises(httpkit.AppError) as e:
            await svc.finding(run.rid, handlers.finding_body({**F032, "paths": ["src/deep/*"]}))
        assert e.value.status == 400 and "不能交给角色" in str(e.value) and "src/deep/*" in str(e.value)
        assert path.read_bytes() == sha and run.roles["dev"]["writable"] == ["src/a.*"] and run.s["tests"]["held"]

    asyncio.run(go())


def test_a_link_in_the_literal_part_of_a_glob_is_fenced_by_where_it_leads(tmp_path, monkeypatch):
    """cmake/up/** matched nothing of the work tree and src/deep/srv/ lost its / to resolve(), so a link in a glob's
    own literal part (cmake/up -> the work tree, src/deep/srv -> mcp/) reached checks/ or mcp/ unrefused."""
    _, _, run, _ = held_run(tmp_path, monkeypatch)
    wt = Path(run.s["run_wt"])
    (wt / "mcp" / "build").mkdir(parents=True, exist_ok=True)
    (wt / "src" / "deep").mkdir(parents=True, exist_ok=True)
    (wt / "src" / "deep" / "srv").symlink_to(wt / "mcp")
    (wt / "cmake").mkdir(exist_ok=True)
    (wt / "cmake" / "up").symlink_to(wt)
    (wt / "tests").mkdir(exist_ok=True)
    team = mod("team")
    reach = ["src/deep/srv/", "src/deep/srv", "src/deep/srv/**", "cmake/up/**", "cmake/up/", "cmake/up/*",
             "cmake/up/docs/aidlc/*", "c*/up/**", "src/*/srv/"]
    assert team.fenced(reach, wt) == reach
    assert team.fenced(["src/a.cpp", "src/a.*", "tests/**", "src/*", "docs/*.md"], wt) == []
