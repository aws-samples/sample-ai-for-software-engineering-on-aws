"""批准 / 拒绝 on the board (D3): the bench's own benchstate.decide() decides, on a temporary bench state."""

import asyncio
import json
import time

import pytest

from teamkit import ROOT, mod

bench = mod("bench")
AppError = mod("httpkit").AppError

LIB = ROOT.parent / "bench" / "lib"
DIGEST = "bc93723c0cb02e054acc5f25705b61a4443435c168351ec5914d0729bdce4d98"


def request(state, rid, expires_in=200.0):
    (state / "requests").mkdir(parents=True, exist_ok=True)
    (state / "decisions").mkdir(exist_ok=True)
    req = {"id": rid, "action": "deploy", "digest": DIGEST, "detail": "", "requested_at": "2026-11-03T01:54:16.000Z",
           "expires": time.time() + expires_in, "timeout_s": 300, "requested_by": "bench tools"}
    (state / "requests" / f"{rid}.json").write_text(json.dumps(req), encoding="utf-8")


def decide(*args):
    return asyncio.run(bench.decide(LIB, *args))


def test_approve_needs_the_digest_and_is_recorded_once(tmp_path, monkeypatch):
    monkeypatch.setenv("CC1_BENCH_STATE", str(tmp_path))
    rid = "20261103T095416-deploy-cc7c"
    request(tmp_path, rid)
    with pytest.raises(AppError) as e:
        decide(rid, "approve", "", "")
    assert e.value.code == "digest_required"
    with pytest.raises(AppError) as e:
        decide(rid, "approve", "ffffff", "")  # not this build's digest: the bench refuses
    assert e.value.code == "bench_refused" and "first 6 characters" in str(e.value)
    assert not (tmp_path / "decisions" / f"{rid}.json").exists()
    res = decide(rid, "approve", "BC9372", "")
    assert res["ok"] and res["decision"]["verdict"] == "approved" and res["decision"]["digest"] == DIGEST
    assert "Kiro Crew 看板" in res["decision"]["by"]
    rec = [json.loads(ln) for ln in (tmp_path / "actions.jsonl").read_text().splitlines()]
    assert rec[-1]["event"] == "decision" and rec[-1]["verdict"] == "approved" and "Kiro Crew 看板" in rec[-1]["by"]
    with pytest.raises(AppError) as e:
        decide(rid, "refuse", "", "too late")
    assert e.value.code == "bench_refused" and "already been decided" in str(e.value)


def test_refuse_needs_a_reason_and_expired_requests_cannot_be_approved(tmp_path, monkeypatch):
    monkeypatch.setenv("CC1_BENCH_STATE", str(tmp_path))
    rid, old = "20261103T095416-deploy-aaaa", "20261103T094046-deploy-2570"
    request(tmp_path, rid)
    request(tmp_path, old, expires_in=-5)
    with pytest.raises(AppError) as e:
        decide(rid, "refuse", "", " ")
    assert e.value.code == "reason_required"
    assert decide(rid, "refuse", "", "不是这次的构建")["decision"]["verdict"] == "refused"
    with pytest.raises(AppError) as e:
        decide(old, "approve", "bc9372", "")
    assert "expired" in str(e.value)


@pytest.mark.parametrize("rid", ["../decisions/x", "20261103T095416-deploy-cc7c;rm", "", None, 5])
def test_only_a_request_id_is_accepted(tmp_path, monkeypatch, rid):
    monkeypatch.setenv("CC1_BENCH_STATE", str(tmp_path))
    with pytest.raises(AppError) as e:
        decide(rid, "approve", "bc9372", "")
    assert e.value.code == "invalid_id"
    with pytest.raises(AppError):
        decide("20261103T095416-deploy-cc7c", "maybe", "bc9372", "")
