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
checks_mod = mod("checks")
service, handlers = mod("service"), mod("handlers")
SAMPLE = constants.APP_ROOT.parent  # the dev checkout: this scenario's folder


def raw_team():
    return json.loads(constants.TEAM_FILE.read_text(encoding="utf-8"))


def test_the_vstatd_team_file_has_the_six_roles_two_gates_and_the_checks():
    t = team_mod.load_team(constants.TEAM_FILE)
    roles = {r["key"]: r for r in t["roles"]}
    assert list(roles) == ["triage", "architect", "tester", "dev-fix", "dev-refactor", "reviewer"]
    assert {k: r["template"] for k, r in roles.items()} == {
        "triage": "embedded-developer-agent", "architect": "embedded-architect-agent", "tester": "embedded-quality-agent",
        "dev-fix": "embedded-developer-agent", "dev-refactor": "embedded-developer-agent",
        "reviewer": "embedded-architecture-reviewer-agent"}
    assert not any(r.get("member") for r in roles.values())  # no Crew members (D6): the sessions run the templates
    assert [k for k, r in roles.items() if r.get("gate") == "human"] == ["triage", "architect"]
    assert {r["phase"] for r in t["roles"]} == {"inception", "construction", "review"}
    assert roles["reviewer"]["writable"] == [] and set(roles["reviewer"]["depends_on"]) == {"dev-fix", "dev-refactor"}
    assert roles["tester"]["depends_on"] == ["architect"] and roles["dev-fix"]["depends_on"] == ["tester"]  # tests first
    assert t["ownership"] == {"file": "docs/aidlc/work-split.json", "from": "architect"}
    assert "也可以是 `cmake/**` 和 `CMakeLists.txt`，这两个可以分给 dev-fix" in roles["architect"]["brief"]
    assert all(roles[k]["writable"] == [team_mod.PENDING_GLOB] for k in ("dev-fix", "dev-refactor"))  # from the split
    assert "docs/aidlc/triage.json" in roles["triage"]["writable"]
    assert roles["triage"]["triage"] == {"file": "docs/aidlc/triage.json", "knowledge": "${sample}/knowledge"}
    assert all(g.startswith("docs/aidlc/") for k in ("triage", "architect") for g in roles[k]["writable"])
    assert t["source"] == "${sample}/reference-project" and "workspace" not in t
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
    assert set(t["bench"]) == {"deploy", "restart", "replay", "doctor", "build", "start", "baseline"}
    assert t["bench"]["deploy"] == ["${sample}/bench/cc1.sh", "deploy", "{artifact}"]
    assert t["bench"]["doctor"] == ["${sample}/bench/doctor.sh"] and t["bench"]["baseline"] == "~/workplace/vstatd-team/baseline"
    assert t["check_runner"]["image"] == {"arm64": "vstatd-build:arm64", "amd64": "vstatd-build:amd64"}
    assert t["check_runner"]["platform"] == {"arm64": "linux/arm64", "amd64": "linux/amd64"}
    assert "--platform" not in t["check_runner"]["docker"]  # chosen for the machine each check runs on
    assert (constants.TEAM_FILE.parent / t["task_template"]).is_file()


@pytest.mark.parametrize("change, message", [
    (lambda t: t["checks"][0].update(when="later"), "when 只能是"),
    (lambda t: t["checks"][0].update(owner="nobody"), "owner 要是一个角色的 key"),
    (lambda t: t["checks"][1].update(name="build"), "name 不对或重复了"),
    (lambda t: t["checks"][0].update(args=["project", "sysroot"]), "args 只能用"),
    (lambda t: t["checks"][0].update(command="checks/build.sh"), "command 要写成命令和参数的列表"),
    (lambda t: t["checks"][0].update(max_rounds=0), "max_rounds 要是 1 到 10 的整数"),
    (lambda t: t.pop("check_runner"), "有 checks 就要写 check_runner"),
    (lambda t: t["check_runner"]["image"].update(riscv64="x"), "image 要写成镜像名"),
    (lambda t: t["check_runner"]["image"].update(arm64=""), "image 要写成镜像名"),
    (lambda t: t["check_runner"]["platform"].pop("amd64"), "platform 要按 image 的架构写"),
    (lambda t: t["check_runner"].update(image="one-image"), "platform 要按 image 的架构写"),
    (lambda t: t["check_runner"]["docker"].extend(["--platform", "linux/amd64"]), "docker 里就不要再写 --platform"),
    (lambda t: t["bench"].update(flash=["x"]), "bench 要写成"),
    (lambda t: t["bench"].pop("doctor"), "bench 要写成"),
    (lambda t: t.update(source=""), "source 要写成要改的项目目录"),
    (lambda t: t["roles"][0]["triage"].update(file="/abs/triage.json"), "triage 要写成"),
    (lambda t: t["roles"][1].update(triage={"file": "docs/x.json", "knowledge": "/k"}, gate=None), "triage 要写成"),
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


@pytest.mark.parametrize("machine, arch", [("arm64", "arm64"), ("aarch64", "arm64"), ("x86_64", "amd64"), ("AMD64", "amd64")])
def test_the_check_runner_is_the_native_image_of_the_machine_it_runs_on(machine, arch):
    runner = raw_team()["check_runner"]
    got = checks_mod.resolve_runner(runner, machine)
    assert got["image"] == f"vstatd-build:{arch}"
    assert got["docker"] == [*runner["docker"], "--platform", f"linux/{arch}",
                             "-v", "vstatd-standin-sysroot:/opt/cc1-sysroot:ro"]
    assert runner["image"] == {"arm64": "vstatd-build:arm64", "amd64": "vstatd-build:amd64"}  # not changed
    assert runner["sysroot"] == "vstatd-standin-sysroot" and "cc1-sysroot:/opt/cc1-sysroot:ro" not in runner["docker"]
    one = {"docker": ["docker", "run", "--platform", "linux/amd64"], "image": "img"}
    assert checks_mod.resolve_runner(one, machine) is one  # one image: as the team file says
    assert checks_mod.resolve_runner({**one, "sysroot": "vol"}, machine) == {
        "docker": [*one["docker"], "-v", "vol:/opt/cc1-sysroot:ro"], "image": "img"}


def test_the_sysroot_is_one_volume_name_and_docker_mounts_nothing_else_there():
    runner = raw_team()["check_runner"]
    checks_mod._check_runner(runner)
    for bad in ("", "/opt/x", "vol:/opt/cc1-sysroot", 3):
        with pytest.raises(ValueError, match="sysroot 要写成一个 Docker 卷名"):
            checks_mod._check_runner({**runner, "sysroot": bad})
    with pytest.raises(ValueError, match="docker 里就不要再挂 /opt/cc1-sysroot"):
        checks_mod._check_runner({**runner, "docker": [*runner["docker"], "-v", "cc1-sysroot:/opt/cc1-sysroot:ro"]})


def test_a_machine_without_an_image_in_the_team_file_cannot_run_the_checks(monkeypatch):
    runner = raw_team()["check_runner"]
    with pytest.raises(ValueError, match="没有 riscv64 的镜像"):
        checks_mod.resolve_runner(runner, "riscv64")
    monkeypatch.setattr(checks_mod.platform, "machine", lambda: "riscv64")
    with pytest.raises(checks_mod.TestsUnavailable, match="没有 riscv64 的镜像"):
        checks_mod.docker_command(runner, [], ["true"])
    assert checks_mod.docker_prefix(runner, []) == ""


def test_a_run_made_with_one_image_takes_the_per_architecture_runner():
    """A run whose state has the runner from before the image was per architecture (r11037a33) uses the team file's,
    so its checks run in this machine's image too; any other runner of its own is kept."""
    current = raw_team()["check_runner"]
    old = {"docker": ["docker", "run", "--rm", "--platform", "linux/amd64", "--security-opt", "seccomp=unconfined",
                      "-v", "cc1-sysroot:/opt/cc1-sysroot:ro"], "image": "vstatd-build:amd64"}
    assert checks_mod.adopt_runner(old, current) is current
    own = {"docker": ["docker", "run"], "image": "my-build:1"}
    assert checks_mod.adopt_runner(own, current) is own
    assert checks_mod.adopt_runner(old, None) is old and checks_mod.adopt_runner(current, current) is current


def test_a_run_made_with_the_buildroot_sysroot_in_docker_takes_the_sysroot_setting():
    """A run made after the image was per architecture but with ``-v cc1-sysroot:/opt/cc1-sysroot:ro`` in docker
    (before the sysroot was a setting) uses the team file's runner and so the stand-in sysroot; a runner that differs
    in anything else is its own."""
    current = raw_team()["check_runner"]
    before = {k: v for k, v in current.items() if k != "sysroot"}
    before["docker"] = [*current["docker"], "-v", "cc1-sysroot:/opt/cc1-sysroot:ro"]
    assert checks_mod.adopt_runner(before, current) is current
    other = {**before, "docker": [*before["docker"], "--cpus", "2"]}
    assert checks_mod.adopt_runner(other, current) is other
    own = {**before, "sysroot": "my-sysroot", "docker": current["docker"]}
    assert checks_mod.adopt_runner(own, current) is own


@pytest.mark.parametrize("machine, arch", [("arm64", "arm64"), ("x86_64", "amd64")])
def test_a_run_starts_from_the_scenarios_reference_project(tmp_path, monkeypatch, machine, arch):
    """The default team: the run repository is a copy of reference-project/, and the first role (triage) gets the
    knowledge source, the build container of this machine and the sample's paths in its task."""
    monkeypatch.delenv("VSTATD_SAMPLE", raising=False)
    monkeypatch.setattr(checks_mod.platform, "machine", lambda: machine)
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
            assert (f"docker run --rm --security-opt seccomp=unconfined --platform linux/{arch} "
                    f"-v vstatd-standin-sysroot:/opt/cc1-sysroot:ro -v {wt}:{wt}:ro") in task
            assert f"-w {wt} vstatd-build:{arch} sh -c 'cmake -S . -B /tmp/build" in task
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


def test_a_stored_run_with_the_amd64_image_runs_its_checks_in_this_machines_image(tmp_path, monkeypatch):
    """A run whose state snapshots the team from before (one image, --platform linux/amd64 in docker, as r11037a33)
    takes the team file's per-architecture runner when the app starts again, and resolves it when a check starts."""
    monkeypatch.delenv("VSTATD_SAMPLE", raising=False)
    monkeypatch.setattr(checks_mod.platform, "machine", lambda: "arm64")
    data = tmp_path / "data"
    data.mkdir()
    (data / paths.SAMPLE_FILE).write_text(json.dumps({"sample": str(SAMPLE)}), encoding="utf-8")
    ctx = SimpleNamespace(name="vstatd-team", logger=logging.getLogger("kcteam-test"), data_dir=str(data))
    legacy = {"docker": ["docker", "run", "--rm", "--platform", "linux/amd64", "--security-opt", "seccomp=unconfined",
                         "-v", "cc1-sysroot:/opt/cc1-sysroot:ro"], "image": "vstatd-build:amd64"}

    async def go():
        svc = service.Service(ctx, manager=FakeManager(), work_root=tmp_path / "work", tick_s=60)
        routes = handlers.build_routes(svc, AppRoute, web=FakeWeb, is_owner=owner_check)
        await svc.start()
        try:
            r = await call(routes, "POST", "/runs", json_body={"requirement": "本批"})
            rid = r.body["run"]
        finally:
            await svc.stop()
        state_file = data / "runs" / rid / "run.json"
        state = json.loads(state_file.read_text(encoding="utf-8"))
        state["team"]["check_runner"] = legacy
        state_file.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        again = service.Service(ctx, manager=FakeManager(), work_root=tmp_path / "work", tick_s=60)
        await again.start()
        try:
            runner = again.runs[rid].team["check_runner"]
            assert runner == raw_team()["check_runner"]
            cmd = checks_mod.docker_command(runner, [], ["true"])
            assert cmd[cmd.index("--platform") + 1] == "linux/arm64" and cmd.count("--platform") == 1
            assert "vstatd-build:arm64" in cmd and "vstatd-build:amd64" not in cmd
            assert cmd[cmd.index("vstatd-standin-sysroot:/opt/cc1-sysroot:ro") - 1] == "-v"
            assert not any(w.startswith("cc1-sysroot:") for w in cmd)  # not the Buildroot sysroot (no C++ headers)
        finally:
            await again.stop()

    asyncio.run(go())
