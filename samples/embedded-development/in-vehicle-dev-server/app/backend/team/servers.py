"""Servers mode (D17): the checks and the bench actions as tool calls of the ``build`` and ``bench`` MCP servers
(``mcp/build``, ``mcp/bench``), through the app's own stdio client (``mcpclient.py``). The ``direct`` mode
(checks.py, bench.py) is unchanged; the team file's ``connectors`` picks one.

The app reads the servers' own configuration files, never writes them: the build server's work tree, triage file and
state folder, the bench server's state folder and timeouts. Before each session it moves the work tree to the commit
the round judges and copies the run's approved triage into the triage file's folder (both in place: the folders are
kept). It starts a server for each round or bench step and ends it afterwards, and keeps ``runs/<run>/servers.jsonl``:
each session with its part of the server's audit log, for the audit trail and the scorecard.

One run uses the servers at a time (``holder.json`` beside the work tree), until it is done or a person stops it.
What a server refuses, a call that times out and a server that exits are BLOCKED: a person decides (D7). The release
check stays direct until the build server's ``run_check release`` reads the bench server's results.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import checks, gitwork, mcpclient
from .constants import APP_NAME, DOCKER_BIN

MODES = ("direct", "servers")
BUILD_CHECKS = ("build", "static", "unit", "size", "trace")  # before the bench, on the build server
BENCH_CHECKS = ("runtime-limits", "logdiff")  # after the bench, on the bench server
CALLS = "servers.jsonl"  # runs/<run>/servers.jsonl
HOLDER = "holder.json"  # beside the work tree: the run that uses the servers
FREE = ("done", "stopped")  # a holder run in one of these has given the servers back
MARK = "vstatd-team-server-worktree"  # in the work tree's .git: the app made this repository (move_tree)
MARGIN_S = 60  # a call's time on top of the server's own timeout for it
READ_S = 120
REQUESTER = "bench MCP server (role {role}, session {session})"  # how mcp/bench names its requests at the console
CLASSES = ("read-only", "controlled-write", "physical")
UNIT_LISTED = 10  # checks/lib/check_unit.py lists at most this many failed tests per build
_FAILED = re.compile(r"plain: FAILED (\S+)")
# mcp/build's refusal at its bound (core.py charge_cross_attempt)
_AT_BOUND = re.compile(r"cross attempts failed (\d+) times in a row: the first attempt and the (\d+) retries")


def repair_count(out: Any) -> dict[str, int] | None:
    """``{failures_in_a_row, limit_retries}`` of a ``run_check build`` answer (mcp/build adds it to every cross
    attempt), or None."""
    r = out.get("repair") if isinstance(out, dict) else None
    keys = ("failures_in_a_row", "limit_retries")
    if isinstance(r, dict) and all(isinstance(r.get(k), int) and not isinstance(r.get(k), bool) for k in keys):
        return {k: r[k] for k in keys}
    return None


def at_bound(n: int, m: int) -> str:
    """Why a round is held at the build server's own bound (TR §5.1), for a person. mcp/build refuses only once more
    than *m* attempts in a row failed, so at ``n == m`` one attempt is left; past it the server refuses."""
    said = f"build 服务器的交叉构建已连续失败 {n} 次、上限 {m}（TR §5.1 的重试次数）"
    if n > m:
        return f"{said}，build 服务器已经拒绝交叉构建：你决定以后，用下面的命令重置计数，再点「重试」"
    return f"{said}：再失败一次，build 服务器就会拒绝之后的交叉构建。点「重试」用掉最后一次尝试"


def reset_command(team: dict[str, Any], n: int) -> str:
    """The command a person runs to reset the build server's repair count: the server's own Python and config file
    from the team file, the home folder written as ``~``."""
    words = team["servers"]["build"]
    conf = words[words.index("--config") + 1]
    home = os.path.expanduser("~")
    tilde = (lambda w: "~" + w[len(home):] if w == home or w.startswith(home + "/") else w)  # noqa: E731
    return (f"{tilde(words[0])} -I -m buildserver.admin reset-repair --config {tilde(conf)} "
            f"--reason \"a person decided after {n} failed cross builds\"")


class Unavailable(RuntimeError):
    """The servers cannot be used now (their configuration, another run holding them, the work tree): a person."""


def on(team: dict[str, Any]) -> bool:
    return team.get("connectors") == "servers"


def board_decides(team: dict[str, Any]) -> bool:
    """Whether the board offers 批准 / 拒绝 for bench requests: always in direct mode (D3); in servers mode only with
    ``servers.board_decides`` (the trial, both servers as the current user, D17). With the servers as their own users
    the board cannot write the bench state, so the switch is off there."""
    return not on(team) or (team.get("servers") or {}).get("board_decides") is True


def _words(x: Any) -> bool:
    return isinstance(x, list) and bool(x) and all(isinstance(w, str) and w for w in x)


def check(team: dict[str, Any]) -> None:
    """``connectors`` (direct by default) and ``servers``: ``{build: [命令和参数], bench: [命令和参数]}``, each with
    ``--config <file>``; or a ValueError saying what is wrong."""
    mode = team.get("connectors", "direct")
    if mode not in MODES:
        raise ValueError("team.json：connectors 只能是 direct 或 servers")
    sv = team.get("servers")
    keys = {"build", "bench"}
    if sv is not None and not (isinstance(sv, dict) and keys <= set(sv) <= keys | {"board_decides"}
                               and all(_words(sv[k]) and "--config" in sv[k][:-1] for k in ("build", "bench"))
                               and isinstance(sv.get("board_decides", False), bool)):
        raise ValueError("team.json：servers 要写成 {build: [命令和参数], bench: [命令和参数]}，每条都带 --config 配置文件"
                         "（board_decides 可选，true 或 false）")
    if mode != "servers":
        return
    if sv is None or not team.get("checks") or not team.get("bench"):
        raise ValueError("team.json：connectors 是 servers 就要有 servers、checks 和 bench")
    for c in team["checks"]:
        where = {"before_bench": BUILD_CHECKS, "after_bench": BENCH_CHECKS}.get(c["when"])
        if where is not None and c["name"] not in where:
            raise ValueError(f"team.json：servers 模式下检查 {c['name']} 不归任何服务器（{c['when']} 只能是 {'、'.join(where)}）")


@dataclass(frozen=True)
class Setup:
    build: list[str]
    bench: list[str]
    workspace: Path
    triage: Path
    build_state: Path
    bench_state: Path
    timeouts: dict[str, float]

    @property
    def holder(self) -> Path:
        return self.workspace.parent / HOLDER


def _argv(words: list[str]) -> list[str]:
    return [os.path.expanduser(w) if w.startswith("~") else w for w in words]


def setup(team: dict[str, Any]) -> Setup:
    """What the app needs of the two servers' configuration files; Unavailable when they cannot be read."""
    sv = team["servers"]
    try:
        import tomllib  # Python 3.11+ (Kiro Crew's is 3.12); direct mode does not need it
    except ImportError as exc:
        raise Unavailable("servers 模式要 Python 3.11 以上（读服务器的 TOML 配置）") from exc

    def conf(name: str) -> dict[str, Any]:
        words = _argv(sv[name])
        path = Path(words[words.index("--config") + 1])
        try:
            return tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise Unavailable(f"读不了 {name} 服务器的配置 {path}：{exc}") from exc

    def path(c: dict[str, Any], key: str, name: str) -> Path:
        v = (c.get("paths") or {}).get(key)
        if not isinstance(v, str) or not v:
            raise Unavailable(f"{name} 服务器的配置里没有 paths.{key}")
        return Path(v).expanduser()

    b, c = conf("build"), conf("bench")
    triage = path(b, "triage", "build")
    if path(c, "triage", "bench").resolve() != triage.resolve():
        raise Unavailable("build 和 bench 服务器的 paths.triage 不是同一个文件")
    times = {"approval": 300.0, "deploy": 600.0, "replay": 900.0, "check": 600.0}
    times.update({k: float(v) for k, v in (c.get("timeouts") or {}).items()
                  if k in times and isinstance(v, (int, float)) and not isinstance(v, bool)})
    return Setup(_argv(sv["build"]), _argv(sv["bench"]), path(b, "workspace", "build"), triage,
                 path(b, "state", "build"), path(c, "state", "bench"), times)


def _json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _replace(dest: Path, data: bytes) -> None:
    """The file replaced in its folder (the folder itself is kept: the build server checks its identity)."""
    tmp = dest.with_name(f".{dest.name}.{os.getpid()}.tmp")
    tmp.write_bytes(data)
    tmp.chmod(0o644)
    os.replace(tmp, dest)


# --- one run at a time ------------------------------------------------------------------------------------------ #

def take(st: Setup, rid: str, runs: Path) -> None:
    """The servers for run *rid*: free, its own already, or held by a run that has given them back (its ``run.json``
    under *runs*): done, stopped, hidden, or failed and not waiting for a person. Unavailable names the run."""
    held = _json(st.holder)
    other = str(held.get("run")) if isinstance(held, dict) and held.get("run") else None
    if other and other != rid:
        state = _json(Path(runs) / other / "run.json")
        if isinstance(state, dict) and holds(state):
            raise Unavailable(f"build / bench 服务器正被运行 {other} 用着（它做完、被人停下或隐藏以后才能用）")
    if other != rid:
        st.holder.parent.mkdir(parents=True, exist_ok=True)
        _replace(st.holder, (json.dumps({"run": rid, "at": time.time()}) + "\n").encode())


def holds(state: dict[str, Any]) -> bool:
    """Whether a run still holds the servers: it is going, or it failed and waits for a person (the servers, its
    checks or its bench step held: 重试 or a registration carries it on with the servers it had)."""
    if state.get("hidden") or state.get("status") in FREE:
        return False
    if state.get("status") != "failed":
        return True
    return bool(state.get("servers_held") or (state.get("tests") or {}).get("held")
                or (state.get("bench") or {}).get("held"))


# --- the work tree and the triage --------------------------------------------------------------------------------- #

def put_triage(st: Setup, triage: Path) -> None:
    """The run's approved triage and its record into the servers' triage folder, when they differ; a run without one
    leaves none there (no other run's triage is judged)."""
    for src, dest in ((Path(triage), st.triage), (Path(f"{triage}.sha256"), Path(f"{st.triage}.sha256"))):
        data = src.read_bytes() if src.is_file() else None
        if data is None:
            dest.unlink(missing_ok=True)
        elif not (dest.is_file() and dest.read_bytes() == data):
            _replace(dest, data)


async def move_tree(st: Setup, run_wt: Path, commit: str) -> None:
    """The build server's work tree (a repository of its own, made once) at *commit* of the run, clean."""
    ws = st.workspace
    if not (ws / ".git").is_dir():
        if ws.exists() and any(ws.iterdir()):
            raise Unavailable(f"build 服务器的工作树 {ws} 既不是空目录也不是 git 仓库")
        ws.mkdir(parents=True, exist_ok=True)
        await gitwork.git(ws, "init", "-q")
        (ws / ".git" / MARK).write_text("made by vstatd-team for the build server (D17)\n", encoding="utf-8")
    if not (ws / ".git" / MARK).is_file():  # checkout --force and clean -fdx below would lose its untracked files
        raise Unavailable(f"build 服务器的工作树 {ws} 是一个不是 app 建的 git 仓库：检查 build 服务器配置的 "
                          "paths.workspace（要是一个空目录，app 第一次用时把它建成仓库）")
    await gitwork.git(ws, "fetch", "-q", "--no-tags", "--force", str(run_wt), "+refs/heads/*:refs/remotes/run/*",
                      timeout=300)
    await gitwork.git(ws, "checkout", "-q", "--detach", "--force", commit)
    await gitwork.git(ws, "clean", "-q", "-fdx")


async def tests_commit(st: Setup, base: str, head: str) -> str:
    """Tests first: a commit on no branch with the code of *base* and the tests of *head* (the work tree is moved back
    by the caller)."""
    ws = st.workspace
    await gitwork.git(ws, "checkout", "-q", "--detach", "--force", base)
    await gitwork.git(ws, "clean", "-q", "-fdx")
    await gitwork.git(ws, "rm", "-r", "-q", "--ignore-unmatch", "--", "tests")
    await gitwork.git(ws, "checkout", head, "--", "tests", ok=(0, 1))
    await gitwork.git(ws, "commit", "-q", "--allow-empty", "-m",
                      f"vstatd-team tests first: the tests of {head[:12]} on {base[:12]} (on no branch)")
    return (await gitwork.git(ws, "rev-parse", "HEAD"))[1].strip()


# --- a server session ------------------------------------------------------------------------------------------- #

def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _audit_lines(path: str, start: int, end: int | None = None) -> list[dict[str, Any]]:
    try:
        with open(path, "rb") as f:
            f.seek(start)
            blob = f.read((end - start) if end is not None else -1)
    except OSError:
        return []
    out = []
    for line in blob.decode(errors="replace").splitlines():
        with contextlib.suppress(ValueError):
            r = json.loads(line)
            if isinstance(r, dict):
                out.append(r)
    return out


class Session:
    """One server process for one round or bench step. Its part of the server's audit log is recorded in *calls*
    when it ends (and, by announce(), while a physical call waits for the console)."""

    def __init__(self, st: Setup, which: str, calls: Path, label: str) -> None:
        self.which, self.calls, self.label = which, Path(calls), label
        self.audit = (st.build_state if which == "build" else st.bench_state) / "audit.jsonl"
        self.client = mcpclient.StdioClient(st.build if which == "build" else st.bench, env=env())
        self.start = 0

    async def __aenter__(self) -> "Session":
        self.start = _size(self.audit)
        await self.client.start()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.client.close()
        self._record(_size(self.audit))

    async def call(self, tool: str, args: dict[str, str] | None = None, *, timeout_s: float = READ_S) -> Any:
        out = await self.client.call_tool(tool, args, timeout_s=timeout_s)
        if not isinstance(out, dict):
            raise mcpclient.McpError(f"{tool}: the answer is not an object")
        return out

    def requesters(self, end: int | None = None) -> list[str]:
        return sorted({REQUESTER.format(role=r["role"], session=r["session"])
                       for r in _audit_lines(str(self.audit), self.start, end) if r.get("session") and r.get("role")})

    def announce(self) -> None:
        """While a request waits at the console: the session's requester, so the board ties the request to the run."""
        self._record(None)

    def _record(self, end: int | None) -> None:
        line = {"at": time.time(), "server": self.which, "label": self.label, "audit": str(self.audit),
                "from": self.start, "to": end, "requesters": self.requesters(end) if self.which == "bench" else []}
        self.calls.parent.mkdir(parents=True, exist_ok=True)
        with open(self.calls, "a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")


def env() -> dict[str, str]:
    """A server's environment: the app's PATH with docker's folder first (the servers run `docker` from PATH, and
    Kiro Crew's gateway has /usr/bin:/bin:/usr/sbin:/sbin only)."""
    path = os.environ.get("PATH") or "/usr/bin:/bin"
    docker = str(Path(DOCKER_BIN).parent) if os.path.isabs(DOCKER_BIN) else ""
    return mcpclient.server_env({"PATH": f"{docker}:{path}" if docker and docker not in path.split(":") else path})


def sessions(root: Path) -> list[dict[str, Any]]:
    """The run's server sessions (runs/<run>/servers.jsonl)."""
    return _audit_lines(str(Path(root) / CALLS), 0)


def requesters(root: Path) -> set[str]:
    """Who the run's bench requests name: the bench server's sessions it started."""
    return {r for s in sessions(root) for r in s.get("requesters") or []}


def ours(rid: str, repo: Any) -> set[str]:
    """Who the requests of run *rid* name at the console: the app (direct mode) and its bench server sessions."""
    return {f"{APP_NAME} {rid}"} | (requesters(Path(str(repo)).parent) if repo else set())


def tool_calls(root: Path) -> dict[str, int] | None:
    """The app's tool calls of the run by permission class, from the servers' audit logs, and how many the servers
    refused: one per outcome line (a call refused before it began has no ``started`` line). The ``lease_release``
    a bench session writes for itself when it ends is not a call. None: the run used no server."""
    done = [s for s in sessions(root) if isinstance(s.get("to"), int)]
    if not done:
        return None
    out = {**{c: 0 for c in CLASSES}, "refused": 0}
    for s in done:
        for r in _audit_lines(str(s["audit"]), int(s["from"]), int(s["to"])):
            if (r.get("outcome") == "started" or r.get("class") not in CLASSES
                    or str(r.get("detail") or "").startswith("released: ")):
                continue
            out[r["class"]] += 1
            out["refused"] += r.get("outcome") == "refused"
    return out


# --- the checks ------------------------------------------------------------------------------------------------- #

def _blocked(why: str) -> dict[str, Any]:
    return {"verdict": "BLOCKED", "reasons": [why], "tier": None, "summary": "服务器没给结果"}


def held_round(team: dict[str, Any], why: str, *, head: str, results: Path, phase: str = "before_bench",
               **_: Any) -> Any:
    """A round the servers could not run at all: every check of *phase* BLOCKED with *why*."""
    async def go() -> dict[str, Any]:
        items = [c for c in team.get("checks") or [] if c["when"] == phase]
        rows: list[dict[str, Any]] = []
        cases: list[dict[str, Any]] = []
        for c in items:
            checks.add_result(rows, cases, c, _blocked(why), Path(results), team, 0)
        return {**checks.wall([c["name"] for c in items], rows, cases, head, Path(results)),
                "server_held": [c["name"] for c in items]}
    return go()


def _result(out: dict[str, Any], name: str, which: str, head: str | None, results: Path) -> tuple[dict[str, Any], bool]:
    """A server's run_check answer as the adapter's result (the check's own result file is kept in *results*), and
    whether a server problem, not the check, made it BLOCKED."""
    (results / f"{name}.run.log").write_text(str(out.get("summary") or ""), encoding="utf-8")
    data = out.get("result") if isinstance(out.get("result"), dict) else None
    if data is not None:
        (results / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    verdict = out.get("verdict")
    if data is None or verdict not in checks.STATUS:
        return _blocked(f"{which} 服务器：{out.get('problem') or out.get('outcome') or '没有结果'}"), True
    if head and data.get("commit") not in (head, None):
        return _blocked(f"build 服务器判的是 {str(data.get('commit'))[:12]}，不是这一轮的 {head[:12]}"), True
    return {"verdict": verdict, "reasons": [str(r) for r in data.get("reasons") or []], "tier": data.get("tier"),
            "summary": str(data.get("summary") or ""), "commit": data.get("commit")}, False


async def run_tests(run_wt: Path, team: dict[str, Any], **kw: Any) -> dict[str, Any]:
    """Deps.run_tests: the checks of a round through the servers in servers mode, else as checks.run_checks does. The
    release check stays direct; in servers mode it is given every input file the servers' results recorded."""
    if not on(team):
        return await checks.run_checks(run_wt, team, **kw)
    if kw.get("phase") == "release":
        inputs = _inputs(Path(kw["results"]), Path(run_wt).parents[1])
        return await checks.run_checks(run_wt, team, inputs_ro=inputs, **kw)
    return await _round(Path(run_wt), team, **kw)


def _inputs(results: Path, root: Path) -> tuple[Path, ...]:
    out: list[Path] = []
    for p in sorted(results.glob("*.json")):
        for inp in ((_json(p) or {}).get("inputs") or {}).values():
            path = Path(str((inp or {}).get("path") or "")) if isinstance(inp, dict) else None
            if path and path.is_absolute() and path.is_file() and not path.resolve().is_relative_to(root.resolve()):
                out.append(path)
    return tuple(dict.fromkeys(out))


async def _round(run_wt: Path, team: dict[str, Any], *, head: str, results: Path, phase: str = "before_bench",
                 triage: Path | None = None, run: Path | None = None, **_: Any) -> dict[str, Any]:
    results = Path(results)
    results.mkdir(parents=True, exist_ok=True)
    root = run_wt.parents[1]
    which = "build" if phase == "before_bench" else "bench"
    items = [c for c in team.get("checks") or [] if c["when"] == phase]
    try:
        st = setup(team)
        put_triage(st, Path(triage) if triage else root / "triage.json")
        if which == "build":
            await move_tree(st, run_wt, head)
    except (Unavailable, gitwork.GitError, OSError) as exc:
        return await held_round(team, str(exc), head=head, results=results, phase=phase)
    rows: list[dict[str, Any]] = []
    cases: list[dict[str, Any]] = []
    held: list[str] = []
    repair: dict[str, int] | None = None  # the build server's repair count, as its last cross attempt left it
    gone = ""  # the session ended: the rest of the round cannot run
    try:
        async with Session(st, which, root / CALLS, f"{phase} {results.name}") as s:
            if which == "build":
                ws = await s.call("workspace_status")
                if ws.get("head") != head or ws.get("changes"):
                    raise Unavailable(f"build 服务器的工作树不在 {head[:12]}，或有没提交的改动")
            else:
                await s.call("lease_acquire")
            for c in items:
                started = time.time()
                if gone:
                    res, server = _blocked(gone), True
                else:
                    try:
                        out = await s.call("run_check", {"check": c["name"]},
                                           timeout_s=float(c["timeout_s"]) + MARGIN_S)
                        res, server = _result(out, c["name"], which, head if which == "build" else None, results)
                        repair = repair_count(out) if which == "build" and c["name"] == "build" else repair
                        if which == "bench" and run is not None and out.get("run") != Path(run).name:
                            # another session replayed between this run's steps (D17): not this step's replay
                            res, server = _blocked(f"bench 服务器判的是回放 {out.get('run')}，不是这一步的 "
                                                   f"{Path(run).name}：期间有别的会话回放过"), True
                    except mcpclient.ToolRefused as exc:
                        bound = _AT_BOUND.search(str(exc)) if which == "build" else None
                        if bound:  # at its own bound: worded as the hold before it (Run._repair_stop)
                            n, m = int(bound.group(1)), int(bound.group(2))
                            repair = {"failures_in_a_row": n, "limit_retries": m}
                            res, server = _blocked(at_bound(n, m)), True
                        else:
                            res, server = _blocked(f"{which} 服务器拒绝了：{exc}"), True
                    except mcpclient.McpError as exc:
                        gone = f"{which} 服务器：{exc}"
                        res, server = _blocked(gone), True
                checks.add_result(rows, cases, c, res, st.workspace, team, round((time.time() - started) * 1000))
                held += [c["name"]] if server else []
            if which == "bench" and not gone:
                with contextlib.suppress(mcpclient.McpError):
                    await s.call("lease_release")
    except (Unavailable, mcpclient.McpError) as exc:
        if not rows:
            return await held_round(team, f"{which} 服务器：{exc}", head=head, results=results, phase=phase)
    return {**checks.wall([c["name"] for c in items], rows, cases, head, results), "server_held": held,
            **({"repair": repair} if repair else {})}


async def tests_first(run_wt: Path, team: dict[str, Any], *, base: str, head: str, triage: dict[str, Any],
                      results: Path) -> dict[str, Any]:
    """checks.tests_first through the build server: ``run_check unit`` on a commit with the code of *base* and the
    tests of *head*, then the work tree back at *head*. unit.sh lists the failed tests (at most UNIT_LISTED per build);
    a new test it did not list may have passed, or may not: when that cannot be told, Unavailable (a person)."""
    run_wt, results = Path(run_wt), Path(results)
    results.mkdir(parents=True, exist_ok=True)
    root = run_wt.parents[1]
    named, reasons = await checks.new_tests(run_wt, base=base, head=head, triage=triage)
    out = {"ok": False, "reasons": reasons, "tests": named, "results": str(results), "base": base, "head": head}
    names = sorted({n for ns in named.values() for n in ns})
    if not names:
        out["ok"] = not reasons
        return out
    st = setup(team)
    put_triage(st, root / "triage.json")
    await move_tree(st, run_wt, head)
    temp = await tests_commit(st, base, head)
    try:
        async with Session(st, "build", root / CALLS, f"tests-first {results.name}") as s:
            ws = await s.call("workspace_status")
            if ws.get("head") != temp:
                raise Unavailable(f"build 服务器的工作树不在测试先行的提交 {temp[:12]}")
            got = await s.call("run_check", {"check": "unit"},
                               timeout_s=float(next((c["timeout_s"] for c in team["checks"] if c["name"] == "unit"),
                                                    checks.DEFAULT_TIMEOUT_S)) + MARGIN_S)
    except mcpclient.McpError as exc:
        raise Unavailable(f"测试先行：build 服务器：{exc}") from exc
    finally:
        await gitwork.git(st.workspace, "checkout", "-q", "--detach", "--force", head)
        await gitwork.git(st.workspace, "clean", "-q", "-fdx")
    data = got.get("result") if isinstance(got.get("result"), dict) else None
    if data is not None and data.get("commit") != temp:
        raise Unavailable(f"测试先行：build 服务器判的是 {str(data.get('commit'))[:12]}，不是测试先行的提交 {temp[:12]}")
    if data is not None:
        (results / "unit.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (results / "tests-first.log").write_text(str(got.get("summary") or ""), encoding="utf-8")
    verdict, said = got.get("verdict"), [str(r) for r in (data or {}).get("reasons") or []]
    failed = {checks._normalize(m.group(1)) for r in said if (m := _FAILED.match(r))}
    if verdict == "PASS":
        ran = {n: False for n in names}
    elif failed:
        if len(failed) >= UNIT_LISTED and not set(names) <= failed:
            raise Unavailable(f"测试先行：unit.sh 只列出前 {UNIT_LISTED} 个失败的测试，看不出新测试是不是都失败了")
        ran = {n: n in failed for n in names}
    else:
        out["reasons"] = reasons + [f"新测试在需求提交 {base[:12]} 的代码上没有跑起来（unit.sh {verdict}）："
                                    + " / ".join(said[:3])[:300]]
        return out
    reasons = checks.judge_first(named, ran, base, reasons)
    out.update(ok=not reasons, reasons=reasons, failed=sorted(n for n in names if ran.get(n)))
    return out


# --- the bench actions ------------------------------------------------------------------------------------------ #

async def physical(team: dict[str, Any], root: Path, action: str, label: str) -> dict[str, Any]:
    """deploy or replay through the bench server, under its lease → {kind: ok|refused|timeout|unknown|failed, why,
    out}. The person approves at the operator console; nothing is retried."""
    try:
        st = setup(team)
    except Unavailable as exc:
        return {"kind": "failed", "why": str(exc), "out": {}}
    timeout = st.timeouts["approval"] + st.timeouts[action] + MARGIN_S
    try:
        async with Session(st, "bench", Path(root) / CALLS, label) as s:
            await s.call("lease_acquire")
            s.announce()
            try:
                out = await s.call(f"request_{action}", timeout_s=timeout)
            finally:
                with contextlib.suppress(mcpclient.McpError):
                    await s.call("lease_release")
    except mcpclient.ToolRefused as exc:
        text = str(exc)
        kind = ("timeout" if "(timeout)" in text else "unknown" if "did not finish within its timeout" in text
                else "refused")
        return {"kind": kind, "why": text, "out": {}}
    except mcpclient.McpError as exc:
        return {"kind": "failed", "why": f"bench 服务器：{exc}", "out": {}}
    if out.get("outcome") != "ok":
        tail = [ln for ln in str(out.get("log_tail") or "").splitlines() if ln.strip()]
        return {"kind": "failed", "why": tail[-1] if tail else str(out.get("outcome")), "out": out}
    return {"kind": "ok", "why": "", "out": out}
