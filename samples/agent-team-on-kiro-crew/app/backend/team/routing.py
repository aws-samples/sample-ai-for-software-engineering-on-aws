"""组队: the orchestrator picks a team for a requirement by keywords, the way AWS AI-DLC picks a scope.

Each team file under ``team/`` may name the official scope it follows (``scope``), the words that send a requirement
to it (``keywords``: the official scope's own triggers, plus Chinese words that mean the same) and a ``priority``
(lower wins when several match: a bug fix beats an MVP). English words match on word boundaries ("debug" is not
"bug"), Chinese ones as substrings. Nothing matched: the team marked ``fallback`` (official AI-DLC falls back to
``feature``). The rule is deterministic and shown on the page: no model decides it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .constants import TEAM_DIR

ROSTER = ("aidlc-product-agent", "aidlc-design-agent", "aidlc-architect-agent", "aidlc-quality-agent",
          "aidlc-developer-agent", "aidlc-devsecops-agent", "aidlc-compliance-agent", "aidlc-pipeline-deploy-agent",
          "aidlc-aws-platform-agent", "aidlc-operations-agent", "aidlc-delivery-agent",
          "aidlc-architecture-reviewer-agent", "aidlc-product-lead-agent", "aidlc-composer-agent")


# what each official scope is for, in the words a person would use
SCOPE_TEXT = {"mvp": "新产品的第一版", "feature": "在已有系统上加功能", "bugfix": "修复缺陷", "poc": "概念验证",
              "enterprise": "企业级交付", "security-patch": "安全补丁", "migration": "迁移"}


def _hit(word: str, text: str) -> bool:
    if re.fullmatch(r"[A-Za-z][A-Za-z -]*", word):
        return re.search(rf"(?<![A-Za-z]){re.escape(word)}(?![A-Za-z])", text, re.I) is not None
    return word in text


def roster_of(team: dict[str, Any], team_dir: Path = TEAM_DIR) -> list[dict[str, str]] | None:
    """The company's whole team a team file draws from (``roster``: a ``roster-*.json`` under team/), in its order:
    who could take part, so the page can show who was picked and who sits this one out. None: the team has none."""
    name = team.get("roster")
    if not isinstance(name, str) or not re.fullmatch(r"roster-[\w-]+\.json", name):
        return None
    try:
        people = json.loads((Path(team_dir) / name).read_text(encoding="utf-8")).get("people")
    except (OSError, ValueError, AttributeError):
        return None
    out = [{"key": str(p["key"]), "title": str(p.get("title") or p["key"]), "member": str(p.get("member") or ""),
            "icon": str(p.get("icon") or p["key"])} for p in people or [] if isinstance(p, dict) and p.get("key")]
    return out or None


def teams(team_dir: Path = TEAM_DIR) -> list[dict[str, Any]]:
    """The team files that take part in 组队 (they name a ``scope``), with what the page shows of each."""
    out = []
    for path in sorted(Path(team_dir).glob("team-*.json")):
        try:
            t = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(t, dict) or not t.get("scope"):
            continue
        roles = [r for r in t.get("roles", []) if isinstance(r, dict)]
        agents = sorted({a.strip() for r in roles for a in str(r.get("aidlc_agent") or "").split(",") if a.strip()})
        stages = sorted({s.strip() for r in roles for s in re.split(r"\s*·\s*", str(r.get("stage") or ""))
                         if re.match(r"\d+\.\d+ ", s.strip())}, key=lambda s: [int(x) for x in s.split()[0].split(".")])
        out.append({
            "file": path.name, "name": t.get("name") or path.stem, "scope": t["scope"],
            "keywords": [k for k in t.get("keywords", []) if isinstance(k, str) and k.strip()],
            "priority": int(t.get("priority", 100)), "fallback": bool(t.get("fallback")),
            "routable": t.get("routable", True) is not False,
            "official_stages": t.get("official_stages"),
            "needs_source": bool(t.get("needs_source")), "starter": t.get("starter"), "source": t.get("source") or None,
            "roles": [{"key": r.get("key"), "title": r.get("title"), "phase": r.get("phase") or "",
                       "stage": r.get("stage") or "", "aidlc_agent": r.get("aidlc_agent") or "",
                       "member": r.get("member") or "", "icon": r.get("icon") or r.get("key"),
                       "assignment": r.get("assignment") or r.get("mission") or "", "gate": r.get("gate") == "human",
                       "optional": bool(r.get("optional"))} for r in roles],
            "agents": agents, "stages": [x for x in stages if x not in (t.get("extra_stages") or [])],
            "extra_stages": [x for x in t.get("extra_stages") or [] if isinstance(x, str)],
            "extra_note": str(t.get("extra_note") or ""),
            "people": roster_of(t, team_dir),
        })
    return out


def route(requirement: str, team_dir: Path = TEAM_DIR) -> dict[str, Any]:
    text = requirement or ""
    # a team with "routable": false is kept (and still runs when named) but never picked by its keywords
    found = [t for t in teams(team_dir) if t["routable"]]
    hits = []
    for t in found:
        matched = [k for k in t["keywords"] if _hit(k, text)]
        if matched:
            hits.append((t["priority"], t["file"], t, matched))
    if hits:
        _, _, pick, matched = min(hits, key=lambda h: (h[0], h[1]))
        why = f"AI-DLC {pick['scope']} 流程（{SCOPE_TEXT.get(pick['scope'], pick['scope'])}）"
    else:
        pick = next((t for t in found if t["fallback"]), found[0] if found else None)
        matched = []
        why = f"AI-DLC {pick['scope']} 流程（{SCOPE_TEXT.get(pick['scope'], pick['scope'])}）" if pick else "没有可用的团队"
    others = [{"file": t["file"], "name": t["name"], "scope": t["scope"], "matched": m} for _, _, t, m in sorted(hits, key=lambda h: (h[0], h[1]))
              if pick is None or t["file"] != pick["file"]]
    custom = sorted({r["member"] for t in found for r in t["roles"] if r["member"] and r["member"] not in ROSTER})
    return {"team": pick, "matched": matched, "why": why, "others": others, "roster": list(ROSTER) + custom,
            "teams": [{"file": t["file"], "name": t["name"], "scope": t["scope"], "keywords": t["keywords"]} for t in found]}
