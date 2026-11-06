"""审计记录 (D14): every decision and action of a run, in time order, from its records only: the run's events
(``events.jsonl``) and the bench's action record (``actions.jsonl``) for the requests the run made
(``requested_by == "vstatd-team <rid>"``). Nothing is inferred: a field with no record behind it is ``""`` (shown —).

Each entry: ``at`` (epoch), ``iso``, ``seq`` (the event's, None for a bench record), ``actor`` (``person`` | ``agent`` | ``app`` | ``bench``), ``who``, ``step`` (a
step key of ui/src/board/flow.ts, ``""`` where none applies), ``what`` (one line), ``evidence`` and ``flags``: what the
board counts, so that it reads no words of ``what`` or ``evidence`` (``differs``: the answers at a gate that differ
from the proposal; ``where``: ``board`` or ``console`` for a bench decision; ``result``: a bench action's).

``bench_only`` lists the bench's request, decision and action records whose request no run made (setting up the
baseline at the console or on the board).

``lang="en"`` (GET /runs/<id>/audit?lang=en) says it in English: an event with a code (messages.py) in its English
template, the app's own words here from WORDS. What the records hold stays as they hold it (the person's notes, the
agents' summaries, reasons, check names, paths, commits). The audit.md written at sign-off is Chinese: its sha256 is
on the sign-off record.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from . import messages, roster
from .constants import APP_NAME

ACTORS = ("person", "agent", "app", "bench")
ACTOR_LABEL = {"person": "人", "agent": "AI", "app": "app", "bench": "台架"}
STEP_TITLE = {"triage": "1 分诊", "gate-triage": "关卡：分诊", "architect": "2 架构", "gate-start": "关卡：开工",
              "tests-first": "3 测试先行", "dev": "4 开发", "before": "5 上台架前检查", "review": "6 评审",
              "bench": "7 台架", "after": "8 台架后检查", "rerun": "9 独立重跑", "signoff": "10 签字放行"}
ACTOR_LABEL_EN = {"person": "person", "agent": "AI", "app": "app", "bench": "bench"}
STEP_TITLE_EN = {"triage": "1 Triage", "gate-triage": "Gate: triage", "architect": "2 Architecture", "gate-start": "Gate: start",
                 "tests-first": "3 Tests first", "dev": "4 Development", "before": "5 Pre-bench checks", "review": "6 Review",
                 "bench": "7 Bench", "after": "8 Post-bench checks", "rerun": "9 Independent rerun", "signoff": "10 Sign-off"}
ROLE_STEP = {"triage": "triage", "architect": "architect", "tester": "tests-first", "dev-fix": "dev",
             "dev-refactor": "dev", "reviewer": "review"}
GATE_STEP = {"triage": "gate-triage", "architect": "gate-start", "reviewer": "review"}
BENCH_ACTION = {"deploy": "部署", "replay": "回放", "restart": "重启"}
VERDICT = {"approved": "批准", "refused": "拒绝"}
# the app's own words in the trail, by language
WORDS: dict[str, dict[str, str]] = {
    "zh": {"person": "负责人", "bench": "台架", "board": "看板", "console": "操作台", "action": "台架动作", "timeout": "超时",
           "request": "向操作台请求{act}：{detail}", "timed": "{act}请求{verdict}（{reason}）", "decision": "{where}{verdict}{act}",
           "gate": "物理关卡（{stage}）{passed}：{why}", "passed": "通过", "not_passed": "不通过", "result": "{act}结果 {result}：{detail}",
           "target": "目标状态 {state}：{why}", "ref_request": "请求 {id}", "ref_digest": "摘要 {digest}", "gate_open": "关卡打开，{text}",
           "tests": "测试 {tests}", "merged": "合入 {sha}", "check": "检查 {check}", "to": "交给 {role}", "writes": "可写 {paths}",
           "changed": "改了 {ids}", "differs": "（与建议不同）", "detail": "：{detail}",
           "title": "审计记录 · {run}", "run": "运行：{run}（{status}）", "req": "需求：{title}", "team": "团队：{team}",
           "base": "基线提交：{base}", "entries": "条目：{n}（来源：events.jsonl、台架 actions.jsonl）", "other": "其他",
           "head": "| 时间（UTC） | 谁 | 做了什么 | 证据 |", "bench_title": "台架动作（不属于任何运行）"},
    "en": {"person": "Release owner", "bench": "bench", "board": "board", "console": "console", "action": "bench action", "timeout": "timed out",
           "request": "Requested {act} from the console: {detail}", "timed": "{act} request {verdict} ({reason})", "decision": "{verdict} {act} on the {where}",
           "gate": "Physical gate ({stage}) {passed}: {why}", "passed": "passed", "not_passed": "not passed", "result": "{act} result {result}: {detail}",
           "target": "Target state {state}: {why}", "ref_request": "request {id}", "ref_digest": "digest {digest}", "gate_open": "Gate opened: {text}",
           "tests": "tests {tests}", "merged": "merged {sha}", "check": "check {check}", "to": "to {role}", "writes": "writes {paths}",
           "changed": "changed {ids}", "differs": " (differs from the proposal)", "detail": ": {detail}",
           "title": "Audit trail · {run}", "run": "Run: {run} ({status})", "req": "Request: {title}", "team": "Team: {team}",
           "base": "Base commit: {base}", "entries": "Entries: {n} (from events.jsonl and the bench's actions.jsonl)", "other": "Other",
           "head": "| Time (UTC) | Who | What | Evidence |", "bench_title": "Bench actions (no run's)"},
}
BENCH_ACTION_EN = {"deploy": "deploy", "replay": "replay", "restart": "restart"}
VERDICT_EN = {"approved": "approved", "refused": "refused"}


def _w(lang: str, key: str, **kw: Any) -> str:
    return WORDS[lang][key].format(**kw)


def who_in(lang: str, who: str) -> str:
    """A record's 谁 in *lang*: the app's own words for a person (负责人, the board) in English; a name as it is."""
    return messages.person(who, lang)
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


def _entry(at: float, actor: str, who: str, step: str, what: str, evidence: str = "",
           flags: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"at": round(float(at), 3), "iso": iso_of(float(at)), "seq": None, "actor": actor, "who": who,
            "step": step or "", "what": what, "evidence": evidence, "flags": dict(flags or {})}


def _verdicts(data: dict[str, Any]) -> str:
    rows = data.get("checks") if isinstance(data.get("checks"), list) else data.get("cases")
    return " ".join(f"{c[0]}={c[1]}" for c in rows or [] if isinstance(c, list) and len(c) > 1)


def where(by: str, lang: str = "zh") -> str:
    """Where a bench decision was made, from its ``by``."""
    return _w(lang, "board") if BOARD_MARK in by else _w(lang, "console")


def _bench_entry(r: dict[str, Any], app_who: str, lang: str = "zh") -> dict[str, Any] | None:
    at = _epoch(r.get("at"))
    if at is None:
        return None
    acts, verdicts = (BENCH_ACTION, VERDICT) if lang == "zh" else (BENCH_ACTION_EN, VERDICT_EN)
    ev, act = r.get("event"), acts.get(str(r.get("action") or ""), str(r.get("action") or _w(lang, "action")))
    digest, rid = str(r.get("digest") or "")[:12], str(r.get("id") or r.get("request") or r.get("last_request") or "")
    ref = " ".join(x for x in (_w(lang, "ref_request", id=rid) if rid else "", _w(lang, "ref_digest", digest=digest) if digest else "") if x)
    bench = _w(lang, "bench")
    if ev == "request":
        by = str(r.get("requested_by") or "")
        mine = by.startswith(APP_NAME + " ")
        return _entry(at, "app" if mine else "bench", app_who if mine else by or bench,
                      "bench", _w(lang, "request", act=act, detail=r.get("detail") or "").rstrip("：: "), ref)
    if ev == "decision":
        by, verdict = str(r.get("by") or ""), verdicts.get(str(r.get("verdict")), str(r.get("verdict") or ""))
        reason = str(r.get("reason") or "")
        if by.startswith("bench"):  # the console's own timeout
            return _entry(at, "bench", bench, "bench", _w(lang, "timed", act=act, verdict=verdict, reason=reason or _w(lang, "timeout")), ref)
        return _entry(at, "person", by or "—", "bench", _w(lang, "decision", where=where(by, lang), verdict=verdict, act=act)
                      + (_w(lang, "detail", detail=reason) if reason else ""), ref,
                      {"where": "board" if BOARD_MARK in by else "console"})
    if ev == "gate":
        return _entry(at, "bench", bench, "bench", _w(lang, "gate", stage=r.get("stage") or "",
                      passed=_w(lang, "passed" if r.get("passed") else "not_passed"), why=r.get("why") or ""), ref)
    if ev == "action":
        return _entry(at, "bench", bench, "bench", _w(lang, "result", act=act, result=r.get("result") or "—", detail=r.get("detail") or ""), ref,
                      {"result": str(r.get("result") or "")})
    if ev == "target":
        return _entry(at, "bench", bench, "bench", _w(lang, "target", state=r.get("state") or "—", why=r.get("why") or ""), ref)
    return None


def _event_entry(e: dict[str, Any], s: dict[str, Any], titles: dict[str, str], extra: str, lang: str = "zh",
                 said: str = "") -> dict[str, Any] | None:
    """*said*: what the entry says (the event's text, or its code in *lang*); the event's text decides the kind of entry."""
    kind, role, frm, text = e.get("kind"), e.get("role"), e.get("from"), str(e.get("text") or "")
    data = e.get("data") if isinstance(e.get("data"), dict) else {}
    entry = _event_kind(e, s, titles, extra, lang, kind, role, frm, text, data)
    if entry and said and entry["what"] == text:
        entry["what"] = said
    elif entry and said and kind == "gate":
        entry["what"] = _w(lang, "gate_open", text=said)
    return entry


def _event_kind(e: dict[str, Any], s: dict[str, Any], titles: dict[str, str], extra: str, lang: str, kind: Any, role: Any,
                frm: Any, text: str, data: dict[str, Any]) -> dict[str, Any] | None:
    at = float(e.get("at") or 0)
    agent = titles.get(str(role), str(role or ""))
    step = ROLE_STEP.get(str(role), "")
    gate = GATE_STEP.get(str(role), step)
    found = " ".join(dict.fromkeys(FINDING.findall(text)))
    ev = " ".join(x for x in (extra, found) if x)
    person = _w(lang, "person")
    if kind == "run":
        if text.startswith(("运行开始", "重试")):
            return _entry(at, "person", str(data.get("by") or person), "", text, ev)
        return _entry(at, "app", "app", "", text, ev)
    if kind == "signoff":
        sig = s.get("signoff") or {}
        return _entry(at, "person", str(sig.get("by") or person), "signoff", text, " ".join(
            x for x in (_w(lang, "tests", tests=sig["tests"]) if sig.get("tests") else "",
                        _w(lang, "merged", sha=sig["merged"]) if sig.get("merged") else "") if x))
    if kind == "finding":  # 补登发现 (TR §4.4): a person registers what a check found and hands it to a role
        paths = " ".join(map(str, data.get("paths") or []))
        return _entry(at, "person", str(data.get("by") or person), "before", text, " ".join(
            x for x in (str(data.get("id") or ""), _w(lang, "check", check=data["check"]) if data.get("check") else "",
                        _w(lang, "to", role=titles.get(str(data.get("role")), str(data.get("role") or ""))) if data.get("role") else "",
                        _w(lang, "writes", paths=paths) if paths else "") if x))
    if kind in ("approved", "talk", "bounce") and frm == "person":
        return _entry(at, "person", person, gate, text, ev)
    if kind == "plan" and (text.startswith("人") or text.startswith("分诊批准")):
        m = re.match(r"分诊批准（(.+?)）", text)
        sha = re.search(r"sha256 ([0-9a-f]{6,64})", text)
        return _entry(at, "person", m.group(1) if m else person, gate,
                      text, " ".join(x for x in (f"sha256 {sha.group(1)}" if sha else "", ev) if x))
    if kind == "gate":
        return _entry(at, "app", "app", gate, _w(lang, "gate_open", text=text), ev)
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


def build(s: dict[str, Any], events: list[dict[str, Any]], recs: list[dict[str, Any]], lang: str = "zh") -> dict[str, Any]:
    """AuditTrail of ui/src/types.ts for the run whose state is *s*, in *lang* (zh or en)."""
    rid = str(s.get("id") or "")
    roles = [r for r in (s.get("team") or {}).get("roles") or [] if isinstance(r, dict) and r.get("key")]
    en = lang == "en"
    team_name = (s.get("team") or {}).get("name")

    def own(r: dict[str, Any], field: str) -> str:  # a run that started before the team file had English names
        return str(r.get(field) or roster.english(team_name, str(r["key"]), field)) if en else ""
    titles = {str(r["key"]): own(r, "title_en") or str(r.get("title") or r["key"]) for r in roles}
    gates = {str(r["key"]): own(r, "gate_label_en") or str(r.get("gate_label") or "") or titles[str(r["key"])] for r in roles}
    lanes = s.get("lanes") or {}
    merges = {k: [m for m in s.get("merges") or [] if m.get("role") == k and m.get("status") == "merged"] for k in titles}
    answers = s.get("answers") or {}
    last_approved = {e.get("role"): e.get("seq") for e in events if e.get("kind") == "approved"}
    seen_merge: dict[str, int] = {}
    out = []
    for e in sorted(events, key=lambda x: (float(x.get("at") or 0), int(x.get("seq") or 0))):
        if e.get("at") is None:
            continue
        key, extra, flags = str(e.get("role") or ""), "", {}
        if e.get("kind") == "merged" and key in merges:
            n = seen_merge[key] = seen_merge.get(key, 0) + 1
            if n <= len(merges[key]):
                extra = f"commit {str(merges[key][n - 1].get('sha') or '')[:12]}"
        elif e.get("kind") == "committed" and key in lanes:
            sha = next((str(c.get("sha") or "") for c in (lanes[key].get("commits") or [])
                        if c.get("subject") and str(c["subject"]) in str(e.get("text") or "")), "")
            extra = f"commit {sha[:12]}" if sha else ""
        elif e.get("kind") == "approved" and last_approved.get(key) == e.get("seq") and answers.get(key):
            extra = ("；" if lang == "zh" else "; ").join(f"{a.get('id')}={a.get('choice')}" + (_w(lang, "differs") if a.get("differs") else "")
                                                          for a in answers[key])
            flags = {"differs": sum(1 for a in answers[key] if a.get("differs"))}
        elif e.get("kind") == "bounce" and isinstance((e.get("data") or {}).get("answers"), list):
            extra = _w(lang, "changed", ids=" ".join(map(str, e["data"]["answers"])))
        code = e.get("code")
        said = (messages.render(str(code), e.get("params"), lambda k: titles.get(k, k), lambda k: gates.get(k, k), lang)
                if en and code in messages.EN else "")
        entry = _event_entry(e, s, titles, extra, lang, said)
        if entry:
            out.append({**entry, "seq": int(e["seq"]) if e.get("seq") is not None else None,
                        "flags": {**entry["flags"], **flags}})
    me = f"{APP_NAME} {rid}"
    mine = {str(r.get("id")) for r in recs if r.get("event") == "request" and r.get("requested_by") == me}
    for r in recs:
        if str(r.get("id") or r.get("request") or r.get("last_request") or "") in mine:
            entry = _bench_entry(r, "app", lang)
            if entry:
                out.append(entry)
    out.sort(key=lambda x: x["at"])
    out = [{**x, "who": who_in(lang, x["who"])} for x in out]
    team = s.get("team") or {}
    base = s.get("base") or (s.get("triage") or {}).get("base") or ""
    return {"run": rid, "title": str(s.get("title") or ""), "requirement": str(s.get("requirement") or ""),
            "team": str(team.get("name") or ""), "base": str(base), "status": str(s.get("status") or ""),
            "entries": out}


def bench_only(recs: list[dict[str, Any]], lang: str = "zh") -> dict[str, Any]:
    """The bench's request, decision and action records whose request no run of this app made: newest BENCH_SHOWN."""
    ours = {str(r.get("id")) for r in recs if r.get("event") == "request" and str(r.get("requested_by") or "").startswith(APP_NAME + " ")}
    out = []
    for r in recs:
        if r.get("event") in ("request", "decision", "action") and str(r.get("id") or "") not in ours:
            entry = _bench_entry(r, "app", lang)
            if entry:
                out.append({**entry, "who": who_in(lang, entry["who"])})
    out.sort(key=lambda x: x["at"])
    return {"entries": out[-BENCH_SHOWN:]}


def _cell(text: Any) -> str:
    return str(text or "—").replace("|", "\\|").replace("\n", " ")


def markdown(trail: dict[str, Any], lang: str = "zh") -> str:
    """The trail as Markdown, like AI-DLC's aidlc-docs/audit.md: a header, then one table per step."""
    steps, actors = (STEP_TITLE, ACTOR_LABEL) if lang == "zh" else (STEP_TITLE_EN, ACTOR_LABEL_EN)
    lines = [f"# {_w(lang, 'title', run=trail['run'])}", "",
             f"- {_w(lang, 'run', run=trail['run'], status=trail['status'] or '—')}", f"- {_w(lang, 'req', title=_cell(trail['title']))}",
             f"- {_w(lang, 'team', team=_cell(trail['team']))}", f"- {_w(lang, 'base', base=_cell(trail['base']))}",
             f"- {_w(lang, 'entries', n=len(trail['entries']))}", ""]
    order = list(steps) + [""]
    for step in order:
        rows = [x for x in trail["entries"] if x["step"] == step]
        if not rows:
            continue
        lines += [f"## {steps.get(step, _w(lang, 'other'))}", "", _w(lang, "head"), "| --- | --- | --- | --- |"]
        lines += [f"| {x['iso']} | {actors[x['actor']]} · {_cell(x['who'])} | {_cell(x['what'])} | {_cell(x['evidence'])} |"
                  for x in rows]
        lines.append("")
    return "\n".join(lines)


def as_json(trail: dict[str, Any]) -> str:
    return json.dumps(trail, ensure_ascii=False, indent=2) + "\n"
