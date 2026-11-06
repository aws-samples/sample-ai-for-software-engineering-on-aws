"""What the replies show of this Mac and of its people (backend/team/display.py), and an older run's events in
English (messages.with_codes), on the first delivery's own events.

tests/fixtures/r11032637/ is r11032637's events.jsonl and the roles of its team, with this Mac's home folder, user
name and host name written {HOME}, {USER} and {HOST}; each test puts this Mac's back, so that what it looks for in
the replies is what this Mac would show.
"""

import asyncio
import getpass
import json
import re
import socket
from pathlib import Path

from http_fakes import call
from teamkit import ROOT, FakeManager, make_run, mod
from test_service import make

messages, display, team_mod, constants = mod("messages"), mod("display"), mod("team"), mod("constants")
FIXTURE = Path(__file__).parent / "fixtures" / "r11032637"
CJK = re.compile(r"[\u3400-\u9fff\u3000-\u303f\uff00-\uffef]")
HOME, USER, HOST = str(Path.home()), getpass.getuser(), socket.gethostname().split(".")[0]
EN_TITLES = {"triage": "Triage", "architect": "Architect", "tester": "Tester", "dev-fix": "Developer · fix",
             "dev-refactor": "Developer · refactor", "reviewer": "Reviewer"}
EN_GATES = {"triage": "Triage", "architect": "Start"}


def here(text: str) -> str:
    return text.replace("{HOME}", HOME).replace("{USER}", USER).replace("{HOST}", HOST)


def first_delivery() -> tuple[list[dict], dict]:
    events = [json.loads(here(line)) for line in (FIXTURE / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    return events, json.loads(here((FIXTURE / "run.json").read_text(encoding="utf-8")))


def blank_free_text(params):
    """*params* with what people, agents and tools wrote (messages.FREE_TEXT) taken out, nested messages kept."""
    if isinstance(params, dict) and "code" in params and set(params) <= {"code", "params"}:
        return {"code": params["code"], "params": blank_free_text(params.get("params") or {})}
    if isinstance(params, dict):
        return {k: ("x" if k in messages.FREE_TEXT and not isinstance(v, dict) else blank_free_text(v)) for k, v in params.items()}
    if isinstance(params, list):
        return [blank_free_text(v) for v in params]
    return params


def english(e: dict) -> str:
    return messages.render(e["code"], blank_free_text(e.get("params") or {}), lambda k: EN_TITLES.get(k, k),
                           lambda k: EN_GATES.get(k, EN_TITLES.get(k, k)), "en")


def test_every_event_of_the_first_delivery_gets_its_code_back_from_its_text():
    events, meta = first_delivery()
    assert not any(e.get("code") for e in events)  # recorded before events carried a code
    out = messages.with_codes(events, meta["roles"])
    assert [e for e in out if not e.get("code")] == []
    titles = {r["key"]: r["title"] for r in meta["roles"]}
    gates = {r["key"]: r.get("gate_label") or r["title"] for r in meta["roles"]}
    for e in out:  # said again in Chinese, the code gives the text as it was recorded (at most 200 characters)
        again = " ".join(messages.render(e["code"], e["params"], lambda k: titles.get(k, k), lambda k: gates.get(k, k)).split())
        assert again == e["text"] or (len(e["text"]) >= 195 and again.startswith(e["text"])), (e["seq"], e["code"])
    assert events == first_delivery()[0]  # the record itself is not changed


def test_in_english_none_of_the_apps_own_words_stay_chinese():
    """The app's own words of every event in English, with what people, agents and tools wrote taken out: no
    Chinese is left. (Those taken out stay as written: the requirement, summaries, notes, reasons, commit subjects.)"""
    events, meta = first_delivery()
    left = [(e["seq"], e["code"], english(e)) for e in messages.with_codes(events, meta["roles"]) if CJK.search(english(e))]
    assert left == []


def test_the_app_writes_new_events_of_the_same_kinds_by_code():
    """A round's label, why the checks hold the run and the decisions at a gate are messages too, not words."""
    assert messages.label_of("修 build、unit") == {"code": "label.fix", "params": {"items": ["build", "unit"]}}
    assert messages.label_of("补写提交说明") == {"code": "label.trace", "params": {}}
    assert messages.label_of("先单独提交 F-023") is None  # the planner's own words
    assert messages.render("label.fix", {"items": ["F-032"]}, lang="en") == "fix F-032"


def service_with_the_first_delivery(tmp_path, monkeypatch):
    """A service holding a run whose events, sign-off and bench are the first delivery's, on this Mac's paths."""
    events, meta = first_delivery()
    bench = tmp_path / "cc1-bench"
    bench.mkdir()
    (bench / "supply.json").write_text(json.dumps({"voltage_v": 13.5, "kl15": "on", "set_by": f"{USER}@{HOST} (/dev/ttys003)"}))
    (bench / "actions.jsonl").write_text("".join(json.dumps(r) + "\n" for r in (
        {"at": "2026-11-03T09:00:00Z", "event": "decision", "id": "q1", "verdict": "approved", "action": "deploy",
         "by": f"Kiro Crew 看板（{USER}，vstatd-team）"},
        {"at": "2026-11-03T09:01:00Z", "event": "action", "id": "q1", "action": "deploy", "result": "ok",
         "detail": f"installed from {HOME}/workplace/vstatd-team/runs/r11032637/results/rerun/artifacts/vstatd"})))
    monkeypatch.setenv("CC1_BENCH_STATE", str(bench))
    svc, routes = make(tmp_path, FakeManager(), tick_s=3600)
    run = make_run(tmp_path / "run", FakeManager(), team=team_mod.load_team(constants.TEAM_FILE), rid=meta["id"],
                   requirement=events[0]["text"].split("：", 1)[1])
    run.events.clear()
    run.events.extend(events)
    run.s.update(status="done", ended_at=meta["ended_at"], signoff={"by": USER, "at": meta["signoff"]["at"], "tests": "5/5"})
    run.s["bench"] = {"step": "done", "run_dir": f"{HOME}/workplace/vstatd-team/runs/r11032637/bench/run-1",
                      "artifact": f"{HOME}/workplace/vstatd-team/runs/r11032637/results/rerun/artifacts/vstatd",
                      "held": {"step": "rerun", "why": f"baseline ({HOME}/workplace/vstatd-team/baseline) changed",
                               "code": "hold.release", "params": {"why": f"baseline ({HOME}/workplace/b) changed"},
                               "commands": [f"{HOME}/x.sh"], "at": 1.0}}
    d = Path(svc.data_dir) / "runs" / run.rid
    d.mkdir(parents=True)
    (d / "events.jsonl").write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events), encoding="utf-8")
    svc.runs[run.rid] = run
    return svc, routes, run


def replies(routes, rid, present=""):
    q = f"present={present}" if present else ""
    paths = [f"/board?run={rid}&{q}", f"/runs/{rid}/events?{q}", f"/runs/{rid}/flow?{q}", f"/runs/{rid}/audit?lang=en&{q}",
             f"/runs/{rid}/audit?lang=en&format=md&{q}", f"/runs/{rid}/audit?lang=en&format=json&{q}", f"/readiness?{q}",
             f"/audit/bench?lang=en&{q}"]

    async def go():
        out = {}
        for p in paths:
            r = await call(routes, "GET", p)
            assert r.status == 200, (p, r.status, getattr(r, "body", None))
            out[p] = r.body if isinstance(r.body, (dict, list)) else str(getattr(r, "text", r.body))
        return out
    return asyncio.run(go())


def test_no_reply_shows_the_home_folder(tmp_path, monkeypatch):
    svc, routes, run = service_with_the_first_delivery(tmp_path, monkeypatch)
    out = replies(routes, run.rid)
    for path, body in out.items():
        text = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
        assert HOME not in text, path
    board = out[f"/board?run={run.rid}&"]["run"]
    assert board["bench"]["run_dir"] == "~/workplace/vstatd-team/runs/r11032637/bench/run-1"
    replayed = next(e for e in board["events"] if e.get("code") == "bench.replayed")
    assert replayed["params"]["run_dir"] == "~/workplace/vstatd-team/runs/r11032637/bench/run-1"
    assert "~/workplace" in replayed["text"]
    assert "~/workplace" in out[f"/runs/{run.rid}/audit?lang=en&format=md&"]
    assert run.s["bench"]["run_dir"].startswith(HOME)  # shown with ~, recorded as it was


def test_in_presentation_mode_no_reply_names_the_user(tmp_path, monkeypatch):
    svc, routes, run = service_with_the_first_delivery(tmp_path, monkeypatch)
    for present, owner in (("en", "Release owner"), ("zh", "负责人")):
        out = replies(routes, run.rid, present)
        for path, body in out.items():
            text = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
            assert USER not in text and HOME not in text and f"@{HOST}" not in text, (present, path)
        board = out[f"/board?run={run.rid}&present={present}"]["run"]
        assert board["signoff"]["by"] == owner
        finding = next(e for e in board["events"] if e.get("code") == "finding.add")
        assert finding["text"].startswith(f"{owner}补登 F-03") and finding["params"]["by"] == owner
        assert board["bench"]["state"]["supply"]["set_by"] == owner
        if present == "en":  # the English audit says the app's words around a name in English too
            entries = out[f"/runs/{run.rid}/audit?lang=en&present=en"]["entries"]
            retry = next(e for e in entries if e["what"].startswith("Retry: Release owner (asked Kiro"))
            assert retry["who"] == "Release owner (asked Kiro to click it in a Kiro session)"
    plain = replies(routes, run.rid)[f"/board?run={run.rid}&"]["run"]
    assert plain["signoff"]["by"] == USER  # off by default


def test_a_name_inside_a_word_or_a_path_is_left_alone():
    v = display.View("en", ["ann"])
    assert v.text("ann补登 F-032") == "Release owner补登 F-032"
    assert v.text("ann@host (/dev/ttys003)") == "Release owner"
    assert v.text("Kiro Crew 看板（ann，vstatd-team）") == "Kiro Crew 看板（Release owner，vstatd-team）"
    assert v.text("planning, annotate, joanna") == "planning, annotate, joanna"
    assert display.View().text(f"cd '{HOME}/a b' && ls {HOME}") == "cd ~/'a b' && ls ~"
    assert display.names_in("lilinll（在 Kiro 会话里让 Kiro 代点）") == {"lilinll"}
    assert display.names_in("Kiro Crew 看板（ann，vstatd-team）") == {"ann"}
    assert display.names_in("负责人") == set() and display.names_in("bench tools") == set()


def test_the_signed_audit_files_are_not_rewritten(tmp_path, monkeypatch):
    """Sign-off writes audit.md and audit.json as they are (their sha256 is on the sign-off record)."""
    svc, routes, run = service_with_the_first_delivery(tmp_path, monkeypatch)
    run.s["repo"] = str(tmp_path / "work" / "repo")
    written = svc._write_audit(run)
    md = Path(written["dir"], "audit.md").read_text(encoding="utf-8")
    assert md.startswith("# 审计记录") and USER in md  # the record as the run has it: not the board's view
    assert ROOT.exists()
