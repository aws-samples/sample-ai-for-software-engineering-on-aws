"""命中规范: which of the company's standards (and which of its knowledge-base data) a requirement touches, by keywords,
the same deterministic way 组队 picks a team. The page shows what matched and why; every role's task lists them, and
the roles look the originals up in the Crew knowledge base themselves.

A team names its company's standards file (``standards``: a JSON file in the app, e.g. ``packs/taoyuan/standards.json``):
a list of ``{id, title, kind: "standard" | "data", owner, doc, rules, keywords}``. ``standards_always`` lists the ids
a team always works by (the lottery page always has 抽奖规则 and 个人信息 in it, whatever the wording).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .constants import APP_ROOT


def _hit(word: str, text: str) -> bool:
    if re.fullmatch(r"[A-Za-z][A-Za-z -]*", word):
        return re.search(rf"(?<![A-Za-z]){re.escape(word)}(?![A-Za-z])", text, re.I) is not None
    return word in text


def load(team: dict[str, Any], app_root: Path = APP_ROOT) -> list[dict[str, Any]]:
    name = team.get("standards")
    if not isinstance(name, str) or not name or name.startswith(("/", "~")) or ".." in name.split("/"):
        return []
    try:
        rows = json.loads((app_root / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [r for r in rows if isinstance(r, dict) and isinstance(r.get("id"), str) and r.get("title")]


def match(requirement: str, team: dict[str, Any], app_root: Path = APP_ROOT) -> list[dict[str, Any]]:
    """The standards and data *requirement* touches, in the file's order, each with why."""
    text = requirement or ""
    always = {a for a in team.get("standards_always") or [] if isinstance(a, str)}
    out = []
    for s in load(team, app_root):
        words = [k for k in s.get("keywords") or [] if isinstance(k, str) and k.strip() and _hit(k, text)]
        if not words and s["id"] not in always:
            continue
        out.append({"id": s["id"], "title": s["title"], "kind": s.get("kind") or "standard", "owner": s.get("owner") or "",
                    "doc": s.get("doc") or "", "rules": [r for r in s.get("rules") or [] if isinstance(r, str)],
                    "why": f"需求提到「{'、'.join(words[:3])}」" if words else "这类项目都要遵守"})
    return out


def task_lines(found: list[dict[str, Any]], source: str = "", source_id: str = "") -> str:
    """The part of a role's task that names them: what to look up in the knowledge base (in *source_id* only, if given)."""
    if not found:
        return "（这次需求不涉及公司规范）"
    where = f"知识库来源「{source}」" if source else "知识库"
    scope = f"，带上 `source_id: \"{source_id}\"` 只查这一个来源" if source_id else ""
    lines = [f"这次需求涉及的公司规范和数据（原文在 Kiro Crew {where}里，用 `local_knowledge_search` 按标题查{scope}，不要凭记忆写）："]
    for s in found:
        rules = f"：{'、'.join(s['rules'])}" if s["rules"] else ""
        lines.append(f"- {'数据' if s['kind'] == 'data' else '规范'}《{s['title']}》{rules}")
    return "\n".join(lines)
