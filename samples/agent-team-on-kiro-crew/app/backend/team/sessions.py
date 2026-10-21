"""Role agents as Kiro Crew chat sessions: every role of a run gets one session, in a folder of the run under
「AI-DLC 团队」 in the dashboard's sidebar. A person can open any of them, read every step and type into it; the app
still dispatches, merges, tests and sends work back. This is the only way the app runs agents: it talks to Kiro Crew
through its HTTP API (``gateway.py``) and never reaches into the Crew process.

``SessionManager`` is the agent manager the sequencer and the board use (``spawn_session``, ``get``, ``all_agents``,
``cancel``, ``continue_conversation_async``, ``recent``, ``history``, ``credits_of`` …); its ``SessionInfo`` objects
carry what ``agent_fields`` below reads. Tests pass a fake with the same surface.

A role may name the Crew member it is (``member``, e.g. ``aidlc-product-agent`` of the 「代理」 page): its session boots
that member's template (prompt, tools, model). A member that is not there (deleted, not added yet) falls back to the
template file of the same name, else to Crew's default agent; ``agent_kind`` says which it got.

What a session takes (checked by ``scripts/probe-sessions.py``): ``POST /api/chat/slots`` in the run's folder, then
its project directory set to the role's worktree (the agent's cwd), then ``trust`` for that one slot (the app holds
``permissions.sessionApproval``, granted by the owner), then the task sent as one message. A turn is over when the
slot is idle twice in a row and the transcript has the reply. A turn KiroCrew could not start (an ``error`` row,
e.g. ``memory_unavailable`` from a race at turn start) is sent again, at most twice.

State lives in ``sessions.json`` in the app's data dir, so a backend reload keeps every role's session.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from .gateway import GatewayError

PREFIX = "s-"
ROOT_FOLDER = "AI-DLC 团队"
IDLE_POLLS = 2          # idle this many polls in a row (after the reply is in) = the turn is over
MISSING_POLLS = 3       # gone from this many listings in a row = closed or deleted by someone
RESENDS = 2             # a turn KiroCrew refused to start is sent again at most this often
NO_START_S = 90.0       # sent, idle and nothing in the transcript for this long: send again
STALL_S = 180.0         # busy with no new transcript row for this long: shown as 卡住
STUCK_S = 240.0         # busy with nothing new for this long: the turn is stopped and the agent told to carry on
NUDGES = 2              # a turn cut short (a transient model error, or stuck) is continued at most this often
TRANSIENT = re.compile(r"transient|5\d\d|runtime failed|timed? ?out|overloaded|rate.?limit|throttl|temporarily|unavailable",
                       re.I)
HISTORY = 400
_FIELDS = ("id", "task", "parent_session_key", "slot", "title", "folder", "cwd", "model", "conv_root", "send_ids",
           "requested", "started", "sent_at", "done", "queued", "queued_reason", "result", "streaming_text", "error",
           "user_stopped", "turns", "tool_count", "last_tool", "last_activity", "stalled", "credits", "calls",
           "resends", "seen_busy", "idle", "missing", "sig", "agent", "agent_kind", "nudges")
KNOWLEDGE_TOOL = "local_knowledge_search"  # kirocrew-core's knowledge search: shown as 查知识库


def _num(val: Any, default: float = 0) -> float:
    return val if isinstance(val, (int, float)) and not isinstance(val, bool) else default


def first_line(text: Any) -> str:
    return str(text or "").split("\n", 1)[0].strip()


def find_agent(mgr: Any, agent_id: str | None) -> Any | None:
    """A role's agent by id, else None."""
    if mgr is None or not agent_id:
        return None
    try:
        return mgr.get(agent_id)
    except Exception:  # noqa: BLE001
        return None


def find_by_tag(mgr: Any, parent: str, match: Callable[[str], bool]) -> Any | None:
    """The newest agent of *parent* whose task's first line passes *match*: finds one whose id never reached run.json
    (the app stopped between the start and the save), so it is adopted instead of started twice."""
    try:
        infos = list(mgr.all_agents)
    except Exception:  # noqa: BLE001
        infos = []
    hits = [i for i in infos if getattr(i, "parent_session_key", "") == parent and match(first_line(getattr(i, "task", "")))]
    return max(hits, key=lambda i: _num(getattr(i, "started", 0))) if hits else None


async def cancel(mgr: Any, agent_id: str) -> bool:
    try:
        return bool(await mgr.cancel(agent_id))
    except Exception:  # noqa: BLE001
        return False


async def cancel_parent(mgr: Any, parent: str) -> None:
    """Every agent of *parent* still going (catches one started while the run was being stopped)."""
    try:
        await mgr.cancel_for_parent(parent)
    except Exception:  # noqa: BLE001
        pass


def agent_fields(info: Any) -> dict[str, Any]:
    """What the sequencer and the board read of a role's agent, read defensively."""
    def g(name: str, default: Any = None) -> Any:
        return getattr(info, name, default)

    error, stopped = str(g("error", "") or ""), bool(g("user_stopped", False))
    queued = bool(g("queued", False))
    return {
        "id": str(g("id", "") or ""), "done": bool(g("done", False)), "queued": queued,
        "queued_reason": str(g("queued_reason", "") or "") or ("在排队，等 Kiro Crew 开始这个会话" if queued else "") or None,
        "result": str(g("result", "") or ""), "text": str(g("streaming_text", "") or ""), "error": error or None,
        "outcome": "stopped" if stopped else ("failed" if error else "completed"),
        "turns": int(_num(g("turns"))), "tool_count": int(_num(g("tool_count"))), "last_tool": str(g("last_tool", "") or ""),
        "last_activity": _num(g("last_activity"), 0) or None, "started": _num(g("started"), 0) or None,
        "stalled": bool(g("stalled", False)), "awaiting": bool(g("_awaiting_approval", False)),
    }


class SessionInfo:
    """What ``agent_fields`` reads of a role's agent, plus what a session needs."""

    conversation_key = ""
    result_path = ""
    _awaiting_approval = False

    def __init__(self, **kw: Any) -> None:
        self.id = ""
        self.task = ""
        self.parent_session_key = ""
        self.slot: str | None = None
        self.title = ""
        self.folder = ""
        self.cwd = ""
        self.model = ""
        self.conv_root: str | None = None  # the session's first info: what a fix round continues
        self.send_ids: list[str] = []
        self.requested = time.time()
        self.started: float | None = None
        self.sent_at: float | None = None
        self.done = False
        self.queued = True
        self.queued_reason: str | None = "正在开 Crew 会话"
        self.result = ""
        self.streaming_text = ""
        self.error: str | None = None
        self.user_stopped = False
        self.turns = 0
        self.tool_count = 0
        self.last_tool = ""
        self.last_activity: float | None = None
        self.stalled = False
        self.credits: float | None = None
        self.calls: list[dict[str, Any]] = []
        self.resends = 0
        self.seen_busy = False
        self.idle = 0
        self.missing = 0
        self.sig = ""
        self.agent = ""        # the Crew member asked for
        self.agent_kind = ""   # what the session got: member, template, or "" (Crew's default agent)
        self.nudges = 0        # times a cut-short turn was continued
        for k, v in kw.items():
            setattr(self, k, v)

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in _FIELDS}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SessionInfo":
        return cls(**{k: d[k] for k in _FIELDS if k in d})


def _tool_call(m: dict[str, Any], scrub: Callable[[str], str]) -> dict[str, Any]:
    meta = m.get("meta") if isinstance(m.get("meta"), dict) else {}
    name = str(meta.get("tool_name") or "") or "tool"
    detail = str(m.get("content") or "").replace("🔧", "").strip()
    raw = meta.get("input")
    try:
        args = json.loads(raw) if isinstance(raw, str) and raw.strip().startswith("{") else raw
    except ValueError:
        args = None
    if isinstance(args, dict):
        for k in ("command", "path", "file_path", "pattern", "query"):
            if isinstance(args.get(k), str) and args[k].strip():
                detail = args[k]
                break
    tool = {"shell": "Running", "execute_bash": "Running", "write": "Writing", "fs_write": "Writing", "read": "Reading",
            "fs_read": "Reading", "glob": "Finding", "grep": "Searching", KNOWLEDGE_TOOL: "查知识库",
            "knowledge_list_sources": "看知识库来源"}.get(name, name[:1].upper() + name[1:])
    for word in (tool, name):  # KiroCrew's row text often starts with the tool's own word ("Reading a.md:1")
        if detail.lower().startswith(word.lower() + " "):
            detail = detail[len(word) + 1:]
            break
    detail = " ".join(scrub(detail).split())
    return {"at": _epoch(m.get("ts")), "tool": tool, "kind": str(meta.get("kind") or "") or None,
            "detail": (detail[:119] + "…") if len(detail) > 120 else (detail or None)}


def _epoch(stamp: Any) -> float:
    from datetime import datetime

    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", text.lower()).strip("-")[:40] or "run"


class SessionManager:
    sessions = True

    def __init__(self, gw: Any, *, app: str, state_file: Path, log: Any, now: Callable[[], float] = time.time,
                 scrub: Callable[[str], str] = lambda s: s) -> None:
        self.gw, self.app, self.state_file, self.log, self.now, self.scrub = gw, app, Path(state_file), log, now, scrub
        self._infos: dict[str, SessionInfo] = {}
        self._folders: dict[str, dict[str, Any]] = {}  # parent → {"id", "name"}
        self._folder_lock = asyncio.Lock()
        self._tasks: set[asyncio.Task[Any]] = set()
        self._dirty = False
        self.max_concurrent = 16

    # ---- persistence ----------------------------------------------------------------------------------- #

    def load(self) -> None:
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for d in data.get("infos", []):
            if isinstance(d, dict) and str(d.get("id", "")).startswith(PREFIX):
                info = SessionInfo.from_dict(d)
                if not info.done and info.queued and not info.slot:  # it was being opened when the app stopped
                    info.done, info.error = True, "app 重启时这个会话还没开好"
                self._infos[info.id] = info
        self._folders = {k: v for k, v in (data.get("folders") or {}).items() if isinstance(v, dict)}

    def _save_now(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        keep = sorted(self._infos.values(), key=lambda i: i.requested)[-400:]
        text = json.dumps({"infos": [i.to_dict() for i in keep], "folders": self._folders}, ensure_ascii=False)
        fd, tmp = tempfile.mkstemp(dir=self.state_file.parent, prefix=".sessions.")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.state_file)

    async def save(self) -> None:
        if self._dirty:
            self._dirty = False
            await asyncio.to_thread(self._save_now)

    # ---- the agent manager surface the sequencer and the board use ------------------------------------- #

    def get(self, agent_id: str) -> SessionInfo | None:
        return self._infos.get(agent_id)

    @property
    def all_agents(self) -> list[SessionInfo]:
        return list(self._infos.values())

    @property
    def running_count(self) -> int:
        return sum(1 for i in self._infos.values() if not i.done and not i.queued)

    @property
    def queued_count(self) -> int:
        return sum(1 for i in self._infos.values() if not i.done and i.queued)

    def spawn_session(self, task: str, *, parent_session_key: str, cwd: str, model: str | None = None, title: str = "",
                      folder: str = "", agent: str = "", **_: Any) -> SessionInfo:
        """A new session for a role (synchronous: it is opened in the background, on the next poll)."""
        info = SessionInfo(id=PREFIX + secrets.token_hex(5), task=task, parent_session_key=parent_session_key, cwd=cwd,
                           model=model or "", title=title or "agent", folder=folder or parent_session_key,
                           requested=self.now(), agent=agent or "")
        info.conv_root = info.id
        self._infos[info.id] = info
        self._dirty = True
        self._background(self._open(info))
        return info

    async def continue_conversation_async(self, conv_id: str, task: str, *, parent_session_key: str, **_: Any) -> SessionInfo:
        """The next turn in the session of *conv_id* (a fix or review round keeps the role's whole conversation)."""
        root = self._infos.get(conv_id)
        info = SessionInfo(id=PREFIX + secrets.token_hex(5), task=task, parent_session_key=parent_session_key,
                           requested=self.now(), conv_root=conv_id)
        self._infos[info.id] = info
        self._dirty = True
        if root is None or not root.slot:
            info.done, info.error = True, "conversation_gone: 找不到这个角色的会话"
            return info
        busy = [i for i in self._infos.values() if i.slot == root.slot and not i.done and i is not info]
        if busy:
            info.done, info.error = True, "conversation_busy: 这个会话还有一轮没结束"
            return info
        info.slot, info.title, info.folder, info.cwd, info.model = root.slot, root.title, root.folder, root.cwd, root.model
        info.agent, info.agent_kind = root.agent, root.agent_kind
        try:
            await self._send(info)
        except Exception as exc:  # noqa: BLE001
            info.done, info.error = True, f"发不出去：{exc}"[:300]
            return info
        info.queued, info.queued_reason, info.started = False, None, self.now()
        return info

    async def cancel(self, agent_id: str) -> bool:
        info = self._infos.get(agent_id)
        if info is None or info.done:
            return False
        if info.slot:
            try:
                await self.gw.stop(info.slot)
            except Exception as exc:  # noqa: BLE001
                self.log.info("aidlc-team: stopping session %s: %s", info.slot, exc)
        info.done, info.user_stopped = True, True
        self._dirty = True
        return True

    async def cancel_for_parent(self, parent: str) -> None:
        await asyncio.gather(*(self.cancel(i.id) for i in list(self._infos.values()) if i.parent_session_key == parent))

    # ---- what the board and the sequencer read beyond SubagentInfo -------------------------------------- #

    def credits_of(self, agent_id: str) -> float | None:
        info = self._infos.get(agent_id)
        return info.credits if info is not None else None

    def slot_of(self, agent_id: str | None) -> str | None:
        info = self._infos.get(agent_id or "")
        return info.slot if info is not None else None

    def recent(self, agent_id: str | None) -> list[dict[str, Any]]:
        info = self._infos.get(agent_id or "")
        return list(info.calls[-8:]) if info is not None else []

    def history(self, agent_id: str) -> list[dict[str, Any]]:
        info = self._infos.get(agent_id)
        return list(info.calls) if info is not None else []

    def folder_of(self, parent: str) -> dict[str, Any] | None:
        return self._folders.get(parent)

    # ---- opening, sending, watching -------------------------------------------------------------------- #

    def _background(self, coro: Any) -> None:
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _folder_for(self, info: SessionInfo) -> str:
        async with self._folder_lock:
            have = self._folders.get(info.parent_session_key)
            if have and have.get("id"):
                return str(have["id"])
            folders = await self.gw.folders()
            root = next((f for f in folders if f.get("name") == ROOT_FOLDER and not f.get("parent_id")
                         and f.get("owner_app") in (self.app, None, "")), None)
            if root is None:
                root = await self.gw.create_folder(ROOT_FOLDER)
            run_dir = str(Path(info.cwd).parents[1]) if info.cwd and len(Path(info.cwd).parents) > 1 else None
            sub = await self.gw.create_folder(info.folder[:60], parent_id=str(root.get("id") or ""),
                                              project_dir=run_dir if run_dir and Path(run_dir).is_dir() else None)
            self._folders[info.parent_session_key] = {"id": str(sub.get("id") or ""), "name": info.folder[:60],
                                                      "root": str(root.get("id") or "")}
            self._dirty = True
            return self._folders[info.parent_session_key]["id"]

    async def _open(self, info: SessionInfo) -> None:
        try:
            folder_id = await self._folder_for(info)
            n = sum(1 for i in self._infos.values() if i.parent_session_key == info.parent_session_key and i.slot) + 1
            name = f"{self.app}-{_slug(info.parent_session_key.split(':')[-1])}-{n}-{secrets.token_hex(2)}"
            row = await self._create(info, name, folder_id)
            key = str(row.get("key") or row.get("name") or "")
            if not key:
                raise GatewayError(0, "创建会话没有返回 key", "no_key")
            info.slot = key
            await self.gw.set_project(key, info.cwd)
            await self.gw.trust(key)
            await self._send(info)
            info.queued, info.queued_reason, info.started = False, None, self.now()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            info.done, info.error = True, f"开 Crew 会话失败：{exc}"[:300]
            self.log.warning("aidlc-team: opening a session for %s failed: %s", info.title, exc)
        self._dirty = True

    async def _create(self, info: SessionInfo, name: str, folder_id: str) -> dict[str, Any]:
        """The slot, booting the role's Crew member; its template file when the member is not there; else the default."""
        kinds = ("member", "template", "") if info.agent else ("",)
        for kind in kinds:
            try:
                row = await self.gw.create_slot(name=name, title=info.title, folder_id=folder_id, model=info.model,
                                                agent=info.agent if kind else "", agent_kind=kind)
            except GatewayError as exc:
                if kind and exc.status in (400, 404, 409):
                    self.log.info("aidlc-team: %s as a %s is not there (%s), trying the next", info.agent, kind, exc.code)
                    continue
                raise
            info.agent_kind = kind
            return row
        raise GatewayError(409, f"开不了 {info.agent} 的会话", "agent_choice_unavailable")  # pragma: no cover

    def knowledge_hits(self, agent_id: str | None) -> list[dict[str, Any]]:
        """What the role's session asked the knowledge base (查知识库 calls), oldest first."""
        info = self._infos.get(agent_id or "")
        return [c for c in (info.calls if info is not None else []) if c.get("tool") == "查知识库"]

    def agent_of(self, agent_id: str | None) -> dict[str, str] | None:
        info = self._infos.get(agent_id or "")
        return {"name": info.agent, "kind": info.agent_kind} if info is not None and info.agent else None

    async def _send(self, info: SessionInfo) -> None:
        sid = f"{info.id}-{len(info.send_ids)}"
        info.send_ids.append(sid)
        info.sent_at, info.idle, info.seen_busy, info.sig = self.now(), 0, False, ""
        info.last_activity = info.sent_at
        self._dirty = True
        await self.gw.send(str(info.slot), info.task, sid)

    async def _nudge(self, info: SessionInfo, why: str) -> None:
        """The turn was cut short (the model backend failed mid-way, or it hung): the same session is told to carry on;
        what it did so far is in its worktree. Counted against NUDGES."""
        info.nudges += 1
        sid = f"{info.id}-{len(info.send_ids)}"
        info.send_ids.append(sid)
        info.sent_at, info.idle, info.seen_busy, info.sig = self.now(), 0, False, ""
        info.last_activity = info.sent_at
        info.last_tool = f"中断了（{why}），编排器让它接着做（第 {info.nudges} 次）"
        self._dirty = True
        self.log.info("aidlc-team: session %s was cut short (%s), continuing (%d)", info.slot, why, info.nudges)
        await self.gw.send(str(info.slot), "（编排器）你上一轮被中断了：" + why + "。你已经做的改动都在工作目录里：先 `git status`、"
                           "`git log --oneline -3` 看一眼做到哪了，再接着把原来的任务做完；做完照原来的要求提交，最后一条回复的第一行写 `DONE: ` 加一句话总结。", sid)

    async def poll(self) -> None:
        """One look at every live session: a single listing, then the transcript of each one that is live."""
        live = [i for i in self._infos.values() if not i.done and i.slot and not i.queued]
        if live:
            try:
                rows = {str(r.get("key") or ""): r for r in await self.gw.slots()}
            except Exception as exc:  # noqa: BLE001
                self.log.info("aidlc-team: listing sessions failed: %s", exc)
                rows = None
            if rows is not None:
                await asyncio.gather(*(self._update(i, rows.get(str(i.slot))) for i in live), return_exceptions=True)
        await self.save()

    async def _update(self, info: SessionInfo, row: dict[str, Any] | None) -> None:
        now = self.now()
        if row is None:
            info.missing += 1
            if info.missing >= MISSING_POLLS:
                info.done, info.error = True, "Crew 里找不到这个会话了（被关掉或删除了）"
                self._dirty = True
            return
        info.missing = 0
        busy = bool(row.get("running") or row.get("pending_approval") or int(row.get("queue_depth") or 0))
        info._awaiting_approval = bool(row.get("pending_approval"))
        try:
            msgs = await self.gw.messages(str(info.slot), limit=300)
        except Exception as exc:  # noqa: BLE001
            self.log.info("aidlc-team: reading session %s failed: %s", info.slot, exc)
            return
        mine = None
        for idx in range(len(msgs) - 1, -1, -1):
            meta = msgs[idx].get("meta") if isinstance(msgs[idx].get("meta"), dict) else {}
            if msgs[idx].get("role") == "user" and meta.get("sendId") in info.send_ids:
                mine = idx
                break
        after = msgs[mine + 1:] if mine is not None else []
        calls = [_tool_call(m, self.scrub) for m in after if m.get("role") == "tool"]
        replies = [m for m in after if m.get("role") == "assistant" and str(m.get("content") or "").strip()]
        errors = [m for m in after if m.get("role") == "error"]
        info.calls, info.tool_count, info.turns = calls[-HISTORY:], len(calls), len(replies)
        if calls:
            info.last_tool = f"{calls[-1]['tool']} {calls[-1]['detail'] or ''}".strip()
        spent = [((m.get("meta") or {}).get("turn_stats") or {}).get("credits") for m in replies]
        vals = [float(v) for v in spent if isinstance(v, (int, float))]
        info.credits = round(sum(vals), 3) if vals else info.credits
        sig = f"{len(after)}:{len(str(after[-1].get('content') or '')) if after else 0}"
        if sig != info.sig:
            info.sig, info.last_activity = sig, now
        info.stalled = busy and now - float(info.last_activity or now) > STALL_S
        self._dirty = True
        quiet = now - float(info.last_activity or now)
        if busy and quiet > STUCK_S and info.nudges < NUDGES:  # hung: stop the turn, then let it carry on
            try:
                await self.gw.stop(str(info.slot))
            except Exception as exc:  # noqa: BLE001
                self.log.info("aidlc-team: stopping stuck session %s: %s", info.slot, exc)
            await self._nudge(info, f"{int(quiet)} 秒没有任何动静")
            return
        last = after[-1] if after else None
        if (not busy and last is not None and last.get("role") == "error" and (calls or replies) and info.nudges < NUDGES
                and TRANSIENT.search(f"{last.get('content') or ''} {(last.get('meta') or {}).get('code') or ''}")):
            await self._nudge(info, "模型后端临时出错")  # mid-way: the first-turn refusal below sends the task again
            return
        if errors and not replies and not calls and not busy:
            if info.resends < RESENDS:  # KiroCrew did not start the turn (memory_unavailable at turn start and the like)
                info.resends += 1
                self.log.info("aidlc-team: session %s refused the turn (%s), sending again", info.slot,
                              ((errors[-1].get("meta") or {}).get("code") or "error"))
                await self._send(info)
                return
        if not after and not busy and now - float(info.sent_at or now) > NO_START_S and info.resends < RESENDS:
            info.resends += 1
            await self._send(info)
            return
        if busy:
            info.seen_busy, info.idle = True, 0
            return
        info.idle += 1
        if info.idle < IDLE_POLLS or not (replies or errors or (info.seen_busy and info.idle >= IDLE_POLLS + 1)):
            return
        if replies:
            info.result = str(replies[-1].get("content") or "")
            info.streaming_text = "\n\n".join(str(m.get("content") or "") for m in replies)[-20000:]
        elif errors:
            info.error = (str(errors[-1].get("content") or "") or "KiroCrew 报错")[:300]
        else:
            info.error = "这一轮结束了，但没有回复"
        info.done = True

    # ---- cleaning up the demo sessions ----------------------------------------------------------------- #

    async def cleanup(self, keep_parents: set[str]) -> dict[str, int]:
        """Delete every session this app opened, except those of *keep_parents* (runs still going), and hide the run
        folders they leave empty under 「AI-DLC 团队」: KiroCrew lets only a person delete a folder."""
        keep_slots = {i.slot for i in self._infos.values() if i.parent_session_key in keep_parents and i.slot}
        keep_folders = {str(v.get("id")) for k, v in self._folders.items() if k in keep_parents}
        slots = [r for r in await self.gw.slots() if r.get("app") == self.app and str(r.get("key")) not in keep_slots]
        deleted = 0
        for r in slots:
            try:
                await self.gw.delete_slot(str(r.get("key")))
                deleted += 1
            except Exception as exc:  # noqa: BLE001
                self.log.info("aidlc-team: deleting session %s: %s", r.get("key"), exc)
        folders = await self.gw.folders()
        root_ids = {str(f.get("id")) for f in folders if f.get("name") == ROOT_FOLDER and not f.get("parent_id")}
        gone = 0
        for f in folders:
            fid = str(f.get("id"))
            if (str(f.get("parent_id") or "") in root_ids and fid not in keep_folders and f.get("owner_app") == self.app
                    and not f.get("hidden")):
                try:
                    await self.gw.hide_folder(fid)
                    gone += 1
                except Exception as exc:  # noqa: BLE001
                    self.log.info("aidlc-team: hiding folder %s: %s", fid, exc)
        for parent in [k for k in self._folders if k not in keep_parents]:
            self._folders.pop(parent, None)
        for info in self._infos.values():
            if info.parent_session_key not in keep_parents and info.slot:
                if not info.done:
                    info.done, info.user_stopped = True, True
                info.slot = None
        self._dirty = True
        await self.save()
        return {"sessions": deleted, "folders": gone}
