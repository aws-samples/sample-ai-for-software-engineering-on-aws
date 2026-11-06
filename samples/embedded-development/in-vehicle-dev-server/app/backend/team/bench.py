"""Bench actions (D3, D10): the app runs the team file's bench commands (``bench/cc1.sh`` deploy and replay) on this
machine, in the background, and reads the bench state for the board. It never writes the bench state: a person
approves each action and digest at ``bench/console.py``, and a refusal, a timeout there or a target left unknown goes
to a person; nothing is retried (bench/README.md).

The bench state is ``$CC1_BENCH_STATE`` or ``~/.cc1-bench`` (bench/lib/benchstate.py): ``target.json``, ``supply.json``,
``requests/<id>.json`` (a pending request has no ``decisions/<id>.json``) and the action record ``actions.jsonl``.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import shlex
import time
from pathlib import Path
from typing import Any

ARTIFACT = "artifacts/vstatd"  # where checks/build.sh leaves the stripped build, in its results directory
ACTION_TIMEOUT_S = 3600  # one action: the console's own timeout (CC1_APPROVAL_TIMEOUT_S, 300 s) comes first
DOCTOR_TIMEOUT_S = 900  # doctor.sh builds the runner image when it is not cached
ACTIONS_SHOWN = 30
TAIL_LINES = 12


def state_dir() -> Path:
    return Path(os.environ.get("CC1_BENCH_STATE") or Path.home() / ".cc1-bench")


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def read_state(d: Path | None = None) -> dict[str, Any]:
    """The bench state, read only: the target, the supply, the pending requests with their digest, and the end of
    the action record. A missing directory reads as a target that is off."""
    d = Path(d) if d else state_dir()
    target = _json(d / "target.json") or {"state": "off", "why": "台架状态目录里没有目标状态（CC-1 没开机）"}
    pending, now = [], time.time()
    for p in sorted((d / "requests").glob("*.json")) if (d / "requests").is_dir() else []:
        r = _json(p)
        if isinstance(r, dict) and r.get("id") and not (d / "decisions" / f"{r['id']}.json").exists():
            pending.append({k: r.get(k) for k in ("id", "action", "digest", "detail", "requested_at", "requested_by")}
                           | {"expired": now >= float(r.get("expires") or 0), "expires": r.get("expires")})
    actions = []
    with contextlib.suppress(OSError):
        for line in (d / "actions.jsonl").read_text(encoding="utf-8").splitlines()[-ACTIONS_SHOWN:]:
            with contextlib.suppress(ValueError):
                actions.append(json.loads(line))
    return {"dir": str(d), "target": target, "supply": _json(d / "supply.json"), "pending": pending, "actions": actions}


REQUEST_ID = re.compile(r"[0-9]{8}T[0-9]{6}-[a-z-]+-[0-9a-f]{4}")
DECIDED_BY = "Kiro Crew 看板（{user}，vstatd-team）"
_DECIDE = """import json, sys
sys.path.insert(0, sys.argv[1])
import benchstate as bs
rid, verdict, by, reason, prefix = sys.argv[2:7]
try:
    print(json.dumps(bs.decide(rid, verdict, by, reason, digest_prefix=prefix or None)))
except bs.GateError as e:
    print(json.dumps({"refused": str(e)}))
"""


async def decide(lib: Path, rid: Any, verdict: Any, digest: Any, reason: Any) -> dict[str, Any]:
    """A person's decision on a bench request, made on the board (D3): the bench's own ``benchstate.decide`` decides,
    with its rules (approval needs the first 6+ characters of the digest the person typed, once, before the timeout);
    the app adds nothing to them and writes the bench state only through it."""
    from .httpkit import AppError

    if not isinstance(rid, str) or not REQUEST_ID.fullmatch(rid):
        raise AppError("id 要是操作台上请求的编号", "invalid_id")
    if verdict not in ("approve", "refuse"):
        raise AppError("verdict 只能是 approve 或 refuse", "invalid_verdict")
    prefix = digest if isinstance(digest, str) else ""
    if verdict == "approve" and not re.fullmatch(r"[0-9a-fA-F]{6,64}", prefix):
        raise AppError("批准要输入构建摘要的前 6 位（核对过再批）", "digest_required")
    why = reason.strip()[:200] if isinstance(reason, str) else ""
    if verdict == "refuse" and not why:
        raise AppError("拒绝要写原因（会记进动作记录）", "reason_required")
    by = DECIDED_BY.format(user=os.environ.get("USER") or "dashboard owner")
    proc = await asyncio.create_subprocess_exec(
        "/usr/bin/python3", "-c", _DECIDE, str(lib), rid, "approved" if verdict == "approve" else "refused", by, why,
        prefix.lower() if verdict == "approve" else "", stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), 30)
    except asyncio.TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        raise AppError("台架 30 秒没回答", "bench_timeout", 504)
    try:
        res = json.loads(out.decode(errors="replace").strip().splitlines()[-1])
    except (ValueError, IndexError):
        why = err.decode(errors='replace').strip()[-200:]
        raise AppError(f"台架没给结果：{why}", "bench_failed", 502, detail=why)
    if "refused" in res:
        raise AppError(f"没批成：{res['refused']}", "bench_refused", 409, detail=res["refused"])
    return {"ok": True, "decision": res}


def argv(cmd: list[str], values: dict[str, str]) -> list[str]:
    """A bench command with its ``{artifact}`` and ``{run}`` filled in."""
    return [re.sub(r"\{(\w+)\}", lambda m: values.get(m.group(1), m.group(0)), w) for w in cmd]


async def run(cmd: list[str], log: Path, timeout: float, env: dict[str, str] | None = None) -> tuple[int | None, str]:
    """(exit status, or None when it did not end in time; the last lines it wrote). Killed when cancelled."""
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "ab") as out:
        out.write(f"$ {shlex.join(cmd)}\n".encode())
        out.flush()
        try:
            proc = await asyncio.create_subprocess_exec(*cmd, stdin=asyncio.subprocess.DEVNULL, stdout=out,
                                                        stderr=asyncio.subprocess.STDOUT, env={**os.environ, **(env or {})})
        except OSError as exc:
            return 127, str(exc)
        try:
            rc = await asyncio.wait_for(proc.wait(), timeout)
        except asyncio.TimeoutError:
            rc = None
        finally:
            if proc.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
    lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    return rc, "\n".join(lines[-TAIL_LINES:])


async def doctor(cmd: list[str], log: Path) -> dict[str, Any]:
    """bench/doctor.sh: exit 0 when nothing FAILs; its FAIL and WARN lines."""
    rc, _ = await run(cmd, log, DOCTOR_TIMEOUT_S)
    lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    return {"ok": rc == 0, "rc": rc, "at": time.time(), "fails": [ln[6:] for ln in lines if ln.startswith("FAIL  ")],
            "warns": [ln[6:] for ln in lines if ln.startswith("WARN  ")],
            "summary": next((ln for ln in reversed(lines) if ln.startswith("doctor:")), "" if rc == 0 else f"退出码 {rc}")}


def missing(bench: dict[str, Any], doc: dict[str, Any], state: dict[str, Any]) -> list[dict[str, str]]:
    """What keeps the bench from its first action (D10), each with the command a person runs for it."""
    out = []
    if not doc["ok"]:
        out.append({"why": "bench/doctor.sh 没通过：" + ("；".join(doc["fails"]) or doc["summary"]),
                    "command": shlex.join(bench["build"]) if bench.get("build") else ""})
    target = state["target"]
    if target.get("state") == "off":
        out.append({"why": f"台架上的 CC-1 没开机：{target.get('why') or ''}",
                    "command": shlex.join(bench["start"]) if bench.get("start") else ""})
    elif target.get("state") != "known":
        out.append({"why": f"台架目标状态是 {target.get('state')}：{target.get('why') or ''}", "command": "到操作台核对（reconcile）"})
    base = Path(bench["baseline"]).expanduser()
    if not has_baseline(bench):
        out.append({"why": f"没有基线目录 {base}（baseline-result.json）", "command": baseline_command(bench)})
    return out


def has_baseline(bench: dict[str, Any]) -> bool:
    return (Path(bench["baseline"]).expanduser() / "baseline-result.json").is_file()


def baseline_command(bench: dict[str, Any]) -> str:
    """How the bench owner writes the baseline once: the replay command with ``--kind baseline`` into it."""
    cmd = argv(bench["replay"], {"run": str(Path(bench["baseline"]).expanduser())})
    if "--kind" in cmd[:-1]:
        cmd[cmd.index("--kind") + 1] = "baseline"
    return "部署当前版本以后运行 " + shlex.join(cmd)


def outcome(rc: int | None, tail: str, target: dict[str, Any]) -> tuple[str, str]:
    """How a bench action ended, for the person it goes to: ok, refused or timeout at the console, the physical gate,
    an unknown target, or failed (from cc1.sh's own words and the target state after it)."""
    if rc == 0:
        return "ok", ""
    last = next((ln for ln in reversed(tail.splitlines()) if ln.strip()), "")
    if target.get("state") in ("unknown", "busy"):
        return "unknown", f"目标状态未知：{target.get('why') or last}"
    if rc is None:
        return "failed", f"超过 {ACTION_TIMEOUT_S} 秒没做完"
    m = re.search(r"refused \((.*?)\): (.*)$", tail, re.M)
    if m and "timeout" in m.group(1):
        return "timeout", f"操作台上没人批准：{m.group(2)}"
    if m:
        return "refused", f"{m.group(1)} 在操作台上拒绝了：{m.group(2)}"
    if "refused: " in tail:
        return "refused", last
    return "failed", last or f"退出码 {rc}"
