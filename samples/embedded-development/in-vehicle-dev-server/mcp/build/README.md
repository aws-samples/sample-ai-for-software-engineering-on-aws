# `build` MCP server

The agents' only way to build `vstatd` and to run the team's checks on the build server
([scenario page, section 4](../../README.md#4-tool-connectors-with-guardrails)). The guardrails live in the server,
whatever the agent session allows. The `bench` server (build plan item 5, with the bench of item 3) is separate.

## Tools

| Tool | Permission class | What it does |
| --- | --- | --- |
| `workspace_status` | read-only | HEAD, branch and uncommitted changes of the agents' work tree |
| `configure` | controlled-write | CMake configure of the work tree for a profile: `cross` (the project's toolchain file), `host`, `tsan` or `asan`, into the server's build directory for that profile |
| `build` | controlled-write | Ninja build of a configured profile; target `vstatd`, `vstatd_tests` or `all` |
| `run_check` | controlled-write | One of the [checks](../../checks/README.md) `build`, `static`, `unit`, `size`, `trace` or `release`, on a clean clone of the committed HEAD, with fixed arguments; returns the verdict from the exit status (0 PASS, 1 FAIL, 3 BLOCKED) |
| `read_result` | read-only | A check's last published result and the tail of its log |
| `read_log` | read-only | The tail of the last configure or build log of a profile |

No tool takes a command, a path, a check option or a limit. No tool commits, pushes, merges, tags or publishes. The
after-deploy checks (`runtime-limits`, `logdiff`) need a run of the bench and belong to `bench`. Until `bench`
publishes their results into the same results folder, `run_check release` reports them missing and cannot PASS.

## Isolation

Configuring and building a project runs the project's own code: CMake scripts, custom build rules, the unit tests.
The agents write that code, so the server runs everything that touches it in a container (the image of
[`reference-project/tools/Dockerfile`](../../reference-project/tools/Dockerfile)), started for the one call: no
network, a read-only root, no capabilities, no new privileges, a fresh home on a temporary file system, at most 1024
processes, the server's user and group IDs (never root), optional memory and CPU limits, and only the mounts below,
at their host paths. The container is removed when the call ends, and every process in it ends with it, including
one that left its session; a container that a crashed server left behind is removed before the next call.

| Call | Read-only | Read-write |
| --- | --- | --- |
| `workspace_status` | the work tree | none |
| `configure`, `build` | the work tree; the sysroot for `cross` only | `builds/<profile>` of the state |
| `run_check`, taking HEAD | the work tree, then the bundle | a scratch folder that receives `git bundle` of HEAD, then `run/` for the clone |
| `run_check` | the sample (`checks/` and its parent), the folder of the approved triage; the sysroot for `build` and `static` | `run/` of the state: the clean clone and a copy of the published results |

The server's state folder holds `builds/`, `logs/`, `results/` (what `read_result` returns), `run/`, `repair.json` and
`audit.jsonl`; its logs, published results, repair count and audit log are never mounted. Git runs on the agents'
work tree and on the objects it hands over only inside a container, because a repository's own config can run
commands ([git's security notes](https://git-scm.com/docs/git#_security)); the server reads only the bundle's header.
Docker options that only one check needs, such as `seccomp=unconfined` for ThreadSanitizer in `checks/unit.sh`, are
given for that check alone (`[sandbox.check_args]`).

The server's user starts containers, which on a default Docker installation is equivalent to root on the host. So the
server runs as a user of its own, and the agents reach it only over MCP; see [Running](#running). At start the
server refuses its configuration, state, triage and sysroot folders, the sample and every file in it,
the triage and its approval record, and the folders above the work tree, when someone other than root or the
server's user could write or replace them. The state may not lie inside the sample or the triage folder, which checks
can read. Before each call the server refuses when a mounted folder is no longer the one it checked.

What stays possible, and what the server does about it:

- **A project can fool the check that builds it.** `checks/build.sh` and `checks/unit.sh` run the project's code in
  the same container as the check, and that code can change the run's copy of the results. The server publishes a
  result only when it names this check, was started by this call, agrees with the check's exit status and judged the
  HEAD the server took. Otherwise it publishes an `ERROR` record in its place. The exit status is the check's own as
  long as the project's code cannot trace the check's process, which the host's Yama setting `ptrace_scope` 1 or
  higher prevents. A verdict is therefore what the check saw; the person at the merge gate still reviews the change.
- **The repair bound counts calls, not what the project's scripts do inside one.** A cross configure or build that
  fails counts, and only a PASS of `checks/build.sh` clears the count, so builds the project's scripts make succeed
  cannot reset it. A script can still compile against the sysroot inside a call that succeeds, for example at
  configure time; `run_check static` configures the cross profile too and is not counted, since a static finding is
  not a failed build; and the cross compiler in the image works without the sysroot. The bound keeps an agent's repair
  loop to the rounds of TR §5.1; it is not a wall against an agent that writes build scripts to get around it, which
  the audit log and the review at the gate show.

## Guardrails

Each has a test in [`tests/test_guardrails.py`](tests/test_guardrails.py); the isolation is probed by
`tests/smoke.py --probe` (see [Tests](#tests)).

| Guardrail | How |
| --- | --- |
| Deny by default | A call runs only when the server's role grants the tool's permission class. The role is the `--role` of the command line that the agent configuration sets, never part of a request; an unknown role is granted nothing |
| Closed arguments | Profiles, targets, checks and log kinds come from fixed lists. A call to an unknown tool, with arguments that are not an object, an extra or missing argument or a value that is not a string is refused before the SDK would reject it, so it is audited too |
| The server's paths are not the agents' | The server refuses to start when its configuration, state, triage, checks or sysroot path resolves (symlinks included) inside the agents' work tree, when the work tree or triage lies inside the state, or when someone else could write or replace one of them (see [Isolation](#isolation)) |
| Fixed check arguments | `run_check` passes `--project`, `--results` and, for the checks that read it, `--triage`, and never `--local`. A work tree with no commit is refused |
| Results that are this run's | See [Isolation](#isolation). A check publishes its result, log and diff, and the inputs it recorded inside its own part of the results folder whose content still matches their recorded SHA-256 (for `build`, the artifact and the toolchain file, which `checks/release.sh` verifies later); whatever it published before is removed first. Files are read without following a symlink at the last step or waiting on a FIFO, and a results folder the check replaced by a link is an `ERROR` |
| Bounded repair | `configure cross`, `build cross` and `run_check build` are cross attempts. Each is charged before it runs; a failure keeps the charge, a configure or build that succeeds takes it back, and only `run_check build` with a PASS clears the count. After the first attempt and the retries of `repair_rounds.cross_build` in [`checks/limits.json`](../../checks/limits.json) (TR §5.1: three) have all failed, cross attempts are refused until a person resets the count with `buildserver.admin reset-repair` (see [Running](#running)), which records who did. An unreadable count refuses. The count is published as `repair-rounds.json` with the results, which `checks/release.sh` reports |
| Audit | Every call appends a `started` line and an outcome line (`ok`, `failed`, `timeout`, `refused` or `error`) to `audit.jsonl`: time, role, tool, class, arguments, exit status, duration and, for a check, the verdict and the digest it recorded. A refusal before the call starts has the outcome line only |
| One call at a time | Calls, and the admin reset, hold one lock, across threads and processes. Malformed calls are refused without waiting for it |
| Timeouts | A call that runs past its timeout is killed with its container and reported; nothing is retried |
| Clean environment | The container gets `PATH`, `HOME`, `LANG`, `PYTHONNOUSERSITE` and git's no-global-config settings only: no credentials or test and sanitizer settings leak in from the server's environment. The docker client alone gets what it needs to find its daemon (`DOCKER_HOST`, `DOCKER_CONTEXT`, `XDG_RUNTIME_DIR` and the like), rootless Docker included |

Output returned to the agent is cut to the last 8 KiB of a log. Refusals and errors are MCP tool errors
(`isError`), or an invalid-parameters error for the calls refused before the SDK.

## Configuration

[`config.example.toml`](config.example.toml): the paths, the container image, its limits and the per-check options,
the roles and their classes, timeouts, the `PATH` inside the container and the tool commands. The sysroot is mounted
where `checks/limits.json` says (`sysroot`). A person approves the triage by writing its approval record next to it
(see the [checks](../../checks/README.md#the-approved-triage)).

## Running

On the build server's host, with Docker, git and Python 3.11 or later, as root once:

```bash
useradd --system --create-home buildsrv && usermod -aG docker buildsrv     # or rootless Docker: sandbox.docker_host
docker build -t vstatd-build /srv/sample/reference-project/tools   # for the host's architecture, as in the Dockerfile
python3 -m venv /opt/buildserver && /opt/buildserver/bin/pip install /srv/sample/mcp/build
```

The server is installed into its virtual environment ([`pyproject.toml`](pyproject.toml), which pins the MCP SDK)
and always started with `python -I`, so nothing is imported from the caller's working directory or environment.
`buildsrv` owns the state folder; root or `buildsrv` owns the virtual environment, the configuration, the sample, the
triage folder and the sysroot; the agents' user owns only the work tree. The agents' user may start the server as
`buildsrv` with one fixed command line, which also fixes the role (`/etc/sudoers.d/buildserver`, one line per role):

```text
agent ALL=(buildsrv) NOPASSWD: /opt/buildserver/bin/python -I -m buildserver --config /srv/build/config.toml --role developer
```

The server speaks MCP over standard input and output. In Kiro, an agent configuration names it like this (the
complete Kiro and Kiro Crew configurations, with the bypass hook and the permission probe, are build plan item 6):

```json
{
  "mcpServers": {
    "build": {
      "command": "sudo",
      "args": ["-n", "-u", "buildsrv", "/opt/buildserver/bin/python", "-I", "-m", "buildserver",
               "--config", "/srv/build/config.toml", "--role", "developer"]
    }
  },
  "tools": ["@build"]
}
```

A person resets the repair count as `buildsrv`; the audit log records the person from sudo and the user it ran as:

```bash
sudo -u buildsrv /opt/buildserver/bin/python -I -m buildserver.admin reset-repair \
  --config /srv/build/config.toml --reason "toolchain fixed by hand"
```

Running the server as the agents' own user works for a trial, but then the agents' shell could write the server's
records directly; the guardrails hold only against the project's code.

## Tests

```bash
python3 tests/test_guardrails.py                      # the guardrails, with stand-in tools and no container
python3 tests/smoke.py --config <config> --full       # over MCP stdio, on the real reference project
python3 tests/smoke.py --config <config> --probe      # tries to leave the container, on a throwaway clone
```

Run them from this folder with the server's virtual environment. `test_guardrails.py` runs the server logic without
a container (`sandbox.runner = "none"`, which the server accepts only with `BUILDSERVER_UNSANDBOXED_FOR_TESTS=1`);
it needs git, and the MCP SDK for its MCP-layer tests. The smoke test starts the server as an agent would and calls
each tool: it configures and builds the host profile, configures the cross profile, runs `checks/build.sh`, reads
its result and runs `checks/release.sh`, which must find every input the published build result recorded. The probe
clones the work tree into a new folder with its own state and commits project code that, at configure and build time
and from a background process that leaves its session, tries to write the audit log, the repair count, the published
results, the work tree, the server user's home and a host path, to reach the network and to forge the build check's
result; it also sets a `core.fsmonitor` hook. It asserts that none of this gets through and that no background
process still writes after the calls return, then deletes its folder.

Last run on 2026-11-03 on an Ubuntu 24.04 build host with Docker 29.8.2, git 2.43.0 and MCP Python SDK 2.3.0:
48 guardrail tests OK. The smoke test's calls returned as expected over stdio, each in its container; `checks/build.sh`
judged the current release FAIL on the missing `<systemd/sd-daemon.h>`, which is the toolchain difficulty the agents
are meant to repair, and `checks/release.sh` then found every input the published build result recorded. The probe's
16 checks held: it reached neither the network nor any path outside the build folder of its call, its background
writers stopped with their containers, and no forged result was published. The checks' own runs are in
[`rehearsal/check-examples/`](../../rehearsal/check-examples/).

## Prerequisites, cost and cleanup

- Docker on the build server; Python 3.11 or later (PSF-2.0) and the
  [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) 2.3.0 (MIT), pinned in
  [`pyproject.toml`](pyproject.toml) because its 2.x API is still changing.
- It runs on the build server and costs nothing beyond it.
- Cleanup: delete the virtual environment, the `vstatd-build` image, the state folder of the configuration, the
  sudoers line and the `buildsrv` user. Keep `audit.jsonl` as long as the evidence of the batch is kept.
