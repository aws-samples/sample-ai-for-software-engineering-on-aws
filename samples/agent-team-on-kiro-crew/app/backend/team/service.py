"""The app's single service object per enable: the runs, the background loop that moves them, and the role sessions.
Built by ``register_routes`` (no I/O), started by ``on_startup``, stopped by ``on_shutdown``."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Callable

from . import board, checks, cto as cto_mod, outputs, routing
from . import standards as standards_mod
from . import store as store_mod
from .constants import APP_NAME, APP_ROOT, TARGET_TEMPLATE, TASK_TEMPLATE_FILE, TEAM_DIR, TEAM_FILE, TICK_S, WORK_ROOT
from .gateway import Gateway, GatewayError
from .sessions import SessionManager
from .httpkit import AppError
from .store import RID_RE, Store
from . import team as team_mod
from .team import Deps, TeamRun, load_team, new_rid, new_state
from . import site as site_mod
from .site import Site

_REGISTRY: dict[str, "Service"] = {}
_SECRETS = re.compile(r"(?i)((?:password|passwd|secret|token|api[_-]?key|authorization)\s*[=:]\s*|bearer\s+)\S+"
                      r"|AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}")


def basic_scrub(text: str) -> str:
    return _SECRETS.sub(lambda m: (m.group(1) or "") + "[已隐去]", text)


class Service:
    def __init__(self, ctx: Any, *, manager: Any = None, work_root: Path | None = None, template: Path | None = None,
                 run_tests: Callable[..., Any] | None = None, tick_s: float = TICK_S,
                 now: Callable[[], float] = time.time, opener: Callable[[list[str]], Any] | None = None,
                 sessions: Any = None) -> None:
        """*manager*: the agent manager the runs use (a fake in tests); by default the role sessions."""
        self.ctx = ctx
        self.name = getattr(ctx, "name", APP_NAME) or APP_NAME
        self.log = getattr(ctx, "logger", None) or logging.getLogger(APP_NAME)
        self.data_dir = Path(getattr(ctx, "data_dir", ".") or ".")
        self.started = False
        self.runs: dict[str, TeamRun] = {}
        self.work_root = Path(work_root) if work_root else WORK_ROOT
        self.tick_s = tick_s
        self.site = Site(scrub=self.scrub, state_file=self.data_dir / "site.json")
        self._opener = opener or _open_on_this_mac
        # every role's agent is a Kiro Crew chat session, opened through the gateway's chat API
        self.sessions = sessions or SessionManager(Gateway(self.name, APP_ROOT / ".app_secret"), app=self.name,
                                                   state_file=self.data_dir / "sessions.json", log=self.log,
                                                   scrub=self.scrub)
        self._agents = manager if manager is not None else self.sessions
        self._deps = Deps(store=Store(self.data_dir / "runs"), manager=self.manager,
                          run_tests=run_tests or checks.run_tests, template=Path(template or TARGET_TEMPLATE),
                          scrub=self.scrub, now=now, log=self.log, deploy=self._deploy, members=self.member_names)
        self._loop: asyncio.Task[None] | None = None
        self._ticks: dict[str, asyncio.Task[None]] = {}
        self._failures: dict[str, int] = {}
        self._creating = asyncio.Lock()
        # what Kiro Crew has around the team: its members (「代理」) and knowledge sources (「知识库 → 来源」), read
        # every CREW_REFRESH_S by the pulse; None while never read (or the app may not read them)
        self.crew: dict[str, Any] = {"at": float("-inf"), "members": None, "knowledge": None, "error": ""}
        self._live_runs: set[str] = set()  # the runs seen going last pulse: one that has ended since keeps its roster
        self._events_cache: dict[str, tuple[int, list[dict[str, Any]]]] = {}  # rid → (seq, every event): the CTO view

    def manager(self) -> Any:
        """The agent manager the runs, the board and 产出 use: the role sessions."""
        return self._agents

    def scrub(self, text: str) -> str:
        """KiroCrew's own outbound redaction (``ctx.scrub``) when there is one, else a few obvious patterns."""
        if not text:
            return ""
        sdk = getattr(self.ctx, "scrub", None)
        if sdk is not None:
            try:
                return sdk.outbound(text).text
            except Exception:  # noqa: BLE001
                pass
        return basic_scrub(text)

    async def start(self) -> None:
        if self.started:
            return
        self.data_dir.mkdir(parents=True, exist_ok=True)
        for state, events in await asyncio.to_thread(self._deps.store.load_all):
            try:
                self.runs[state["id"]] = TeamRun(state, self._deps, events)
            except Exception:  # noqa: BLE001
                self.log.exception("aidlc-team: run %s cannot be loaded", state.get("id"))
        for run in self.runs.values():  # signed off before the signature merged the PR (0.6.0): it does now, once
            sig = run.s.get("signoff")
            if isinstance(sig, dict) and "merged" not in sig and not run.s.get("imported"):
                sig["merged"] = await run.merge_pr()
                await run.save()
        await asyncio.to_thread(self.sessions.load)
        self.started = True
        self._redeploy_task = asyncio.create_task(self._redeploy_latest())
        self._loop = asyncio.create_task(self._forever())
        self.log.info("aidlc-team: started, %d runs, data in %s", len(self.runs), self.data_dir)

    async def stop(self) -> None:
        self.started = False
        tasks = [t for t in (self._loop, *self._ticks.values()) if t is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._loop, self._ticks = None, {}
        await self.site.stop()
        await self.sessions.gw.close() if hasattr(self.sessions.gw, "close") else None

    async def _forever(self) -> None:
        while True:
            try:
                await self.pulse()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                self.log.exception("aidlc-team: background pulse failed")
            await asyncio.sleep(self.tick_s)

    async def pulse(self) -> None:
        """One beat: what the role sessions did, then a tick for every active run that is not ticking already."""
        try:
            await self.sessions.poll()
        except Exception:  # noqa: BLE001
            self.log.exception("aidlc-team: polling the role sessions failed")
        if time.monotonic() - self.crew["at"] >= CREW_REFRESH_S:
            await self.refresh_crew()
        for rid in list(self._live_runs):
            run = self.runs.get(rid)
            if run is not None and run.ended:
                await self.freeze_roster(run)
        self._live_runs = {rid for rid, run in self.runs.items() if not run.ended}
        for rid, run in list(self.runs.items()):
            if not run.ended and rid not in self._ticks:
                self._ticks[rid] = asyncio.create_task(self._tick(run))

    async def _tick(self, run: TeamRun) -> None:
        try:
            await run.tick()
            self._failures.pop(run.rid, None)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            n = self._failures[run.rid] = self._failures.get(run.rid, 0) + 1
            if n in (1, 5) or n % 50 == 0:
                self.log.exception("aidlc-team: tick of %s failed (%d in a row)", run.rid, n)
        finally:
            if self._ticks.get(run.rid) is asyncio.current_task():
                self._ticks.pop(run.rid, None)

    async def refresh_crew(self) -> None:
        """The members and knowledge sources Kiro Crew has now (the app reads them; it never changes them)."""
        self.crew["at"] = time.monotonic()
        errors = []
        for key, call in (("members", self.sessions.gw.members), ("knowledge", self.sessions.gw.knowledge_sources)):
            try:
                self.crew[key] = await call()
            except (GatewayError, AttributeError) as exc:
                errors.append(f"{key}: {exc}"[:160])
        self.crew["error"] = "；".join(errors)

    async def freeze_roster(self, run: TeamRun) -> None:
        """A run that just ended keeps the team's members as they were then (Crew's 「代理」 page, its workspace): looking
        back at it later shows that team, not whoever joined since. Runs that ended before this never got one."""
        ws = run.team.get("workspace")
        names = self.member_names(ws) if ws else None
        if names is None or "crew_members" in run.s:
            return
        run.s["crew_members"] = sorted(names)
        await run.save()

    def member_names(self, workspace: str | None = None) -> set[str] | None:
        """The Crew members' names (those of *workspace* only, when given: the team's own 「代理」)."""
        rows = self.crew.get("members")
        if rows is None:
            return None
        return {str(r.get("name")) for r in rows if not workspace or r.get("workspace") == workspace}

    def knowledge_id(self, name: str) -> str:
        """The id of the knowledge source called *name* ("" when Crew has none, or the app has not read them yet)."""
        row = next((r for r in self.crew.get("knowledge") or [] if name and r.get("name") == name), None)
        return str(row.get("id") or "") if row else ""

    def knowledge_view(self, name: str) -> dict[str, Any] | None:
        """One knowledge source as the page shows it: how many documents are in, and whether it is still indexing."""
        rows = self.crew.get("knowledge")
        if not name or rows is None:
            return None
        return board.source_row(name, next((r for r in rows if r.get("name") == name), {}))

    async def create_run(self, requirement: str, model: str | None = None, source: str | None = None,
                         team_name: str | None = None) -> str:
        """One run at a time: every run spends real credits. *model* (optional) replaces the team's default model
        for every role of this run that does not name its own. *source* (optional) is an existing project the team
        takes over instead of the demo template; *team_name* (optional) is a ``team-*.json`` under team/."""
        if not self.started:
            raise AppError("app 还没启动好，稍后再试", "not_started", 503)
        async with self._creating:
            active = [r.rid for r in self.runs.values() if not r.ended]
            if active:
                raise AppError(f"已经有一个运行在跑（{active[0]}），先停掉它", "run_active", 409)
            src = Path(source).expanduser() if source else None
            if src is not None and not src.is_dir():
                raise AppError(f"接手的项目目录不存在：{source}", "bad_source")
            team_file = TEAM_DIR / team_name if team_name else TEAM_FILE
            try:
                team = await asyncio.to_thread(load_team, team_file)
                tmpl_name = team.get("task_template")  # a team file may bring its own task template (team/ 下的 .md)
                if tmpl_name is not None and (not isinstance(tmpl_name, str) or not re.fullmatch(r"[\w-]+\.md", tmpl_name)):
                    raise ValueError(f"task_template 必须是 team/ 下的 .md 文件名：{tmpl_name}")
                tmpl_file = TEAM_DIR / tmpl_name if tmpl_name else TASK_TEMPLATE_FILE
                template = await asyncio.to_thread(tmpl_file.read_text, encoding="utf-8")
            except (OSError, ValueError) as exc:
                raise AppError(f"读不了团队配置：{exc}", "bad_team", 500)
            if src is None and isinstance(team.get("source"), str):  # the team works on the customer's own repository
                src = Path(team["source"]).expanduser()
                if not src.is_dir():
                    raise AppError(f"这个团队要改的项目不在这台电脑上：{team['source']}", "bad_source")
            if team.get("needs_source") and src is None:
                raise AppError("这个团队要在一个已有的项目上做事：先指定项目目录（source）", "needs_source")
            if model:
                team = {**team, "defaults": {**team.get("defaults", {}), "model": model}}
            rid = new_rid(self.runs)
            state = new_state(rid, requirement, team, template, self.work_root, self._deps.template, self._deps.now(),
                              source=src)
            state["standards"] = standards_mod.match(requirement, team)
            state["roster"] = routing.roster_of(team)  # the whole team as it was when this run began
            kb_id = self.knowledge_id(str((team.get("knowledge") or {}).get("source") or ""))
            if kb_id:  # the roles search this company's source only (two companies' 《品牌规范》 would both answer)
                state["knowledge_source_id"] = kb_id
            run = TeamRun(state, self._deps)
            run.emit("run", f"运行开始：{state['title']}")
            if team.get("workspace") and any(r.get("optional") for r in team["roles"]):
                await self.refresh_crew()  # 在职 is who is on 「代理」 now: a member added a moment ago counts
                run.leave_out_unhired(self.member_names(team["workspace"]))
            if state["standards"]:
                run.emit("standards", "适用公司规范：" + "、".join(f"《{x['title']}》" for x in state["standards"] if x["kind"] != "data")
                         + ("；用到的数据：" + "、".join(f"《{x['title']}》" for x in state["standards"] if x["kind"] == "data")
                            if any(x["kind"] == "data" for x in state["standards"]) else ""))
            await run.save()
            self.runs[rid] = run
            task = self._ticks[rid] = asyncio.create_task(self._tick(run))
        await asyncio.shield(task)  # the repository is set up and the first role started before the answer
        return rid

    async def stop_run(self, rid: str) -> dict[str, Any]:
        run = self.runs.get(rid) if RID_RE.match(rid or "") else None
        if run is None:
            raise AppError("没有这个运行", "not_found", 404)
        if not await run.stop():
            raise AppError(f"运行已经结束了（{run.s['status']}）", "run_ended", 409)
        return {"ok": True, "run": rid, "status": run.s["status"]}

    def _run(self, rid: str) -> TeamRun:
        run = self.runs.get(rid) if RID_RE.match(rid or "") else None
        if run is None:
            raise AppError("没有这个运行", "not_found", 404)
        return run

    async def retry(self, rid: str, roles: Any = None, note: str = "") -> dict[str, Any]:
        """重试: the failed roles of *rid* (all of them, or those named) get another round; an ended run carries on."""
        run = self._run(rid)
        self._not_imported(run, "重试")
        if roles is not None and (not isinstance(roles, list) or not all(isinstance(r, str) for r in roles)):
            raise AppError("roles 必须是角色名的列表", "invalid_roles")
        async with self._creating:
            active = [r.rid for r in self.runs.values() if not r.ended and r.rid != run.rid]
            if active:
                raise AppError(f"已经有一个运行在跑（{active[0]}），一次只跑一个", "run_active", 409)
            picked = await run.retry(roles or None, note=note)
        if not picked:
            raise AppError("没有失败的角色可以重试", "nothing_to_retry", 409)
        return {"ok": True, "run": run.rid, "roles": picked, "status": run.s["status"]}

    async def gate(self, rid: str, role: str, decision: str, note: str = "", delivery: Any = None,
                   answers: Any = None) -> dict[str, Any]:
        """A person at a gate: approve, send the role back with what to change, or 讨论 (it answers; the gate stays).
        *delivery*: the 交付标签 they confirm; *answers*: their choice for each question the role put to them."""
        run = self._run(rid)
        spec = run.roles.get(role) or {}
        pending = bool(spec) and run.lane(role).get("gate") == "pending"
        if decision == "discuss" and pending and not note.strip():
            raise AppError("讨论要写下你想问的或想商量的", "no_message")
        if decision == "discuss" and pending and not run.discuss_allowed(role):
            raise AppError("这个关卡不能讨论（团队没有打开，或讨论的轮数用完了）", "no_discuss", 409)
        if decision == "approve" and pending and run.lane(role).get("overrule") and not note.strip():
            raise AppError("审查还说要改：推翻审查结论放行要写理由（会记在签字单上）", "no_reason")
        if (decision == "revise" and pending and not spec.get("writable")
                and not team_mod.review_targets(note, run.team["roles"])
                and not team_mod.review_targets(run.overrule_review(role), run.team["roles"])):
            raise AppError("退回要写明打回给谁，比如「打回：前端开发 #2」", "no_target")
        if not await run.gate(role, decision, note, delivery, answers):
            raise AppError("这个角色现在没有在等人批准", "not_gated", 409)
        return {"ok": True, "run": run.rid, "role": role, "decision": decision, "status": run.s["status"]}

    async def signoff(self, rid: str, by: str, note: str = "") -> dict[str, Any]:
        """签字放行: a person takes responsibility for releasing what the team delivered (a finished run only: the
        machine checks and the independent review are in, the person signs for the release)."""
        run = self._run(rid)
        if not run.ended:
            raise AppError("运行结束以后才能签字", "run_active", 409)
        if run.sign_block():
            raise AppError(run.sign_block(), "not_signable", 409)
        if run.s.get("signoff"):
            raise AppError(f"已经由 {run.s['signoff']['by']} 签过了", "signed", 409)
        t = run.s["tests"]
        run.s["signoff"] = {"by": by, "note": note, "at": self._deps.now(), "tests": f"{t['passed']}/{t['total']}"}
        pr = run.pr() or {}
        run.s["signoff"]["merged"] = await run.merge_pr()
        merged = f"PR #{pr.get('number')} 合入 main（{run.s['signoff']['merged']}）" if run.s["signoff"]["merged"] else ""
        run.emit("signoff", f"{by} 签字放行" + (f"：{note}" if note else "") + (f"；{merged}" if merged else ""), role=None)
        await run.save()
        return {"ok": True, "run": run.rid, "signoff": run.s["signoff"]}

    async def import_run(self, state: Any, events: Any, replace: bool = False) -> dict[str, Any]:
        """导入: a finished run recorded on another Mac (its run.json and events.jsonl), to look at and replay here. Its record only:
        the code and the Kiro Crew sessions stayed there, so it cannot be retried, opened in a folder or run as a site.
        *replace*: a run imported before is replaced by this record (a run of this Mac never is)."""
        if not isinstance(state, dict) or not isinstance(events, list) or not all(isinstance(e, dict) for e in events):
            raise AppError("导入的内容要有 run（运行记录）和 events（事件列表）", "invalid_import")
        rid = str(state.get("id") or "")
        if not RID_RE.match(rid):
            raise AppError(f"运行编号不对：{rid!r}", "invalid_import")
        if state.get("status") not in team_mod.ENDED:
            raise AppError("只能导入已经结束的运行", "invalid_import")
        if not isinstance(state.get("lanes"), dict) or not isinstance(state.get("team"), dict):
            raise AppError("运行记录不完整（缺 lanes 或 team）", "invalid_import")
        if rid in self.runs and not (replace and self.runs[rid].s.get("imported")):
            raise AppError(f"已经有这次运行了：{rid}", "exists", 409)
        state = {**state, "imported": dict(state.get("imported") or {"from": "另一台 Mac"}), "hidden": False}
        events = sorted(events, key=lambda e: int(e.get("seq") or 0))
        if events:
            state["seq"] = max(int(state.get("seq") or 0), int(events[-1].get("seq") or 0))
        lines = [json.dumps(e, ensure_ascii=False) + "\n" for e in events]
        if rid in self.runs:  # replacing an imported run: its events are written again from the start (write appends)
            await asyncio.to_thread((self.data_dir / "runs" / rid / "events.jsonl").unlink, missing_ok=True)
        await asyncio.to_thread(self._deps.store.write, rid, json.dumps(state, ensure_ascii=False), lines)
        try:
            self.runs[rid] = TeamRun(state, self._deps, events[-200:])
        except Exception as exc:  # noqa: BLE001
            raise AppError(f"运行记录读不了：{exc}", "invalid_import") from exc
        self._events_cache.pop(rid, None)
        return {"ok": True, "run": rid, "title": state.get("title"), "events": len(events)}

    def _not_imported(self, run: TeamRun, what: str) -> None:
        if run.s.get("imported"):
            raise AppError(f"这是从别的 Mac 导入的运行，只带运行记录，不能{what}", "imported", 409)

    async def hide_run(self, rid: str) -> dict[str, Any]:
        """从列表里删除: a finished run leaves the page's list; its record, code and sessions stay on disk."""
        run = self._run(rid)
        if not run.ended:
            raise AppError("运行还在进行，先停止再删除", "run_active", 409)
        run.s["hidden"] = True
        await run.save()
        return {"ok": True, "run": run.rid}

    def folder(self, rid: str, role: str | None = None) -> Path:
        """Where a run's code is: the run branch's worktree (everything merged), or one role's own worktree."""
        run = self._run(rid)
        self._not_imported(run, "打开文件夹（代码在原来那台 Mac 上）")
        if role in (None, "", "run"):
            path = run.s.get("run_wt")
        elif role in run.roles:
            path = run.lane(role).get("worktree")
        else:
            raise AppError("没有这个角色", "not_found", 404)
        if not path or not Path(path).is_dir():
            raise AppError("这个文件夹还没建出来", "no_folder", 404)
        return Path(path)

    async def open_folder(self, rid: str, role: Any = None, app: Any = "finder") -> dict[str, Any]:
        """Open the folder on this Mac: in Finder, or in the Kiro IDE. Only a run's own folders, never a path from
        the request."""
        if role is not None and not isinstance(role, str):
            raise AppError("role 必须是角色名", "invalid_role")
        if app not in ("finder", "kiro"):
            raise AppError("app 只能是 finder 或 kiro", "invalid_app")
        path = self.folder(rid, role)
        cmd = ["/usr/bin/open", str(path)] if app == "finder" else ["/usr/bin/open", "-a", "Kiro", str(path)]
        rc = await self._opener(cmd)
        if rc not in (0, None):
            raise AppError("打不开：" + ("没装 Kiro" if app == "kiro" else "open 命令失败"), "open_failed", 502)
        return {"ok": True, "path": str(path), "app": app}

    async def events(self, rid: str) -> dict[str, Any]:
        """Every event of a run, for the replay (the board carries only the latest ones)."""
        run = self._run(rid)
        evs = await asyncio.to_thread(store_mod.all_events, self.data_dir / "runs" / run.rid / "events.jsonl")
        return {"run": run.rid, "events": [{**e, "text": self.scrub(str(e.get("text", "")))} for e in evs]}

    async def role_output(self, rid: str, role: str) -> dict[str, Any]:
        return await outputs.role_output(self._run(rid), role, mgr=self.manager(), scrub=self.scrub)

    async def file_view(self, rid: str, role: str, path: Any, view: str) -> dict[str, Any]:
        run = self._run(rid)
        self._not_imported(run, "看文件内容（代码在原来那台 Mac 上）")
        return await outputs.file_view(run, role, path, view)

    def site_status(self, rid: str) -> dict[str, Any]:
        return self.site.status(self._run(rid).rid)

    async def start_site(self, rid: str) -> dict[str, Any]:
        run = self._run(rid)
        self._not_imported(run, "打开网站（代码在原来那台 Mac 上）")
        if not run.ended:
            raise AppError("运行结束以后才能打开网站：运行中 app 要在这个目录里合并和跑测试", "run_active", 409)
        if not run.s.get("base"):
            raise AppError("这个运行还没有代码", "no_code", 409)
        return await self.site.start(run.rid, Path(run.s["run_wt"]))

    async def stop_site(self, rid: str) -> dict[str, Any]:
        run = self._run(rid)
        if self.site.rid == run.rid:
            await self.site.stop()
        return self.site.status(run.rid)

    async def _redeploy_latest(self) -> None:
        """The app stopping stops the site it started: when it starts again, the newest run deployed within its time
        is deployed again the same way, so the demo's last step still opens."""
        try:
            done = [r for r in self.runs.values() if r.ended and not r.s.get("imported") and not r.s.get("hidden")
                    and any(r.lane(k).get("deployed") for k in r.order)]
            if not done:
                return
            run = max(done, key=lambda r: float(r.s.get("ended_at") or 0))
            key = next(k for k in run.order if run.lane(k).get("deployed"))
            spec = run.roles[key].get("deploy") or {}
            if time.time() - float(run.lane(key)["deployed"].get("at") or 0) > float(spec.get("ttl_min") or 120) * 60:
                return
            res = await self._deploy(run.rid, Path(run.s["run_wt"]), spec)
            self.log.info("aidlc-team: redeployed %s after a restart: %s", run.rid, res.get("url") or res.get("error"))
        except Exception:  # noqa: BLE001
            self.log.exception("aidlc-team: redeploying after a restart failed")

    async def _deploy(self, rid: str, wt: Path, spec: dict[str, Any]) -> dict[str, Any]:
        """部署执行 for a deploy role: the port and health path from the role's ``deploy/local.json`` (else the team's
        defaults), the service started on 127.0.0.1 from the run worktree, healthy only when the path answers 200."""
        cfg: dict[str, Any] = {}
        path = wt / "deploy" / "local.json"
        if path.is_file():
            try:
                cfg = json.loads(await asyncio.to_thread(path.read_text, encoding="utf-8"))
            except ValueError as exc:
                return {"ok": False, "error": f"deploy/local.json 不是合法的 JSON：{exc}"}
        elif spec.get("config_required", True):
            return {"ok": False, "error": "没有 deploy/local.json（要写明 port 和 health）"}
        port = cfg.get("port", spec.get("port", 8080))
        health = cfg.get("health", spec.get("health", "/"))
        if not isinstance(port, int) or not 1024 <= port <= 65535:
            return {"ok": False, "error": f"deploy/local.json 的 port 要是 1024 到 65535 的整数：{port!r}"}
        if not isinstance(health, str) or not health.startswith("/") or len(health) > 200:
            return {"ok": False, "error": f"deploy/local.json 的 health 要是以 / 开头的路径：{health!r}"}
        st = await self.site.start(rid, wt, port=port, ttl_s=float(spec.get("ttl_min") or 120) * 60)
        if st["state"] != "running":
            return {"ok": False, "error": st.get("error") or "服务没起来"}
        code = await site_mod.http_status(int(st["port"]), health)
        if code != 200:
            await self.site.stop()
            return {"ok": False, "error": f"健康检查 GET {health} 返回 {code or '没有应答'}，不是 200"}
        note = "" if st["port"] == port else f"{port} 被占用，换成了 {st['port']}"
        return {"ok": True, "url": st["url"], "note": note}


    def cards(self) -> list[dict[str, Any]]:
        return board.cards(self.runs)

    def route(self, requirement: str) -> dict[str, Any]:
        """组队预览: which team the orchestrator picks for *requirement*, and why (no run is started); with the
        company standards it touches, which of its members Kiro Crew has, and its knowledge source."""
        out = routing.route(requirement)
        pick = out.get("team")
        names = self.member_names()
        out["crew"] = {"members": sorted(names) if names is not None else None, "error": self.crew.get("error") or ""}
        if pick:
            try:
                full = load_team(TEAM_DIR / pick["file"])
            except (OSError, ValueError):
                full = {}
            out["standards"] = standards_mod.match(requirement, full)
            out["knowledge"] = self.knowledge_view(str((full.get("knowledge") or {}).get("source") or ""))
            here = self.member_names(full["workspace"]) if full.get("workspace") else names  # as create_run looks
            for r in pick["roles"]:
                r["on_crew"] = None if here is None or not r.get("member") else r["member"] in here
        return out

    async def cleanup_sessions(self) -> dict[str, Any]:
        """清理已结束的会话: delete the Kiro Crew sessions and folders this app opened, except those of a running run and of
        a signed one (a run a person signed off is one to show again: its sessions stay openable)."""
        keep = {r.parent for r in self.runs.values() if not r.ended or r.s.get("signoff")}
        try:
            done = await self.sessions.cleanup(keep)
        except Exception as exc:  # noqa: BLE001
            raise AppError(f"清理会话失败：{exc}"[:300], "cleanup_failed", 502)
        return {"ok": True, **done, "kept_runs": sorted(r.rid for r in self.runs.values() if not r.ended or r.s.get("signoff"))}

    def board(self, rid: str | None = None) -> dict[str, Any]:
        return board.build(self.runs, rid, mgr=self.manager(), scrub=self.scrub, now=time.time(), crew=self)

    def _all_events(self, run: TeamRun) -> list[dict[str, Any]]:
        """Every event of *run* (read again only when it has new ones)."""
        seq = int(run.s.get("seq") or 0)
        got = self._events_cache.get(run.rid)
        if got is None or got[0] != seq:
            got = (seq, store_mod.all_events(self.data_dir / "runs" / run.rid / "events.jsonl"))
            self._events_cache[run.rid] = got
        return got[1]

    async def cto(self) -> dict[str, Any]:
        """CTO 视图: the company's deliveries and what is in progress, with this app's runs in them (cto.py)."""
        try:
            return await asyncio.to_thread(cto_mod.build, self.runs, self._deps.now(), events_of=self._all_events)
        except (OSError, ValueError, KeyError) as exc:
            raise AppError(f"CTO 视图的数据读不了：{exc}"[:300], "cto_data", 500)

    async def cto_flow(self, rid: str) -> dict[str, Any]:
        """交付详情: the 价值流 of one run (cto.flow): its segments, moments and numbers."""
        run = self._run(rid)
        return await asyncio.to_thread(cto_mod.flow, run, self._all_events(run), self._deps.now())

    async def cto_offline(self) -> dict[str, Any]:
        """离线版: the offline page with this moment's data, as {name, html} for the page to save."""
        data = await self.cto()
        stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(self._deps.now()))
        try:
            return await asyncio.to_thread(cto_mod.offline, data, generated=stamp)
        except OSError as exc:
            raise AppError(f"离线版的页面模板读不了：{exc}"[:300], "cto_offline", 500)


CREW_REFRESH_S = 5.0


async def _open_on_this_mac(cmd: list[str]) -> int | None:
    proc = await asyncio.create_subprocess_exec(*cmd, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
                                                stderr=asyncio.subprocess.DEVNULL)
    try:
        return await asyncio.wait_for(proc.wait(), 10)
    except asyncio.TimeoutError:
        return None


def get_or_build(ctx: Any) -> Service:
    name = getattr(ctx, "name", APP_NAME) or APP_NAME
    svc = _REGISTRY.get(name)
    if svc is None:
        svc = Service(ctx)
        _REGISTRY[name] = svc
    elif ctx is not svc.ctx:
        svc.ctx = ctx
    return svc


def current(name: str = APP_NAME) -> Service | None:
    return _REGISTRY.get(name)


def discard(name: str = APP_NAME) -> Service | None:
    return _REGISTRY.pop(name, None)
