# `bench` MCP server

The agents' only way to act on the emulated CC-1 ([scenario page, section 4](../../README.md#4-tool-connectors-with-guardrails)):
lease the target, read its state, request a deploy, a restart and the drive replay, and run the after-bench checks on
the replay. The guardrails live in the server, whatever the agent session allows. It is the companion of the
[`build` server](../build/README.md) and follows its design: roles from the command line, closed arguments, one call at
a time, a JSONL audit log, a container for everything that reads what the agents' code produced.

The physical gate, the approval at the operator console and the action record are the bench's own
([bench/README.md](../../bench/README.md)): the server calls `bench/cc1.sh`, which waits until a person approves the
action for that build's digest at `bench/console.py`. The server adds what the bench does not know: who is asking, a
lease, which build may be deployed, and checks on the replay that the agents cannot change.

## Tools

| Tool | Permission class | What it does |
| --- | --- | --- |
| `bench_status` | read-only | The target's state (`off`, `known`, `busy`, `unknown`) and why, the supply and KL15, the lease, the requests waiting at the console, the build installed and the last run |
| `read_actions` | read-only | The last entries of the bench's action record |
| `read_result` | read-only | An after-bench check's last published result and the tail of its log |
| `lease_acquire` | controlled-write | Takes the target for this session, for the configured time; refused while another session holds it |
| `lease_release` | controlled-write | Gives the target back |
| `run_check` | controlled-write | `runtime-limits` or `logdiff` on the last replay and the baseline, with fixed arguments, in a container; returns the verdict from the exit status |
| `request_deploy` | physical | Deploys the build that the `build` server's `checks/build.sh` judged PASS: its stripped `vstatd`, whose SHA-256 must be the digest that check recorded. Waits for the person's approval at the console |
| `request_restart` | physical | Restarts `vstatd` with the installed build, which must be the approved one. Waits for the approval |
| `request_replay` | physical | Replays the bench's recorded drive into a new run folder of the server's state. Waits for the approval |

No tool takes a command, a path, a digest, a drive, a check option or a limit. No tool approves, refuses or
reconciles: that stays at the operator console. The bench owner's commands of `bench/cc1.sh` (`start`, `stop`,
`reset`, `ssh`, `put`, the baseline replay) are not offered.

## Guardrails

| Guardrail | How |
| --- | --- |
| Deny by default | A call runs only when the server's role grants the tool's permission class (`read-only`, `controlled-write`, `physical`). The role is the `--role` of the command line that the agent configuration sets, never part of a request; an unknown role is granted nothing |
| Closed arguments | Only `run_check` takes an argument, from a fixed list. An unknown tool, an extra or missing argument or a value that is not a string is refused and audited before the SDK would reject it |
| A lease | Physical calls and `run_check` need the lease. One session holds it at a time; it lapses after `lease.ttl_s` without a call and is renewed by each physical call. The holder is the server process, so two agent sessions never share it |
| Only a judged build | `request_deploy` takes the build from the `build` server's published results: `build.json` with verdict PASS, not `--local`, and `artifacts/vstatd` whose SHA-256 is that result's digest. It copies the file into its own state before `cc1.sh` sees it, so nothing can swap it between the check and the deploy |
| A person approves each action | `cc1.sh` passes the physical gate, writes a request with the digest, and waits for a decision at the console; no answer before the timeout is a refusal. The request names the server and its role as the requester (`CC1_REQUESTER`) |
| No retries | A refusal, a timeout or a failure is returned as it is. After an interrupted or failed action the bench reports the target `unknown` and refuses everything but reads until a person reconciles it at the console |
| Results that are this run's | The after-bench checks read what the agents' build produced on the target, so they run in a container like the `build` server's (no network, read-only root, no capabilities, only the run, the baseline, the triage and the sample mounted read-only). A result is published only when it names the check, agrees with the exit status, and recorded the run and baseline the server gave it, with their SHA-256 unchanged; otherwise an `ERROR` record is published in its place |
| The server's paths are not the agents' | The server refuses to start when its configuration, state, the bench state, the sample, the baseline or the triage folder could be written or replaced by someone other than root or the server's user |
| Audit | Every call appends a `started` line and an outcome line (`ok`, `failed`, `timeout`, `refused`, `error`) to `audit.jsonl`: time, role, tool, class, arguments, exit status, duration, and for an action its request ID and digest. A refusal before the call starts has the outcome line only. The bench's action record holds the approvals |
| One call at a time | Calls hold one lock across threads and processes; malformed calls are refused without waiting for it |
| Clean environment | `cc1.sh` gets `PATH`, `HOME`, `LANG`, the bench state, the approval timeout, the requester and what the docker client needs; nothing else of the server's environment |

## Plan

Each step ends with its verification. Steps 1 to 7 are done (2026-11-04); what is not verified yet is at
[Not yet verified](#not-yet-verified).

1. **Service and configuration** (`benchserver/core.py`): `BenchService(config, role)`, the path checks of the
   `build` server, roles and classes, the audit log, the lock, `call()` with `malformed()`. *Verify:* tests for an
   unknown role, an unsafe path, a malformed call, a refused class, the audit lines.
2. **Reads** through `cc1.sh target|supply|probe` and the bench's own state files (requests, action record).
   *Verify:* tests with a stand-in `cc1.sh` and bench state.
3. **Lease** in the server's state (`lease.json`, holder, expiry). *Verify:* a second service is refused while the
   first holds it; an expired lease can be taken; release by another holder is refused.
4. **Physical actions** through `cc1.sh deploy|restart|replay`, with the build taken from the `build` server's
   results. *Verify:* deploy refused without a PASS build, with `--local`, with a digest mismatch, without the lease;
   a refusal at the console and a timeout reach the agent as refusals and are not retried.
5. **After-bench checks** in the container, with the publish rules above. *Verify:* fixed arguments; a forged or
   stale result becomes `ERROR`; no run yet is refused.
6. **MCP layer** (`benchserver/server.py`), the same screening as the `build` server's. *Verify:* over the SDK's
   in-memory client, when the SDK is installed.
7. **Documentation**: this page's Running, Tests and Not yet verified; the scenario page.

## Configuration

[`config.example.toml`](config.example.toml): the paths (the sample's `bench/` and `checks/`, the server's state, the
bench state, the `build` server's published results, the baseline, the approved triage), the container image and its
limits for the checks, the roles and their classes, the lease time and the timeouts.

## Running

As for the `build` server, on the bench host, with Docker and Python 3.11 or later, as root once:

```bash
useradd --system --create-home benchsrv && usermod -aG docker benchsrv
python3 -m venv /opt/benchserver && /opt/benchserver/bin/pip install /srv/sample/mcp/bench
```

`benchsrv` owns the server's state and the bench state (`CC1_BENCH_STATE`); it can read the `build` server's
published results and the baseline. The agents' user may start the server as `benchsrv` with one fixed command line
per role, and nothing else as that user:

```text
agent ALL=(benchsrv) NOPASSWD: /opt/benchserver/bin/python -I -m benchserver --config /srv/bench/config.toml --role developer
```

```json
{
  "mcpServers": {
    "bench": {
      "command": "sudo",
      "args": ["-n", "-u", "benchsrv", "/opt/benchserver/bin/python", "-I", "-m", "benchserver",
               "--config", "/srv/bench/config.toml", "--role", "developer"]
    }
  },
  "tools": ["@bench"]
}
```

The MCP client's tool timeout must be longer than the console's approval timeout (`timeouts.approval`, 300 s by
default), since a physical call waits for the person.

The person keeps `bench/console.py` open as the bench owner to approve, refuse and reconcile. Running the server as
the agents' own user works for a trial; then the agents' shell can write the bench state and reach Docker directly,
and the guardrails hold only against what goes through the server.

## Tests

```bash
python3 tests/test_guardrails.py                    # the guardrails, with a stand-in cc1.sh and checks and no container
python3 tests/smoke.py --config <config> [--checks]  # over MCP stdio on the real bench; requests no physical action
```

`test_guardrails.py` runs the server logic with a stand-in `cc1.sh` that answers like the real one, and stand-in
after-bench checks without a container (`sandbox.runner = "none"`, accepted only with
`BENCHSERVER_UNSANDBOXED_FOR_TESTS=1`). Its MCP-layer tests need the MCP SDK and are skipped without it. The smoke
test starts the server as an agent would: as a reviewer it lists the tools, reads the bench and the action record and
is refused a deploy; with `--checks`, as a developer, it takes the lease and runs both after-bench checks in their
container on the last run in the server's state.

Last run on 2026-11-04 on an Apple Silicon Mac with Docker Desktop, Python 3.13 and MCP Python SDK 2.3.0, as the
user who owns the bench: 26 guardrail tests OK (24 and 2 skipped without the SDK). The smoke test over stdio read the
running emulated CC-1 (target `known`, supply 13.5 V and KL15 on, the installed digest), was refused `request_deploy`
as a reviewer, and with a copy of the first delivery's replay (`r11032637`) in its state ran `runtime-limits` (PASS,
peak RSS 5896 of 8192 KiB) and `logdiff` (PASS, 328 of 328 entries paired) in the `vstatd-build:arm64` container, in
7 s.

## Not yet verified

- A deploy, a restart and a replay through the server on the real bench, each approved at the operator console. The
  tests cover them with a stand-in `cc1.sh`; the smoke test requests no physical action.
- The server as a user of its own (`benchsrv`), started by the agents' user through sudo; the run above was as the
  bench owner's own user, so the path checks only met that user's folders.
- A Linux bench host.

## Open, for the 11/6 sync

- **Where the after-bench results go.** `checks/release.sh` reads every result from one results folder. This server
  publishes `runtime-limits` and `logdiff` into its own state. Proposed: the `build` server's `run_check release`
  takes this server's published results folder as one more read-only input, so neither server writes the other's
  records.
- **The baseline.** Made by the bench owner with `cc1.sh replay --kind baseline` and kept read-only for the server;
  not a tool.
- **The Kiro Crew app.** It calls `cc1.sh` itself today. Switching it to these tools, and the Kiro Crew members to
  the `build` and `bench` servers, is the trust-boundary question of the sync.
- **Repeated replays** for the repeatability runs: each one is a separate approval; whether a person may approve a
  batch for one digest is not decided.
