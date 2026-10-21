"""The app runs the tests itself instead of trusting an agent's word: one test file at a time (so every case is
attributed to its file), ``node --test --test-reporter=tap``, TAP parsed into the test wall's cases."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import signal
import tempfile
import time
from pathlib import Path
from typing import Any

from .constants import NODE_BIN
from .gitwork import matches

# AC = 功能验收；SEC / UX / COMP / STORE = 规范包里的安全、体验、合规、上架检查
AC_RE = re.compile(r"^\s*((?:AC|RULE|ACC|PII|SEC|FE|UX|BR|COMP|STORE|PRC|MGN|PP|DATA)-\d+)")
# 功能、业务规则、账号安全、个人信息、安全、前端工程、体验、品牌、合规、上架；价格合规、毛利、价保；数据
GROUP_ORDER = {"AC": 0, "RULE": 1, "ACC": 2, "PII": 3, "SEC": 4, "FE": 5, "UX": 6, "BR": 7, "COMP": 8, "STORE": 9,
               "PRC": 10, "MGN": 11, "PP": 12, "DATA": 13}


def case_order(ac: str | None) -> tuple[int, int]:
    """Sort key of a case id: its group (功能、安全、合规、上架), then its number; cases without one go last."""
    if not ac:
        return (len(GROUP_ORDER), 10**6)
    prefix, _, num = ac.partition("-")
    return (GROUP_ORDER.get(prefix, len(GROUP_ORDER)), int(num) if num.isdigit() else 10**6)
_RESULT_RE = re.compile(r"^(not ok|ok)\b(?:\s+\d+)?(?:\s+-\s+(.*?))?\s*$")
_DIRECTIVE_RE = re.compile(r"(?<!\\)\s#\s*(SKIP|TODO)\b.*$", re.I)
_TEST_FILE_RE = re.compile(r"(\.test|[-_]test)\.[cm]?js$|^test([-_].*)?\.[cm]?js$")
_ERROR_RE = re.compile(r"(Error|Cannot find|SyntaxError|not defined|Unexpected)")
_SUMMARY_RE = re.compile(r"^(tests|suites|pass|fail|cancelled|skipped|todo|duration_ms)\s")


class TestsUnavailable(RuntimeError):
    """The tests cannot be run at all (no node): not something to send back to a role."""


def _unquote(val: str) -> Any:
    if val in ("~", "null"):
        return None
    if len(val) >= 2 and val[0] == val[-1] == "'":
        return val[1:-1].replace("''", "'")
    if len(val) >= 2 and val[0] == val[-1] == '"':
        try:
            return json.loads(val)
        except ValueError:
            return val[1:-1]
    return val


def _yaml(lines: list[str]) -> dict[str, Any]:
    """The flat keys of one diagnostic block (``duration_ms``, ``error``, ``failureType`` …); block scalars kept."""
    if not lines:
        return {}
    base = min(len(line) - len(line.lstrip(" ")) for line in lines if line.strip())
    out: dict[str, Any] = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if len(line) - len(line.lstrip(" ")) != base or ":" not in line:
            continue
        key, _, val = line.strip().partition(":")
        val = val.strip()
        if val[:1] in ("|", ">"):
            block = []
            while i < len(lines) and (not lines[i].strip() or len(lines[i]) - len(lines[i].lstrip(" ")) > base):
                block.append(lines[i].strip())
                i += 1
            out[key] = "\n".join(block).strip()
        else:
            out[key] = _unquote(val)
    return out


def parse_tap(text: str) -> tuple[list[dict[str, Any]], list[str]]:
    """TAP 13 from node's reporter → (top-level results, each with nested ``children``; top-level comments).
    A parent's result line comes after its children's, four spaces less indented."""
    pending: dict[int, list[dict[str, Any]]] = {}
    comments: list[str] = []
    last: dict[str, Any] | None = None
    yaml_at: int | None = None
    block: list[str] = []
    for raw in text.splitlines():
        line = raw.rstrip("\r")
        body = line.lstrip(" ")
        indent = len(line) - len(body)
        if yaml_at is not None:
            if body == "..." and indent == yaml_at:
                if last is not None:
                    last["yaml"] = _yaml(block)
                yaml_at, block = None, []
            else:
                block.append(line)
            continue
        m = _RESULT_RE.match(body)
        if m:
            level = indent // 4
            name, directive = m.group(2) or "", None
            d = _DIRECTIVE_RE.search(name)
            if d:
                directive, name = d.group(1).upper(), name[: d.start()]
            last = {"ok": m.group(1) == "ok", "name": name.replace("\\#", "#").replace("\\\\", "\\").strip(),
                    "directive": directive, "yaml": {}, "children": pending.pop(level + 1, [])}
            pending.setdefault(level, []).append(last)
        elif body == "---" and last is not None:
            yaml_at = indent
        elif body.startswith("#") and indent == 0 and not body.startswith("# Subtest:"):
            comments.append(body[1:].strip())
    return pending.get(0, []), comments


def _message(node: dict[str, Any]) -> str | None:
    err = str(node["yaml"].get("error") or "")
    if node["yaml"].get("failureType") == "subtestsFailed" or not err:
        for child in node["children"]:
            if not child["ok"] and child["directive"] is None:
                sub = _message(child)
                return f"{child['name']}: {sub}"[:200] if sub else child["name"][:200]
    first = next((s.strip() for s in err.splitlines() if s.strip()), "")
    return first[:200] or None


def _has_ac(node: dict[str, Any]) -> bool:
    return bool(AC_RE.match(node["name"])) or any(_has_ac(c) for c in node["children"])


def to_cases(results: list[dict[str, Any]], file: str, owner: str | None) -> list[dict[str, Any]]:
    """One case per acceptance criterion: the shallowest test whose name starts with ``AC-n``; a test with no AC
    anywhere below it is a case of its own."""
    out: list[dict[str, Any]] = []

    def visit(node: dict[str, Any]) -> None:
        if not AC_RE.match(node["name"]) and any(_has_ac(c) for c in node["children"]):
            for child in node["children"]:
                visit(child)
            return
        status = "skip" if node["directive"] else ("pass" if node["ok"] else "fail")
        ms = node["yaml"].get("duration_ms")
        try:
            ms = round(float(ms))
        except (TypeError, ValueError):
            ms = None
        ac = AC_RE.match(node["name"])
        out.append({"id": "", "ac": ac.group(1) if ac else None, "name": node["name"][:200], "file": file,
                    "status": status, "owner": owner, "ms": ms, "message": _message(node) if status == "fail" else None})

    for node in results:
        visit(node)
    return out


def file_case(file: str, owner: str | None, name: str, message: str) -> dict[str, Any]:
    return {"id": "", "ac": None, "name": name, "file": file, "status": "fail", "owner": owner, "ms": None,
            "message": message[:200]}


def test_files(wt: Path) -> list[str]:
    """What ``node --test tests/`` would pick up: node's default test-file names, anywhere under tests/."""
    root = wt / "tests"
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d != "node_modules")
        for name in filenames:
            if _TEST_FILE_RE.search(name):
                found.append(str((Path(dirpath) / name).relative_to(wt)))
    return sorted(found)


def owner_of(path: str, team: dict[str, Any]) -> str | None:
    return next((o["role"] for o in team.get("test_owners", []) if matches(path, [o["glob"]])), None)


def _killpg(pid: int) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
        os.killpg(pid, signal.SIGKILL)


async def run_file(node: str, wt: Path, rel: str, timeout: float) -> tuple[int | None, str, str, bool]:
    """(exit code, stdout, stderr, timed out). Its own process group, killed afterwards: a server a test started
    and never closed must not outlive the run, nor hold the pipes open."""
    env = {"PATH": os.pathsep.join([str(Path(node).parent), "/usr/bin", "/bin"]), "HOME": os.environ.get("HOME", "/tmp"),
           "TMPDIR": tempfile.gettempdir(), "LANG": "en_US.UTF-8", "NO_COLOR": "1", "NODE_ENV": "test"}
    try:
        proc = await asyncio.create_subprocess_exec(
            node, "--test", "--test-reporter=tap", "--test-force-exit", "--test-timeout=30000", rel, cwd=str(wt), env=env,
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            start_new_session=True)
    except OSError as exc:
        return None, "", f"跑不了 node（{node}）：{exc}", False
    readers = [asyncio.ensure_future(proc.stdout.read()), asyncio.ensure_future(proc.stderr.read())]
    timed_out = False
    try:
        try:
            await asyncio.wait_for(proc.wait(), timeout)
        except asyncio.TimeoutError:
            timed_out = True
        finally:
            _killpg(proc.pid)
        await asyncio.wait(readers, timeout=5)  # a grandchild outside the group may still hold the pipes
    finally:
        for task in readers:
            task.cancel()
    out, err = (r.result().decode("utf-8", "replace") if r.done() and not r.cancelled() and not r.exception() else ""
                for r in readers)
    return proc.returncode, out, err, timed_out


async def run_tests(wt: Path, team: dict[str, Any], *, node: str = NODE_BIN, timeout: float | None = None) -> dict[str, Any]:
    """Every test file in the integration worktree, one at a time → the test wall (cases sorted by AC number). A file
    gets *timeout* seconds, else the team's ``test_timeout_s``, else 60. The files owned by a role in the team's
    ``skip_owners`` (one that sits this run out) are not run."""
    timeout = float(timeout or team.get("test_timeout_s") or 60.0)
    leave = set(team.get("skip_owners") or [])
    files = [f for f in await asyncio.to_thread(test_files, wt) if not leave or owner_of(f, team) not in leave]
    roots = (str(wt) + "/", os.path.realpath(wt) + "/")
    cases: list[dict[str, Any]] = []
    for rel in files:
        owner = owner_of(rel, team)
        rc, out, err, timed_out = await run_file(node, wt, rel, timeout)
        if rc is None and not timed_out:
            raise TestsUnavailable(err)
        base = Path(rel).name
        if timed_out:
            cases.append(file_case(rel, owner, f"{base} 超时", f"超过 {timeout:g} 秒没跑完"))
            continue
        results, comments = parse_tap(out)
        whole = [r for r in results if r["name"] == rel and not r["ok"]]  # node's stand-in when the file cannot load
        if whole or (not results and rc != 0):
            lines = comments + err.splitlines()
            why = next((s.strip() for s in lines if _ERROR_RE.search(s) and not _SUMMARY_RE.match(s)), "")
            for root in roots:
                why = why.replace(root, "")
            cases.append(file_case(rel, owner, f"{base} 跑不起来", why or f"测试文件跑不起来（退出码 {rc}）"))
        cases.extend(to_cases([r for r in results if r not in whole], rel, owner))
    seen: dict[str, int] = {}
    for c in cases:
        key = f"{Path(c['file']).name}#{c['ac'] or c['name']}"
        seen[key] = seen.get(key, 0) + 1
        c["id"] = key if seen[key] == 1 else f"{key}#{seen[key]}"
    cases.sort(key=lambda c: case_order(c["ac"]))  # stable: file order within one id
    passed = sum(c["status"] == "pass" for c in cases)
    failed = sum(c["status"] == "fail" for c in cases)
    return {"at": time.time(), "command": " ".join(team.get("test_command") or []), "cases": cases,
            "passed": passed, "failed": failed, "total": len(cases)}
