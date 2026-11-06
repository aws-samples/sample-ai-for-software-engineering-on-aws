"""``GET /board``: exactly the ``Board`` type of ui/src/types.ts, built from the runs' state plus what KiroCrew says
about their agents right now (cheap attribute reads), so the live parts stay live between ticks."""

from __future__ import annotations

import json
import re
import shlex
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from . import bench as bench_mod
from . import gitwork, library, messages, roster
from .constants import APP_NAME
from .sessions import agent_fields, find_agent
from .team import ACTIVE, TeamRun, clean_risk, live_status
from .toollog import short


def _newest_first(runs: dict[str, TeamRun]) -> list[TeamRun]:
    """The runs the page lists, newest first: a run a person removed from the list (``hidden``) is not one of them."""
    shown = [r for r in runs.values() if not r.s.get("hidden")]
    return sorted(shown, key=lambda r: float(r.s.get("started_at") or 0), reverse=True)


def cards(runs: dict[str, TeamRun]) -> list[dict[str, Any]]:
    return [card(r) for r in _newest_first(runs)]


def build(runs: dict[str, TeamRun], selected: str | None, *, mgr: Any, scrub: Callable[[str], str],
          now: float, crew: Any = None) -> dict[str, Any]:
    """``run`` is the one asked for (``?run=``), else the newest active one, else the newest."""
    ordered = _newest_first(runs)
    pick = runs.get(selected) if selected else None
    if pick is not None and pick.s.get("hidden"):
        pick = None
    if pick is None:
        pick = next((r for r in ordered if not r.ended), ordered[0] if ordered else None)
    return {"at": now, "runs": [card(r) for r in ordered],
            "run": detail(pick, mgr=mgr, scrub=scrub, now=now, crew=crew) if pick is not None else None}


def card(run: TeamRun) -> dict[str, Any]:
    s, t = run.s, run.s["tests"]
    return {"id": s["id"], "title": s["title"], "status": s["status"], "started_at": s["started_at"],
            "ended_at": s["ended_at"],
            "roles_done": sum(run.lane(k)["status"] in ("merged", "done") for k in run.order), "roles_total": len(run.order),
            "tests": {"passed": t["passed"], "failed": t["failed"], "total": t["total"]},
            "imported": bool(s.get("imported")), "name": run.delivery()["name"], "issue": run.issue()["id"]}


def detail(run: TeamRun, *, mgr: Any, scrub: Callable[[str], str], now: float,
           crew: Any = None) -> dict[str, Any]:
    s, t = run.s, run.s["tests"]
    lanes = [lane(run, k, mgr=mgr, scrub=scrub, now=now) for k in run.order]
    kb = run.team.get("knowledge") or {}
    known = [ln["credits"] for ln in lanes if ln["credits"] is not None]
    return {
        "id": s["id"], "title": s["title"], "status": s["status"], "repo": s["repo"], "folder": s["run_wt"], "base": (s["base"] or "")[:7],
        "branch": s["branch"], "started_at": s["started_at"], "ended_at": s["ended_at"],
        "wall_s": round(max(0.0, (s["ended_at"] or now) - s["started_at"] - float(s.get("paused_s") or 0)), 1),
        "serial_s": round(sum(ln["active_s"] for ln in lanes), 1),
        "credits": round(sum(known), 3) if known else None,
        "roles": lanes,
        "edges": [[dep, k] for k in run.order for dep in run.roles[k]["depends_on"]],
        "team": {"name": run.team.get("name") or "", "orchestrator": run.team.get("orchestrator") or "kirocrew-team"},
        "ownership": s.get("ownership"), "review_rounds": int(s.get("review_rounds") or 0),
        "gate_notes": dict(s.get("gate_notes") or {}),
        "gate_discuss": bool(run.team.get("defaults", {}).get("gate_discuss")),
        "plan_skip": dict(s.get("plan_skip") or {}),
        "overruled": dict(s["overruled"]) if s.get("overruled") else None,
        "sign_block": scrub(run.sign_block()),  # its why comes from release.sh
        "sign_block_msg": messages.scrubbed(run.sign_block_msg(), scrub),
        "review_redo": run.review_redo(),
        "tests": {"at": t["at"], "command": t.get("command", ""), "cases": [_case(c) for c in t["cases"]],
                  "passed": t["passed"], "failed": t["failed"], "total": t["total"],
                  "history": [{"at": h["at"], "passed": h["passed"], "failed": h["failed"]} for h in t["history"]],
                  "held": ({**messages.scrubbed(t["held"], scrub), "suggest": run.path_suggestions()}
                           if t.get("held") else None), "round": int(t.get("round") or 0),
                  "running": bool(s.get("needs_test"))},
        "merges": [{k: m.get(k) for k in ("role", "sha", "at", "status", "files", "note")} for m in s["merges"]],
        "events": [{**e, "text": scrub(str(e.get("text", ""))), "code": e.get("code"),
                    "params": messages.scrubbed(e.get("params"), scrub), "data": e.get("data")}
                   for e in messages.with_codes(run.events, list(run.roles.values())) if not (e.get("kind") == "violation" and any(p in str(e.get("text", "")) for p in gitwork.HOST_PREFIXES))],
        "imported": dict(s["imported"]) if s.get("imported") else None,
        "signoff": dict(s["signoff"]) if s.get("signoff") else None,
        "risks": [{k: r.get(k) for k in ("what", "amount", "gate", "role", "at")} for r in s.get("risks") or [] if isinstance(r, dict)],
        "requirement": s.get("requirement") or "",
        "knowledge": {"source": (crew.knowledge_view(str(kb.get("source") or "")) if crew is not None else None)
                      or (source_row(str(kb["source"]), None) if kb.get("source") else None),
                      "hits": knowledge_hits(run, mgr, scrub, str(kb.get("data_dir") or "")), "docs": cited_docs(run)},
        "crew_members": crew_members(run, crew),
        "delivery": {**run.delivery(), "confirmed": bool(s.get("delivery"))},
        "issue": run.issue(),
        "pr": run.pr(),
        "bench": bench_view(run, scrub),
        "release": release_view(run),
        "backlog": backlog_view(run),
    }


EVIDENCE_SHOWN = 200_000  # characters of the evidence page the sign-off dialog gets


def release_view(run: TeamRun) -> dict[str, Any] | None:
    """ReleaseView: the independent rerun (D9), release.sh's verdict, the checks whose verdict changed on the rerun,
    and the evidence page for the sign-off dialog (None before the rerun)."""
    r = run.s.get("rerun")
    if not r:
        return None
    evidence = None
    if r.get("evidence"):
        try:
            evidence = Path(r["evidence"]).read_text(encoding="utf-8", errors="replace")[:EVIDENCE_SHOWN]
        except OSError:
            evidence = None
    return {"at": r["at"], "head": r["head"], "results": r["results"], "release": dict(r["release"]),
            "checks": [dict(c) for c in r["checks"]], "differs": [dict(d) for d in r["differs"]], "evidence": evidence}


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def backlog_view(run: TeamRun) -> dict[str, Any] | None:
    """BacklogView: the backlog, and once the triage exists (merged for the gate, or approved) one row per finding."""
    kdir = knowledge_dir(run)
    if kdir is None:
        return None
    try:
        rows, next_id = library.backlog_rows(kdir)
    except (OSError, IndexError):
        rows, next_id = [], ""
    return {"rows": rows, "next_id": next_id, "triage": triage_view(run)}


def triage_view(run: TeamRun) -> dict[str, Any] | None:
    """TriageView: the approved triage beside the repository, else the proposed one merged into the run branch; each
    finding with the person's answer at the gate, and what the latest round's static and trace results say of it (None
    where the app has no such record)."""
    key = next(k for k in run.order if run.roles[k].get("triage"))
    s = run.s
    t = _json(Path(s["repo"]).parent / "triage.json") if s.get("repo") else None
    state = "approved" if isinstance(t, dict) and isinstance(t.get("approved"), dict) else None
    if state is None:
        t = _json(Path(s["run_wt"]) / run.roles[key]["triage"]["file"]) if s.get("run_wt") else None
        state = "proposed" if isinstance(t, dict) else None
    if state is None or not isinstance(t.get("findings"), list):
        return None
    answers = {a.get("id"): a for a in (s.get("answers") or {}).get(key) or [] if isinstance(a, dict)}
    results = Path(str(s["tests"].get("results") or "")) if s["tests"].get("results") else None
    static = _json(results / "static.json") if results else None
    trace = _json(results / "trace.json") if results else None
    reported = {f.get("id"): str(f.get("status") or "") for f in ((static or {}).get("details") or {}).get("findings") or []
                if isinstance(f, dict) and f.get("id")} if isinstance(static, dict) else None
    traced = ((trace or {}).get("details") or {}).get("traced") if isinstance(trace, dict) else None
    out = []
    for f in t["findings"]:
        if not isinstance(f, dict) or not isinstance(f.get("id"), str):
            continue
        fid, a = f["id"], answers.get(f["id"])
        answer, answer_msg = None, None
        if a is not None:
            answer = f"其他：{a.get('text') or ''}" if a.get("choice") == "other" else f"{a.get('choice')} {a.get('option') or ''}".strip()
            if a.get("choice") != "other":  # the option's words are the app's (triage.opt.*): said by code in English
                m = messages.as_msg(a.get("option"), "triage.opt.")
                answer_msg = m if isinstance(m, dict) else None
        added = f.get("added") if isinstance(f.get("added"), dict) else {}
        out.append({"id": fid, "decision": str(f.get("decision") or ""), "added": "added" in f,
                    "found_by": str(added["found_by"]) if added.get("found_by") else None,
                    "location": str(added["location"]) if added.get("location") else None,
                    "cites": [str(c) for c in f.get("cites") or []], "facts": [str(x) for x in f.get("facts") or []],
                    "evidence": f.get("evidence") if isinstance(f.get("evidence"), str) else None,
                    "behaviour": f.get("behaviour") if isinstance(f.get("behaviour"), bool) else None, "answer": answer,
                    "answer_key": str(a.get("choice")) if answer_msg else None, "answer_msg": answer_msg,
                    "static": reported.get(fid) if reported is not None else None,
                    "trace": [str(c) for c in traced.get(fid) or []] if isinstance(traced, dict) else None})
    approved = t.get("approved") if state == "approved" else None
    return {"state": state, "approved": {"by": str(approved.get("by") or ""), "at": str(approved.get("at") or "")} if approved else None,
            "findings": out}


def english(run: TeamRun, key: str, field: str) -> str:
    """A role's English name, stage or gate label: the run's team file's, else (a run that started before the team
    file had them) the current team file's, when it is the same team."""
    own = str(run.roles.get(key, {}).get(field) or "")
    return own or roster.english(run.team.get("name"), key, field)


def question(q: dict[str, Any]) -> dict[str, Any]:
    """A gate question with its words by code (the triage's: triage.py), read from the text for an older run."""
    msg = q.get("q_msg") or messages.as_msg(q.get("q"), "triage.q.")
    opts = [{**o, "msg": o.get("msg") or messages.as_msg(o.get("text"), "triage.opt.")} for o in q.get("options") or []]
    out = {**q, "q_msg": msg if isinstance(msg, dict) else None, "options": opts}
    out["options"] = [{**o, "msg": o["msg"] if isinstance(o["msg"], dict) else None} for o in opts]
    return out


def bench_history(run: TeamRun) -> list[dict[str, Any]]:
    """The bench's action record as it concerns this run, for its replay: the requests the run made, every record
    that names one of them, and the target and supply records while it ran (at most 200, oldest first)."""
    from .scorecard import records  # the whole record, read only
    me = f"{APP_NAME} {run.rid}"
    t0, t1 = float(run.s.get("started_at") or 0), float(run.s.get("ended_at") or time.time())
    recs = records()
    mine = {str(r.get("id")) for r in recs if r.get("event") == "request" and r.get("requested_by") == me}
    out = []
    for r in recs:
        rid = str(r.get("id") or r.get("request") or r.get("last_request") or "")
        at = _epoch(r.get("at"))
        if rid in mine or (r.get("event") in ("target", "supply") and at is not None and t0 <= at <= t1 + 60):
            out.append(r)
    return out[-200:]


def _epoch(text: Any) -> float | None:
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def bench_view(run: TeamRun, scrub: Callable[[str], str] = str) -> dict[str, Any] | None:
    """BenchView: the run's bench step and the bench state, read now (read only); *console*: how a person opens the
    operator console, when the bench beside the deploy command has one (bench/console.py)."""
    spec = run.team.get("bench")
    if not spec:
        return None
    b = run.s.get("bench") or {}
    console = Path(spec["deploy"][0]).with_name("console.py")
    held = messages.scrubbed(b.get("held"), scrub) if b.get("held") else None  # its why and params: the bench's output
    return {"step": b.get("step"), "running": b.get("running"), "held": held, "doctor": b.get("doctor"),
            "artifact": b.get("artifact"), "run_dir": b.get("run_dir"), "baseline": str(spec["baseline"]),
            "actions": list(b.get("actions") or []), "state": bench_mod.read_state(), "history": bench_history(run),
            "console": shlex.join(["python3", str(console)]) if console.is_file() else None}


def crew_members(run: TeamRun, crew: Any) -> list[str] | None:
    """The team's members on Crew's 「代理」 page (its workspace): now, for a run still going; as they were when it
    ended, for one that is over (none known for runs that ended before rosters were kept, or a team without one)."""
    if not run.team.get("workspace"):
        return None
    if run.ended:
        kept = run.s.get("crew_members")
        return list(kept) if isinstance(kept, list) else None
    names = crew.member_names(run.team["workspace"]) if crew is not None else None
    return sorted(names) if names is not None else None


def source_row(name: str, row: dict[str, Any] | None) -> dict[str, Any]:
    """A knowledge source as the page shows it (KnowledgeSource): *row* is Crew's, None while not read, {} when absent."""
    spend = (row or {}).get("spend") if isinstance((row or {}).get("spend"), dict) else {}
    return {"name": name, "present": None if row is None else bool(row), "items": (row or {}).get("item_count"),
            "status": str((row or {}).get("sync_status") or ""), "files_total": spend.get("files_total"),
            "files_done": spend.get("files_done"), "path": str((row or {}).get("uri") or "").replace(str(Path.home()), "~")}


def knowledge_dir(run: TeamRun) -> Path | None:
    """The scenario's knowledge folder, as the team's triage role names it (None: a team without a triage)."""
    return next((Path(r["triage"]["knowledge"]) for r in run.team["roles"] if r.get("triage")), None)


def cited_docs(run: TeamRun) -> list[dict[str, Any]]:
    """KnowledgeChip: each citable document and how often the roles' replies (or summaries) cite it."""
    if knowledge_dir(run) is None:
        return []
    texts = [str(a.get("reply") or a.get("summary") or "") for k in run.order for a in run.lane(k)["attempts"]]
    n = library.cites(texts)
    return [{"key": k, "title": library.TITLES[k], "path": library.PATHS[k], "cites": n[k]} for k in library.CITE_KEYS]


def knowledge_hits(run: TeamRun, mgr: Any, scrub: Callable[[str], str], data_dir: str) -> list[dict[str, Any]]:
    """What the roles looked up: their 查知识库 calls, and their reads of the knowledge base's data files."""
    hits_of = getattr(mgr, "knowledge_hits", None)
    history = getattr(mgr, "history", None) or getattr(getattr(mgr, "ses", None), "history", None)
    marker = "/".join(Path(data_dir).expanduser().parts[-2:]) if data_dir else ""
    out: list[dict[str, Any]] = []
    for k in run.order:
        for att in run.lane(k)["attempts"]:
            aid = att.get("agent")
            if not aid:
                continue
            for h in (hits_of(aid) if hits_of is not None else []):
                out.append({"role": k, "at": h.get("at"), "kind": "search", "text": scrub(str(h.get("detail") or ""))})
            if marker and history is not None and str(aid).startswith("s-"):
                for c in history(aid):  # reading a data file, or copying it into the project (cp …/data/x.json …)
                    detail = str(c.get("detail") or "")
                    if c.get("tool") != "查知识库" and marker in detail:
                        names = re.findall(re.escape(marker) + r"/([\w.-]+)", detail)
                        out.append({"role": k, "at": c.get("at"), "kind": "data",
                                    "text": "、".join(dict.fromkeys(names)) or detail.rsplit("/", 1)[-1].split(":")[0]})
    out.sort(key=lambda h: float(h.get("at") or 0))
    return out[-60:]


def _case(c: dict[str, Any]) -> dict[str, Any]:
    return {k: c.get(k) for k in ("id", "ac", "name", "file", "status", "owner", "ms", "message", "verdict", "tier")}


def _duration(att: dict[str, Any], live: dict[str, Any] | None, now: float) -> float:
    """An attempt's own working time: not while it waits in KiroCrew's queue, up to now while it runs."""
    if live is not None and live["queued"]:
        return 0.0
    return max(0.0, float(att.get("ended") or now) - float(att.get("started") or att.get("requested_at") or now))


def lane(run: TeamRun, key: str, *, mgr: Any, scrub: Callable[[str], str], now: float) -> dict[str, Any]:
    role, ln = run.roles[key], run.lane(key)
    atts = ln["attempts"]
    att = atts[-1] if atts else None
    live = None
    if att is not None and att.get("agent") and not att.get("ended"):
        info = find_agent(mgr, att["agent"])
        live = agent_fields(info) if info is not None else None
    status = ln["status"]
    if status in ACTIVE and live is not None and not live["done"]:
        status = live_status(att["kind"], live)
    credits = [a["credits"] for a in atts if a.get("credits") is not None]
    defaults = run.team.get("defaults", {})
    return {
        "key": key, "title": role["title"], "title_en": english(run, key, "title_en"), "emoji": role.get("emoji", ""),
        "model": role.get("model") or defaults.get("model") or "", "status": status,
        "depends_on": list(role["depends_on"]), "writable": list(role["writable"]), "attempt": max(1, len(atts)),
        "agent": agent(att, live, mgr=mgr, scrub=scrub, now=now) if att is not None and att.get("agent") else None,
        "worktree": ln["worktree"], "branch": ln["branch"], "files": [f for f in ln["files"] if not gitwork.is_host_path(f["path"])], "lines": dict(ln["lines"]),
        "commits": list(ln["commits"]), "violations": [p for p in ln["violations"] if not gitwork.is_host_path(p)],
        "owns_tests": [c["id"] for c in run.s["tests"]["cases"] if c.get("owner") == key],
        "started_at": ln["started_at"], "done_at": ln["done_at"],
        "active_s": round(sum(_duration(a, live if a is att else None, now) for a in atts), 1),
        "credits": round(sum(credits), 3) if credits else None, "summary": ln["summary"],
        "phase": role.get("phase") or "", "stage": role.get("stage") or "", "stage_en": english(run, key, "stage_en"),
        "mission": role.get("mission") or "", "mission_en": english(run, key, "mission_en"),
        "aidlc_agent": role.get("aidlc_agent") or "", "gate": ln.get("gate") if role.get("gate") == "human" else None,
        "gate_label": role.get("gate_label") or "", "gate_label_en": english(run, key, "gate_label_en"), "gate_preset": str(role.get("gate_preset") or ""),
        "gate_revise_preset": str(role.get("gate_revise_preset") or ""),
        "gate_revise_risk": clean_risk(role.get("gate_revise_risk")),
        "kinds": [a["kind"] for a in atts],
        "session": _session(atts, mgr),
        "icon": str(role.get("icon") or key),
        "assignment": run.assignment(key),
        "doing": str((att or {}).get("label") or run.assignment(key)),
        "doing_msg": messages.label_of((att or {}).get("label")),  # a round's own words (修 build、unit …) by code
        "member": role.get("member") or role.get("template") or "", "member_kind": _member_kind(atts, mgr),
        "optional": bool(role.get("optional")), "overrule": bool(ln.get("overrule")),
        "awaiting_member": str(ln.get("awaiting_member") or "") or None,
        "delivery_gate": bool(role.get("delivery")),
        "questions": [question(q) for q in (run.s.get("questions") or {}).get(key) or []],
        "answers": [{k: a[k] for k in ("id", "choice", "option", "text", "differs")} for a in (run.s.get("answers") or {}).get(key) or []],
        "talk": [{k: x.get(k) for k in ("who", "text", "at", "changed")} for x in (run.s.get("talks") or {}).get(key) or []],
        "can_discuss": role.get("gate") == "human" and run.discuss_allowed(key),
        "tests_first": (ln.get("first") or {}).get("status"),
    }


def _member_kind(atts: list[dict[str, Any]], mgr: Any) -> str | None:
    """How the role's session was booted: as its Crew member, from the template of that name, or Crew's default."""
    agent_of = getattr(mgr, "agent_of", None)
    for att in reversed(atts):
        got = agent_of(att.get("agent")) if agent_of is not None and att.get("agent") else None
        if got:
            return got.get("kind") or "default"
    return None


def _session(atts: list[dict[str, Any]], mgr: Any) -> str | None:
    """The Kiro Crew session the role works in (the session runner), for 「在 Crew 里打开会话」."""
    slot_of = getattr(mgr, "slot_of", None)
    if slot_of is None:
        return None
    for att in reversed(atts):
        for aid in [att.get("agent"), *att.get("dead", [])]:
            slot = slot_of(aid) if aid else None
            if slot:
                return slot
    return None


def agent(att: dict[str, Any], live: dict[str, Any] | None, *, mgr: Any, scrub: Callable[[str], str],
          now: float) -> dict[str, Any]:
    """AgentLive for the lane's current (or last) attempt: live from its session, else what was kept when it ended."""
    snap = att.get("snap") or {}
    aid = att["agent"]
    started = float((live or {}).get("started") or att.get("started") or att.get("requested_at") or now)
    recent = list(mgr.recent(aid)) if mgr is not None else []
    if live is not None:
        tail = (live["text"] or live["result"]).strip()
        view = {"turns": live["turns"], "tool_count": live["tool_count"], "last_tool": short(scrub(live["last_tool"])),
                "last_activity": live["last_activity"], "text_tail": tail[-300:] or None,
                "queued_reason": live["queued_reason"] if live["queued"] else None, "error": live["error"] or att.get("error")}
    else:
        view = {k: snap.get(k) for k in ("turns", "tool_count", "last_tool", "last_activity", "text_tail")}
        view.update(turns=view["turns"] or 0, tool_count=view["tool_count"] or 0, last_tool=view["last_tool"] or "",
                    queued_reason=None, error=att.get("error"))
    return {"id": aid, "turns": view["turns"], "tool_count": view["tool_count"], "last_tool": view["last_tool"],
            "last_activity": view["last_activity"], "started": started,
            "elapsed_s": round(max(0.0, float(att.get("ended") or now) - started), 1),
            "queued_reason": view["queued_reason"], "error": view["error"],
            "recent_tools": recent or list(snap.get("recent_tools") or []), "text_tail": view["text_tail"],
            "credits": att.get("credits")}
