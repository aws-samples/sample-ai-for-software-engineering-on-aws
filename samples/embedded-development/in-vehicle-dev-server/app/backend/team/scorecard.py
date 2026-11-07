"""``GET /scorecard`` (D8): the rehearsal scorecard of the scenario page, from the records of the runs only.

Read from each run's ``run.json`` (its state), ``events.jsonl``, the approved triage and the results directories beside
its repository (``runs/<run>/``), and the bench's action record (``actions.jsonl``, its entries tied to the run by the
requester the app gives ``cc1.sh``). A figure with no run behind it is ``None`` (shown empty), never 0.

How each figure is taken:

- Findings fixed, justified, deferred: the decisions of the approved triage, the entries it added (TR §4.4: the
  refactor) left out.
- Justifications overturned: a finding the triage proposed to justify that a person answered other than A at the triage
  gate (the send-back event names it), or that a reviewer's 要改 verdict names on a ``推翻说明：`` line while the approved
  triage justifies it (naming it elsewhere, to confirm it, does not count).
- Times: wall clock from the run's start (the requirement given) to the triage approval, to the first round of the
  checks before the bench in which every check passed, and to the sign-off.
- Build repair rounds: the fix rounds the app gave for a failing ``build`` check.
- Check failures caught before the bench: per check, the rounds before the bench whose result was FAIL.
- Log differences: ``logdiff``'s differences over the runs on the bench (the independent rerun judges the last of them
  again and is not counted twice), and how many of them no approved difference explained. Whether one was a real
  change of behaviour is nothing the app records, so that figure is left out.
- Bench actions: the console's decisions on the run's requests (approved, refused: a timeout is a refusal) and the
  reconciles after the run's own latest request.
- Checks whose verdict differed on the independent rerun (D9).

The scenario's "tool calls by permission class" comes from the ``build`` and ``bench`` MCP servers' audit log; the
agents here use neither (D2, D3), so it is not a figure here at all.
"""

from __future__ import annotations

import calendar
import json
import re
import time
from pathlib import Path
from typing import Any

from . import bench as bench_mod
from .constants import APP_NAME
from .store import all_events
from .team import review_verdict
from .team import TRIAGE_FILE
from .triage import FINDING_ID

# A reviewer overturns a justification on a line of its own (team file brief): `推翻说明：F-008`; naming it elsewhere,
# to confirm it, is no overturn.
OVERTURN_LINE = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)、]\s*)?[*_`]*推翻说明[*_`]*\s*[:：]\s*(.+)$", re.M)


def _json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _iso(text: Any) -> float | None:
    try:
        return float(calendar.timegm(time.strptime(str(text), "%Y-%m-%dT%H:%M:%SZ")))
    except ValueError:
        return None


def _since(start: float, at: float | None) -> float | None:
    return round(max(0.0, at - start), 1) if at is not None else None


def records(d: Path | None = None) -> list[dict[str, Any]]:
    """The bench's whole action record (read only; [] when there is none)."""
    try:
        lines = ((Path(d) if d else bench_mod.state_dir()) / "actions.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict):
            out.append(r)
    return out


def bench_actions(rid: str, recs: list[dict[str, Any]]) -> dict[str, int] | None:
    """Decisions on the run's requests and the reconciles after its latest one (None: the run asked for nothing)."""
    me = f"{APP_NAME} {rid}"
    mine: set[str] = set()
    last = None
    out = {"approved": 0, "refused": 0, "reconciled": 0}
    for r in recs:
        ev = r.get("event")
        if ev == "request":
            last = r.get("requested_by")
            if last == me:
                mine.add(str(r.get("id")))
        elif ev == "decision" and str(r.get("id")) in mine and r.get("verdict") in ("approved", "refused"):
            out[r["verdict"]] += 1
        elif ev == "reconcile" and last == me:
            out["reconciled"] += 1
    return out if mine else None


def _rounds(results: Path) -> list[Path]:
    """The rounds of the checks before the bench: ``results/<n>/``, in order."""
    if not results.is_dir():
        return []
    return sorted((p for p in results.iterdir() if p.is_dir() and p.name.isdigit()), key=lambda p: int(p.name))


def _after(results: Path) -> list[Path]:
    if not results.is_dir():
        return []
    return sorted((p for p in results.iterdir() if p.is_dir() and re.fullmatch(r"after-\d+", p.name)),
                  key=lambda p: int(p.name[6:]))


def run_figures(s: dict[str, Any], events: list[dict[str, Any]], recs: list[dict[str, Any]]) -> dict[str, Any]:
    """One run's figures."""
    root = Path(str(s.get("repo") or "")).parent
    started = float(s.get("started_at") or 0)
    checks = (s.get("team") or {}).get("checks") or []
    triage = _json(root / TRIAGE_FILE) if s.get("repo") else None
    approved = triage if isinstance(triage, dict) and isinstance(triage.get("approved"), dict) else None

    findings = None
    justified: set[str] = set()
    if approved:
        rows = [f for f in approved.get("findings") or [] if isinstance(f, dict) and "added" not in f]
        findings = {k: sum(f.get("decision") == d for f in rows) for k, d in
                    (("fixed", "fix"), ("justified", "justify"), ("deferred", "defer"))}
        justified = {str(f.get("id")) for f in approved.get("findings") or [] if isinstance(f, dict)
                     and f.get("decision") == "justify"}

    by_person = sorted({str(i) for e in events if e.get("kind") == "bounce" and isinstance(e.get("data"), dict)
                        for i in e["data"].get("justified") or []})
    readonly = {r["key"] for r in (s.get("team") or {}).get("roles") or [] if not r.get("writable")}
    by_reviewer = sorted({i for k in readonly for a in ((s.get("lanes") or {}).get(k) or {}).get("attempts") or []
                          if a.get("kind") != "discuss" and review_verdict(a.get("summary")) == "changes"
                          for line in OVERTURN_LINE.findall(str(a.get("reply") or ""))
                          for i in FINDING_ID.findall(line) if i in justified})
    overturned = ({"ids": sorted({*by_person, *by_reviewer}), "by_person": by_person, "by_reviewer": by_reviewer}
                  if approved or by_person else None)

    t = s.get("tests") or {}
    first = next((h for h in t.get("history") or [] if not h.get("failed") and h.get("passed")), None)
    sign = s.get("signoff") or {}
    times = {"triage_s": _since(started, _iso(approved["approved"].get("at"))) if approved else None,
             "first_pass_s": _since(started, float(first["at"])) if first else None,
             "signoff_s": _since(started, float(sign["at"])) if sign.get("at") else None}

    results = root / "results"
    before = [c["name"] for c in checks if c.get("when") == "before_bench"]
    rounds = _rounds(results) if s.get("repo") else []
    caught = None
    if rounds and before:
        caught = {n: sum((_json(r / f"{n}.json") or {}).get("verdict") == "FAIL" for r in rounds) for n in before}
    build_rounds = int((t.get("rounds") or {}).get("build", 0)) if rounds and "build" in before else None

    logdiff = None
    for d in _after(results) if s.get("repo") else []:
        details = (_json(d / "logdiff.json") or {}).get("details")
        if isinstance(details, dict) and isinstance(details.get("differences"), int):
            logdiff = logdiff or {"differences": 0, "unexplained": 0}
            logdiff["differences"] += details["differences"]
            logdiff["unexplained"] += int(details.get("unexplained") or 0)

    rerun = s.get("rerun")
    return {"id": s["id"], "title": s.get("title") or "", "status": s.get("status") or "", "started_at": started,
            "signed": bool(sign), "findings": findings, "overturned": overturned, "times": times,
            "build_rounds": build_rounds, "caught": caught, "logdiff": logdiff,
            "bench": bench_actions(s["id"], recs) if s.get("team", {}).get("bench") else None,
            "rerun_differs": [str(x.get("name")) for x in rerun.get("differs") or []] if rerun else None}


def _sum(values: list[Any]) -> Any:
    """The sum of the figures that exist: ints, or dicts of ints key by key (None when none exists)."""
    have = [v for v in values if v is not None]
    if not have:
        return None
    if isinstance(have[0], dict):
        keys = list(dict.fromkeys(k for v in have for k in v))
        return {k: sum(int(v.get(k) or 0) for v in have) for k in keys}
    return sum(have)


def total(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Over the runs. Times are per run only: a sum of separate runs' durations measures nothing."""
    return {"runs": len(rows),
            "findings": _sum([r["findings"] for r in rows]),
            "overturned": _sum([len(r["overturned"]["ids"]) if r["overturned"] else None for r in rows]),
            "build_rounds": _sum([r["build_rounds"] for r in rows]),
            "caught": _sum([r["caught"] for r in rows]),
            "logdiff": _sum([r["logdiff"] for r in rows]),
            "bench": _sum([r["bench"] for r in rows]),
            "rerun_differs": _sum([len(r["rerun_differs"]) if r["rerun_differs"] is not None else None for r in rows])}


def build(states: list[dict[str, Any]], runs_dir: Path, bench_dir: Path | None = None) -> dict[str, Any]:
    """The Scorecard of ui/src/types.ts: the runs on the page's list (not those a person removed), newest first.
    Blocking (it reads the runs' files): call it in a thread."""
    shown = sorted((s for s in states if not s.get("hidden")), key=lambda s: float(s.get("started_at") or 0), reverse=True)
    recs = records(bench_dir)
    rows = [run_figures(s, all_events(Path(runs_dir) / s["id"] / "events.jsonl"), recs) for s in shown]
    return {"runs": rows, "total": total(rows)}
