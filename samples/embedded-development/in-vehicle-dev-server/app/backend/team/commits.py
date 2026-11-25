"""How big each commit of a run is (D18): its changed lines, how many of them git sees as moved, and the rest. Reported
on the scorecard, the sign-off card and in the reviewer's task; nothing is judged on it (no check, no send-back).

Commits: the non-merge commits of ``base..HEAD`` on the run branch, oldest first. The app's own commits are listed
apart and not counted: ``[run] …`` (a gate decision, a merge) and the subject ``[role] （app 代提交）`` exactly
(gitwork.commit_leftovers: it starts with the role's tag too, so it is recognised before the role is read).

Moved lines, a fixed algorithm (same git, same numbers)::

    git -c color.diff.oldMoved=blue -c color.diff.newMoved=yellow -c color.diff.oldMovedAlternative=blue
        -c color.diff.newMovedAlternative=yellow show --format= --color=always --color-moved=zebra
        --color-moved-ws=allow-indentation-change <sha>

then each ``+``/``-`` line is counted by the colour it starts with: blue or yellow is moved, red or green is not
(headers are bold, so they are neither). ``lines`` = added + removed, ``not_moved`` = ``lines`` - ``moved``. git only
marks a block as moved when it has at least 20 letters or digits (its own minimum), so a shorter move counts as not
moved and the not-moved figure is usually high. A block copied to several places counts every copy as moved, though: a
6-line block removed from one file and added to two others is 18 lines, 18 moved, 0 not moved.

Each run is measured once, into ``results/commit-sizes.json`` beside its repository with the HEAD it was taken at, and
again when HEAD moves. Once the run has ended, HEAD is compared one last time and the file marked ``final``; after that
it is read as it is while HEAD stays where it was measured (a run resumed after it ended may merge more). A measurement
that fails is not tried again until HEAD moves. An imported run has no repository here: None.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import statistics
from pathlib import Path
from typing import Any

from . import gitwork

FILE = "commit-sizes.json"  # in the run's results directory
APP_SUBJECT = re.compile(r"^\[[\w.-]+\] （app 代提交）$")  # gitwork.commit_leftovers' subject, exactly
SHOWN = 60  # commits the reviewer's table lists
COLOURS = ("-c", "color.diff.old=red", "-c", "color.diff.new=green", "-c", "color.diff.meta=bold",
           "-c", "color.diff.oldMoved=blue", "-c", "color.diff.newMoved=yellow",
           "-c", "color.diff.oldMovedAlternative=blue", "-c", "color.diff.newMovedAlternative=yellow")
MOVED_SHOW = ("show", "--format=", "--color=always", "--color-moved=zebra", "--color-moved-ws=allow-indentation-change")
_LINE = re.compile(r"\x1b\[(3[1-4])m[+-]")  # a diff line's first colour: 31 red, 32 green, 33 yellow, 34 blue
_FILE = re.compile(r"^(?:\x1b\[[0-9;]*m)*diff --git ", re.M)
_TAG = re.compile(r"^\[([\w.-]+)\]\s*")
_IDS = re.compile(r"^(?:F-\d{3}[\s、,，/]*)+")  # the finding IDs the subject starts with, after its tag
_FAILED: dict[str, str] = {}  # results directory → the HEAD its measurement failed at (not tried again there)


def count(colored: str) -> dict[str, int]:
    """One commit's ``git show --color-moved`` output (the command above) → files, lines, moved, not_moved."""
    lines = moved = 0
    for line in colored.split("\n"):
        m = _LINE.match(line)
        if m:
            lines += 1
            moved += m.group(1) in ("33", "34")
    return {"files": len(_FILE.findall(colored)), "lines": lines, "moved": moved, "not_moved": lines - moved}


def parse_subject(subject: str) -> dict[str, Any]:
    """{app, role, findings} of a commit subject: ``[dev-fix] F-018、F-016 parse_interval …`` → dev-fix, both IDs."""
    if subject.startswith("[run]") or APP_SUBJECT.match(subject):
        return {"app": True, "role": None, "findings": []}
    tag = _TAG.match(subject)
    rest = subject[tag.end():] if tag else subject
    ids = _IDS.match(rest)
    findings = list(dict.fromkeys(re.findall(r"F-\d{3}", ids.group(0)))) if ids else []
    return {"app": False, "role": tag.group(1) if tag else None, "findings": findings}


async def measure(cwd: Path | str, base: str, head: str) -> dict[str, Any]:
    """The commits of ``base..head`` and their sizes (read only: no lock taken, nothing written in *cwd*)."""
    _, log, _ = await gitwork.git(cwd, "log", "--no-merges", "--reverse", "--format=%H%x1f%s%x1e", f"{base}..{head}",
                                  locks=False)
    commits: list[dict[str, Any]] = []
    app: list[dict[str, Any]] = []
    for rec in log.split("\x1e"):
        parts = rec.strip("\n").split("\x1f")
        if len(parts) != 2:
            continue
        sha, subject = parts
        who = parse_subject(subject)
        if who["app"]:
            app.append({"sha": sha[:7], "subject": subject[:200]})
            continue
        _, out, _ = await gitwork.git(cwd, *COLOURS, *MOVED_SHOW, sha, locks=False)
        commits.append({"sha": sha[:7], "subject": subject[:200], "role": who["role"], "findings": who["findings"],
                        **count(out)})
    return {"base": base[:12], "head": head, "commits": commits, "app": app}


def load(results: Path) -> dict[str, Any] | None:
    try:
        got = json.loads((Path(results) / FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return got if isinstance(got, dict) and isinstance(got.get("commits"), list) else None


def _write(results: Path, data: dict[str, Any]) -> None:
    results.mkdir(parents=True, exist_ok=True)
    tmp = results / f"{FILE}.{secrets.token_hex(4)}.tmp"  # the scorecard and the run's tick may write at once
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, results / FILE)


async def ensure(results: Path, cwd: Path | str, base: str, *, moving: bool = True) -> dict[str, Any] | None:
    """The run's commit sizes, measured again only when HEAD has moved since they were kept. *moving* False (a run that
    has ended): a file marked ``final`` is read as it is while HEAD is still the one it was taken at (a resumed run may
    have merged more since); otherwise it is measured again if HEAD moved, then marked ``final``. None, without git
    trying again, while HEAD stays where a measurement failed (the error is raised the first time only)."""
    kept = load(results)
    head = await gitwork.head(cwd)
    if kept is not None and not moving and kept.get("final") and kept.get("head") == head:
        return kept
    if _FAILED.get(str(results)) == head:
        return None
    if kept is not None and kept.get("head") == head:
        data = kept
    else:
        try:
            data = await measure(cwd, base, head)
        except Exception:
            _FAILED[str(results)] = head
            raise
        _FAILED.pop(str(results), None)
    if not moving:
        data = {**data, "final": True}
    if data is not kept:
        await asyncio.to_thread(_write, Path(results), data)
    return data


def summary(data: dict[str, Any] | None) -> dict[str, Any] | None:
    """The scorecard's figures: how many commits, the most and the median of their not-moved lines, the biggest one."""
    rows = (data or {}).get("commits") or []
    if not rows:
        return None
    big = max(rows, key=lambda c: int(c.get("not_moved") or 0))
    return {"commits": len(rows), "max_not_moved": int(big.get("not_moved") or 0),
            "median_not_moved": statistics.median(int(c.get("not_moved") or 0) for c in rows),
            "max_sha": big.get("sha")}


def table(data: dict[str, Any] | None) -> str:
    """The reviewer's table of the batch's commits, oldest first ("" with none)."""
    rows = (data or {}).get("commits") or []
    if not rows:
        return ""
    out = ["本批的提交（app 统计；搬移行按 git 的 moved 检测，见 D18）：", "",
           "| 提交 | 角色 | 发现 | 文件 | 行数 | 搬移 | 非搬移 | 提交说明原文 |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for c in rows[:SHOWN]:
        subject = str(c.get("subject") or "").replace("|", "\\|")
        out.append(f"| {c['sha']} | {c.get('role') or ''} | {'、'.join(c.get('findings') or [])} | {c['files']} | "
                   f"{c['lines']} | {c['moved']} | {c['not_moved']} | {subject} |")
    if len(rows) > SHOWN:
        out.append(f"（还有 {len(rows) - SHOWN} 个提交没列出：`git log --no-merges {data['base']}..HEAD`）")
    if data.get("app"):
        out.append(f"另有 {len(data['app'])} 个 app 自己的提交（关卡决定、合入、代提交）没有列出。")
    return "\n".join(out)
