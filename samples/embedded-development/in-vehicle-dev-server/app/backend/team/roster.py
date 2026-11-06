"""组队预览 in the start form (``GET /team``): the default team's roles in flow order, its checks by when they run, and
whether each role's Kiro agent template is installed. Read only: one ``stat`` per template, nothing written."""

from __future__ import annotations

import functools
import json
from pathlib import Path
from typing import Any

from .constants import TEAM_FILE

WHEN = ("before_bench", "after_bench", "release")


def _writable(role: dict[str, Any], titles: dict[str, str], ownership: dict[str, Any]) -> str:
    if role.get("writable_from"):
        by = titles.get(str(ownership.get("from") or ""), "")
        return f"按{by}的分工" if by else "按分工"
    w = [str(x) for x in role.get("writable") or []]
    return "、".join(w) if w else "只读"


def preview(team: dict[str, Any], knowledge: dict[str, Any] | None, agents_dir: Path) -> dict[str, Any]:
    """TeamPreview: roles (TeamRoleView), checks (TeamCheckView), the knowledge source and the templates' files."""
    roles = [r for r in team.get("roles") or [] if isinstance(r, dict)]
    titles = {str(r.get("key")): str(r.get("title") or r.get("key")) for r in roles}
    ownership = team.get("ownership") or {}
    names = sorted({str(r["template"]) for r in roles if r.get("template")})
    templates = [{"name": n, "present": (Path(agents_dir) / f"{n}.json").is_file()} for n in names]
    checks = [{"name": str(c.get("name")), "when": str(c.get("when") or ""), "owner": c.get("owner") or None,
               "max_rounds": int(c.get("max_rounds") or 2)}
              for c in team.get("checks") or [] if isinstance(c, dict) and c.get("when") in WHEN]
    return {
        "name": str(team.get("name") or ""),
        "roles": [{"key": str(r.get("key")), "title": titles[str(r.get("key"))], "icon": str(r.get("icon") or ""),
                   "aidlc_agent": str(r.get("aidlc_agent") or ""), "template": str(r.get("template") or ""),
                   "writable": _writable(r, titles, ownership), "gate": str(r.get("gate_label") or "批准") if r.get("gate") else "",
                   "phase": str(r.get("phase") or "")} for r in roles],
        "checks": checks,
        "templates": templates,
        "knowledge": knowledge,
        "error": "",
    }


@functools.lru_cache(maxsize=8)
def _team_english(path: str, mtime: float) -> tuple[str, dict[str, dict[str, str]]]:
    try:
        team = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "", {}
    fields = ("title_en", "stage_en", "gate_label_en", "mission_en")
    return str(team.get("name") or ""), {str(r.get("key")): {f: str(r.get(f) or "") for f in fields}
                                          for r in team.get("roles") or [] if isinstance(r, dict)}


def english(team_name: Any, key: str, field: str) -> str:
    """*field* (title_en, stage_en, gate_label_en) of role *key* in the team files beside TEAM_FILE whose name is
    *team_name*: a run keeps the team file as it started, and one that started before the file had English names
    gets them from it here. '' when there is none."""
    for path in sorted(TEAM_FILE.parent.glob("team-*.json")):
        try:
            name, roles = _team_english(str(path), path.stat().st_mtime)
        except OSError:
            continue
        if name and name == team_name and key in roles:
            return roles[key].get(field, "")
    return ""
