"""The vstatd team file (D6, D11) and the scenario folder it refers to (D12)."""

import asyncio
import copy
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from http_fakes import AppRoute, FakeWeb, call, owner_check
from teamkit import FakeManager, mod, sh

team_mod, paths, constants, httpkit = mod("team"), mod("paths"), mod("constants"), mod("httpkit")
service, handlers = mod("service"), mod("handlers")
SAMPLE = constants.APP_ROOT.parent  # the dev checkout: this scenario's folder


def raw_team():
    return json.loads(constants.TEAM_FILE.read_text(encoding="utf-8"))


def test_the_vstatd_team_file_has_the_six_roles_two_gates_and_the_checks():
    t = team_mod.load_team(constants.TEAM_FILE)
    roles = {r["key"]: r for r in t["roles"]}
    assert list(roles) == ["triage", "architect", "tester", "dev-fix", "dev-refactor", "reviewer"]
    assert {k: r["member"] for k, r in roles.items()} == {
        "triage": "aidlc-developer-agent", "architect": "aidlc-architect-agent", "tester": "aidlc-quality-agent",
        "dev-fix": "aidlc-developer-agent", "dev-refactor": "aidlc-developer-agent",
        "reviewer": "aidlc-architecture-reviewer-agent"}
    assert [k for k, r in roles.items() if r.get("gate") == "human"] == ["triage", "architect"]
    assert {r["phase"] for r in t["roles"]} == {"inception", "construction", "review"}
    assert roles["reviewer"]["writable"] == [] and set(roles["reviewer"]["depends_on"]) == {"dev-fix", "dev-refactor"}
    assert roles["tester"]["depends_on"] == ["architect"] and roles["dev-fix"]["depends_on"] == ["tester"]  # tests first
    assert t["ownership"] == {"file": "docs/aidlc/work-split.json", "from": "architect"}
    assert all(roles[k]["writable"] == [team_mod.PENDING_GLOB] for k in ("dev-fix", "dev-refactor"))  # from the split
    assert "docs/aidlc/triage.json" in roles["triage"]["writable"]
    assert all(g.startswith("docs/aidlc/") for k in ("triage", "architect") for g in roles[k]["writable"])
    assert t["source"] == "${sample}/reference-project" and t["workspace"] == "vstatd"
    assert t["knowledge"] == {"source": "vstatd", "data_dir": "~/workplace/vstatd"}
    checks = {c["name"]: c for c in t["checks"]}
    assert list(checks) == ["build", "static", "unit", "size", "trace", "runtime-limits", "logdiff", "release"]
    assert {n: c["max_rounds"] for n, c in checks.items()} == {
        "build": 3, "static": 2, "unit": 2, "size": 2, "trace": 2, "runtime-limits": 2, "logdiff": 2, "release": 2}
    assert [n for n, c in checks.items() if c["when"] == "after_bench"] == ["runtime-limits", "logdiff"]
    assert checks["release"]["when"] == "release" and checks["release"].get("owner") is None  # a person decides
    assert all(c["command"] == [f"${{sample}}/checks/{n}.sh"] for n, c in checks.items())
    assert {n for n, c in checks.items() if "triage" in c["args"]} == {"static", "unit", "trace", "logdiff", "release"}
    assert checks["logdiff"]["args"] == ["run", "baseline", "triage"]
    assert set(t["bench"]) == {"deploy", "restart", "replay"} and t["bench"]["deploy"][0] == "${sample}/bench/cc1.sh"
    assert t["check_runner"]["image"] == "vstatd-build:amd64"
    assert (constants.TEAM_FILE.parent / t["task_template"]).is_file()


@pytest.mark.parametrize("change, message", [
    (lambda t: t["checks"][0].update(when="later"), "when 只能是"),
    (lambda t: t["checks"][0].update(owner="nobody"), "owner 要是一个角色的 key"),
    (lambda t: t["checks"][1].update(name="build"), "name 不对或重复了"),
    (lambda t: t["checks"][0].update(args=["project", "sysroot"]), "args 只能用"),
    (lambda t: t["checks"][0].update(command="checks/build.sh"), "command 要写成命令和参数的列表"),
    (lambda t: t["checks"][0].update(max_rounds=0), "max_rounds 要是 1 到 10 的整数"),
    (lambda t: t.pop("check_runner"), "有 checks 就要写 check_runner"),
    (lambda t: t["bench"].update(flash=["x"]), "bench 要写成"),
    (lambda t: t.update(source=""), "source 要写成要改的项目目录"),
])
def test_the_team_check_names_what_is_wrong(change, message):
    t = raw_team()
    change(t)
    with pytest.raises(ValueError, match=message):
        team_mod.check_team(t)


def test_a_release_check_alone_may_leave_its_owner_to_a_person():
    t = raw_team()
    t["checks"][-1]["owner"] = None
    team_mod.check_team(copy.deepcopy(t))
    t["checks"][0].pop("owner")
    with pytest.raises(ValueError, match="只有 release 的检查可以不写"):
        team_mod.check_team(t)


def test_the_sample_folder_comes_from_the_apps_data_then_the_environment_then_the_dev_checkout(tmp_path, monkeypatch):
    sample = tmp_path / "scenario"
    for d in ("checks", "reference-project"):
        (sample / d).mkdir(parents=True)
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.delenv("VSTATD_SAMPLE", raising=False)
    assert paths.sample_dir(data) == SAMPLE  # nothing recorded: the dev checkout
    monkeypatch.setenv("VSTATD_SAMPLE", str(sample))
    assert paths.sample_dir(data) == sample
    other = tmp_path / "other"
    for d in ("checks", "reference-project"):
        (other / d).mkdir(parents=True)
    (data / paths.SAMPLE_FILE).write_text(json.dumps({"sample": str(other)}), encoding="utf-8")
    assert paths.sample_dir(data) == other  # what setup.sh recorded wins


def test_an_unknown_or_moved_sample_folder_is_a_clear_error(tmp_path, monkeypatch):
    monkeypatch.delenv("VSTATD_SAMPLE", raising=False)
    monkeypatch.setattr(paths, "APP_ROOT", tmp_path / "installed" / "vstatd-team")  # an installed copy: no checks/ beside it
    with pytest.raises(httpkit.AppError, match="不知道场景文件夹在哪：先运行场景的 setup.sh"):
        paths.sample_dir(tmp_path)
    moved = tmp_path / "moved"
    (moved / "checks").mkdir(parents=True)
    (tmp_path / paths.SAMPLE_FILE).write_text(json.dumps({"sample": str(moved)}), encoding="utf-8")
    with pytest.raises(httpkit.AppError, match=r"里没有 reference-project/：文件夹移动过？重新运行 setup.sh") as e:
        paths.sample_dir(tmp_path)
    assert e.value.code == "no_sample"
    (tmp_path / paths.SAMPLE_FILE).write_text(json.dumps({"sample": "relative/path"}), encoding="utf-8")
    with pytest.raises(httpkit.AppError, match="要是绝对路径"):
        paths.sample_dir(tmp_path)
    (tmp_path / paths.SAMPLE_FILE).write_text("{", encoding="utf-8")
    with pytest.raises(httpkit.AppError, match="读不了"):
        paths.sample_dir(tmp_path)


def test_sample_is_replaced_in_every_string_of_the_team():
    t = paths.expand(raw_team(), "/x/scenario")
    assert t["source"] == "/x/scenario/reference-project"
    assert t["checks"][0]["command"] == ["/x/scenario/checks/build.sh"]
    assert t["bench"]["replay"][:2] == ["/x/scenario/bench/cc1.sh", "replay"]
    assert "${sample}" not in json.dumps(t, ensure_ascii=False)
    assert paths.expand({"n": 3, "b": None, "l": [True]}, "/x") == {"n": 3, "b": None, "l": [True]}


def test_a_run_starts_from_the_scenarios_reference_project(tmp_path, monkeypatch):
    """The default team: the run repository is a copy of reference-project/, and the first role (triage) gets the
    knowledge source, the build container and the sample's paths in its task."""
    monkeypatch.delenv("VSTATD_SAMPLE", raising=False)
    data = tmp_path / "data"
    data.mkdir()
    (data / paths.SAMPLE_FILE).write_text(json.dumps({"sample": str(SAMPLE)}), encoding="utf-8")
    mgr = FakeManager()
    ctx = SimpleNamespace(name="vstatd-team", logger=logging.getLogger("kcteam-test"), data_dir=str(data))
    svc = service.Service(ctx, manager=mgr, work_root=tmp_path / "work", tick_s=60)
    routes = handlers.build_routes(svc, AppRoute, web=FakeWeb, is_owner=owner_check)

    async def go():
        await svc.start()
        try:
            r = await call(routes, "POST", "/runs", json_body={"requirement": "本批：修复待办里标了 fix 的发现，拆分 Service::run()"})
            assert r.status == 200, r.body
            run = svc.runs[r.body["run"]]
            repo = Path(run.s["repo"])
            assert (repo / "src" / "service.cpp").read_bytes() == (SAMPLE / "reference-project" / "src" / "service.cpp").read_bytes()
            assert (repo / ".clang-tidy").is_file() and not (repo / "build-host").exists()
            assert sh(repo, "log", "--format=%s").splitlines() == ["接手：本批：修复待办里标了 fix 的发现，拆分 Service::run()"]
            assert run.s["source"] == str(SAMPLE / "reference-project")
            assert run.team["checks"][0]["command"] == [str(SAMPLE / "checks" / "build.sh")]
            assert [mgr.role_of(a) for a in mgr.live()] == ["triage"]
            task = mgr.by_role("triage").task
            assert f"{SAMPLE}/checks/README.md" in task and "${sample}" not in task
            assert "知识库来源「vstatd」" in task and "[VSTATD-IF p.7 §4.1]" in task
            wt = run.lane("triage")["worktree"]
            assert f"docker run --rm --platform linux/amd64 --security-opt seccomp=unconfined -v cc1-sysroot:/opt/cc1-sysroot:ro -v {wt}:{wt}:ro" in task
            assert f"-w {wt} vstatd-build:amd64 sh -c 'cmake -S . -B /tmp/build" in task
            assert "{build_env}" not in task and "`docs/aidlc/triage.json`" in task
        finally:
            await svc.stop()

    asyncio.run(go())


def test_without_a_known_sample_folder_no_run_starts(tmp_path, monkeypatch):
    monkeypatch.delenv("VSTATD_SAMPLE", raising=False)
    monkeypatch.setattr(paths, "APP_ROOT", tmp_path / "installed")
    mgr = FakeManager()
    ctx = SimpleNamespace(name="vstatd-team", logger=logging.getLogger("kcteam-test"), data_dir=str(tmp_path / "data"))
    svc = service.Service(ctx, manager=mgr, work_root=tmp_path / "work", tick_s=60)
    routes = handlers.build_routes(svc, AppRoute, web=FakeWeb, is_owner=owner_check)

    async def go():
        await svc.start()
        try:
            r = await call(routes, "POST", "/runs", json_body={"requirement": "本批"})
            assert (r.status, r.code) == (500, "no_sample") and "setup.sh" in r.body["error"]
            assert not svc.runs and not mgr.spawned
        finally:
            await svc.stop()

    asyncio.run(go())
