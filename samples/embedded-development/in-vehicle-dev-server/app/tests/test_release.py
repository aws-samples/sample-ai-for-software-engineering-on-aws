"""The independent rerun (D9): every check again on the final commit in a new results directory, release.sh, the
evidence page, and sign-off only when release.sh passed (stand-in checks and bench, as in test_bench.py)."""

import asyncio
import hashlib
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_bench import Rig
from test_checks import until
from teamkit import mod, sh

board, service, httpkit = mod("board"), mod("service"), mod("httpkit")


def signer(tmp_path, rig):
    ctx = SimpleNamespace(name="vstatd-team", logger=logging.getLogger("kcteam-test"), data_dir=str(tmp_path / "svc"))
    svc = service.Service(ctx, manager=rig.mgr, work_root=tmp_path / "work", tick_s=60)
    svc.runs[rig.run.rid] = rig.run
    return svc


def to_rerun(rig):
    return until(rig.run, rig.mgr, lambda: (rig.run.s.get("bench") or {}).get("step") == "rerun")


def test_the_rerun_judges_the_final_commit_afresh_and_signing_merges_into_main(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, release=True)
    run = rig.run

    async def go():
        await to_rerun(rig)
        root = Path(run.s["repo"]).parent
        stale = root / "results" / "rerun" / "work"
        stale.mkdir(parents=True)  # something an earlier rerun left: a new rerun starts from nothing
        (stale / "cache").write_text("x", encoding="utf-8")
        await until(run, rig.mgr, lambda: run.ended)
        assert run.s["status"] == "done" and run.sign_block() == ""
        rerun = run.s["rerun"]
        results = root / "results" / "rerun"
        assert rerun["results"] == str(results) and not stale.exists()
        assert [c["name"] for c in rerun["checks"]] == ["build", "unit", "logdiff", "runtime-limits"]
        assert rerun["release"]["verdict"] == "PASS" and rerun["differs"] == []
        for name in ("build", "unit", "logdiff", "runtime-limits", "release"):  # all of it in the one directory
            args = json.loads((results / f"{name}.json").read_text())["args"] if name != "build" else None
            assert (results / f"{name}.json").is_file()
            if name in ("logdiff", "runtime-limits"):  # the run directory of the last replay
                assert args[args.index("--run") + 1] == run.s["bench"]["run_dir"]
        assert json.loads((results / "repair-rounds.json").read_text())["limits"]["logdiff"] == 2
        assert sh(root / "wt" / "_checks", "rev-parse", "HEAD").strip() == run.s["bench"]["head"]
        view = board.release_view(run)
        assert view["evidence"].startswith("# Evidence page: vstatd") and "release" in view["evidence"]
        assert [c["argv"][0] for c in rig.calls()] == ["deploy", "replay"]  # no fresh replay for the rerun

        svc = signer(tmp_path, rig)
        out = await svc.signoff(run.rid, "王经理", "按证据页放行")
        assert out["signoff"]["by"] == "王经理" and out["signoff"]["merged"]
        trail = out["signoff"]["audit"]  # the audit trail beside the evidence, outside the repository, named by sha256
        assert trail["dir"] == str(root / "results") and not (results / "audit.md").exists()
        for name in ("md", "json"):
            assert hashlib.sha256((root / "results" / f"audit.{name}").read_bytes()).hexdigest() == trail[name]
        assert (root / "results" / "audit.md").read_text().startswith(f"# 审计记录 · {run.rid}")
        repo = Path(run.s["repo"])
        assert sh(repo, "rev-parse", "main").strip() == sh(repo, "rev-parse", run.s["branch"]).strip()

    asyncio.run(go())


def test_a_check_that_differs_on_the_rerun_is_recorded_and_a_failing_release_refuses_sign_off(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, release=True)
    run = rig.run

    async def go():
        await to_rerun(rig)
        rig.bench.set("unit", 1, ["plain: FAILED SignalTable.Find (flaky before, failing on a clean build)"])
        rig.bench.set("release", 1, ["unit: FAIL - see reasons"])
        await until(run, rig.mgr, lambda: run.ended)
        rerun = run.s["rerun"]
        assert rerun["differs"] == [{"name": "unit", "was": "PASS", "now": "FAIL"}]
        assert rerun["release"] == {"verdict": "FAIL", "summary": "", "reasons": ["unit: FAIL - see reasons"]}
        assert run.s["status"] == "failed" and run.s["bench"]["held"]["step"] == "rerun"
        assert run.sign_block() == "独立重跑后 release.sh 没通过，不能签字放行：unit: FAIL - see reasons"
        assert board.release_view(run)["differs"][0]["name"] == "unit"
        with pytest.raises(httpkit.AppError, match="release.sh 没通过") as e:
            await signer(tmp_path, rig).signoff(run.rid, "王经理")
        assert e.value.code == "not_signable" and not run.s.get("signoff")

        rig.bench.set("unit", 0)  # a person dealt with it; 重试 reruns everything
        rig.bench.set("release", 0)
        assert await run.retry() == ["bench"]
        await until(run, rig.mgr, lambda: run.ended)
        assert run.s["status"] == "done" and run.s["rerun"]["differs"] == [] and run.sign_block() == ""

    asyncio.run(go())


def test_before_the_rerun_a_team_with_a_release_check_cannot_sign(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, release=True, doctor="fail")
    run = rig.run

    async def go():
        await until(run, rig.mgr, lambda: run.ended)
        assert run.s["status"] == "failed" and not run.s.get("rerun") and board.release_view(run) is None
        run.s["status"] = "done"  # even a run marked done has no release.sh behind it
        assert run.sign_block() == "还没有独立重跑和 release.sh 的结果，不能签字放行"

    asyncio.run(go())
