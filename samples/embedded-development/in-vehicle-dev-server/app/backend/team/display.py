"""What a reply shows of this Mac and of the people on it, decided when it is sent (nothing recorded changes).

- **The home folder** is always written ``~``: every string of every JSON reply and of a downloaded trail
  (``/Users/<name>/workplace/…`` → ``~/workplace/…``).
- **Presentation mode** (``?present=zh|en``, set by the board's 演示模式 / Presentation mode switch): the people's
  names are their role, 负责人 or Release owner: the signer, who registered a finding, who decided at a gate or the
  console, the audit trail's 谁 column, a name inside a text, and this Mac's user name; ``user@host (tty)`` and the
  host name go too.

The names come from the records (``by``, ``requested_by``, ``set_by`` …) and from this Mac (``getpass.getuser()``,
the account's full name), so a name inside a text is found without knowing the text's wording.
"""

from __future__ import annotations

import contextvars
import getpass
import os
import pwd
import re
import socket
from pathlib import Path
from typing import Any, Callable, Iterable

OWNER = {"zh": "负责人", "en": "Release owner"}
PRESENT: contextvars.ContextVar[str] = contextvars.ContextVar("vstatd_present", default="")
# Words a record's "by" holds that are no person's name
_NOT_NAMES = {"负责人", "release", "owner", "bench", "tools", "app", "台架", "操作台", "kiro", "crew", "看板", "vstatd-team",
              "the", "console", "person", "人", "you", "bench tools"}


def home_prefixes() -> list[str]:
    """The home folder as the records may spell it: as it is and resolved (longest first)."""
    home = str(Path.home())
    out = {home.rstrip("/")}
    try:
        out.add(os.path.realpath(home).rstrip("/"))
    except OSError:
        pass
    return sorted((h for h in out if len(h) > 1), key=len, reverse=True)


def this_mac_names() -> set[str]:
    out = set()
    try:
        out.add(getpass.getuser())
    except Exception:  # noqa: BLE001 - no user name: nothing to hide
        pass
    try:
        gecos = pwd.getpwuid(os.getuid()).pw_gecos.split(",,")[0].strip()
        if gecos:
            out.add(gecos)
    except (KeyError, OSError):
        pass
    return {n for n in out if n}


def host_names() -> set[str]:
    out = set()
    try:
        host = socket.gethostname()
        out |= {host, host.split(".")[0]}
    except OSError:
        pass
    return {h for h in out if len(h) >= 3 and h.lower() not in ("localhost",)}


_SPLIT = re.compile(r"[@（(，,\s]")
_IN_BOARD = re.compile(r"看板（([^，,）)]+)")


def names_in(by: str) -> set[str]:
    """The person's name(s) in a record's ``by``: ``lilinll``, ``lilinll@host (tty)``, ``lilinll（在 Kiro 会话里…）``,
    ``Kiro Crew 看板（lilinll，vstatd-team）``."""
    by = str(by or "").strip()
    out = set(_IN_BOARD.findall(by))
    first = _SPLIT.split(by, 1)[0].strip()
    if first and not by.startswith("Kiro Crew"):
        out.add(first)
    return {n for n in out if len(n) >= 2 and n.lower() not in _NOT_NAMES}


class View:
    """How one reply is shown: the home folder always; the people as their role in presentation mode."""

    def __init__(self, present: str = "", names: Iterable[str] = ()) -> None:
        self.homes = home_prefixes()
        self.present = present if present in OWNER else ""
        self.owner = OWNER.get(self.present, "")
        found = set(names) | this_mac_names() if self.present else set()
        self.names = sorted(found, key=len, reverse=True)
        self.hosts = sorted(host_names(), key=len, reverse=True) if self.present else []
        self._rx: re.Pattern[str] | None = None
        if self.names:
            alt = "|".join(re.escape(n) for n in self.names)
            host = "|".join(re.escape(h) for h in self.hosts) or r"(?!)"
            # a name, with what may follow it (@host or @domain, a terminal); a name inside a word of Latin letters
            # (annotate for ann) is left alone, one between - . / is not (a folder or a file named after the user)
            self._rx = re.compile(rf"(?<![A-Za-z0-9_])(?:{alt})(?:@(?:{host}|[\w.-]+))?(?:\s*\(/dev/[^)]*\))?(?![A-Za-z0-9_])")
        self._host = re.compile("|".join(rf"(?<![\w.-]){re.escape(h)}(?![\w-])" for h in self.hosts)) if self.hosts else None

    def text(self, s: str) -> str:
        for h in self.homes:
            if h in s:
                # a command shows it quoted when the path has a space ('/Users/x/a b'): ~/'a b' still expands
                s = re.sub(rf"'{re.escape(h)}/", "~/'", s)
                s = re.sub(rf"{re.escape(h)}(?=/|$|[^\w.-])", "~", s)
        if self._rx is not None:
            s = self._rx.sub(self.owner, s)
        if self._host is not None:
            s = self._host.sub("this-mac", s)
        return s

    def __call__(self, data: Any) -> Any:
        """A copy of *data* with every string (keys too) shown this way; *data* is not changed."""
        if isinstance(data, str):
            return self.text(data)
        if isinstance(data, dict):
            return {(self.text(k) if isinstance(k, str) else k): self(v) for k, v in data.items()}
        if isinstance(data, (list, tuple)):
            return [self(v) for v in data]
        return data


def current(names: Callable[[], Iterable[str]] = lambda: ()) -> View:
    """The view of the reply being built (PRESENT is set per request by the route guard)."""
    present = PRESENT.get()
    return View(present, names() if present else ())
