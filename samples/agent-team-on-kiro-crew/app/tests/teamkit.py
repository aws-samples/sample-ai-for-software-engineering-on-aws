"""Fakes for the sequencer tests: a SubagentManager stand-in, a test runner decided by files, agent simulators."""

from __future__ import annotations

import importlib
import json
import re
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import backend.routes  # noqa: F401  (bootstraps the private namespace the app's modules live in)


def mod(name: str) -> Any:
    return importlib.import_module(f"_aidlcteam_backend.team.{name}")


constants, gitwork, team_mod, store_mod = mod("constants"), mod("gitwork"), mod("team"), mod("store")
ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "ui" / "src" / "test" / "fixtures" / "board-running.json"
TYPES_TS = ROOT / "ui" / "src" / "types.ts"


def info(aid: str, task: str, **kw: Any) -> SimpleNamespace:
    now = time.time()
    base = dict(id=aid, task=task, started=now, done=False, queued=False, queued_reason="", queued_reason_detail="",
                result="", error="", user_stopped=False, turns=0, tool_count=0, last_tool="", last_activity=now,
                stalled=False, _awaiting_approval=False, streaming_text="", parent_session_key="", cwd="",
                conversation_key="", app="", elapsed=0.0)
    base.update(kw)
    return SimpleNamespace(**base)


class FakeManager:
    """The role-session manager's surface (``spawn_session``, ``continue_conversation_async``, ``get`` …): records starts
    and continuations; agents are SimpleNamespaces a test flips to done."""

    def __init__(self, cap: int = 4) -> None:
        self.agents: dict[str, SimpleNamespace] = {}
        self._queue: list[dict[str, Any]] = []
        self.spawned: list[tuple[str, str, dict[str, Any]]] = []
        self.continued: list[tuple[str, str, str, dict[str, Any]]] = []
        self.cancelled: list[str] = []
        self.max_concurrent = cap
        self.refuse = ""  # spawn answers a refusal with this error
        self.full = False  # spawn answers None
        self.gone = False  # a continuation answers conversation_gone
        self.calls: dict[str, list[dict[str, Any]]] = {}  # each agent's tool calls, as a session transcript has them
        self._n = 0

    def _new(self, task: str, kw: dict[str, Any]) -> SimpleNamespace:
        self._n += 1
        a = info(f"ag{self._n:02d}", task, parent_session_key=kw.get("parent_session_key", ""), cwd=kw.get("cwd", ""),
                 conversation_key=kw.get("conversation_key", ""), app=kw.get("app", ""))
        self.agents[a.id] = a
        return a

    def spawn_session(self, task: str, **kw: Any) -> Any:
        if self.full:
            return None
        if self.refuse:
            return info("refused", task, done=True, error=self.refuse)
        a = self._new(task, kw)
        self.spawned.append((a.id, task, kw))
        return a

    def add(self, calls: list[tuple[str, dict[str, Any]]]) -> None:
        for aid, call in calls:
            self.calls.setdefault(aid, []).append(call)

    def recent(self, aid: str | None) -> list[dict[str, Any]]:
        return self.calls.get(aid or "", [])[-8:]

    def history(self, aid: str) -> list[dict[str, Any]]:
        return list(self.calls.get(aid, []))

    def credits_of(self, aid: str) -> float | None:
        return None

    async def continue_conversation_async(self, conv_id: str, task: str, **kw: Any) -> Any:
        if self.gone:
            return info("gone", task, done=True, error="conversation_gone: no resumable session remains")
        a = self._new(task, kw)
        self.continued.append((conv_id, a.id, task, kw))
        return a

    def get(self, aid: str) -> Any:
        return self.agents.get(aid)

    @property
    def all_agents(self) -> list[Any]:
        return list(self.agents.values())

    @property
    def running_count(self) -> int:
        return sum(not a.done for a in self.agents.values())

    @property
    def queued_count(self) -> int:
        return len(self._queue)

    async def cancel(self, aid: str) -> bool:
        a = self.agents.get(aid)
        if a is None or a.done:
            return False
        a.done, a.user_stopped = True, True
        self.cancelled.append(aid)
        return True

    async def cancel_for_parent(self, parent: str) -> tuple[int, int]:
        for a in list(self.agents.values()):
            if a.parent_session_key == parent and not a.done:
                await self.cancel(a.id)
        return 0, 0

    def live(self) -> list[SimpleNamespace]:
        return [a for a in self.agents.values() if not a.done]

    def role_of(self, a: SimpleNamespace) -> str:
        return a.task.split("role=", 1)[1].split(" ", 1)[0]

    def by_role(self, role: str) -> SimpleNamespace:
        return [a for a in self.agents.values() if self.role_of(a) == role][-1]


def sh(cwd: Any, *args: str) -> str:
    return subprocess.run([constants.GIT_BIN, "-C", str(cwd), *args], check=True, capture_output=True, text=True,
                          env=gitwork._ENV).stdout


def act(a: SimpleNamespace, files: dict[str, str | None], commit: bool = True, msg: str = "") -> None:
    """The agent writes (None: deletes) files in its worktree and, by default, commits them."""
    wt = Path(a.cwd)
    a.tool_count += 1
    for rel, text in files.items():
        p = wt / rel
        if text is None:
            sh(wt, "rm", "-q", "--", rel)
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
    if commit:
        sh(wt, "add", "-A")
        subprocess.run([constants.GIT_BIN, "-C", str(wt), "commit", "-q", "-m", msg or "[agent] work"],
                       capture_output=True, env=gitwork._ENV)  # nothing to commit is fine


def finish(a: SimpleNamespace, summary: str | None = "做完了", error: str = "") -> None:
    a.result = f"我改了几个文件。\n\nDONE: {summary}" if summary else "没写总结"
    a.error, a.done = error, True


class FakeTests:
    """The test wall decided by files in the integration worktree: rules are (case id, owner, passes(wt))."""

    def __init__(self, rules: list[tuple[str, str | None, Callable[[Path], bool]]]) -> None:
        self.rules, self.calls = rules, 0

    async def __call__(self, wt: Path, team: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        cases, leave = [], set(team.get("skip_owners") or [])  # as checks.run_tests: a role sitting the run out is not tested
        for cid, owner, ok in self.rules:
            if owner in leave:
                continue
            good = ok(Path(wt))
            file, ac = cid.split("#")
            cases.append({"id": cid, "ac": ac, "name": f"{ac}: 用例", "file": f"tests/{file}", "status": "pass" if good else "fail",
                          "owner": owner, "ms": 3, "message": None if good else "expected 409, got 201"})
        passed = sum(c["status"] == "pass" for c in cases)
        return {"at": time.time(), "command": "node --test tests/", "cases": cases, "passed": passed,
                "failed": len(cases) - passed, "total": len(cases)}


def read(wt: Path, rel: str) -> str:
    try:
        return (wt / rel).read_text(encoding="utf-8")
    except OSError:
        return ""


def default_tests() -> FakeTests:
    return FakeTests([
        ("api-signup.test.js#AC-6", "backend", lambda wt: "v2" in read(wt, "backend/server.js")),
        ("web-render.test.js#AC-1", "frontend", lambda wt: (wt / "frontend/index.html").exists()),
    ])


def make_run(tmp: Path, mgr: FakeManager, tests: Any = None, *, requirement: str = "", now: Callable[[], float] = time.time,
             team: dict[str, Any] | None = None, rid: str = "r1006test") -> Any:
    team = team or team_mod.load_team(constants.TEAM_FILE)
    deps = make_deps(tmp, mgr, tests or default_tests(), now=now)
    state = team_mod.new_state(rid, requirement, team, constants.TASK_TEMPLATE_FILE.read_text(encoding="utf-8"),
                               tmp / "work", constants.TARGET_TEMPLATE, now())
    return team_mod.TeamRun(state, deps)


def make_deps(tmp: Path, mgr: FakeManager, tests: Any, *, now: Callable[[], float] = time.time) -> Any:
    return team_mod.Deps(store=store_mod.Store(tmp / "data" / "runs"), manager=lambda: mgr, run_tests=tests,
                         template=constants.TARGET_TEMPLATE, now=now)


def reload(tmp: Path, mgr: FakeManager, tests: Any, **kw: Any) -> Any:
    """The run as a restarted app builds it: from run.json and events.jsonl only."""
    deps = make_deps(tmp, mgr, tests, **kw)
    (state, events), = deps.store.load_all()
    return team_mod.TeamRun(state, deps, events)


def ts_types() -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """ui/src/types.ts, loosely: object type → its field names, string union → its values."""
    text = TYPES_TS.read_text(encoding="utf-8")
    objects = {m.group(1): set(re.findall(r"^  (\w+)\??:", m.group(2), re.M))
               for m in re.finditer(r"export type (\w+) = \{\n(.*?)\n\}", text, re.S)}
    objects.update({m.group(1): set(re.findall(r"(?:^|;)\s*(\w+)\??:", m.group(2)))  # one-line types
                    for m in re.finditer(r"export type (\w+) = \{ (.*) \}$", text, re.M)})
    bare = re.sub(r"//[^\n]*|/\*.*?\*/", "", text, flags=re.S)
    unions = {m.group(1): set(re.findall(r"'([^']+)'", m.group(2)))
              for m in re.finditer(r"export type (\w+) =\s*((?:\|?\s*'[^']+'\s*)+)", bare)}
    return objects, unions


def same_shape(mine: Any, ref: Any, path: str = "board") -> None:
    """Every dict in *mine* has exactly the keys of its counterpart in *ref* (the fixture), all the way down."""
    if isinstance(ref, dict):
        assert isinstance(mine, dict), f"{path}: {type(mine).__name__}, not an object"
        assert set(mine) == set(ref), f"{path}: extra {set(mine) - set(ref)}, missing {set(ref) - set(mine)}"
        for k, v in ref.items():
            if v is not None and mine[k] is not None:
                same_shape(mine[k], v, f"{path}.{k}")
    elif isinstance(ref, list) and ref and isinstance(mine, list):
        for i, item in enumerate(mine):
            same_shape(item, ref[0], f"{path}[{i}]")


def richest(items: list[dict[str, Any]]) -> dict[str, Any]:
    """The fixture lane with the most filled-in nested data, the reference for every lane."""
    return max(items, key=lambda x: len(json.dumps(x)))


def mini_team() -> dict[str, Any]:
    """Four roles, for flows that only need a reviewer at the end of a fix loop."""
    role = lambda key, title, deps, writable: {"key": key, "title": title, "emoji": "", "depends_on": deps,  # noqa: E731
                                               "writable": writable, "outputs": [], "brief": f"{title}的活"}
    return team_mod.check_team({
        "version": 1, "test_command": ["node", "--test", "tests/"],
        "roles": [role("pm", "产品经理", [], ["docs/product/**"]), role("backend", "后端", ["pm"], ["backend/**"]),
                  role("frontend", "前端", ["pm"], ["frontend/**"]), role("reviewer", "评审", ["backend", "frontend"], [])],
        "defaults": {"model": "claude-opus-5.5", "effort": "high", "max_fix_rounds": 2},
        "test_owners": [{"glob": "tests/api-*", "role": "backend"}, {"glob": "tests/web-*", "role": "frontend"}],
    })


OUTPUTS = {
    "pm": {"docs/product/acceptance.md": "AC-1: 首页\nAC-6: 名额\n"},
    "architect": {"contracts/api.md": "# API\n", "docs/architecture/layout.md": "# 布局\n"},
    "designer": {"docs/design/pages.md": "# 页面\n", "frontend/styles/main.css": "body {}\n"},
    "tester": {"tests/api-signup.test.js": "// AC-6\n", "tests/web-render.test.js": "// AC-1\n"},
    "backend": {"backend/server.js": "// v2\n"},
    "frontend": {"frontend/index.html": "<h1>活动</h1>\n"},
    "ops": {"ops/start.sh": "node backend/server.js\n", "Dockerfile": "FROM node:22\n"},
}


async def drive(run: Any, mgr: FakeManager, behave: Callable[[SimpleNamespace, str], None] | None = None,
                ticks: int = 40) -> None:
    """Tick until the run ends; each live agent does its role's work (or *behave*) and finishes."""
    for _ in range(ticks):
        await run.tick()
        if run.ended:
            return
        for a in mgr.live():
            role = mgr.role_of(a)
            if behave is not None:
                behave(a, role)
            elif role == "reviewer":
                finish(a, "可以交付")
            else:
                act(a, OUTPUTS[role])
                finish(a)
    raise AssertionError(f"run did not end: {run.s['status']}")
