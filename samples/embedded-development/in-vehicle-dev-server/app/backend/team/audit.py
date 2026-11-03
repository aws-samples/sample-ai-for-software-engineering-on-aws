"""审计记录 (D14): every decision and action of a run, in time order, from its records only: the run's events
(``events.jsonl``) and the bench's action record (``actions.jsonl``) for the requests the run made
(``requested_by == "vstatd-team <rid>"``). Nothing is inferred: a field with no record behind it is ``""`` (shown —).

Each entry: ``at`` (epoch), ``iso``, ``seq`` (the event's, None for a bench record), ``actor`` (``person`` | ``agent`` | ``app`` | ``bench``), ``who``, ``step`` (a
step key of ui/src/board/flow.ts, ``""`` where none applies), ``what`` (one line) and ``evidence``.

``bench_only`` lists the bench's request, decision and action records whose request no run made (setting up the
baseline at the console or on the board).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from .constants import APP_NAME

ACTORS = ("person", "agent", "app", "bench")
ACTOR_LABEL = {"person": "人", "agent": "AI", "app": "app", "bench": "台架"}
STEP_TITLE = {"triage": "1 分诊", "gate-triage": "关卡：分诊", "architect": "2 架构", "gate-start": "关卡：开工",
              "tests-first": "3 测试先行", "dev": "4 开发", "before": "5 上台架前检查", "review": "6 评审",
              "bench": "7 台架", "after": "8 台架后检查", "rerun": "9 独立重跑", "signoff": "10 签字放行"}
ROLE_STEP = {"triage": "triage", "architect": "architect", "tester": "tests-first", "dev-fix": "dev",
             "dev-refactor": "dev", "reviewer": "review"}
GATE_STEP = {"triage": "gate-triage", "architect": "gate-start", "reviewer": "review"}
BENCH_ACTION = {"deploy": "部署", "replay": "回放", "restart": "重启"}
VERDICT = {"approved": "批准", "refused": "拒绝"}
BOARD_MARK = "Kiro Crew 看板"
BENCH_SHOWN = 50
FINDING = re.compile(r"\b(?:F-\d{3}|VSTATD-[A-Z]+[-\w.]*)")


def iso_of(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _epoch(text: Any) -> float | None:
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _entry(at: float, actor: str, who: str, step: str, what: str, evidence: str = "") -> dict[str, Any]:
    return {"at": round(float(at), 3), "iso": iso_of(float(at)), "seq": None, "actor": actor, "who": who,
            "step": step or "", "what": what, "evidence": evidence}


def _verdicts(data: dict[str, Any]) -> str:
    rows = data.get("checks") if isinstance(data.get("checks"), list) else data.get("cases")
    return " ".join(f"{c[0]}={c[1]}" for c in rows or [] if isinstance(c, list) and len(c) > 1)


def where(by: str) -> str:
    """Where a bench decision was made, from its ``by``."""
    return "看板" if BOARD_MARK in by else "操作台"


def _bench_entry(r: dict[str, Any], app_who: str) -> dict[str, Any] | None:
    at = _epoch(r.get("at"))
    if at is None:
        return None
    ev, act = r.get("event"), BENCH_ACTION.get(str(r.get("action") or ""), str(r.get("action") or "台架动作"))
    digest, rid = str(r.get("digest") or "")[:12], str(r.get("id") or r.get("request") or r.get("last_request") or "")
    ref = " ".join(x for x in (f"请求 {rid}" if rid else "", f"摘要 {digest}" if digest else "") if x)
    if ev == "request":
        by = str(r.get("requested_by") or "")
        mine = by.startswith(APP_NAME + " ")
        return _entry(at, "app" if mine else "bench", app_who if mine else by or "台架",
                      "bench", f"向操作台请求{act}：{r.get('detail') or ''}".rstrip("："), ref)
    if ev == "decision":
        by, verdict = str(r.get("by") or ""), VERDICT.get(str(r.get("verdict")), str(r.get("verdict") or ""))
        reason = str(r.get("reason") or "")
        if by.startswith("bench"):  # the console's own timeout
            return _entry(at, "bench", "台架", "bench", f"{act}请求{verdict}（{reason or '超时'}）", ref)
        return _entry(at, "person", by or "—", "bench", f"{where(by)}{verdict}{act}" + (f"：{reason}" if reason else ""), ref)
    if ev == "gate":
        return _entry(at, "bench", "台架", "bench",
                      f"物理关卡（{r.get('stage') or ''}）{'通过' if r.get('passed') else '不通过'}：{r.get('why') or ''}", ref)
    if ev == "action":
        return _entry(at, "bench", "台架", "bench", f"{act}结果 {r.get('result') or '—'}：{r.get('detail') or ''}", ref)
    if ev == "target":
        return _entry(at, "bench", "台架", "bench", f"目标状态 {r.get('state') or '—'}：{r.get('why') or ''}", ref)
    return None


def _event_entry(e: dict[str, Any], s: dict[str, Any], titles: dict[str, str], extra: str) -> dict[str, Any] | None:
    kind, role, frm, text = e.get("kind"), e.get("role"), e.get("from"), str(e.get("text") or "")
    data = e.get("data") if isinstance(e.get("data"), dict) else {}
    at = float(e.get("at") or 0)
    agent = titles.get(str(role), str(role or ""))
    step = ROLE_STEP.get(str(role), "")
    gate = GATE_STEP.get(str(role), step)
    found = " ".join(dict.fromkeys(FINDING.findall(text)))
    ev = " ".join(x for x in (extra, found) if x)
    person = "负责人"
    if kind == "run":
        if text.startswith(("运行开始", "重试")):
            return _entry(at, "person", str(data.get("by") or person), "", text, ev)
        return _entry(at, "app", "app", "", text, ev)
    if kind == "signoff":
        sig = s.get("signoff") or {}
        return _entry(at, "person", str(sig.get("by") or person), "signoff", text, " ".join(
            x for x in (f"测试 {sig['tests']}" if sig.get("tests") else "", f"合入 {sig['merged']}" if sig.get("merged") else "") if x))
    if kind == "finding":  # 补登发现 (TR §4.4): a person registers what a check found and hands it to a role
        paths = " ".join(map(str, data.get("paths") or []))
        return _entry(at, "person", str(data.get("by") or person), "before", text, " ".join(
            x for x in (str(data.get("id") or ""), f"检查 {data['check']}" if data.get("check") else "",
                        f"交给 {titles.get(str(data.get('role')), str(data.get('role') or ''))}" if data.get("role") else "",
                        f"可写 {paths}" if paths else "") if x))
    if kind in ("approved", "talk", "bounce") and frm == "person":
        return _entry(at, "person", person, gate, text, ev)
    if kind == "plan" and (text.startswith("人") or text.startswith("分诊批准")):
        m = re.match(r"分诊批准（(.+?)）", text)
        sha = re.search(r"sha256 ([0-9a-f]{6,64})", text)
        return _entry(at, "person", m.group(1) if m else person, gate,
                      text, " ".join(x for x in (f"sha256 {sha.group(1)}" if sha else "", ev) if x))
    if kind == "gate":
        return _entry(at, "app", "app", gate, "关卡打开，" + text, ev)
    if kind == "talk":
        return _entry(at, "agent", agent, gate, text, ev)
    if kind == "tests":
        phase = data.get("phase")
        st = {"before_bench": "before", "after_bench": "after", "rerun": "rerun"}.get(str(phase), "")
        if data.get("first") is not None or (role and not phase):
            st = "tests-first"
        verdicts = _verdicts(data) or (" ".join(data["first"]) if isinstance(data.get("first"), list) else "")
        return _entry(at, "app", "app", st, text, " ".join(x for x in (verdicts, ev) if x))
    if kind == "bench":
        return _entry(at, "app", "app", "rerun" if data.get("step") == "rerun" else "bench", text, ev)
    if kind == "failed":
        st = "bench" if data.get("commands") else ("before" if data.get("checks") else step)
        return _entry(at, "app", "app", st, text, ev)
    if kind == "bounce":  # the app sends work back (a check, a merge conflict, a malformed file)
        return _entry(at, "app", "app", "before" if frm == "tests" else step, text, ev)
    if kind in ("spawned", "done", "review", "tool", "violation") or (kind == "committed" and not text.startswith("app ")):
        return _entry(at, "agent", agent, step, text, ev)
    if kind == "plan" and role and "没有提出" not in text:
        return _entry(at, "agent", agent, step, text, ev)
    return _entry(at, "app", "app", step if kind != "plan" or role else "gate-start", text, ev)


def build(s: dict[str, Any], events: list[dict[str, Any]], recs: list[dict[str, Any]]) -> dict[str, Any]:
    """AuditTrail of ui/src/types.ts for the run whose state is *s*."""
    rid = str(s.get("id") or "")
    roles = [r for r in (s.get("team") or {}).get("roles") or [] if isinstance(r, dict) and r.get("key")]
    titles = {str(r["key"]): str(r.get("title") or r["key"]) for r in roles}
    lanes = s.get("lanes") or {}
    merges = {k: [m for m in s.get("merges") or [] if m.get("role") == k and m.get("status") == "merged"] for k in titles}
    answers = s.get("answers") or {}
    last_approved = {e.get("role"): e.get("seq") for e in events if e.get("kind") == "approved"}
    seen_merge: dict[str, int] = {}
    out = []
    for e in sorted(events, key=lambda x: (float(x.get("at") or 0), int(x.get("seq") or 0))):
        if e.get("at") is None:
            continue
        key, extra = str(e.get("role") or ""), ""
        if e.get("kind") == "merged" and key in merges:
            n = seen_merge[key] = seen_merge.get(key, 0) + 1
            if n <= len(merges[key]):
                extra = f"commit {str(merges[key][n - 1].get('sha') or '')[:12]}"
        elif e.get("kind") == "committed" and key in lanes:
            sha = next((str(c.get("sha") or "") for c in (lanes[key].get("commits") or [])
                        if c.get("subject") and str(c["subject"]) in str(e.get("text") or "")), "")
            extra = f"commit {sha[:12]}" if sha else ""
        elif e.get("kind") == "approved" and last_approved.get(key) == e.get("seq") and answers.get(key):
            extra = "；".join(f"{a.get('id')}={a.get('choice')}" + ("（与建议不同）" if a.get("differs") else "")
                             for a in answers[key])
        elif e.get("kind") == "bounce" and isinstance((e.get("data") or {}).get("answers"), list):
            extra = "改了 " + " ".join(map(str, e["data"]["answers"]))
        entry = _event_entry(e, s, titles, extra)
        if entry:
            out.append({**entry, "seq": int(e["seq"]) if e.get("seq") is not None else None})
    me = f"{APP_NAME} {rid}"
    mine = {str(r.get("id")) for r in recs if r.get("event") == "request" and r.get("requested_by") == me}
    for r in recs:
        if str(r.get("id") or r.get("request") or r.get("last_request") or "") in mine:
            entry = _bench_entry(r, "app")
            if entry:
                out.append(entry)
    out.sort(key=lambda x: x["at"])
    team = s.get("team") or {}
    base = s.get("base") or (s.get("triage") or {}).get("base") or ""
    return {"run": rid, "title": str(s.get("title") or ""), "requirement": str(s.get("requirement") or ""),
            "team": str(team.get("name") or ""), "base": str(base), "status": str(s.get("status") or ""),
            "entries": out}


def bench_only(recs: list[dict[str, Any]]) -> dict[str, Any]:
    """The bench's request, decision and action records whose request no run of this app made: newest BENCH_SHOWN."""
    ours = {str(r.get("id")) for r in recs if r.get("event") == "request" and str(r.get("requested_by") or "").startswith(APP_NAME + " ")}
    out = []
    for r in recs:
        if r.get("event") in ("request", "decision", "action") and str(r.get("id") or "") not in ours:
            entry = _bench_entry(r, "app")
            if entry:
                out.append(entry)
    out.sort(key=lambda x: x["at"])
    return {"entries": out[-BENCH_SHOWN:]}


def _cell(text: Any) -> str:
    return str(text or "—").replace("|", "\\|").replace("\n", " ")


def markdown(trail: dict[str, Any]) -> str:
    """The trail as Markdown, like AI-DLC's aidlc-docs/audit.md: a header, then one table per step."""
    lines = [f"# 审计记录 · {trail['run']}", "",
             f"- 运行：{trail['run']}（{trail['status'] or '—'}）", f"- 需求：{_cell(trail['title'])}",
             f"- 团队：{_cell(trail['team'])}", f"- 基线提交：{_cell(trail['base'])}",
             f"- 条目：{len(trail['entries'])}（来源：events.jsonl、台架 actions.jsonl）", ""]
    order = list(STEP_TITLE) + [""]
    for step in order:
        rows = [x for x in trail["entries"] if x["step"] == step]
        if not rows:
            continue
        lines += [f"## {STEP_TITLE.get(step, '其他')}", "", "| 时间（UTC） | 谁 | 做了什么 | 证据 |", "| --- | --- | --- | --- |"]
        lines += [f"| {x['iso']} | {ACTOR_LABEL[x['actor']]} · {_cell(x['who'])} | {_cell(x['what'])} | {_cell(x['evidence'])} |"
                  for x in rows]
        lines.append("")
    return "\n".join(lines)


def as_json(trail: dict[str, Any]) -> str:
    return json.dumps(trail, ensure_ascii=False, indent=2) + "\n"
