"""The gateway's own chat API, called as this app (the backend runs inside the gateway process).

Auth: the install secret ``<app dir>/.app_secret`` is exchanged at
``POST /api/apps/<app>/token`` (header ``X-App-Secret``) for a 5-minute token sent as ``?token=``; it is renewed a
minute early, and a credential refusal (``X-Auth-Required``) is retried once with a fresh one. Only loopback is
ever called, and neither the secret nor the token goes into a log line or an error message.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

TOKEN_MAX_AGE = 240.0
TIMEOUT_S = 30.0

try:  # the gateway always ships aiohttp; unit tests pass a fake
    import aiohttp
except ImportError:  # pragma: no cover
    aiohttp = None  # type: ignore[assignment]


class GatewayError(RuntimeError):
    def __init__(self, status: int, message: str, code: str = "", path: str = "") -> None:
        super().__init__(f"{path} → HTTP {status} {code} {message}".strip())
        self.status, self.code, self.path = status, code, path


def base_url(env: Any = None) -> str:
    """Loopback URL of the gateway this backend runs in (``KIROCREW_BOUND_PORT``); anything else is refused."""
    env = os.environ if env is None else env
    port = str(env.get("KIROCREW_BOUND_PORT") or env.get("KIROCREW_PORT") or "5476").strip()
    if not port.isdigit():
        raise GatewayError(0, "KIROCREW_BOUND_PORT is not a port", "no_port")
    host = str(env.get("KIROCREW_BOUND_HOST") or "").strip()
    if host in ("", "127.0.0.1", "0.0.0.0", "localhost"):
        return f"http://127.0.0.1:{port}"
    if host in ("::1", "::"):
        return f"http://[::1]:{port}"
    raise GatewayError(0, "the gateway is not bound to loopback; the app secret is not sent there", "no_loopback")


def q(key: str) -> str:
    return quote(str(key), safe="")


class Gateway:
    def __init__(self, app: str, secret_file: Path, *, base: Callable[[], str] = base_url,
                 clock: Callable[[], float] | None = None) -> None:
        self.app, self._secret_file, self._base = app, Path(secret_file), base
        self._clock = clock
        self._token: str | None = None
        self._token_at = 0.0
        self._lock = asyncio.Lock()
        self._session: Any = None

    def _now(self) -> float:
        return self._clock() if self._clock else asyncio.get_running_loop().time()

    def _client(self) -> Any:
        if aiohttp is None:
            raise GatewayError(0, "aiohttp is missing", "no_aiohttp")
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=TIMEOUT_S))
        return self._session

    async def close(self) -> None:
        s, self._session = self._session, None
        if s is not None and not s.closed:
            await s.close()

    async def _token_now(self) -> str:
        if self._token and self._now() - self._token_at < TOKEN_MAX_AGE:
            return self._token
        async with self._lock:
            if self._token and self._now() - self._token_at < TOKEN_MAX_AGE:
                return self._token
            path = f"/api/apps/{self.app}/token"
            secret = (await asyncio.to_thread(self._secret_file.read_text, encoding="utf-8")).strip()
            if not secret:
                raise GatewayError(0, "the app secret is empty", "no_secret", path)
            try:
                async with self._client().post(self._base() + path, headers={"X-App-Secret": secret}) as resp:
                    status, text = resp.status, await resp.text()
            except Exception as exc:  # noqa: BLE001
                raise GatewayError(0, f"gateway unreachable ({type(exc).__name__})", "unreachable", path) from None
            token = None
            if status == 200:
                try:
                    token = (json.loads(text) or {}).get("token")
                except ValueError:
                    token = None
            if not isinstance(token, str) or not token:
                raise GatewayError(status, "app token exchange was refused", "token_exchange", path)
            self._token, self._token_at = token, self._now()
            return token

    async def request(self, method: str, path: str, *, params: dict[str, Any] | None = None, body: Any = None) -> Any:
        """``path`` with the app token; the decoded JSON (``{}`` when empty); 4xx/5xx raise GatewayError."""
        for attempt in (0, 1):
            query = {k: str(v) for k, v in (params or {}).items() if v is not None}
            query["token"] = await self._token_now()
            try:
                async with self._client().request(method, self._base() + path, params=query, json=body) as resp:
                    status, text = resp.status, await resp.text()
                    auth_required = resp.headers.get("X-Auth-Required", "").lower() == "true"
            except Exception as exc:  # noqa: BLE001
                raise GatewayError(0, f"gateway unreachable ({type(exc).__name__})", "unreachable", path) from None
            if status in (401, 403) and auth_required and attempt == 0:
                self._token = None
                continue
            try:
                data: Any = json.loads(text) if text else {}
            except ValueError:
                data = {"raw": text[:300]}
            if status >= 400:
                err = data if isinstance(data, dict) else {}
                raise GatewayError(status, str(err.get("error") or err.get("message") or "")[:200], str(err.get("code") or ""), path)
            return data
        raise AssertionError("unreachable")  # pragma: no cover

    # ---- the calls the session runner makes -------------------------------------------------------------- #

    async def folders(self) -> list[dict[str, Any]]:
        return _rows(await self.request("GET", "/api/chat/folders"), "folders")

    async def create_folder(self, name: str, *, parent_id: str | None = None, project_dir: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"name": name}
        if parent_id:
            body["parent_id"] = parent_id
        if project_dir:
            body["project_dir"] = project_dir
        data = await self.request("POST", "/api/chat/folders", body=body)
        return data.get("folder", data) if isinstance(data, dict) else {}

    async def hide_folder(self, folder_id: str) -> None:
        """An app may not delete a folder (KiroCrew: "ask the person"); it may hide one it owns."""
        await self.request("PATCH", f"/api/chat/folders/{q(folder_id)}", body={"hidden": True})

    async def slots(self) -> list[dict[str, Any]]:
        return _rows(await self.request("GET", "/api/chat/slots"), "slots")

    async def create_slot(self, *, name: str, title: str, folder_id: str, model: str = "", memory_mode: str = "incognito",
                          agent: str = "", agent_kind: str = "") -> dict[str, Any]:
        """*agent*: a Crew member (its template, workspace and model) or, with *agent_kind* ``template``, a template
        file of ~/.kiro/agents; KiroCrew answers 409 ``agent_choice_unavailable`` when the kind asked for is not there."""
        body: dict[str, Any] = {"name": name, "title": title, "folder_id": folder_id, "memory_mode": memory_mode}
        if model:
            body["model"] = model
        if agent:
            body["agent"] = agent
            if agent_kind:
                body["agent_kind"] = agent_kind
        data = await self.request("POST", "/api/chat/slots", body=body)
        return data if isinstance(data, dict) else {}

    async def members(self) -> list[dict[str, Any]]:
        """The Crew members (「代理」): name, template, workspace (needs ``/api/agents`` in the app's permissions)."""
        data = await self.request("GET", "/api/agents")
        rows = data.get("agents") if isinstance(data, dict) else data
        return [r for r in rows or [] if isinstance(r, dict)]

    async def knowledge_sources(self) -> list[dict[str, Any]]:
        """The knowledge base's sources (「知识库 → 来源」), with their item counts and sync state."""
        data = await self.request("GET", "/api/knowledge/sources")
        rows = data.get("sources") if isinstance(data, dict) else data
        return [r for r in rows or [] if isinstance(r, dict)]

    async def set_project(self, key: str, project: str) -> None:
        await self.request("POST", f"/api/chat/slots/{q(key)}/project", body={"project": project})

    async def trust(self, key: str) -> None:
        await self.request("POST", "/api/chat/mode", body={"mode": "trust", "slot": key})

    async def send(self, key: str, message: str, send_id: str) -> dict[str, Any]:
        data = await self.request("POST", "/api/chat", params={"ws": 1},
                                  body={"slot": key, "message": message, "meta": {"sendId": send_id}})
        return data if isinstance(data, dict) else {}

    async def messages(self, key: str, limit: int = 120) -> list[dict[str, Any]]:
        data = await self.request("GET", f"/api/chat/slots/{q(key)}", params={"limit": limit})
        rows = data.get("messages") if isinstance(data, dict) else None
        return [m for m in (rows or []) if isinstance(m, dict)]

    async def stop(self, key: str) -> None:
        await self.request("POST", f"/api/chat/slots/{q(key)}/stop", body={})

    async def delete_slot(self, key: str) -> None:
        await self.request("DELETE", f"/api/chat/slots/{q(key)}")


def _rows(data: Any, key: str) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        for k in (key, "items", "data"):
            if isinstance(data.get(k), list):
                return [r for r in data[k] if isinstance(r, dict)]
    return []
