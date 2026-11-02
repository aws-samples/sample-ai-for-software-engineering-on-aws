"""The triage gate (D4) and the traced commits (D13).

The triage role writes ``triage.json`` in the format of the scenario's checks/README.md ("The approved triage"). The
app checks it by the same rules as checks/lib/common.py's ``load_triage`` (mirrored here, never imported: the checks
are not the app's), except the approval itself, which the app adds at the gate. A malformed file goes back to the role.

At the gate a person is asked only about what needs judgement: each finding the role proposes to justify or defer,
each whose decision differs from its label in the backlog, and each entry the role added (TR §4.4); a justification's
question carries its citations. The fixes are in the gate's document. Once approved, the triage is written beside the
run's repository with ``approved: {by, at}`` and its approval record ``<triage>.sha256``.

From the triage's base on, every commit cites a finding the triage fixes or justifies, and a behaviour fix one of its
fact entries (TR §7.2, checked by checks/trace.sh); the app's merge commits list what the commits they merge cite.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

FINDING_ID = re.compile(r"\bF-\d{3}\b")
DECISIONS = ("fix", "justify", "defer")
EVIDENCE = ("unit-test", "static-analysis", "build")
SPEC = ("VSTATD-IF", "CC1-PN")
DOCS = {"VSTATD-IF": "vstatd-interface.md", "CC1-PN": "cc1-platform-notes.md", "TR": "team-rules.md"}
CITATION = re.compile(r"^\[(?P<doc>VSTATD-IF|CC1-PN|TR)(?: p\.(?P<page>\d+))? §(?P<sec>\d+(?:\.\d+)?)\]$")
AGREE = "A"  # the option of every question that takes the proposal as it is


def backlog(knowledge: Path) -> dict[str, dict[str, str]]:
    """The backlog's rows: ID → tool, check, location, message, label (findings-backlog.md)."""
    rows = {}
    for line in (Path(knowledge) / "findings-backlog.md").read_text(encoding="utf-8").splitlines():
        if line.startswith("| F-"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            rows[cells[0]] = {"tool": cells[1], "check": cells[2], "location": cells[3].replace("`", ""),
                              "message": cells[4], "label": cells[5]}
    return rows


def fact_ids(knowledge: Path) -> set[str]:
    ids: set[str] = set()
    for p in sorted((Path(knowledge) / "facts").glob("*.yaml")):
        ids.update(re.findall(r"^- id: (\S+)$", p.read_text(encoding="utf-8"), re.M))
    return ids


def citation_problem(cite: Any, knowledge: Path, docs: tuple[str, ...]) -> str | None:
    """None when *cite* names a section that exists, on the page it gives (pages end at ``<!-- pagebreak -->``)."""
    m = CITATION.match(str(cite))
    if not m:
        return f"引用 {cite!r} 的写法不对，要写成 [VSTATD-IF p.N §x.y] 或 [CC1-PN §x.y]"
    doc, sec = m.group("doc"), m.group("sec")
    if doc not in docs:
        return f"引用 {cite!r}：这里只能引 {'或'.join(docs)}"
    pages = (Path(knowledge) / DOCS[doc]).read_text(encoding="utf-8").split("<!-- pagebreak -->")
    pattern = re.compile(rf"(?:^#+ |\*\*)§{re.escape(sec)}(?![.\d])", re.M)
    page = next((n for n, text in enumerate(pages, 1) if pattern.search(text)), None)
    if page is None:
        return f"引用 {cite!r}：{DOCS[doc]} 里没有 §{sec}"
    if doc == "VSTATD-IF" and m.group("page") is None:
        return f"引用 {cite!r}：引 VSTATD-IF 要写页码"
    if doc == "VSTATD-IF" and int(m.group("page")) != page:
        return f"引用 {cite!r}：§{sec} 在第 {page} 页"
    return None


def problems(t: Any, knowledge: Path) -> list[str]:
    """What is wrong with a proposed triage, by the rules the checks apply to the approved one (its approval aside)."""
    if not isinstance(t, dict):
        return ["triage.json 不是一个 JSON 对象"]
    out: list[str] = []
    rows, facts = backlog(knowledge), fact_ids(knowledge)
    if not re.fullmatch(r"[0-9a-f]{40}", str(t.get("base", ""))):
        out.append("base 要写需求提交（40 位十六进制）")
    seen: dict[str, dict[str, Any]] = {}
    added: list[int] = []
    for f in t.get("findings") if isinstance(t.get("findings"), list) else []:
        fid = f.get("id") if isinstance(f, dict) else None
        if not isinstance(fid, str) or not re.fullmatch(r"F-\d{3}", fid):
            out.append(f"有一条发现没有 F-nnn 形式的 id：{f!r}"[:200])
            continue
        if fid in seen:
            out.append(f"{fid}：有不止一个决定")
        seen[fid] = f
        decision = f.get("decision")
        if decision not in DECISIONS:
            out.append(f"{fid}：decision 只能是 fix、justify 或 defer")
        if any(not isinstance(f.get(k, []), list) for k in ("cites", "facts")):
            out.append(f"{fid}：cites 和 facts 要写成列表")
            continue
        if "added" in f:
            if not isinstance(f["added"], dict) or not f["added"].get("found_by") or fid in rows:
                out.append(f"{fid}：新加的发现要写 added.found_by（谁发现的），而且不能是待办里已有的编号")
            added.append(int(fid[2:]))
        elif fid not in rows:
            out.append(f"{fid}：待办里没有，也没有按 TR §4.4 标成新加的（added）")
        elif rows[fid]["label"] != "fix":
            out.append(f"{fid}：待办里标的是 {rows[fid]['label']}，不在本批")
        if decision == "fix":
            if f.get("evidence") not in EVIDENCE:
                out.append(f"{fid}：修复要写 evidence：unit-test、static-analysis 或 build（TR §4.1）")
            if not isinstance(f.get("behaviour"), bool):
                out.append(f"{fid}：修复要写 behaviour：true 或 false")
        if decision == "defer" and not (f.get("reason") and f.get("pick_up_when")):
            out.append(f"{fid}：延后要写 reason 和 pick_up_when（TR §4.1）")
        if decision == "justify" and not f.get("cites"):
            out.append(f"{fid}：说明要引 VSTATD-IF 或 CC1-PN 的页和节（TR §4.1）")
        if decision in ("fix", "justify"):
            docs = SPEC if decision == "justify" or f.get("behaviour") else tuple(DOCS)
            out += [f"{fid}：{p}" for p in (citation_problem(c, knowledge, docs) for c in f.get("cites", [])) if p]
        if decision == "fix" and f.get("behaviour") and not (f.get("cites") and f.get("facts")):
            out.append(f"{fid}：涉及行为的修复要引规范的页（cites）并写事实条目（facts）（TR §7.2）")
        unknown = sorted(set(map(str, f.get("facts", []))) - facts)
        if unknown:
            out.append(f"{fid}：知识库里没有这些事实条目：{', '.join(unknown)}")
    first = max((int(i[2:]) for i in rows), default=0) + 1
    if sorted(added) != list(range(first, first + len(added))):
        out.append(f"新加的发现按 TR §4.4 从 F-{first:03d} 起依次编号：" + "、".join(f"F-{n:03d}" for n in sorted(added)))
    out += [f"{fid}：待办里标了 fix，但分诊里没有它的决定（TR §4.1）"
            for fid in sorted(i for i, r in rows.items() if r["label"] == "fix" and i not in seen)]
    for d in t.get("allowed_log_differences") if isinstance(t.get("allowed_log_differences"), list) else []:
        entry = d.get("entry") if isinstance(d, dict) else None
        f = seen.get(d.get("finding")) if isinstance(d, dict) else None
        count = d.get("count", 1) if isinstance(d, dict) else None
        if (not isinstance(entry, dict) or not f or f.get("decision") not in ("fix", "justify")
                or d.get("side") not in ("baseline", "run") or not isinstance(entry.get("ev"), str)
                or not isinstance(count, int) or isinstance(count, bool) or count < 1
                or not isinstance(entry.get("t_ms", 0), int) or isinstance(entry.get("t_ms", 0), bool)):
            out.append(f"allowed_log_differences 里这一条不对（要对应一个修复或说明的发现，写 side、entry.ev，count 为正整数）：{d!r}"[:240])
    for r in t.get("requirements") if isinstance(t.get("requirements"), list) else []:
        if (not isinstance(r, dict) or not r.get("id") or not isinstance(r.get("real_target_only"), bool)
                or not isinstance(r.get("evidence"), list) or not r["evidence"]):
            out.append(f"requirements 里每一条要写 id、real_target_only 和 evidence（检查名的列表）：{r!r}"[:200])
    return out


def _clip(text: Any, n: int) -> str:
    return " ".join(str(text or "").split())[:n]


def questions(t: dict[str, Any], rows: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    """The gate's questions (D4), in the format of a gated role's questions file; option A takes the proposal."""
    out = []
    for f in t["findings"]:
        fid, decision, row = f["id"], f["decision"], rows.get(f["id"])
        where = row["location"] if row else str((f.get("added") or {}).get("location") or "")
        label = f"（待办标的是 {row['label']}）" if row and row["label"] != decision else ""
        if f.get("added"):
            q = f"{fid} 是分诊新加的（{_clip(f['added'].get('found_by'), 40)}），定为 {decision}：{where}"
            opts = ["同意加入本批", "不同意：不加入（退回分诊）"]
            why = _clip(f.get("note") or f.get("reason") or (f["added"].get("tool") or ""), 200)
        elif decision == "justify":
            q = f"{fid} 分诊建议说明为误报或无害、不修{label}：{where}"
            opts = ["同意说明（评审还会复核引用）", "不同意：本批修复（退回分诊补齐证据和行为）"]
            why = _clip(f.get("note") or f.get("reason"), 200)
        elif decision == "defer":
            q = f"{fid} 分诊建议延后{label}：{where}"
            opts = ["同意延后", "不同意：本批修复（退回分诊补齐证据和行为）"]
            why = _clip(f"{f.get('reason') or ''}；什么时候再处理：{f.get('pick_up_when') or ''}", 200)
        elif label:
            q, opts, why = f"{fid} 的决定和待办不同{label}：{decision}，{where}", ["同意", "不同意（退回分诊）"], _clip(f.get("note"), 200)
        else:
            continue
        out.append({"id": fid, "q": _clip(q, 160), "options": [{"key": k, "text": x} for k, x in zip("AB", opts)],
                    "recommend": AGREE, "why": why, "cites": [str(c) for c in f.get("cites") or []]})
    return out


def listed(t: dict[str, Any], rows: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    """The findings the gate asks nothing about: in its document only."""
    asked = {q["id"] for q in questions(t, rows)}
    return [{"id": f["id"], "decision": f["decision"], "evidence": f.get("evidence"), "behaviour": f.get("behaviour")}
            for f in t["findings"] if f["id"] not in asked]


def write(path: Path, t: dict[str, Any]) -> str:
    """The approved triage and its approval record ``<triage>.sha256`` (the SHA-256 the checks compare)."""
    data = (json.dumps(t, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    Path(path).write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    Path(path).with_name(Path(path).name + ".sha256").write_text(digest + "\n", encoding="utf-8")
    return digest


def decided(t: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {f["id"]: f for f in t.get("findings") or [] if isinstance(f, dict) and "id" in f}


def commit_problem(message: str, t: dict[str, Any]) -> str | None:
    """Why a commit after the triage's base would fail checks/trace.sh, or None (TR §7.2)."""
    ids, by = sorted(set(FINDING_ID.findall(message))), decided(t)
    if not ids:
        return "没写发现编号"
    bad = [i for i in ids if (by.get(i) or {}).get("decision") not in ("fix", "justify")]
    if bad:
        return f"引用的 {'、'.join(bad)} 在分诊里不是修复也不是说明"
    for i in ids:
        f = by[i]
        if f["decision"] == "fix" and f.get("behaviour") and not any(
                re.search(rf"\b{re.escape(x)}\b", message) for x in f.get("facts") or []):
            return f"{i} 涉及行为，提交说明要写它的事实条目之一（{'、'.join(f.get('facts') or [])}）"
    return None


def trailer(messages: list[str], t: dict[str, Any]) -> str:
    """What the merged commits cite, for the merge commit: ``Findings: F-003 F-031`` and ``Facts: SUP-GRACE``."""
    text, by = "\n".join(messages), decided(t)
    ids = sorted(set(FINDING_ID.findall(text)))
    facts = sorted({x for i in ids for x in (by.get(i) or {}).get("facts") or [] if re.search(rf"\b{re.escape(x)}\b", text)})
    return "\n".join([f"Findings: {' '.join(ids)}"] + ([f"Facts: {' '.join(facts)}"] if facts else [])) if ids else ""
