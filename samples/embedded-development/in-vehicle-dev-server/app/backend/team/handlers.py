"""HTTP routes, served under ``/api/apps/vstatd-team/``. All but ``/health`` are for the dashboard owner only:
they start agents and spend credits."""

from __future__ import annotations

from typing import Any

import re

MODEL_RE = re.compile(r"^[a-z0-9][a-z0-9.\-]{1,63}$")

from . import audit as audit_mod
from .httpkit import AppError, Kit

try:  # always there in the gateway; plain pytest passes a fake web module
    from aiohttp import web as _web
except ImportError:  # pragma: no cover
    _web = None

MAX_REQUIREMENT = 8000


def _text(body: dict[str, Any], key: str, limit: int, required: bool = False) -> str:
    v = body.get(key)
    if v is not None and not isinstance(v, str):
        raise AppError(f"{key} 要是文字", "invalid_finding")
    v = " ".join((v or "").split())
    if required and not v:
        raise AppError(f"要写明 {key}", "invalid_finding")
    if len(v) > limit:
        raise AppError(f"{key} 太长了（最多 {limit} 字）", "invalid_finding")
    return v


def _texts(body: dict[str, Any], key: str, limit: int = 120) -> list[str]:
    v = body.get(key, [])
    if not isinstance(v, list) or len(v) > 20 or not all(isinstance(x, str) and 0 < len(x.strip()) <= limit for x in v):
        raise AppError(f"{key} 要是文字的列表（最多 20 条）", "invalid_finding")
    return list(dict.fromkeys(x.strip() for x in v))


def scope_glob(g: str) -> bool:
    """A path a person adds to a role's write scope: relative, inside the project, not everything."""
    return not g.startswith(("/", "~", ".git", "!")) and ".." not in g.split("/") and g.strip("*/") != "" and "\\" not in g


def finding_body(body: dict[str, Any]) -> dict[str, Any]:
    """POST /runs/{rid}/finding, its shape checked (what it means is checked by the run, the triage by its rules).
    With ``extend`` (the ID of a finding added already): no new finding, only the paths, the role and the note for it."""
    ext = body.get("extend")
    if ext is not None and not (isinstance(ext, str) and re.fullmatch(r"F-\d{3}", ext)):
        raise AppError("extend 要是一个已补登的发现编号，例如 F-032", "invalid_finding")
    out: dict[str, Any] = {k: _text(body, k, n, not ext or k == "role") for k, n in (("check", 40), ("tool", 80), ("location", 200), ("role", 40))}
    out.update({k: _text(body, k, n) for k, n in (("reason", 400), ("pick_up_when", 400), ("note", 1000), ("by", 60))})
    if not out["by"]:
        raise AppError("要写明是谁补登的（by）", "invalid_finding")
    out["extend"] = ext or None
    if ext:
        if body.get("continue") is not None and not isinstance(body["continue"], bool):
            raise AppError("continue 要是 true 或 false", "invalid_finding")
        out.update(decision=None, evidence=None, behaviour=None, facts=[], cites=[], paths=_texts(body, "paths"),
                   **{"continue": body.get("continue", True)})
        if not out["paths"]:
            raise AppError("要写明给它加哪些可写路径（paths）", "invalid_finding")
        bad = [g for g in out["paths"] if not scope_glob(g)]
        if bad:
            raise AppError(f"paths 要是项目里的相对路径或通配：{'、'.join(bad)}", "invalid_finding")
        return out
    if body.get("decision") not in ("fix", "justify", "defer"):
        raise AppError("decision 只能是 fix、justify 或 defer", "invalid_finding")
    out["decision"] = body["decision"]
    if body.get("evidence") not in (None, "", "unit-test", "static-analysis", "build"):
        raise AppError("evidence 只能是 unit-test、static-analysis 或 build", "invalid_finding")
    out["evidence"] = body.get("evidence") or None
    for k in ("behaviour", "continue"):
        if body.get(k) is not None and not isinstance(body[k], bool):
            raise AppError(f"{k} 要是 true 或 false", "invalid_finding")
    out["behaviour"] = body.get("behaviour")
    out["continue"] = body.get("continue", True)
    out.update(facts=_texts(body, "facts", 40), cites=_texts(body, "cites", 60), paths=_texts(body, "paths"))
    bad = [g for g in out["paths"] if not scope_glob(g)]
    if bad:
        raise AppError(f"paths 要是项目里的相对路径或通配：{'、'.join(bad)}", "invalid_finding")
    return out


def build_routes(svc: Any, AppRoute: Any, *, web: Any = None, is_owner: Any = None) -> list[Any]:
    web = web if web is not None else _web
    if web is None:
        raise RuntimeError("aiohttp is not installed: pass web=")
    kit = Kit(web, is_owner=is_owner)

    async def health(request: Any, ctx: Any) -> Any:
        return kit.json({"ok": True, "started": svc.started})

    async def board(request: Any) -> Any:
        return kit.json(svc.board(request.query.get("run") or None))

    async def ready(request: Any) -> Any:
        return kit.json(await svc.readiness())

    async def ready_doctor(request: Any) -> Any:
        return kit.json(await svc.readiness(doctor=True))

    async def bench_decide(request: Any) -> Any:
        body = await kit.body(request)
        return kit.json(await svc.bench_decide(body.get("id"), body.get("verdict"), body.get("digest"), body.get("reason")))

    async def knowledge(request: Any) -> Any:
        return kit.json(await svc.knowledge())

    async def knowledge_file(request: Any) -> Any:
        return kit.json(await svc.knowledge_file(request.query.get("path")))

    async def team_view(request: Any) -> Any:
        return kit.json(await svc.team_view())

    async def backlog(request: Any) -> Any:
        return kit.json(await svc.backlog())

    async def score(request: Any) -> Any:
        return kit.json(await svc.scorecard())

    async def runs(request: Any) -> Any:
        return kit.json({"runs": svc.cards()})

    async def create_run(request: Any) -> Any:
        body = await kit.body(request)
        requirement = body.get("requirement")
        if requirement is not None and not isinstance(requirement, str):
            raise AppError("requirement 必须是字符串", "invalid_requirement")
        requirement = (requirement or "").strip()
        if len(requirement) > MAX_REQUIREMENT:
            raise AppError(f"需求太长了（最多 {MAX_REQUIREMENT} 字）", "requirement_too_long")
        model = body.get("model")
        if model is not None and (not isinstance(model, str) or not MODEL_RE.match(model)):
            raise AppError("model 不是合法的模型名", "invalid_model")
        source = body.get("source")
        if source is not None and (not isinstance(source, str) or not source.startswith(("/", "~"))):
            raise AppError("source 必须是项目目录的绝对路径", "invalid_source")
        team_name = body.get("team")
        if team_name is not None and (not isinstance(team_name, str) or not re.fullmatch(r"team-[\w-]+\.json", team_name)):
            raise AppError("team 必须是 team/ 下的 team-*.json", "invalid_team")
        return kit.json({"run": await svc.create_run(requirement, model or None, source or None, team_name or None)})

    async def cleanup_sessions(request: Any) -> Any:
        return kit.json(await svc.cleanup_sessions())

    async def stop_run(request: Any) -> Any:
        return kit.json(await svc.stop_run(str(request.match_info.get("rid", ""))))

    async def retry(request: Any) -> Any:
        body = await kit.body(request)
        note = body.get("note")
        if note is not None and not isinstance(note, str):
            raise AppError("note 必须是文字", "invalid_note")
        by = body.get("by")
        if by is not None and not isinstance(by, str):
            raise AppError("by 是做决定的人的名字", "invalid_note")
        return kit.json(await svc.retry(str(request.match_info.get("rid", "")), body.get("roles"), (note or "").strip()[:4000],
                                        (by or "").strip()[:60]))

    async def events(request: Any) -> Any:
        return kit.json(await svc.events(str(request.match_info.get("rid", ""))))

    async def run_flow(request: Any) -> Any:
        return kit.json(await svc.flow(str(request.match_info.get("rid", ""))))

    def lang_of(request: Any) -> str:
        lang = request.query.get("lang") or "zh"
        if lang not in ("zh", "en"):
            raise AppError("lang 只能是 zh 或 en", "invalid_lang")
        return lang

    async def run_audit(request: Any) -> Any:
        lang = lang_of(request)
        trail = await svc.audit(str(request.match_info.get("rid", "")), lang)
        return download(request, trail, f"audit-{trail['run']}", lang)

    async def bench_audit(request: Any) -> Any:
        lang = lang_of(request)
        return download(request, {"run": "", "title": audit_mod.WORDS[lang]["bench_title"], "requirement": "", "team": "", "base": "",
                                  "status": "", **await svc.audit_bench(lang)}, "audit-bench", lang)

    def download(request: Any, trail: dict[str, Any], name: str, lang: str = "zh") -> Any:
        fmt = request.query.get("format") or ""
        if fmt not in ("", "md", "json"):
            raise AppError("format 只能是 md 或 json", "invalid_format")
        if not fmt:
            return kit.json(trail)
        text = audit_mod.markdown(trail, lang) if fmt == "md" else audit_mod.as_json(trail)
        return web.Response(text=text, content_type="text/markdown" if fmt == "md" else "application/json", charset="utf-8",
                            headers={"Content-Disposition": f'attachment; filename="{name}.{fmt}"'})

    async def gate(request: Any) -> Any:
        body = await kit.body(request)
        role, decision, note = body.get("role"), body.get("decision"), body.get("note")
        if not isinstance(role, str) or decision not in ("approve", "revise", "discuss") or (note is not None and not isinstance(note, str)):
            raise AppError("要写明 role、decision（approve、revise 或 discuss），note 是文字", "invalid_gate")
        delivery, answers = body.get("delivery"), body.get("answers")
        if delivery is not None and not isinstance(delivery, dict):
            raise AppError("delivery 是交付标签 {name, kind, size, line}", "invalid_gate")
        if answers is not None and not (isinstance(answers, dict) and all(isinstance(v, dict) for v in answers.values())):
            raise AppError("answers 是每个问题的选择 {id: {choice, text}}", "invalid_gate")
        risk, by = body.get("risk"), body.get("by")
        if risk is not None and not isinstance(risk, dict):
            raise AppError("risk 是拦下的风险 {what, amount}（amount 以元计）", "invalid_gate")
        if by is not None and not isinstance(by, str):
            raise AppError("by 是批准人的名字", "invalid_gate")
        return kit.json(await svc.gate(str(request.match_info.get("rid", "")), role, decision, (note or "").strip()[:4000],
                                       delivery, answers, risk, (by or "").strip()[:60]))

    async def finding(request: Any) -> Any:
        body = await kit.body(request)
        return kit.json(await svc.finding(str(request.match_info.get("rid", "")), finding_body(body)))

    async def signoff(request: Any) -> Any:
        body = await kit.body(request)
        by, note = body.get("by"), body.get("note")
        if not isinstance(by, str) or not by.strip() or (note is not None and not isinstance(note, str)):
            raise AppError("要写明谁签字（by），note 是文字", "invalid_signoff")
        return kit.json(await svc.signoff(str(request.match_info.get("rid", "")), by.strip()[:60], (note or "").strip()[:2000]))

    async def import_run(request: Any) -> Any:
        body = await kit.body(request)
        return kit.json(await svc.import_run(body.get("run"), body.get("events"), replace=body.get("replace") is True))

    async def hide_run(request: Any) -> Any:
        return kit.json(await svc.hide_run(str(request.match_info.get("rid", ""))))

    async def open_folder(request: Any) -> Any:
        body = await kit.body(request)
        return kit.json(await svc.open_folder(str(request.match_info.get("rid", "")), body.get("role"), body.get("app") or "finder"))

    def rid_role(request: Any) -> tuple[str, str]:
        return str(request.match_info.get("rid", "")), str(request.match_info.get("role", ""))

    async def role_output(request: Any) -> Any:
        return kit.json(await svc.role_output(*rid_role(request)))

    async def file_view(request: Any) -> Any:
        rid, role = rid_role(request)
        return kit.json(await svc.file_view(rid, role, request.query.get("path"), request.query.get("view") or "content"))

    return [
        AppRoute("GET", "/health", health),
        AppRoute("GET", "/board", kit.guarded(board)),
        AppRoute("GET", "/scorecard", kit.guarded(score)),
        AppRoute("GET", "/readiness", kit.guarded(ready)),
        AppRoute("POST", "/readiness/doctor", kit.guarded(ready_doctor)),
        AppRoute("POST", "/bench/decide", kit.guarded(bench_decide)),
        AppRoute("GET", "/knowledge", kit.guarded(knowledge)),
        AppRoute("GET", "/knowledge/file", kit.guarded(knowledge_file)),
        AppRoute("GET", "/backlog", kit.guarded(backlog)),
        AppRoute("GET", "/team", kit.guarded(team_view)),
        AppRoute("GET", "/runs", kit.guarded(runs)),
        AppRoute("POST", "/runs", kit.guarded(create_run)),
        AppRoute("POST", "/sessions/cleanup", kit.guarded(cleanup_sessions)),
        AppRoute("POST", "/runs/import", kit.guarded(import_run)),
        AppRoute("POST", "/runs/{rid}/stop", kit.guarded(stop_run)),
        AppRoute("POST", "/runs/{rid}/retry", kit.guarded(retry)),
        AppRoute("POST", "/runs/{rid}/gate", kit.guarded(gate)),
        AppRoute("POST", "/runs/{rid}/signoff", kit.guarded(signoff)),
        AppRoute("POST", "/runs/{rid}/finding", kit.guarded(finding)),
        AppRoute("POST", "/runs/{rid}/hide", kit.guarded(hide_run)),
        AppRoute("GET", "/runs/{rid}/events", kit.guarded(events)),
        AppRoute("GET", "/runs/{rid}/flow", kit.guarded(run_flow)),
        AppRoute("GET", "/runs/{rid}/audit", kit.guarded(run_audit)),
        AppRoute("GET", "/audit/bench", kit.guarded(bench_audit)),
        AppRoute("POST", "/runs/{rid}/open", kit.guarded(open_folder)),
        AppRoute("GET", "/runs/{rid}/roles/{role}", kit.guarded(role_output)),
        AppRoute("GET", "/runs/{rid}/roles/{role}/file", kit.guarded(file_view)),
    ]
