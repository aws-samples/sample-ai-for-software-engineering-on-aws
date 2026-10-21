"""aidlc-team: lifecycle hooks (``on_startup`` / ``on_shutdown``).

``on_startup`` gets the same ctx as the routes; ``on_shutdown`` gets a fresh one, so the service is looked up by
app name. Shutdown drops the synthetic modules so the next enable re-reads the code from disk.
"""

from __future__ import annotations

import importlib
import importlib.machinery
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

# --- bootstrap (verbatim in backend/hooks.py) ------------------------------- #

_BACKEND_DIR = Path(__file__).resolve().parent
_NS = "_aidlcteam_backend"
_REQUIRED = ("service", "handlers")


def teardown_namespace() -> None:
    """Drop this app's synthetic modules so the next import re-reads the files from disk."""
    prefix = f"{_NS}."
    for key in [k for k in sys.modules if k == _NS or k.startswith(prefix)]:
        sys.modules.pop(key, None)


def bootstrap() -> dict[str, ModuleType]:
    """Import ``team.service`` and ``team.handlers`` through the private namespace."""
    for final in (False, True):
        root = sys.modules.get(_NS)
        if root is not None and list(getattr(root, "__path__", ())) != [str(_BACKEND_DIR)]:
            teardown_namespace()
            root = None
        if root is None:
            spec = importlib.machinery.ModuleSpec(_NS, None, is_package=True)
            root = importlib.util.module_from_spec(spec)
            root.__path__ = [str(_BACKEND_DIR)]  # type: ignore[attr-defined]
            sys.modules[_NS] = root
        try:
            mods = {name: importlib.import_module(f"{_NS}.team.{name}") for name in _REQUIRED}
        except BaseException:
            teardown_namespace()
            raise
        if all(mods.values()):
            return mods
        teardown_namespace()
        if final:
            raise ImportError(f"{_NS}.team imported incompletely")
    raise AssertionError("unreachable")  # pragma: no cover


_mods = bootstrap()
service = _mods["service"]
handlers = _mods["handlers"]

# --- end bootstrap ---------------------------------------------------------- #


async def on_startup(ctx) -> None:  # noqa: ANN001 - host contract
    await service.get_or_build(ctx).start()


async def on_shutdown(ctx) -> None:  # noqa: ANN001 - host contract
    name = getattr(ctx, "name", "aidlc-team")
    try:
        svc = service.discard(name)
        if svc is not None:
            await svc.stop()
    finally:
        teardown_namespace()
