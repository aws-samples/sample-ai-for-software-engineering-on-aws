"""GET /readiness (D10): the default team's checklist for the empty board, with a stand-in scenario folder, Docker and
doctor.sh. The probes run in the background; a request never waits for them and the bench state is only read."""

import asyncio
import json
import logging
import sys
import time
from types import SimpleNamespace

import pytest

from http_fakes import AppRoute, FakeWeb, call, owner_check
from teamkit import FakeManager, mod

service, handlers, constants, paths = mod("service"), mod("handlers"), mod("constants"), mod("paths")
checks_mod = mod("checks")

DOCKER = f"""#!{sys.executable}
import sys
if sys.argv[1] == "volume":
    print("Error response from daemon: get " + sys.argv[-1] + ": no such volume", file=sys.stderr)
else:
    print("Error: No such image: " + sys.argv[-1], file=sys.stderr)
sys.exit(1)
"""

DOCTOR = f"""#!{sys.executable}
import os, sys, time
open(os.environ["FAKE_DOCTOR_LOG"], "a").write("run\\n")
time.sleep(float(os.environ.get("FAKE_DOCTOR_SLEEP", "0")))
print("PASS  Docker 27, 6 CPUs")
print("WARN  the supply is not set")
print("FAIL  no target image in the volume cc1-images: run bench/build-target.sh")
print("doctor: 1 problem(s)")
sys.exit(1)
"""


def scenario(tmp_path, monkeypatch, sleep=0.0):
    sample = tmp_path / "sample"
    for d in ("checks", "reference-project", "bench"):
        (sample / d).mkdir(parents=True)
    for name, text in (("bench/doctor.sh", DOCTOR), ("docker", DOCKER)):
        (sample / name).write_text(text, encoding="utf-8")
        (sample / name).chmod(0o755)
    (sample / "bench" / "console.py").write_text("", encoding="utf-8")
    team = json.loads(constants.TEAM_FILE.read_text(encoding="utf-8"))
    team["check_runner"]["docker"][0] = "${sample}/docker"
    team["bench"]["baseline"] = str(tmp_path / "baseline")
    team_file = tmp_path / "team" / "team-vstatd.json"
    team_file.parent.mkdir()
    team_file.write_text(json.dumps(team, ensure_ascii=False), encoding="utf-8")
    data = tmp_path / "data"
    data.mkdir()
    (data / paths.SAMPLE_FILE).write_text(json.dumps({"sample": str(sample)}), encoding="utf-8")
    state = tmp_path / "bench-state"
    (state / "requests").mkdir(parents=True)
    (state / "target.json").write_text(json.dumps({"state": "off", "why": "never started"}), encoding="utf-8")
    monkeypatch.setenv("CC1_BENCH_STATE", str(state))
    monkeypatch.setenv("FAKE_DOCTOR_LOG", str(tmp_path / "doctor.log"))
    monkeypatch.setenv("FAKE_DOCTOR_SLEEP", str(sleep))
    ctx = SimpleNamespace(name="vstatd-team", logger=logging.getLogger("kcteam-test"), data_dir=str(data))
    svc = service.Service(ctx, manager=FakeManager(), work_root=tmp_path / "work", tick_s=60, team_file=team_file)
    return svc, handlers.build_routes(svc, AppRoute, web=FakeWeb, is_owner=owner_check), sample, state


def snapshot(d):
    return sorted((str(p.relative_to(d)), p.read_bytes()) for p in d.rglob("*") if p.is_file())


def test_readiness_is_owner_only(tmp_path, monkeypatch):
    svc, routes, _, _ = scenario(tmp_path, monkeypatch)

    async def go():
        for method, path in (("GET", "/readiness"), ("POST", "/readiness/doctor")):
            assert (await call(routes, method, path, user=None)).status == 401, path
            r = await call(routes, method, path, owner=False)
            assert (r.status, r.code) == (403, "owner_only"), path

    asyncio.run(go())


@pytest.mark.parametrize("machine, arch", [("arm64", "arm64"), ("x86_64", "amd64")])
def test_the_checklist_answers_at_once_and_says_what_to_run(tmp_path, monkeypatch, machine, arch):
    monkeypatch.setattr(checks_mod.platform, "machine", lambda: machine)
    svc, routes, sample, state = scenario(tmp_path, monkeypatch, sleep=1.5)
    before = snapshot(state)

    async def go():
        try:
            t0 = time.monotonic()
            r = await call(routes, "GET", "/readiness")
            assert r.status == 200 and time.monotonic() - t0 < 1.0  # doctor.sh is still running
            first = {i["key"]: i for i in r.body["items"]}
            assert r.body["team"] == "AIDLC-Embedded团队" and r.body["error"] == ""
            assert list(first) == ["knowledge", "image", "sysroot", "doctor", "target", "baseline", "console"]
            assert first["doctor"]["ok"] is None and first["doctor"]["running"] and first["doctor"]["detail"] == "正在跑"
            for _ in range(100):
                await asyncio.sleep(0.05)
                items = {i["key"]: i for i in (await call(routes, "GET", "/readiness")).body["items"]}
                if all(items[k]["ok"] is not None for k in ("doctor", "image", "sysroot")):
                    break
            assert {k: i["needed"] for k, i in items.items()} == {"knowledge": "start", "image": "checks", "sysroot": "checks",
                                                                   "doctor": "bench", "target": "bench", "baseline": "bench", "console": "bench"}
            assert items["knowledge"]["ok"] is None  # Kiro Crew's sources not read yet
            assert items["image"]["ok"] is False and items["image"]["detail"] == "镜像不在本机"
            assert items["image"]["label"] == f"构建容器镜像 vstatd-build:{arch}"
            assert items["image"]["command"] == f"docker build --platform linux/{arch} -t vstatd-build:{arch} {sample}/reference-project/tools/"
            assert items["sysroot"]["label"] == "检查用的 sysroot（vstatd-standin-sysroot）"
            assert items["sysroot"]["ok"] is False and items["sysroot"]["detail"] == "卷不在本机"
            assert items["sysroot"]["command"] == (
                f"docker run --rm --platform linux/{arch} -v vstatd-standin-sysroot:/opt/cc1-sysroot -v {sample}:/sample:ro "
                f"vstatd-build:{arch} python3 /sample/reference-project/tools/make-standin-sysroot.py /opt/cc1-sysroot")
            assert items["doctor"]["ok"] is False and not items["doctor"]["running"] and items["doctor"]["age_s"] >= 0
            assert "no target image" in items["doctor"]["detail"] and "the supply is not set" in items["doctor"]["detail"]
            assert items["doctor"]["command"] == f"{sample}/bench/build-target.sh"
            assert items["target"]["ok"] is False and items["target"]["command"] == f"{sample}/bench/cc1.sh start"
            assert items["baseline"]["ok"] is False
            assert items["baseline"]["command"].endswith(f"replay --kind baseline --out {tmp_path / 'baseline'}")
            assert items["console"]["ok"] is None and items["console"]["command"] == f"python3 {sample}/bench/console.py"
            assert (tmp_path / "doctor.log").read_text().count("run") == 1  # once by itself, not on every request

            r = await call(routes, "POST", "/readiness/doctor")
            assert r.status == 200 and {i["key"]: i for i in r.body["items"]}["doctor"]["running"]
            for _ in range(100):
                await asyncio.sleep(0.05)
                if not svc.probes.running("doctor"):
                    break
            assert (tmp_path / "doctor.log").read_text().count("run") == 2

            (tmp_path / "baseline").mkdir()
            (tmp_path / "baseline" / "baseline-result.json").write_text("{}", encoding="utf-8")
            (state / "target.json").write_text(json.dumps({"state": "known", "why": "booted"}), encoding="utf-8")
            svc.crew["knowledge"] = [{"name": "vstatd", "item_count": 14, "sync_status": "synced"}]
            items = {i["key"]: i for i in (await call(routes, "GET", "/readiness")).body["items"]}
            assert items["baseline"]["ok"] and items["baseline"]["command"] == ""
            assert items["target"]["ok"] and items["knowledge"]["ok"] and items["knowledge"]["detail"] == "14 份文档 · 已索引"
            before_known = snapshot(state)
        finally:
            await svc.stop()
        return before_known

    known = asyncio.run(go())
    assert snapshot(state) == known and before != known  # the app wrote nothing there; only the test did


def test_without_a_scenario_folder_the_checklist_says_why(tmp_path, monkeypatch):
    svc, routes, _, _ = scenario(tmp_path, monkeypatch)
    (tmp_path / "data" / paths.SAMPLE_FILE).write_text(json.dumps({"sample": str(tmp_path / "moved")}), encoding="utf-8")

    async def go():
        r = await call(routes, "GET", "/readiness")
        assert r.status == 200 and r.body["items"] == [] and "setup.sh" in r.body["error"]

    asyncio.run(go())


def test_the_checklist_lists_the_requests_waiting_at_the_console(tmp_path, monkeypatch):
    svc, routes, sample, state = scenario(tmp_path, monkeypatch)
    now = time.time()
    req = {"id": "20261103T094307-deploy-ac78", "action": "deploy", "digest": "bc93723c0cb02e054acc5f25705b61a4",
           "detail": "", "requested_at": "2026-11-03T01:43:07.000Z", "requested_by": "bench tools", "expires": now + 200}
    (state / "requests" / f"{req['id']}.json").write_text(json.dumps(req), encoding="utf-8")
    old = {**req, "id": "20261103T094046-deploy-2570", "expires": now - 10}  # timed out: not listed
    (state / "requests" / f"{old['id']}.json").write_text(json.dumps(old), encoding="utf-8")
    done = {**req, "id": "20261103T090000-replay-0001"}  # decided: not listed
    (state / "requests" / f"{done['id']}.json").write_text(json.dumps(done), encoding="utf-8")
    (state / "decisions").mkdir()
    (state / "decisions" / f"{done['id']}.json").write_text("{}", encoding="utf-8")
    before = snapshot(state)

    async def go():
        try:
            return (await call(routes, "GET", "/readiness")).body["pending"]
        finally:
            await svc.stop()

    pending = asyncio.run(go())
    assert [p["id"] for p in pending] == [req["id"]]
    p = pending[0]
    assert p["action"] == "deploy" and p["requested_by"] == "bench tools" and 190 <= p["left_s"] <= 200
    assert p["approve"] == f"python3 {sample}/bench/console.py approve {req['id']} --digest bc93723c0cb0"
    assert p["refuse"] == f"python3 {sample}/bench/console.py refuse {req['id']} --reason <原因>"
    assert snapshot(state) == before  # read only
