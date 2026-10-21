"""交付标签: what a run delivers, as the CTO view counts it — a short name, 类型, 规模 and 业务线.

The run's first gated role proposes them in a small JSON file (a team file role's ``"delivery"``: a path in the run
branch), the person confirms or changes them when approving that gate. Until then, or when the file is missing or wrong,
the team file's ``delivery_defaults`` stand (a team without a gate, the bugfix pair, only ever has those)."""

from __future__ import annotations

import json
import re
import zlib
from pathlib import Path
from typing import Any

KINDS = ("新应用", "新功能", "修复")
SIZES = ("小", "中", "大")
LINES = ("电商", "移动应用", "客户关系管理", "供应链", "内部系统")
NAME_MAX = 20
WHY_MAX = 60
FIELDS = {"kind": KINDS, "size": SIZES, "line": LINES}
# who raises a business line's Issues when a run does not say (an imported run brings its own)
REPORTERS = {"电商": "运营部", "移动应用": "用户体验组", "客户关系管理": "会员运营部", "供应链": "供应链管理部", "内部系统": "行政部"}


def issue_id(rid: str) -> str:
    """A run's Issue number, from its id (stable, and apart from the shipped history's TY-1001…TY-2999)."""
    return f"TY-{3000 + zlib.crc32(rid.encode()) % 7000}"


def pr_number(rid: str) -> int:
    """A run's pull request number, from its id (stable, and apart from the history's #1201…#4999)."""
    return 5000 + zlib.crc32(f"{rid}:pr".encode()) % 5000


def short_name(title: str) -> str:
    """A delivery's name from a requirement's first line: up to its first colon or comma, at most NAME_MAX characters."""
    head = re.split(r"[：:，,。]", " ".join(str(title or "").split()), maxsplit=1)[0].strip()
    return head[:NAME_MAX] or "未命名的交付"


def clean(data: Any, base: dict[str, Any]) -> dict[str, Any]:
    """*base* with every valid field of *data* over it (anything else in *data* is ignored)."""
    out = dict(base)
    if not isinstance(data, dict):
        return out
    for key, allowed in FIELDS.items():
        if data.get(key) in allowed:
            out[key] = data[key]
    name = " ".join(str(data.get("name") or "").split())
    if name:
        out["name"] = name[:NAME_MAX]
    why = " ".join(str(data.get("why") or "").split())
    if why:
        out["why"] = why[:WHY_MAX]
    return out


def defaults(team: dict[str, Any], title: str, *, on_source: bool = False, team_dir: Path | None = None) -> dict[str, Any]:
    """The team file's ``delivery_defaults``; a run that began before teams had them takes those of the team file of the
    same name in *team_dir*; without any: a change to an existing project is a 新功能, anything else a 新应用, 中, 内部系统."""
    base = {"name": short_name(title), "kind": "新功能" if on_source else "新应用", "size": "中", "line": "内部系统", "why": ""}
    dd = team.get("delivery_defaults")
    if not isinstance(dd, dict) and team_dir is not None and team.get("name"):
        dd = _defaults_by_name(team_dir).get(str(team["name"]))
    return clean(dd, base)


def _defaults_by_name(team_dir: Path) -> dict[str, Any]:
    """Every team file's ``delivery_defaults``, by its name (read once per change of the folder)."""
    key = (str(team_dir), max((p.stat().st_mtime for p in team_dir.glob("team*.json")), default=0.0))
    if _by_name.get("key") != key:
        found: dict[str, Any] = {}
        for p in team_dir.glob("team*.json"):
            try:
                t = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(t, dict) and t.get("name") and isinstance(t.get("delivery_defaults"), dict):
                found[str(t["name"])] = t["delivery_defaults"]
        _by_name.update(key=key, found=found)
    return _by_name["found"]


_by_name: dict[str, Any] = {}


def check(team: dict[str, Any]) -> None:
    """A team file's delivery settings, or a ValueError saying what is wrong."""
    dd = team.get("delivery_defaults")
    if dd is not None:
        if not isinstance(dd, dict):
            raise ValueError("team.json：delivery_defaults 要写成 {kind, size, line}")
        for key, allowed in FIELDS.items():
            if key in dd and dd[key] not in allowed:
                raise ValueError(f"team.json：delivery_defaults.{key} 只能是 {'、'.join(allowed)}")
    for r in team.get("roles") or []:
        rel = r.get("delivery")
        if rel is None:
            continue
        if not isinstance(rel, str) or not rel.endswith(".json") or rel.startswith(("/", "~")) or ".." in rel.split("/"):
            raise ValueError(f"team.json：{r.get('key')} 的 delivery 要写成运行分支里的相对路径（.json）")
        if r.get("gate") != "human":
            raise ValueError(f"team.json：{r.get('key')} 写交付标签，它后面要有人的关卡（gate: human）")


def label(d: dict[str, Any]) -> str:
    """One line for events and the gate: 新功能 · 中 · 电商（双十一家电大促）."""
    return f"{d['kind']} · {d['size']} · {d['line']}（{d['name']}）"
