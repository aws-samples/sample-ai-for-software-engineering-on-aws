"""JSON replies, the owner-only guard, and reading a JSON body.

The aiohttp ``web`` module and the owner check are passed in, so routes also run under plain pytest with a fake
web module.
"""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from . import display
from .constants import APP_NAME


class AppError(Exception):
    """An error a route answers with ``{"error", "code"}`` and *status*."""

    def __init__(self, message: str, code: str = "bad_request", status: int = 400, extra: dict[str, Any] | None = None,
                 detail: Any = None) -> None:
        """*detail*: what the app passes on from elsewhere (a reason from the bench, a path, an exception's text): the
        English board says the error by its code with this inside; the app's own words stay out of it."""
        super().__init__(message)
        self.code = code
        self.status = status
        self.extra = extra or {}  # more fields of the reply (a refused finding's ``problems``)
        if detail is not None and str(detail).strip():
            self.extra["detail"] = str(detail).strip()


def host_is_owner(request: Any) -> bool:
    """KiroCrew's own owner predicate; fails closed if the host moved it."""
    try:
        from kiro_crew.dashboard.handlers.source_providers import is_owner_dashboard_request
    except Exception:  # noqa: BLE001
        return False
    try:
        return bool(is_owner_dashboard_request(request))
    except Exception:  # noqa: BLE001
        return False


async def read_body(request: Any) -> dict[str, Any]:
    if not request.can_read_body:
        return {}
    try:
        data = await request.json()
    except (ValueError, UnicodeDecodeError):
        raise AppError("请求体不是合法 JSON", "invalid_json")
    if not isinstance(data, dict):
        raise AppError("请求体必须是 JSON 对象", "invalid_json")
    return data


def _scrubbed(v: Any, scrub: Callable[[str], str]) -> Any:
    if isinstance(v, str):
        return scrub(v)
    if isinstance(v, list):
        return [_scrubbed(x, scrub) for x in v]
    if isinstance(v, dict):
        return {k: v[k] if k == "code" else _scrubbed(v[k], scrub) for k in v}
    return v


class Kit:
    def __init__(self, web: Any, *, is_owner: Callable[[Any], bool] | None = None, app_name: str = APP_NAME,
                 names: Callable[[], Any] = lambda: (), reserved: Callable[[], Any] = lambda: (),
                 scrub: Callable[[str], str] = lambda s: s) -> None:
        """*names*: the people's names in the records, for presentation mode (display.py); *reserved*: the role keys,
        never taken for a name."""
        self.web = web
        self.is_owner = is_owner or host_is_owner
        self.app_name = app_name
        self.body = read_body
        self.names = names
        self.reserved = reserved
        self.scrub = scrub  # an error's words go out redacted as the board's do (a reason may carry a secret)

    def view(self) -> display.View:
        """How this reply shows the home folder and the people (display.py)."""
        return display.current(self.names, self.reserved)

    def json(self, data: Any, status: int = 200) -> Any:
        data = self.view()(data)  # ~ for the home folder, roles for names in presentation mode: nothing recorded changes
        return self.web.json_response(data, status=status, dumps=lambda o: json.dumps(o, ensure_ascii=False, default=str))

    def err(self, status: int, code: str, message: str) -> Any:
        return self.json({"error": message, "code": code}, status=status)

    def deny(self, request: Any) -> Any | None:
        """Only the dashboard owner's own requests get through: these routes start agents and spend credits."""
        if request.get("user") is None:
            return self.err(401, "unauthenticated", "需要登录 KiroCrew dashboard")
        if request.get("app"):
            return self.err(403, "app_token_forbidden", "这些接口只接受 dashboard 主人本人的请求")
        try:
            owner = bool(self.is_owner(request))
        except Exception:  # noqa: BLE001
            owner = False
        if not owner:
            return self.err(403, "owner_only", "这些接口只接受 dashboard 主人本人的请求")
        return None

    def guarded(self, fn: Callable[[Any], Awaitable[Any]]) -> Callable[[Any, Any], Awaitable[Any]]:
        async def handler(request: Any, ctx: Any) -> Any:
            denied = self.deny(request)
            if denied is not None:
                return denied
            present = str(request.query.get("present") or "")
            token = display.PRESENT.set(present if present in display.OWNER else "")
            try:
                return await fn(request)
            except AppError as exc:
                body = {"error": str(exc), "code": exc.code, **exc.extra}
                return self.json(_scrubbed(body, self.scrub), status=exc.status)
            finally:
                display.PRESENT.reset(token)

        return handler
