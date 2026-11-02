"""The check adapter (D7, D11): the app runs the team file's checks itself, in the build container, instead of
trusting an agent's word.

A check keeps the protocol of the scenario's checks/README.md: it is given ``--results <dir>`` and, as its ``args``
say, ``--project``, ``--triage``, ``--run`` and ``--baseline``; its exit status is the verdict (0 PASS, 1 FAIL,
2 usage or configuration error, 3 BLOCKED) and it writes ``<results>/<check>.json``. One results directory per round of
checks, outside the worktrees. The project a round judges is a worktree of its own (``wt/_checks``), detached at the
commit the round is for, so that merges into the run branch meanwhile change nothing it reads.

The round becomes the test wall: one case per check and owner. A failure goes to the role whose write scope covers a
file its reasons name, else to the check's default owner; a check that cannot judge (BLOCKED) or is misconfigured
goes to a person (no owner).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import shlex
import time
import uuid
from pathlib import Path
from typing import Any

from . import gitwork
from .constants import DOCKER_BIN

CHECK_NAME = re.compile(r"[a-z][a-z0-9-]{0,23}")
CHECK_WHEN = ("before_bench", "after_bench", "release")  # before the bench actions, after the replay, before sign-off
CHECK_ARGS = ("project", "triage", "run", "baseline")  # what a check is given besides --results (checks/README.md)
DEFAULT_ROUNDS = 2  # repair rounds per check when the team file gives none (TR §5.1 names build 3, logdiff 2)
DEFAULT_TIMEOUT_S = 1800  # one check, in its container
BENCH_ACTIONS = ("deploy", "restart", "replay")


def _words(x: Any) -> bool:
    return isinstance(x, list) and bool(x) and all(isinstance(w, str) and w for w in x)


def check_config(team: dict[str, Any], keys: list[str]) -> None:
    """The team file's checks, check runner and bench commands (D11), filled in, or a ValueError saying what is wrong.
    A check: ``name``, ``command``, ``args`` (of CHECK_ARGS), ``when`` (of CHECK_WHEN), ``owner`` (the role a failure
    naming no file goes to; none for a release check: a person decides), ``max_rounds`` (DEFAULT_ROUNDS) and
    ``timeout_s`` (DEFAULT_TIMEOUT_S)."""
    runner = team.get("check_runner")
    if runner is not None and not (isinstance(runner, dict) and _words(runner.get("docker"))
                                   and isinstance(runner.get("image"), str) and runner["image"]):
        raise ValueError("team.json：check_runner 要写成 {docker: [命令和参数], image: 镜像名}")
    items = team.get("checks")
    if items is not None and not isinstance(items, list):
        raise ValueError("team.json：checks 要写成检查的列表")
    if items and runner is None:
        raise ValueError("team.json：有 checks 就要写 check_runner（检查在哪个容器里跑）")
    seen: set[str] = set()
    for c in items or []:
        name = c.get("name") if isinstance(c, dict) else None
        if not isinstance(name, str) or not CHECK_NAME.fullmatch(name) or name in seen:
            raise ValueError(f"team.json：检查的 name 不对或重复了：{name!r}")
        seen.add(name)
        if not _words(c.get("command")):
            raise ValueError(f"team.json：检查 {name} 的 command 要写成命令和参数的列表")
        args = c.setdefault("args", [])
        if not isinstance(args, list) or any(a not in CHECK_ARGS for a in args):
            raise ValueError(f"team.json：检查 {name} 的 args 只能用 {'、'.join(CHECK_ARGS)}")
        if c.get("when") not in CHECK_WHEN:
            raise ValueError(f"team.json：检查 {name} 的 when 只能是 {'、'.join(CHECK_WHEN)}")
        owner = c.get("owner")
        if not (owner in keys or (owner is None and c["when"] == "release")):
            raise ValueError(f"team.json：检查 {name} 的 owner 要是一个角色的 key（只有 release 的检查可以不写，交给人）")
        rounds = c.setdefault("max_rounds", DEFAULT_ROUNDS)
        if not isinstance(rounds, int) or isinstance(rounds, bool) or not 1 <= rounds <= 10:
            raise ValueError(f"team.json：检查 {name} 的 max_rounds 要是 1 到 10 的整数")
        timeout = c.setdefault("timeout_s", DEFAULT_TIMEOUT_S)
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
            raise ValueError(f"team.json：检查 {name} 的 timeout_s 要是正数（秒）")
    bench = team.get("bench")
    if bench is not None and not (isinstance(bench, dict) and set(bench) <= set(BENCH_ACTIONS)
                                  and all(_words(v) for v in bench.values())):
        raise ValueError(f"team.json：bench 要写成 {{{'、'.join(BENCH_ACTIONS)}: [命令和参数]}}")


def docker_command(runner: dict[str, Any], mounts: list[tuple[str, bool]], cmd: list[str],
                   workdir: str | None = None, name: str | None = None) -> list[str]:
    """``docker run`` of the team's build container with each of *mounts* (path, writable) at the same path inside,
    so that the paths in a result mean the same on both sides; git there accepts the host's repositories. *name*: the
    container's, so that it can be removed when its check is cancelled or times out."""
    out = list(runner["docker"]) + (["--name", name] if name else [])
    if out[0] == "docker":  # the gateway's PATH may not have it
        out[0] = DOCKER_BIN
    for path, writable in mounts:
        out += ["-v", f"{path}:{path}" + ("" if writable else ":ro")]
    out += ["-e", "GIT_CONFIG_COUNT=1", "-e", "GIT_CONFIG_KEY_0=safe.directory", "-e", "GIT_CONFIG_VALUE_0=*"]
    if workdir:
        out += ["-w", workdir]
    return out + [runner["image"], *cmd]


def docker_prefix(runner: dict[str, Any] | None, mounts: list[tuple[str, bool]], workdir: str | None = None) -> str:
    """The same as one shell line ending with the image, for a role's task ("" when the team has no build container)."""
    return shlex.join(docker_command(runner, mounts, [], workdir)) if runner else ""


class TestsUnavailable(RuntimeError):
    """The checks cannot be run at all (no docker): not something to send back to a role."""


VERDICTS = {0: "PASS", 1: "FAIL", 2: "USAGE", 3: "BLOCKED"}
STATUS = {"PASS": "pass", "FAIL": "fail", "USAGE": "blocked", "BLOCKED": "blocked"}  # the test wall's cell
SNAPSHOT = "_checks"  # the worktree a round judges, beside the run branch's own (wt/_run)
REASONS_SHOWN = 6
# a file a reason names: a relative path (or one inside the check's copy of the tree, …/work/<check>/tree/…), with a
# source or build-file suffix, optionally :line[:column]
_FILE_RE = re.compile(r"(?<![\w./-])(/?(?:[\w.+-]+/)*[\w.+-]+\.(?:cpp|cc|cxx|c|hpp|hh|h|cmake|txt|service))(?::\d+)*")


def files_named(reasons: list[str], project: Path) -> list[str]:
    """The project's files that *reasons* name, in order, each once (paths into the check's copy of the tree are
    taken relative to it; a name that is not a file of *project* is not one)."""
    out: list[str] = []
    for reason in reasons:
        for m in _FILE_RE.finditer(str(reason)):
            path = m.group(1)
            if "/tree/" in path:
                path = path.rsplit("/tree/", 1)[1]
            elif path.startswith("/"):
                continue
            if path not in out and (project / path).is_file():
                out.append(path)
    return out


def owner_of_file(path: str, team: dict[str, Any]) -> str | None:
    """The first role whose write scope covers *path* (None: nobody's)."""
    return next((r["key"] for r in team["roles"] if gitwork.matches(path, r.get("writable") or [])), None)


def attribute(check: dict[str, Any], result: dict[str, Any], project: Path, team: dict[str, Any]) -> dict[str | None, list[str]]:
    """A failing check's reasons by the role they go back to: each reason to the owners of the files it names, a
    reason naming none to the check's default owner. A check that did not judge (BLOCKED, a usage error) goes to a
    person: the key None."""
    reasons = [str(r) for r in result.get("reasons") or []] or [str(result.get("summary") or result["verdict"])]
    if result["verdict"] != "FAIL":
        return {None: reasons}
    out: dict[str | None, list[str]] = {}
    for reason in reasons:
        owners = [o for o in (owner_of_file(f, team) for f in files_named([reason], project)) if o]
        for o in dict.fromkeys(owners or [check.get("owner")]):
            out.setdefault(o, []).append(reason)
    return out


async def snapshot(run_wt: Path, head: str) -> Path:
    """The worktree a round judges, detached at *head* and clean (made once, moved for every round)."""
    wt = Path(run_wt).parent / SNAPSHOT
    if not (wt / ".git").exists():
        await gitwork.git(run_wt, "worktree", "prune")
        await gitwork.git(run_wt, "worktree", "add", "-q", "--detach", str(wt), head)
    else:
        await gitwork.git(wt, "checkout", "-q", "--detach", "--force", head)
        await gitwork.reset_clean(wt)
    return wt


def _read_result(results: Path, name: str, rc: int | None, why: str) -> dict[str, Any]:
    """The check's own result file, checked against its exit status. What does not add up is BLOCKED: no evidence is
    not a pass (checks/README.md, rule 2)."""
    verdict = VERDICTS.get(rc) if rc is not None else None
    try:
        data = json.loads((results / f"{name}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    if verdict is None:
        return {"verdict": "BLOCKED", "reasons": [why or f"检查没跑起来（退出码 {rc}）"], "tier": None, "summary": "没有结果"}
    if not isinstance(data, dict) or data.get("verdict") != verdict:
        if verdict == "USAGE":
            return {"verdict": "USAGE", "reasons": [why or "检查配置错误（退出码 2）"], "tier": None, "summary": "检查配置错误"}
        got = data.get("verdict") if isinstance(data, dict) else "没有结果文件"
        return {"verdict": "BLOCKED", "reasons": [f"退出码是 {verdict}，结果文件 {name}.json 说 {got}：对不上"],
                "tier": None, "summary": "结果对不上"}
    return {"verdict": verdict, "reasons": [str(r) for r in data.get("reasons") or []], "tier": data.get("tier"),
            "summary": str(data.get("summary") or ""), "commit": data.get("commit")}


async def _exec(cmd: list[str], log: Path, timeout: float, name: str) -> tuple[int | None, str]:
    """(exit status, why there is none). The container is removed when its check times out or is cancelled."""
    with open(log, "ab") as out:
        try:
            proc = await asyncio.create_subprocess_exec(*cmd, stdin=asyncio.subprocess.DEVNULL, stdout=out,
                                                        stderr=asyncio.subprocess.STDOUT)
        except OSError as exc:
            raise TestsUnavailable(f"跑不了 {cmd[0]}：{exc}") from exc
        try:
            return await asyncio.wait_for(proc.wait(), timeout), ""
        except asyncio.TimeoutError:
            return None, f"超过 {timeout:g} 秒没跑完"
        finally:
            if proc.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
                await _remove(cmd[0], name)


async def _remove(docker: str, name: str) -> None:
    with contextlib.suppress(OSError):
        rm = await asyncio.create_subprocess_exec(docker, "rm", "-f", name, stdin=asyncio.subprocess.DEVNULL,
                                                  stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await asyncio.shield(rm.wait())


def check_argv(check: dict[str, Any], results: Path, values: dict[str, Path | None]) -> list[str] | str:
    """The check's command line, or why it cannot be given what its ``args`` ask for."""
    argv = [*check["command"], "--results", str(results)]
    for a in check["args"]:
        if values.get(a) is None:
            return f"没有 --{a}（{check['name']} 要它）"
        argv += [f"--{a}", str(values[a])]
    return argv


async def run_checks(run_wt: Path, team: dict[str, Any], *, head: str, results: Path, phase: str = "before_bench",
                     triage: Path | None = None, run: Path | None = None, baseline: Path | None = None) -> dict[str, Any]:
    """One round: the team's checks of *phase*, in order, one container at a time, on *head* → the test wall."""
    runner = team["check_runner"]
    results = Path(results)
    results.mkdir(parents=True, exist_ok=True)
    project = await snapshot(Path(run_wt), head)
    root = Path(run_wt).parents[1]  # runs/<run>/: the repository, its worktrees and the results
    values = {"project": project, "triage": triage, "run": run, "baseline": baseline}
    rows, cases, names = [], [], []
    for check in [c for c in team.get("checks") or [] if c["when"] == phase]:
        name = check["name"]
        names.append(name)
        started = time.time()
        argv = check_argv(check, results, values)
        if isinstance(argv, str):
            res = {"verdict": "USAGE", "reasons": [argv], "tier": None, "summary": "检查配置错误"}
        else:
            sample = Path(check["command"][0]).resolve().parents[1]  # the scenario folder: the checks and the knowledge
            mounts = [(str(sample), False), (str(root), True)]
            mounts += [(str(Path(v)), False) for k, v in values.items() if k in check["args"] and v is not None
                       and not Path(v).resolve().is_relative_to(root.resolve()) and k != "project"]
            container = f"vstatd-check-{uuid.uuid4().hex[:12]}"
            cmd = docker_command(runner, mounts, argv, name=container)
            (results / f"{name}.cmd").write_text(shlex.join(cmd) + "\n", encoding="utf-8")
            rc, why = await _exec(cmd, results / f"{name}.run.log", float(check["timeout_s"]), container)
            res = _read_result(results, name, rc, why)
        ms = round((time.time() - started) * 1000)
        groups = attribute(check, res, project, team) if res["verdict"] != "PASS" else {check.get("owner"): []}
        rows.append({"name": name, "verdict": res["verdict"], "tier": res.get("tier"), "summary": res["summary"],
                     "owners": [o for o in groups if o], "files": files_named(res["reasons"], project),
                     "reasons": res["reasons"][:20], "ms": ms})
        for owner, reasons in groups.items():
            cases.append({"id": name if len(groups) == 1 else f"{name}#{owner or 'person'}", "ac": name,
                          "name": f"{name}.sh", "file": (files_named(reasons, project) or [""])[0],
                          "status": STATUS[res["verdict"]], "verdict": res["verdict"], "tier": res.get("tier"),
                          "owner": owner,
                          "ms": ms, "message": "；".join(reasons[:REASONS_SHOWN])[:400] or None})
    passed = sum(c["status"] == "pass" for c in cases)
    failed = sum(c["status"] != "pass" for c in cases)
    return {"at": time.time(), "command": " ".join(names), "cases": cases, "passed": passed, "failed": failed,
            "total": len(cases), "head": head, "checks": rows, "results": str(results)}
