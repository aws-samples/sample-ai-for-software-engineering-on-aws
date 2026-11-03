"""What each role produced, for the board's 产出 view: the task it was given, its full last reply, every tool call it
made, and the files it delivered on its branch (content and diff). ``role="run"`` is the whole product: the run
branch against the requirement commit.

Replies and tool calls are kept on each attempt when it finishes. Runs from before that are filled in on first
look: the reply from KiroCrew's sub-agent manager (it keeps finished agents in memory), the calls from KiroCrew's
live tool-call log.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

from . import gitwork
from .httpkit import AppError
from .sessions import find_agent

RUN = "run"
FILE_MAX = 300_000  # characters of one file (or diff) sent to the page
REPLY_KEEP = 20_000
_LANG = {".md": "markdown", ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".ts": "typescript",
         ".json": "json", ".html": "html", ".htm": "html", ".css": "css", ".sh": "shell", ".yml": "yaml",
         ".yaml": "yaml", ".py": "python", ".txt": "text", ".svg": "xml", ".xml": "xml"}


def lang_of(path: str) -> str:
    name = PurePosixPath(path).name
    if name == "Dockerfile" or name.endswith(".dockerfile"):
        return "dockerfile"
    return _LANG.get(PurePosixPath(name).suffix.lower(), "text")


def safe_path(path: Any) -> str:
    """A repository-relative path as the page sent it, or AppError: no absolute paths, no ``..``, no control chars."""
    if not isinstance(path, str) or not 0 < len(path) <= 400:
        raise AppError("path 不对", "invalid_path")
    p = path.strip().removeprefix("./")
    if not p or p.startswith("/") or "\\" in p or any(ord(c) < 32 for c in p):
        raise AppError("path 不对", "invalid_path")
    if any(part in ("", ".", "..") for part in p.split("/")):
        raise AppError("path 不对", "invalid_path")
    return p


def _where(run: Any, key: str) -> tuple[Path, str | None, str | None]:
    """(the repository, the commit to compare against, the branch holding the deliverable)."""
    s = run.s
    repo = Path(s["repo"])
    if key == RUN:
        return repo, s.get("base"), s.get("branch") if s.get("base") else None
    lane = run.lane(key)
    return repo, lane.get("base_fork") or lane.get("fork"), lane.get("branch")


def _role(run: Any, key: str) -> dict[str, Any]:
    if key != RUN and key not in run.roles:
        raise AppError("没有这个角色", "not_found", 404)
    return run.roles.get(key, {})


def _in_outputs(path: str, outputs: list[str]) -> bool:
    return any(path == o or (o.endswith("/") and path.startswith(o)) for o in outputs)


async def _backfill(run: Any, key: str, mgr: Any, scrub: Any) -> None:
    """Replies of finished attempts that were never kept (older runs), filled in once."""
    attempts = [a for a in run.lane(key)["attempts"] if a.get("agent") and a.get("ended")]
    changed = False
    for a in attempts:
        if a.get("reply") is None and mgr is not None:
            info = find_agent(mgr, a["agent"])
            text = str(getattr(info, "result", "") or getattr(info, "streaming_text", "") or "") if info is not None else ""
            if text:
                a["reply"], changed = scrub(text)[:REPLY_KEEP], True
    if changed:
        await run.save()


def _attempt(a: dict[str, Any], mgr: Any, scrub: Any) -> dict[str, Any]:
    live = not a.get("ended")
    calls = (list(mgr.history(a["agent"])) if mgr is not None and a.get("agent") else []) if live else (a.get("calls") or [])
    snap = a.get("snap") or {}
    return {
        "n": a["n"], "kind": a["kind"], "label": a.get("label") or "", "agent": a.get("agent"),
        "started": a.get("started"), "ended": a.get("ended"), "credits": a.get("credits"), "error": a.get("error"),
        "summary": a.get("summary"), "reply": a.get("reply") or (snap.get("text_tail") if not live else None),
        "task": scrub(a.get("task") or ""), "calls": calls[-400:], "live": live,
    }


async def role_output(run: Any, key: str, *, mgr: Any, scrub: Any) -> dict[str, Any]:
    role = _role(run, key)
    repo, base, ref = _where(run, key)
    if key != RUN and not run.s.get("imported"):  # an imported run's sessions are on the other Mac
        await _backfill(run, key, mgr, scrub)
    writes = key == RUN or bool(role.get("writable"))
    files: list[dict[str, Any]] = []
    head = None
    if writes and base and ref:
        try:
            files = await gitwork.diff_files(repo, base, ref)
            head = (await gitwork.git(repo, "rev-parse", "--short", ref, locks=False))[1].strip() or None
        except gitwork.GitError:
            files = []
    files = [f for f in files if PurePosixPath(f["path"]).name != ".gitkeep"]
    outputs = [o for k in (run.order if key == RUN else [key]) for o in run.roles[k].get("outputs", [])]
    owner = {}
    if key == RUN:
        for f in files:
            owner[f["path"]] = next((k for k in run.order if gitwork.matches(f["path"], run.roles[k].get("writable") or [])), None)
    lane = run.lane(key) if key != RUN else None
    return {
        "run": run.rid,
        "role": key,
        "title": "整个产品" if key == RUN else role["title"],
        "emoji": "📦" if key == RUN else role.get("emoji", ""),
        "status": run.s["status"] if key == RUN else lane["status"],
        "branch": ref,
        "folder": run.s.get("run_wt") if key == RUN else lane.get("worktree"),
        "base": base[:7] if base else None,
        "head": head,
        "writable": [] if key == RUN else list(role.get("writable") or []),
        "files": [{**f, "output": _in_outputs(f["path"], outputs), "owner": owner.get(f["path"]) if key == RUN else key}
                  for f in files],
        "attempts": [] if key == RUN else [_attempt(a, mgr, scrub) for a in lane["attempts"]],
        "ended": run.ended,
    }


async def file_view(run: Any, key: str, path: Any, view: str) -> dict[str, Any]:
    """One file of the role's branch as it stands (``content``) or what the role changed in it (``diff``)."""
    _role(run, key)
    p = safe_path(path)
    if view not in ("content", "diff"):
        raise AppError("view 只能是 content 或 diff", "invalid_view")
    repo, base, ref = _where(run, key)
    if not ref or not base:
        raise AppError("这个角色还没开工", "not_started", 404)
    if view == "diff":
        rc, out, _ = await gitwork.git(repo, "diff", "--no-color", "--no-renames", "--no-ext-diff", base, ref, "--", p,
                                       ok=None, locks=False)
        if rc != 0:
            raise AppError("看不了这个文件的改动", "no_diff", 404)
    else:
        rc, out, _ = await gitwork.git(repo, "show", f"{ref}:{p}", ok=None, locks=False)
        if rc != 0:
            raise AppError("这个分支里没有这个文件（可能被删了）", "no_file", 404)
    binary = "\x00" in out[:8000]
    return {"path": p, "view": view, "lang": "diff" if view == "diff" else lang_of(p), "binary": binary,
            "size": len(out), "truncated": len(out) > FILE_MAX, "text": "" if binary else out[:FILE_MAX]}
