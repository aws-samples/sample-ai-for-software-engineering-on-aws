"""How a tool call is shown: one short line, worktree paths made relative. The calls themselves come from the role
sessions' transcripts (``sessions.py``)."""

from __future__ import annotations

import re

from .constants import WORK_ROOT

_WT_PREFIX = re.compile(re.escape(str(WORK_ROOT)) + r"/runs/[^/\s]+/(?:wt/[^/\s'\";&|)]+|repo)(/|(?=[\s'\";&|)]|$))")
_CD_HERE = re.compile(r"(^|: )cd \.\s*(?:&&|;)\s*")


def short(text: str, limit: int = 120) -> str:
    """One line, worktree paths made relative (a leading ``cd <its worktree> &&`` dropped), at most *limit* characters."""
    text = " ".join(_WT_PREFIX.sub(lambda m: "" if m.group(1) else ".", text).split())
    text = _CD_HERE.sub(lambda m: m.group(1), text, count=1)
    return text if len(text) <= limit else text[: limit - 1] + "…"
