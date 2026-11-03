"""Each run on disk: ``runs/<rid>/run.json`` (its whole state, replaced atomically) and ``events.jsonl`` (appended).

Both are written together, off the event loop; events go first, so a crash in between leaves events whose ``seq``
is ahead of run.json, which ``load_all`` reconciles.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

RID_RE = re.compile(r"^r[0-9a-z]{4,24}$")


class Store:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def write(self, rid: str, state_text: str, event_lines: list[str]) -> None:
        """Blocking: call it in a thread."""
        if not RID_RE.match(rid):
            raise ValueError(f"bad run id {rid!r}")
        d = self.root / rid
        d.mkdir(parents=True, exist_ok=True)
        if event_lines:
            with (d / "events.jsonl").open("a", encoding="utf-8") as fh:
                fh.write("".join(event_lines))
        tmp = d / f".run.json.{os.getpid()}.tmp"
        tmp.write_text(state_text, encoding="utf-8")
        os.replace(tmp, d / "run.json")

    def load_all(self, keep: int = 200) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
        """Every readable run with its latest *keep* events. Blocking: call it in a thread."""
        out = []
        if not self.root.is_dir():
            return out
        for d in sorted(self.root.iterdir()):
            if not (d.is_dir() and RID_RE.match(d.name)):
                continue
            try:
                state = json.loads((d / "run.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(state, dict) or state.get("id") != d.name:
                continue
            events = _tail_events(d / "events.jsonl", keep)
            if events:
                state["seq"] = max(int(state.get("seq") or 0), int(events[-1].get("seq") or 0))
            out.append((state, events))
        return out


def all_events(path: Path) -> list[dict[str, Any]]:
    """Every event of a run, oldest first (a replay plays them all)."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if isinstance(ev, dict) and "seq" in ev:
            out.append(ev)
    seen: dict[int, dict[str, Any]] = {}
    for ev in out:  # a restart may have appended an event twice: the later copy wins
        seen[int(ev["seq"])] = ev
    return [seen[k] for k in sorted(seen)]


def _tail_events(path: Path, keep: int) -> list[dict[str, Any]]:
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - 2_000_000))
            lines = fh.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return []
    events = []
    for line in lines[-keep - 1:]:
        try:
            ev = json.loads(line)
        except ValueError:
            continue  # a torn first or last line
        if isinstance(ev, dict) and "seq" in ev:
            events.append(ev)
    return events[-keep:]
