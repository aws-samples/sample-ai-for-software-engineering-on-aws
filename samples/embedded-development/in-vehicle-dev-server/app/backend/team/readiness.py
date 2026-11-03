"""``GET /readiness``: what a run of the default team needs, before it starts and before its first bench action (D10),
for the board's empty state. Read only: the bench state is read, never written.

The build container image and ``bench/doctor.sh`` are probed in the background and cached; a request never waits for
them and gets the cached result with its time. doctor.sh runs once by itself and again when a person asks (it builds
the bench runner image when that is not cached, so it is not run on every request).
"""

from __future__ import annotations

import asyncio
import contextlib
import shlex
import time
from pathlib import Path
from typing import Any

from . import bench as bench_mod

IMAGE_TTL_S = 30.0
IMAGE_TIMEOUT_S = 20.0


async def image_exists(docker: str, image: str) -> dict[str, Any]:
    """``docker image inspect``: ok True (there), False (not there, or Docker does not answer: *why*)."""
    try:
        proc = await asyncio.create_subprocess_exec(docker, "image", "inspect", "-f", "{{.Id}}", image,
                                                    stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.PIPE)
    except OSError as exc:
        return {"ok": False, "why": f"没有 {docker}：{exc}", "at": time.time()}
    try:
        out, err = await asyncio.wait_for(proc.communicate(), IMAGE_TIMEOUT_S)
    except asyncio.TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        return {"ok": False, "why": f"Docker {IMAGE_TIMEOUT_S:.0f} 秒没回答", "at": time.time()}
    if proc.returncode == 0:
        return {"ok": True, "why": out.decode(errors="replace").strip()[:19], "at": time.time()}
    msg = err.decode(errors="replace").strip().splitlines()
    missing = any("no such" in ln.lower() for ln in msg)
    return {"ok": False, "why": "镜像不在本机" if missing else (msg[-1][:200] if msg else "Docker 没回答"), "at": time.time()}


class Probes:
    """The cached probes and the background tasks that refresh them."""

    def __init__(self, log_dir: Path) -> None:
        self.log_dir = Path(log_dir)
        self.image: dict[str, Any] | None = None
        self.doctor: dict[str, Any] | None = None
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def running(self, name: str) -> bool:
        task = self._tasks.get(name)
        return task is not None and not task.done()

    def refresh(self, team: dict[str, Any], *, doctor: bool = False) -> None:
        """Start what is due: the image probe when older than IMAGE_TTL_S, doctor.sh when never run or *doctor*."""
        runner, spec = team.get("check_runner") or {}, team.get("bench") or {}
        if runner.get("image") and not self.running("image") and (
                self.image is None or time.time() - self.image["at"] >= IMAGE_TTL_S):
            self._start("image", self._image((runner.get("docker") or ["docker"])[0], runner["image"]))
        if spec.get("doctor") and not self.running("doctor") and (doctor or self.doctor is None):
            self._start("doctor", self._doctor(spec["doctor"]))

    def _start(self, name: str, coro: Any) -> None:
        self._tasks[name] = asyncio.create_task(coro)

    async def _image(self, docker: str, image: str) -> None:
        self.image = await image_exists(docker, image)

    async def _doctor(self, cmd: list[str]) -> None:
        log = self.log_dir / "doctor.log"
        log.unlink(missing_ok=True)  # bench.run appends: this result is this run's lines only
        self.doctor = await bench_mod.doctor(cmd, log)

    async def stop(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks = {}


def pending(team: dict[str, Any], state: dict[str, Any], now: float) -> list[dict[str, Any]]:
    """The bench requests waiting at the operator console now, whoever made them (a run, or a person setting up the
    baseline), with the seconds left before the console's timeout refuses them and the console commands for them. Read
    from the bench state; the app never approves."""
    spec = team.get("bench") or {}
    console = Path(spec["deploy"][0]).with_name("console.py") if spec.get("deploy") else None
    cmd = shlex.join(["python3", str(console)]) if console else "python3 bench/console.py"
    out = []
    for r in state.get("pending") or []:
        if r.get("expired"):
            continue
        left = round(float(r["expires"]) - now) if isinstance(r.get("expires"), (int, float)) else None
        out.append({"id": r["id"], "action": r.get("action") or "", "digest": r.get("digest") or "",
                    "requested_by": r.get("requested_by") or "", "left_s": left,
                    "approve": f"{cmd} approve {r['id']} --digest {str(r.get('digest') or '')[:12]}",
                    "refuse": f"{cmd} refuse {r['id']} --reason <原因>"})
    return out


def items(team: dict[str, Any], probes: Probes, knowledge: dict[str, Any] | None, state: dict[str, Any],
          sample: Path, now: float) -> list[dict[str, Any]]:
    """The checklist: each item's state (ok True, False, or None when the app cannot tell or has not read it yet),
    what it found, the command a person runs when it is not ready, and from which step the run needs it."""
    runner, spec = team.get("check_runner") or {}, team.get("bench") or {}
    out: list[dict[str, Any]] = []

    def add(key: str, label: str, ok: bool | None, detail: str, command: str, needed: str, at: float | None = None,
            running: bool = False) -> None:
        out.append({"key": key, "label": label, "ok": ok, "detail": detail, "command": "" if ok else command,
                    "needed": needed, "age_s": round(now - at, 1) if at else None, "running": running})

    kb = str((team.get("knowledge") or {}).get("source") or "")
    if kb:
        if knowledge is None or knowledge.get("present") is None:
            add("knowledge", f"知识库来源「{kb}」", None, "还没从 Kiro Crew 读到知识库来源", "", "start")
        elif not knowledge["present"]:
            add("knowledge", f"知识库来源「{kb}」", False, "Kiro Crew 里没有这个来源", f"bash {shlex.quote(str(sample / 'setup.sh'))}", "start")
        else:
            synced = knowledge.get("status") == "synced" and bool(knowledge.get("items"))
            add("knowledge", f"知识库来源「{kb}」", synced,
                f"{knowledge.get('items') or 0} 份文档 · " + ("已索引" if synced else f"还在索引（{knowledge.get('status') or '未知'}）"),
                "等 Kiro Crew 索引完（「知识库 → 来源」）", "start")
    if runner.get("image"):
        img, name = probes.image, runner["image"]
        tools = sample / "reference-project" / "tools"
        add("image", f"构建容器镜像 {name}", None if img is None else img["ok"],
            "正在查" if img is None else ("在本机" if img["ok"] else img["why"]),
            f"docker build --platform linux/amd64 -t {shlex.quote(name)} {shlex.quote(str(tools))}/", "checks",
            img["at"] if img else None, probes.running("image"))
    if not spec:
        return out
    doc = probes.doctor
    if spec.get("doctor"):
        add("doctor", "台架自检 bench/doctor.sh", None if doc is None else doc["ok"],
            ("正在跑" if probes.running("doctor") else "还没跑") if doc is None
            else ("通过" if doc["ok"] else "没通过：" + ("；".join(doc["fails"]) or doc["summary"])) + (
                f"（警告：{'；'.join(doc['warns'])}）" if doc["warns"] else ""),
            shlex.join(spec["build"]) if spec.get("build") else shlex.join(spec["doctor"]), "bench",
            doc["at"] if doc else None, probes.running("doctor"))
    target = state.get("target") or {}
    tstate = str(target.get("state") or "")
    add("target", "台架上的目标 CC-1", tstate == "known", f"{tstate or '未知'}：{target.get('why') or ''}".rstrip("："),
        shlex.join(spec["start"]) if tstate == "off" and spec.get("start") else "在操作台上核对（c reconcile）", "bench")
    if spec.get("baseline"):
        base = Path(spec["baseline"]).expanduser()
        add("baseline", "基线（baseline-result.json）", bench_mod.has_baseline(spec),
            str(base).replace(str(Path.home()), "~"), bench_mod.baseline_command(spec), "bench")
    console = Path(spec["deploy"][0]).with_name("console.py") if spec.get("deploy") else None
    if console is not None:
        add("console", "操作台", None, "app 看不出操作台开着没有：部署和回放要人在操作台上批准，它要在自己的终端里开着",
            shlex.join(["python3", str(console)]), "bench")
    return out
