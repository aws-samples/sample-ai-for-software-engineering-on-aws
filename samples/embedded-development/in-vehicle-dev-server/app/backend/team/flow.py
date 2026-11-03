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

from . import scorecard
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

    def seg(kind: str, a: float, b: float | None, label: str, role: str | None = None, result: str | None = None) -> None:
        segs.append({"kind": kind, "from": rel(a), "to": rel(b if b is not None else stop), "role": role, "label": label,
                     "result": result, "open": b is None and live})

    credits: list[float] = []
    for key in titles:
        for att in (lanes.get(key) or {}).get("attempts") or []:
            if att.get("credits") is not None:
                credits.append(float(att["credits"]))
            if att.get("started") is None:
                continue
            what = att.get("label") or ("讨论" if att.get("kind") == "discuss" else f"第 {att.get('n') or 1} 轮")
            seg("agent", float(att["started"]), float(att["ended"]) if att.get("ended") is not None else None,
                f"{titles[key]} · {what}", key, "出错" if att.get("error") else None)

    marks: list[dict[str, Any]] = []
    open_gate: dict[str, float] = {}
    rerun_at, before = None, 0
    for e in evs:
        kind, key, src, at = e.get("kind"), e.get("role"), e.get("from"), float(e["at"])
        data = e.get("data") if isinstance(e.get("data"), dict) else {}
        if kind == "gate" and key in titles:
            open_gate.setdefault(key, at)
        elif kind in ("approved", "bounce") and src == "person" and key in open_gate:
            label = next((str(r.get("gate_label") or "") for r in roles if r["key"] == key), "") or titles[key]
            seg("gate", open_gate.pop(key), at, f"等人批准 · {label}", key, "批准" if kind == "approved" else "退回")
        if kind == "approved":
            marks.append({"at": rel(at), "kind": "approved", "role": key, "label": str(e.get("text") or "")})
        elif kind == "bounce":
            marks.append({"at": rel(at), "kind": "bounce", "role": key, "label": str(e.get("text") or "")})
        elif kind == "bench" and data.get("step") == "rerun":
            rerun_at = at
        elif kind == "tests" and data.get("phase") in ("before_bench", "after_bench", "rerun"):
            phase, bad = data["phase"], _failing(data)
            if phase == "rerun":
                if rerun_at is not None:
                    seg("rerun", rerun_at, at, "独立重跑全部检查", None, "不同" if data.get("differs") else "一致")
                    rerun_at = None
            else:
                before += phase == "before_bench"
                label = f"检查 第 {before} 轮" if phase == "before_bench" else "台架之后的检查"
                if isinstance(data.get("ms"), (int, float)):
                    seg("checks", at - data["ms"] / 1000, at, label, None, "不过" if bad else "通过")
            if bad:
                marks.append({"at": rel(at), "kind": "check_fail", "role": None,
                              "label": f"检查不过：{'、'.join(bad[:6])}" + ("等" if len(bad) > 6 else "")})
    for key, at in open_gate.items():
        label = next((str(r.get("gate_label") or "") for r in roles if r["key"] == key), "") or titles[key]
        seg("gate", at, None, f"等人批准 · {label}", key)
    if rerun_at is not None:
        seg("rerun", rerun_at, None, "独立重跑全部检查")

    me, mine = f"{APP_NAME} {s.get('id')}", {}
    for r in recs:
        if r.get("event") == "request" and r.get("requested_by") == me and _iso(r.get("at")) is not None:
            mine[str(r.get("id"))] = r
        elif r.get("event") == "decision" and str(r.get("id")) in mine:
            q = mine.pop(str(r.get("id")))
            seg("console", _iso(q["at"]), _iso(r.get("at")), f"操作台 · {q.get('action') or '台架动作'}", None,
                {"approved": "批准", "refused": "拒绝"}.get(str(r.get("verdict")), str(r.get("verdict") or "")))
    for q in mine.values():  # no decision: the console's own timeout ends the wait
        a = _iso(q["at"])
        b = a + float(q["timeout_s"]) if isinstance(q.get("timeout_s"), (int, float)) and a + float(q["timeout_s"]) < stop else None
        seg("console", a, b, f"操作台 · {q.get('action') or '台架动作'}", None, "超时" if b is not None else None)

    if sig and sig.get("at"):
        marks.append({"at": rel(sig["at"]), "kind": "signoff", "role": None, "label": f"{sig.get('by') or ''} 签字放行".strip()})
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
        "roles": [{"key": k, "title": t, "icon": str(next((r.get("icon") for r in roles if r["key"] == k), "") or k)}
                  for k, t in titles.items()],
        "totals": {"elapsed_s": rel(end), "agent_s": round(_union(span("agent")), 1) if span("agent") else None,
                   "person_s": round(_union(span("gate", "console")), 1) if span("gate", "console") else None,
                   "gate_s": round(_union(span("gate")), 1) if span("gate") else None,
                   "console_s": round(_union(span("console")), 1) if span("console") else None,
                   "check_s": round(sum(b - a for a, b in checked), 1) if checked else None,
                   "credits": round(sum(credits), 1) if credits else None,
                   "check_rounds": rounds, "send_backs": sum(m["kind"] == "bounce" for m in marks)},
    }
