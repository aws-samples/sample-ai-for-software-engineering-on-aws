"""HTTP routes, served under ``/api/apps/aidlc-team/``. All but ``/health`` are for the dashboard owner only:
they start agents and spend credits."""

from __future__ import annotations

from typing import Any

import re

MODEL_RE = re.compile(r"^[a-z0-9][a-z0-9.\-]{1,63}$")

from .httpkit import AppError, Kit

try:  # always there in the gateway; plain pytest passes a fake web module
    from aiohttp import web as _web
except ImportError:  # pragma: no cover
    _web = None

MAX_REQUIREMENT = 8000


def build_routes(svc: Any, AppRoute: Any, *, web: Any = None, is_owner: Any = None) -> list[Any]:
    web = web if web is not None else _web
    if web is None:
        raise RuntimeError("aiohttp is not installed: pass web=")
    kit = Kit(web, is_owner=is_owner)

    async def health(request: Any, ctx: Any) -> Any:
        return kit.json({"ok": True, "started": svc.started})

    async def board(request: Any) -> Any:
        return kit.json(svc.board(request.query.get("run") or None))

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
        if team_name == "auto":  # 组队: the orchestrator picks the team by the requirement's keywords
            team_name = ((svc.route(requirement).get("team") or {}).get("file")) or None
        if team_name is not None and (not isinstance(team_name, str) or not re.fullmatch(r"team-[\w-]+\.json", team_name)):
            raise AppError("team 必须是 team/ 下的 team-*.json，或者 auto", "invalid_team")
        return kit.json({"run": await svc.create_run(requirement, model or None, source or None, team_name or None)})

    async def route(request: Any) -> Any:
        body = await kit.body(request)
        requirement = body.get("requirement")
        if requirement is not None and not isinstance(requirement, str):
            raise AppError("requirement 必须是字符串", "invalid_requirement")
        return kit.json(svc.route((requirement or "")[:MAX_REQUIREMENT]))

    async def cleanup_sessions(request: Any) -> Any:
        return kit.json(await svc.cleanup_sessions())

    async def stop_run(request: Any) -> Any:
        return kit.json(await svc.stop_run(str(request.match_info.get("rid", ""))))

    async def retry(request: Any) -> Any:
        body = await kit.body(request)
        note = body.get("note")
        if note is not None and not isinstance(note, str):
            raise AppError("note 必须是文字", "invalid_note")
        return kit.json(await svc.retry(str(request.match_info.get("rid", "")), body.get("roles"), (note or "").strip()[:4000]))

    async def events(request: Any) -> Any:
        return kit.json(await svc.events(str(request.match_info.get("rid", ""))))

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
        risk = body.get("risk")
        if risk is not None and not isinstance(risk, dict):
            raise AppError("risk 是拦下的风险 {what, amount}（amount 以元计）", "invalid_gate")
        return kit.json(await svc.gate(str(request.match_info.get("rid", "")), role, decision, (note or "").strip()[:4000],
                                       delivery, answers, risk))

    async def cto(request: Any) -> Any:
        return kit.json(await svc.cto())

    async def cto_offline(request: Any) -> Any:
        return kit.json(await svc.cto_offline())

    async def cto_flow(request: Any) -> Any:
        return kit.json(await svc.cto_flow(str(request.query.get("run") or "")))  # a run it does not have: 404

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

    async def site_status(request: Any) -> Any:
        return kit.json(svc.site_status(str(request.match_info.get("rid", ""))))

    async def start_site(request: Any) -> Any:
        return kit.json(await svc.start_site(str(request.match_info.get("rid", ""))))

    async def stop_site(request: Any) -> Any:
        return kit.json(await svc.stop_site(str(request.match_info.get("rid", ""))))

    return [
        AppRoute("GET", "/health", health),
        AppRoute("GET", "/board", kit.guarded(board)),
        AppRoute("GET", "/cto", kit.guarded(cto)),
        AppRoute("GET", "/cto/offline", kit.guarded(cto_offline)),
        AppRoute("GET", "/cto/flow", kit.guarded(cto_flow)),
        AppRoute("GET", "/runs", kit.guarded(runs)),
        AppRoute("POST", "/runs", kit.guarded(create_run)),
        AppRoute("POST", "/route", kit.guarded(route)),
        AppRoute("POST", "/sessions/cleanup", kit.guarded(cleanup_sessions)),
        AppRoute("POST", "/runs/import", kit.guarded(import_run)),
        AppRoute("POST", "/runs/{rid}/stop", kit.guarded(stop_run)),
        AppRoute("POST", "/runs/{rid}/retry", kit.guarded(retry)),
        AppRoute("POST", "/runs/{rid}/gate", kit.guarded(gate)),
        AppRoute("POST", "/runs/{rid}/signoff", kit.guarded(signoff)),
        AppRoute("POST", "/runs/{rid}/hide", kit.guarded(hide_run)),
        AppRoute("GET", "/runs/{rid}/events", kit.guarded(events)),
        AppRoute("POST", "/runs/{rid}/open", kit.guarded(open_folder)),
        AppRoute("GET", "/runs/{rid}/roles/{role}", kit.guarded(role_output)),
        AppRoute("GET", "/runs/{rid}/roles/{role}/file", kit.guarded(file_view)),
        AppRoute("GET", "/runs/{rid}/site", kit.guarded(site_status)),
        AppRoute("POST", "/runs/{rid}/site", kit.guarded(start_site)),
        AppRoute("POST", "/runs/{rid}/site/stop", kit.guarded(stop_site)),
    ]
