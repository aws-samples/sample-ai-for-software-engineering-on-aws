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
import contextlib
import errno
import json
import logging
import os
import re
import secrets
import shutil
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from . import bench as bench_mod
from . import checks, gitwork, messages
from . import commits as commits_mod
from . import delivery as delivery_mod
from . import servers as servers_mod
from . import triage as triage_mod
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
# a turn the model backend could not finish (an HTTP 5xx, a runtime that died, no network): worth one more go in a
# new session
# the network wordings are the model backend's own; a bare ``connection`` would also take in the permanent failures
# (connection refused, connection closed) that are a person's to look at right away
TRANSIENT_ERROR = re.compile(r"transient|HTTP 5\d\d|5xx|runtime failed|timed? ?out|overloaded|rate.?limit|throttl"
                             r"|cannot reach the network|network error|connection (?:unstable|lost|reset by)", re.I)
ERRORS_TO_FAIL = 30  # this many failing ticks in a row (about a minute) end the run
REPLY_KEEP = 20_000  # characters of an agent's last reply kept for the 产出 view
# also mid-line (KiroCrew joins messages with no break), but not `DONE:` quoted in backticks in the reply's prose
_DONE_RE = re.compile(r"(?<![A-Za-z`])DONE\s*[:：]\s*(.*)$", re.M)
TRACE_RULE = ("每个提交说明都写它对应的发现编号（`F-003`）；修的发现在分诊里 behaviour 为 true 时，再写它的事实条目之一（如 "
              "`SUP-GRACE`）。只写分诊里定为修复或说明的发现。没提交的改动提交掉；要改已有提交的说明，"
              "`git reset --soft $(git merge-base HEAD {branch})` 以后按发现重新提交。")
REVIEW_KEEP = 12_000  # characters of a 要改 review a bounced role is given
TALK_KEEP = 2_000  # characters of a role's answer in a 讨论 at its gate, kept for the gate card
DECISIONS_FILE = "docs/aidlc/decisions.md"  # what people decided at the gates, written into the run branch by the app
TRIAGE_FILE = "triage.json"  # the approved triage, beside the run's repository (runs/<run>/), out of the agents' worktrees
# a project path in a reply. shortcut: a dot-directory (.github/…, .kiro/…) is never matched, a silent miss that is
# safe (nothing there is a role's to be given); allow a leading dot here if a cause there must be proposed.
PATH_SAID = re.compile(r"(?<![\w/.-])((?:[\w-]+/)+[\w.-]+\.[A-Za-z]\w*|CMakeLists\.txt)(?![\w/])")
# a role saying where the cause is, or that a file is not its to change
CAUSE_SAID = re.compile(r"根因|真正的原因|原因是|不归我|改不了|可写范围|可改范围|能改的|不在我|没有权限|分给")
NOT_SAID = re.compile(r"(?:不在|不是)\s*[`*]*$")  # right before a path: 根因不在 X，在 Y names Y, not X
FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,}).*?(?:^[ \t]*\1[ \t]*$|\Z)", re.M | re.S)  # a fenced code block, to its end
# a reply's blocks: split at blank lines, headings and lines that are bold only (**F-032**)
BLOCK_SPLIT = re.compile(r"\n[ \t]*\n|\n(?=[ \t]*(?:#{1,6}[ \t]|\*\*[^\n]*\*\*[ \t]*$))", re.M)
FINDING_SAID = re.compile(r"F-\d{3}(?:\s*[~～–-]\s*F-\d{3})?")  # a finding, or a range of them, named in a reply
# what a role is never given by a proposal or a person: what judges it, the servers, the bench, the gates' record
FENCED = ("checks/**", "mcp/**", "bench/**", ".kiro/**", DECISIONS_FILE)
PROPOSED_MAX = 10  # paths proposed for one finding or check at most


def cause_paths(replies: list[str], mention: re.Pattern[str], mine: Callable[[str], bool],
                usable: Any) -> tuple[list[str], str]:
    """The files a role said the cause is in, or are not its to change, for one finding or check: in a block of its
    replies (fenced code left out), each path of a sentence saying so that *usable* accepts (a file of the project
    the role may be given), when the nearest *mention* (of a finding, or a check) before it in the block is one that
    *mine* accepts. And the first of those sentences, in the role's words ('' for none).

    shortcut: only the nearest mention counts, so in "F-032 和 F-040 的根因都在 X" X goes to F-040 alone; read lists
    of mentions if a role's replies need it."""
    paths: list[str] = []
    said = ""
    for block in (b for r in replies for b in BLOCK_SPLIT.split(FENCE.sub("", r))):
        named = [(m.start(), mine(m.group())) for m in mention.finditer(block)]
        for s in re.finditer(r"[^。\n；;]+", block):
            if not CAUSE_SAID.search(s.group()):
                continue
            got: list[str] = []
            for p in PATH_SAID.finditer(block, s.start(), s.end()):
                near = [ok for at, ok in named if at < p.start()]
                if (near and near[-1] and not NOT_SAID.search(block, 0, p.start()) and p.group(1) not in paths
                        and p.group(1) not in got and usable(p.group(1))):
                    got.append(p.group(1))
            paths += got
            said = said or (re.sub(r"\*\*|`", "", s.group()).strip(" -*") if got else "")
    return paths[:PROPOSED_MAX], said[:300]


def fenced(globs: list[str], root: Path | None = None) -> list[str]:
    """The paths or globs a person asked for that could reach what a role is never given (FENCED): by what the glob
    itself says and, with *root* (the work tree), by what a path of it resolves to, so a symlink committed at a path
    outside FENCED cannot stand in for a file inside it, nor for one outside the work tree (the source repo's own
    checks/, say)."""
    return [g for g in globs
            if any(_globs_meet(g.split("/"), f.split("/")) for f in FENCED) or resolves_fenced(g, root)]


def resolves_fenced(p: str, root: Path | None) -> bool:
    """Whether a path of the work tree *root* resolves, through a symlink, to what a role is never given: FENCED, or
    anything outside the work tree, or nothing at all (a symbolic link loop). False without a *root*."""
    if root is None:
        return False
    try:  # strict: a loop in any part (src/a/x.cpp with src/a one) is ELOOP on every Python version
        os.path.realpath(root / p, strict=True)
    except OSError as exc:
        if exc.errno == errno.ELOOP:  # it leads nowhere a role may be given
            return True
    try:
        rel = (root / p).resolve().relative_to(root.resolve())
    except ValueError:  # outside the work tree: no role's to be given
        return True
    except OSError:
        return False
    return gitwork.matches(str(rel), list(FENCED))


def _proposable(root: Path, p: str) -> bool:
    """Whether the app may propose path p to a person at all: a file of the work tree *root*, and not one a role is
    never given (FENCED, by what the path says and by what it resolves to)."""
    f = root / p
    return (f.is_file() and f.resolve().is_relative_to(root.resolve()) and not gitwork.matches(p, list(FENCED))
            and not resolves_fenced(p, root))


def _globs_meet(a: list[str], b: list[str]) -> bool:
    """Whether two globs, split at ``/``, may match one path: a ``**`` part (or a trailing ``/``) may match anything
    from there on, and two parts that are both wild are taken to meet."""
    a = [*a[:-1], "**"] if a and a[-1] == "" else a
    b = [*b[:-1], "**"] if b and b[-1] == "" else b
    if not a or not b:
        return all(p == "**" for p in a + b)
    x, y = a[0], b[0]
    if "**" in (x, y):
        return True
    wild = lambda p: "*" in p or "?" in p  # noqa: E731
    part = lambda p: "".join("[^/]*" if c == "*" else "." if c == "?" else re.escape(c) for c in p)  # noqa: E731
    if wild(x) and wild(y):
        meet = True
    elif wild(x) or wild(y):
        meet = bool(re.fullmatch(part(x), y) if wild(x) else re.fullmatch(part(y), x))
    else:
        meet = x == y
    return meet and _globs_meet(a[1:], b[1:])


def _ids_in(text: str) -> set[str]:
    """The finding IDs a sentence names, ranges (F-032~F-034) spelled out."""
    ids = set(re.findall(r"F-\d{3}", text))
    for a, b in re.findall(r"F-(\d{3})\s*[~～–-]\s*F-(\d{3})", text):
        ids.update(f"F-{n:03d}" for n in range(int(a), min(int(b), int(a) + 50) + 1))
    return ids
# A review names who fixes what: its own `打回：` line (`Send back:` from the English board; role keys, titles or
# English titles), else every 归X it writes.
_BOUNCE_LINE_RE = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)、]\s*)?[*_`]*(?:打回|send back)[*_`]*\s*[:：]\s*(.+)$",
                             re.M | re.I)  # a list item too
_OWNER_RE = re.compile(r"归([^）)，,；;。\n]{1,40})")
_ROLE_ALIASES = {"后端": "backend", "服务端": "backend", "前端": "frontend", "网页": "frontend", "网页前端": "frontend",
                 "移动端": "mobile", "安卓": "mobile", "Android": "mobile", "运维": "ops", "合规": "compliance",
                 "安全": "compliance", "合规与安全": "compliance", "测试": "tester", "体验设计": "designer",
                 "设计": "designer", "UI 设计": "designer", "产品经理": "pm", "产品": "pm", "架构师": "architect",
                 "架构": "architect"}


class FindingRequestError(ValueError):
    """A finding the request cannot register; *detail*: what of the request it was about (a role, a check, a
    finding's ID), passed on to the English board as the error's detail."""

    def __init__(self, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.detail = detail


class FindingRefused(ValueError):
    """The triage with a person's new finding would not pass the checks' rules: what is wrong."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("；".join(problems))
        self.problems = problems


@dataclass
class Deps:
    """What a run needs from outside; tests pass fakes."""

    store: Store
    manager: Callable[[], Any]
    run_tests: Callable[..., Awaitable[dict[str, Any]]]  # (run worktree, team[, head, results, triage]) → test wall
    template: Path | None  # the project a team without a source starts from
    scrub: Callable[[str], str] = lambda s: s
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
        tri = r.get("triage")
        if tri is not None and not (r.get("gate") == "human" and isinstance(tri, dict) and _app_rel(str(tri.get("file") or ""))
                                    and isinstance(tri.get("knowledge"), str) and tri["knowledge"]):
            raise ValueError(f"team.json：{r['key']} 的 triage 要写成 {{file: 仓库里的相对路径, knowledge: 知识库目录}}，而且它要有人的关卡")
        if r.get("questions") is not None and not (r.get("gate") == "human" and isinstance(r["questions"], str) and _app_rel(r["questions"])):
            raise ValueError(f"team.json：{r['key']} 的 questions 要写成仓库里的相对路径，而且它要有人的关卡")
        if not isinstance(r.get("optional", False), bool):
            raise ValueError(f"team.json：{r['key']} 的 optional 要写 true 或 false")
        if r.get("writable_from") and not r["writable"]:
            r["writable"] = [PENDING_GLOB]
        if r.get("member") is not None and not (isinstance(r["member"], str) and re.fullmatch(r"[A-Za-z0-9][\w.-]{0,63}", r["member"])):
            raise ValueError(f"team.json：{r['key']} 的 member 要是 Crew 成员的名字")
        # template: a Kiro agent template of ~/.kiro/agents the role's session runs, without a Crew member (Kiro
        # Crew 0.12 builds a new member from its own worker, not from a template)
        if r.get("template") is not None and not (isinstance(r["template"], str) and re.fullmatch(r"[A-Za-z0-9][\w.-]{0,63}", r["template"])):
            raise ValueError(f"team.json：{r['key']} 的 template 要是 ~/.kiro/agents 里模板的名字")
        if r.get("member") and r.get("template"):
            raise ValueError(f"team.json：{r['key']} 只能写 member 或 template 其中一个")
    own = team.get("ownership")
    if own is not None and (not isinstance(own, dict) or own.get("from") not in keys or not isinstance(own.get("file"), str)):
        raise ValueError("team.json：ownership 要写明分工文件 file 和由谁写 from")
    if any(r.get("writable_from") for r in roles) and own is None:
        raise ValueError("team.json：有角色的目录由分工决定（writable_from），但没有 ownership")
    if team.get("source") is not None and not (isinstance(team["source"], str) and team["source"].strip()):
        raise ValueError("team.json：source 要写成要改的项目目录（可以用 ${sample}/…）")
    checks.check_config(team, keys)
    servers_mod.check(team)
    delivery_mod.check(team)
    return team


def _app_rel(path: str) -> bool:
    """A path inside the target repo (no absolute path, no ``..``)."""
    return bool(path) and not path.startswith("/") and ".." not in Path(path).parts


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


_REVIEW_OK = re.compile(r"^\s*(?:可以交付|ready to deliver|can be delivered|ok to deliver)", re.I)
_REVIEW_CHANGES = re.compile(r"^\s*(?:要改|changes? (?:needed|requested|required)|needs? changes)", re.I)


def review_verdict(summary: Any) -> str:
    """A reviewer's ``DONE:`` line: ``ok`` (可以交付, or "Ready to deliver" from an agent writing English), ``changes``
    (要改, "Changes needed"), else ``""``."""
    text = str(summary or "")
    return "ok" if _REVIEW_OK.match(text) else "changes" if _REVIEW_CHANGES.match(text) else ""


def _plain(text: str) -> str:
    """For matching an English role name: lower case, without markdown ``*`` and `` ` ``, ``·`` ``-`` ``–`` ``—``
    ``_`` and runs of spaces as one space, no trailing ``.:：。``."""
    text = re.sub(r"[*`]", "", text.lower())
    return " ".join(re.sub(r"[·・\-–—_]", " ", text).split()).rstrip(" .:：。")


# a path in a send-back line, taken out whole before the line is split into roles: a word holding a / that starts
# at a folder of a project, at ~ or /, or ends in a file; it may begin after ` " ' ( [ or : and ends before them
_PATH = re.compile(r"""
    (?<![^\s`"'(\[:])
    (?: [~.]?/(?=[\w.~-])                                              # ~/…  ./…  /… (not a bare " / ")
      | (?:docs|src|tests?|cmake|checks|bench|app|scripts|include|lib)/  # a folder of a project
      | [\w.~-]+/[\w./-]*\.\w+                                       # a file: a/b.md
    ) [^\s`"')\],;]*""", re.X)
_TICKED = re.compile(r"`([^`\n]*)`")  # a backticked span: one with a / in it is a path (`Tester/plan`), left out
_URL = re.compile(r"(?<![a-z0-9+.-])[a-z][a-z0-9+.-]*://\S*", re.I)  # a link, left out whole (one scan per start)
_ASIDE = re.compile(r"\([^)]*\)|（[^）]*）")  # what a send-back line says about the change, not whom it goes to
# asides standing alone between two " / " ("fix / (note) / Tester", one or more in a row: "fix / (a) (b) / Tester")
# leave a mark, not nothing, so that the two " / " around them stay two (taken out, they would leave
# "fix /  / Tester", and the role after them would be lost)
_ASIDE_BETWEEN = re.compile(r"(?<=\s/)(\s+)(?:\([^)]*\)|（[^）]*）)(?:\s*(?:\([^)]*\)|（[^）]*）))*(?=\s+/\s)")
_MARK = "\x00"


def review_targets(text: str, roles: list[dict[str, Any]]) -> list[str]:
    """The writing roles a 要改 review sends back, in team order: its ``打回：`` (or ``Send back:``) lines (one per role
    is fine), else every 归X it names."""
    writers = [r["key"] for r in roles if r.get("writable")]
    names = {**_ROLE_ALIASES, **{r["title"]: r["key"] for r in roles}, **{k: k for k in writers}}
    lines = _BOUNCE_LINE_RE.findall(text or "")
    en = {r["key"]: _plain(r["title_en"]) for r in roles if r.get("writable") and r.get("title_en")}

    def starts(part: str, key: str) -> bool:
        return bool(re.match(rf"(?:the\s+)?{re.escape(en[key])}(?!\w)", part))

    def starts_word(raw: str, key: str) -> bool:
        """As starts(), on the part as written: a word joined to the name by a hyphen (Tester-notes) is not it."""
        sep = r"[\s·・\-_–—]+"
        name = sep.join(map(re.escape, en[key].split()))
        return bool(re.match(rf"(?:the\s+)?{name}(?![\w-])", re.sub(r"[*`]", "", raw).strip().lower()))

    def a_role(part: str) -> bool:
        return bool(names.get(part.strip(" `*_（）()"))) or any(starts_word(part, k) for k in en)

    def ticked(m: re.Match[str]) -> str:
        """A backticked span with a / is a path (`Tester/plan`, also `Developer · fix/qa`: a role's name before the /
        does not make it one), unless each of its parts is a role's name. A path becomes an item separator."""
        return m.group(0) if "/" not in m.group(1) or all(map(a_role, m.group(1).split("/"))) else ","

    # a role the note goes on to mention in parentheses is not sent back too, nor one a path's folder is named after;
    # a path or a link taken out leaves a "," so that what comes after it (" / Tester") is an item of its own
    def plain_line(c: str) -> str:
        return _PATH.sub(",", _URL.sub(",", _TICKED.sub(ticked, _ASIDE.sub("", _ASIDE_BETWEEN.sub(r"\1" + _MARK, c)))))
    marked = [plain_line(c) for c in lines] or _OWNER_RE.findall(text or "")
    chunks = [c.replace(_MARK, "") for c in marked]  # the mark only splits English items below
    # a word with a / (后端/测试, qa/tester) names each part only when every part is a role's name,
    # else its first part only
    found: set[str | None] = set()
    for chunk in chunks:
        for word in re.split(r"[、,，和及与\s]+", chunk):
            parts = [names.get(p.strip(" `*_（）()")) for p in word.split("/")]
            found |= set(parts) if all(parts) else {parts[0]}
    found |= {r["key"] for r in roles if r.get("writable") and any(r["title"] in chunk for chunk in chunks)}
    # English names name a target only where an item of the line starts with one ("the Developer · fix role" too);
    # items are split on , ; 、 and "and", and a spaced " / " splits an item too (a path left a "," before it:
    # "see src/a.c / Tester"). Every part after a spaced " / " starts with the role's name as written, not joined to a
    # word by a hyphen: "Developer · fix / Tester-side cases" names the fix role only, as "Tester-cases" is no role.
    # A part with a bare / ("Developer · fix/Tester") names each of its pieces only when every piece starts with a
    # role's name (after the /, as written); else only its first piece counts, so that what a path, a branch or a
    # two-part name ("qa/Tester", "feature/Tester-cases") holds after a / is no role
    for chunk in marked:
        for item in re.split(r"[,，;；、]|\band\b", chunk, flags=re.I):
            for i, part in enumerate(p.replace(_MARK, "") for p in re.split(r"\s+/\s+", item)):
                raw = part.split("/")
                if not raw[0].strip():
                    continue  # a blank lead (what a path left)
                lead = (starts(_plain(raw[0]), k) if i == 0 else starts_word(raw[0], k) for k in en)
                named = [{k for k, ok in zip(en, lead) if ok}, *({k for k in en if starts_word(p, k)} for p in raw[1:])]
                found |= set().union(*named) if all(named) else named[0]
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






def _ms(rows: list[dict[str, Any]]) -> int | None:
    """A round's check time: its checks' own wall times added up (None when a row has none)."""
    ms = [r.get("ms") for r in rows]
    return sum(ms) if ms and all(isinstance(m, int) for m in ms) else None


def _held_reasons(rows: Any) -> list[str]:
    """Every reason of the held checks, oldest first. The hold's ``why`` and its params carry only the first one of
    each, and a check names what a person must act on in any of them (checks/lib/check_static.py writes the new
    findings before the ones the batch removed), so the board needs the whole list."""
    return [str(x)[:300] for r in rows for x in (r.get("reasons") or [r.get("summary") or ""]) if str(x).strip()][:40]


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
        "seq": 0, "needs_test": False, "lanes": {r["key"]: _lane() for r in team["roles"]}, "merges": [],
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
        self._tests: tuple[str, asyncio.Task[dict[str, Any]]] | None = None  # (head, the test run in the background)
        self._first: tuple[str, asyncio.Task[dict[str, Any]]] | None = None  # (head, the tester's tests on the base)
        self._bench: asyncio.Task[Any] | None = None  # the bench step in the background (doctor, deploy, replay, checks)
        self.errors = 0

    @property
    def impl(self) -> list[str]:
        """The roles that make the tests pass (they get bounced); the ownership file may name them during the run. With
        the team file's checks: the checks' owners and the roles the work split gives files to."""
        owners = {o.get("role") for o in self.team.get("test_owners", [])}
        owners |= {c.get("owner") for c in self.team.get("checks") or []}
        owners |= {k for k in self.order if self.roles[k].get("writable_from")}
        return [k for k in self.order if k in owners and self.lane(k)["status"] != "skipped"]

    @property
    def _build_start(self) -> str | None:
        """The build-start gate: the last of the team's human gates (D13)."""
        return next((k for k in reversed(self.order) if self.roles[k].get("gate") == "human"), None)

    @property
    def test_writers(self) -> list[str]:
        # a test file a person added to an implementer's scope with a finding (TR §4.4) does not make it a test writer
        return [k for k in self.order if any(g.startswith("tests/") and g not in (self.roles[k].get("granted") or [])
                                             for g in self.roles[k]["writable"])]

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

    def gate_label(self, key: str) -> str:
        return self.roles[key].get("gate_label") or self.title(key) if key in self.roles else key

    def msg(self, code: str, params: dict[str, Any] | None = None) -> str:
        """The Chinese text of a message (messages.py), with its roles named."""
        return messages.render(code, params, lambda k: self.title(k) if k in self.roles else k, self.gate_label)

    def emit(self, kind: str, text: str | None, role: str | None = None, frm: str | None = None, to: str | None = None,
             data: dict[str, Any] | None = None, *, code: str | None = None, params: dict[str, Any] | None = None) -> None:
        """An event on the board. With a *code*, its Chinese *text* comes from the code and its *params*, and the board
        says it in the person's language; without one (an older run's events, too), the board shows *text* as it is."""
        self.s["seq"] = int(self.s.get("seq") or 0) + 1
        if code:
            params = messages.clean(params)
            text = self.msg(code, params)
        ev = {"seq": self.s["seq"], "at": self.d.now(), "kind": kind, "role": role, "text": " ".join((text or "").split())[:200],
              "from": frm, "to": to, "data": data or None}
        if code:
            ev.update(code=code, params=params)
        self.events.append(ev)
        self._unsaved.append(ev)

    def say(self, kind: str, code: str, params: dict[str, Any] | None = None, **kw: Any) -> None:
        self.emit(kind, None, code=code, params=params, **kw)

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
                if self.ended:  # the batch's commits as they stay (D18), for the sign-off card
                    await self.commit_sizes()
                self.errors = 0
            except Exception as exc:
                self.errors += 1
                if self.errors >= ERRORS_TO_FAIL:
                    await self.stop(status="failed", code="run.error", params={"error": str(exc)})
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
            await self._tests_first()
        if not self.ended:
            await self._bench_step(mgr)
        if not self.ended:
            self._settle()

    async def _setup(self) -> None:
        s = self.s
        try:
            source = s.get("source")
            template = Path(source) if source else self.d.template
            base = await gitwork.create_repo(template, Path(s["repo"]), s["requirement"], s["title"],
                                             existing=bool(source))
            await gitwork.add_worktree(Path(s["repo"]), Path(s["run_wt"]), s["branch"], base)
        except Exception as exc:  # noqa: BLE001
            self._end("failed", "run.repo_failed", {"error": str(exc)})
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
                        self.say("member", "member.missing", {"r_role": key, "member": missing}, role=key)
                    return
                if lane.get("awaiting_member"):
                    self.say("member", "member.added", {"member": lane["awaiting_member"], "r_role": key}, role=key)
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
        if (lane.get("first") or {}).get("status", "passed") != "passed":  # the tester's tests did not fail on the base yet
            return False
        if not self.roles[key]["writable"]:  # a reviewer: done, it let the work through, and a person did (its gate)
            return lane["status"] == "skipped" or (lane["status"] == "done" and bool(lane.get("passed")) and (
                self.roles[key].get("gate") != "human" or lane.get("gate") == "approved"))
        return lane["status"] == "skipped" or (lane["status"] == "merged" and (
            self.roles[key].get("gate") != "human" or lane.get("gate") == "approved"))

    def _after(self, key: str) -> set[str]:
        """The roles that wait for *key*, directly or further down."""
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
        if role["writable"]:
            return True
        # Read-only (the reviewer): every writing role it depends on (directly or further up) is in, no gate waits for
        # a person, and the latest test run has settled: green, or nothing left to send back (a bounced role is fixing,
        # not merged). A role beside it (the tester, when the team says the review does not wait for it) goes on.
        before = self._before(key)
        return not self.s["needs_test"] and not self.s["tests"].get("held") and all(self._settled(k) for k in self.order
                                                if self.roles[k]["writable"] and k in before)

    async def _start(self, key: str, kind: str, mgr: Any, *, failing: list[dict[str, Any]] | None = None,
                     conflicts: list[str] | None = None, review: str = "", found: list[dict[str, Any]] | None = None) -> None:
        """A new attempt: ``work`` (the role's first, or a retry of it), ``fix`` (failing tests; with *found*: the
        findings a person registered for them), ``conflict`` (its merge) or ``review`` (what a 要改 review found in its
        area)."""
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
                names = [_name(p) for p in self.roles[dep]["outputs"]]
                self.say("handoff", "handoff", {"r_from": dep, "outs": names, "r_role": key}, role=key, frm=dep, to=key,
                         data={"carry": "、".join(names) or "产出"})
        n = len(lane["attempts"]) + 1
        # a round's label is said by a label.* message (its Chinese words are kept; the board says them by code)
        if kind == "fix" and found:
            caught_up = await self._catch_up(key)
            task, label = self._found_task(key, n, found, caught_up), self.msg("label.fix", {"items": [f["id"] for f in found]})
        elif kind == "fix":
            items = [c["ac"] or c["name"] for c in failing[:6]]
            caught_up = await self._catch_up(key)
            task = self._fix_task(key, n, failing, caught_up, said=review)
            label = self.msg("label.fix", {"items": items, "more": len(failing) > 6})
        elif kind == "conflict":
            task, label = self._conflict_task(key, n, conflicts or []), self.msg("label.conflict")
        elif kind == "review":
            caught_up = await self._catch_up(key)
            task, label = self._review_task(key, n, review, caught_up), self.msg("label.review")
        elif kind == "trace":  # its commits do not cite their findings: it commits again, its worktree as it is
            task, label = self._revise_task(key, n, review, False), self.msg("label.trace")
        elif kind == "revise":  # never merged yet (a wrong ownership file): it redoes its own branch as it is
            caught_up = await self._catch_up(key) if lane.get("merged_sha") else False
            task, label = self._revise_task(key, n, review, caught_up), self.msg("label.revise")
        elif kind == "discuss":  # a person at its gate talks with it: it answers, and changes its documents if it has to
            caught_up = await self._catch_up(key) if role["writable"] and lane.get("merged_sha") else False
            task, label = self._discuss_task(key, n, review, caught_up), self.msg("label.discuss")
        else:
            sizes = await self.commit_sizes() if not role["writable"] else None  # the reviewer's table (D18)
            task, label = self._work_task(key, n, sizes), (self.msg("label.again") if n > 1 else "")
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
        again = att.pop("again", None) or None
        if att["kind"] == "work" and att["n"] == 1:
            code, params = ("spawned.dispatch", {"r_role": key, "task": task}) if task else ("spawned.start", {"r_role": key})
        else:
            code, params = "spawned.round", {"r_role": key, "n": att["n"], "label": messages.label_of(att["label"]) or att["label"]}
        self.say("spawned", code, {**params, "again": messages.as_msg(again, "again.")}, role=key)
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
            self.d.log.info("vstatd-team: %s/%s cannot continue its session (%s): a new one takes over",
                            self.rid, key, why[:160])
            att["via"] = "fresh"
            if self.ended:
                return None
        task = att["task"] if att["kind"] == "work" else self._with_context(key, att["task"])
        return mgr.spawn_session(task, parent_session_key=self.parent, cwd=lane["worktree"], model=model,
                                 title=f"{self.title(key)} agent", folder=f"{self.s['title'][:24]} · {self.rid}",
                                 agent=role.get("member") or role.get("template") or "")

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
            self.say("tool", "tool", {"r_role": key, "tool": tool}, role=key)
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
        if await self._unmerged_messages(key):  # work not merged yet (held for a person, D15): nothing to catch up
            return False  # (``merge --ff-only`` would say "up to date" and the unmerged commits would count as merged)
        if not await gitwork.fast_forward(wt, self.s["branch"]):
            self.d.log.info("vstatd-team: %s/%s cannot fast-forward to the run branch", self.rid, key)
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
                self.say("committed", "committed", {"r_role": key, "subject": c["subject"]}, role=key)
        del seen[:-50]
        self._violations(key, st["paths"])

    def _violations(self, key: str, paths: list[str]) -> None:
        lane, globs = self.lane(key), self.roles[key]["writable"]
        for p in paths:
            if gitwork.is_host_path(p) or p in lane["violations"] or gitwork.matches(p, globs) or len(lane["violations"]) >= 50:
                continue
            lane["violations"].append(p)
            if len(lane["violations"]) <= 12:
                self.say("violation", "violation", {"r_role": key, "path": p}, role=key)

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
            await self._again(key, att, self.msg("again.transient"))
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
        self.say("done", "done", {"r_role": key, "summary": att["summary"]}, role=key)
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

    def review_redo(self) -> dict[str, Any] | None:
        """按评审意见再改一轮, open to a person: the run ended on a 要改 review that names the roles it sends back, and no
        role failed. {role: the reviewer, summary, targets: the roles it sends back}; None otherwise."""
        if not self.ended or any(self.lane(k)["status"] == "failed" for k in self.order):
            return None
        rev = next((k for k in self.order if not self.roles[k]["writable"] and self.lane(k)["status"] == "done"), None)
        last = self.lane(rev)["attempts"][-1] if rev and self.lane(rev)["attempts"] else {}
        targets = review_targets(last.get("reply") or "", self.team["roles"])
        if not (review_verdict(last.get("summary")) == "changes" and targets):
            return None
        return {"role": rev, "summary": str(last["summary"]), "targets": targets}

    async def retry(self, keys: list[str] | None = None, note: str = "", by: str = "") -> list[str]:
        """The person's 重试: every failed role (or the given ones) gets one more round, and an ended run carries on.
        A role whose work never got merged starts over in its own worktree (what it left there stays); a role that
        failed later is sent back with what is failing now, or its merge is tried again."""
        async with self._lock:
            failed = [k for k in self.order if self.lane(k)["status"] == "failed"]
            bench = self.s.get("bench") or {}
            held = self.servers_retry()
            if not keys and not failed and self.ended and held:  # the servers could not do it (D17): again
                self._resume()
                self.s["servers_held"] = None
                if held == "checks":
                    t = self.s["tests"]
                    t.update(held=None, head=None)
                    if self._repair_stop():  # the person decided at the build server's bound: this round runs
                        t["repair_go"] = True
                    self.s["needs_test"] = True
                self.say("run", "retry.servers", {"by": by, "note": note},
                         data={"by": by, "note": note} if by else None)
                self._settle()
                await self.save()
                return ["servers"]
            if not keys and not failed and self.ended and bench.get("held"):  # a person dealt with the bench: carry on
                self._resume()
                bench["held"] = None
                self.say("run", "retry.bench", {"by": by, "step": bench["step"], "note": note},
                         data={"by": by, "note": note} if by else None)
                self._settle()
                await self.save()
                return ["bench"]
            redo = self.review_redo() if not keys and not failed else None
            if redo:  # it ended on a 要改 review: the person sends that back
                rev = redo["role"]
                review = self.lane(rev)["attempts"][-1].get("reply") or ""
                self._resume()
                if note:  # the person's decisions on what the review left to them
                    self.s["review_note"] = note
                self.say("run", "retry.review", {"by": by, "note": note},
                         data={"by": by, "note": note} if by else None)
                picked = await self._review_bounce(rev, review)
                self._settle()
                await self.save()
                return picked
            picked = [k for k in self.order if k in set(keys)] if keys else failed
            if not picked or any(k not in failed for k in picked):
                return []
            if self.ended:
                self._resume()
            self.say("run", "retry.roles", {"r_roles": picked})
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
                    first = lane.get("first") or {}
                    if first.get("status") == "failed":  # its tests did not fail on the base: one more round at that
                        first["status"] = "sent_back"
                        await self._start(key, "revise", mgr, review=self._first_review(first))
                    elif failing:
                        await self._start(key, "fix", mgr, failing=failing)
                else:
                    lane.update(status="waiting" if not self._ready(key) else lane["status"])
                    if self._ready(key):
                        await self._start(key, "work", mgr)
            self._settle()
            await self.save()
            return picked

    # --- a finding a check found, registered by a person (TR §4.4) ------------------------------------------- #

    def _knowledge(self) -> Path | None:
        return next((Path(r["triage"]["knowledge"]) for r in self.team["roles"] if r.get("triage")), None)

    def next_finding_id(self) -> str:
        """The next free ID: after the backlog's and every ID in the approved triage (added ones take them in turn)."""
        k, t = self._knowledge(), self._approved_triage() or {}
        ids = [int(i[2:]) for i in (triage_mod.backlog(k) if k else {})]
        ids += [int(f["id"][2:]) for f in t.get("findings") or [] if isinstance(f, dict)
                and re.fullmatch(r"F-\d{3}", str(f.get("id")))]
        return f"F-{max(ids, default=0) + 1:03d}"

    async def register_finding(self, body: dict[str, Any]) -> dict[str, Any]:
        """A person registers a defect a check found and the backlog does not have (TR §4.4) while the run is held
        for them after the checks: it gets the next free ID in the approved triage (``added``: the check, its tool and
        where), *role* may write *paths* from now on, and with ``continue`` the hold ends and the role gets one more
        round of that check, its session continued with the check's reasons and the findings registered since the
        hold. Without ``continue`` the run stays held, so several can be registered first.

        Raises LookupError (not held), ValueError (the request) or FindingRefused (the triage would not pass)."""
        async with self._lock:
            t = self.s["tests"]
            held = t.get("held")
            if not held:
                raise LookupError("这个运行没有在检查之后停下来等人决定")
            spec = {c["name"]: c for c in self.team.get("checks") or []}
            role, ext = body["role"], body.get("extend")
            # a finding added already may also go to a test writer: the test a unit-test finding lacks is its to write
            if (role not in self.impl and not (ext and role in self.test_writers)) or not self.roles[role]["writable"]:
                choices = "、".join(self.impl)
                raise FindingRequestError(f"{role} 不是做实现的角色（可以选：{choices}）", str(role))
            wt = self.s.get("run_wt")
            bad = fenced(body["paths"], Path(wt) if wt else None)
            if bad:  # what judges the role, the servers, the bench or the gates' record: never the role's to change
                raise FindingRequestError(f"{'、'.join(bad)} 会碰到检查、服务器、台架或门禁决定的文件"
                                          f"（{'、'.join(FENCED)}），不能交给角色改", ", ".join(bad))
            k, path = self._knowledge(), Path(self.s["repo"]).parent / TRIAGE_FILE
            data = self._approved_triage()
            if k is None or data is None:
                raise ValueError("这个运行还没有批准的分诊，没地方登记发现")
            if ext:  # a finding added already: its role gets more paths, the triage stays as it is
                entry = next((f for f in data.get("findings") or [] if isinstance(f, dict) and f.get("id") == ext
                              and isinstance(f.get("added"), dict)), None)
                if entry is None:
                    raise FindingRequestError(f"批准的分诊里没有补登过的 {ext}", str(ext))
                m = re.fullmatch(r"checks/([\w-]+)\.sh", str(entry["added"].get("found_by") or ""))
                if not m:
                    raise FindingRequestError(f"{ext} 不是检查发现的，没有检查可以再跑一轮", str(ext))
                fid, check, location = ext, m.group(1), str(entry["added"].get("location") or "")
                digest = str((self.s.get("triage") or {}).get("sha256") or "")
            else:
                check, location = body["check"], body["location"]
            if check not in spec:
                raise FindingRequestError(f"团队没有叫 {check} 的检查", str(check))
            if not ext:
                fid = self.next_finding_id()
                entry = {"id": fid, "decision": body["decision"]}
                for key in ("evidence", "behaviour", "facts", "cites", "reason", "pick_up_when", "note"):
                    if body.get(key) not in (None, "", []):
                        entry[key] = body[key]
                entry["added"] = {"found_by": f"checks/{check}.sh", "tool": body["tool"], "location": location}
                data = {**data, "findings": [*data.get("findings", []), entry]}
                problems = triage_mod.problems(data, k)
                if problems:
                    raise FindingRefused(problems)
                digest = await asyncio.to_thread(triage_mod.write, path, data)
                if isinstance(self.s.get("triage"), dict):
                    self.s["triage"]["sha256"] = digest
            r = self.roles[role]
            added = [g for g in body["paths"] if g not in r["writable"]]
            r["writable"] = [*r["writable"], *added]
            r["granted"] = [*(r.get("granted") or []), *added]
            reg = {"id": fid, "check": check, "role": role, "paths": list(body["paths"]), "added_paths": added,
                   "decision": entry["decision"], "evidence": entry.get("evidence"), "behaviour": entry.get("behaviour"),
                   "facts": entry.get("facts") or [], "location": location, "note": body["note"], "by": body["by"],
                   "extend": bool(ext)}
            held["registered"] = [*(held.get("registered") or []), reg]
            go_on = bool(body["continue"])
            self.say("finding", "finding.extend" if ext else "finding.add",
                     {"by": body["by"], "id": fid, "check": check, "location": location,
                      "decision": None if ext else entry["decision"], "r_role": role, "paths": list(body["paths"]),
                      "go_on": go_on, "note": body["note"]},
                     role=role, frm="person", to=role,
                      data={"by": body["by"], "id": fid, "check": check, "role": role, "paths": list(body["paths"]),
                            "note": body["note"], "continue": go_on, "extend": bool(ext)})
            if go_on:
                await self._go_on_with_findings(held["registered"])
            await self.save()
            return {"id": fid, "triage_sha256": digest, "held": bool(t.get("held")), "status": self.s["status"]}

    def path_suggestions(self) -> list[dict[str, Any]]:
        """给已补登的发现加路径, proposed for a person to agree to: for each held check that has a finding added for it
        already, the files its role cannot write that would let it fix it. From what the role said (a path in its
        replies about the finding that is in the project and outside its scope) and, for a unit-test finding no test
        names yet (TR §4.1), the test file of its location when the project has it already (a new one would not be
        compiled: reference-project/tests/CMakeLists.txt names its test sources one by one), proposed on its own to
        the role whose scope has it (the tester: the developer is never given tests/**), or to the finding's role
        when no role's has it. [] when there is nothing to propose; nothing changes here."""
        t, data = self.s["tests"], self._approved_triage()
        held, wt = t.get("held"), self.s.get("run_wt")
        if not held or not data or not wt:
            return []
        root = Path(wt)
        added = [f for f in data.get("findings") or [] if isinstance(f, dict) and isinstance(f.get("added"), dict)]
        rows = {r["name"]: r for r in t.get("checks") or []}
        out: list[dict[str, Any]] = []
        for c in held.get("checks") or []:
            mine = [f for f in added if f["added"].get("found_by") == f"checks/{c}.sh"]
            owners = [o for o in (rows.get(c) or {}).get("owners") or [] if o in self.impl]
            role = owners[0] if owners else next(iter(self.impl), None)
            if not mine or role is None:
                continue
            first, ids = mine[0], {f["id"] for f in mine}
            loc = str(first["added"].get("location") or "")
            same = [f["id"] for f in mine[1:] if f["added"].get("location") == loc]
            said_paths, said = cause_paths(self._replies(role), FINDING_SAID, lambda m: bool(ids & _ids_in(m)),
                                           self._free(root, role))
            also = (f"。{'、'.join(same)} 和 {first['id']} 是同一个失败，提交说明一并写上 {first['id']}、{'、'.join(same)}"
                    if same else "")
            if said_paths:
                out.append({"extend": first["id"], "check": c, "role": role, "paths": said_paths,
                            "note": (f"{self.title(role)}说：{said}" + also)[:1000]})
            reasons = " ".join(str(x) for x in (rows.get(c) or {}).get("reasons") or [])
            for f in mine:
                stem = Path(str(f["added"].get("location") or "").split(":")[0]).stem
                test = f"tests/test_{stem}.cpp"
                owner = self._owner_of(test, role)
                if (f.get("evidence") == "unit-test" and f"{f['id']}: triaged as fix with evidence unit-test, but no test" in reasons
                        and stem and _proposable(root, test) and test not in said_paths
                        and (owner in self.test_writers + self.impl if owner
                             else not gitwork.matches(test, self.roles[role]["writable"]))):
                    note = (f"{f['id']} 的证据是单元测试，还没有测试写它的编号（TR §4.1）：在 {test} 里加"
                            + (f"。这个文件本来就在{self.title(owner)}的可改范围里，交给它一轮来写" if owner else ""))
                    out.append({"extend": f["id"], "check": c, "role": owner or role, "paths": [test],
                                "note": (note + (also if f is first else ""))[:1000]})
        return out

    def _free(self, root: Path, role: str) -> Any:
        """Whether a path a role named can be proposed to a person for it: a file of the project (_proposable),
        outside the role's scope and not in another role's scope."""
        others = [r["writable"] for k, r in self.roles.items() if k != role and r.get("writable")]

        def free(p: str) -> bool:
            return (_proposable(root, p) and not gitwork.matches(p, self.roles[role]["writable"])
                    and not any(gitwork.matches(p, g) for g in others))
        return free

    def _owner_of(self, p: str, role: str) -> str | None:
        """The other role whose scope has p (the first in the team file), to propose p to. None when no other role's
        scope has it."""
        for k, r in self.roles.items():
            if k != role and r.get("writable") and gitwork.matches(p, r["writable"]):
                return k
        return None

    def _replies(self, role: str) -> list[str]:
        return [str(a.get("reply") or "") for a in self.lane(role)["attempts"]]

    def finding_prefill(self) -> list[dict[str, Any]]:
        """补登发现 (a new finding), filled in for a person to check: for each held check, the files its role said the
        cause is in and it cannot change, in a paragraph of its replies that names the check, and why in its words.
        [] when it named none; nothing changes here."""
        t, wt = self.s["tests"], self.s.get("run_wt")
        held = t.get("held")
        if not held or not wt:
            return []
        rows = {r["name"]: r for r in t.get("checks") or []}
        names = sorted({c["name"] for c in self.team.get("checks") or []} | set(held.get("checks") or []), key=len)
        word = re.compile(rf"(?<![\w/.-])(?:{'|'.join(re.escape(n) for n in names[::-1])})(?![\w/.-])")
        out: list[dict[str, Any]] = []
        for c in held.get("checks") or []:
            owners = [o for o in (rows.get(c) or {}).get("owners") or [] if o in self.impl]
            role = owners[0] if owners else next(iter(self.impl), None)
            if role is None:
                continue
            paths, said = cause_paths(self._replies(role), word, lambda m, c=c: m == c, self._free(Path(wt), role))
            if paths:
                out.append({"check": c, "role": role, "paths": paths, "note": f"{self.title(role)}说：{said}"})
        return out

    async def _go_on_with_findings(self, registered: list[dict[str, Any]]) -> None:
        """The hold ends: each role named gets one more round of each check it was given a finding for (the check's
        limit and the role's own), continuing its session with the findings."""
        t = self.s["tests"]
        t["held"] = None
        if self.ended:
            self._resume()
        rounds, granted = t.setdefault("rounds", {}), t.setdefault("granted", {})
        for c in dict.fromkeys(r["check"] for r in registered):
            granted[c] = int(granted.get(c) or 0) + 1
            rounds[c] = int(rounds.get(c) or 0) + 1
        mgr = self.d.manager()
        for key in [k for k in self.order if any(r["role"] == k for r in registered)]:
            mine = [r for r in registered if r["role"] == key]
            lane = self.lane(key)
            lane["extra"] = int(lane.get("extra") or 0) + 1
            lane["stuck"] = False
            if lane.get("merged_sha"):
                lane["status"] = "merged"
            names = {r["check"] for r in mine}
            failing = [c for c in t["cases"] if c["id"] in names] or [{"id": n, "ac": n, "name": n, "file": ""} for n in names]
            self.say("bounce", "bounce.finding", {"ids": [r["id"] for r in mine], "cases": sorted(names), "r_role": key},
                     role=key, frm="tests", to=key, data={"cases": sorted(names)})
            await self._start(key, "fix", mgr, failing=failing, found=mine)
        self._settle()

    def _found_task(self, key: str, n: int, found: list[dict[str, Any]], caught_up: bool) -> str:
        s, lane = self.s, self.lane(key)
        rows = {r["name"]: r for r in s["tests"].get("checks") or []}
        lines = [self._tag(key, n), "", f"你是开发团队里的「{self.title(key)}」。app 在运行分支 `{s['branch']}` 上跑的检查没过，"
                 "停下来交给人决定。负责人按 TR §4.4 把检查发现的问题补登成分诊里的发现，交给你修："]
        for f in found:
            how = {"fix": "修复", "justify": "说明", "defer": "延后"}.get(f["decision"], f["decision"])
            extra = f"，证据 {f['evidence']}" if f.get("evidence") else ""
            lines.append(f"- {f['id']}（{f['check']} 发现，{how}{extra}）：{f['location']}" + (f"。负责人说：{f['note']}" if f.get("note") else ""))
        lines += ["", "没过的检查和它们的原因："]
        for c in dict.fromkeys(f["check"] for f in found):
            row = rows.get(c) or {}
            reasons = row.get("reasons") or [row.get("summary") or "没过"]
            lines += [f"- {c}：{x}" for x in reasons[:8]]
        added = sorted({g for f in found for g in f.get("added_paths") or []})
        if added:
            lines += ["", f"为了这些发现，你的可写范围加了：{'、'.join(f'`{g}`' for g in added)}。"]
        if any(f.get("evidence") == "unit-test" for f in found):
            ids = "、".join(f["id"] for f in found if f.get("evidence") == "unit-test")
            lines.append(f"{ids} 的证据是单元测试：新加或改的测试要在名字或测试体里写它的编号（TR §4.1）。")
        if caught_up:
            lines += ["", "app 已经把你的分支快进到运行分支的最新提交：测试和别的角色的代码都在你的工作目录里了。"]
        cite = "、".join(f["id"] + (f"（behaviour 为 true，再写事实条目 {'或'.join(f['facts'])}）" if f.get("behaviour") and f.get("facts") else "")
                        for f in found)
        lines += ["", f"在你的工作目录 {lane['worktree']}（分支 {lane['branch']}）里把它们修好。你只能改：{self._writable(key)}。",
                  f"每个提交说明都写它修的发现编号：{cite}（TR §7.2）。",
                  f"每个检查的完整结果在 `{s['tests'].get('results')}/<检查>.json` 和 `<检查>.log`；检查由 app 重跑，你不能改它们。"]
        return "\n".join(lines + self._closing(key))

    async def _integrate(self, key: str) -> None:
        """Commit its leftovers, record what it changed, merge it into the run branch."""
        s, lane, role = self.s, self.lane(key), self.roles[key]
        wt = Path(lane["worktree"])
        if self._traced():  # from the triage's base on, every commit cites its findings: the role commits its own work
            left = await gitwork.uncommitted(wt, role["writable"])
            if left:
                await self._trace_back(key, f"这些改动没有提交：{'、'.join(left[:12])}。检查只看提交了的代码，app 也不替你提交"
                                       "（app 的提交写不出它对应哪个发现）。")
                return
        paths, sha = await gitwork.commit_leftovers(wt, role["writable"], key) if not self._traced() else ([], None)
        if paths:
            lane.setdefault("seen_commits", []).append(sha)
            self.say("committed", "committed.app", {"r_role": key, "n": len(paths)}, role=key)
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
            first = lane.get("first") or {}
            if first.get("status") == "sent_back":
                # Tests first sent it back and this round changed nothing: nothing else looks at a send-back again, and
                # the developers wait for it, so the run would go on with nothing to move (r1119826c). It fails for a
                # person; 重试 sends it back once more (retry: failed -> sent_back).
                first["status"] = "failed"
                self.say("failed", "failed.nochange",
                         {"r_role": key, "n": lane["attempt"], "summary": att.get("summary")}, role=key)
                self._fail_first(key, "测试先行没过，打回以后这一轮没有改动：" + "；".join(first.get("reasons") or [])[:120])
                return
            # Nothing new since its last merge: sending the same failures back again would only spend credits.
            lane.update(status="merged", done_at=self.d.now(), stuck=True)
            self.say("failed", "failed.nochange", {"r_role": key, "n": lane["attempt"], "summary": att.get("summary")}, role=key)
            self.s["needs_test"] = True  # same head, so no new test run: only who to send the failures to is looked at again
            return
        own = self.team.get("ownership")
        if own and own.get("from") == key and lane["attempt"] < self.max_attempts(key):
            err = ownership_problem(wt / own["file"], [k for k in self.order if self.roles[k].get("writable_from")])
            if err:  # the team cannot be dispatched from a wrong ownership file: it goes back before it is merged
                self.say("bounce", "bounce.split", {"r_role": key, "error": err}, role=key, frm="run", to=key)
                await self._start(key, "revise", self.d.manager(), review=f"你写的分工文件 `{own['file']}` 用不了：{err}。"
                                  "按任务说明里的格式改好它（只改这个文件也行），再提交。")
                return
        tri = role.get("triage")
        if tri and lane.get("gate") != "approved":
            err = self._triage_problems(key)
            if err:  # a triage the checks would refuse goes back before it reaches the gate
                if lane["attempt"] >= self.max_attempts(key):
                    self._fail_lane(key, f"分诊文件 {tri['file']} 不合格式，修改的轮数用完了：{err[0]}")
                    return
                self.say("bounce", "bounce.triage_format", {"r_role": key, "error": err[0]}, role=key, frm="run", to=key)
                await self._start(key, "revise", self.d.manager(), review=f"你写的 `{tri['file']}` 不合 checks/README.md 的格式，"
                                  "检查会拒绝它：\n" + "\n".join(f"- {e}" for e in err[:20]) + "\n\n改好再提交。")
                return
        message = f"[run] 合入{self.title(key)}（第 {lane['attempt']} 轮）"
        if self._traced():
            messages = await self._unmerged_messages(key)
            bad = [f"{sha[:12]}「{msg.strip().splitlines()[0][:60] if msg.strip() else ''}」：{why}"
                   for sha, msg in messages for why in [triage_mod.commit_problem(msg, self._approved_triage() or {})] if why]
            if bad and self._hold_unregistered(key, [m for _, m in messages]):
                return
            if bad:
                await self._trace_back(key, "这些提交的说明 checks/trace.sh 不会通过（TR §7.2）：\n" + "\n".join(f"- {b}" for b in bad[:12]))
                return
            tail = triage_mod.trailer([m for _, m in messages], self._approved_triage() or {})
            message += f"\n\n{tail}" if tail else ""
        res = await gitwork.merge(Path(s["run_wt"]), lane["branch"], message)
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
            if (key in self.test_writers and self._approved_triage() is not None
                    and all(self.lane(k)["status"] in ("waiting", "skipped") for k in self.impl if k != key)):
                lane["first"] = {"status": "pending"}  # tests first: the developers wait until they fail on the base
            self.say("merged", "merged", {"r_role": key}, role=key, frm=key, to="run")
            if own and own.get("from") == key:
                await self._resolve_ownership()  # before any role it dispatches is looked at in this same tick
            if role.get("gate") == "human" and lane.get("gate") != "approved":
                if role.get("plan"):
                    self._read_plan(key, role["plan"])
                if role.get("delivery"):
                    self._read_delivery(key, role["delivery"])
                if role.get("questions"):
                    self._read_questions(key, role["questions"])
                if role.get("triage"):
                    self._triage_questions(key)
                if att["kind"] == "discuss":  # it answered and changed its documents: the person looks again
                    self._discussed(key, att, changed=True)
                else:
                    lane["gate"] = "pending"
                    self.say("gate", "gate.wait", {"g_gate": key}, role=key, frm=key, to="person")
            if key in self.impl or key in self.test_writers or any(self.lane(k)["status"] == "merged" for k in self.impl):
                s["needs_test"] = True
            return
        self.say("conflict", "conflict", {"r_role": key, "note": res["note"]}, role=key, frm=key, to="run",
                  data={"paths": [p for p in str(res.get("note") or "").replace("、", ",").split(",") if p.strip()][:12]})
        if lane["attempt"] >= self.max_attempts(key):
            self._fail_lane(key, f"合入冲突，修改的轮数用完了：{res['note']}")
            return
        self.say("bounce", "bounce.conflict", {"r_role": key}, role=key, frm="run", to=key)
        await self._start(key, "conflict", self.d.manager(), conflicts=res["conflicts"] or [res["note"]])

    async def _test_and_bounce(self, mgr: Any) -> None:
        """The app's own test run on the run branch, in the background (the tick goes on while it runs, and looks
        again next time); failing cases go back to the role that owns them. The team file's checks judge the whole
        batch: they start once every implementing role is in."""
        s, t = self.s, self.s["tests"]
        run_wt = Path(s["run_wt"])
        head = await self.run_head()
        checked = bool(self.team.get("checks"))
        if checked and not all((self.lane(k).get("merged_sha") and self.lane(k)["status"] not in ACTIVE)
                               or self.lane(k)["status"] == "failed" for k in self.impl):
            return
        if head != t.get("head"):  # this exact head was tested before a restart: its result stands
            if self._tests is not None and self._tests[0] != head:  # merged meanwhile: that run judges an old head
                self.cancel_tests()
            if self._tests is None:
                self._tests = (head, asyncio.create_task(self._run_tests(run_wt, head)))
                await asyncio.sleep(0)  # one that needs no waiting is done at once
            if not self._tests[1].done():
                return
            task, self._tests = self._tests[1], None
            try:
                wall = task.result()
            except checks.TestsUnavailable as exc:  # without tests nothing can be checked: stop spending credits
                await self.stop(status="failed", code="run.tests_failed", params={"error": str(exc)})
                return
            finally:
                if not checked:
                    await gitwork.reset_clean(run_wt)  # what the tests left behind must not get in a merge's way
            t.update({k: wall[k] for k in ("at", "cases", "passed", "failed", "total")}, head=head,
                     command=wall.get("command") or t.get("command", ""))
            if checked:
                t.update(checks=wall["checks"], results=wall["results"], server_held=wall.get("server_held") or [])
                if wall.get("repair"):  # servers mode: the build server's repair count after this round
                    t["repair"] = wall["repair"]
            t["history"] = (t.get("history", []) + [{"at": wall["at"], "passed": wall["passed"], "failed": wall["failed"]}])[-60:]
            green = bool(t["total"] and not t["failed"])
            red = bool(not green and t["total"] and not t["passed"] and not any(self.lane(k)["status"] == "merged" for k in self.impl))
            # every case's status rides along: a replay of the run turns the test wall cell by cell
            self.say("tests", "tests.score", {"passed": t["passed"], "total": t["total"], "green": green, "red": red},
                     data={"passed": t["passed"], "total": t["total"],
                      "cases": [[c["id"], c["status"]] for c in t["cases"]][:400],
                      **({"phase": "before_bench", "ms": _ms(wall["checks"])} if checked else {})})
        s["needs_test"] = False
        if checked:
            await self._check_bounce(mgr)
            return
        # A test of one role often needs another's work: nobody is sent back until every implementing role is in.
        if not all(self.lane(k).get("merged_sha") or self.lane(k)["status"] == "failed" for k in self.impl):
            return
        for key in self.impl:
            lane = self.lane(key)
            failing = [c for c in t["cases"] if c.get("owner") == key and c["status"] == "fail"]
            if (lane["status"] != "merged" or lane.get("stuck") or not failing or lane["attempt"] >= self.max_attempts(key)
                    or self.ended):
                continue
            self.say("bounce", "bounce.tests", {"cases": [c["ac"] or c["name"] for c in failing[:6]], "more": len(failing) > 6,
                                                "r_role": key}, role=key, frm="tests", to=key,
                      data={"cases": [c["ac"] or c["name"] for c in failing][:24]})
            await self._start(key, "fix", mgr, failing=failing)
        await self._test_writer_bounce(mgr)

    def _run_tests(self, run_wt: Path, head: str) -> Awaitable[dict[str, Any]]:
        """One test run of *head*; the team file's checks get a results directory of their own per round, outside the
        worktrees, and the approved triage (kept beside the repository)."""
        if not self.team.get("checks"):
            return self.d.run_tests(run_wt, self._tested_team())
        t, root = self.s["tests"], Path(self.s["repo"]).parent
        t["round"] = int(t.get("round") or 0) + 1
        return self._round(head=head, results=root / "results" / str(t["round"]), triage=root / TRIAGE_FILE)

    def _round(self, **kw: Any) -> Awaitable[dict[str, Any]]:
        """A round of the team file's checks (kw as checks.run_checks); in servers mode (D17) one the servers held by
        another run cannot run is BLOCKED with that reason, for a person."""
        why = self._servers_busy()
        if why:
            return servers_mod.held_round(self._tested_team(), why, **kw)
        if kw.get("phase", "before_bench") == "before_bench":
            stop = self._repair_stop()
            if stop:  # not one call to the server: a person decides first (D17, TR §5.1)
                return servers_mod.held_round(self._tested_team(), servers_mod.at_bound(*stop), **kw)
            self.s["tests"].pop("repair_go", None)
        return self.d.run_tests(Path(self.s["run_wt"]), self._tested_team(), **kw)

    def _repair_stop(self) -> tuple[int, int] | None:
        """Servers mode: (failures in a row, retries allowed) when the build server's last cross attempt left its
        repair count where one more failure reaches its bound (TR §5.1), so the round waits for a person; None when
        the round may run, or the person's 重试 said it may once."""
        t = self.s["tests"]
        r = t.get("repair") or {}
        n, m = r.get("failures_in_a_row"), r.get("limit_retries")
        if (not servers_mod.on(self.team) or t.get("repair_go") or not isinstance(n, int) or not isinstance(m, int)
                or n < m or not any(c["name"] == "build" and c["when"] == "before_bench" for c in self.team["checks"])):
            return None
        return n, m

    def _reset_command(self) -> str | None:
        """The build server's reset-repair command for a person, once its repair count is past the bound (it refuses
        then); at the bound one attempt is left, and resetting there would wipe the server's count early."""
        r = self.s["tests"].get("repair") or {}
        n, m = r.get("failures_in_a_row"), r.get("limit_retries")
        if servers_mod.on(self.team) and isinstance(n, int) and isinstance(m, int) and n > m:
            return servers_mod.reset_command(self.team, n)
        return None

    def _servers_busy(self) -> str:
        """Servers mode: "" when this run may use the build and bench servers now (it takes them), else why not."""
        if not servers_mod.on(self.team):
            return ""
        try:
            servers_mod.take(servers_mod.setup(self.team), self.rid, self.d.store.root)
        except (servers_mod.Unavailable, OSError) as exc:
            return str(exc)
        return ""

    def cancel_tests(self) -> None:
        """Stop the test run in the background (its checks remove their containers)."""
        if self._tests is not None:
            self._tests[1].cancel()
            self._tests = None
        if self._first is not None:
            self._first[1].cancel()
            self._first = None
        if self._bench is not None:  # cc1.sh killed mid-action leaves the target unknown, for a person (bench/README.md)
            self._bench.cancel()
            self._bench = None

    def _approved_triage(self) -> dict[str, Any] | None:
        """The approved triage beside the run's repository (None: none yet, or the team has no triage)."""
        try:
            data = json.loads((Path(self.s["repo"]).parent / TRIAGE_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) and isinstance(data.get("approved"), dict) else None

    async def _tests_first(self) -> None:
        """Tests first (D6): once the tester is merged, its new tests run on the triage's base commit in the build
        container, in the background; every test for a fix must fail there. One that does not goes back to the tester
        (a round of its own, as any send-back); the developers start only when they all fail."""
        key = next((k for k in self.test_writers if (self.lane(k).get("first") or {}).get("status") == "pending"), None)
        triage = self._approved_triage()
        if key is None or triage is None:
            return
        lane, head = self.lane(key), await self.run_head()
        if self._first is not None and self._first[0] != head:
            self.cancel_tests()
        if self._first is None:
            root = Path(self.s["repo"]).parent
            n = sum(a["kind"] in ("work", "revise", "fix") for a in lane["attempts"])
            busy = self._servers_busy()
            if busy:
                await self._servers_hold("tests_first", busy)
                return
            first = servers_mod.tests_first if servers_mod.on(self.team) else checks.tests_first
            self._first = (head, asyncio.create_task(first(
                Path(self.s["run_wt"]), self.team, base=str(triage.get("base") or ""), head=head, triage=triage,
                results=root / "results" / "tests-first" / str(n))))
            await asyncio.sleep(0)
        if not self._first[1].done():
            return
        task, self._first = self._first[1], None
        try:
            res = task.result()
        except (checks.TestsUnavailable, gitwork.GitError, servers_mod.Unavailable, OSError) as exc:
            if servers_mod.on(self.team) and not isinstance(exc, checks.TestsUnavailable):
                await self._servers_hold("tests_first", str(exc))  # the servers' problem: 重试 tries again (D17)
                return
            if isinstance(exc, OSError):
                raise
            await self.stop(status="failed", code="run.tests_first_failed", params={"error": str(exc)})
            return
        lane["first"] = {"status": "passed" if res["ok"] else "failed", "head": head, "base": res["base"],
                         "tests": res["tests"], "reasons": res["reasons"][:20], "results": res["results"], "at": self.d.now()}
        if res["ok"]:
            self.say("tests", "tests.first_ok", {"r_role": key}, role=key,
                      data={"first": sorted({n for ns in res["tests"].values() for n in ns})[:40]})
            return
        why = "；".join(res["reasons"][:6])
        if lane["attempt"] >= self.max_attempts(key):
            self._fail_first(key, f"测试先行没过，修改的轮数用完了：{why}")
            return
        lane["first"]["status"] = "sent_back"
        self.say("bounce", "bounce.tests_first", {"r_role": key, "why": why}, role=key, frm="tests", to=key)
        await self._start(key, "revise", self.d.manager(), review=self._first_review(res))

    def _fail_first(self, key: str, why: str) -> None:
        """Tests first gave up on test writer *key*: it fails, for a person. With the team file's checks its merge is
        tested only once the developers' are in, and they wait for it: the run is not kept busy for that test run.
        An implementer that does have work to test writes the flag again as it merges (``_integrate``)."""
        self.s["needs_test"] = False
        if self._tests is not None:  # a test run of a head nothing waits for now: it would outlive the run
            self.cancel_tests()
        self._fail_lane(key, why)

    def _hold_failing(self) -> bool:
        """The team's checks: a last round that still fails, with nothing holding it, holds the run for a person
        (each failing check as no longer the owner's to change, a BLOCKED one as not judged). True when held now."""
        t = self.s["tests"]
        rows = [r for r in t.get("checks") or [] if r["verdict"] != "PASS"]
        if not (self.team.get("checks") and t.get("failed") and rows and not t.get("held")):
            return False
        what = {"FAIL": {"code": "held.owner"}, "USAGE": {"code": "held.usage"}}
        items = [{"check": r["name"], "what": what.get(r["verdict"], {"code": "held.blocked"}),
                  "reason": (r["reasons"] or [r["summary"]])[0]} for r in rows]
        reason = messages.clean({"items": items}) or {}
        t["held"] = {"checks": [r["name"] for r in rows], "why": self.msg("checks.held", reason)[:300],
                     "code": "checks.held", "params": reason, "reasons": _held_reasons(rows)}
        self.say("failed", "failed.checks", {"why": {"code": "checks.held", "params": reason}},
                 data={"checks": t["held"]["checks"]})
        return True

    def servers_retry(self) -> str | None:
        """What 重试 asks the servers again for (D17): ``checks`` or ``tests_first``; None when 重试 is not that."""
        if not self.ended:
            return None
        return self.s.get("servers_held") or ("checks" if self._servers_round_held() else None)

    def _servers_round_held(self) -> bool:
        """Servers mode (D17): the checks are held because a server refused or failed a check, and the others held
        could not judge (BLOCKED, as size is without a build): nothing for a role or a finding, 重试 runs the round."""
        t = self.s["tests"]
        h, mine = t.get("held") or {}, set(t.get("server_held") or [])
        order = [r["name"] for r in t.get("checks") or []]
        rows = {r["name"]: r for r in t.get("checks") or []}
        names = h.get("checks") or []
        first = min((order.index(n) for n in mine if n in order), default=len(order))
        # a BLOCKED check after the first one a server refused could not judge for want of it (size without a build)
        return bool(servers_mod.on(self.team) and names and not h.get("unregistered") and mine & set(names)
                    and all(n in mine or ((rows.get(n) or {}).get("verdict") == "BLOCKED" and n in order
                                          and order.index(n) > first) for n in names))

    async def _servers_hold(self, what: str, why: str) -> None:
        """Servers mode (D17): the servers could not do *what* (the tests first, a round of checks); the run ends for a
        person, and 重试 tries it again."""
        self.s["servers_held"] = what
        await self.stop(status="failed", code="run.servers_held", params={"error": why[:300]})

    def _finale_due(self) -> bool:
        """Every role is in, the reviewer let it through, and the latest round of the checks before the bench passed
        on what is merged: the bench actions come next (D3), then the checks after them."""
        t = self.s["tests"]
        return (bool(self.team.get("bench")) and not self.ended and not self.s["needs_test"]
                and all(self._settled(k) for k in self.order)
                and not any(self.lane(k)["status"] in ACTIVE for k in self.order)
                and t["total"] > 0 and not t["failed"] and not t.get("held"))

    async def _bench_step(self, mgr: Any) -> None:
        """The bench, for the build the checks passed: doctor.sh and what the bench needs (D10), deploy, replay, then
        the checks after the bench on the run directory and the baseline, each in the background. Each bench action
        waits for a person at the operator console (D3); whatever stops one goes to a person (``held``)."""
        if not self._finale_due():
            return
        t, root = self.s["tests"], Path(self.s["repo"]).parent
        b = self.s.get("bench")
        if b is None or b["head"] != t["head"]:  # a new build: the bench starts over with it
            n = int((b or {}).get("n") or 0) + 1
            artifact = Path(t["results"]) / bench_mod.ARTIFACT
            run_dir: str | None = str(root / "bench" / f"run-{n}")
            if servers_mod.on(self.team):  # the bench server deploys what the build server published (D17)
                try:
                    artifact = servers_mod.setup(self.team).build_state / "results" / bench_mod.ARTIFACT
                except servers_mod.Unavailable:
                    pass
                run_dir = None  # the bench server's runs/run-<n>, known once the replay is done
            b = self.s["bench"] = {"head": t["head"], "n": n, "step": "doctor", "running": None, "held": None,
                                   "doctor": (b or {}).get("doctor"), "actions": list((b or {}).get("actions") or []),
                                   "artifact": str(artifact), "run_dir": run_dir, "after": None}
            self.say("bench", "bench.go", {"n": n})
        if b["held"] or b["step"] == "done":
            return
        if self._bench is None:
            if b["running"]:  # it was going when the app stopped: what it did on the bench is a person's to check
                b["running"] = None
                self._bench_hold("hold.restart", {"step": b["step"]})
                return
            busy = self._servers_busy() if b["step"] != "doctor" else ""
            if busy:
                self._bench_hold("hold.servers", {"why": busy})
                return
            if b["step"] == "deploy" and not servers_mod.on(self.team) and not Path(b["artifact"]).is_file():
                self._bench_hold("hold.no_artifact", {"artifact": b["artifact"]})
                return
            b["running"] = b["step"]
            self._bench = asyncio.create_task(self._bench_task(b))
            await self.save()
            await asyncio.sleep(0)
        if not self._bench.done():
            return
        task, self._bench = self._bench, None
        b["running"] = None
        try:
            res = task.result()
        except checks.TestsUnavailable as exc:
            await self.stop(status="failed", code="run.after_bench_failed", params={"error": str(exc)})
            return
        await self._bench_done(b, res, mgr)

    def _bench_task(self, b: dict[str, Any]) -> Awaitable[Any]:
        spec, root, step = self.team["bench"], Path(self.s["repo"]).parent, b["step"]
        log = root / "bench" / f"{step}-{b['n']}.log"
        if step == "doctor":
            return bench_mod.doctor(spec["doctor"], log)
        if step == "rerun":
            return self._rerun(b)
        if step == "after":
            return self._round(head=b["head"], results=root / "results" / f"after-{b['n']}", phase="after_bench",
                               triage=root / TRIAGE_FILE, run=Path(b["run_dir"]) if b["run_dir"] else None,
                               baseline=Path(spec["baseline"]).expanduser())
        if servers_mod.on(self.team):  # deploy and replay through the bench server (D17)
            return servers_mod.physical(self.team, root, step, f"{step} {b['n']}")
        cmd = bench_mod.argv(spec[step], {"artifact": b["artifact"], "run": b["run_dir"]})
        return bench_mod.run(cmd, log, bench_mod.ACTION_TIMEOUT_S, env={"CC1_REQUESTER": f"{APP_NAME} {self.rid}"})

    async def _bench_done(self, b: dict[str, Any], res: Any, mgr: Any) -> None:
        step = b["step"]
        if step == "doctor":
            b["doctor"] = res
            gaps = bench_mod.missing(self.team["bench"], res, bench_mod.read_state())
            if gaps:
                self._bench_hold("hold.not_ready", {"why": "；".join(g["why"] for g in gaps)}, [g["command"] for g in gaps if g["command"]])
                return
            b["step"] = "deploy"
            self.say("bench", "bench.deploy", {"artifact": Path(b["artifact"]).name})
        elif step in ("deploy", "replay") and servers_mod.on(self.team):
            kind, why, out = res["kind"], res["why"], res["out"]
            if kind == "ok" and step == "deploy" and out.get("commit") != b["head"]:
                kind, why = "failed", f"bench 服务器部署的是 {str(out.get('commit'))[:12]} 的构建，不是这一轮的 {b['head'][:12]}"
            if kind == "ok" and step == "replay":
                if not out.get("result") or not out.get("run"):
                    kind, why = "failed", "回放结束了，但 bench 服务器的运行目录里没有 run-result.json"
                else:
                    with contextlib.suppress(servers_mod.Unavailable):
                        b["run_dir"] = str(servers_mod.setup(self.team).bench_state / "runs" / str(out["run"]))
            b["actions"].append({"action": step, "at": self.d.now(), "outcome": kind, "why": why, "rc": None,
                                 **{k: out[k] for k in ("request", "digest") if out.get(k)}})
            if kind != "ok":
                self._bench_hold("hold.deploy" if step == "deploy" else "hold.replay", {"kind": kind, "why": why})
                return
            b["step"] = "replay" if step == "deploy" else "after"
            self.say("bench", "bench.replay" if step == "deploy" else "bench.replayed",
                     {"run_dir": b["run_dir"]} if step != "deploy" else None)
        elif step in ("deploy", "replay"):
            rc, tail = res
            kind, why = bench_mod.outcome(rc, tail, bench_mod.read_state()["target"])
            if kind == "ok" and step == "replay" and not (Path(b["run_dir"]) / "run-result.json").is_file():
                kind, why = "failed", f"回放结束了，但运行目录 {b['run_dir']} 里没有 run-result.json"
            b["actions"].append({"action": step, "at": self.d.now(), "outcome": kind, "why": why, "rc": rc})
            if kind != "ok":
                self._bench_hold("hold.deploy" if step == "deploy" else "hold.replay", {"kind": kind, "why": why})
                return
            b["step"] = "replay" if step == "deploy" else "after"
            self.say("bench", "bench.replay" if step == "deploy" else "bench.replayed", {"run_dir": b["run_dir"]} if step != "deploy" else None)
        elif step == "after":
            b["after"] = {k: res[k] for k in ("at", "passed", "failed", "total", "checks", "results")}
            self.say("tests", "tests.after", {"passed": res["passed"], "total": res["total"]}, data={"checks": [[r["name"], r["verdict"]] for r in res["checks"]],
                                                                               "phase": "after_bench", "ms": _ms(res["checks"])})
            if not res["failed"]:
                if any(c["when"] == "release" for c in self.team["checks"]):
                    b["step"] = "rerun"
                    self.say("bench", "bench.rerun", data={"step": "rerun"})
                else:
                    b["step"] = "done"
                return
            res["cases"] = [{**c, "results": res["results"]} for c in res["cases"]]
            await self._check_bounce(mgr, res)
            if res.get("held"):
                b["after"]["held"] = res["held"]
                self._bench_hold("hold.after_bench", {"why": res["held"]["why"]})
                return
            for k in self.order:  # the fix changes what the reviewer let through: it looks again before the bench
                if not self.roles[k]["writable"] and self.lane(k)["status"] == "done":
                    self.lane(k).update(status="waiting", passed=False)

        elif step == "rerun":
            rerun = self.s["rerun"] = res
            self.say("tests", "tests.rerun", {"verdict": rerun["release"]["verdict"], "differs": [d["name"] for d in rerun["differs"]]},
                     data={"checks": [[r["name"], r["verdict"]] for r in rerun["checks"]], "differs": rerun["differs"], "phase": "rerun"})
            if rerun["release"]["verdict"] != "PASS":
                rel = rerun["release"]  # BLOCKED: release.sh, or the build server (D17), gave no verdict
                self._bench_hold("hold.release", {"why": "；".join(rel["reasons"][:3] or [rel["summary"]]),
                                                  "blocked": rel["verdict"] == "BLOCKED" or None})
                return
            b["step"] = "done"

    async def _rerun(self, b: dict[str, Any]) -> dict[str, Any]:
        """D9: every check again on the final commit, in a new results directory (each check builds from ``git archive``
        into ``<results>/work``, so nothing of an earlier round is used), on the run directory of the last replay
        (release.sh asks that the after-bench checks judged the build it checked: a fresh replay would need another
        deploy); then release.sh on it all and the evidence page. Which checks' verdict differs from the run's last."""
        root, spec = Path(self.s["repo"]).parent, self.team["bench"]
        results = root / "results" / "rerun"
        await asyncio.to_thread(shutil.rmtree, results, True)
        results.mkdir(parents=True)
        common = {"head": b["head"], "results": results, "triage": root / TRIAGE_FILE, "run": Path(b["run_dir"]),
                  "baseline": Path(spec["baseline"]).expanduser()}
        rows = []
        for phase in ("before_bench", "after_bench"):
            rows += (await self.d.run_tests(Path(self.s["run_wt"]), self._tested_team(), phase=phase, **common))["checks"]
        limits = {c["name"]: c["max_rounds"] for c in self.team["checks"]}
        (results / "repair-rounds.json").write_text(json.dumps(  # TR §5.2: the limits in use, with the run
            {"rounds": self.s["tests"].get("rounds") or {}, "limits": limits,
             "granted": self.s["tests"].get("granted") or {}}, ensure_ascii=False) + "\n", encoding="utf-8")
        release = (await self.d.run_tests(Path(self.s["run_wt"]), self._tested_team(), phase="release", **common))["checks"]
        page = None
        if self.team.get("evidence_page"):
            make_page = servers_mod.evidence_page if servers_mod.on(self.team) else checks.evidence_page
            page = await make_page(self.team["evidence_page"], self.team, results, root / TRIAGE_FILE)
        last = {r["name"]: r["verdict"] for r in (self.s["tests"].get("checks") or []) + ((b.get("after") or {}).get("checks") or [])}
        now = {r["name"]: r["verdict"] for r in rows}
        rel = release[0] if release else {"verdict": "BLOCKED", "reasons": ["团队配置里没有 release 检查"], "summary": ""}
        return {"at": self.d.now(), "head": b["head"], "results": str(results),
                "checks": [{k: r[k] for k in ("name", "verdict", "tier", "summary", "reasons")} for r in rows],
                "differs": [{"name": n, "was": last.get(n), "now": now.get(n)} for n in dict.fromkeys([*last, *now])
                            if last.get(n) != now.get(n)],
                "release": {k: rel[k] for k in ("verdict", "summary", "reasons")}, "evidence": str(page) if page else None}

    def _bench_hold(self, code: str, params: dict[str, Any], commands: list[str] | None = None) -> None:
        """The bench waits for a person: the reason, and the commands they run for it (D10). No automatic retry."""
        b = self.s["bench"]
        params = messages.clean(params) or {}
        b["held"] = {"step": b["step"], "why": " ".join(self.msg(code, params).split())[:400], "code": code, "params": params,
                     "commands": commands or [], "at": self.d.now()}
        self.say("failed", "failed.bench", {"why": {"code": code, "params": params}}, data={"commands": b["held"]["commands"]})

    def _first_review(self, res: dict[str, Any]) -> str:
        return "\n".join([f"app 在需求提交 `{res['base'][:12]}` 的代码上跑了你的新测试（构建容器里、和 unit.sh 一样构建，"
                          "不带消毒器）。TR §4.1 要求测试在修复之前失败，这些不满足：", ""]
                         + [f"- {r}" for r in res["reasons"][:15]]
                         + ["", "改测试：断言 VSTATD-IF 规定的正确行为，让它在需求提交上失败、修好以后通过；测试名或测试体里写发现编号。"
                            f"每次跑的结果在 `{res['results']}`。"])

    async def _check_bounce(self, mgr: Any, wall: dict[str, Any] | None = None) -> None:
        """A round of the team file's checks (the test wall, or *wall*: the checks after the bench): each failure back
        to the role it was attributed to, one fix round per failing check; a check that could not judge, a
        misconfigured one, or one out of its rounds stops the run for a person (D7). A check that could not judge
        because another failed (no build to measure) waits for that fix."""
        t = wall if wall is not None else self.s["tests"]
        if wall is None and (t.get("held") or {}).get("unregistered"):
            return  # held for a person to register findings (D15): another round of the same checks changes nothing
        spec = {c["name"]: c for c in self.team["checks"]}
        rows = t.get("checks") or []
        failing = [r for r in rows if r["verdict"] == "FAIL"]
        rounds = self.s["tests"].setdefault("rounds", {})
        granted = self.s["tests"].get("granted") or {}  # rounds a person gave a check with a finding (TR §4.4)
        held: list[tuple[dict[str, Any], dict[str, Any]]] = [(r, {"code": "held.usage"}) for r in rows if r["verdict"] == "USAGE"]
        if not failing:
            held += [(r, {"code": "held.blocked"}) for r in rows if r["verdict"] == "BLOCKED"]
        for r in failing:
            if rounds.get(r["name"], 0) >= spec[r["name"]]["max_rounds"] + int(granted.get(r["name"]) or 0):
                held.append((r, {"code": "held.rounds", "params": {"n": rounds.get(r["name"], 0)}}))
            elif any(o not in self.roles or self.lane(o)["status"] != "merged" or self.lane(o).get("stuck")
                     or self.lane(o)["attempt"] >= self.max_attempts(o) for o in r["owners"]):  # out of its rounds
                held.append((r, {"code": "held.owner"}))
        owners = {o for r in failing for o in r["owners"]}
        if held:
            reason = messages.clean({"items": [{"check": r["name"], "what": what, "reason": (r["reasons"] or [r["summary"]])[0]}
                                               for r, what in held]}) or {}
            why = self.msg("checks.held", reason)[:300]
            t["held"] = {"checks": [r["name"] for r, _ in held], "why": why, "code": "checks.held", "params": reason,
                         "reasons": _held_reasons(r for r, _ in held)}
            server = wall is None and self._servers_round_held()
            self.s["servers_held"] = "checks" if server else None  # the servers' problem: 重试 runs the round again
            reset = self._reset_command() if server else None
            if reset:  # at the build server's bound: what the person runs before 重试
                t["held"]["commands"] = [reset]
            self.say("failed", "failed.checks", {"why": {"code": "checks.held", "params": reason}},
                     data={"checks": t["held"]["checks"]})
            return
        t["held"] = None
        if self.s.get("servers_held") == "checks":
            self.s["servers_held"] = None
        for r in failing:
            rounds[r["name"]] = rounds.get(r["name"], 0) + 1
        for key in [k for k in self.order if k in owners]:
            cases = [c for c in t["cases"] if c.get("owner") == key and c["status"] == "fail"]
            self.say("bounce", "bounce.checks", {"cases": [c["ac"] for c in cases], "r_role": key}, role=key, frm="tests", to=key,
                      data={"cases": [c["ac"] for c in cases]})
            await self._start(key, "fix", mgr, failing=cases)

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
            self.say("bounce", "bounce.test_writer", {"cases": [c["ac"] or c["name"] for c in failing[:6]], "more": len(failing) > 6,
                                                      "r_owners": owners, "r_role": writer},
                      role=writer, frm="tests", to=writer, data={"cases": [c["ac"] or c["name"] for c in failing][:24]})
            await self._start(writer, "fix", mgr, failing=failing, review=said)

    async def _review_done(self, key: str, att: dict[str, Any]) -> None:
        s, lane = self.s, self.lane(key)
        # whatever the reviewer wrote in its snapshot is a violation
        _, committed = await asyncio.gather(self._stats(key), gitwork.committed_paths(Path(lane["worktree"]), lane["fork"]))
        self._violations(key, committed)
        lane.update(status="done", done_at=self.d.now())
        summary = att.get("summary") or ""
        self.say("review", "review", {"summary": summary}, role=key)
        if review_verdict(summary) == "changes":
            rounds = int(s.get("review_rounds") or 0)
            limit = int(self.team.get("defaults", {}).get("max_review_rounds", 0) or 0)
            if rounds < limit and not self.ended and await self._review_bounce(key, att.get("reply") or ""):
                return
            if self.roles[key].get("gate") == "human" and not self.ended:
                # its rounds are used up (or it names nobody): the person at its gate decides, the run does not end here
                lane.update(gate="pending", overrule=True, passed=False)
                s["verdict"] = f"审查打回 {rounds} 轮后仍要改" if rounds else "审查要改"
                self.say("gate", "gate.overrule", {"g_gate": key, "rounds": rounds}, role=key, frm=key, to="person")
                return
            self._end("failed", "run.review_rounds", {"rounds": rounds})
        else:
            lane["passed"] = True
            if self.roles[key].get("gate") == "human" and lane.get("gate") != "approved":
                lane["gate"] = "pending"  # a person signs this review off before anything after it starts
                self.say("gate", "gate.wait", {"g_gate": key}, role=key, frm=key, to="person")
            first = re.split(r"[。；;\n]", summary, maxsplit=1)[0].strip() if summary else ""
            s["verdict"] = f"审查说{first[:30]}" if first else "审查没有给结论"
            if lane.get("gate") == "pending" or any(self.lane(k)["status"] not in ("merged", "done", "skipped") for k in self._after(key)):
                return  # a person's gate, or a role after the review: _settle ends the run once they are done
            if self.team.get("bench"):
                return  # the bench actions and the checks after them come next (_bench_step); _settle ends the run
            red = int(s["tests"].get("failed") or 0)
            if red and self._hold_failing():  # the team's checks still fail: held for a person, not done
                self._end("failed", "run.held", {"why": {"code": s["tests"]["held"]["code"],
                                                         "params": s["tests"]["held"].get("params")}})
                return
            if red:  # done, but not green: said as it is, the person decides
                self._end("done", "run.done_red", {"summary": summary[:20], "red": red})
            else:
                self._end("done", "run.done_ok" if review_verdict(summary) == "ok" else "run.done")

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
            await self.stop(status="failed", code="run.ownership_failed", params={"file": own["file"], "error": err})
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        now, assigned = self.d.now(), {}
        for k in dynamic:
            globs = [g for g in (data["roles"].get(k) or []) if ok_glob(g)]
            if globs:
                self.roles[k]["writable"] = assigned[k] = globs
            else:
                self.lane(k).update(status="skipped", done_at=now)
                self.say("skipped", "skipped.unneeded", {"r_role": k}, role=k)
        areas = {str(a): r for a, r in (data.get("test_areas") or {}).items() if r in assigned}
        if areas:
            self.team["test_owners"] = [{"glob": f"tests/**/*-{a}-*", "role": r} for a, r in areas.items()]
        s["ownership"] = {"roles": assigned, "test_areas": areas}
        self.say("ownership", "ownership", {"r_from": own["from"], "assigned": [{"r_role": k, "files": list(g)} for k, g in assigned.items()]},
                 data={"roles": assigned})

    async def gate(self, key: str, decision: str, note: str = "", delivery: Any = None, answers: Any = None,
                   risk: Any = None, by: str = "") -> bool:
        """A person's answer at a gate: approve (the roles after it start), send it back with what to change, or 讨论
        (it answers, and changes its documents if it has to; the gate stays). *delivery*: the 交付标签 as the person
        confirms them when approving the gate of the role that proposes them (fields left out keep the proposal's).
        *answers*: the person's choice for each question the role put to them (``{id: {"choice": "A", "text": ""}}``;
        a question left out takes the role's recommendation). *risk*: with 退回, what the send-back kept from going live
        (``{what, amount}``, amount in yuan): kept on the run and on the 签字单. *by*: who approves (the approved
        triage records it)."""
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
                self.say("talk", "talk.gate", {"g_gate": key, "r_role": key, "note": note}, role=key, frm="person", to=key)
                await self._start(key, "discuss", self.d.manager(), review=note.strip())
                self._settle()
                await self.save()
                return True
            if decision == "approve":
                if lane.get("overrule") and not note.strip():
                    return False  # overruling a review that still says 要改 takes a reason
                if role.get("triage"):
                    changed = await self._approve_triage(key, self._answers_for(key, answers), by.strip() or "负责人")
                    if changed:  # not as proposed: the triage role writes the person's decisions in, the gate comes again
                        lane["gate"] = None
                        said = "\n".join(f"- {a['id']}「{a['q']}」：" + (f"其他：{a['text']}" if a["choice"] == "other" else
                                         f"{a['choice']}. {a['option']}" + (f"（补充：{a['text']}）" if a["text"] else ""))
                                         for a in changed)
                        asked = {q["id"]: q for q in (self.s.get("questions") or {}).get(key) or []}
                        self.say("bounce", "bounce.triage_changed", {"g_gate": key, "n": len(changed), "r_role": key}, role=key,
                                 frm="person", to=key, data={"answers": [a["id"] for a in changed], "justified": [
                                      a["id"] for a in changed if asked.get(a["id"], {}).get("decision") == "justify"]})
                        await self._start(key, "revise", self.d.manager(), review=(
                            f"人在{label}关卡上不同意这些建议，按人的决定改 `{role['triage']['file']}` 和分诊文档（改成修复的补 evidence、"
                            "behaviour，涉及行为的补 cites 和 facts；不加入的删掉那一条），再提交：\n" + said
                            + (f"\n\n人的意见：{note}" if note else "")))
                        self._settle()
                        await self.save()
                        return True
                lane.update(gate="approved", gate_note=note or None)
                if note:
                    self.s.setdefault("gate_notes", {})[key] = note
                picked = self._answers_for(key, answers)
                said = None  # the decisions at the gate, as a message (the board says them in either language)
                if picked:
                    self.s.setdefault("answers", {})[key] = picked
                    note_text = note
                    said = [{"id": a["id"], "choice": a["choice"] if a["choice"] != "other" else {"code": "choice.other"},
                             "differs": bool(a["differs"])} for a in picked]
                    # what goes on to the roles after it: the message without its 「人批准了<关卡>：」 (a label may hold a ：)
                    said_all, head = self.msg("approved.answers", {"g_gate": key, "note": note_text, "answers": said}), f"人批准了{self.gate_label(key)}："
                    note = said_all[len(head):] if said_all.startswith(head) else said_all
                    lane["gate_note"] = note_text or None
                if lane.pop("overrule", None):
                    lane["passed"] = True
                    last = lane["attempts"][-1] if lane["attempts"] else {}
                    self.s["overruled"] = {"role": key, "note": note, "review": str(last.get("summary") or "")}
                    self.s["verdict"] = "人推翻了审查结论放行"
                    self.say("approved", "approved.overrule", {"g_gate": key, "note": note}, role=key, frm="person", to=key)
                else:
                    if said:
                        self.say("approved", "approved.answers", {"g_gate": key, "note": note_text, "answers": said},
                                 role=key, frm="person", to=key)
                    else:
                        self.say("approved", "approved", {"g_gate": key, "note": note}, role=key, frm="person", to=key)
                if role.get("delivery"):  # the person confirms the 交付标签 the role proposed (or changes them)
                    self.s["delivery"] = delivery_mod.clean(delivery, self.delivery())
                    self.say("plan", "plan.delivery_confirmed", {"delivery": delivery_mod.label(self.s["delivery"])}, role=key,
                             data={"delivery": self.s["delivery"]})
                if role.get("plan"):  # the roles the approved proposal leaves out sit this run out
                    for k, why in (self.s.get("plan_skip") or {}).items():
                        if k in self.roles and self.lane(k)["status"] == "waiting":
                            self._sit_out(k, f"这次用不到：{why}", f"这次用不到（{self.title(key)}提议，人在{label}关卡批准）：{why}")
                if self.s.get("gate_notes") or self.s.get("answers"):
                    await self._record_decisions()
                if self.s.get("triage") and not self._traced() and key == self._build_start:
                    await self._set_base()
            elif not role["writable"] and lane.get("overrule") and (review_targets(note, self.team["roles"])
                                                                     or review_targets(self.overrule_review(key), self.team["roles"])):
                # the review still says 要改: one more round as it says, with what the person adds (the person's note wins)
                review = self.overrule_review(key)
                lane.update(gate=None, overrule=False)
                if note:
                    self.s["review_note"] = note
                caught = self._keep_risk(key, label, clean_risk(risk), note)
                self.say("bounce", "bounce.gate_review", {"g_gate": key, "note": note}, role=key, frm="person", to=key, data=caught)
                await self._review_bounce(key, review, only=review_targets(note, self.team["roles"]) or None)
            elif not role["writable"]:  # a review gate: the person sends work back to the members the note names
                targets = review_targets(note, self.team["roles"])
                if not targets:
                    return False  # 退回 has to say to whom (打回：前端开发 #2 …)
                lane.update(gate=None, passed=False)
                self.s["human_review"] = note
                caught = self._keep_risk(key, label, clean_risk(risk), note)
                self.say("bounce", "bounce.gate", {"g_gate": key, "note": note}, role=key, frm="person", to=key, data=caught)
                lane["status"] = "waiting"
                mgr = self.d.manager()
                for t in targets:
                    self.say("bounce", "bounce.by_person", {"r_role": t}, role=t, frm=key, to=t)
                    await self._start(t, "review", mgr, review=HUMAN_MARK + note)
            else:
                lane["gate"] = None
                caught = self._keep_risk(key, label, clean_risk(risk), note)
                self.say("bounce", "bounce.rejected", {"g_gate": key, "note": note}, role=key, frm="person", to=key, data=caught)
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
            self.say("plan", "plan.no_split", {"r_role": key, "file": rel}, role=key)
            return
        skip = data.get("skip") if isinstance(data, dict) else None
        drop = {k: " ".join(str(v).split())[:60] or "没写理由" for k, v in (skip.items() if isinstance(skip, dict) else [])
                if k in self.roles and self.roles[k].get("optional") and self.lane(k)["status"] == "waiting"}
        plan = {k: " ".join(str(v).split())[:40] for k, v in (data.items() if isinstance(data, dict) else [])
                if k in self.roles and k != key and k not in drop and isinstance(v, str) and v.strip()}
        self.s["plan"], self.s["plan_skip"] = plan, drop
        if plan or drop:
            self.say("plan", "plan.split", {"r_role": key, "plan": [{"r_role": k, "what": v} for k, v in plan.items()],
                                            "skip": [{"r_role": k, "why": v} for k, v in drop.items()]},
                     role=key, data={"plan": plan, "skip": drop})

    def _read_delivery(self, key: str, rel: str) -> None:
        """交付标签: the gated role's proposal (``{name, kind, size, line, why}``, a JSON file in the run branch), shown at
        its gate for the person to confirm. No file, or a wrong one: the team file's defaults stand."""
        try:
            data = json.loads((Path(self.s["run_wt"]) / rel).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        if not isinstance(data, dict):
            self.say("plan", "plan.no_delivery", {"r_role": key, "file": rel, "delivery": delivery_mod.label(self.delivery())}, role=key)
            return
        self.s["delivery_proposed"] = delivery_mod.clean(data, self._delivery_defaults())
        self.say("plan", "plan.delivery", {"r_role": key, "delivery": delivery_mod.label(self.s["delivery_proposed"])}, role=key,
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
            self.say("plan", "plan.questions", {"r_role": key, "n": len(out)}, role=key, data={"questions": len(out)})

    def _read_triage(self, key: str, where: Path) -> tuple[dict[str, Any] | None, list[str]]:
        tri = self.roles[key]["triage"]
        try:
            data = json.loads((where / tri["file"]).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None, [f"没有 {tri['file']}"]
        except (OSError, ValueError) as exc:
            return None, [f"{tri['file']} 读不了或不是 JSON：{exc}"[:200]]
        return data, triage_mod.problems(data, Path(tri["knowledge"]))

    def _triage_problems(self, key: str) -> list[str]:
        return self._read_triage(key, Path(self.lane(key)["worktree"]))[1]

    def _triage_questions(self, key: str) -> None:
        """The triage gate's questions (D4), from the merged triage and the backlog; the rest is in its document."""
        data, _ = self._read_triage(key, Path(self.s["run_wt"]))
        rows = triage_mod.backlog(Path(self.roles[key]["triage"]["knowledge"]))
        out = triage_mod.questions(data, rows)
        self.s.setdefault("questions", {})[key] = out
        self.s["triage_listed"] = triage_mod.listed(data, rows)
        self.say("plan", "plan.triage", {"r_role": key, "n": len(out), "listed": len(self.s["triage_listed"])},
                 role=key, data={"questions": len(out)})
        # the gate warns about what a refactored function leaves stranded, while a person can still act on it
        work_item = str(self.s.get("requirement") or self.team.get("work_item") or "")  # this run's, if edited
        later = triage_mod.later_in_refactor(data, rows, work_item)
        if later:  # only the backlog, before a run, can change these
            self.say("plan", "plan.triage_refactor", {"items": later, "backlog": triage_mod.BACKLOG_FILE}, role=key,
                     data={"later_in_refactor": [x["id"] for x in later]})
        deferred = triage_mod.defer_in_refactor(data, rows, work_item)
        if deferred:  # these the person can change here, at this gate, on each finding's own question
            self.say("plan", "plan.triage_refactor_defer", {"items": deferred}, role=key,
                     data={"defer_in_refactor": [x["id"] for x in deferred]})

    async def _approve_triage(self, key: str, picked: list[dict[str, Any]], by: str) -> list[dict[str, Any]]:
        """The person's answers at the triage gate: those that take a proposal as it is (A) leave it; the others
        (another decision, or the person's own words) are the triage role's to write in, since a decision needs the
        fields only the role can give (a fix's evidence and behaviour, a deferral's condition): returned, and the
        triage goes back. All A: the triage is written with ``approved`` beside the repository, with its record."""
        changed = [a for a in picked if a["choice"] != triage_mod.AGREE]
        if changed:
            return changed
        data, _ = self._read_triage(key, Path(self.s["run_wt"]))
        data = {k: v for k, v in data.items() if k != "approved"}
        data["approved"] = {"by": by, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.d.now()))}
        path = Path(self.s["repo"]).parent / TRIAGE_FILE
        digest = await asyncio.to_thread(triage_mod.write, path, data)
        self.s["triage"] = {"path": str(path), "sha256": digest, "base": data["base"], "base_set": False,
                            "approved": data["approved"]}
        self.say("plan", "plan.triage_approved", {"by": by, "file": TRIAGE_FILE, "sha": digest[:12]}, role=key)
        return []

    async def _set_base(self) -> None:
        """D13: the triage's base is the run branch once the build-start gate is approved and its decisions committed:
        every commit after it is a role's work or the app's merge of it, and cites a finding."""
        tri = self.s.get("triage")
        path = Path(tri["path"])
        data = json.loads(path.read_text(encoding="utf-8"))
        self._head = None
        data["base"] = await self.run_head()
        tri.update(base=data["base"], sha256=await asyncio.to_thread(triage_mod.write, path, data), base_set=True)
        self.say("plan", "plan.triage_base", {"base": data["base"][:12]})

    def _traced(self) -> bool:
        return bool((self.s.get("triage") or {}).get("base_set"))

    async def _unmerged_messages(self, key: str) -> list[tuple[str, str]]:
        """(sha, message) of each commit of *key*'s branch not yet on the run branch, oldest first."""
        _, out, _ = await gitwork.git(Path(self.s["run_wt"]), "log", "--reverse", "--format=%H%x1f%B%x1e",
                                      f"HEAD..{self.lane(key)['branch']}", locks=False)
        return [tuple(rec.strip("\n").split("\x1f", 1)) for rec in out.split("\x1e") if "\x1f" in rec]

    def _hold_unregistered(self, key: str, texts: list[str]) -> bool:
        """A role sent back by the checks fixed what they found and cited finding IDs the triage does not have (a
        defect the backlog lacks, TR §4.4): the run is held for a person to register them (D15), and the role spends
        no round on rewriting its commit messages. True when held; False when the commits fail trace.sh otherwise."""
        t, att = self.s["tests"], self.lane(key)["attempts"][-1] if self.lane(key)["attempts"] else {}
        triage = self._approved_triage() or {}
        known = set(triage_mod.decided(triage))
        bad = [m for m in texts if triage_mod.commit_problem(m, triage)]
        unknown = sorted({i for m in bad for i in triage_mod.FINDING_ID.findall(m) if i not in known})
        failing = [c for c in t.get("cases") or [] if c.get("owner") == key and c["status"] == "fail"]
        if att.get("kind") != "fix" or not failing or not unknown or not all(
                set(triage_mod.FINDING_ID.findall(m)) - known for m in bad):
            return False
        rows = {r["name"]: r for r in t.get("checks") or []}
        names = list(dict.fromkeys(c["ac"] for c in failing))
        what = {"code": "held.unregistered", "params": {"r_role": key, "ids": unknown}}
        first = {n: ((rows.get(n) or {}).get("reasons") or [""])[0] for n in names}
        reason = messages.clean({"items": [{"check": n, "what": what, "reason": first[n]} for n in names]})
        t["held"] = {"checks": names, "why": self.msg("checks.held", reason)[:300], "code": "checks.held",
                     "params": reason, "unregistered": unknown}
        self.lane(key).update(status="merged", stuck=False, done_at=self.d.now())
        self.say("failed", "failed.checks", {"why": {"code": "checks.held", "params": reason}}, data={"checks": names})
        return True

    async def _trace_back(self, key: str, why: str) -> None:
        """A role's work that checks/trace.sh would refuse goes back before it is merged (its worktree as it is)."""
        lane = self.lane(key)
        if lane["attempt"] >= self.max_attempts(key):
            self._fail_lane(key, f"提交没写清对应的发现，修改的轮数用完了：{why}", keep_merged=bool(lane.get("merged_sha")))
            return
        self.say("bounce", "bounce.trace", {"r_role": key}, role=key, frm="run", to=key)
        await self._start(key, "trace", self.d.manager(), review=why + "\n\n" + TRACE_RULE.format(
            branch=self.s["branch"]))

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
        lane = self.lane(key)
        said = (att.get("reply") or "").strip()  # its answer, without the DONE: line (that is the summary)
        reply = "\n".join(ln for ln in said.splitlines() if not ln.strip().startswith("DONE:")).strip() or att.get("summary") or ""
        text = f"（这一轮没有回答：{failed}）" if failed else (reply[:TALK_KEEP] or "（没有写回答）")
        self.s.setdefault("talks", {}).setdefault(key, []).append(
            {"who": "agent", "text": text, "summary": att.get("summary") or "", "at": self.d.now(), "changed": changed})
        lane["gate"] = "pending"
        self.say("talk", "talk.failed" if failed else "talk.answer",
                 {"r_role": key, "error": failed} if failed else {"r_role": key, "answer": att.get("summary") or text[:80]},
                 role=key, frm=key, to="person")
        self.say("gate", "gate.after_talk", {"g_gate": key}, role=key, frm=key, to="person")

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
            self.d.log.info("vstatd-team: %s cannot write %s: %s", self.rid, DECISIONS_FILE, exc)

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
        """The run's pull request: its run branch into main. Open once the run delivered; merged when a person signs it off (签字放行) and main moved here; ``signed`` when they signed but it
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

    async def commit_sizes(self) -> dict[str, Any] | None:
        """The batch's commits and how big each is (D18, commits.py), kept in the run's results directory; None for an
        imported run (no repository here) or when git cannot say. A report only: nothing is judged on it."""
        s = self.s
        if s.get("imported") or not s.get("base") or not s.get("run_wt") or not Path(s["run_wt"]).is_dir():
            return None
        try:
            return await commits_mod.ensure(Path(s["repo"]).parent / "results", s["run_wt"], s["base"],
                                            moving=not self.ended)
        except Exception:  # noqa: BLE001 - the run goes on without the figures
            self.d.log.warning("vstatd-team: %s cannot measure its commits", self.rid, exc_info=True)
            return None

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
            self.d.log.warning("vstatd-team: %s cannot merge its PR into main", self.rid, exc_info=True)
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
        self.say("skipped", "skipped", {"r_role": key, "why": why, "globs": globs}, role=key)

    def _tested_team(self) -> dict[str, Any]:
        """The team as the test run sees it: the test files owned by a role that sits this run out are left out."""
        out = [k for k in self.order if self.lane(k)["status"] == "skipped"]
        return {**self.team, "skip_owners": out} if out else self.team

    def sign_block_detail(self) -> str:
        """Of why the run cannot be signed off, what came from outside the app: release.sh's reason ("" if none)."""
        m = self.sign_block_msg()
        return str((m.get("params") or {}).get("why") or "") if m and m["code"] == "sign.release" else ""

    def sign_block(self) -> str:
        """Why this run cannot be signed off ("" when it can), in Chinese; sign_block_msg() has it by code."""
        m = self.sign_block_msg()
        return self.msg(m["code"], m["params"]) if m else ""

    def sign_block_msg(self) -> dict[str, Any] | None:
        """Why this run cannot be signed off (None when it can), as a message: 签字放行 is a person taking
        responsibility for what the team delivered, so a run that failed or was stopped has nothing to sign; with a
        release check, only a release.sh that passed on the independent rerun can be signed (D9)."""
        s = self.s
        if not self.ended:
            return {"code": "sign.not_ended", "params": None}
        release = (s.get("rerun") or {}).get("release")
        if release and release["verdict"] != "PASS":  # D9: sign-off only on a release.sh that passed on the rerun
            return {"code": "sign.release", "params": {"why": ((release["reasons"] or [release["summary"]])[0])[:120]}}
        if s["status"] == "failed":
            return {"code": "sign.failed", "params": None}
        if s["status"] == "stopped":
            return {"code": "sign.stopped", "params": None}
        if any(c["when"] == "release" for c in self.team.get("checks") or []) and not release:
            return {"code": "sign.no_rerun", "params": None}
        return None

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
            self.say("bounce", "bounce.review", {"r_role": t, "round": rnd}, role=t, frm=key, to=t,
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
        bench = self.s.get("bench") or {}
        busy = (self.s["needs_test"] or any(lane["status"] in ACTIVE for lane in lanes)
                or any((lane.get("first") or {}).get("status") == "pending" for lane in lanes)
                or (self._finale_due() and bench.get("step") != "done" and not bench.get("held")))
        gating = any(lane.get("gate") == "pending" for lane in lanes)
        t = self.s["tests"]
        if (not busy and not gating and self.team.get("checks") and t.get("failed") and not t.get("held")
                and not bench.get("held") and t.get("rechecked") != t.get("head")):
            # the last round still fails and nothing holds it (a role's round ended without a merge): the checks are
            # looked at again, so that a failure goes back to a role or to a person; the run never ends done with it
            t["rechecked"] = t.get("head")
            self.s["needs_test"] = True
            busy = True
        if not busy and not gating and not any(self.lane(k)["status"] == "waiting" and self._ready(k) for k in self.order):
            self._hold_failing()  # never done with failing checks: the person decides
            held = self.s["tests"].get("held") or bench.get("held")
            if held:
                self._end("failed", "run.held", {"why": {"code": held["code"], "params": held.get("params")} if held.get("code") else held["why"]})
                return
            failed = [k for k in self.order if self.lane(k)["status"] == "failed"]
            if failed:
                self._end("failed", "run.failed_roles", {"r_roles": failed})
                return
            if all(lane["status"] in ("merged", "done", "skipped") for lane in lanes):
                self._end("done", "run.done", {"verdict": self.s.get("verdict")})
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

    def _end(self, status: str, code: str, params: dict[str, Any] | None = None) -> None:
        if not self.ended:
            self.s.update(status=status, ended_at=self.d.now())
            self.say("run", code, params)

    def _fail_lane(self, key: str, why: str, *, keep_merged: bool = False) -> None:
        lane, now = self.lane(key), self.d.now()
        first = lane.get("first") or {}
        if first.get("status") == "sent_back":
            # a round after a send-back failed (an error, a lost agent): tests first gives up on it as on a round with
            # no change, else the developers wait for it with the run still going; 重试 sends it back (failed only)
            first["status"] = "failed"
            self._fail_first(key, why)
            return
        why = " ".join(str(why).split())[:200]
        if lane["attempts"]:
            att = lane["attempts"][-1]
            att["error"], att["ended"] = why, att.get("ended") or now
        lane.update(status="merged" if keep_merged else "failed", done_at=now)
        self.say("failed", "failed.round" if keep_merged else "failed.role", {"r_role": key, "n": lane["attempt"], "why": why}, role=key)

    async def stop(self, *, status: str = "stopped", code: str = "run.stopped", params: dict[str, Any] | None = None) -> bool:
        """Cancel every live agent of the run, and its test run; it ends as *status*."""
        if self.ended:
            return False
        self.cancel_tests()
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
        self._end(status, code, params)
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

    def _work_task(self, key: str, n: int = 1, sizes: dict[str, Any] | None = None) -> str:
        s, lane, role = self.s, self.lane(key), self.roles[key]
        brief = role.get("brief", "")
        if (s.get("plan") or {}).get(key):  # the split a person approved at the gate
            brief = f"这次分给你的任务（{self._planner()}提议、人在关卡上批准的分工）：{s['plan'][key]}。\n\n" + brief
        if not role["writable"] and s.get("base"):
            brief += f"（需求提交是 {s['base'][:12]}，`git diff {s['base'][:12]} HEAD` 就是全部改动。）"
            if commits_mod.table(sizes):
                brief += "\n\n" + commits_mod.table(sizes) + "\n\n"
            t = s.get("tests") or {}
            if t.get("total"):
                red = [c["name"] for c in t.get("cases", []) if c.get("status") == "fail"]
                brief += (f"app 刚跑的测试：{t.get('passed')}/{t.get('total')} 通过" +
                          (f"，没过的：{'；'.join(red[:8])}。没过的测试要算进结论。" if red else "，全绿。"))
        values = {"run": self.rid, "role": key, "title": role["title"], "branch": lane["branch"],
                  "worktree": lane["worktree"], "writable": self._writable(key), "brief": brief,
                  "inputs": "、".join(f"`{p}`" for p in self._inputs(key)) or "无", "repo": s["repo"],
                  "build_env": checks.docker_prefix(self.team.get("check_runner"), [(lane["worktree"], False)],
                                                    workdir=lane["worktree"])}
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
        if n > 1 and not role["writable"] and review_verdict(prev.get("summary")) == "changes" and s.get("review_rounds"):
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
        cite = "，写上对应的发现编号（涉及行为的修复再写事实条目）" if any(r.get("triage") for r in self.team["roles"]) else ""
        return ["", "做完以后：", f"1. 在 {lane['worktree']} 里 `git add` 你改过的文件，提交到 {lane['branch']}，提交说明以 `[{key}]` 开头{cite}。",
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
        results = failing[0].get("results") if failing else None  # a check after the bench: its own results directory
        tail = (f"每个检查的完整结果在 `{results or s['tests'].get('results')}/<检查>.json` 和 `<检查>.log`；检查由 app 重跑，你不能改它们。"
                if self.team.get("checks") else f"可以自己跑 `node --test {files}` 看结果。")
        lines += ["", f"在你的工作目录 {lane['worktree']}（分支 {lane['branch']}）里把它们修好。你只能改：{self._writable(key)}；"
                  "测试和别的目录不归你，看可以，改不行。", tail]
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
