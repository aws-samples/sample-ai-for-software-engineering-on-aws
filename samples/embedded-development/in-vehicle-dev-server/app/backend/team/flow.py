"""``GET /runs/<rid>/flow`` (交付详情): where one run's time went, from its records only. Seconds count from the run's
start; nothing is estimated, and a figure with no record behind it is ``None``.

Segments, each a measured span:

- ``agent``: one attempt of a role, from its session starting to its reply (``lanes.<role>.attempts``).
- ``gate``: a human gate waiting, from its ``gate`` event to the person's decision (``approved`` or ``bounce`` from the
  person); a 讨论 there keeps it open.
- ``console``: a bench action waiting at the operator console, from the run's request to the console's decision in the
  bench's action record (``actions.jsonl``; the requester is ``vstatd-team <rid>``, as the scorecard ties them).
- ``checks``: one round of the checks the app ran (before the bench, after it), ending at its ``tests`` event and as
  long as its checks' own wall times added up (``data.ms``; a round recorded without them has no segment).
- ``rerun``: the independent rerun, from the bench event that starts it to its ``tests`` event.

Moments: the send-backs (every ``bounce``), the rounds with a failing check, the approvals and the sign-off.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from . import messages, scorecard
from .constants import APP_NAME


def _iso(text: Any) -> float | None:
    """A bench record's time (``2027-01-15T08:30:00.123Z``)."""
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _union(spans: list[tuple[float, float]]) -> float:
    """Seconds covered by at least one span (parallel roles count once)."""
    out, end = 0.0, float("-inf")
    for a, b in sorted(spans):
        if b > end:
            out += b - max(a, end)
            end = b
    return out


def _failing(data: dict[str, Any]) -> list[str]:
    if isinstance(data.get("cases"), list):
        return [str(c[0]) for c in data["cases"] if isinstance(c, list) and len(c) > 1 and c[1] != "pass"]
    return [str(c[0]) for c in data.get("checks") or [] if isinstance(c, list) and len(c) > 1 and c[1] != "PASS"]


def build(s: dict[str, Any], events: list[dict[str, Any]], recs: list[dict[str, Any]], now: float) -> dict[str, Any]:
    """RunFlow of ui/src/types.ts for the run whose state is *s*."""
    t0 = float(s.get("started_at") or now)
    live = s.get("status") not in ("done", "failed", "stopped")
    sig = s.get("signoff") if isinstance(s.get("signoff"), dict) else None
    stop = now if live else float(s.get("ended_at") or now)
    end = float(sig["at"]) if sig and sig.get("at") else stop
    rel = lambda t: round(max(0.0, float(t) - t0), 1)  # noqa: E731
    roles = [r for r in (s.get("team") or {}).get("roles") or [] if isinstance(r, dict)]
    titles = {str(r["key"]): str(r.get("title") or r["key"]) for r in roles}
    lanes = s.get("lanes") or {}
    evs = sorted((e for e in events if e.get("at") is not None), key=lambda e: (float(e["at"]), int(e.get("seq") or 0)))
    segs: list[dict[str, Any]] = []

    gates = {str(r["key"]): str(r.get("gate_label") or "") or titles[str(r["key"])] for r in roles}

    def say(code: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        params = messages.clean(params)
        return {"label": messages.render(code, params, lambda k: titles.get(k, k), lambda k: gates.get(k, k)).strip(),
                "code": code, "params": params}

    def seg(kind: str, a: float, b: float | None, label: dict[str, Any], role: str | None = None, result: str | None = None) -> None:
        """*label*: say(); *result*: a result code (result.*), shown as its text."""
        segs.append({"kind": kind, "from": rel(a), "to": rel(b if b is not None else stop), "role": role, **label,
                     "result": messages.ZH[f"result.{result}"] if result else None, "result_code": result,
                     "open": b is None and live})

    def mark(at: float, kind: str, role: str | None, e: dict[str, Any] | None = None, label: dict[str, Any] | None = None) -> None:
        """A moment: an event's own text (and code), or *label*."""
        said = label or {"label": str((e or {}).get("text") or ""), "code": (e or {}).get("code"), "params": (e or {}).get("params")}
        marks.append({"at": rel(at), "kind": kind, "role": role, **said})

    credits: list[float] = []
    for key in titles:
        for att in (lanes.get(key) or {}).get("attempts") or []:
            if att.get("credits") is not None:
                credits.append(float(att["credits"]))
            if att.get("started") is None:
                continue
            what = (say("flow.agent", {"r_role": key, "label": att["label"]}) if att.get("label") else
                    say("flow.agent.talk", {"r_role": key}) if att.get("kind") == "discuss" else
                    say("flow.agent.round", {"r_role": key, "n": att.get("n") or 1}))
            seg("agent", float(att["started"]), float(att["ended"]) if att.get("ended") is not None else None,
                what, key, "error" if att.get("error") else None)

    marks: list[dict[str, Any]] = []
    open_gate: dict[str, float] = {}
    rerun_at, before = None, 0
    for e in evs:
        kind, key, src, at = e.get("kind"), e.get("role"), e.get("from"), float(e["at"])
        data = e.get("data") if isinstance(e.get("data"), dict) else {}
        if kind == "gate" and key in titles:
            open_gate.setdefault(key, at)
        elif kind in ("approved", "bounce") and src == "person" and key in open_gate:
            seg("gate", open_gate.pop(key), at, say("flow.gate", {"g_gate": key}), key, "approved" if kind == "approved" else "sent_back")
        if kind == "approved":
            mark(at, "approved", key, e)
        elif kind == "bounce":
            mark(at, "bounce", key, e)
        elif kind == "bench" and data.get("step") == "rerun":
            rerun_at = at
        elif kind == "tests" and data.get("phase") in ("before_bench", "after_bench", "rerun"):
            phase, bad = data["phase"], _failing(data)
            if phase == "rerun":
                if rerun_at is not None:
                    seg("rerun", rerun_at, at, say("flow.rerun"), None, "differs" if data.get("differs") else "same")
                    rerun_at = None
            else:
                before += phase == "before_bench"
                label = say("flow.checks", {"n": before}) if phase == "before_bench" else say("flow.after_bench")
                if isinstance(data.get("ms"), (int, float)):
                    seg("checks", at - data["ms"] / 1000, at, label, None, "fail" if bad else "pass")
            if bad:
                mark(at, "check_fail", None, label=say("flow.check_fail", {"checks": bad[:6], "more": len(bad) > 6}))
    for key, at in open_gate.items():
        seg("gate", at, None, say("flow.gate", {"g_gate": key}), key)
    if rerun_at is not None:
        seg("rerun", rerun_at, None, say("flow.rerun"))

    me, mine = f"{APP_NAME} {s.get('id')}", {}
    for r in recs:
        if r.get("event") == "request" and r.get("requested_by") == me and _iso(r.get("at")) is not None:
            mine[str(r.get("id"))] = r
        elif r.get("event") == "decision" and str(r.get("id")) in mine:
            q = mine.pop(str(r.get("id")))
            verdict = str(r.get("verdict") or "")
            seg("console", _iso(q["at"]), _iso(r.get("at")), say("flow.console", {"action": q.get("action")}), None,
                verdict if verdict in ("approved", "refused") else None)
    for q in mine.values():  # no decision: the console's own timeout ends the wait
        a = _iso(q["at"])
        b = a + float(q["timeout_s"]) if isinstance(q.get("timeout_s"), (int, float)) and a + float(q["timeout_s"]) < stop else None
        seg("console", a, b, say("flow.console", {"action": q.get("action")}), None, "timeout" if b is not None else None)

    if sig and sig.get("at"):
        mark(sig["at"], "signoff", None, label=say("flow.signoff", {"by": sig.get("by") or ""}))
    segs.sort(key=lambda x: (x["from"], x["to"]))
    marks.sort(key=lambda m: m["at"])

    span = lambda *kinds: [(x["from"], x["to"]) for x in segs if x["kind"] in kinds]  # noqa: E731
    root = Path(str(s.get("repo") or "")).parent / "results"
    rounds = len(scorecard._rounds(root)) + len(scorecard._after(root)) if s.get("repo") else None
    checked = span("checks", "rerun")
    return {
        "run": str(s.get("id") or ""), "title": str(s.get("title") or ""), "status": str(s.get("status") or ""),
        "started_at": t0, "end": rel(end), "live": live, "signed": bool(sig),
        "segments": segs, "marks": marks,
        "roles": [{"key": k, "title": t, "title_en": str(next((r.get("title_en") for r in roles if r["key"] == k), "") or ""),
                   "gate_label": str(next((r.get("gate_label") for r in roles if r["key"] == k), "") or ""),
                   "gate_label_en": str(next((r.get("gate_label_en") for r in roles if r["key"] == k), "") or ""),
                   "icon": str(next((r.get("icon") for r in roles if r["key"] == k), "") or k)}
                  for k, t in titles.items()],
        "totals": {"elapsed_s": rel(end), "agent_s": round(_union(span("agent")), 1) if span("agent") else None,
                   "person_s": round(_union(span("gate", "console")), 1) if span("gate", "console") else None,
                   "gate_s": round(_union(span("gate")), 1) if span("gate") else None,
                   "console_s": round(_union(span("console")), 1) if span("console") else None,
                   "check_s": round(sum(b - a for a, b in checked), 1) if checked else None,
                   "credits": round(sum(credits), 1) if credits else None,
                   "check_rounds": rounds, "send_backs": sum(m["kind"] == "bounce" for m in marks)},
    }
