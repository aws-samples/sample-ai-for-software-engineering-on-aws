#!/usr/bin/env python3
# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Smoke test of the build MCP server over stdio, as an agent reaches it, in the build environment:

    python3 tests/smoke.py --config /srv/build/config.toml [--full]
    python3 tests/smoke.py --config /srv/build/config.toml --probe

Run it with the Python of the server's virtual environment, where the server is installed (README, Running). Starts
`python -I -m buildserver --config <config> --role developer` and calls each tool once: workspace_status,
configure and build (host; with --full also cross and `run_check build`), read_result and read_log. Prints one line
per call and exits non-zero when a call does not return what it should. A check's verdict is reported, not judged.

--probe tests the sandbox instead. It never touches the configured work tree or state: it clones the work tree and
writes a config of its own under a new folder next to the state. In the clone it commits project code that tries,
at configure and build time and from a background process that leaves its session, to write the server's audit log,
repair count and published results, the work tree, the server user's home and a host path; to reach the network;
and to forge the build check's result, also after the check has written it. The background process writes five
times a second for twelve seconds. It also sets a
`core.fsmonitor` hook in the clone's git config. It then runs
configure, build and `run_check build` and asserts that none of these got through and that no background process
still writes once the calls have returned.
"""

import argparse
import asyncio
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib

from mcp import Client
from mcp.client.stdio import StdioServerParameters

HERE = pathlib.Path(__file__).resolve().parent
TOOLS = {"workspace_status", "configure", "build", "run_check", "read_result", "read_log"}

# Runs inside the sandbox from the project's CMakeLists.txt. $1 is the report file, the rest are paths to try.
PROBE_SH = r"""#!/bin/sh
out=$1; shift
for t in "$@"; do
  if ( echo probe-wrote >> "$t" ) 2>/dev/null; then echo "WROTE $t"; else echo "denied $t"; fi
done >> "$out"
if python3 -c 'import socket; socket.create_connection(("1.1.1.1", 443), 3)' 2>/dev/null; then
  echo "WROTE network" >> "$out"; else echo "denied network" >> "$out"; fi
d=$PWD res=/nonexistent
for i in 1 2 3 4 5; do
  d=$(dirname "$d")
  [ "$(basename "$d")" = results ] && res=$d && echo "found the results folder $d" >> "$out"
done
echo '{"check": "build", "verdict": "PASS", "forged": true}' > "$out.forge"
# Leaves its session and keeps forging the build check's result and writing the targets.
setsid sh -c "i=0; while [ \$i -lt 60 ]; do date +%s >> '$out.late'; cp '$out.forge' '$res/build.json' 2>/dev/null; \
  for t in $*; do echo late >> \"\$t\"; done; i=\$((i+1)); sleep 0.2; done" >/dev/null 2>&1 < /dev/null &
exit 0
"""


def payload(result):
    if getattr(result, "structured_content", None):
        return result.structured_content
    for part in result.content:
        text = getattr(part, "text", None)
        if text:
            try:
                return json.loads(text)
            except ValueError:
                return {"text": text}
    return {}


def toml_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        return "[" + ", ".join(toml_value(x) for x in v) + "]"
    return json.dumps(str(v))


def dump_toml(cfg, prefix=""):
    lines, tables = [], []
    for k, v in cfg.items():
        (tables if isinstance(v, dict) else lines).append((k, v))
    out = "".join(f"{k} = {toml_value(v)}\n" for k, v in lines)
    for k, v in tables:
        out += f"\n[{prefix}{k}]\n" + dump_toml(v, f"{prefix}{k}.").lstrip("\n")
    return out


class Session:
    def __init__(self, client):
        self.client, self.failures = client, 0

    def judge(self, good, line):
        self.failures += not good
        print(f"{'PASS' if good else 'FAIL'} {line}")

    async def call(self, name, args, expect):
        r = await self.client.call_tool(name, args)
        data = payload(r)
        short = {k: data[k] for k in ("outcome", "exit_status", "verdict", "head", "problem") if k in data}
        if r.is_error:
            short["error"] = str(data.get("text", data))[:200]
        self.judge(not r.is_error and expect(data), f"{name} {json.dumps(args)} -> {json.dumps(short)}")
        return data


def server_params(config):
    return StdioServerParameters(command=sys.executable,
                                 args=["-I", "-m", "buildserver", "--config", str(config), "--role", "developer"])


async def smoke(config, full):
    async with Client(server_params(config)) as client:
        s = Session(client)
        tools = {t.name for t in (await client.list_tools()).tools}
        s.judge(tools == TOOLS, f"tools: {sorted(tools)}")
        await s.call("workspace_status", {}, lambda d: len(d.get("head", "")) == 40)
        await s.call("configure", {"profile": "host"}, lambda d: d.get("outcome") == "ok")
        await s.call("build", {"profile": "host", "target": "vstatd"}, lambda d: d.get("outcome") == "ok")
        await s.call("read_log", {"kind": "build", "profile": "host"}, lambda d: "log_tail" in d)
        if full:
            await s.call("configure", {"profile": "cross"}, lambda d: d.get("outcome") == "ok")
            await s.call("run_check", {"check": "build"}, lambda d: d.get("verdict") in ("PASS", "FAIL", "BLOCKED"))
            await s.call("read_result", {"check": "build"}, lambda d: (d.get("result") or {}).get("check") == "build")
            rel = await s.call("run_check", {"check": "release"}, lambda d: d.get("verdict") in ("FAIL", "BLOCKED"))
            missing = [x for x in (rel.get("result") or {}).get("reasons", []) if "went missing" in x]
            s.judge(not missing, f"release finds every input the published results recorded: {missing or 'ok'}")
        else:
            await s.call("read_result", {"check": "build"}, lambda d: "result" in d)
    return s.failures


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


async def probe(config):
    cfg = tomllib.loads(pathlib.Path(config).read_text())
    if cfg.get("sandbox", {}).get("runner", "docker") != "docker":
        print("FAIL --probe tests the docker sandbox; the config does not use it")
        return 1
    workspace, state = pathlib.Path(cfg["paths"]["workspace"]), pathlib.Path(cfg["paths"]["state"])
    root = pathlib.Path(tempfile.mkdtemp(prefix="buildserver-probe-", dir=state.parent))
    work, pstate, outside = root / "work", root / "state", root / "outside-canary"
    home_canary = pathlib.Path.home() / ".buildserver-probe-canary"
    marker = root / "fsmonitor-ran"
    print(f"probe folder {root}")
    subprocess.run(["git", "clone", "-q", "--no-hardlinks", workspace, work], check=True)
    g = ["git", "-C", work, "-c", "user.name=probe", "-c", "user.email=probe@example.invalid"]
    (work / "probe.sh").write_text(PROBE_SH)
    (work / "probe.sh").chmod(0o755)
    (work / "fsmonitor.sh").write_text(f"#!/bin/sh\ntouch {marker}\n")
    (work / "fsmonitor.sh").chmod(0o755)
    targets = [pstate / "audit.jsonl", pstate / "repair.json", pstate / "results" / "build.json",
               pstate / "results" / "planted.json", pstate / "logs" / "host.build.log", work / "planted",
               home_canary, outside]
    call = " ".join(f'"{t}"' for t in targets)
    with open(work / "CMakeLists.txt", "a") as f:
        f.write("\n# build-server probe: tries to leave the sandbox (tests/smoke.py --probe)\n"
                f'execute_process(COMMAND "${{CMAKE_SOURCE_DIR}}/probe.sh" "${{CMAKE_BINARY_DIR}}/probe.txt" {call}\n'
                '                WORKING_DIRECTORY "${CMAKE_BINARY_DIR}")\n'
                f'add_custom_target(probe ALL COMMAND "${{CMAKE_SOURCE_DIR}}/probe.sh" '
                f'"${{CMAKE_BINARY_DIR}}/probe-build.txt" {call})\n')
    subprocess.run([*g, "add", "-A"], check=True)
    subprocess.run([*g, "commit", "-qm", "probe"], check=True)
    subprocess.run(["git", "-C", work, "config", "core.fsmonitor", str(work / "fsmonitor.sh")], check=True)

    cfg["paths"]["workspace"], cfg["paths"]["state"] = str(work), str(pstate)
    pconfig = root / "config.toml"
    pconfig.write_text(dump_toml(cfg))

    async with Client(server_params(pconfig)) as client:
        s = Session(client)
        await s.call("workspace_status", {}, lambda d: len(d.get("head", "")) == 40)
        await s.call("configure", {"profile": "host"}, lambda d: d.get("outcome") in ("ok", "failed"))
        await s.call("build", {"profile": "host", "target": "all"}, lambda d: "outcome" in d)
        before = {t: digest(t) for t in targets[:3]}
        check = await s.call("run_check", {"check": "build"}, lambda d: d.get("verdict") != "PASS")
        late = {f: f.stat().st_size for f in pstate.rglob("probe*.txt.late")}
        print(f"     every call has returned; {len(late)} background writer(s) left traces; waiting 6 s")
        time.sleep(6)
        published = await s.call("read_result", {"check": "build"}, lambda d: True)
        after = {f: f.stat().st_size for f in pstate.rglob("probe*.txt.late")}
        s.judge(bool(late) and after == late,
                f"the session-leaving background writers stopped with their sandbox: {len(late)} started, "
                f"{sum(after.get(f, 0) != n for f, n in late.items()) + len(set(after) - set(late))} still writing")

        reports = sorted(pstate.rglob("probe*.txt"))
        lines = [ln for r in reports for ln in r.read_text().splitlines()]
        s.judge(bool(lines), f"the probe ran in the sandbox: {len(reports)} report(s), {len(lines)} line(s)")
        wrote = sorted({ln for ln in lines if ln.startswith("WROTE")})
        s.judge(not wrote, f"nothing outside the build folder was writable or reachable: {wrote or 'ok'}")
        for t in targets[5:]:
            s.judge(not t.exists(), f"not created: {t}")
        audit = (pstate / "audit.jsonl").read_text()
        s.judge("probe" not in audit, "audit log has no probe lines")
        repair = json.loads((pstate / "repair.json").read_text())
        s.judge("probe" not in json.dumps(repair) and repair["cross_build"]["failures_in_a_row"] == 1,
                f"repair count is the server's: {repair['cross_build']}")
        for t in (pstate / "results" / "planted.json",):
            s.judge(not t.exists(), f"not created: {t}")
        result = published.get("result") or {}
        s.judge(not result.get("forged") and result.get("verdict") != "PASS",
                f"the forged PASS was not published: published verdict {result.get('verdict')}, "
                f"call verdict {check.get('verdict')} {check.get('problem', '')}")
        s.judge(not marker.exists(), "the work tree's core.fsmonitor hook did not run")
        print(f"     changed by the server itself, as expected: "
              f"{[str(t.name) for t, d in before.items() if d != digest(t)]}")
        print("     probe report lines: " + "; ".join(sorted(set(lines))))
    for t in (home_canary, outside):
        t.unlink(missing_ok=True)
    if not s.failures:
        subprocess.run(["chmod", "-R", "u+rwX", root], check=False)
        shutil.rmtree(root, ignore_errors=True)
        print(f"removed {root}")
    else:
        print(f"kept {root} for inspection")
    return s.failures


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--config", required=True)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--full", action="store_true", help="also configure cross and run checks/build.sh")
    mode.add_argument("--probe", action="store_true", help="try to leave the sandbox, on a throwaway clone")
    args = p.parse_args()
    config = pathlib.Path(args.config).resolve()
    failures = asyncio.run(probe(config) if args.probe else smoke(config, args.full))
    print(f"\n{failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
