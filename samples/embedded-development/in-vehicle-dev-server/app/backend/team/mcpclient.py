"""A minimal MCP client over stdio, for the `build` and `bench` servers (D17). Kiro Crew's Python has no MCP SDK, so the
app speaks the protocol itself: newline-delimited JSON-RPC 2.0 on the server's standard input and output, with
``initialize``, ``notifications/initialized`` and ``tools/call``. Nothing else of MCP is used.

The protocol version is one that MCP Python SDK 2.3.0, which both servers pin, negotiates in its handshake
(``HANDSHAKE_PROTOCOL_VERSIONS``: 2024-11-05 to 2025-11-25); the server's answer must name the same version.

What a call can end in:

- the tool's result: ``structuredContent`` when the server sent it, else the JSON of its first text item;
- ``ToolRefused``: the server answered, and refused or failed the call (a tool result with ``isError``, or the
  invalid-parameters error the servers send for a malformed call). Its message is the server's;
- ``McpError``: any other JSON-RPC error, or an answer that is not what MCP says;
- ``McpTimeout``: no answer within the call's time; the client is closed, since the server may still be working;
- ``McpExited``: the server's process ended, or never started; the last lines it wrote on stderr are kept.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import json
import os
from collections import deque
from pathlib import Path
from typing import Any

PROTOCOL_VERSION = "2025-11-25"
CLIENT_INFO = {"name": "vstatd-team", "version": "1"}
INVALID_PARAMS = -32602
LINE_LIMIT = 16 * 1024 * 1024  # one JSON-RPC message (a check's result with its log tail is far smaller)
STDERR_KEPT = 40


class McpError(RuntimeError):
    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


class ToolRefused(McpError):
    """The server refused or failed the call (its guardrails); nothing more was done on its side."""


class McpTimeout(McpError):
    pass


class McpExited(McpError):
    pass


class StdioClient:
    """One server process, started by start() and ended by close(). Calls go one at a time."""

    def __init__(self, argv: list[str], *, env: dict[str, str] | None = None, cwd: str | Path | None = None,
                 start_timeout_s: float = 60.0) -> None:
        self.argv = [str(a) for a in argv]
        self.env = env
        self.cwd = str(cwd) if cwd else None
        self.start_timeout_s = start_timeout_s
        self.proc: asyncio.subprocess.Process | None = None
        self.server: dict[str, Any] = {}
        self.stderr: deque[str] = deque(maxlen=STDERR_KEPT)
        self._ids = itertools.count(1)
        self._lock = asyncio.Lock()
        self._err_task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> "StdioClient":
        await self.start()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    async def start(self) -> dict[str, Any]:
        try:
            self.proc = await asyncio.create_subprocess_exec(
                *self.argv, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, env=self.env, cwd=self.cwd, limit=LINE_LIMIT,
                start_new_session=True)
        except OSError as exc:
            raise McpExited(f"cannot start {self.argv[0]}: {exc}") from exc
        self._err_task = asyncio.create_task(self._drain_stderr())
        res = await self._request("initialize", {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                                                 "clientInfo": CLIENT_INFO}, self.start_timeout_s)
        if not isinstance(res, dict) or res.get("protocolVersion") != PROTOCOL_VERSION:
            await self.close()
            got = res.get("protocolVersion") if isinstance(res, dict) else res
            raise McpError(f"the server speaks protocol {got!r}, not {PROTOCOL_VERSION}")
        self.server = res
        await self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return res

    async def call_tool(self, name: str, arguments: dict[str, str] | None = None, *, timeout_s: float) -> Any:
        res = await self._request("tools/call", {"name": name, "arguments": arguments or {}}, timeout_s)
        if not isinstance(res, dict):
            raise McpError(f"{name}: the answer is not a tool result")
        items = [c for c in res.get("content") or [] if isinstance(c, dict) and c.get("type") == "text"]
        text = items[0].get("text") if items else None
        if res.get("isError"):
            raise ToolRefused(str(text or f"{name} failed on the server"))
        if isinstance(res.get("structuredContent"), dict):
            data = res["structuredContent"]
            # a tool typed `-> dict` answers {"result": {...}} in structuredContent (SDK 2.x wraps it)
            return data["result"] if set(data) == {"result"} and isinstance(data["result"], dict) else data
        try:
            return json.loads(text) if isinstance(text, str) else None
        except ValueError:
            return text

    async def close(self) -> None:
        proc, self.proc = self.proc, None
        if proc is None:
            return
        with contextlib.suppress(Exception):
            if proc.stdin and not proc.stdin.is_closing():
                proc.stdin.close()  # an MCP server ends when its input ends
        try:
            await asyncio.wait_for(proc.wait(), 5)
        except asyncio.TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.terminate()  # the servers end their session on SIGTERM (stop what they started, give leases back)
            try:
                await asyncio.wait_for(proc.wait(), 10)
            except asyncio.TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
                await proc.wait()
        if self._err_task:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._err_task, 1)

    # ---------------------------------------------------------------------------------------------------- wire

    async def _drain_stderr(self) -> None:
        assert self.proc and self.proc.stderr
        while line := await self.proc.stderr.readline():
            self.stderr.append(line.decode(errors="replace").rstrip())

    def _exited(self, what: str) -> McpExited:
        rc = self.proc.returncode if self.proc else None
        tail = " / ".join(list(self.stderr)[-3:])
        return McpExited(f"{what}: the server exited" + (f" with {rc}" if rc is not None else "")
                         + (f" ({tail[:300]})" if tail else ""))

    async def _send(self, msg: dict[str, Any]) -> None:
        if not self.proc or not self.proc.stdin or self.proc.stdin.is_closing():
            raise self._exited("send")
        try:
            self.proc.stdin.write((json.dumps(msg, ensure_ascii=False) + "\n").encode())
            await self.proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as exc:
            raise self._exited("send") from exc

    async def _request(self, method: str, params: dict[str, Any], timeout_s: float) -> Any:
        async with self._lock:
            rid = next(self._ids)
            await self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
            try:
                return await asyncio.wait_for(self._answer(rid, method), timeout_s)
            except asyncio.TimeoutError:
                await self.close()
                raise McpTimeout(f"{method}: no answer within {timeout_s:g} s; the server was stopped") from None

    async def _answer(self, rid: int, method: str) -> Any:
        assert self.proc and self.proc.stdout
        while True:
            try:
                line = await self.proc.stdout.readline()
            except ValueError as exc:  # a line longer than LINE_LIMIT
                raise McpError(f"{method}: an answer longer than {LINE_LIMIT} bytes") from exc
            if not line:
                await self.proc.wait()
                raise self._exited(method)
            try:
                msg = json.loads(line)
            except ValueError:
                continue  # not a protocol message (the servers write nothing else on stdout)
            if not isinstance(msg, dict):
                continue
            if "method" in msg and "id" in msg:  # a request of the server's: answer ping, refuse the rest
                reply = ({"result": {}} if msg["method"] == "ping" else
                         {"error": {"code": -32601, "message": "the client offers no methods"}})
                await self._send({"jsonrpc": "2.0", "id": msg["id"], **reply})
                continue
            if msg.get("id") != rid:
                continue  # a notification, or an answer to a call given up on
            if "error" in msg:
                err = msg["error"] if isinstance(msg["error"], dict) else {}
                text, code = str(err.get("message") or "error"), err.get("code")
                raise (ToolRefused if code == INVALID_PARAMS else McpError)(text, code)
            return msg.get("result")


def server_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """The environment a server is started with: PATH, HOME and what the docker client needs, nothing else of the
    app's (the servers clean their own children's environment too)."""
    keep = ("PATH", "HOME", "LANG", "DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG", "XDG_RUNTIME_DIR", "TMPDIR")
    return {**{k: os.environ[k] for k in keep if k in os.environ}, **(extra or {})}
