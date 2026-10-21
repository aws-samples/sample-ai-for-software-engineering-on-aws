import asyncio
from types import SimpleNamespace

from http_fakes import FakeWeb, FakeRequest  # noqa: F401  (stdlib-only aiohttp fakes)

import backend.routes as routes


class Route:
    def __init__(self, method, path, handler):
        self.method, self.path, self.handler = method, path, handler


def build(owner=True):
    ctx = SimpleNamespace(name="aidlc-team", logger=None, data_dir="/tmp/kcteam-test")
    svc = routes.service.get_or_build(ctx)
    return {(r.method, r.path): r.handler for r in routes.handlers.build_routes(svc, Route, web=FakeWeb(), is_owner=lambda _r: owner)}


def call(handler, **req):
    return asyncio.run(handler(FakeRequest(**req), None))


def test_health_needs_no_login():
    resp = call(build()[("GET", "/health")])
    assert resp.status == 200 and resp.body["ok"] is True
