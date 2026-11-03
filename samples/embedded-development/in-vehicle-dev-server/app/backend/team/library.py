"""知识库 and 需求清单 on the home page and the board: the scenario's knowledge documents the team uses, with figures read
from the files at request time, one of them as text for the read-only viewer, and the findings backlog. Read only;
nothing here writes."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from . import triage as triage_mod
from .httpkit import AppError

MAX_TEXT = 1_000_000  # bytes the viewer gets of one file
CITE_KEYS = ("VSTATD-IF", "CC1-PN", "TR")
_SUBSECTION = re.compile(r"(?:^#+ |\*\*)§(\d+\.\d+)(?![.\d])", re.M)


def _sections(text: str) -> list[dict[str, Any]]:
    return [{"label": "节", "n": len(set(_SUBSECTION.findall(text)))}]


def _spec(text: str) -> list[dict[str, Any]]:
    return _sections(text) + [{"label": "页", "n": text.count("<!-- pagebreak -->") + 1}]


def _facts(text: str) -> list[dict[str, Any]]:
    return [{"label": "条目", "n": len(re.findall(r"^- id: \S+$", text, re.M))}]


def _dbc(text: str) -> list[dict[str, Any]]:
    return [{"label": "报文", "n": len(re.findall(r"^BO_ ", text, re.M))},
            {"label": "信号", "n": len(re.findall(r"^\s*SG_ ", text, re.M))}]


def _vss(text: str) -> list[dict[str, Any]]:
    return [{"label": "信号路径", "n": len(re.findall(r"^  [A-Z][\w.]*:\s*$", text, re.M))}]


def _backlog(text: str) -> list[dict[str, Any]]:
    labels = [c[5].strip() for c in (ln.strip().strip("|").split("|") for ln in text.splitlines() if ln.startswith("| F-"))
              if len(c) > 5]
    return [{"label": "发现", "n": len(labels)}, {"label": "fix", "n": labels.count("fix")},
            {"label": "later", "n": labels.count("later")}]


# path, title, citation key, what it is, how its figures are counted (None: not a text file)
DOCS: tuple[tuple[str, str, str | None, str, Callable[[str], list[dict[str, Any]]] | None], ...] = (
    ("vstatd-interface.md", "vstatd 接口规范", "VSTATD-IF", "网关报文、信号、解码、监督、IPC、错误、运行日志和启动；引用要写页码", _spec),
    ("vstatd-interface.pdf", "vstatd 接口规范（PDF）", None, "上面那份规范的排版版本，分页相同；这里只看 Markdown 版", None),
    ("cc1-platform-notes.md", "CC-1 平台说明", "CC1-PN", "目标、仿真的 CC-1、资源限额、启动顺序、日志格式、工具链和台架", _sections),
    ("team-rules.md", "团队规则", "TR", "C++ 规则、构建选项、分析器设置、分诊规则、修复轮数和完成的定义", _sections),
    ("findings-backlog.md", "静态分析待办", None, "当前版本的静态分析发现，标 fix 的进本批，标 later 的留在待办", _backlog),
    ("cc1-gateway.dbc", "CAN 数据库（DBC）", None, "报文、信号、周期和 SNA 值；规范 §3.1 的表从这里来", _dbc),
    ("vss-mapping.yaml", "VSS 信号映射", None, "每个发布的信号路径（COVESA VSS v6.1 名字）对应哪个 CAN 信号", _vss),
    ("facts/signals.yaml", "事实条目 · 信号", None, "从规范里摘出的每个信号，带页和节", _facts),
    ("facts/messages.yaml", "事实条目 · 报文", None, "从规范里摘出的每个报文，带页和节", _facts),
    ("facts/rules.yaml", "事实条目 · 规则", None, "从规范里摘出的每条规则，带页和节", _facts),
)
TEXT_FILES = {p for p, *_, count in DOCS if count is not None}
BINARY_FILES = {p for p, *_, count in DOCS if count is None}
TITLES = {key: title for _, title, key, *_ in DOCS if key}
PATHS = {key: path for path, _, key, *_ in DOCS if key}


def docs(knowledge: Path) -> list[dict[str, Any]]:
    """KnowledgeDoc: every document, its figures counted from the file now (none when it is missing)."""
    out = []
    for path, title, key, desc, count in DOCS:
        f = Path(knowledge) / path
        present = f.is_file()
        counts: list[dict[str, Any]] = []
        if present and count is not None:
            try:
                counts = count(f.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                present = False
        out.append({"path": path, "title": title, "key": key, "desc": desc, "counts": counts, "present": present,
                    "text": count is not None, "rendered_from": "vstatd-interface.md" if path.endswith(".pdf") else None})
    return out


def read_text(knowledge: Path, rel: Any) -> dict[str, Any]:
    """One listed document as text, for the viewer: a relative path that stays inside *knowledge*, no PDF, <= 1 MB."""
    if not isinstance(rel, str) or not rel or "\x00" in rel or "\\" in rel:
        raise AppError("path 要写知识库里的文件（相对路径）", "invalid_path")
    parts = Path(rel).parts
    if Path(rel).is_absolute() or ".." in parts:
        raise AppError("path 只能是知识库文件夹里的相对路径", "invalid_path")
    if rel in BINARY_FILES:
        raise AppError(f"{rel} 是二进制文件（PDF），这里只能看文字：看 vstatd-interface.md，页码相同", "binary_file", 415)
    if rel not in TEXT_FILES:
        raise AppError(f"{rel} 不是团队用的知识库文档", "not_found", 404)
    root = Path(knowledge).resolve()
    f = (root / rel).resolve()
    if not f.is_relative_to(root):
        raise AppError(f"{rel} 指到了知识库文件夹外面", "invalid_path")
    if not f.is_file():
        raise AppError(f"知识库里没有 {rel}", "not_found", 404)
    if f.stat().st_size > MAX_TEXT:
        raise AppError(f"{rel} 太大了（超过 {MAX_TEXT // 1_000_000} MB）", "too_large", 413)
    data = f.read_bytes()
    if b"\x00" in data:
        raise AppError(f"{rel} 不是文字文件", "binary_file", 415)
    title = next(t for p, t, *_ in DOCS if p == rel)
    return {"path": rel, "title": title, "text": data.decode("utf-8", errors="replace"), "size": len(data)}


def cites(texts: list[str]) -> dict[str, int]:
    """How often each citation key opens a citation (``[VSTATD-IF``, ``[CC1-PN``, ``[TR``) in *texts*."""
    joined = "\n".join(texts)
    return {k: len(re.findall(rf"\[{re.escape(k)}(?![\w-])", joined)) for k in CITE_KEYS}


def backlog_rows(knowledge: Path) -> tuple[list[dict[str, str]], str]:
    """BacklogRow: the backlog's rows (triage.py's parser), and the next free ID, the one TR §4.4 gives the refactor."""
    rows = triage_mod.backlog(Path(knowledge))
    last = max((int(i[2:]) for i in rows), default=0)
    return [{"id": i, **r} for i, r in rows.items()], f"F-{last + 1:03d}"
