# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Commands for a person at the build server, not exposed over MCP.

    sudo -u buildsrv /opt/buildserver/bin/python -I -m buildserver.admin reset-repair \
        --config /srv/build/config.toml --reason "toolchain fixed by hand"

Resets the count of failed cross builds in a row after a person has decided how the work goes on (TR §5.1). Holds
the server's lock, so it cannot interleave with a build, and records the reset in the audit log, with the person who
ran it (sudo's SUDO_USER) and the user it ran as.
"""

import argparse
import getpass
import os
import sys

from .core import BuildService, ConfigError


def main(argv=None):
    p = argparse.ArgumentParser(prog="buildserver.admin")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("reset-repair")
    r.add_argument("--config", required=True)
    r.add_argument("--reason", required=True)
    args = p.parse_args(argv)
    try:
        service = BuildService(args.config, role="operator")
    except (ConfigError, OSError) as e:
        print(f"buildserver.admin: {e} (run it as the server's user, as in the README)", file=sys.stderr)
        return 2
    with service.exclusive():
        state = service.repair_state(strict=False)
        before = state["cross_build"].get("failures_in_a_row")
        state["cross_build"]["failures_in_a_row"] = 0
        service.save_repair(state)
        service.audit({"tool": "admin.reset-repair", "class": "operator", "outcome": "ok",
                       "args": {"reason": args.reason, "by": os.environ.get("SUDO_USER"), "as": getpass.getuser(),
                                "failures_in_a_row_before": before}})
    print(f"cross-build repair count reset (was {before})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
