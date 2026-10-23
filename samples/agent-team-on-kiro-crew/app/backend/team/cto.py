"""``GET /cto``: the CTO view's data, in the shape the page (ui/src/cto) and the offline page (cto/offline.html) read.

- ``items``: deliveries. The company's history is simulated and ships with the app (cto/history.json, made by
  scripts/cto_history.py); its dates are moved so that its last day is today. Every run of this app a person signed off
  joins it as 实测, labelled with its 交付标签 (delivery.py), with the decisions people made at its gates. Each one has
  its Issue (``issue``, ``reporter``, ``created``) and the PR that took it into main (``pr``); a fix raised after
  something shipped links back to it (``origin``) and that one lists it (``defects``).
- ``wip``: what is in progress now: simulated cards, plus every run of this app that is going, waits at a gate, or is
  delivered and waits for its signature. Their cards move as the run does, and open the run on the board.
- ``meta``: the period, the business lines, and the figures the page's 口径 uses.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

from .constants import APP_ROOT
from .delivery import LINES
from .team import ACTIVE, TeamRun

HISTORY = APP_ROOT / "cto" / "history.json"
OFFLINE = APP_ROOT / "cto" / "offline.html"
KIND_KEY = {"新应用": "app", "新功能": "feat", "修复": "fix"}
SIZE_KEY = {"小": "S", "中": "M", "大": "L"}
# the kanban's columns: a run waiting at a gate sits where that gate is; one at work sits in its role's AI-DLC phase
GATE_COL = {"范围": "构思", "需求": "启动", "方案": "启动", "上线": "运维", "安全": "运维"}
PHASE_COL = {"ideation": "构思", "inception": "启动", "construction": "构建", "review": "构建", "operation": "运维"}
NOTE_MAX = 60
_LEAD = re.compile(r"^(?:批准上线|批准发布到预发|批准|按上线前体检退回|按风险提示退回|按审查意见再改一轮)[。：:，,]?\s*")
_BOUNCE_TO = re.compile(r"打回\s*[:：][^。；;\n]*[。；;]?\s*")

_cache: dict[str, Any] = {"mtime": None, "data": None}


def load_history(path: Path = HISTORY) -> dict[str, Any]:
    """The simulated history (read again only when the file changes)."""
    mtime = path.stat().st_mtime
    if _cache["mtime"] != mtime or _cache.get("path") != str(path):
        _cache.update(mtime=mtime, path=str(path), data=json.loads(path.read_text(encoding="utf-8")))
    return _cache["data"]


def build(runs: dict[str, TeamRun], now: float, *, events_of: Callable[[TeamRun], list[dict[str, Any]]],
          history: dict[str, Any] | None = None) -> dict[str, Any]:
    h = history if history is not None else load_history()
    today = date.fromtimestamp(now)
    shift = (today - date.fromisoformat(h["meta"]["today"])).days
    mv = lambda iso: (date.fromisoformat(iso) + timedelta(days=shift)).isoformat()  # noqa: E731
    meta = {**h["meta"], "today": today.isoformat(), "agentStart": mv(h["meta"]["agentStart"]),
            "weeks": [mv(w) for w in h["meta"]["weeks"]]}
    items = [{**i, "ship": mv(i["ship"]), **({"created": mv(i["created"])} if i.get("created") else {})} for i in h["items"]]
    wip = [dict(w) for w in h["wip"]]
    for run in sorted(runs.values(), key=lambda r: float(r.s.get("started_at") or 0)):
        if run.s.get("hidden"):
            continue
        if run.s.get("signoff"):
            items.append(real_item(run, events_of(run)))
        else:
            card = live_card(run, now)
            if card is not None:
                wip.append(card)
    reals = [i for i in items if i.get("real")]
    meta["realAvgMins"] = round(sum(i["mins"] for i in reals) / len(reals)) if reals else 0
    items.sort(key=lambda i: (i["ship"], i["t"]), reverse=True)
    return {"meta": meta, "items": items, "wip": wip}


def _labels(run: TeamRun) -> dict[str, Any]:
    d, iss = run.delivery(), run.issue()
    return {"t": d["name"], "line": LINES.index(d["line"]), "kind": KIND_KEY[d["kind"]], "size": SIZE_KEY[d["size"]],
            "issue": iss["id"], "reporter": iss["reporter"], "created": date.fromtimestamp(iss["created_at"] or 0).isoformat()}


def real_item(run: TeamRun, events: list[dict[str, Any]]) -> dict[str, Any]:
    """A run a person signed off: one delivery, 实测. Its cycle runs until the signature; 用时 is the run's own time."""
    s, sig = run.s, run.s["signoff"]
    started = float(s.get("started_at") or sig["at"])
    ended = float(s.get("ended_at") or sig["at"])
    mins = max(1, round((ended - started - float(s.get("paused_s") or 0)) / 60))
    return {**_labels(run), "period": "agent", "ship": date.fromtimestamp(float(sig["at"])).isoformat(),
            "cyc": round(max(0.0, float(sig["at"]) - started) / 86400, 3), "mins": mins, "signer": sig.get("by") or "",
            "real": run.rid, "tests": sig.get("tests") or f"{s['tests']['passed']}/{s['tests']['total']}",
            "members": sum(run.lane(k)["status"] != "skipped" for k in run.order), "decisions": decisions(run, events),
            "pr": (run.pr() or {}).get("number"), "defects": [],
            **caught_of(run, events, float(sig["at"]))}


def caught_of(run: TeamRun, events: list[dict[str, Any]], now: float) -> dict[str, Any]:
    """更稳 for one run: what was sent back before release (by the checks, the independent review and people at the
    gates, as its 价值流 counts them) and the risks people noted when they sent something back."""
    f = flow(run, events, now)
    return {"caught": f["sent_back"], "risks": f["risks"]}


def decisions(run: TeamRun, events: list[dict[str, Any]]) -> list[list[str]]:
    """What people decided at the run's gates, in order: [「批准需求」, 「补充规则：…」]. A run imported with its own
    list (``decisions`` in its record) keeps that one."""
    kept = run.s.get("decisions")
    if isinstance(kept, list) and all(isinstance(x, list) and len(x) == 2 for x in kept):
        return [[str(a), str(b)] for a, b in kept]
    out = []
    for e in events:
        if e.get("from") != "person" or e.get("kind") not in ("approved", "bounce"):
            continue
        role = run.roles.get(str(e.get("role") or "")) or {}
        gate = str(role.get("gate_label") or role.get("title") or "")
        verb = "批准" if e["kind"] == "approved" else "退回"
        text = str(e.get("text") or "")
        note = text.split("：", 1)[1] if "：" in text else ""
        note = _BOUNCE_TO.sub("", _LEAD.sub("", note.strip())).strip()
        if len(note) > NOTE_MAX:
            note = note[:NOTE_MAX - 1] + "…"
        out.append([verb + gate, note or ("无补充意见" if verb == "批准" else "按审查意见再改一轮")])
    return out


def live_card(run: TeamRun, now: float) -> dict[str, Any] | None:
    """The kanban card of a run that has not been signed off: at work, at a gate, or delivered and waiting for its
    signature. A run that failed or was stopped delivered nothing: no card."""
    base = {**_labels(run), "live": True, "real": run.rid}
    if run.ended:
        if run.s["status"] != "done" or run.sign_block():
            return None
        waited = (now - float(run.s.get("ended_at") or now)) / 3600
        return {**base, "state": "wait", "col": "运维", "gate": "签字放行", "role": "", "who": "负责人",
                "hours": round(max(0.0, waited), 2), "focus": "已交付并通过检查，待签字放行", "pr": (run.pr() or {}).get("number")}
    pending = [k for k in run.order if run.lane(k).get("gate") == "pending"]
    if pending:
        key = pending[0]
        role = run.roles[key]
        label = str(role.get("gate_label") or run.title(key))
        since = max([float(e.get("at") or 0) for e in run.events if e.get("kind") == "gate" and e.get("role") == key] or [now])
        if role.get("plan") or role.get("delivery"):
            focus = "确认分工、验收标准与交付标签"
        elif not role.get("writable"):
            focus = "独立审查已出结论，待负责人决定"
        else:
            focus = f"{label}待负责人确认"
        return {**base, "state": "wait", "col": GATE_COL.get(label, PHASE_COL.get(str(role.get("phase") or ""), "运维")),
                "gate": f"{label}关卡", "role": key, "who": "负责人", "hours": round(max(0.0, now - since) / 3600, 2),
                "focus": focus}
    working = [k for k in run.order if run.lane(k)["status"] in ACTIVE]
    latest = max(working, key=lambda k: float(run.lane(k).get("started_at") or 0)) if working else None
    col = PHASE_COL.get(str(run.roles[latest].get("phase") or ""), "构建") if latest else "构思"
    return {**base, "state": "agent", "col": col, "members": max(1, len(working)),
            "mins": max(0, round((now - float(run.s.get("started_at") or now)) / 60))}


def _short(text: str) -> str:
    note = text.split("：", 1)[1] if "：" in text else ""
    note = _BOUNCE_TO.sub("", _LEAD.sub("", note.strip())).strip()
    return note[:NOTE_MAX - 1] + "…" if len(note) > NOTE_MAX else note


def flow(run: TeamRun, events: list[dict[str, Any]], now: float) -> dict[str, Any]:
    """价值流 of one run for 交付详情: where its time went, from its Issue (the run's start) to the signature.

    ``segments`` cut the run in time: ``person`` while a gate waits for a person (from the gate to their decision) and
    while a delivered run waits for its signature; ``agent`` the rest, by the kanban column of the role that was set to
    work last (构思/启动/构建/运维), and 返工 from a role's second round until a role works for the first time or a gate
    stops the run. ``marks`` are the moments: gates, decisions, the checks or a review sending work back, the
    deployment, the signature, the PR going into main. Seconds count from the run's start (``at`` in the board's
    links). The rest is the numbers 交付详情 shows: agent and person time, credits, checks, send-backs, review."""
    s = run.s
    t0 = float(s.get("started_at") or now)
    sig = s.get("signoff") if isinstance(s.get("signoff"), dict) else None
    ended = float(s.get("ended_at") or now) if run.ended else None
    stop = ended if ended is not None else now
    evs = sorted((e for e in events if e.get("at") is not None), key=lambda e: (float(e["at"]), int(e.get("seq") or 0)))
    rel = lambda t: round(max(0.0, float(t) - t0), 1)  # noqa: E731
    title = lambda k: run.title(k) if k in run.roles else str(k or "")  # noqa: E731
    col_of = lambda k: PHASE_COL.get(str((run.roles.get(k) or {}).get("phase") or ""), "构建")  # noqa: E731

    person, marks, decided = [], [], []
    curated = s.get("decisions") if isinstance(s.get("decisions"), list) else None
    told = -1e9  # the last time a person sent work back: the bounces that carry it out are theirs, not a review's
    open_at: set[str] = set()  # gates open and not decided yet: a 讨论 there opens it again, its time is the same wait
    for i, e in enumerate(evs):
        kind, key, src = e.get("kind"), e.get("role"), e.get("from")
        if kind == "gate" and key in run.roles and key in open_at:
            continue
        if kind == "gate" and key in run.roles:
            open_at.add(key)
            role = run.roles[key]
            label = str(role.get("gate_label") or title(key))
            dec = next((x for x in evs[i + 1:] if x.get("role") == key and x.get("from") == "person"
                        and x.get("kind") in ("approved", "bounce")), None)
            to = float(dec["at"]) if dec else stop
            person.append({"from": rel(e["at"]), "to": rel(to), "who": "person", "col": GATE_COL.get(label, col_of(key)),
                           "phase": str(role.get("phase") or ""), "label": f"等人批准 · {label}关卡", "roles": [key], "gate": key,
                           "decision": ("批准" if dec["kind"] == "approved" else "退回") if dec else None})
            marks.append({"at": rel(e["at"]), "kind": "gate", "role": key, "label": f"{label}关卡：等人批准"})
        elif kind in ("approved", "bounce") and src == "person" and key in run.roles:
            open_at.discard(key)
            label = str(run.roles[key].get("gate_label") or title(key))
            verb = "批准" if kind == "approved" else "退回"
            told = float(e["at"]) if kind == "bounce" else told
            decided.append({"at": rel(e["at"]), "role": key, "gate": verb + label, "note": _short(str(e.get("text") or ""))})
            marks.append({"at": rel(e["at"]), "kind": kind, "role": key, "label": verb + label})
        elif kind == "bounce" and src == "tests":
            marks.append({"at": rel(e["at"]), "kind": "check", "role": key, "label": f"检查不过，退回{title(key)}"})
        elif kind == "bounce" and src in run.roles and not str(e.get("text") or "").startswith("按人的意见") and float(e["at"]) - told > 2:
            marks.append({"at": rel(e["at"]), "kind": "review", "role": key, "label": f"{title(src)}要改，退回{title(key)}"})
        elif kind == "deployed":
            marks.append({"at": rel(e["at"]), "kind": "deployed", "role": key, "label": "部署到本机"})
    if curated and len(curated) == len(decided):  # an imported run's own wording, at its decisions' moments
        for d, (gate, note) in zip(decided, curated):
            d.update(gate=str(gate), note=str(note))
    for d in decided:
        d["note"] = d["note"] or ("无补充意见" if d["gate"].startswith("批准") else "按审查意见再改一轮")

    # agent time: the run's span outside the gates, cut where the work moves to another column or into a second round
    states, seen = [], set()
    for e in evs:
        key = e.get("role")
        if e.get("kind") != "spawned" or key not in run.roles:
            continue
        again = key in seen
        seen.add(key)
        label = "返工" if again else col_of(key)
        if states and states[-1]["label"] == label and (again or states[-1]["col"] == col_of(key)):
            if key not in states[-1]["roles"]:
                states[-1]["roles"].append(key)  # set to work together: one segment
            continue
        states.append({"t": float(e["at"]), "col": col_of(key), "phase": str(run.roles[key].get("phase") or ""),
                       "label": label, "roles": [key]})
    cuts = sorted({t0, stop, *[t0 + p["from"] for p in person], *[min(stop, t0 + p["to"]) for p in person],
                   *[x["t"] for x in states if t0 < x["t"] < stop]})
    waits = [(t0 + p["from"], t0 + p["to"]) for p in person]
    agent: list[dict[str, Any]] = []
    for a, b in zip(cuts, cuts[1:]):
        if b - a < 0.5 or any(w0 <= a and b <= w1 for w0, w1 in waits):
            continue
        st = next((x for x in reversed(states) if x["t"] <= a + 0.5), states[0] if states else None)
        if st is None:
            st = {"col": "构思", "phase": "", "label": "建仓库", "roles": []}
        if agent and agent[-1]["label"] == st["label"] and abs(agent[-1]["to"] - rel(a)) < 1:
            agent[-1]["to"] = rel(b)
            continue
        if b - a < 3 and not any(x["t"] == a for x in states):  # the moment between a decision and the next work handed out
            continue
        agent.append({"from": rel(a), "to": rel(b), "who": "agent", "col": st["col"], "phase": st["phase"],
                      "label": st["label"], "roles": list(st["roles"]), "gate": None, "decision": None})
    # 签字放行: from the delivery to the signature (still waiting when there is none yet)
    sign = None
    if ended is not None and s["status"] == "done" and not run.sign_block():
        sign = {"from": rel(ended), "to": rel(float(sig["at"]) if sig else now), "who": "person", "col": "运维", "phase": "operation",
                "label": "签字放行", "roles": [], "gate": "signoff", "decision": "签字" if sig else None}
    segments = sorted(agent + person + ([sign] if sign and sign["to"] - sign["from"] >= 1 else []), key=lambda x: x["from"])
    if sig:
        marks.append({"at": rel(sig["at"]), "kind": "signoff", "role": None, "label": f"{sig.get('by') or ''} 签字放行"})
        pr = run.pr() or {}
        if pr.get("state") == "merged":
            marks.append({"at": rel(sig["at"]), "kind": "merged", "role": None, "label": f"PR #{pr.get('number')} 合入 main"})
    marks.sort(key=lambda m: m["at"])

    t = s["tests"]
    cases = t.get("cases") or []
    known = [a["credits"] for k in run.order for a in run.lane(k)["attempts"] if a.get("credits") is not None]
    agent_s = sum(x["to"] - x["from"] for x in segments if x["who"] == "agent")
    person_s = sum(x["to"] - x["from"] for x in segments if x["who"] == "person")
    count = lambda k: sum(m["kind"] == k for m in marks)  # noqa: E731
    return {"run": run.rid, "status": s["status"], "started_at": t0, "end": rel(float(sig["at"]) if sig else stop),
            "segments": segments, "marks": marks, "decisions": decided,
            "agent_s": round(agent_s, 1), "person_s": round(person_s, 1), "gates": sum(x["gate"] not in (None, "signoff") for x in segments),
            "credits": round(sum(known), 1) if known else None,
            "members": sum(run.lane(k)["status"] != "skipped" for k in run.order),
            "tests": {"passed": int(t.get("passed") or 0), "total": int(t.get("total") or 0),
                      "enterprise": sum(str(c.get("file") or "").startswith("tests/enterprise/") for c in cases)},
            "sent_back": {"person": count("bounce"), "review": count("review"), "checks": count("check")},
            "risks": [{"what": str(r.get("what") or ""), "amount": r.get("amount"), "gate": str(r.get("gate") or ""),
                       "role": r.get("role"), "at": rel(r["at"]) if r.get("at") is not None else 0.0}
                      for r in s.get("risks") or [] if isinstance(r, dict)],
            "rework": sum(x["label"].startswith("返工") for x in segments if x["who"] == "agent"),
            "review": str(s.get("verdict") or ""), "deployed": any(m["kind"] == "deployed" for m in marks),
            "issue": run.issue(), "pr": run.pr(), "labels": _labels(run), "titles": {k: run.title(k) for k in run.order},
            "team": [{"key": k, "title": run.title(k), "icon": str(run.roles[k].get("icon") or k),
                      "skipped": run.lane(k)["status"] == "skipped",
                      "credits": round(sum(a["credits"] for a in run.lane(k)["attempts"] if a.get("credits") is not None), 1)}
                     for k in run.order]}


def offline(data: dict[str, Any], *, generated: str, path: Path = OFFLINE) -> dict[str, Any]:
    """离线版: the offline page with this moment's data inlined (it opens without Kiro Crew; its jumps say so)."""
    html = path.read_text(encoding="utf-8")
    html = html.replace('data-snapshot=""', f'data-snapshot="{generated}"', 1)
    html = html.replace("/*__DATA__*/{}", json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"), 1)
    return {"name": f"CTO视图-离线版-{data['meta']['today']}.html", "html": html}
