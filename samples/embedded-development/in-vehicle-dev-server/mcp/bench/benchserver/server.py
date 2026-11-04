# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""The `bench` MCP server over stdio. Each tool forwards to BenchService, which holds every guardrail.

    python -m benchserver --config /srv/bench/config.toml --role developer

The role comes from the command line that the agent configuration sets, never from a request. A call to an unknown
tool or with an argument a tool does not take is refused and audited before the SDK sees it.
"""

import argparse
import sys

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.shared.exceptions import MCPError

from .core import CHECKS, BenchService, ConfigError, Refused, end_on_exit

INVALID_PARAMS = -32602


def make_screen(service):
    async def screen(ctx, call_next):
        """Refuses and audits the calls the SDK would reject before a tool function sees them."""
        if ctx.method == "tools/call":
            try:
                params = dict(ctx.params or {})
            except (TypeError, ValueError):
                params = {}
            name, args = params.get("name"), params.get("arguments")
            args = {} if args is None else args
            if not isinstance(args, dict) or BenchService.malformed(name, args):
                try:
                    service.call(name, **(args if isinstance(args, dict) else {"arguments": args}))
                except Refused as e:
                    raise MCPError(INVALID_PARAMS, f"refused: {e}") from None
                except Exception:  # noqa: BLE001 - BenchService.call has audited it
                    raise MCPError(INVALID_PARAMS, "refused: malformed call") from None
                raise MCPError(INVALID_PARAMS, "refused: malformed call")
        return await call_next(ctx)
    return screen


def make_server(service):
    server = MCPServer(
        name="bench",
        instructions=("Tools for the emulated CC-1 bench. Take the lease first. Each deploy, restart and replay waits "
                      "until a person approves it at the operator console for the build's digest; a refusal or no "
                      "answer is final, do not retry it on your own. Only the build the build server judged PASS "
                      "can be deployed. After a replay, run the after-bench checks. When the target is unknown, only "
                      "reads work until a person reconciles it. Calls the role does not allow are refused."),
        middleware=[make_screen(service)],
    )

    def guarded(tool, /, **args):
        try:
            return service.call(tool, **args)
        except Refused as e:
            raise ToolError(f"refused: {e}") from None
        except RuntimeError as e:
            raise ToolError(str(e)) from None

    @server.tool(description="The target's state, supply and KL15, the lease, the requests waiting at the operator "
                             "console, the installed build and the last run. Read-only.")
    def bench_status() -> dict:
        return guarded("bench_status")

    @server.tool(description="The last entries of the bench's action record. Read-only.")
    def read_actions() -> dict:
        return guarded("read_actions")

    @server.tool(description="An after-bench check's last published result and the tail of its log. Read-only. "
                             "check: One of: " + ", ".join(CHECKS) + ".")
    def read_result(check: str) -> dict:
        return guarded("read_result", check=check)

    @server.tool(description="Take the target for this session. Refused while another session holds it. "
                             "Controlled write.")
    def lease_acquire() -> dict:
        return guarded("lease_acquire")

    @server.tool(description="Give the target back. Controlled write.")
    def lease_release() -> dict:
        return guarded("lease_release")

    @server.tool(description="Run an after-bench check on the last replay and the baseline, with fixed arguments, in "
                             "a sandbox. Returns the verdict (0 PASS, 1 FAIL, 3 BLOCKED). Needs the lease. "
                             "check: One of: " + ", ".join(CHECKS) + ".")
    def run_check(check: str) -> dict:
        return guarded("run_check", check=check)

    @server.tool(description="Deploy the build the build server judged PASS. Waits for a person's approval at the "
                             "operator console. Needs the lease. Physical.")
    def request_deploy() -> dict:
        return guarded("request_deploy")

    @server.tool(description="Restart vstatd with the installed, approved build. Waits for a person's approval. "
                             "Needs the lease. Physical.")
    def request_restart() -> dict:
        return guarded("request_restart")

    @server.tool(description="Replay the bench's recorded drive into a new run. Waits for a person's approval. "
                             "Needs the lease. Physical.")
    def request_replay() -> dict:
        return guarded("request_replay")

    return server


def main(argv=None):
    p = argparse.ArgumentParser(prog="benchserver")
    p.add_argument("--config", required=True)
    p.add_argument("--role", required=True)
    args = p.parse_args(argv)
    try:
        service = BenchService(args.config, args.role)
    except ConfigError as e:
        print(f"benchserver: {e}", file=sys.stderr)
        return 2
    end_on_exit(service)  # a session that ends stops what it started and gives the target back
    make_server(service).run("stdio")
    return 0
