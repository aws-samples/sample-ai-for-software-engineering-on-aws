"""打开网站: the product of a finished run, started from its integration worktree on a free local port so the board
can show it. One site at a time; it stops by itself after half an hour, and when the app stops.

The site runs in its own session (so it can be stopped as a group), which also means it outlives an app that is killed
rather than stopped (an update, a reinstall): with *state_file* the site's pid is kept there, and the next start stops
that one first, so a run deploys on its own port again instead of on a random one.

The entry is the target's ``npm start`` when that is ``node <file>``, else ``backend/server.js``. The server gets
``PORT`` and ``HOST=127.0.0.1``; whether it honours them is up to the code the team wrote, so the board waits for an
HTTP answer on that port before it says the site is up, and then asks lsof what the site listens on: a site that listens
beyond loopback (all interfaces, or a network address) is stopped, so a run never puts its product on the network.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable

from .constants import NODE_BIN

TTL_S = 30 * 60
READY_S = 15.0
_START_RE = re.compile(r"^node\s+((?:\./)?[\w./-]+\.(?:m?js|cjs))\s*$")


def entry_of(wt: Path) -> str | None:
    """The server file ``npm start`` runs (``node <file>``), else ``backend/server.js``; None when neither exists."""
    try:
        scripts = json.loads((wt / "package.json").read_text(encoding="utf-8")).get("scripts") or {}
    except (OSError, ValueError, AttributeError):
        scripts = {}
    m = _START_RE.match(str(scripts.get("start") or ""))
    for rel in ([m.group(1).removeprefix("./")] if m else []) + ["backend/server.js"]:
        p = (wt / rel).resolve()
        if ".." not in rel.split("/") and p.is_file() and p.is_relative_to(wt.resolve()):
            return rel
    return None


def free_port(prefer: int | None = None) -> int:
    """*prefer* when nothing listens there (a port someone can open in advance), else any free one."""
    for port in ([prefer] if prefer else []) + [0]:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                continue
            return int(s.getsockname()[1])
    raise OSError("no free port")


LSOF = "/usr/sbin/lsof" if Path("/usr/sbin/lsof").exists() else shutil.which("lsof")
LOOPBACK = ("127.", "[::1]", "localhost")


def beyond_loopback(addrs: list[str]) -> list[str]:
    """The listening addresses (lsof's ``host:port``) that are not loopback: ``*:8090`` is every interface."""
    return sorted({a for a in addrs if not a.startswith(LOOPBACK)})


def wide_listeners(pgid: int) -> list[str]:
    """Where the site's process group listens beyond loopback; [] when it is loopback only, or when there is no lsof."""
    if not LSOF:
        return []
    try:
        out = subprocess.run([LSOF, "-nP", "-a", "-g", str(pgid), "-iTCP", "-sTCP:LISTEN", "-Fn"],
                             capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return beyond_loopback([ln[1:] for ln in out.splitlines() if ln.startswith("n")])


async def answers_http(port: int, timeout: float = 1.0) -> bool:
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", port), timeout)
    except (OSError, asyncio.TimeoutError):
        return False
    try:
        writer.write(b"GET / HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n")
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout)
        return line.startswith(b"HTTP/")
    except (OSError, asyncio.TimeoutError):
        return False
    finally:
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()


async def http_status(port: int, path: str, timeout: float = 10.0) -> int | None:
    """The status code of GET *path* on 127.0.0.1:*port* (None: no answer within *timeout*)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", port), 2)
        except (OSError, asyncio.TimeoutError):
            await asyncio.sleep(0.3)
            continue
        try:
            writer.write(f"GET {path} HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n".encode())
            await writer.drain()
            line = (await asyncio.wait_for(reader.readline(), 3)).decode("latin-1")
            parts = line.split()
            return int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else None
        except (OSError, asyncio.TimeoutError):
            await asyncio.sleep(0.3)
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
    return None


class Site:
    def __init__(self, *, node: str = NODE_BIN, scrub: Callable[[str], str] = lambda s: s,
                 now: Callable[[], float] = time.time, ttl_s: float = TTL_S, ready_s: float = READY_S,
                 state_file: Path | None = None) -> None:
        self.node, self.scrub, self.now, self.ttl_s, self.ready_s = node, scrub, now, ttl_s, ready_s
        self.state_file = state_file
        self.rid: str | None = None
        self.proc: asyncio.subprocess.Process | None = None
        self.port: int | None = None
        self.started_at: float | None = None
        self.entry: str | None = None
        self.error: str | None = None
        self.lines: deque[str] = deque(maxlen=80)
        self._tasks: list[asyncio.Task[None]] = []
        self._lock = asyncio.Lock()
        self._ttl = ttl_s  # this start's: a run that deploys itself may keep its site up longer

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    def status(self, rid: str) -> dict[str, Any]:
        mine = self.rid == rid
        up = mine and self.running
        state = "running" if up else ("failed" if mine and self.error else "off")
        return {"run": rid, "state": state, "url": f"http://127.0.0.1:{self.port}/" if up else None,
                "port": self.port if up else None, "entry": self.entry if mine else None,
                "started_at": self.started_at if mine and up else None,
                "expires_at": (self.started_at or 0) + self._ttl if up else None,
                "error": self.error if mine else None, "log": list(self.lines)[-40:] if mine else []}

    async def start(self, rid: str, wt: Path, *, port: int | None = None, ttl_s: float | None = None) -> dict[str, Any]:
        """The run's product on 127.0.0.1: on *port* when it is free, else any free port; it stops after *ttl_s*."""
        async with self._lock:
            await self._stop()
            await self._reap()
            self.rid, self.error, self.started_at = rid, None, self.now()
            self._ttl = float(ttl_s or self.ttl_s)
            self.lines.clear()
            self.entry = entry_of(wt)
            if self.entry is None:
                self.error = "找不到服务的入口：package.json 的 start 不是 `node <文件>`，也没有 backend/server.js"
                return self.status(rid)
            self.port = free_port(port)
            env = {"PATH": os.pathsep.join([str(Path(self.node).parent), "/usr/bin", "/bin"]),
                   "HOME": os.environ.get("HOME", "/tmp"), "LANG": "en_US.UTF-8", "NO_COLOR": "1",
                   "PORT": str(self.port), "HOST": "127.0.0.1", "NODE_ENV": "production"}
            try:
                self.proc = await asyncio.create_subprocess_exec(
                    self.node, self.entry, cwd=str(wt), env=env, stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, start_new_session=True)
            except OSError as exc:
                self.error = f"跑不了 node：{exc}"
                return self.status(rid)
            proc = self.proc
            self._keep({"pid": proc.pid, "port": self.port, "run": rid, "cwd": str(wt.resolve()), "at": self.started_at})
            self._tasks = [asyncio.create_task(self._pump(proc)), asyncio.create_task(self._expire(proc))]
            if not await self._ready(proc):
                last = next((ln for ln in reversed(self.lines) if ln.strip()), "")
                self.error = ("网站没起来：" + (last or f"{self.ready_s:g} 秒内端口 {self.port} 上没有应答"))[:300]
                await self._stop(keep_error=True)
            elif wide := await asyncio.to_thread(wide_listeners, proc.pid):  # its own session: the pid is the group
                self.error = f"网站不只监听本机（{'、'.join(wide)}），已停掉：服务要只监听 HOST（127.0.0.1）"[:300]
                await self._stop(keep_error=True)
            return self.status(rid)

    async def _ready(self, proc: asyncio.subprocess.Process) -> bool:
        deadline = time.monotonic() + self.ready_s
        while time.monotonic() < deadline:
            if proc.returncode is not None:
                return False
            if self.port is not None and await answers_http(self.port):
                return True
            await asyncio.sleep(0.25)
        return False

    async def _pump(self, proc: asyncio.subprocess.Process) -> None:
        assert proc.stdout is not None
        with contextlib.suppress(Exception):
            async for raw in proc.stdout:
                self.lines.append(self.scrub(raw.decode("utf-8", "replace").rstrip())[:300])

    async def _expire(self, proc: asyncio.subprocess.Process) -> None:
        await asyncio.sleep(self._ttl)
        if self.proc is proc:
            asyncio.ensure_future(self.stop())

    async def stop(self) -> None:
        async with self._lock:
            await self._stop()

    async def _stop(self, *, keep_error: bool = False) -> None:
        proc, self.proc = self.proc, None
        if proc is not None and proc.returncode is None:
            for sig in (signal.SIGTERM, signal.SIGKILL):
                with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
                    os.killpg(proc.pid, sig)
                try:
                    await asyncio.wait_for(proc.wait(), 3)
                    break
                except asyncio.TimeoutError:
                    continue
        if proc is not None:
            self._keep(None)
        current = asyncio.current_task()
        for task in self._tasks:
            if task is not current:
                task.cancel()
        self._tasks = []
        if not keep_error:
            self.error = None

    def _keep(self, rec: dict[str, Any] | None) -> None:
        """The running site, for the next app to find (None: nothing running)."""
        if self.state_file is None:
            return
        with contextlib.suppress(OSError):
            if rec is None:
                self.state_file.unlink(missing_ok=True)
            else:
                self.state_file.parent.mkdir(parents=True, exist_ok=True)
                self.state_file.write_text(json.dumps(rec), encoding="utf-8")

    async def _reap(self) -> None:
        """Stop the site a previous app left running (its pid is in *state_file*), when that pid is still the node
        server it started there: a pid the system has given to something else since is left alone."""
        if self.state_file is None:
            return
        try:
            rec = json.loads(self.state_file.read_text(encoding="utf-8"))
            pid, cwd = int(rec["pid"]), str(rec["cwd"])
        except (OSError, ValueError, KeyError, TypeError):
            return
        if await _cwd_of(pid) == cwd:
            for sig in (signal.SIGTERM, signal.SIGKILL):
                with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
                    os.killpg(pid, sig)
                for _ in range(30):
                    if await _cwd_of(pid) is None:
                        break
                    await asyncio.sleep(0.1)
                else:
                    continue
                break
        self._keep(None)


async def _cwd_of(pid: int) -> str | None:
    """The working directory of process *pid* (None when there is no such process, or it cannot be told)."""
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError, OSError):
        return None
    try:
        proc = await asyncio.create_subprocess_exec("/usr/sbin/lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn",
                                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        out, _ = await asyncio.wait_for(proc.communicate(), 5)
    except (OSError, asyncio.TimeoutError):
        return None
    names = [ln[1:] for ln in out.decode("utf-8", "replace").splitlines() if ln.startswith("n")]
    return names[0] if names else None
