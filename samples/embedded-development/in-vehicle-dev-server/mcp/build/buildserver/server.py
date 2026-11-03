# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""The `build` MCP server over stdio. Each tool forwards to BuildService, which holds every guardrail.

    python -m buildserver --config /srv/build/config.toml --role developer

The role comes from the command line that the agent configuration sets, never from a request. Arguments are plain
strings so that every value reaches BuildService, which checks it against its fixed lists and audits the call; a
call to an unknown tool or with an argument a tool does not take is refused and audited before the SDK sees it.
"""

import argparse
import sys

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.shared.exceptions import MCPError

from .core import CHECKS, LOG_KINDS, PROFILES, TARGETS, BuildService, ConfigError, Refused

INVALID_PARAMS = -32602


def make_screen(service):
    async def screen(ctx, call_next):
        """Refuses and audits the calls the SDK would otherwise reject before a tool function sees them: unknown
        tools, arguments that are not an object, extra or missing arguments, values that are not strings."""
        if ctx.method == "tools/call":
            try:
                params = dict(ctx.params or {})
            except (TypeError, ValueError):
                params = {}
            name, args = params.get("name"), params.get("arguments")
            args = {} if args is None else args
            if not isinstance(args, dict) or BuildService.malformed(name, args):
                try:
                    service.call(name, **(args if isinstance(args, dict) else {"arguments": args}))
                except Refused as e:
                    raise MCPError(INVALID_PARAMS, f"refused: {e}") from None
                except Exception:  # noqa: BLE001 - BuildService.call has audited it
                    raise MCPError(INVALID_PARAMS, "refused: malformed call") from None
                raise MCPError(INVALID_PARAMS, "refused: malformed call")  # not reached: BuildService refuses these
        return await call_next(ctx)
    return screen


def make_server(service):
    server = MCPServer(
        name="build",
        instructions=("Build tools for the vstatd work tree on the build server. Configure and build a profile, run "
                      "one of the team's checks on the committed HEAD with its fixed arguments, and read results and "
                      "logs. A check's verdict is its exit status: 0 PASS, 1 FAIL, 3 BLOCKED. Calls the role does "
                      "not allow are refused."),
        middleware=[make_screen(service)],
    )

    def guarded(tool, **args):
        try:
            return service.call(tool, **args)
        except Refused as e:
            raise ToolError(f"refused: {e}") from None
        except RuntimeError as e:
            raise ToolError(str(e)) from None

    one_of = lambda values: "One of: " + ", ".join(values) + "."  # noqa: E731

    @server.tool(description="HEAD, branch and uncommitted changes of the work tree. Read-only.")
    def workspace_status() -> dict:
        return guarded("workspace_status")

    @server.tool(description="Configure a build profile of the work tree with CMake, in a sandbox (cross uses the "
                             "project's toolchain file). Controlled write. profile: " + one_of(PROFILES))
    def configure(profile: str) -> dict:
        return guarded("configure", profile=profile)

    @server.tool(description="Build a configured profile with Ninja, in a sandbox. Cross builds stop after the first "
                             "attempt and the retries of TR §5.1 have failed, until a person resets the count. "
                             "Controlled write. profile: " + one_of(PROFILES) + " target: " + one_of(TARGETS))
    def build(profile: str, target: str = "all") -> dict:
        return guarded("build", profile=profile, target=target)

    @server.tool(description="Run one of the team's checks on a clean clone of the committed HEAD, with its fixed "
                             "arguments, in a sandbox. Returns the verdict. check: " + one_of(CHECKS))
    def run_check(check: str) -> dict:
        return guarded("run_check", check=check)

    @server.tool(description="Read a check's last published result and the tail of its log. Read-only. check: "
                             + one_of(CHECKS))
    def read_result(check: str) -> dict:
        return guarded("read_result", check=check)

    @server.tool(description="Read the tail of the last configure or build log of a profile. Read-only. kind: "
                             + one_of(LOG_KINDS) + " profile: " + one_of(PROFILES))
    def read_log(kind: str, profile: str) -> dict:
        return guarded("read_log", kind=kind, profile=profile)

    return server


def main(argv=None):
    p = argparse.ArgumentParser(prog="buildserver")
    p.add_argument("--config", required=True)
    p.add_argument("--role", required=True)
    args = p.parse_args(argv)
    try:
        service = BuildService(args.config, args.role)
    except ConfigError as e:
        print(f"buildserver: {e}", file=sys.stderr)
        return 2
    make_server(service).run("stdio")
    return 0
