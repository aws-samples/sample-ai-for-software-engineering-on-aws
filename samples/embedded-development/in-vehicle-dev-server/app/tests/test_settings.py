"""设置 (GET / POST /settings): the app's own settings.json, the dashboard owner's alone, checked before it is
saved, and what the team a run gets looks like afterwards. The servers' own configuration files are only read: this
test writes one by hand and checks that the app leaves it byte for byte as it was.
"""

import asyncio
import json
import logging
from pathlib import Path
from types import SimpleNamespace

from http_fakes import AppRoute, FakeWeb, call, owner_check
from teamkit import FakeManager, mod

service, handlers, constants, paths = mod("service"), mod("handlers"), mod("constants"), mod("paths")
settings_mod, servers_mod = mod("settings"), mod("servers")
readiness_mod = mod("readiness")
shown = mod("display").View().text  # replies write the home folder as ~ (display.py)

BUILD_TOML = """\
[paths]
workspace = "{root}/server/worktree"
state = "{root}/server/build-state"
triage = "{root}/server/triage/triage.json"
checks = "{root}/sample/checks"

[sandbox]
runner = "docker"
image = "vstatd-build"
"""

BENCH_TOML = """\
[paths]
bench = "{root}/sample/bench"
state = "{root}/server/bench-state"
baseline = "{root}/server/baseline"
triage = "{root}/server/triage/triage.json"
"""


def scenario(tmp_path, monkeypatch):
    """The app with the shipped team file, a stand-in scenario folder and both servers' configuration files."""
    sample = tmp_path / "sample"
    for d in ("checks", "reference-project", "bench"):
        (sample / d).mkdir(parents=True)
    (sample / "bench" / "console.py").write_text("", encoding="utf-8")
    team = json.loads(constants.TEAM_FILE.read_text(encoding="utf-8"))
    team_file = tmp_path / "team" / "team-vstatd.json"
    team_file.parent.mkdir()
    team_file.write_text(json.dumps(team, ensure_ascii=False), encoding="utf-8")
    server = tmp_path / "server"
    server.mkdir()
    for name, text in (("build.toml", BUILD_TOML), ("bench.toml", BENCH_TOML)):
        (server / name).write_text(text.format(root=tmp_path), encoding="utf-8")
    data = tmp_path / "data"
    data.mkdir()
    (data / paths.SAMPLE_FILE).write_text(json.dumps({"sample": str(sample)}), encoding="utf-8")
    monkeypatch.setenv("CC1_BENCH_STATE", str(tmp_path / "bench-state"))
    ctx = SimpleNamespace(name="vstatd-team", logger=logging.getLogger("kcteam-test"), data_dir=str(data))
    svc = service.Service(ctx, manager=FakeManager(), work_root=tmp_path / "work", tick_s=60, team_file=team_file)
    return svc, handlers.build_routes(svc, AppRoute, web=FakeWeb, is_owner=owner_check), server


def post(routes, body, **kw):
    return call(routes, "POST", "/settings", json_body=body, **kw)


def test_settings_are_the_dashboard_owners_alone(tmp_path, monkeypatch):
    svc, routes, _ = scenario(tmp_path, monkeypatch)

    async def go():
        for method in ("GET", "POST"):
            assert (await call(routes, method, "/settings", user=None)).status == 401, method
            r = await call(routes, method, "/settings", owner=False)
            assert (r.status, r.code) == (403, "owner_only"), method
            r = await call(routes, method, "/settings", app="vstatd-team")
            assert (r.status, r.code) == (403, "app_token_forbidden"), method
        assert not (svc.data_dir / "settings.json").exists()  # a refused request writes nothing

    asyncio.run(go())


def test_with_no_settings_file_the_defaults_are_the_team_files(tmp_path, monkeypatch):
    svc, routes, server = scenario(tmp_path, monkeypatch)

    async def go():
        r = await call(routes, "GET", "/settings")
        assert r.status == 200
        got, dflt = r.body["settings"], r.body["defaults"]
        assert got == dflt  # no file: nothing differs from the team file
        assert got["mode"] == "direct" and r.body["release"] is None  # direct mode reads no server configuration
        assert got["server_configs"] == {"build": shown("~/workplace/vstatd-team/server/build.toml"),
                                         "bench": shown("~/workplace/vstatd-team/server/bench.toml")}
        assert got["baseline"] == "${sample}/bench/baseline"
        assert got["docker"] == {"runner": "", "host": ""} and got["board_decides"] is False
        # the team a run would get is the team file as it is
        team, _ = await asyncio.to_thread(svc._default_team)
        assert team["connectors"] == "direct" and team["check_runner"]["docker"][0] == "docker"
        assert team["bench"]["baseline"] == str(tmp_path / "sample" / "bench" / "baseline")

    asyncio.run(go())


def test_saving_changes_what_the_next_run_gets_and_leaves_the_server_configs_alone(tmp_path, monkeypatch):
    svc, routes, server = scenario(tmp_path, monkeypatch)
    before = {p.name: p.read_bytes() for p in server.glob("*.toml")}

    async def go():
        confs = {"build": str(server / "build.toml"), "bench": str(server / "bench.toml")}
        body = {"settings": {"mode": "servers",
                             "server_configs": confs,
                             "baseline": str(tmp_path / "own-baseline"),
                             "docker": {"runner": "/opt/podman/bin/docker", "host": "tcp://bench.example:2375"},
                             "board_decides": True,
                             "a_key_this_version_does_not_know": 1}}
        r = await post(routes, body)
        assert r.status == 200 and r.body["ok"] is True
        got = r.body["settings"]
        assert "a_key_this_version_does_not_know" not in got  # an unknown key is dropped
        assert got["mode"] == "servers" and got["board_decides"] is True
        assert got["docker"] == {"runner": "/opt/podman/bin/docker", "host": "tcp://bench.example:2375"}
        # written as one JSON object in the app's data directory; the reply writes the home folder as ~ (display.py)
        kept = json.loads((svc.data_dir / "settings.json").read_text(encoding="utf-8"))
        assert set(kept) == set(got) and kept["mode"] == "servers" and kept["board_decides"] is True
        assert kept["baseline"] == str(tmp_path / "own-baseline")
        assert got["baseline"] == shown(str(tmp_path / "own-baseline"))
        assert kept["server_configs"] == {"build": str(server / "build.toml"), "bench": str(server / "bench.toml")}
        # the team a run would get now carries every one of them
        team, _ = await asyncio.to_thread(svc._default_team)
        assert servers_mod.on(team) and servers_mod.board_decides(team) is True
        assert team["servers"]["build"][team["servers"]["build"].index("--config") + 1] == str(server / "build.toml")
        assert team["servers"]["bench"][team["servers"]["bench"].index("--config") + 1] == str(server / "bench.toml")
        assert team["bench"]["baseline"] == str(tmp_path / "own-baseline")
        words = team["check_runner"]["docker"]
        assert words[:4] == ["/opt/podman/bin/docker", "-H", "tcp://bench.example:2375", "run"]
        # GET says the same, with the team file's values still beside them as the defaults
        r = await call(routes, "GET", "/settings")
        assert r.body["settings"] == got and r.body["defaults"]["mode"] == "direct"
        assert {p.name: p.read_bytes() for p in server.glob("*.toml")} == before  # never written by the app

    asyncio.run(go())


def test_what_does_not_hold_up_is_refused_and_nothing_is_written(tmp_path, monkeypatch):
    svc, routes, server = scenario(tmp_path, monkeypatch)

    async def go():
        for patch, said in (({"mode": "sideways"}, "「模式」只能是 direct 或 servers"),
                            ({"server_configs": {"build": "server/build.toml"}}, "要写绝对路径"),
                            ({"baseline": ""}, "不能留空"),
                            ({"docker": {"host": "bench.example:2375"}}, "要以 unix://"),
                            ({"docker": {"runner": "docker"}}, "要写绝对路径"),
                            ({"board_decides": "yes"}, "要是 true 或 false"),
                            ({"baseline": "x" * 600}, "太长了")):
            r = await post(routes, {"settings": {**patch}})
            assert (r.status, r.code) == (400, "invalid_settings"), patch
            assert any(said in p for p in r.body["problems"]), (patch, r.body["problems"])
            assert not (svc.data_dir / "settings.json").exists(), patch
        # an empty configuration file path is refused and the team file's stays
        r = await post(routes, {"settings": {"server_configs": {"build": "", "bench": ""}}})
        assert (r.status, r.code) == (400, "invalid_settings")
        assert sum("不能留空" in p for p in r.body["problems"]) == 2
        assert not (svc.data_dir / "settings.json").exists()

    asyncio.run(go())


def test_a_team_file_without_servers_cannot_be_switched_to_servers_mode(tmp_path, monkeypatch):
    svc, routes, _ = scenario(tmp_path, monkeypatch)
    team = json.loads(svc.team_file.read_text(encoding="utf-8"))
    team.pop("servers")
    svc.team_file.write_text(json.dumps(team, ensure_ascii=False), encoding="utf-8")

    async def go():
        r = await post(routes, {"settings": {"mode": "servers"}})
        assert (r.status, r.code) == (400, "invalid_settings")
        assert any("没有 servers" in p for p in r.body["problems"])
        assert not (svc.data_dir / "settings.json").exists()

    asyncio.run(go())


def test_a_settings_file_that_cannot_be_read_falls_back_to_the_team_file(tmp_path, monkeypatch):
    svc, routes, _ = scenario(tmp_path, monkeypatch)
    (svc.data_dir / "settings.json").write_text("{ not json", encoding="utf-8")

    async def go():
        r = await call(routes, "GET", "/settings")
        assert r.status == 200 and r.body["settings"] == r.body["defaults"] and r.body["settings"]["mode"] == "direct"
        team, _ = await asyncio.to_thread(svc._default_team)
        assert team["connectors"] == "direct"

    asyncio.run(go())


def test_the_release_inputs_of_the_build_server_are_read_and_the_lines_derived(tmp_path, monkeypatch):
    svc, routes, server = scenario(tmp_path, monkeypatch)
    conf = {"build": str(server / "build.toml"), "bench": str(server / "bench.toml")}

    async def go():
        body = {"settings": {"mode": "servers", "server_configs": conf}}
        r = await post(routes, body)
        rel = r.body["release"]
        assert r.status == 200 and rel["ok"] is False
        assert rel["missing"] == ["bench_results", "bench_runs", "bench_baseline"]
        assert rel["lines"] == [f'bench_results = "{shown(str(server / "bench-state"))}/results"',
                                f'bench_runs = "{shown(str(server / "bench-state"))}/runs"',
                                f'bench_baseline = "{shown(str(server / "baseline"))}"']
        assert "release" in rel["detail"] and rel["config"] == shown(conf["build"])
        # 准备情况 carries the same item in servers mode (read only, no command of its own); items() alone, so that
        # this test starts no Docker or doctor.sh probe
        team, sample = await asyncio.to_thread(svc._default_team)
        rows = readiness_mod.items(team, svc.probes, None, {}, sample, 0.0,
                                   settings_mod.release_inputs(settings_mod.defaults(team)))
        item = {i["key"]: i for i in rows}["release_inputs"]
        assert item["ok"] is False and item["command"] == "" and "设置" in item["detail"]

        # the three paths added by hand, in the server's own file (inside its [paths]): both say it is ready
        (server / "build.toml").write_text(
            BUILD_TOML.format(root=tmp_path).replace(
                '[sandbox]',
                f'bench_results = "{server / "bench-state"}/results"\n'
                f'bench_runs = "{server / "bench-state"}/runs"\n'
                f'bench_baseline = "{server / "baseline"}"\n\n[sandbox]'), encoding="utf-8")
        r = await call(routes, "GET", "/settings")
        assert r.body["release"]["ok"] is True and r.body["release"]["missing"] == []
        rows = readiness_mod.items(team, svc.probes, None, {}, sample, 0.0,
                                   settings_mod.release_inputs(settings_mod.defaults(team)))
        assert {i["key"]: i for i in rows}["release_inputs"]["ok"] is True

        # a configuration file that is not there at all: the app cannot tell (ok None), and says why
        Path(server / "build.toml").unlink()
        r = await call(routes, "GET", "/settings")
        assert r.body["release"]["ok"] is None and "读不了" in r.body["release"]["detail"]

    asyncio.run(go())


def test_direct_mode_reads_no_server_configuration_and_shows_no_release_item(tmp_path, monkeypatch):
    svc, routes, server = scenario(tmp_path, monkeypatch)

    async def go():
        assert (await post(routes, {"settings": {"mode": "direct"}})).body["release"] is None
        team, sample = await asyncio.to_thread(svc._default_team)
        rows = readiness_mod.items(team, svc.probes, None, {}, sample, 0.0, None)
        assert "release_inputs" not in {i["key"] for i in rows}

    asyncio.run(go())


def test_defaults_apply_and_check_stand_on_their_own():
    """settings.py without the service: the team file's defaults, a value sent back unchanged, and apply()."""
    team = json.loads(constants.TEAM_FILE.read_text(encoding="utf-8"))
    dflt = settings_mod.defaults(team)
    # a field sent back exactly as the team file has it is that default, ${sample} and all
    got, probs = settings_mod.check(dict(dflt), team)
    assert (got, probs) == (dflt, [])
    # apply() changes the team dict only, never the file, and leaves a server command line's other words alone
    changed = {**dflt, "mode": "servers", "docker": {"runner": "", "host": "unix:///tmp/d.sock"}}
    out = settings_mod.apply(team, changed)
    assert team["connectors"] == "direct" and out["connectors"] == "servers"
    assert out["check_runner"]["docker"][:3] == ["docker", "-H", "unix:///tmp/d.sock"]
    assert out["servers"]["build"][-2:] == team["servers"]["build"][-2:]
    twice = settings_mod.apply(settings_mod.apply(team, changed), changed)  # applied again: one -H, not two
    assert twice["check_runner"]["docker"].count("-H") == 1
