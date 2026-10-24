"""The sequencer: one TeamRun per run. ``tick()`` moves a run forward; it is idempotent and restart-safe: all state
is in run.json, live agents are found again by id (a start whose id never reached run.json by the tag on its task's
first line), and every git step checks what is already done. Every role's agent is a Kiro Crew chat session
(``sessions.py``), started through the manager the deps hand out.

A role: waiting → (its dependencies merged) worktree from the run branch head, handoffs, spawn → queued / running /
stalled / awaiting_approval → done → the app commits its leftovers and merges it into the run branch → merged (or a
conflict, sent back) → the app runs the tests; failing cases go back to their owner, whose conversation is continued
(fixing), until green or out of fix rounds → the read-only reviewer → the run is done (failed if it still says 要改 when
its rounds are used up; a reviewer behind a person's gate hands that to the person instead).

A role marked ``"optional": true`` may sit a run out: its Crew member is not on the team's 「代理」 page when the run is
handed over (未入职), or the planner's 分工提案 leaves it out and the person approves (这次用不到).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from . import checks, gitwork
from . import delivery as delivery_mod
from . import standards as standards_mod
from .constants import APP_NAME, APP_ROOT, EVENTS_KEPT, TAG_PREFIX
from .store import Store
from .sessions import agent_fields, cancel, cancel_parent, find_agent, find_by_tag, first_line
from .toollog import short

ACTIVE = ("queued", "running", "stalled", "awaiting_approval", "fixing")
DONE_OK = ("merged", "skipped")  # a dependency that is done: merged, or not needed in this project
PENDING_GLOB = "（待分工）"  # what a role whose directories come from the ownership file may write until then: nothing
ENDED = ("done", "failed", "stopped")
LOST_GRACE_S = 60.0  # an agent KiroCrew no longer knows is given up on after this
TOOL_EVENT_GAP_S = 3.0  # at most one ``tool`` event per role this often
STATS_GAP_S, STATS_EVERY_S = 6.0, 30.0  # a running worktree's git stats: at most / at least this often
HUMAN_MARK = "【负责人退回】"  # a review-kind fix task that a person, not the reviewer, sent back
# a turn the model backend could not finish (an HTTP 5xx, a runtime that died): worth one more go in a new session
TRANSIENT_ERROR = re.compile(r"transient|HTTP 5\d\d|5xx|runtime failed|timed? ?out|overloaded|rate.?limit|throttl", re.I)
ERRORS_TO_FAIL = 30  # this many failing ticks in a row (about a minute) end the run
REPLY_KEEP = 20_000  # characters of an agent's last reply kept for the 产出 view
_DONE_RE = re.compile(r"(?<![A-Za-z])DONE\s*[:：]\s*(.*)$", re.M)  # also mid-line: KiroCrew joins messages with no break
REVIEW_KEEP = 12_000  # characters of a 要改 review a bounced role is given
TALK_KEEP = 2_000  # characters of a role's answer in a 讨论 at its gate, kept for the gate card
DECISIONS_FILE = "docs/aidlc/decisions.md"  # what people decided at the gates, written into the run branch by the app
# A review names who fixes what: its own `打回：` line (role keys or titles), else every 归X it writes.
_BOUNCE_LINE_RE = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)、]\s*)?[*_`]*打回[*_`]*\s*[:：]\s*(.+)$", re.M)  # a list item too
_OWNER_RE = re.compile(r"归([^）)，,；;。\n]{1,40})")
_ROLE_ALIASES = {"后端": "backend", "服务端": "backend", "前端": "frontend", "网页": "frontend", "网页前端": "frontend",
                 "移动端": "mobile", "安卓": "mobile", "Android": "mobile", "运维": "ops", "合规": "compliance",
                 "安全": "compliance", "合规与安全": "compliance", "测试": "tester", "体验设计": "designer",
                 "设计": "designer", "UI 设计": "designer", "产品经理": "pm", "产品": "pm", "架构师": "architect",
                 "架构": "architect"}


@dataclass
class Deps:
    """What a run needs from outside; tests pass fakes."""

    store: Store
    manager: Callable[[], Any]
    run_tests: Callable[[Path, dict[str, Any]], Awaitable[dict[str, Any]]]
    template: Path
    scrub: Callable[[str], str] = lambda s: s
    # 部署执行: (run id, run worktree, the role's "deploy" spec) → {"ok", "url" | "error"}; None: no deployment here
    deploy: Callable[[str, Path, dict[str, Any]], Awaitable[dict[str, Any]]] | None = None
    # the members on Crew's 「代理」 page of a workspace (None: not read yet, or not readable: nothing is held then)
    members: Callable[[str | None], set[str] | None] | None = None
    now: Callable[[], float] = time.time
    log: Any = field(default_factory=lambda: logging.getLogger(APP_NAME))


def load_team(path: Path) -> dict[str, Any]:
    return check_team(json.loads(Path(path).read_text(encoding="utf-8")))


def check_team(team: Any) -> dict[str, Any]:
    """team.json, validated (every dependency listed before its dependant, so no cycles) and filled in."""
    roles = team.get("roles") if isinstance(team, dict) else None
    if not isinstance(roles, list) or not roles:
        raise ValueError("team.json 里没有 roles")
    keys = [r.get("key") for r in roles]
    if len(set(keys)) != len(keys) or not all(isinstance(k, str) and re.fullmatch(r"[a-z][a-z0-9-]{0,23}", k) for k in keys):
        raise ValueError("team.json 里角色的 key 不对")
    for r in roles:
        for dep in r.setdefault("depends_on", []):
            if dep not in keys or keys.index(dep) >= keys.index(r["key"]):
                raise ValueError(f"team.json：{r['key']} 依赖的 {dep} 要排在它前面")
        r.setdefault("writable", [])
        r.setdefault("outputs", [])
        r.setdefault("title", r["key"])
        r.setdefault("emoji", "")
        r.setdefault("phase", "")
        r.setdefault("stage", "")
        if r.get("gate") not in (None, "human"):
            raise ValueError(f"team.json：{r['key']} 的 gate 只能是 human")
        if r.get("gate_revise_risk") is not None and clean_risk(r["gate_revise_risk"]) is None:
            raise ValueError(f"team.json：{r['key']} 的 gate_revise_risk 要写成 {{what, amount}}（amount 以元计）")
        if r.get("questions") is not None and not (r.get("gate") == "human" and isinstance(r["questions"], str) and _app_rel(r["questions"])):
            raise ValueError(f"team.json：{r['key']} 的 questions 要写成仓库里的相对路径，而且它要有人的关卡")
        if not isinstance(r.get("optional", False), bool):
            raise ValueError(f"team.json：{r['key']} 的 optional 要写 true 或 false")
        if r.get("writable_from") and not r["writable"]:
            r["writable"] = [PENDING_GLOB]
        if r.get("member") is not None and not (isinstance(r["member"], str) and re.fullmatch(r"[A-Za-z0-9][\w.-]{0,63}", r["member"])):
            raise ValueError(f"team.json：{r['key']} 的 member 要是 Crew 成员的名字")
    own = team.get("ownership")
    if own is not None and (not isinstance(own, dict) or own.get("from") not in keys or not isinstance(own.get("file"), str)):
        raise ValueError("team.json：ownership 要写明分工文件 file 和由谁写 from")
    if any(r.get("writable_from") for r in roles) and own is None:
        raise ValueError("team.json：有角色的目录由分工决定（writable_from），但没有 ownership")
    for name in [team.get("starter")] * ("starter" in team) + spec_packs(team) + [team.get("standards")] * ("standards" in team):
        if not _app_folder(name):
            raise ValueError(f"team.json：starter、spec_pack 和 standards 要写成 app 里的相对路径：{name}")
    delivery_mod.check(team)
    return team


def _app_rel(path: str) -> bool:
    """A path inside the target repo (no absolute path, no ``..``)."""
    return bool(path) and not path.startswith("/") and ".." not in Path(path).parts


def spec_packs(team: dict[str, Any]) -> list[str]:
    """The team's spec packs (folders of the app), in order: one name or a list."""
    pack = team.get("spec_pack")
    return [p for p in ([pack] if isinstance(pack, str) else pack if isinstance(pack, list) else []) if p]


def _app_folder(name: Any) -> bool:
    return isinstance(name, str) and bool(name) and not name.startswith(("/", "~")) and ".." not in name.split("/")


def ok_glob(g: Any) -> bool:
    """A directory a role may be given by the ownership file: a relative pattern, never the tests or everything."""
    return (isinstance(g, str) and 0 < len(g) <= 120 and not g.startswith(("/", ".git", "tests/", "~")) and ".." not in g
            and g.strip("*/") != "")


def ownership_problem(path: Path, dynamic: list[str]) -> str | None:
    """What is wrong with the ownership file the team reads its directories from (None: it can be used)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return "文件不存在"
    except (OSError, ValueError) as exc:
        return f"读不了或不是 JSON：{exc}"[:200]
    roles = data.get("roles") if isinstance(data, dict) else None
    if not isinstance(roles, dict):
        return "缺少 roles（角色 key → 可写目录列表）"
    bad = [f"{k}: {g}" for k, gs in roles.items() for g in (gs if isinstance(gs, list) else [gs]) if not ok_glob(g)]
    if bad:
        return "这些目录不能分给开发角色（不能是 tests/、整个仓库或含 ..）：" + "；".join(bad[:6])
    unknown = [k for k in roles if k not in dynamic]
    if unknown:
        return f"这些角色不归分工文件管：{'、'.join(unknown)}（可分的角色：{'、'.join(dynamic)}）"
    if not any(roles.get(k) for k in dynamic):
        return "一个角色都没分到目录"
    areas = data.get("test_areas", {})
    if not isinstance(areas, dict) or any(not re.fullmatch(r"[a-z0-9]{2,16}", str(a)) or r not in roles or not roles.get(r)
                                          for a, r in areas.items()):
        return "test_areas 要写成 区域名 → 分到了目录的角色 key（区域名只用小写字母和数字）"
    return None


def clean_risk(raw: Any) -> dict[str, Any] | None:
    """拦下的风险: what a person sent back at a gate kept from going live, as they write it: ``{what, amount}`` with the
    amount in yuan (or none). Nothing usable (no words and no amount): None."""
    if not isinstance(raw, dict):
        return None
    what = " ".join(str(raw.get("what") or "").split())[:60]
    amount = raw.get("amount")
    try:
        amount = round(float(amount), 2) if amount not in (None, "") else None
    except (TypeError, ValueError):
        amount = None
    if amount is not None and not (0 < amount < 1e12):
        amount = None
    if not what and amount is None:
        return None
    return {"what": what or "未写明", "amount": amount}


def money(amount: float | None) -> str:
    """¥20.6 万 · ¥8,000 · '' (no amount)."""
    if amount is None:
        return ""
    return f"¥{amount / 1e4:,.1f} 万" if amount >= 1e4 else f"¥{amount:,.0f}"


def review_targets(text: str, roles: list[dict[str, Any]]) -> list[str]:
    """The writing roles a 要改 review sends back, in team order: its ``打回：`` lines (one per role is fine), else every
    归X it names."""
    writers = [r["key"] for r in roles if r.get("writable")]
    names = {**_ROLE_ALIASES, **{r["title"]: r["key"] for r in roles}, **{k: k for k in writers}}
    lines = _BOUNCE_LINE_RE.findall(text or "")
    chunks = lines or _OWNER_RE.findall(text or "")
    found = {names.get(tok.strip(" `*_（）()")) for chunk in chunks for tok in re.split(r"[、,，/和及与\s]+", chunk)}
    found |= {r["key"] for r in roles if r.get("writable") and any(r["title"] in chunk for chunk in chunks)}
    return [k for k in writers if k in found]




def parse_done(text: str) -> str | None:
    """The agent's last ``DONE: …`` line."""
    found = _DONE_RE.findall(text or "")
    summary = found[-1].strip().strip("*_`").strip() if found else ""
    return summary[:200] or None


def gist(text: str) -> str | None:
    """No ``DONE:`` line: the first line of its last message that reads like a sentence (markdown stripped)."""
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith(("```", "|", "---")):
            continue
        line = line.lstrip("#>*-+ ").replace("**", "").replace("`", "").strip()
        if len(line) >= 4:
            return line[:120] + ("…" if len(line) > 120 else "")
    return None






def title_of(requirement: str, template: Path) -> str:
    """The first line of the requirement, else the template README's title."""
    for line in (requirement or "").splitlines():
        if line.strip().lstrip("#").strip():
            return line.strip().lstrip("#").strip()[:40]
    try:
        heads = [ln[2:].strip() for ln in (template / "README.md").read_text(encoding="utf-8").splitlines() if ln.startswith("# ")]
    except OSError:
        heads = []
    return (heads[0] if heads else "未命名的运行")[:40]


def new_rid(taken: Any) -> str:
    while True:
        rid = "r" + time.strftime("%m%d") + secrets.token_hex(2)
        if rid not in taken:
            return rid


def _lane() -> dict[str, Any]:
    return {"status": "waiting", "attempt": 0, "attempts": [], "conv": None, "worktree": None, "branch": None,
            "fork": None, "files": [], "file_count": 0, "lines": {"added": 0, "removed": 0}, "commits": [],
            "violations": [], "started_at": None, "done_at": None, "summary": None, "seen_commits": [],
            "tool_seen": "", "tool_at": 0.0}


def new_state(rid: str, requirement: str, team: dict[str, Any], task_template: str, work_root: Path, template: Path,
              now: float, source: Path | None = None) -> dict[str, Any]:
    root = Path(work_root) / "runs" / rid
    return {
        "version": 1, "id": rid, "title": title_of(requirement, Path(source) if source else template),
        "requirement": requirement or "", "source": str(source) if source else None,
        "status": "starting", "started_at": now, "ended_at": None, "repo": str(root / "repo"), "base": None,
        "branch": f"team/{rid}/run", "run_wt": str(root / "wt" / "_run"), "team": team, "task_template": task_template,
        "seq": 0, "needs_test": False, "lanes": {r["key"]: _lane() for r in team["roles"]}, "merges": [], "standards": [],
        "tests": {"at": None, "head": None, "command": " ".join(team.get("test_command") or []), "cases": [],
                  "passed": 0, "failed": 0, "total": 0, "history": []},
    }


def live_status(kind: str, f: dict[str, Any]) -> str:
    """A live attempt's lane status from KiroCrew's view of its agent."""
    if f["queued"]:
        return "queued"
    if f["awaiting"]:
        return "awaiting_approval"
    if f["stalled"]:
        return "stalled"
    return "running" if kind in ("work", "discuss") else "fixing"


def _name(path: str) -> str:
    return path.rstrip("/").rsplit("/", 1)[-1] + ("/" if path.endswith("/") else "")


def paused_from(events: Any) -> float:
    """Seconds a run spent ended before a 重试 picked it up again, from its ``run`` events (runs from before
    ``paused_s`` was kept)."""
    paused, ended = 0.0, None
    for e in events:
        if e.get("kind") != "run":
            continue
        text = str(e.get("text") or "")
        if text.startswith("重试"):
            if ended is not None:
                paused += max(0.0, float(e.get("at") or 0) - ended)
                ended = None
        elif not text.startswith("运行开始"):
            ended = float(e.get("at") or 0)
    return round(paused, 1)


class _Keep(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


class TeamRun:
    def __init__(self, state: dict[str, Any], deps: Deps, events: Any = ()) -> None:
        self.s, self.d = state, deps
        self.rid, self.parent = state["id"], f"{APP_NAME}:{state['id']}"  # the parent session key of its agents
        self.team = state["team"]
        self.roles = {r["key"]: r for r in self.team["roles"]}
        self.order = [r["key"] for r in self.team["roles"]]
        self.events: deque[dict[str, Any]] = deque(events, maxlen=EVENTS_KEPT)
        if "paused_s" not in state:
            state["paused_s"] = paused_from(self.events)
        self._unsaved: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()
        self._save_lock = asyncio.Lock()
        self._head: str | None = None  # the run branch head, known within one tick
        self.errors = 0

    @property
    def impl(self) -> list[str]:
        """The roles that make the tests pass (they get bounced); the ownership file may name them during the run."""
        owners = {o.get("role") for o in self.team.get("test_owners", [])}
        return [k for k in self.order if k in owners and self.lane(k)["status"] != "skipped"]

    @property
    def test_writers(self) -> list[str]:
        return [k for k in self.order if any(g.startswith("tests/") for g in self.roles[k]["writable"])]

    @property
    def ended(self) -> bool:
        return self.s["status"] in ENDED

    def lane(self, key: str) -> dict[str, Any]:
        return self.s["lanes"][key]

    def title(self, key: str) -> str:
        return self.roles[key]["title"]

    def max_attempts(self, key: str | None = None) -> int:
        """Rounds a role may take; every manual retry of it allows one more."""
        extra = int(self.lane(key).get("extra") or 0) if key else 0
        if key:  # a 讨论 at its gate is not a fix: it does not count against them
            extra += sum(a.get("kind") == "discuss" for a in self.lane(key)["attempts"])
        return 1 + int(self.team.get("defaults", {}).get("max_fix_rounds", 2)) + extra

    def emit(self, kind: str, text: str, role: str | None = None, frm: str | None = None, to: str | None = None,
             data: dict[str, Any] | None = None) -> None:
        self.s["seq"] = int(self.s.get("seq") or 0) + 1
        ev = {"seq": self.s["seq"], "at": self.d.now(), "kind": kind, "role": role, "text": " ".join(text.split())[:200],
              "from": frm, "to": to, "data": data or None}
        self.events.append(ev)
        self._unsaved.append(ev)

    async def save(self) -> None:
        async with self._save_lock:
            text = json.dumps(self.s, ensure_ascii=False)
            events, self._unsaved = self._unsaved, []
            try:
                await asyncio.to_thread(self.d.store.write, self.rid, text, [json.dumps(e, ensure_ascii=False) + "\n" for e in events])
            except BaseException:
                self._unsaved[:0] = events
                raise

    # --- the tick ------------------------------------------------------------------------------------------- #

    async def tick(self) -> None:
        if self.ended or self._lock.locked():
            return
        async with self._lock:
            try:
                await self._advance()
                self.errors = 0
            except Exception as exc:
                self.errors += 1
                if self.errors >= ERRORS_TO_FAIL:
                    await self.stop(status="failed", text=f"运行出错，停下了：{exc}")
                raise
            finally:
                await self.save()

    async def run_head(self) -> str:
        if self._head is None:
            self._head = await gitwork.head(Path(self.s["run_wt"]))
        return self._head

    async def _advance(self) -> None:
        self._head = None
        if self.s["base"] is None:
            await self._setup()
        mgr = self.d.manager()
        await self._resolve_ownership()
        for key in self.order:
            if self.ended:
                return
            await self._step(key, mgr)
        if self.s["needs_test"] and not self.ended:
            await self._test_and_bounce(mgr)
        if not self.ended:
            self._settle()

    async def _setup(self) -> None:
        s = self.s
        try:
            source = s.get("source")
            starter = self.team.get("starter")  # a folder of the app (starters/<name>/): the company template
            template = Path(source) if source else APP_ROOT / starter if starter else self.d.template
            packs = [APP_ROOT / p for p in spec_packs(self.team)]  # laid into the repo where missing
            base = await gitwork.create_repo(template, Path(s["repo"]), s["requirement"], s["title"],
                                             existing=bool(source), overlay=packs or None,
                                             keep_title=bool(starter and not source))
            await gitwork.add_worktree(Path(s["repo"]), Path(s["run_wt"]), s["branch"], base)
        except Exception as exc:  # noqa: BLE001
            self._end("failed", f"运行失败：建仓库出错：{exc}")
            return
        s["base"], s["status"] = base, "running"

    async def _step(self, key: str, mgr: Any) -> None:
        lane = self.lane(key)
        if lane["status"] == "waiting":
            if self._ready(key):
                missing = self._member_missing(key)
                if missing:  # held until a person adds the member: once, not every tick
                    if lane.get("awaiting_member") != missing:
                        lane["awaiting_member"] = missing
                        self.emit("member", f"{self.title(key)}没开工：Crew「代理」里还没有成员 {missing}，加上就自动开工", role=key)
                    return
                if lane.get("awaiting_member"):
                    self.emit("member", f"成员 {lane['awaiting_member']} 加上了，{self.title(key)}开工", role=key)
                    lane["awaiting_member"] = None
                await self._start(key, "work", mgr)
            return
        if lane["status"] not in ACTIVE or not lane["attempts"] or mgr is None:
            return
        att = lane["attempts"][-1]
        if not att.get("agent"):
            await self._dispatch(key, att, mgr)
            return
        info = find_agent(mgr, att["agent"])
        if info is None:
            now = self.d.now()
            if now - att.setdefault("missing_since", now) >= LOST_GRACE_S:
                self._fail_lane(key, "KiroCrew 里找不到这个子 agent 了（KiroCrew 重启过？）")
            return
        att.pop("missing_since", None)
        f = agent_fields(info)
        if f["done"]:
            await self._finish(key, att, f)
        else:
            await self._refresh(key, att, f)

    def _settled(self, key: str) -> bool:
        """Done as a dependency: merged (and, behind a person's gate, approved) or skipped."""
        lane = self.lane(key)
        if not self.roles[key]["writable"]:  # a reviewer: done, it let the work through, and a person did (its gate)
            return lane["status"] == "skipped" or (lane["status"] == "done" and bool(lane.get("passed")) and (
                self.roles[key].get("gate") != "human" or lane.get("gate") == "approved"))
        return lane["status"] == "skipped" or (lane["status"] == "merged" and (
            self.roles[key].get("gate") != "human" or lane.get("gate") == "approved"))

    def _after(self, key: str) -> set[str]:
        """The roles that wait for *key*, directly or further down (a deployment after the review)."""
        out: set[str] = set()
        for k in self.order:
            if any(d == key or d in out for d in self.roles[k]["depends_on"]):
                out.add(k)
        return out

    def _before(self, key: str) -> set[str]:
        """The roles *key* waits for, directly or further up."""
        out: set[str] = set()
        todo = list(self.roles[key]["depends_on"])
        while todo:
            k = todo.pop()
            if k not in out:
                out.add(k)
                todo.extend(self.roles[k]["depends_on"])
        return out

    def _ready(self, key: str) -> bool:
        role = self.roles[key]
        if not all(self._settled(d) for d in role["depends_on"]):
            return False
        if role.get("writable_from") and not (self.s.get("ownership") or {}).get("roles"):
            return False  # its directories are not known yet
        if role.get("deploy") and (self.s["needs_test"] or int(self.s["tests"].get("failed") or 0)):
            return False  # nothing red or untested goes out: a red run ends saying why
        if role["writable"]:
            return True
        # Read-only (the reviewer): every writing role it depends on (directly or further up) is in, no gate waits for
        # a person, and the latest test run has settled: green, or nothing left to send back (a bounced role is fixing,
        # not merged). A role beside it (the tester, when the team says the review does not wait for it) goes on.
        before = self._before(key)
        return not self.s["needs_test"] and all(self._settled(k) for k in self.order
                                                if self.roles[k]["writable"] and k in before)

    async def _start(self, key: str, kind: str, mgr: Any, *, failing: list[dict[str, Any]] | None = None,
                     conflicts: list[str] | None = None, review: str = "") -> None:
        """A new attempt: ``work`` (the role's first, or a retry of it), ``fix`` (failing tests), ``conflict`` (its
        merge) or ``review`` (what a 要改 review found in its area)."""
        s, lane, role, now = self.s, self.lane(key), self.roles[key], self.d.now()
        again = kind == "work" and bool(lane["attempts"]) and bool(lane.get("worktree"))  # a retry: its worktree stays
        if again and not role["writable"]:  # read-only: it looks at what is merged now, in its own snapshot
            run_head = await self.run_head()
            await gitwork.reset_clean(Path(lane["worktree"]))
            await gitwork.git(Path(lane["worktree"]), "reset", "-q", "--hard", run_head)
            lane["fork"] = run_head
        if kind == "work" and not again:
            run_wt = Path(s["run_wt"])
            run_head = await self.run_head()
            if role["writable"]:
                wt, branch = Path(s["repo"]).parent / "wt" / key, f"team/{self.rid}/{key}"
                if await gitwork.add_worktree(Path(s["repo"]), wt, branch, run_head):
                    fork = run_head
                else:  # made before a restart: where it branched off
                    fork = await gitwork.merge_base(run_wt, branch, "HEAD")
                lane.update(worktree=str(wt), branch=branch, fork=fork, base_fork=fork)
            else:  # read-only (a reviewer): a snapshot of the run branch of its own, so merges that go on meanwhile (a
                # tester beside it) neither change what it reads nor count as its writes
                await gitwork.reset_clean(run_wt)
                wt, branch = Path(s["repo"]).parent / "wt" / key, f"team/{self.rid}/{key}"
                if not await gitwork.add_worktree(Path(s["repo"]), wt, branch, run_head):
                    await gitwork.git(wt, "reset", "-q", "--hard", run_head)
                lane.update(worktree=str(wt), branch=branch, fork=run_head, base_fork=run_head)
            lane["started_at"] = now
            for dep in role["depends_on"]:
                outs = "、".join(_name(p) for p in self.roles[dep]["outputs"]) or "产出"
                self.emit("handoff", f"{self.title(dep)}把 {outs} 交给{self.title(key)}", role=key, frm=dep, to=key,
                          data={"carry": outs})
        n = len(lane["attempts"]) + 1
        if kind == "fix":
            names = "、".join(c["ac"] or c["name"] for c in failing[:6]) + ("等" if len(failing) > 6 else "")
            caught_up = await self._catch_up(key)
            task, label = self._fix_task(key, n, failing, caught_up, said=review), f"修 {names}"
        elif kind == "conflict":
            task, label = self._conflict_task(key, n, conflicts or []), "解决合入冲突"
        elif kind == "review":
            caught_up = await self._catch_up(key)
            task, label = self._review_task(key, n, review, caught_up), "按评审意见改"
        elif kind == "revise":  # never merged yet (a wrong ownership file): it redoes its own branch as it is
            caught_up = await self._catch_up(key) if lane.get("merged_sha") else False
            task, label = self._revise_task(key, n, review, caught_up), "按意见重写"
        elif kind == "discuss":  # a person at its gate talks with it: it answers, and changes its documents if it has to
            caught_up = await self._catch_up(key) if role["writable"] and lane.get("merged_sha") else False
            task, label = self._discuss_task(key, n, review, caught_up), "讨论"
        else:
            task, label = self._work_task(key, n), ("重新开工" if n > 1 else "")
        lane["attempts"].append({"n": n, "kind": kind, "label": label, "agent": None, "conv": None, "task": task,
                                 "requested_at": now, "started": None, "ended": None, "error": None, "summary": None,
                                 "credits": None, "tries": 0})
        lane.update(attempt=n, status="queued" if kind in ("work", "discuss") else "fixing", done_at=None)
        await self.save()  # the intent is on disk before anything starts
        await self._dispatch(key, lane["attempts"][-1], mgr)

    async def _dispatch(self, key: str, att: dict[str, Any], mgr: Any) -> None:
        if self.ended:
            return
        known = {i for k in self.order for a in self.lane(k)["attempts"] for i in [a.get("agent"), *a.get("dead", [])]} - {None}
        info = find_by_tag(mgr, self.parent, self._matcher(key, att["n"]))
        if info is None or getattr(info, "id", None) in known:
            try:
                info = await self._launch(key, att, mgr)
            except Exception as exc:  # noqa: BLE001
                info = find_by_tag(mgr, self.parent, self._matcher(key, att["n"]))  # it may have started anyway
                if info is None or getattr(info, "id", None) in known:
                    self._fail_lane(key, f"派活出错：{type(exc).__name__}: {exc}")
                    return
            if self.ended:  # stopped while a continuation was being started
                if info is not None and not getattr(info, "done", False):
                    await cancel(mgr, info.id)
                return
            if info is None:
                self._fail_lane(key, "Kiro Crew 没有开出这个角色的会话")
                return
        f = agent_fields(info)
        if f["done"] and f["outcome"] != "completed":
            att["agent"] = f["id"] or None
            self._fail_lane(key, f"KiroCrew 没有接这个活：{f['error'] or '已停止'}")
            return
        conv = f["id"]  # the session a fix round continues
        att.update(agent=f["id"], conv=conv, error=None, queued_reason=f["queued_reason"])
        self.lane(key).update(conv=conv, status=live_status(att["kind"], f))
        task = self.assignment(key) if self.roles[key].get("assignment") or self.s.get("plan") else ""
        label = ((f"编排器派活：{self.title(key)} · {task}" if task else f"{self.title(key)}开工") if att["kind"] == "work" and att["n"] == 1
                 else f"{self.title(key)}第 {att['n']} 轮：{att['label']}")
        if att.get("again"):
            label += f"（{att.pop('again')}）"
        self.emit("spawned", label, role=key)
        await self.save()

    async def _launch(self, key: str, att: dict[str, Any], mgr: Any) -> Any | None:
        """A fix round continues the role's own session (it keeps its context); else a new session in the run's folder,
        booted as the role's Crew member: a person can open it, read every step, type into it."""
        lane, role, defaults = self.lane(key), self.roles[key], self.team.get("defaults", {})
        model = role.get("model") or defaults.get("model")
        att["via"] = "fresh"
        if att["kind"] != "work" and lane.get("conv"):
            att["via"] = "continue"
            try:
                info = await mgr.continue_conversation_async(lane["conv"], att["task"], parent_session_key=self.parent,
                                                             cwd=lane["worktree"], model=model or None)
                why = str(getattr(info, "error", "") or "") if info is not None else "not supported"
            except Exception as exc:  # noqa: BLE001
                info, why = None, f"{type(exc).__name__}: {exc}"
            if info is not None and not (getattr(info, "done", False) and why):
                return info
            self.d.log.info("aidlc-team: %s/%s cannot continue its session (%s): a new one takes over",
                            self.rid, key, why[:160])
            att["via"] = "fresh"
            if self.ended:
                return None
        task = att["task"] if att["kind"] == "work" else self._with_context(key, att["task"])
        return mgr.spawn_session(task, parent_session_key=self.parent, cwd=lane["worktree"], model=model,
                                 title=f"{self.title(key)} agent", folder=f"{self.s['title'][:24]} · {self.rid}",
                                 agent=role.get("member") or "")

    async def _refresh(self, key: str, att: dict[str, Any], f: dict[str, Any]) -> None:
        lane, now = self.lane(key), self.d.now()
        lane["status"] = live_status(att["kind"], f)
        if f["queued"]:
            return
        if att.get("started") is None:
            att["started"] = f["started"] or now
        tool = short(self.d.scrub(f["last_tool"]))
        if tool and tool != lane.get("tool_seen") and now - float(lane.get("tool_at") or 0) >= TOOL_EVENT_GAP_S:
            lane["tool_seen"], lane["tool_at"] = tool, now
            self.emit("tool", f"{self.title(key)}：{tool}", role=key)
        # The worktree only changes through the agent's tool calls: look again after new ones (or now and then).
        since = now - float(lane.get("stats_at") or 0)
        if since >= STATS_EVERY_S or (since >= STATS_GAP_S and f["tool_count"] != lane.get("stats_tools")):
            lane["stats_tools"], lane["stats_at"] = f["tool_count"], now
            await self._stats(key)

    async def _catch_up(self, key: str) -> bool:
        """Before a fix round: its branch (merged already) fast-forwards to the run branch, so the failing tests and
        everyone else's code are in its worktree. What it changed so far is kept for the board; this round counts
        from here."""
        lane = self.lane(key)
        wt = Path(lane["worktree"])
        if not await gitwork.fast_forward(wt, self.s["branch"]):
            self.d.log.info("aidlc-team: %s/%s cannot fast-forward to the run branch", self.rid, key)
            return False
        head = await gitwork.head(wt)
        lane["prior"] = {"files": lane["files"], "lines": lane["lines"], "commits": lane["commits"],
                         "file_count": lane.get("file_count", len(lane["files"]))}
        lane.update(fork=head, merged_sha=head)
        return True

    async def _stats(self, key: str) -> None:
        lane = self.lane(key)
        if not lane.get("worktree") or not lane.get("fork"):
            return
        st = await gitwork.stats(Path(lane["worktree"]), lane["fork"])
        files, count, lines, commits = st["files"], st["count"], st["lines"], st["commits"]
        prior = lane.get("prior")
        if prior:  # earlier rounds, already merged, plus this one
            by = {f["path"]: dict(f) for f in prior["files"]}
            for f in st["files"]:
                old = by.get(f["path"])
                if old is None:
                    by[f["path"]] = dict(f)
                else:
                    old.update(added=old["added"] + f["added"], removed=old["removed"] + f["removed"],
                               status="A" if old["status"] == "A" else f["status"])
            files = sorted(by.values(), key=lambda f: (-(f["added"] + f["removed"]), f["path"]))[:12]
            count = prior["file_count"] + sum(f["path"] not in {p["path"] for p in prior["files"]} for f in st["files"])
            lines = {k: prior["lines"][k] + st["lines"][k] for k in ("added", "removed")}
            shas = {c["sha"] for c in prior["commits"]}
            commits = (prior["commits"] + [c for c in st["commits"] if c["sha"] not in shas])[-8:]
        lane.update(files=files, file_count=count, lines=lines, commits=commits)
        seen = lane.setdefault("seen_commits", [])
        for c in commits:
            if c["sha"] not in seen:
                seen.append(c["sha"])
                self.emit("committed", f"{self.title(key)}提交：{c['subject']}", role=key)
        del seen[:-50]
        self._violations(key, st["paths"])

    def _violations(self, key: str, paths: list[str]) -> None:
        lane, globs = self.lane(key), self.roles[key]["writable"]
        for p in paths:
            if gitwork.is_host_path(p) or p in lane["violations"] or gitwork.matches(p, globs) or len(lane["violations"]) >= 50:
                continue
            lane["violations"].append(p)
            if len(lane["violations"]) <= 12:
                self.emit("violation", f"{self.title(key)}改了不属于它的 {p}", role=key)

    async def _finish(self, key: str, att: dict[str, Any], f: dict[str, Any]) -> None:
        lane, now = self.lane(key), self.d.now()
        att["ended"] = now
        att["started"] = att.get("started") or f["started"] or att["requested_at"]
        att["summary"] = parse_done(f["result"]) or parse_done(f["text"]) or gist(f["result"] or f["text"])
        mgr = self.d.manager()
        recent = list(mgr.recent(f["id"])) if mgr is not None else []
        tail = (f["text"] or f["result"]).strip()
        att["snap"] = {"turns": f["turns"], "tool_count": f["tool_count"], "last_tool": short(self.d.scrub(f["last_tool"])),
                       "last_activity": f["last_activity"], "recent_tools": recent, "text_tail": tail[-300:] or None}
        att["reply"] = self.d.scrub(f["result"] or f["text"])[:REPLY_KEEP]
        att["calls"] = list(mgr.history(f["id"])) if mgr is not None else []
        att["credits"] = await self._credits(att)
        if (f["outcome"] == "failed" and not self.ended and not att.get("fresh_retry")
                and TRANSIENT_ERROR.search(str(f["error"] or ""))):
            # the model backend kept failing in that session (it was told to carry on already): once more in a new one,
            # with the worktree as it was left
            att["fresh_retry"] = True
            await self._again(key, att, "模型后端出错，换一个新会话接着做")
            return
        if f["outcome"] != "completed" and att["kind"] == "discuss" and not self.ended:
            # the answer did not come: the gate is open again as it was, the person can ask once more or decide
            self.lane(key).update(status="merged" if self.roles[key]["writable"] else "done", done_at=now)
            self._discussed(key, att, failed=f["error"] or "被停止了")
            return
        if f["outcome"] != "completed":
            # A failed fix round leaves the role's merged work in place, and the run goes on without it.
            self._fail_lane(key, f["error"] or "被停止了", keep_merged=att["kind"] == "fix")
            return
        if att["summary"]:
            lane["summary"] = att["summary"]
        self.emit("done", f"{self.title(key)}完成" + (f"：{att['summary']}" if att["summary"] else ""), role=key)
        if self.roles[key]["writable"]:
            await self._integrate(key)
        elif att["kind"] == "discuss":  # a reviewer answered the person: its verdict stands, the gate is open again
            lane.update(status="done", done_at=now)
            self._discussed(key, att)
        else:
            await self._review_done(key, att)

    async def _again(self, key: str, att: dict[str, Any], why: str) -> None:
        """The same attempt once more, in a new agent (the old one is remembered, so it is never adopted again)."""
        att.setdefault("dead", []).append(att["agent"])
        att.update(agent=None, conv=None, started=None, ended=None, error=None, tries=0, snap=None, reply=None, calls=None,
                   again=why)
        self.lane(key)["status"] = "queued" if att["kind"] in ("work", "discuss") else "fixing"
        await self.save()
        await self._dispatch(key, att, self.d.manager())

    def _resume(self) -> None:
        """An ended run carries on; the time it spent ended is not working time: the wall clock leaves it out."""
        gap = max(0.0, self.d.now() - float(self.s.get("ended_at") or self.d.now()))
        self.s.update(status="running", ended_at=None, paused_s=round(float(self.s.get("paused_s") or 0) + gap, 1))
        self.errors = 0

    async def retry(self, keys: list[str] | None = None, note: str = "") -> list[str]:
        """The person's 重试: every failed role (or the given ones) gets one more round, and an ended run carries on.
        A role whose work never got merged starts over in its own worktree (what it left there stays); a role that
        failed later is sent back with what is failing now, or its merge is tried again."""
        async with self._lock:
            failed = [k for k in self.order if self.lane(k)["status"] == "failed"]
            if not keys and not failed and self.ended:  # it ended on a 要改 review: the person sends that back
                rev = next((k for k in self.order if not self.roles[k]["writable"] and self.lane(k)["status"] == "done"), None)
                last = self.lane(rev)["attempts"][-1] if rev and self.lane(rev)["attempts"] else {}
                review = last.get("reply") or ""
                if (last.get("summary") or "").startswith("要改") and review_targets(review, self.team["roles"]):
                    self._resume()
                    if note:  # the person's decisions on what the review left to them
                        self.s["review_note"] = note
                    self.emit("run", "重试：按评审意见改" + ("，附人的决定" if note else ""))
                    picked = await self._review_bounce(rev, review)
                    self._settle()
                    await self.save()
                    return picked
            picked = [k for k in self.order if k in set(keys)] if keys else failed
            if not picked or any(k not in failed for k in picked):
                return []
            if self.ended:
                self._resume()
            self.emit("run", f"重试：{'、'.join(self.title(k) for k in picked)}")
            mgr = self.d.manager()
            for key in picked:
                lane = self.lane(key)
                lane["extra"] = int(lane.get("extra") or 0) + 1
                last = lane["attempts"][-1] if lane["attempts"] else None
                if last is not None and last["kind"] == "conflict":
                    await self._integrate(key)  # merge again: a conflict goes back to it, with the round it was given
                elif lane.get("merged_sha"):
                    t = self.s["tests"]
                    failing = [c for c in t["cases"] if c.get("owner") == key and c["status"] == "fail"]
                    lane.update(status="merged", stuck=False)
                    if failing:
                        await self._start(key, "fix", mgr, failing=failing)
                else:
                    lane.update(status="waiting" if not self._ready(key) else lane["status"])
                    if self._ready(key):
                        await self._start(key, "work", mgr)
            self._settle()
            await self.save()
            return picked

    async def _integrate(self, key: str) -> None:
        """Commit its leftovers, record what it changed, merge it into the run branch."""
        s, lane, role = self.s, self.lane(key), self.roles[key]
        wt = Path(lane["worktree"])
        paths, sha = await gitwork.commit_leftovers(wt, role["writable"], key)
        if paths:
            lane.setdefault("seen_commits", []).append(sha)
            self.emit("committed", f"app 替{self.title(key)}提交了 {len(paths)} 个文件", role=key)
        _, committed = await asyncio.gather(self._stats(key), gitwork.committed_paths(wt, lane["fork"]))
        self._violations(key, committed)
        # what it changed outside its area and then put back (a stub to try its tests, a checkout that only touched line
        # endings) was seen live but is not part of its work: the badge keeps what it merges, and what earlier rounds did
        kept = set(committed) | set(lane.get("merged_violations") or [])
        lane["violations"] = [v for v in lane["violations"] if v in kept]
        lane["merged_violations"] = list(lane["violations"])
        head, att = await gitwork.head(wt), lane["attempts"][-1]
        if att["kind"] == "discuss" and head == lane.get("merged_sha"):  # it only answered: the gate is open again
            lane.update(status="merged", done_at=self.d.now())
            self._discussed(key, att)
            return
        if att["kind"] != "work" and head == lane.get("merged_sha"):
            # Nothing new since its last merge: sending the same failures back again would only spend credits.
            lane.update(status="merged", done_at=self.d.now(), stuck=True)
            self.emit("failed", f"{self.title(key)}第 {lane['attempt']} 轮没有改动：{att.get('summary') or '没说原因'}", role=key)
            self.s["needs_test"] = True  # same head, so no new test run: only who to send the failures to is looked at again
            return
        own = self.team.get("ownership")
        if own and own.get("from") == key and lane["attempt"] < self.max_attempts(key):
            err = ownership_problem(wt / own["file"], [k for k in self.order if self.roles[k].get("writable_from")])
            if err:  # the team cannot be dispatched from a wrong ownership file: it goes back before it is merged
                self.emit("bounce", f"分工文件不对，退回{self.title(key)}：{err}", role=key, frm="run", to=key)
                await self._start(key, "revise", self.d.manager(), review=f"你写的分工文件 `{own['file']}` 用不了：{err}。"
                                  "按任务说明里的格式改好它（只改这个文件也行），再提交。")
                return
        res = await gitwork.merge(Path(s["run_wt"]), lane["branch"], f"[run] 合入{self.title(key)}（第 {lane['attempt']} 轮）")
        self._head = None
        now = self.d.now()
        sha = lane["commits"][-1]["sha"] if lane["commits"] else lane["fork"][:7]
        s["merges"].append({"role": key, "sha": sha, "at": now, "status": "merged" if res["ok"] else "conflict",
                            "files": lane.get("file_count", 0), "note": res["note"]})
        if res["ok"]:
            lane.update(status="merged", done_at=now, merged_sha=head)
            if key in self.test_writers and att["kind"] == "fix":
                for k in self.impl:  # the tests changed: an implementer that gave up on the old ones may be sent back
                    self.lane(k)["stuck"] = False
            self.emit("merged", f"{self.title(key)}的分支合入运行分支", role=key, frm=key, to="run")
            if own and own.get("from") == key:
                await self._resolve_ownership()  # before any role it dispatches is looked at in this same tick
            if role.get("deploy") and self.d.deploy is not None:
                await self._deploy(key, role["deploy"])
                if lane["status"] != "merged":
                    return  # sent back or failed
            if role.get("gate") == "human" and lane.get("gate") != "approved":
                if role.get("plan"):
                    self._read_plan(key, role["plan"])
                if role.get("delivery"):
                    self._read_delivery(key, role["delivery"])
                if role.get("questions"):
                    self._read_questions(key, role["questions"])
                if att["kind"] == "discuss":  # it answered and changed its documents: the person looks again
                    self._discussed(key, att, changed=True)
                else:
                    lane["gate"] = "pending"
                    self.emit("gate", f"等人批准：{role.get('gate_label') or self.title(key)}", role=key, frm=key, to="person")
            if key in self.impl or key in self.test_writers or any(self.lane(k)["status"] == "merged" for k in self.impl):
                s["needs_test"] = True
            return
        self.emit("conflict", f"{self.title(key)}合入冲突：{res['note']}", role=key, frm=key, to="run",
                  data={"paths": [p for p in str(res.get("note") or "").replace("、", ",").split(",") if p.strip()][:12]})
        if lane["attempt"] >= self.max_attempts(key):
            self._fail_lane(key, f"合入冲突，修改的轮数用完了：{res['note']}")
            return
        self.emit("bounce", f"合入冲突，打回{self.title(key)}", role=key, frm="run", to=key)
        await self._start(key, "conflict", self.d.manager(), conflicts=res["conflicts"] or [res["note"]])

    async def _test_and_bounce(self, mgr: Any) -> None:
        """The app's own test run on the run branch; failing cases go back to the role that owns them."""
        s, t = self.s, self.s["tests"]
        run_wt = Path(s["run_wt"])
        head = await self.run_head()
        if head != t.get("head"):  # this exact head was tested before a restart: its result stands
            try:
                wall = await self.d.run_tests(run_wt, self._tested_team())
            except checks.TestsUnavailable as exc:  # without tests nothing can be checked: stop spending credits
                await self.stop(status="failed", text=f"运行失败：app 跑不了测试：{exc}")
                return
            finally:
                await gitwork.reset_clean(run_wt)  # what the tests left behind must not get in a merge's way
            t.update({k: wall[k] for k in ("at", "cases", "passed", "failed", "total")}, head=head,
                     command=wall.get("command") or t.get("command", ""))
            t["history"] = (t.get("history", []) + [{"at": wall["at"], "passed": wall["passed"], "failed": wall["failed"]}])[-60:]
            note = ""
            if t["total"] and not t["failed"]:
                note = "：全绿"
            elif t["total"] and not t["passed"] and not any(self.lane(k)["status"] == "merged" for k in self.impl):
                note = "：实现还没写，全红"
            # every case's status rides along: a replay of the run turns the test wall cell by cell
            self.emit("tests", f"测试 {t['passed']}/{t['total']}{note}", data={"passed": t["passed"], "total": t["total"],
                      "cases": [[c["id"], c["status"]] for c in t["cases"]][:400]})
        s["needs_test"] = False
        # A test of one role often needs another's work: nobody is sent back until every implementing role is in.
        if not all(self.lane(k).get("merged_sha") or self.lane(k)["status"] == "failed" for k in self.impl):
            return
        for key in self.impl:
            lane = self.lane(key)
            failing = [c for c in t["cases"] if c.get("owner") == key and c["status"] == "fail"]
            if (lane["status"] != "merged" or lane.get("stuck") or not failing or lane["attempt"] >= self.max_attempts(key)
                    or self.ended):
                continue
            names = "、".join(c["ac"] or c["name"] for c in failing[:6]) + ("等" if len(failing) > 6 else "")
            self.emit("bounce", f"{names} 失败，打回{self.title(key)}", role=key, frm="tests", to=key,
                      data={"cases": [c["ac"] or c["name"] for c in failing][:24]})
            await self._start(key, "fix", mgr, failing=failing)
        await self._test_writer_bounce(mgr)

    async def _deploy(self, key: str, spec: dict[str, Any]) -> None:
        """部署执行: the deploy role wrote the configuration and checked it itself; the app starts the service the way it
        says and calls it healthy only when it answers. A failure goes back to the role, like a red test."""
        lane = self.lane(key)
        try:
            res = await self.d.deploy(self.rid, Path(self.s["run_wt"]), spec)  # type: ignore[misc]
        except Exception as exc:  # noqa: BLE001
            res = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        if res.get("ok"):
            lane["deployed"] = {"url": res["url"], "at": self.d.now()}
            note = f"；{res['note']}" if res.get("note") else ""
            text = f"部署到本机：{res['url']}（编排器按{self.title(key)}写的配置起的服务，健康检查通过{note}）"
            self.emit("deployed", text, role=key, data={"url": res["url"]})
            return
        why = str(res.get("error") or "没起来")[:300]
        if lane["attempt"] < self.max_attempts(key):
            self.emit("bounce", f"部署没成功，打回{self.title(key)}：{why}", role=key, frm="run", to=key)
            await self._start(key, "fix", self.d.manager(), failing=[{"name": "部署后的健康检查", "file": "deploy/local.json",
                                                                       "message": why, "ac": None}])
        else:
            self._fail_lane(key, f"部署没成功：{why}")

    def _gave_up(self, key: str) -> bool:
        """The implementing role will not fix more: its last round changed nothing, or it has no rounds left."""
        lane = self.lane(key)
        return lane["status"] == "merged" and (bool(lane.get("stuck")) or lane["attempt"] >= self.max_attempts(key))

    async def _test_writer_bounce(self, mgr: Any) -> None:
        """A failing test whose implementer gave up on it (「测试本身的问题」, or out of rounds) goes back to the role that
        wrote that test file, with what the implementer said: a wrong test is not the implementer's to fix."""
        t = self.s["tests"]
        for writer in self.test_writers:
            lane = self.lane(writer)
            if lane["status"] != "merged" or lane.get("stuck") or lane["attempt"] >= self.max_attempts(writer) or self.ended:
                continue
            globs = self.roles[writer]["writable"]
            failing = [c for c in t["cases"] if c["status"] == "fail" and gitwork.matches(c["file"], globs)
                       and c.get("owner") in self.impl and self._gave_up(c["owner"])]
            if not failing:
                continue
            owners = sorted({c["owner"] for c in failing}, key=self.order.index)
            said = "\n".join(f"- {self.title(o)}：{self.lane(o).get('summary') or self.lane(o)['attempts'][-1].get('summary') or '没说原因'}"
                              for o in owners)
            names = "、".join(c["ac"] or c["name"] for c in failing[:6]) + ("等" if len(failing) > 6 else "")
            self.emit("bounce", f"{names} 失败，{'、'.join(self.title(o) for o in owners)}说测试本身有问题，打回{self.title(writer)}",
                      role=writer, frm="tests", to=writer, data={"cases": [c["ac"] or c["name"] for c in failing][:24]})
            await self._start(writer, "fix", mgr, failing=failing, review=said)

    async def _review_done(self, key: str, att: dict[str, Any]) -> None:
        s, lane = self.s, self.lane(key)
        # whatever the reviewer wrote in its snapshot is a violation
        _, committed = await asyncio.gather(self._stats(key), gitwork.committed_paths(Path(lane["worktree"]), lane["fork"]))
        self._violations(key, committed)
        lane.update(status="done", done_at=self.d.now())
        summary = att.get("summary") or ""
        self.emit("review", f"审查：{summary or '没有给结论'}", role=key)
        if summary.startswith("要改"):
            rounds = int(s.get("review_rounds") or 0)
            limit = int(self.team.get("defaults", {}).get("max_review_rounds", 0) or 0)
            if rounds < limit and not self.ended and await self._review_bounce(key, att.get("reply") or ""):
                return
            if self.roles[key].get("gate") == "human" and not self.ended:
                # its rounds are used up (or it names nobody): the person at its gate decides, the run does not end here
                lane.update(gate="pending", overrule=True, passed=False)
                label = self.roles[key].get("gate_label") or self.title(key)
                s["verdict"] = f"审查打回 {rounds} 轮后仍要改" if rounds else "审查要改"
                self.emit("gate", f"等人决定{label}：{s['verdict']}，人可以再退回一轮，或写明理由推翻审查放行", role=key,
                          frm=key, to="person")
                return
            self._end("failed", f"运行结束：评审打回 {rounds} 轮后仍要改，交给人决定" if rounds else "运行结束：评审要改")
        else:
            lane["passed"] = True
            if self.roles[key].get("gate") == "human" and lane.get("gate") != "approved":
                lane["gate"] = "pending"  # a person signs this review off before anything after it starts
                label = self.roles[key].get("gate_label") or self.title(key)
                self.emit("gate", f"等人批准：{label}", role=key, frm=key, to="person")
            first = re.split(r"[。；;\n]", summary, maxsplit=1)[0].strip() if summary else ""
            s["verdict"] = f"审查说{first[:30]}" if first else "审查没有给结论"
            if lane.get("gate") == "pending" or any(self.lane(k)["status"] not in ("merged", "done", "skipped") for k in self._after(key)):
                return  # a person's gate, or a deployment after the review: _settle ends the run once they are done
            red = int(s["tests"].get("failed") or 0)
            if red:  # done, but not green: said as it is, the person decides
                self._end("done", f"运行结束：审查说{summary[:20] or '没有结论'}，但测试还有 {red} 项没过，交给人决定")
            else:
                self._end("done", "运行完成：审查说可以交付" if summary.startswith("可以交付") else "运行完成")

    async def _resolve_ownership(self) -> None:
        """Once the role that writes the ownership file is merged: every role whose directories come from it gets
        them, or is skipped (this project does not need it), and the test areas say whom a failure goes back to."""
        own, s = self.team.get("ownership"), self.s
        if not own or s.get("ownership") is not None or self.lane(own["from"])["status"] != "merged":
            return
        dynamic = [k for k in self.order if self.roles[k].get("writable_from")]
        path = Path(s["run_wt"]) / own["file"]
        err = ownership_problem(path, dynamic)
        if err:
            s["ownership"] = {"error": err}
            await self.stop(status="failed", text=f"运行失败：分工文件 {own['file']} 用不了：{err}")
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        now, assigned = self.d.now(), {}
        for k in dynamic:
            globs = [g for g in (data["roles"].get(k) or []) if ok_glob(g)]
            if globs:
                self.roles[k]["writable"] = assigned[k] = globs
            else:
                self.lane(k).update(status="skipped", done_at=now)
                self.emit("skipped", f"{self.title(k)}：这个项目用不到，跳过", role=k)
        areas = {str(a): r for a, r in (data.get("test_areas") or {}).items() if r in assigned}
        if areas:
            self.team["test_owners"] = [{"glob": f"tests/**/*-{a}-*", "role": r} for a, r in areas.items()]
        s["ownership"] = {"roles": assigned, "test_areas": areas}
        self.emit("ownership", f"编排器按{self.title(own['from'])}的分工派活：" + "；".join(
            f"{self.title(k)} {'、'.join(g)}" for k, g in assigned.items()), data={"roles": assigned})

    async def gate(self, key: str, decision: str, note: str = "", delivery: Any = None, answers: Any = None,
                   risk: Any = None) -> bool:
        """A person's answer at a gate: approve (the roles after it start), send it back with what to change, or 讨论
        (it answers, and changes its documents if it has to; the gate stays). *delivery*: the 交付标签 as the person
        confirms them when approving the gate of the role that proposes them (fields left out keep the proposal's).
        *answers*: the person's choice for each question the role put to them (``{id: {"choice": "A", "text": ""}}``;
        a question left out takes the role's recommendation). *risk*: with 退回, what the send-back kept from going live
        (``{what, amount}``, amount in yuan): kept on the run for 更稳 in the CTO view and on the 签字单."""
        async with self._lock:
            lane, role = self.lane(key), self.roles.get(key) or {}
            if self.ended or role.get("gate") != "human" or lane.get("gate") != "pending":
                return False
            label = role.get("gate_label") or self.title(key)
            if decision == "discuss":
                if not note.strip() or not self.discuss_allowed(key):
                    return False
                lane["gate"] = "discussing"
                self.s.setdefault("talks", {}).setdefault(key, []).append({"who": "person", "text": note.strip(), "at": self.d.now()})
                self.emit("talk", f"人在{label}关卡和{self.title(key)}讨论：{note}", role=key, frm="person", to=key)
                await self._start(key, "discuss", self.d.manager(), review=note.strip())
                self._settle()
                await self.save()
                return True
            if decision == "approve":
                if lane.get("overrule") and not note.strip():
                    return False  # overruling a review that still says 要改 takes a reason
                lane.update(gate="approved", gate_note=note or None)
                if note:
                    self.s.setdefault("gate_notes", {})[key] = note
                picked = self._answers_for(key, answers)
                if picked:
                    self.s.setdefault("answers", {})[key] = picked
                    note_text = note
                    note = (note + "；" if note else "") + "决定：" + "、".join(
                        f"{a['id']} 选 {a['choice'] if a['choice'] != 'other' else '其他'}" + ("（与建议不同）" if a["differs"] else "")
                        for a in picked)
                    lane["gate_note"] = note_text or None
                if lane.pop("overrule", None):
                    lane["passed"] = True
                    last = lane["attempts"][-1] if lane["attempts"] else {}
                    self.s["overruled"] = {"role": key, "note": note, "review": str(last.get("summary") or "")}
                    self.s["verdict"] = "人推翻了审查结论放行"
                    self.emit("approved", f"人推翻审查结论，批准了{label}：{note}", role=key, frm="person", to=key)
                else:
                    self.emit("approved", f"人批准了{label}" + (f"：{note}" if note else ""), role=key, frm="person", to=key)
                if role.get("delivery"):  # the person confirms the 交付标签 the role proposed (or changes them)
                    self.s["delivery"] = delivery_mod.clean(delivery, self.delivery())
                    self.emit("plan", f"人确认交付标签：{delivery_mod.label(self.s['delivery'])}", role=key,
                              data={"delivery": self.s["delivery"]})
                if role.get("plan"):  # the roles the approved proposal leaves out sit this run out
                    for k, why in (self.s.get("plan_skip") or {}).items():
                        if k in self.roles and self.lane(k)["status"] == "waiting":
                            self._sit_out(k, f"这次用不到：{why}", f"这次用不到（{self.title(key)}提议，人在{label}关卡批准）：{why}")
                if self.s.get("gate_notes") or self.s.get("answers"):
                    await self._record_decisions()
            elif not role["writable"] and lane.get("overrule") and (review_targets(note, self.team["roles"])
                                                                     or review_targets(self.overrule_review(key), self.team["roles"])):
                # the review still says 要改: one more round as it says, with what the person adds (the person's note wins)
                review = self.overrule_review(key)
                lane.update(gate=None, overrule=False)
                if note:
                    self.s["review_note"] = note
                caught = self._keep_risk(key, label, clean_risk(risk), note)
                self.emit("bounce", f"人在{label}关卡退回：按审查意见再改一轮" + (f"：{note}" if note else ""), role=key,
                          frm="person", to=key, data=caught)
                await self._review_bounce(key, review, only=review_targets(note, self.team["roles"]) or None)
            elif not role["writable"]:  # a review gate: the person sends work back to the members the note names
                targets = review_targets(note, self.team["roles"])
                if not targets:
                    return False  # 退回 has to say to whom (打回：前端开发 #2 …)
                lane.update(gate=None, passed=False)
                self.s["human_review"] = note
                caught = self._keep_risk(key, label, clean_risk(risk), note)
                self.emit("bounce", f"人在{label}关卡退回：{note}", role=key, frm="person", to=key, data=caught)
                lane["status"] = "waiting"
                mgr = self.d.manager()
                for t in targets:
                    self.emit("bounce", f"按人的意见打回{self.title(t)}", role=t, frm=key, to=t)
                    await self._start(t, "review", mgr, review=HUMAN_MARK + note)
            else:
                lane["gate"] = None
                caught = self._keep_risk(key, label, clean_risk(risk), note)
                self.emit("bounce", f"人退回了{label}：{note or '没写原因'}", role=key, frm="person", to=key, data=caught)
                await self._start(key, "revise", self.d.manager(), review=f"人在关卡上没有批准，意见：{note or '没写原因'}")
            self._settle()
            await self.save()
            return True

    def _keep_risk(self, key: str, label: str, risk: dict[str, Any] | None, note: str) -> dict[str, Any] | None:
        """A send-back's 拦下的风险 on the run (``risks``), with the gate and the moment; the event carries it too."""
        if risk is None:
            return None
        rec = {**risk, "role": key, "gate": str(label), "at": self.d.now(), "note": " ".join(note.split())[:200]}
        self.s.setdefault("risks", []).append(rec)
        return {"risk": {k: rec[k] for k in ("what", "amount", "gate")}}

    def _read_plan(self, key: str, rel: str) -> None:
        """分工提案: the gated role proposed who does what this time (``{member key: one line}``, a JSON file in the run
        branch). Lines for the team's own members are kept (40 characters at most) and become their assignments on
        the board and in their tasks once a person approves the gate; anything else is ignored. No file, or a wrong
        one: the team file's assignments stand."""
        path = Path(self.s["run_wt"]) / rel
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.emit("plan", f"{self.title(key)}没有提出分工（{rel}），按团队配置派活", role=key)
            return
        skip = data.get("skip") if isinstance(data, dict) else None
        drop = {k: " ".join(str(v).split())[:60] or "没写理由" for k, v in (skip.items() if isinstance(skip, dict) else [])
                if k in self.roles and self.roles[k].get("optional") and self.lane(k)["status"] == "waiting"}
        plan = {k: " ".join(str(v).split())[:40] for k, v in (data.items() if isinstance(data, dict) else [])
                if k in self.roles and k != key and k not in drop and isinstance(v, str) and v.strip()}
        self.s["plan"], self.s["plan_skip"] = plan, drop
        if plan or drop:
            self.emit("plan", f"{self.title(key)}提议分工：" + "；".join(f"{self.title(k)} · {v}" for k, v in plan.items())
                      + ("；这次不要：" + "、".join(f"{self.title(k)}（{v}）" for k, v in drop.items()) if drop else ""),
                      role=key, data={"plan": plan, "skip": drop})

    def _read_delivery(self, key: str, rel: str) -> None:
        """交付标签: the gated role's proposal (``{name, kind, size, line, why}``, a JSON file in the run branch), shown at
        its gate for the person to confirm. No file, or a wrong one: the team file's defaults stand."""
        try:
            data = json.loads((Path(self.s["run_wt"]) / rel).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        if not isinstance(data, dict):
            self.emit("plan", f"{self.title(key)}没有提出交付标签（{rel}），按团队配置：{delivery_mod.label(self.delivery())}", role=key)
            return
        self.s["delivery_proposed"] = delivery_mod.clean(data, self._delivery_defaults())
        self.emit("plan", f"{self.title(key)}提议交付标签：{delivery_mod.label(self.s['delivery_proposed'])}", role=key,
                  data={"delivery": self.s["delivery_proposed"]})

    def _read_questions(self, key: str, rel: str) -> None:
        """要人决定的: the gated role's questions for the person (``{"questions": [{id, q, options: [{key, text}], recommend,
        why}]}``, a JSON file in the run branch), each answered at its gate by picking an option (or writing another).
        No file, or a wrong one: none, the person writes what they decide in the note."""
        try:
            data = json.loads((Path(self.s["run_wt"]) / rel).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        rows = data.get("questions") if isinstance(data, dict) else data
        out: list[dict[str, Any]] = []
        for i, q in enumerate(rows if isinstance(rows, list) else []):
            if not isinstance(q, dict) or not str(q.get("q") or "").strip():
                continue
            opts = [{"key": str(o.get("key") or "").strip()[:2] or "ABCD"[j], "text": " ".join(str(o.get("text") or "").split())[:200]}
                    for j, o in enumerate(q.get("options") if isinstance(q.get("options"), list) else []) if isinstance(o, dict) and j < 4]
            opts = [o for o in opts if o["text"]]
            if len(opts) < 2:
                continue
            keys = [o["key"] for o in opts]
            rec = str(q.get("recommend") or "").strip()[:2]
            out.append({"id": " ".join(str(q.get("id") or i + 1).split())[:8], "q": " ".join(str(q["q"]).split())[:160],
                        "options": opts, "recommend": rec if rec in keys else "", "why": " ".join(str(q.get("why") or "").split())[:200]})
            if len(out) >= 10:
                break
        self.s.setdefault("questions", {})[key] = out
        if out:
            self.emit("plan", f"{self.title(key)}列出 {len(out)} 件要人决定的事", role=key, data={"questions": len(out)})

    def _answers_for(self, key: str, answers: Any) -> list[dict[str, Any]]:
        """The person's choices for the questions *key* put to them; one left out (or not one of its options) takes the
        recommendation, else the first option. ``other`` with words is the person's own answer."""
        given = answers if isinstance(answers, dict) else {}
        out = []
        for q in (self.s.get("questions") or {}).get(key) or []:
            a = given.get(q["id"]) if isinstance(given.get(q["id"]), dict) else {}
            keys = {o["key"]: o["text"] for o in q["options"]}
            choice, text = str(a.get("choice") or ""), " ".join(str(a.get("text") or "").split())[:300]
            if choice == "other" and not text:
                choice = ""
            if choice != "other" and choice not in keys:
                choice = q["recommend"] or q["options"][0]["key"]
            out.append({"id": q["id"], "q": q["q"], "choice": choice, "option": keys.get(choice, ""), "text": text,
                        "recommend": q["recommend"], "differs": bool(q["recommend"]) and choice != q["recommend"]})
        return out

    def discuss_allowed(self, key: str) -> bool:
        """讨论 at this role's gate: the team allows it, and the rounds for this gate are not used up."""
        d = self.team.get("defaults", {})
        if not d.get("gate_discuss"):
            return False
        said = sum(t["who"] == "person" for t in (self.s.get("talks") or {}).get(key) or [])
        return said < int(d.get("max_discuss_rounds", 5) or 5)

    def _discussed(self, key: str, att: dict[str, Any], failed: str = "", changed: bool = False) -> None:
        """The role answered the person (or could not): the answer is kept for the gate card, the gate is open again."""
        lane, role = self.lane(key), self.roles[key]
        label = role.get("gate_label") or self.title(key)
        said = (att.get("reply") or "").strip()  # its answer, without the DONE: line (that is the summary)
        reply = "\n".join(ln for ln in said.splitlines() if not ln.strip().startswith("DONE:")).strip() or att.get("summary") or ""
        text = f"（这一轮没有回答：{failed}）" if failed else (reply[:TALK_KEEP] or "（没有写回答）")
        self.s.setdefault("talks", {}).setdefault(key, []).append(
            {"who": "agent", "text": text, "summary": att.get("summary") or "", "at": self.d.now(), "changed": changed})
        lane["gate"] = "pending"
        self.emit("talk", f"{self.title(key)}" + (f"没有回答：{failed}" if failed else f"回答：{att.get('summary') or text[:80]}"),
                  role=key, frm=key, to="person")
        self.emit("gate", f"等人批准：{label}（讨论之后）", role=key, frm=key, to="person")

    async def _record_decisions(self) -> None:
        """What people said and decided at the gates so far, as a document in the run branch: the roles after them read
        it with the rest of the documents (their tasks say it too), and it stays with the delivered code."""
        lines = ["# 人在关卡上的决定", "", "由 app 记录：负责人在各关卡批准时写的意见和逐条做的决定，以此为准。", ""]
        notes, answers = self.s.get("gate_notes") or {}, self.s.get("answers") or {}
        for k in self.order:
            if k not in notes and k not in answers:
                continue
            lines += [f"## {self.roles[k].get('gate_label') or self.title(k)}关卡（{self.title(k)}）", ""]
            if notes.get(k):
                lines += ["意见：" + notes[k].strip(), ""]
            for a in answers.get(k) or []:
                pick = f"其他：{a['text']}" if a["choice"] == "other" else f"{a['choice']}. {a['option']}" + (f"（补充：{a['text']}）" if a["text"] else "")
                lines.append(f"- 决定 {a['id']}「{a['q']}」：{pick}" + ("（与建议不同）" if a["differs"] else ""))
            lines.append("")
        run_wt = Path(self.s["run_wt"])
        try:
            path = run_wt / DECISIONS_FILE
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
            await gitwork.git(run_wt, "add", "--", DECISIONS_FILE)
            await gitwork.git(run_wt, "commit", "-q", "-m", "[run] 人在关卡上的决定", "--", DECISIONS_FILE, ok=(0, 1))
            self._head = None
        except Exception as exc:  # noqa: BLE001  (the tasks say the same: the run goes on without the file)
            self.d.log.info("aidlc-team: %s cannot write %s: %s", self.rid, DECISIONS_FILE, exc)

    def _delivery_defaults(self) -> dict[str, Any]:
        return delivery_mod.defaults(self.team, self.s.get("title") or "", on_source=bool(self.s.get("source")),
                                     team_dir=APP_ROOT / "team")

    def delivery(self) -> dict[str, Any]:
        """The run's 交付标签: as a person confirmed them, else as proposed, else the team file's defaults."""
        got = self.s.get("delivery") or self.s.get("delivery_proposed")
        return delivery_mod.clean(got, self._delivery_defaults()) if isinstance(got, dict) else self._delivery_defaults()

    def issue(self) -> dict[str, Any]:
        """The run's Issue: the requirement as the organisation tracks it — its number, 需求 or 缺陷, who raised it and
        when. A run's record may carry its own (``issue``: an imported run brings its reporter); else they follow from
        its id and its 交付标签."""
        got = self.s.get("issue") if isinstance(self.s.get("issue"), dict) else {}
        d = self.delivery()
        return {"id": str(got.get("id") or delivery_mod.issue_id(self.rid)),
                "kind": str(got.get("kind") or ("缺陷" if d["kind"] == "修复" else "需求")),
                "reporter": str(got.get("reporter") or delivery_mod.REPORTERS[d["line"]]),
                "created_at": float(got.get("created_at") or self.s.get("started_at") or 0)}

    def pr(self) -> dict[str, Any] | None:
        """The run's pull request: its run branch into main. Open once the run delivered (finished, and deployed where its
        team deploys); merged when a person signs it off (签字放行) and main moved here; ``signed`` when they signed but it
        was not merged on this computer (an imported run: its repository is on the other one). None before it delivered."""
        s = self.s
        sig = s.get("signoff") if isinstance(s.get("signoff"), dict) else None
        if not sig and (not self.ended or s["status"] != "done" or self.sign_block()):
            return None
        lanes = [self.lane(k) for k in self.order]
        t = s["tests"]
        return {"number": delivery_mod.pr_number(self.rid), "head": str(s.get("branch") or f"team/{self.rid}/run"), "base": "main",
                "state": ("merged" if sig.get("merged") else "signed") if sig else "open", "opened_at": float(s.get("ended_at") or 0),
                "merged_at": float(sig["at"]) if sig else None, "merged_by": str(sig.get("by") or "") if sig else None,
                "sha": str(sig.get("merged") or "") if sig else "",
                "files": sum(int(ln.get("file_count") or len(ln.get("files") or [])) for ln in lanes),
                "added": sum(int((ln.get("lines") or {}).get("added") or 0) for ln in lanes),
                "removed": sum(int((ln.get("lines") or {}).get("removed") or 0) for ln in lanes),
                "checks": f"{t['passed']}/{t['total']}", "review": str(s.get("verdict") or "")}

    async def merge_pr(self) -> str:
        """签字放行合并 PR: the run branch goes into main of the run's repository (a fast-forward: main has not moved
        since the run branched off). Returns main's new commit, or "" when there is no repository here (a run imported
        from another computer) or main cannot move."""
        repo = Path(self.s["repo"])
        if not (repo / ".git").exists():
            return ""
        try:
            if (await gitwork.git(repo, "merge", "--ff-only", "-q", self.s["branch"], ok=None))[0] != 0:
                return ""
            return await gitwork.short_head(repo)
        except Exception:  # noqa: BLE001 - the signature stands; the PR then says it was not merged here
            self.d.log.warning("aidlc-team: %s cannot merge its PR into main", self.rid, exc_info=True)
            return ""

    def overrule_review(self, key: str) -> str:
        """The review a person is deciding over at its gate (it still says 要改 with its rounds used up), else ""."""
        lane = self.lane(key)
        return str(lane["attempts"][-1].get("reply") or "") if lane.get("overrule") and lane["attempts"] else ""

    def leave_out_unhired(self, members: set[str] | None) -> list[str]:
        """在职: an optional role whose Crew member is not on the team's 「代理」 page (*members*) when the run is handed
        over sits it out, like a post the company has not filled. *members* None (Crew not read) leaves everyone in;
        the other roles boot the template of their member's name when the member is not there (sessions.py)."""
        if members is None:
            return []
        out = [k for k in self.order if self.roles[k].get("optional") and self.roles[k].get("member")
               and self.roles[k]["member"] not in members and self.lane(k)["status"] == "waiting"]
        for k in out:
            self._sit_out(k, "未入职", f"Crew「代理」里还没有 {self.roles[k]['member']}（未入职），这次不参与")
        return out

    def _member_missing(self, key: str) -> str | None:
        """The Crew member a required role runs as, when the team's 「代理」 page does not have it: the role holds (its
        session would boot the template of that name instead, and nobody would know). None while the members are not
        read; an optional role is ``leave_out_unhired``'s, decided when the run is handed over."""
        role = self.roles[key]
        member = role.get("member")
        if not member or role.get("optional") or self.d.members is None:
            return None
        names = self.d.members(self.team.get("workspace"))
        return member if names is not None and member not in names else None

    def _sit_out(self, key: str, summary: str, why: str) -> None:
        """*key* takes no part in this run: skipped (a dependency that is done), and the checks only it owns are not run."""
        self.lane(key).update(status="skipped", done_at=self.d.now(), summary=summary)
        globs = [str(o["glob"]) for o in self.team.get("test_owners", []) if o.get("role") == key]
        self.emit("skipped", f"{self.title(key)}：{why}" + (f"；归它的检查（{'、'.join(globs)}）这次不跑" if globs else ""), role=key)

    def _tested_team(self) -> dict[str, Any]:
        """The team as the test run sees it: the test files owned by a role that sits this run out are left out."""
        out = [k for k in self.order if self.lane(k)["status"] == "skipped"]
        return {**self.team, "skip_owners": out} if out else self.team

    def sign_block(self) -> str:
        """Why this run cannot be signed off ("" when it can): 签字放行 is a person taking responsibility for what the
        team delivered, so a run that failed, was stopped, or has a deployment that never went out has nothing to sign."""
        s = self.s
        if not self.ended:
            return "运行结束以后才能签字"
        if s["status"] == "failed":
            return "运行失败了，没有交付，不能签字放行（可以重试失败的角色）"
        if s["status"] == "stopped":
            return "运行停下了，没有交付，不能签字放行"
        deployers = [k for k in self.order if self.roles[k].get("deploy") and self.lane(k)["status"] != "skipped"]
        if deployers and not any(self.lane(k).get("deployed") for k in deployers):
            red = int(s["tests"].get("failed") or 0)
            return "没有部署，不能签字放行" + (f"（测试还有 {red} 项没过）" if red else "")
        return ""

    def _planner(self) -> str:
        return next((self.title(k) for k in self.order if self.roles[k].get("plan")), "上游")

    def assignment(self, key: str) -> str:
        """What this member is assigned this run: the approved proposal's line, else the team file's."""
        role = self.roles[key]
        return str((self.s.get("plan") or {}).get(key) or role.get("assignment") or role.get("mission") or "")

    def _revise_task(self, key: str, n: int, why: str, caught_up: bool) -> str:
        lane = self.lane(key)
        lines = [self._tag(key, n), "", f"你是开发团队里的「{self.title(key)}」。你上一轮的产出要改：", "", why.strip()[:REVIEW_KEEP]]
        if caught_up:
            lines += ["", "app 已经把你的分支快进到运行分支的最新提交。"]
        lines += ["", f"在你的工作目录 {lane['worktree']}（分支 {lane['branch']}）里改。你只能改：{self._writable(key)}。"]
        return "\n".join(lines + self._closing(key))

    async def _review_bounce(self, key: str, review: str, only: list[str] | None = None) -> list[str]:
        """A 要改 review goes back to the roles it names (or *only*, those a person named); the reviewer looks again
        once their fixes are in."""
        targets = [k for k in (only or review_targets(review, self.team["roles"])) if self.lane(k).get("worktree")]
        if not targets:
            return []
        self.s["review_rounds"] = rnd = int(self.s.get("review_rounds") or 0) + 1
        self.lane(key)["status"] = "waiting"
        mgr = self.d.manager()
        for t in targets:
            self.emit("bounce", f"评审要改，打回{self.title(t)}（第 {rnd} 轮评审）", role=t, frm=key, to=t,
                      data={"review_round": rnd})
            await self._start(t, "review", mgr, review=review)
        return targets

    def _discuss_task(self, key: str, n: int, said: str, caught_up: bool) -> str:
        lane, role = self.lane(key), self.roles[key]
        label = role.get("gate_label") or self.title(key)
        lines = [self._tag(key, n), "", f"你是开发团队里的「{self.title(key)}」。你的产出停在「{label}」关卡等负责人批准，负责人想先和你讨论：",
                 "", said.strip()[:REVIEW_KEEP], "",
                 "先回答负责人：说清楚、短，有依据就写依据（文件、规范编号）。负责人还没批准，不要往下做别的角色的活。"]
        if role["writable"]:
            if caught_up:
                lines += ["", "app 已经把你的分支快进到运行分支的最新提交。"]
            lines += ["", f"讨论改变了你的产出时才改文件：在你的工作目录 {lane['worktree']}（分支 {lane['branch']}）里改，你只能改："
                      f"{self._writable(key)}；要人决定的事有变化，同步改问题文件。只是回答，就不改文件。",
                      "", "做完以后：", f"1. 改了文件就 `git add`、提交到 {lane['branch']}，提交说明以 `[{key}]` 开头；没改就不提交。",
                      "2. 最后一条回复的第一行写 `DONE: ` 加一句话总结，下面写给负责人的回答。", "3. 不要 push，不要动别的分支，不要改 git 配置。"]
        else:
            lines += ["", "你是只读的：不改任何文件，也不提交。", "",
                      "最后一条回复的第一行写 `DONE: ` 加一句话总结，下面写给负责人的回答。"]
        return "\n".join(lines)

    def _review_task(self, key: str, n: int, review: str, caught_up: bool) -> str:
        s, lane, title = self.s, self.lane(key), self.title(key)
        if review.startswith(HUMAN_MARK):
            lines = [self._tag(key, n), "", f"你是开发团队里的「{title}」。所有检查都通过了，独立审查也放行了，但负责人在关卡上把它退回来，"
                     "意见原文如下：写明打回你（{title}）的部分由你改，别的看一眼就行。", "", "---", review[len(HUMAN_MARK):].strip()[:REVIEW_KEEP], "---"]
            lines[2] = lines[2].replace("{title}", title)
            if caught_up:
                lines += ["", "app 已经把你的分支快进到运行分支的最新提交：别的角色的代码都在你的工作目录里了。"]
            lines += ["", f"在你的工作目录 {lane['worktree']}（分支 {lane['branch']}）里改，只改需要改的那一处。你只能改：{self._writable(key)}。"
                      "改完自己跑 `node tests/enterprise/_run.cjs`，确认检查仍然全绿。"]
            return "\n".join(lines + self._closing(key))
        lines = [self._tag(key, n), "", f"你是开发团队里的「{title}」。所有检查都通过了，但独立评审读完全部改动后说「要改」"
                 f"（第 {s.get('review_rounds') or 1} 轮评审）。下面是评审意见原文：写明归你（{title}）的条目由你修；"
                 "归别人的看一眼就行，不用改。", "", "---", review.strip()[:REVIEW_KEEP], "---"]
        if s.get("review_note"):
            lines += ["", "评审里留给人决定的事，人已经定了，按这个做（和评审意见冲突时以这里为准）：", "", s["review_note"]]
        if caught_up:
            lines += ["", "app 已经把你的分支快进到运行分支的最新提交：别的角色的代码都在你的工作目录里了。"]
        lines += ["", f"在你的工作目录 {lane['worktree']}（分支 {lane['branch']}）里改。你只能改：{self._writable(key)}；"
                  "别的目录不归你，看可以，改不行。改完自己跑 `node tests/enterprise/_run.cjs`，确认检查仍然全绿。",
                  "某一条你认为不该改或改不了，不要硬改，在总结里写清理由，交给人决定。"]
        return "\n".join(lines + self._closing(key))

    def _settle(self) -> None:
        """End a run nothing can move any more; else name what it is doing."""
        lanes = [self.lane(k) for k in self.order]
        busy = self.s["needs_test"] or any(lane["status"] in ACTIVE for lane in lanes)
        gating = any(lane.get("gate") == "pending" for lane in lanes)
        if not busy and not gating and not any(self.lane(k)["status"] == "waiting" and self._ready(k) for k in self.order):
            failed = [self.title(k) for k in self.order if self.lane(k)["status"] == "failed"]
            if failed:
                self._end("failed", f"运行失败：{'、'.join(failed)}没做完，后面的角色没法开工")
                return
            if all(lane["status"] in ("merged", "done", "skipped") for lane in lanes):
                dk = next((k for k in self.order if self.lane(k).get("deployed")), None)
                url = self.lane(dk)["deployed"]["url"] if dk else None
                parts = [p for p in (self.s.get("verdict"), f"已部署到本机 {url}" if url else None) if p]
                self._end("done", "运行完成" + (f"：{'，'.join(parts)}" if parts else ""))
                return
            held = [k for k in self.order if self.lane(k)["status"] == "waiting" and self.roles[k].get("deploy")]
            red = int(self.s["tests"].get("failed") or 0)
            if held and red:
                self._end("done", f"运行结束：{self.s.get('verdict') or '评审没有结论'}，但测试还有 {red} 项没过，"
                                  f"没有部署，交给人决定")
                return
        if gating and not busy:
            self.s["status"] = "gating"
        elif any(self.lane(k)["status"] in ACTIVE and not self.roles[k]["writable"]
                 and self.lane(k)["attempts"][-1]["kind"] != "discuss" for k in self.order if self.lane(k)["attempts"]):
            self.s["status"] = "reviewing"
        elif any(lane["status"] in ACTIVE and lane["attempts"][-1]["kind"] not in ("work", "discuss") for lane in lanes if lane["attempts"]):
            self.s["status"] = "fixing"
        else:
            self.s["status"] = "running"

    def _end(self, status: str, text: str) -> None:
        if not self.ended:
            self.s.update(status=status, ended_at=self.d.now())
            self.emit("run", text)

    def _fail_lane(self, key: str, why: str, *, keep_merged: bool = False) -> None:
        lane, now = self.lane(key), self.d.now()
        why = " ".join(str(why).split())[:200]
        if lane["attempts"]:
            att = lane["attempts"][-1]
            att["error"], att["ended"] = why, att.get("ended") or now
        lane.update(status="merged" if keep_merged else "failed", done_at=now)
        text = f"{self.title(key)}第 {lane['attempt']} 轮没修成：{why}" if keep_merged else f"{self.title(key)}失败：{why}"
        self.emit("failed", text, role=key)

    async def stop(self, *, status: str = "stopped", text: str = "运行已停止") -> bool:
        """Cancel every live agent of the run; it ends as *status*."""
        if self.ended:
            return False
        now, mgr, ids = self.d.now(), self.d.manager(), []
        for key in self.order:
            lane = self.lane(key)
            if lane["status"] not in ACTIVE:
                continue
            if lane["attempts"]:
                att = lane["attempts"][-1]
                if att.get("agent") and not att.get("ended"):
                    ids.append(att["agent"])
                att["error"], att["ended"] = att.get("error") or "运行被停止", att.get("ended") or now
            lane.update(status="failed", done_at=now)
        self._end(status, text)
        await self.save()  # the end is on disk before anything is cancelled
        if mgr is not None:
            await asyncio.gather(*(cancel(mgr, aid) for aid in ids))
            await cancel_parent(mgr, self.parent)
        return True

    async def _credits(self, att: dict[str, Any]) -> float | None:
        """This attempt's credits: the turn stats Kiro Crew put on the session's replies."""
        mgr = self.d.manager()
        val = mgr.credits_of(att["agent"]) if mgr is not None and att.get("agent") else None
        return round(float(val), 3) if val is not None else None

    # --- what each agent is told ------------------------------------------------------------------------------- #

    def _tag(self, key: str, n: int) -> str:
        lane = self.lane(key)
        head = f"{TAG_PREFIX}run={self.rid} role={key} branch={lane['branch']} worktree={lane['worktree']}"
        return head + ("]" if n == 1 else f" attempt={n}]")

    def _matcher(self, key: str, n: int) -> Callable[[str], bool]:
        needle, mark = f"run={self.rid} role={key} ", f" attempt={n}]"
        return lambda line: line.startswith(TAG_PREFIX) and needle in line and (
            line.endswith(mark) if n > 1 else " attempt=" not in line)

    def _inputs(self, key: str) -> list[str]:
        """Every upstream role's outputs, in team order."""
        seen, todo = set(), list(self.roles[key]["depends_on"])
        while todo:
            k = todo.pop()
            if k not in seen:
                seen.add(k)
                todo.extend(self.roles[k]["depends_on"])
        return list(dict.fromkeys(p for k in self.order if k in seen for p in self.roles[k]["outputs"]))

    def _writable(self, key: str) -> str:
        return "、".join(f"`{g}`" for g in self.roles[key]["writable"]) or "无（只读，不改任何文件）"

    def _work_task(self, key: str, n: int = 1) -> str:
        s, lane, role = self.s, self.lane(key), self.roles[key]
        brief = role.get("brief", "")
        if (s.get("plan") or {}).get(key):  # the split a person approved at the gate
            brief = f"这次分给你的任务（{self._planner()}提议、人在关卡上批准的分工）：{s['plan'][key]}。\n\n" + brief
        if not role["writable"] and s.get("base"):
            brief += f"（需求提交是 {s['base'][:12]}，`git diff {s['base'][:12]} HEAD` 就是全部改动。）"
            t = s.get("tests") or {}
            if t.get("total"):
                red = [c["name"] for c in t.get("cases", []) if c.get("status") == "fail"]
                brief += (f"app 刚跑的测试：{t.get('passed')}/{t.get('total')} 通过" +
                          (f"，没过的：{'；'.join(red[:8])}。没过的测试要算进结论。" if red else "，全绿。"))
        values = {"run": self.rid, "role": key, "title": role["title"], "branch": lane["branch"],
                  "worktree": lane["worktree"], "writable": self._writable(key), "brief": brief,
                  "inputs": "、".join(f"`{p}`" for p in self._inputs(key)) or "无", "repo": s["repo"],
                  "standards": standards_mod.task_lines(s.get("standards") or [], (self.team.get("knowledge") or {}).get("source") or "",
                                                        s.get("knowledge_source_id") or "")}
        text = s["task_template"].format_map(_Keep(values))
        notes = s.get("gate_notes") or {}
        if notes:  # what a person said when approving an earlier stage holds for everyone after it
            text += "\n\n人在关卡上批准时的意见（以此为准）：\n" + "\n".join(
                f"- {self.roles[k].get('gate_label') or self.title(k)}：{v}" for k, v in notes.items() if k in self.roles)
        answers = s.get("answers") or {}
        if answers:  # …and what they decided, question by question
            text += f"\n\n人在关卡上逐条做的决定（以此为准，也记在运行分支的 `{DECISIONS_FILE}`）：\n" + "\n".join(
                f"- {self.roles[k].get('gate_label') or self.title(k)} · 决定 {a['id']}「{a['q']}」："
                + (f"其他：{a['text']}" if a["choice"] == "other" else f"{a['choice']}（{a['option']}）" + (f"，补充：{a['text']}" if a["text"] else ""))
                for k, rows in answers.items() if k in self.roles for a in rows)
        out = [k for k in self.order if k != key and self.lane(k)["status"] == "skipped" and self.lane(k).get("summary")]
        if out:  # an optional member that sits this run out: nobody writes its part or plans work for it
            text += ("\n\n这次不参加的成员：" + "；".join(f"{self.title(k)}（{self.lane(k)['summary']}）" for k in out)
                     + "。它们负责的部分保持模板原样，不要替它们写，也不要给它们分工。")
        if not role["writable"]:
            text = "\n".join("1. 你是只读的：不改任何文件，也不提交。" if "git add" in ln else ln for ln in text.splitlines())
        tag = self._tag(key, n)
        prev = self.lane(key)["attempts"][-1] if n > 1 and self.lane(key)["attempts"] else {}
        if n > 1 and not role["writable"] and (prev.get("summary") or "").startswith("要改") and s.get("review_rounds"):
            text += (f"\n\n这是第 {int(s['review_rounds']) + 1} 轮评审。上一轮评审说「要改」，相关角色已经按意见改过并重新合入，"
                     "测试结果见测试墙。先按上一轮的问题编号（F-1、F-2……）逐条核对改好了没有（没改的，看它在提交说明或总结里给的理由是否成立），编号不变，"
                     "再看这一轮的新改动有没有引入新问题。上一轮的意见：\n\n---\n"
                     + (prev.get("reply") or prev.get("summary") or "").strip()[:REVIEW_KEEP] + "\n---")
            if s.get("review_note"):
                text += f"\n\n上一轮之后，人对评审留给人决定的事做了决定（以此为准，不算问题）：\n\n{s['review_note']}"
        elif n > 1 and not role["writable"] and s.get("human_review"):
            text += ("\n\n上一轮你放行了，但负责人在关卡上退回，意见：\n\n---\n" + s["human_review"].strip()[:REVIEW_KEEP] +
                     "\n---\n\n相关成员已经按意见改完并重新合入。先核对这条改好了没有，再看这次的新改动有没有引入新问题；"
                     "上一轮的问题编号保持不变。")
        elif n > 1:  # a retry: say what happened to the round before
            text += (f"\n\n这是第 {n} 次开工：上一次没做完（{prev.get('error') or '没有结果'}）。工作目录里可能有上一次留下的半成品，"
                     "先 `git status`、`git log` 看一眼，能用的接着用。")
        return text if first_line(text) == tag else f"{tag}\n\n{text}"

    def _closing(self, key: str) -> list[str]:
        lane = self.lane(key)
        return ["", "做完以后：", f"1. 在 {lane['worktree']} 里 `git add` 你改过的文件，提交到 {lane['branch']}，提交说明以 `[{key}]` 开头。",
                "2. 最后一条回复的第一行写 `DONE: ` 加一句话总结。", "3. 不要 push，不要动别的分支，不要改 git 配置。"]

    def _fix_task(self, key: str, n: int, failing: list[dict[str, Any]], caught_up: bool = False, said: str = "") -> str:
        s, lane = self.s, self.lane(key)
        files = " ".join(sorted({c["file"] for c in failing}))
        if said:  # the test writer: the implementers say these tests are wrong themselves
            lines = [self._tag(key, n), "", f"你是开发团队里的「{self.title(key)}」，这些测试是你写的。app 在运行分支 `{s['branch']}` 上"
                     f"跑了测试，下面这些没过，负责实现的角色改不动了，它们是这么说的：", said, "", "没过的测试："]
            lines += [f"- {c['name']}（{c['file']}）：{c.get('message') or '失败'}" for c in failing[:15]]
            lines += ["", "对照需求和契约核一遍：测试写错了（比如几个用例共用一个服务、前面的下单改了库存、断言和契约不一致），"
                      "就改测试；测试没错，就不改，并在回复里说清楚是实现的哪里不对。"]
            if caught_up:
                lines += ["", "app 已经把你的分支快进到运行分支的最新提交：实现的代码都在你的工作目录里了。"]
            lines += ["", f"在你的工作目录 {lane['worktree']}（分支 {lane['branch']}）里改。你只能改：{self._writable(key)}。",
                      f"可以自己跑 `node --test {files}` 看结果。"]
            return "\n".join(lines + self._closing(key))
        lines = [self._tag(key, n), "", f"你是开发团队里的「{self.title(key)}」。app 在运行分支 `{s['branch']}` 上跑了测试"
                 f"（`{s['tests'].get('command') or 'npm test'}`），归你负责的这些没过："]
        lines += [f"- {c['name']}（{c['file']}）：{c.get('message') or '失败'}" for c in failing[:15]]
        if caught_up:
            lines += ["", "app 已经把你的分支快进到运行分支的最新提交：测试和别的角色的代码都在你的工作目录里了。"]
        lines += ["", f"在你的工作目录 {lane['worktree']}（分支 {lane['branch']}）里把它们修好。你只能改：{self._writable(key)}；"
                  "测试和别的目录不归你，看可以，改不行。", f"可以自己跑 `node --test {files}` 看结果。"]
        return "\n".join(lines + self._closing(key))

    def _with_context(self, key: str, task: str) -> str:
        """A fix or conflict task for a fresh agent: it has not seen the role's earlier rounds, so they are summed up."""
        lane = self.lane(key)
        files = "、".join(f["path"] for f in lane.get("files", [])[:12]) or "还没有"
        story = ["", f"背景：这个角色之前几轮的对话接不上了，你接着做。上一轮的总结：{lane.get('summary') or '没有'}；"
                 f"相对开工时改过的文件：{files}。先看 `git log --oneline {lane['fork'][:12]}..HEAD` 了解做过什么。"]
        head, _, rest = task.partition("\n")
        return "\n".join([head, *story, rest.lstrip("\n")]) if rest else "\n".join([head, *story])

    def _conflict_task(self, key: str, n: int, conflicts: list[str]) -> str:
        s, lane = self.s, self.lane(key)
        lines = [self._tag(key, n), "", f"你是开发团队里的「{self.title(key)}」。你的分支 `{lane['branch']}` 合入运行分支 "
                 f"`{s['branch']}` 时冲突了，冲突的文件：{'、'.join(conflicts[:12])}。它们在运行分支上已经被别的角色改过。",
                 f"- 不在你可写范围（{self._writable(key)}）里的：本来就不该改。恢复成你开工时的样子："
                 f"`git checkout {lane['fork'][:12]} -- <文件>`；你开工时还没有的文件，`git rm` 掉。",
                 f"- 在你可写范围里的：先 `git checkout {s['branch']} -- <文件>` 拿到运行分支上的版本，再在它上面把你的改动重新做好。"]
        return "\n".join(lines + self._closing(key))
