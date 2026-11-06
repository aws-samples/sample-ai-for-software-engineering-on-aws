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
| A lease | Physical calls and `run_check` need the lease. One session holds it at a time; it lapses after `lease.ttl_s` without a call and is renewed by each physical call. The holder is the server process, so two agent sessions never share it; a lease whose holder process is gone can be taken at once |
| Only a judged build | `request_deploy` takes the build from the `build` server's published results: `build.json` with verdict PASS, not `--local`, and `artifacts/vstatd` whose SHA-256 is that result's digest. It copies the file into its own state before `cc1.sh` sees it, so nothing can swap it between the check and the deploy |
| A person approves each action | `cc1.sh` passes the physical gate, writes a request with the digest, and waits for a decision at the console; no answer before the timeout is a refusal. The request names the server, its role and the session as the requester (`CC1_REQUESTER`, unique per session). The call's request is the one in the bench's action record, written during the call, that names this session (and, for a deploy, this build's digest); whether it was refused comes from the decision and gate entries with that request's ID, not from the log, which also holds what the target printed. An approved action the bench did not begin (the target busy) is a refusal: nothing ran |
| No retries | A refusal, a timeout or a failure is returned as it is. After an interrupted or failed action the bench reports the target `unknown` and refuses everything but reads until a person reconciles it at the console |
| Results that are this run's | The after-bench checks read what the agents' build produced on the target, so they run in a container like the `build` server's (no network, read-only root, no capabilities, only the run, the baseline, the triage and the sample mounted read-only). A result is published only when it names the check, agrees with the exit status, and recorded the run and baseline the server gave it, with their SHA-256 unchanged; otherwise an `ERROR` record is published in its place |
| The server's paths are not the agents' | The server refuses to start when its configuration, state, the bench state, the sample, the baseline (its folder and files) or the triage (its folder, `triage.json` and its `.sha256`) could be written or replaced by someone other than root or the server's user. `trust.readers` names the users who may also own the `build` server's published results and the triage (`buildsrv`), for those two paths only |
| Audit | Every call appends a `started` line and an outcome line (`ok`, `failed`, `timeout`, `refused`, `error`) to `audit.jsonl`: time, role, tool, class, arguments, exit status, duration, and for an action its request ID and digest. A refusal before the call starts has the outcome line only, a malformed call's arguments capped (20, each 200 characters, in the reason too); an argument named `tool` or `self` is refused like any other unexpected one. The bench's action record holds the approvals |
| A session that ends ends its actions | When the server exits or gets SIGTERM, SIGHUP or SIGINT (an MCP client that goes away closes stdin, then terminates the server), it stops the `cc1.sh` and container clients it started, audits the call in progress as `error`, gives the lease back and exits without waiting for the call. A request still waiting at the console is then answered by nobody and expires; an approved action in progress is ended, and the bench marks the target `unknown` until a person reconciles it |
| One call at a time | Calls that change something hold one lock across threads and processes; reads take none, so the bench and the requests waiting at the console can be read while an action waits for its approval; each read has a log of its own, and a check's published result is replaced and read under a short lock of its own, so a read never sees half of it. Malformed calls are refused without waiting for the lock |
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
published results and the baseline. The published results and the triage belong to `buildsrv`: name it in
`trust.readers` (the example does), or the server refuses to start. The agents' user may start the server as
`benchsrv` with one fixed command line per role, and nothing else as that user:

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
user who owns the bench: 44 guardrail tests OK (41 and 3 skipped without the SDK). The smoke test over stdio read the
running emulated CC-1 (target `known`, supply 13.5 V and KL15 on, the installed digest), was refused `request_deploy`
as a reviewer, and with a copy of the first delivery's replay (`r11032637`) in its state ran `runtime-limits` (PASS,
peak RSS 5896 of 8192 KiB) and `logdiff` (PASS, 328 of 328 entries paired) in the `vstatd-build:arm64` container, in
7 s.

A deploy and a replay through the server on the real bench, 2026-11-04, same machine and user: an MCP client over
stdio with the developer role took the lease, called `request_deploy` with the first delivery's signed-off build
(the `build` result of `r11032637`'s rerun, PASS, digest `4cbb3cb4b7ad…`), then `request_replay`, then both
after-bench checks on that replay, then released the lease. A person approved each request (on the Kiro Crew board,
which records itself as the decider in the action record); the deploy read the digest back, the replay wrote
`run-1` into the server's state, `runtime-limits` gave PASS (peak RSS 5844 of 8192 KiB, baseline 5860, 3 threads)
and `logdiff` PASS (328 of 328 entries paired, no difference). `audit.jsonl` has an `ok` line for each of the nine
calls with the two request IDs and the digest; the deploy and the replay each took about 72 s, most of it the wait
for the approval.

Seen on a first attempt, before the run above, and fixed since (*A session that ends ends its actions*, and the
lease row): when the MCP client went away while `request_deploy` waited for the approval, the server ended but its
`cc1.sh deploy` stayed alive and still waiting, so an approval then would have deployed with nobody recording the
outcome; the request was refused at the console. The lease of that session stayed in `lease.json` until its expiry
(30 minutes), so a new session was refused until it was removed by hand. Two tests reproduce it: a client over stdio
that gives up mid-deploy, and a server terminated mid-deploy; both failed before the fix.

On a Linux bench host, 2026-11-06: Ubuntu 24.04 on x86_64 (8 vCPUs), Docker 29.8.2, QEMU 8.2.2 in the runner image,
Python 3.12 and MCP Python SDK 2.3.0, as the bench owner's own user. A script played the person at
`bench/console.py`'s command line throughout (`approve <id> --digest <first 6 characters>` or `refuse <id> --reason
…`, about 3 s after the request appeared); no person answered any request. `bench/build-target.sh` built the target
image and sysroot in 68 minutes (first build), `bench/doctor.sh` reported ready, and the target was up 33 s after
`cc1.sh start`. The build was the `build` server's PASS result of a batch of
[rehearsal/build-server-run/](../../rehearsal/build-server-run/README.md) (stand-in sysroot, digest
`fa471f3d1cf7…`); the bench owner's user deployed it and recorded the baseline with `cc1.sh`. Then, five times, an
MCP client over stdio played the agent. As a reviewer, `request_deploy` was refused. As a developer, it took the
lease and called `request_deploy` (approved, digest read back), `request_restart` (refused at the console: returned
as a refusal and not retried), `request_restart` again (approved), `request_replay` (approved), both after-bench
checks and `lease_release`. Every physical call behaved as expected in all five runs; from call to result, including
the wait for the answer, a deploy took 6.6 to 6.9 s, a restart 5.7 to 5.9 s and a replay 17 to 20 s.
`runtime-limits` gave PASS in all five (peak RSS 5896 and 5832 of 6400 KiB in the first and the last run, baseline
5820, 3 threads). `logdiff` gave FAIL in all five, each time for one or two order changes: a `SIGNAL_TIMEOUT` and a
`SIGNAL_VALUE` of another message that fell on the same millisecond (see [Open questions](#open-questions)); in the
first and the last run all 348 baseline entries paired with no other difference. The batch's final build keeps the
F-008 wrong fix of its step 6, which writes timeouts at start-up and after the reconnection that a correct build
does not (at 334 ms and 20436 ms in this baseline). The first run's `audit.jsonl` has 19 lines (9 `started`, 7 `ok`,
2 `refused`, 1 `failed`: the `logdiff` FAIL).

Then with a build that has no seeded wrong fix, the same day and host: the reference project with only the right
toolchain repair (F-031, the sysroot), built by the `build` server (PASS, digest `8608714a2e61…`), a new baseline
recorded with it, and five more runs of the same sequence. All 55 rows were as expected: `logdiff` PASS in all five
(328 of 328 baseline entries paired, no difference, no order change) and `runtime-limits` PASS (peak RSS 5836 to
5872 of 6400 KiB, baseline 5932, 3 threads). Against that baseline, one run of the batch's build with the F-008
wrong fix gave `logdiff` FAIL with 20 unexplained differences and no order change: the timeouts and recoveries of
five messages after the start (from 93 ms) and again after the reconnection (from 20195 ms), only in the run. The
log comparison catches the wrong fix on this host, as
[rehearsal/check-examples/](../../rehearsal/check-examples/README.md) says it should.

On that host the guardrail tests pass (44 OK) with `umask 022` and a temporary folder of the user's own with mode
755. With Ubuntu's default `umask 002`, or with `TMPDIR=/tmp`,
`test_trusted_readers_own_the_build_results_and_the_triage_only` fails or errors: when it pretends to be another
user, the path check refuses a group-writable folder on the path, or the sticky `/tmp` holding another user's
folder, as "writable by other users" before it reaches the owner check the test expects. The server refuses those
paths as it should; the test's expected message is narrower than the check.

## Not yet verified

- The server as a user of its own (`benchsrv`), started by the agents' user through sudo; the runs above were as the
  bench owner's own user, so the path checks only met that user's folders.
- `test_trusted_readers_own_the_build_results_and_the_triage_only` under `umask 002` or `TMPDIR=/tmp`: the test
  expects the owner message where the check first finds a writable folder.

## Open questions

- **Where the after-bench results go.** `checks/release.sh` reads every result from one results folder. This server
  publishes `runtime-limits` and `logdiff` into its own state. Proposed: the `build` server's `run_check release`
  takes this server's published results folder as one more read-only input, so neither server writes the other's
  records.
- **The baseline.** Made by the bench owner with `cc1.sh replay --kind baseline` and kept read-only for the server;
  not a tool.
- **The Kiro Crew app.** It calls `cc1.sh` itself today. Switching it to these tools, and the Kiro Crew members to
  the `build` and `bench` servers, is the open trust-boundary question.
- **Approval on the board.** The board approved this server's requests as it approves the app's own: it is open to
  any request at the console, which is what the scenario page's demo advice says.
- **Two steps in one millisecond.** `logdiff` takes the baseline entries with the same `t_ms` as one decoding step
  and keeps their order (CC1-PN §6.3; `checks/lib/check_logdiff.py` groups by equal `t_ms`). A timeout and another
  message's decoding step can fall on the same millisecond, and VSTATD-IF §7.3 orders entries within one decoding
  step or one timeout, not between a timeout and another message's decoding step; on the Linux host their order
  changed between the baseline and a run of the same build. Those collisions involve timeouts that the F-008 wrong
  fix writes, in both the baseline and the run; with a correct build, five runs on that host had no order change. A
  correct build can still meet it when its one timeout, `BCM_Exterior`'s after the reconnection, lands on another
  message's decoding step. Proposed: change CC1-PN §6.3 and the check so that the order rule applies to the entries
  of one message (a `SIGNAL_TIMEOUT` with that message's `SIGNAL_VALUE` entries, which needs the path-to-message
  mapping of `knowledge/vss-mapping.yaml`, since `SIGNAL_VALUE` names no message), and check it against the
  repeatability data.
- **Repeated replays** for the repeatability runs: each one is a separate approval; whether a person may approve a
  batch for one digest is not decided.
