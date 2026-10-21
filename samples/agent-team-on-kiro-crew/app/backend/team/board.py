"""``GET /board``: exactly the ``Board`` type of ui/src/types.ts, built from the runs' state plus what KiroCrew says
about their agents right now (cheap attribute reads), so the live parts stay live between ticks."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from . import gitwork
from .sessions import agent_fields, find_agent
from .team import ACTIVE, TeamRun, live_status
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
        "sign_block": run.sign_block(),
        "tests": {"at": t["at"], "command": t.get("command", ""), "cases": [_case(c) for c in t["cases"]],
                  "passed": t["passed"], "failed": t["failed"], "total": t["total"],
                  "history": [{"at": h["at"], "passed": h["passed"], "failed": h["failed"]} for h in t["history"]]},
        "merges": [{k: m.get(k) for k in ("role", "sha", "at", "status", "files", "note")} for m in s["merges"]],
        "events": [{**e, "data": e.get("data")} for e in run.events if not (e.get("kind") == "violation" and any(p in str(e.get("text", "")) for p in gitwork.HOST_PREFIXES))],
        "standards": list(s.get("standards") or []),
        "roster": [dict(x) for x in s["roster"]] if s.get("roster") else None,
        "imported": dict(s["imported"]) if s.get("imported") else None,
        "signoff": dict(s["signoff"]) if s.get("signoff") else None,
        "requirement": s.get("requirement") or "",
        "knowledge": {"source": (crew.knowledge_view(str(kb.get("source") or "")) if crew is not None else None)
                      or (source_row(str(kb["source"]), None) if kb.get("source") else None),
                      "hits": knowledge_hits(run, mgr, scrub, str(kb.get("data_dir") or ""))},
        "crew_members": crew_members(run, crew),
        "delivery": {**run.delivery(), "confirmed": bool(s.get("delivery"))},
        "issue": run.issue(),
        "pr": run.pr(),
    }


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
    return {k: c.get(k) for k in ("id", "ac", "name", "file", "status", "owner", "ms", "message")}


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
        "key": key, "title": role["title"], "emoji": role.get("emoji", ""),
        "model": role.get("model") or defaults.get("model") or "", "status": status,
        "depends_on": list(role["depends_on"]), "writable": list(role["writable"]), "attempt": max(1, len(atts)),
        "agent": agent(att, live, mgr=mgr, scrub=scrub, now=now) if att is not None and att.get("agent") else None,
        "worktree": ln["worktree"], "branch": ln["branch"], "files": [f for f in ln["files"] if not gitwork.is_host_path(f["path"])], "lines": dict(ln["lines"]),
        "commits": list(ln["commits"]), "violations": [p for p in ln["violations"] if not gitwork.is_host_path(p)],
        "owns_tests": [c["id"] for c in run.s["tests"]["cases"] if c.get("owner") == key],
        "started_at": ln["started_at"], "done_at": ln["done_at"],
        "active_s": round(sum(_duration(a, live if a is att else None, now) for a in atts), 1),
        "credits": round(sum(credits), 3) if credits else None, "summary": ln["summary"],
        "phase": role.get("phase") or "", "stage": role.get("stage") or "", "mission": role.get("mission") or "",
        "aidlc_agent": role.get("aidlc_agent") or "", "gate": ln.get("gate") if role.get("gate") == "human" else None,
        "gate_label": role.get("gate_label") or "", "gate_preset": str(role.get("gate_preset") or ""),
        "gate_revise_preset": str(role.get("gate_revise_preset") or ""),
        "kinds": [a["kind"] for a in atts],
        "session": _session(atts, mgr),
        "icon": str(role.get("icon") or key),
        "assignment": run.assignment(key),
        "doing": str((att or {}).get("label") or run.assignment(key)),
        "member": role.get("member") or "", "member_kind": _member_kind(atts, mgr),
        "deployed": dict(ln["deployed"]) if ln.get("deployed") else None,
        "optional": bool(role.get("optional")), "overrule": bool(ln.get("overrule")),
        "awaiting_member": str(ln.get("awaiting_member") or "") or None,
        "delivery_gate": bool(role.get("delivery")),
        "questions": [dict(q, options=[dict(o) for o in q["options"]]) for q in (run.s.get("questions") or {}).get(key) or []],
        "answers": [{k: a[k] for k in ("id", "choice", "option", "text", "differs")} for a in (run.s.get("answers") or {}).get(key) or []],
        "talk": [{k: x.get(k) for k in ("who", "text", "at", "changed")} for x in (run.s.get("talks") or {}).get(key) or []],
        "can_discuss": role.get("gate") == "human" and run.discuss_allowed(key),
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
