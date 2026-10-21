"""aidlc-team: in-gateway route entry point (``backend.hooks.routes = backend.routes:register_routes``).

KiroCrew loads this file by path and calls ``register_routes(ctx) -> list[AppRoute]``. The app's code lives in
``backend/team/`` and is imported through a private namespace package, so its relative imports resolve the same
way in the gateway and in tests. The bootstrap block is duplicated verbatim in ``backend/hooks.py`` (the host loads
the two files as unrelated modules).
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


def register_routes(ctx):  # noqa: ANN001, ANN201 - host contract
    from kiro_crew.apps.route_registry import AppRoute  # host module, always present in the gateway

    svc = service.get_or_build(ctx)
    routes = handlers.build_routes(svc, AppRoute)
    ctx.logger.info("aidlc-team: %d routes registered", len(routes))
    return routes
