# In-vehicle software on a development server next to the bench

> **Status: in development.** This page defines the scenario: the work, the knowledge, the gates, the tools and the
> definition of done that the runnable sample must meet. The runnable parts are being built against it (see
> [Build plan](#build-plan)). It follows the [embedded framework](../README.md) and its five building blocks.

## What: clean up a vehicle platform service on the cockpit computer, without changing what it does

In-vehicle software teams rarely build on a laptop. Code, cross toolchains, licence servers and test benches sit on
the company network, and engineers work on a shared Linux build server that can reach the benches.

The platform services on the vehicle's cockpit or central computer are large, old C++ code bases. They carry a long
tail of static analysis findings that nobody has time to fix, because every fix needs a cross build, a deploy to a
bench target and a check that nothing else changed. An AI coding assistant on a laptop can propose the fixes. It
cannot run the cross build, cannot deploy to the target, and cannot tell whether the service still behaves as it did
last week.

This sample takes that maintenance work through AI-DLC on the real setup. The agents analyse a platform service, fix
a batch of findings and refactor it, cross-build it on the build server with bounded self-repair, and deploy it to the
target. The target's own runtime log then shows whether its behaviour changed. Everything runs on one machine without
automotive hardware: a container plays the build server and an emulated 64-bit Arm Linux system plays the cockpit
computer. A real bench target is an optional profile.

| A team starts with | The sample shows how to end with |
| --- | --- |
| A platform service in C++ with a backlog of static analysis findings, its interface specification and its design notes | Each finding triaged, fixed or justified, with the change traced to the finding, the rule and the specification page it touches |
| The team's coding rules, cross toolchain and the target's resource limits | A change that cross-builds with warnings as errors, introduces no new findings and stays within the binary-size and memory limits |
| The team's definition of done: unit tests, a run on the target compared with a baseline log, a reviewed change | Unit tests that pass on the build server, a run on the emulated target whose log matches the baseline except for approved differences, and a record of every build, deploy and target action |
| A bench the team does not want agents to touch unsupervised | Deploy, restart and target writes only through guarded tools, each one approved by a person, and refused when the bench is not in a safe state |
| An engineer who owns the release | The same engineer signs it off from one evidence page: findings, changes, checks, the log comparison and the action record |

**What it means for the team.** The engineer's time on a maintenance batch moves from fixing, cross-building and
re-deploying one finding at a time to deciding which findings to fix and reviewing evidence. A fix that changes
behaviour is caught by the log comparison on the emulated target before a real bench is involved. The sample
measures this with the [one-day guided rehearsal](../../../docs/guided-rehearsal.md); the
[scorecard](#how-the-sample-is-measured) lists what is recorded. It reports no productivity figures until a rehearsal
has produced them.

## The scenario

All names, code and data in this scenario are synthetic.

- **Target:** a fictional cockpit computer, *CC-1*: a 64-bit Arm system-on-chip running embedded Linux. In the sample
  it is an emulated `aarch64` Linux system (QEMU system emulation) with the core count and memory limit from the
  synthetic platform notes.
- **Service:** `vstatd`, a C++17 platform service. It reads vehicle signals from a gateway socket (a simplification
  of a SocketCAN or SOME/IP gateway), keeps their latest values, and serves them to cockpit apps over a local
  inter-process communication (IPC) socket. It writes a structured runtime log: start-up, subscriptions, signal
  updates, timeouts and errors. About 3,000 lines of product code and 1,000 lines of unit tests, written for the sample.
- **Build server:** a Linux container with the cross toolchain (`aarch64-linux-gnu-g++`), CMake, the unit-test
  framework and the static analysers. Agents run here, next to the bench, as engineers would over remote SSH.
- **Bench:** the emulated CC-1; a signal player that replays a recorded drive (synthetic) into the gateway socket; a
  baseline log from the current release on the same replay; and a simulated bench power supply that reports supply
  voltage and ignition state (terminal 15, KL15: the switched ignition supply). The emulated CC-1 stands in for the
  bench, so its deploys rehearse the action gate exactly as a real bench would.
- **Operator console:** a separate terminal process, outside the agents' tools, where a person sees each requested
  action with its build digest (the SHA-256 of the exact build) and approves or refuses it. The supply and ignition
  values are set only here or by a scripted scenario; the agents' tools can read them but not change them.
- **Work item:** *Fix the static analysis findings in `vstatd` marked "fix" in the backlog, and split the signal table
  handling out of the 750-line `Service::run()`. No change in behaviour: same signals, same values, same timeouts and
  same errors on the recorded drive; memory on the target within the limit.* The backlog holds about 30 synthetic
  findings of common kinds: null dereference on an error path, resource leak, uninitialised member, implicit widening
  in a scaling, unchecked return value. A data race on the shared signal table is seeded too; ThreadSanitizer in the
  unit tests finds it, not the static analysers.
- **Seeded difficulties** for the rehearsal, each caught by a check rather than by luck:
  - one "obvious" fix changes a timeout's behaviour, and only the log comparison shows it;
  - one finding is a false positive that the specification explains, so the right answer is a justification, not a
    code change;
  - one fix is correct but pushes peak memory over the target's limit;
  - the first cross build fails on a target-only header, which the bounded repair loop has to solve or hand back.

## How

### 1. Knowledge with citations

- `knowledge/vstatd-interface.md` (with a rendered PDF): the synthetic interface specification, with numbered pages
  and sections: signals, their scaling and timeouts, the IPC protocol, error behaviour. A fact extraction step turns it
  into `knowledge/facts/`, one entry per signal, timeout and error rule, each with its page and section, for example
  `[VSTATD-IF p.7 §4.1]`.
- `knowledge/cc1-gateway.dbc` and `knowledge/vss-mapping.yaml`: the CAN database in DBC format, and the mapping from
  each CAN signal to the path `vstatd` publishes it under. The paths are names from the COVESA Vehicle Signal
  Specification (VSS), so that a team can map them onto its own signal catalogue and CAN databases.
- `knowledge/cc1-platform-notes.md`: the target's cores, memory limit, start-up order, log format, and the log
  comparison's settings (timing tolerance, ignored fields).
- `knowledge/team-rules.md`: the team's C++ rules, cross-build flags, resource limits, the triage policy (fix,
  justify, defer) and the definition of done.
- `knowledge/findings-backlog.md`: the static analysis findings on the current release.
- `knowledge/tools/check_knowledge.py` keeps these files consistent: citations, PDF pages, the DBC, the mapping and
  the facts. A separate check confirms that every change and every justification cites a finding and, where it
  touches behaviour, a fact entry.

What the knowledge contains is described in [knowledge/README.md](knowledge/README.md).

### 2. AI-DLC phases and gates

| AI-DLC phase | Work in this scenario | Human gate |
| --- | --- | --- |
| Inception | Triage the findings against the rules and the specification; propose fix, justify or defer for each; plan the refactor; split the work into units | The triage list approved; build start approved |
| Construction | Fixes and the refactor with unit tests; cross build with warnings as errors; static analysis; size check | The checks decide; a unit returns to its owner on any failure |
| Operation | Deploy to the emulated target, restart `vstatd`, replay the recorded drive, collect the runtime log and memory figures, compare with the baseline | Each deploy, restart and target write, approved one at a time at the operator console |
| Release | One evidence page for the batch | The release owner signs off |

Repair loops are bounded by settings recorded with each run: by default the agents may retry a failing cross build
three times and a failing log comparison twice; after that the unit stops and a person decides.

### 3. Checks and gates before the bench

Checks are command-line scripts whose exit status is the verdict: pass, fail, or blocked when a check cannot judge,
for example because a run had not ended ([checks/README.md](checks/README.md)). The build server runs them; the
agents cannot change them.

| Check | When | Pass condition |
| --- | --- | --- |
| `checks/build.sh` | Before deploy | Cross build succeeds with `-Wall -Wextra -Werror` and the team's flags |
| `checks/static.sh` | Before deploy | Static analysis (cppcheck and clang-tidy with the team's rule set): every finding in the batch is fixed or has an approved justification, and there are no new findings |
| `checks/unit.sh` | Before deploy | Unit tests pass on the build server, including a new test for each fix with an observable effect; ThreadSanitizer, AddressSanitizer and UndefinedBehaviorSanitizer report nothing |
| `checks/size.sh` | Before deploy | Binary size within the limit in the platform notes |
| `checks/trace.sh` | Before deploy | Every change and justification cites a finding, and a fact entry where it touches behaviour |
| `checks/runtime-limits.sh` | After deploy | Peak memory of `vstatd` during the replay within the limit. CPU is reported only relative to the baseline on the same emulator, because emulated CPU time says little about the real SoC. Both are labelled as emulation results |
| `checks/logdiff.sh` | After deploy | The runtime log on the replay matches the baseline: same signals and values, same timeouts and errors, in the same order. Guest time runs on QEMU's instruction counter (`-icount`) so timing is repeatable; the tolerance is a setting in the platform notes. Differences listed in the approved triage are allowed |
| `checks/release.sh` | Before sign-off | Every check passed on the final commit, and no requirement is blocked by its evidence tier |

The three gates of the framework apply:

- **Quality gate:** nothing is deployed until build, static, unit, size and trace pass.
- **Action gate:** every deploy, restart and target write waits for a person at the operator console.
- **Physical gate:** the bench refuses an action when the simulated supply is outside 11.0 to 14.8 V, or when the
  ignition is in the wrong state for it (a deploy needs KL15 on).

**Evidence tiers.** Each result on the evidence page carries the tier its evidence came from: unit test, emulation
or real target (the optional profile). The page also lists what emulation cannot show, such as CPU load on the real
SoC. When the team rules mark a requirement as real-target only and its only evidence comes from emulation, it is
reported as blocked, not passed, and the release check fails. The sample's work item has no such requirement, so the
default profile can be signed off.

### 4. Tool connectors with guardrails

Two MCP servers. Their guardrails live in the servers, whatever the agent session allows.

- **`build`**: configure, cross-build, run a check, read its log. Runs only inside the build server's workspace.
- **`bench`**: lease the target, read supply and ignition, request a deploy of a build, request a restart of
  `vstatd`, start the drive replay, fetch the runtime log and memory figures, release the lease.
  - A lease gives one session the target at a time.
  - Each physical action is a request that the operator console must approve for that build's digest. It is written
    to an append-only action record with its digest and the approver.
  - After an interruption the bench reports the target as *unknown* and accepts only reads and a reconcile until a
    person has checked its state. Nothing is retried automatically.
  - Permissions are read-only, controlled-write and physical, granted by role.
- **Both servers:**
  - Deny by default. Each tool has a permission class, and a call is refused unless the caller's role grants that
    class. A request that needs approval is refused when nobody answers at the operator console before its timeout,
    a setting recorded with each run.
  - No tool merges, tags or publishes; that stays with the release owner.
  - Every call, reads included, goes to a JSONL audit log with its class and outcome. The action record is the part
    of that log for physical actions. The evidence page takes its tool-call and action lists from it.

**Around the servers (defence in depth).** The servers are the only path that is meant to work; these measures
make the other paths fail too:

- Only `bench` can reach the target: the agents' shell runs without the target's SSH key and without access to the
  gateway socket. A hook also refuses shell commands that reach the target directly, for example `ssh` or `scp` to
  the emulated CC-1.
- The agent configurations deny `git push` and history rewrites (`push --force`, `rebase`, `reset --hard`). Command
  patterns are easy to get around, for example with `git -C <dir> push` or a compound command, so the build server
  also holds no push credentials.
- A probe test tries these commands and their variants against the agent configurations. Run it again after each
  Kiro or Kiro Crew update, because how rules match commands can change between versions.

Neither server needs `--trust-all-tools`, and the sample's agent configurations do not use it.

### 5. The agent next to the bench

The agents run on the build server, so builds, deploys and target traffic stay on the team's network. In the sample
that is the container; in a real team it is the team's own build host. Engineers reach it over remote SSH with Kiro,
or open Kiro Crew's dashboard through an SSH port forward; the dashboard binds to loopback and is never published.
AWS Systems Manager port forwarding is an option for build hosts registered as managed nodes; on premises that needs
a hybrid activation and the advanced-instances tier, which has a cost. What leaves the network is the agents' traffic
to the model service, which includes the code and documents they read; use only material you are allowed to send
there.

### Where it runs

| Part | In Kiro (IDE or CLI) | In Kiro Crew |
| --- | --- | --- |
| `knowledge/` | Steering files | A knowledge source the agents search and cite |
| `mcp/build`, `mcp/bench` | MCP configuration | Not used: the app runs the checks and the bench actions itself |
| `checks/` | Hooks that block the next tool call on failure; a hook on raw target commands as defence in depth; the guardrails themselves are in the MCP servers | Run by the [Kiro Crew app](#the-kiro-crew-app) after each merge and before the bench, as in the [agent-team sample](../../agent-team-on-kiro-crew/) |
| `bench/` | Through the `bench` MCP server | `bench/cc1.sh`, run by the app; each action approved at the operator console |
| Roles (optional) | Custom agents | Team members |

The parts may also be packaged as an AI-DLC plugin; the plain parts stay usable on their own.

## The Kiro Crew app

> **Status: in development.** The app's own tests pass. It has not yet taken a delivery end to end with agents and the
> bench (step 12 of the [implementation plan](docs/kiro-crew-app.md#implementation-plan)), so nothing on this page about
> it is measured yet.

[`app/`](app/README.md) is a Kiro Crew app, `vstatd-team` (AIDLC-Embedded团队), modelled on the
[agent-team sample](../../agent-team-on-kiro-crew/). It takes the work item through AI-DLC with six roles, each a Kiro
Crew session running one of four AI-DLC experts as a Kiro agent template (`embedded-developer-agent`,
`embedded-architect-agent`, `embedded-quality-agent`, `embedded-architecture-reviewer-agent`). The team has no Kiro Crew
members: Kiro Crew 0.12 builds a member from its own worker, not from a template:

| Role | Expert | What it does | Gate after it |
| --- | --- | --- | --- |
| Triage | `aidlc-developer-agent` | Fix, justify or defer for each finding, with citations; adds the refactor under TR §4.4 | Triage: a person answers a question for each justification, deferral and added entry |
| Architect | `aidlc-architect-agent` | The refactor plan of `Service::run()` and the work split by source file | Build start |
| Tester | `aidlc-quality-agent` | A unit test for each fix that needs one; the app requires that it fails on the base commit | — |
| Developer: fixes | `aidlc-developer-agent` | The fixes, in the files the split gives it | — |
| Developer: refactor | `aidlc-developer-agent` | The refactor, in the files the split gives it | — |
| Reviewer | `aidlc-architecture-reviewer-agent` | Read only; looks hardest at the justifications and at the behaviour the refactor keeps | — |

The app, not an agent, runs the checks of [checks/](checks/README.md) in the build container once every developer's work
is merged, and again after each fix, and sends a failure to the developer who owns the file it names; BLOCKED, and a
check out of its repair rounds, go to a person. When the checks pass and the reviewer lets the change through, the app
runs `bench/doctor.sh`, then deploys and replays through `bench/cc1.sh`, each action waiting for a person at the
operator console, and runs the checks after the bench. Before sign-off it reruns every check on the final commit in a
new results directory and runs `release.sh`; the sign-off button is enabled only when `release.sh` passes, and the
sign-off dialog shows the evidence page. The board's 评分卡 (scorecard) shows the figures of [How the sample is
measured](#how-the-sample-is-measured) that the runs' records hold, and leaves a figure empty when no run is behind it.
It leaves out the tool calls by permission class (they come from the MCP servers' audit log), how many log differences
were real changes of behaviour and the defects found later (the app records neither). The decisions behind this are in
[docs/kiro-crew-app.md](docs/kiro-crew-app.md).

### Quick start

On a Mac with Kiro Crew running, Docker, Node.js 22, git and Python 3:

1. Install the app, its knowledge source `vstatd` and the team's agent templates: `bash setup.sh` in this folder. It asks once
   whether the sessions the app opens may approve their own tool calls; read [Guardrails](#guardrails) first.
   `bash setup.sh --dry-run` says what it would do and changes nothing. Keep this folder where it is: the app runs the
   checks and the bench from it.
2. Build the checks' build container and the bench once (setup.sh does not, and prints these commands):

   ```bash
   docker build --platform linux/arm64 -t vstatd-build:arm64 reference-project/tools/   # Apple Silicon; linux/amd64 and vstatd-build:amd64 on Intel
   bench/build-target.sh        # the target image and its sysroot (first build: about 40 min, bench/README.md)
   bench/doctor.sh
   ```

3. Before the first run: open the operator console in a terminal of its own (`python3 bench/console.py`), set the
   supply there (`v 13.5`, `k on`), start the target (`bench/cc1.sh start && bench/cc1.sh wait`), deploy the current
   release and write the baseline once with `bench/cc1.sh replay --kind baseline --out ~/workplace/vstatd-team/baseline`
   (see [bench/README.md](bench/README.md)). Until the bench is ready, a run stops before its first bench action and the
   board says what is missing and the command for it.
4. Open Kiro Crew → Apps → AIDLC-Embedded团队 → 团队看板, choose 新需求 (it is filled in with the work item) and
   hand it to the team.
5. At the triage gate, answer each question (its citations are shown); then approve build start.
6. Approve each deploy and replay, within its timeout: on the board (type the first six characters of the build's
   digest and press 批准) or at the operator console. Either way the bench's own approval rules decide.
7. After the independent rerun, read the evidence page in the sign-off dialog and sign off. 评分卡 shows the run's
   figures.

Cost: to be measured with the first delivery. A run uses Kiro Crew credits and creates no AWS resources.

Remove it with `bash cleanup.sh` (`--dry-run` lists what it would remove). It removes only what setup.sh recorded in
`.install-state.json` and puts back agent templates setup.sh replaced; it leaves the Docker images and volumes, the
bench state and the baseline alone, and prints the commands that remove them.

### Guardrails

What the app enforces: a role after a human gate gets no session until a person approves; the app runs the checks
itself, so an agent's word that they pass counts for nothing; a role's commits that do not cite a finding are sent back
before they are merged; each bench action waits for a person to approve that build's digest, on the board or at the
operator console, through the bench's own approval rules and behind its physical gate, and goes to the action record; sign-off is possible only after `release.sh` passed on the
independent rerun.

What it does not enforce. If you agree during setup, the app sets **the sessions it opens** to auto-approve their tool
calls, and the roles' templates allow file reads and writes and shell commands. An agent's shell then has three paths
around the bench's guardrails:

1. It can reach the emulated target without the app or the console: `docker exec` into the bench's runner container,
   whose volume `cc1-bench-secrets` holds the target's SSH key.
2. It can write the bench state in `~/.cc1-bench`, including approval decisions.
3. It can write the check results of a round under `~/workplace/vstatd-team/runs/<run>/results/`, which the app reads.

So in this app the physical gate, the operator console and the action record show how the guardrails work; they are not
a boundary against the agents. "Only `bench` can reach the target" holds only where the agents' shell has no Docker
access and no write access to the bench state, such as Kiro Crew in a build-server container without a Docker socket
([D2](docs/kiro-crew-app.md#d2-kiro-crew-runs-on-the-users-own-machine-agents-have-a-shell-sessions-auto-approve)). The
target is emulated, so a bypass damages no hardware. The shell runs as your user, so it can also change files outside
its worktree, this folder's checks included: write scopes are checked when a role's branch is merged, not while the
agent works, and write-scope rules in an agent's own configuration did not stop writes in a test on one Mac (D2). Run
the app on a machine and user account **without production credentials or customer data**. If you do not agree during
setup, every tool call waits for your approval in Kiro Crew.

The agents' sessions send their prompts, the code they read and the knowledge they look up to the model service that
Kiro Crew uses; the scenario's data is synthetic.

## How the sample is measured

The rehearsal scorecard records, for the batch:

- findings fixed, justified and deferred, and how many justifications the reviewer overturned;
- time from the backlog to an approved triage, to the first passing check run, and to the release sign-off;
- build repair rounds used;
- check failures caught before the bench, by check;
- log differences found, and how many were real behaviour changes;
- bench actions approved, refused and reconciled;
- tool calls by permission class, and how many were refused;
- checks whose result changed when a person, or a separate session, reran every check on the final commit from a
  clean build with no build cache;
- defects found later that a check should have caught.

The first rehearsal's numbers are the baseline. The sample publishes measured numbers only, with how they were
measured.

## Why

- **Maintenance is where the backlog lives.** Static analysis findings on a large platform service pile up because
  each fix costs a cross build, a deploy and a regression check. That loop is exactly what agents can run, if the loop
  is available to them and its result is trustworthy.
- **"No change in behaviour" needs proof from the target.** Unit tests do not show that a refactor kept a timeout or
  an error path; the service's own runtime log on a recorded drive, compared with the baseline, does. In-vehicle teams
  already compare logs with a known-good run; making it a check lets agents prove that a change did only what was
  approved.
- **A justification is a valid answer.** Some findings are false positives that the specification explains. Asking
  agents to cite the page for a justification keeps them from "fixing" correct code.
- **Bounded repair, then a person.** Unbounded retries on a build or a bench hide the real problem and use the bench;
  a limit turns repeated failure into a decision.
- **Guardrails in the tools, not in the prompt.** Leases, approvals at the operator console, the action record and
  reconcile-after-interrupt hold even if an agent is misconfigured. That is what makes it acceptable to connect agents
  to a bench at all.
- **Next to the bench, on the team's network.** Toolchains, licence servers and benches cannot move to a laptop or
  to the cloud; the agents go where they are.

## Build plan

Each item is a pull request. The sample becomes available when all of them are merged and the rehearsal guide has
been dry-run once.

1. Synthetic interface specification and platform notes (Markdown and rendered PDF), CAN database and VSS mapping,
   fact entries, team rules and the findings backlog, with a consistency check; facilitator notes on the seeded
   difficulties. *Done:* [knowledge/](knowledge/), [rehearsal/facilitator-notes.md](rehearsal/facilitator-notes.md).
2. `vstatd` reference project: the service, its unit tests, CMake with the cross toolchain file, and the seeded
   findings and difficulties. *Done:* [reference-project/](reference-project/); the facilitators' seed checks are in
   [rehearsal/seed-checks/](rehearsal/seed-checks/).
3. Bench emulation: a script that builds the emulated CC-1 image, the gateway socket and drive replay, the baseline
   log, the simulated supply, the operator console and a reset script. Also a `doctor` script that checks the host
   before a session. *Done* except the final baseline: [bench/](bench/README.md).
4. Checks, each with a failing and a passing example; the release check and the evidence page generator.
   *Done:* [checks/](checks/README.md), with the triage format and the run directories the bench hands over (a
   proposed interface with item 3); the facilitators' runs on the reference project are in
   [rehearsal/check-examples/](rehearsal/check-examples/).
5. MCP servers `build` and `bench`, with their guardrails, the audit log, a test for each guardrail and a smoke test
   of both. They are for Kiro; the Kiro Crew app does not need them.
6. Kiro and Kiro Crew configurations with the bypass hook; the permission probe test; optional AI-DLC plugin. The
   Kiro Crew app (item 8) needs neither the MCP servers nor this item's configurations.
7. Rehearsal guide and scorecard. One dry run in which, after the triage is approved, nobody answers in the agent
   session and a person answers only at the operator console, followed by an independent rerun of the checks.
   Record the time and credits it used.
8. The [Kiro Crew app](#the-kiro-crew-app): `app/`, its roles' templates, `setup.sh` and `cleanup.sh`. *In
   development:* steps 1 to 11 of its [implementation plan](docs/kiro-crew-app.md#implementation-plan) are done; one
   delivery end to end (step 12) is not.

Definition of done for the sample itself: runs on one Linux host, or a Mac with a container runtime, from `setup.sh`
to a signed-off evidence page; `cleanup.sh` removes everything it created; every third-party tool is listed with its
licence; synthetic data only, with no customer names, code, data or identifying details; no credentials or account
identifiers; no `--trust-all-tools`.

## Layout

| Folder | Contents |
| --- | --- |
| `knowledge/` | Synthetic interface specification, CAN database, VSS mapping, platform notes, fact entries, team rules, findings backlog, consistency check |
| `checks/` | The seven checks, the release check, the evidence page generator, their limits and their tests |
| `mcp/` | `build` and `bench` servers and their guardrail tests |
| `agents/` | `kiro-crew/make_templates.py`, the roles' Kiro agent templates; to come (item 6): the Kiro configurations, the bypass hook, the permission probe test |
| `app/` | The Kiro Crew app `vstatd-team`: orchestrator, board and scorecard ([app/README.md](app/README.md)) |
| `vendor/` | The four AI-DLC expert definitions the templates use, unmodified ([vendor/aidlc-workflows/SOURCE.md](vendor/aidlc-workflows/SOURCE.md)) |
| `scripts/` | What `setup.sh` and `cleanup.sh` share: the install record, the templates, the team's install, and their tests |
| `docs/` | Design notes of the Kiro Crew app ([docs/kiro-crew-app.md](docs/kiro-crew-app.md)) |
| `setup.sh`, `cleanup.sh` | Install the Kiro Crew app into the local Kiro Crew; remove what setup recorded |
| `reference-project/` | `vstatd`, its GoogleTest unit tests, CMake with the cross toolchain file, the build-environment Dockerfile, a stand-in sysroot script and the analyser scripts |
| `bench/` | Emulated-target image build script, drive replay, baseline log, simulated supply, operator console, doctor script |
| `rehearsal/` | One-day guide, scorecard, facilitator notes and seed checks; not copied into the agents' workspace |

## Prerequisites

To be completed with the build: a Linux host, or a Mac with a container runtime (Docker, Podman or Colima), and Kiro
or Kiro Crew. Third-party tools and their licences will be listed here, among them QEMU (GPL-2.0) and the emulated
target's Linux image built by `bench/build-target.sh` with Buildroot (GPL-2.0; Linux kernel GPL-2.0) and not committed
to the repository. They are used as tools and not redistributed. The bench's own tools are listed in
[bench/README.md](bench/README.md#third-party-tools).

The [Kiro Crew app](#the-kiro-crew-app) needs, besides the bench: a Mac (`setup.sh` installs into the Kiro Crew desktop
app), Kiro Crew running and signed in, Docker, git, Python 3 and Node.js 22 or newer to build the board. Its manifest
asks for Kiro Crew 0.8.0 or newer; it has not run a delivery end to end yet, so no Kiro Crew version is listed as
tested.

The reference project builds in the container of `reference-project/tools/Dockerfile`, based on the `ubuntu:24.04`
image (Ubuntu 24.04 LTS from Docker Hub; each of its packages is under its own licence, recorded in
`/usr/share/doc/<package>/copyright` in the image), with these tools from Ubuntu's packages. The image builds natively
for the machine it runs on: `vstatd-build:arm64` (`--platform linux/arm64`) on Apple Silicon and arm64 Linux, where the
host `g++-12` and `binutils` already target `aarch64-linux-gnu`, and `vstatd-build:amd64` (`--platform linux/amd64`)
on x86_64, with the cross compiler. The app picks the image of the machine its checks run on. An amd64 image under
Rosetta cannot run ThreadSanitizer (see [docs/kiro-crew-app.md](docs/kiro-crew-app.md#not-yet-verified)). The versions
are those `dpkg-query` reports in the container, the same in both images; GCC 12.4 is Ubuntu's `g++-12` (and on amd64
`g++-12-aarch64-linux-gnu`) 12.4.0-2ubuntu1~24.04.1 from `noble-updates`:

| Tool | Version | Licence |
| --- | --- | --- |
| GCC, host and `aarch64-linux-gnu` cross compiler | 12.4 | GPL-3.0-or-later with the GCC Runtime Library Exception |
| GNU Binutils for `aarch64-linux-gnu` (linker, `readelf`, `strip`: `binutils` on arm64, `binutils-aarch64-linux-gnu` on amd64) | 2.42 | GPL-3.0-or-later |
| CMake | 3.28 | BSD-3-Clause |
| Git (the checks judge committed trees) | 2.43 | GPL-2.0-only |
| Ninja | 1.11 | Apache-2.0 |
| GoogleTest | 1.14 | BSD-3-Clause |
| cppcheck | 2.13 | GPL-3.0-or-later |
| clang-tidy | 18.1 | Apache-2.0 WITH LLVM-exception |
| Python | 3.12 | PSF-2.0 |
| dpkg (`dpkg -x` for the stand-in sysroot) | 1.22 | GPL-2.0-or-later |
| `file` | 5.45 | BSD-2-Clause |
| `ca-certificates` (HTTPS downloads of the stand-in sysroot) | 20260816 | MPL-2.0 (certificate data) |

Until the bench's Buildroot build (build plan item 3) provides the CC-1 sysroot, `tools/make-standin-sysroot.py`
unpacks a stand-in from Ubuntu 24.04 arm64 packages; it is generated on the build server and not committed:

| Packages | Licence |
| --- | --- |
| `libc6`, `libc6-dev` (glibc) | LGPL-2.1-or-later |
| `libcrypt1`, `libcrypt-dev` (libxcrypt) | LGPL-2.1-or-later |
| `linux-libc-dev` (Linux UAPI headers) | GPL-2.0 WITH Linux-syscall-note |
| `libsystemd0`, `libsystemd-dev` (systemd) | LGPL-2.1-or-later |
| `libcap2` | BSD-3-Clause or GPL-2.0 |
| `libgcrypt20`, `libgpg-error0` | LGPL-2.1-or-later |
| `liblz4-1` | BSD-2-Clause |
| `liblzma5` (xz 5.4) | Public domain |
| `libzstd1` | BSD-3-Clause or GPL-2.0 |
| `libgcc-s1`, `libgcc-12-dev`, `libstdc++6`, `libstdc++-12-dev` | GPL-3.0-or-later with the GCC Runtime Library Exception |

The knowledge uses signal names from the COVESA Vehicle Signal Specification
v6.1 (MPL-2.0) without copying its files, and its check needs cantools (MIT) and PyYAML (MIT); see
[knowledge/README.md](knowledge/README.md#third-party-references).

## Cost

To be measured with the dry run, and for the Kiro Crew app with its first delivery. The sample creates no AWS resources;
the cost is the model usage of Kiro or Kiro Crew for one batch (see [Kiro pricing](https://kiro.dev/pricing/)).

## Cleanup

`bash cleanup.sh` removes what `setup.sh` recorded: the app with its data and run repositories, any members and
workspace an earlier setup created, the knowledge source and its copy, and the agent templates it added; it puts back the templates it replaced.
`--dry-run` lists them. It leaves the build container, the bench's images and volumes, the bench state
(`~/.cc1-bench`) and the baseline, and prints the commands of [bench/README.md](bench/README.md#cleanup) that remove
them.
