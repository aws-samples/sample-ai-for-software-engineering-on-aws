"""The app's stdio MCP client (D17) against a stand-in server: a small script that speaks newline-delimited JSON-RPC
the way the build and bench servers do (MCP Python SDK 2.x), with one tool per case."""

import asyncio
import sys

import pytest

from teamkit import mod

mcpclient = mod("mcpclient")

FAKE_SERVER = r'''
import json, select, sys, time
version = sys.argv[1]

def send(msg):
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()

def text(rid, data, error=False):
    res = {"content": [{"type": "text", "text": data if isinstance(data, str) else json.dumps(data)}]}
    if error:
        res["isError"] = True
    send({"jsonrpc": "2.0", "id": rid, "result": res})

for line in sys.stdin:
    msg = json.loads(line)
    rid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": rid, "result": {"protocolVersion": version, "capabilities": {"tools": {}},
                                                       "serverInfo": {"name": "stand-in", "version": "0"}}})
        continue
    if method != "tools/call":
        continue
    name, args = params["name"], params.get("arguments") or {}
    if name == "echo":
        send({"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": json.dumps(args)}],
                                                       "structuredContent": {"result": args}}})
    elif name == "text_only":
        text(rid, {"outcome": "ok", **args})
    elif name == "refuse":
        text(rid, "Error executing tool refuse: refused: role 'alice' is not granted physical", error=True)
    elif name == "malformed":
        send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": "check: field required"}})
    elif name == "broken":
        send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32603, "message": "internal error"}})
    elif name == "pings":
        send({"jsonrpc": "2.0", "id": "s1", "method": "ping"})
        send({"jsonrpc": "2.0", "id": "s2", "method": "sampling/createMessage", "params": {}})
        replies = [json.loads(sys.stdin.readline()) for _ in range(2)]
        text(rid, {"replies": replies})
    elif name == "slow":
        select.select([sys.stdin], [], [], 30)  # ends early when the client closes our input
        sys.exit(0)
    elif name == "die":
        sys.stderr.write("cannot open the workspace\n")
        sys.stderr.flush()
        sys.exit(4)
'''


@pytest.fixture
def server(tmp_path):
    path = tmp_path / "fake_server.py"
    path.write_text(FAKE_SERVER)

    def argv(version=mcpclient.PROTOCOL_VERSION):
        return [sys.executable, "-I", str(path), version]
    return argv


def run(coro):
    return asyncio.run(coro)


def test_a_call_returns_the_tools_result(server):
    async def go():
        async with mcpclient.StdioClient(server(), env=mcpclient.server_env()) as c:
            assert c.server["serverInfo"]["name"] == "stand-in"
            structured = await c.call_tool("echo", {"check": "build"}, timeout_s=10)
            plain = await c.call_tool("text_only", {"check": "static"}, timeout_s=10)
            return structured, plain
    structured, plain = run(go())
    assert structured == {"check": "build"}  # unwrapped from {"result": {...}}
    assert plain == {"outcome": "ok", "check": "static"}


def test_a_server_of_another_protocol_version_is_refused(server):
    async def go():
        c = mcpclient.StdioClient(server("2024-11-05"))
        with pytest.raises(mcpclient.McpError, match="2024-11-05"):
            await c.start()
        assert c.proc is None
    run(go())


def test_a_refusal_and_a_malformed_call_are_tool_refusals_other_errors_are_not(server):
    async def go():
        async with mcpclient.StdioClient(server()) as c:
            with pytest.raises(mcpclient.ToolRefused, match="not granted physical"):
                await c.call_tool("refuse", timeout_s=10)
            with pytest.raises(mcpclient.ToolRefused, match="field required") as malformed:
                await c.call_tool("malformed", timeout_s=10)
            assert malformed.value.code == -32602
            with pytest.raises(mcpclient.McpError) as broken:
                await c.call_tool("broken", timeout_s=10)
            assert not isinstance(broken.value, mcpclient.ToolRefused) and broken.value.code == -32603
            assert await c.call_tool("echo", {"a": "1"}, timeout_s=10) == {"a": "1"}  # the session goes on
    run(go())


def test_a_timeout_stops_the_server(server):
    async def go():
        c = mcpclient.StdioClient(server())
        await c.start()
        proc = c.proc
        with pytest.raises(mcpclient.McpTimeout, match="no answer within 0.5 s"):
            await c.call_tool("slow", timeout_s=0.5)
        assert c.proc is None and proc.returncode is not None
        with pytest.raises(mcpclient.McpExited):
            await c.call_tool("echo", timeout_s=10)
    run(go())


def test_a_server_that_exits_keeps_its_last_words(server):
    async def go():
        async with mcpclient.StdioClient(server()) as c:
            with pytest.raises(mcpclient.McpExited, match=r"exited with 4 \(cannot open the workspace\)"):
                await c.call_tool("die", timeout_s=10)
    run(go())


def test_a_server_that_cannot_start(tmp_path):
    async def go():
        with pytest.raises(mcpclient.McpExited, match="cannot start"):
            await mcpclient.StdioClient([str(tmp_path / "no-such-server")]).start()
    run(go())


def test_the_client_answers_ping_and_refuses_other_server_requests(server):
    async def go():
        async with mcpclient.StdioClient(server()) as c:
            return await c.call_tool("pings", timeout_s=10)
    ping, other = run(go())["replies"]
    assert ping == {"jsonrpc": "2.0", "id": "s1", "result": {}}
    assert other["id"] == "s2" and other["error"]["code"] == -32601


def test_the_server_environment_keeps_only_what_it_needs(monkeypatch):
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "x")
    monkeypatch.setenv("DOCKER_HOST", "unix:///tmp/alice-docker.sock")
    env = mcpclient.server_env({"EXTRA": "1"})
    assert "AWS_SECRET_ACCESS_KEY" not in env
    assert env["DOCKER_HOST"] == "unix:///tmp/alice-docker.sock" and env["EXTRA"] == "1"
