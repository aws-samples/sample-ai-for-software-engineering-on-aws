"""Just enough of aiohttp to run the app's routes under plain pytest.

The test interpreter has no aiohttp: handlers.build_routes(svc, AppRoute, web=FakeWeb,
is_owner=...) builds the real route handlers against this fake ``web`` module, and :func:`call`
finds a route by method and path template (``/runs/{rid}``) and awaits its handler the way the host
does, ``handler(request, ctx)``.

* ``FakeWeb.json_response`` / ``Response`` / ``FileResponse`` all give a :class:`FakeResponse` with
  ``status``, ``body`` (the decoded JSON for a JSON reply), ``text`` and ``headers``;
* :class:`FakeRequest` is a mapping like aiohttp's request (``request.get("user")``, ``"app"``) with
  ``method``, ``match_info``, ``query``, a JSON or raw body, ``owner`` for the injected owner check,
  ``can_read_body``, ``await json()``, ``await read()`` and ``content.iter_chunked(n)``.
"""

from __future__ import annotations

import json
import re
from collections import namedtuple
from typing import Any
from urllib.parse import parse_qsl, urlsplit

AppRoute = namedtuple("AppRoute", ["method", "path", "handler"])
_MISSING = object()


class FakeResponse:
    def __init__(
        self,
        *,
        status: int = 200,
        body: Any = None,
        text: str | None = None,
        headers: dict[str, str] | None = None,
        content_type: str | None = None,
        charset: str | None = None,
        path: str | None = None,
    ) -> None:
        self.status = status
        self.body = body
        self.text = text
        self.headers = dict(headers or {})
        self.content_type = content_type
        self.charset = charset
        self.path = path  # a FileResponse's file

    @property
    def code(self) -> str | None:
        """The ``code`` of a JSON error reply."""
        return self.body.get("code") if isinstance(self.body, dict) else None

    def __repr__(self) -> str:
        return f"FakeResponse({self.status}, {self.body if self.body is not None else self.text!r})"


class FakeWeb:
    """The parts of ``aiohttp.web`` the route modules use."""

    @staticmethod
    def json_response(data: Any, *, status: int = 200, dumps: Any = json.dumps, headers: dict[str, str] | None = None) -> FakeResponse:
        text = dumps(data)  # what aiohttp would send: it must serialize
        return FakeResponse(status=status, body=json.loads(text), text=text, headers=headers, content_type="application/json")

    @staticmethod
    def Response(
        *, text: str | None = None, body: Any = None, status: int = 200, content_type: str | None = None,
        charset: str | None = None, headers: dict[str, str] | None = None,
    ) -> FakeResponse:
        return FakeResponse(status=status, body=body, text=text, headers=headers, content_type=content_type, charset=charset)

    @staticmethod
    def FileResponse(path: Any, *, status: int = 200, headers: dict[str, str] | None = None, chunk_size: int = 256 * 1024) -> FakeResponse:
        return FakeResponse(status=status, headers=headers, path=str(path))


class FakeContent:
    """``request.content``: the raw body, read in chunks."""

    def __init__(self, data: bytes) -> None:
        self._data = data

    async def iter_chunked(self, n: int):
        for i in range(0, len(self._data), max(1, int(n))):
            yield self._data[i : i + n]

    async def read(self, n: int = -1) -> bytes:
        data, self._data = (self._data, b"") if n < 0 else (self._data[:n], self._data[n:])
        return data


class FakeRequest(dict):
    """A request as the host's middleware leaves it: ``request["user"]`` for a signed-in dashboard user,
    ``request["app"]`` for an app's token. *json_body* is sent as JSON; *raw* as bytes as they are."""

    def __init__(
        self,
        method: str = "GET",
        path: str = "/",
        *,
        match_info: dict[str, str] | None = None,
        query: dict[str, str] | None = None,
        json_body: Any = _MISSING,
        raw: bytes | None = None,
        headers: dict[str, str] | None = None,
        user: Any = "owner",
        app: str = "",
        owner: bool = True,
    ) -> None:
        super().__init__()
        if user is not None:
            self["user"] = user
        if app:
            self["app"] = app
        self.method = method.upper()
        self.path = path
        self.match_info = dict(match_info or {})
        self.query = dict(query or {})
        self.headers = dict(headers or {})
        self.owner = owner
        if json_body is not _MISSING:
            raw = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            self.headers.setdefault("Content-Type", "application/json")
        self._raw = raw
        self.content = FakeContent(raw or b"")

    @property
    def can_read_body(self) -> bool:
        return bool(self._raw)

    @property
    def body_exists(self) -> bool:
        return self._raw is not None

    async def read(self) -> bytes:
        return self._raw or b""

    async def text(self) -> str:
        return (self._raw or b"").decode("utf-8")

    async def json(self) -> Any:
        return json.loads((self._raw or b"").decode("utf-8"))


def owner_check(request: Any) -> bool:
    """The is_owner to inject: what the request says it is."""
    return bool(getattr(request, "owner", False))


def _pattern(template: str) -> re.Pattern[str]:
    out, pos = "", 0
    for m in re.finditer(r"\{(\w+)\}", template):
        out += re.escape(template[pos : m.start()]) + f"(?P<{m.group(1)}>[^/]+)"
        pos = m.end()
    return re.compile(out + re.escape(template[pos:]))


def find(routes: list[Any], method: str, path: str) -> tuple[Any, dict[str, str]]:
    """The route for *method* and *path* (no query string) and its match_info."""
    for route in routes:
        if route.method != method.upper():
            continue
        m = _pattern(route.path).fullmatch(path)
        if m:
            return route, m.groupdict()
    raise LookupError(f"no route {method} {path}")


async def call(routes: list[Any], method: str, path: str, **kw: Any) -> FakeResponse:
    """Await the handler of ``method path`` (a query string in *path* becomes ``request.query``);
    *kw* goes to :class:`FakeRequest` (json_body, raw, user, app, owner, headers)."""
    parts = urlsplit(path)
    route, match_info = find(routes, method, parts.path)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update(kw.pop("query", None) or {})
    request = FakeRequest(method, parts.path, match_info=match_info, query=query, **kw)
    return await route.handler(request, None)


def fill(template: str, **values: str) -> str:
    """A concrete path for a route template, every ``{name}`` replaced (by *values*, else ``x``)."""
    return re.sub(r"\{(\w+)\}", lambda m: values.get(m.group(1), "x"), template)
