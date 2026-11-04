#!/usr/bin/env python3
# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Smoke test of the bench MCP server over stdio, as an agent starts it, on the real bench. It requests no physical
action: it lists the tools, reads the bench, checks that a reviewer's physical call is refused, and with --checks takes
the lease and runs both after-bench checks in their container on the last run in the server's state.

    python3 tests/smoke.py --config <config> [--checks]

Run it with the server's virtual environment (the MCP SDK it pins).
"""
import argparse
import asyncio
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def session(config, role, fn):
    params = StdioServerParameters(command=sys.executable, args=["-I", "-m", "benchserver", "--config", config,
                                                                 "--role", role], cwd=None)
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        return await fn(s)


def payload(result):
    text = "".join(getattr(c, "text", "") for c in result.content)
    try:
        return json.loads(text)
    except ValueError:
        return text


async def reviewer(s):
    tools = sorted(t.name for t in (await s.list_tools()).tools)
    status = payload(await s.call_tool("bench_status", {}))
    actions = payload(await s.call_tool("read_actions", {}))
    deploy = await s.call_tool("request_deploy", {})
    return tools, status, actions, deploy


async def developer(s):
    out = {"lease": payload(await s.call_tool("lease_acquire", {}))}
    for check in ("runtime-limits", "logdiff"):
        r = await s.call_tool("run_check", {"check": check})
        p = payload(r)
        out[check] = {"is_error": r.is_error, "verdict": p.get("verdict") if isinstance(p, dict) else p,
                      "problem": p.get("problem") if isinstance(p, dict) else None}
    out["release"] = payload(await s.call_tool("lease_release", {}))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--checks", action="store_true")
    a = ap.parse_args()
    tools, status, actions, deploy = asyncio.run(session(a.config, "reviewer", reviewer))
    print("tools:", ", ".join(tools))
    print("target:", status["target"], "| supply:", status["supply"])
    print("probe:", status["probe"])
    print("pending:", len(status["pending_requests"]), "| last run:", status["last_run"])
    print("action record entries read:", len(actions["actions"]))
    print("reviewer request_deploy refused:", deploy.is_error, "-", "".join(getattr(c, "text", "") for c in deploy.content)[:120])
    ok = deploy.is_error and len(tools) == 9
    if a.checks:
        out = asyncio.run(session(a.config, "developer", developer))
        print(json.dumps(out, indent=1))
        ok = ok and all(not out[c]["is_error"] and out[c]["verdict"] in ("PASS", "FAIL") for c in ("runtime-limits", "logdiff"))
    print("smoke:", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
