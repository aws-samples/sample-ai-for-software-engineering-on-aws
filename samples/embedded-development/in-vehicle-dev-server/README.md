# In-vehicle software on a development server next to the bench

> **Status: in development.** This page defines the scenario: the work, the knowledge, the gates, the tools and the
> definition of done that the runnable sample must meet. The runnable parts are being built against it (see
> [Build plan](#build-plan)). It follows the [embedded framework](../README.md) and its five building blocks.

## Business measures

The measures a platform team would use to decide whether this pays off, each with a target stated as a hypothesis
and the [scorecard](#how-the-sample-is-measured) item that measures it. Targets are set against the team's own
baseline (its history for comparable batches, or the same batch done the usual way) and corrected after the first
rehearsal.

| Business measure | Target (hypothesis) | Business goal | Scorecard item |
| --- | --- | --- | --- |
| Engineer hours per finding: triage, fix and verification | −50 % | Every finding in the batch decided (fix, justify or defer) and traceable | Engineer hours per finding; findings fixed, justified and deferred; justifications overturned |
| Changes that pass every pre-bench check on the first round | Set after the first rehearsal | Changes build with the team's toolchain, add no findings and stay within limits | Changes that passed every pre-bench check on the first round; build repair rounds |
| Behaviour changes that escape to the bench or later | 0 | No change in behaviour, shown by the target's own log | Log differences and real behaviour changes; defects found later |
| Engineer time attending the bench | −50 % | Bench actions only through guarded tools, each one approved by a person | Engineer time at the operator console and the bench; bench actions approved, refused and reconciled |
| Cycle time of a batch, from backlog to sign-off | −50 % | The release owner signs off from one evidence page | Time to an approved triage, to the first passing check run and to sign-off |

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
  updates, timeouts and errors. About 5,000 lines, written for the sample.
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
  handling out of the 900-line `Service::run()`. No change in behaviour: same signals, same values, same timeouts and
  same errors on the recorded drive; memory on the target within the limit.* The backlog holds about 30 synthetic
  findings of common kinds: null dereference on an error path, resource leak, uninitialised member, integer overflow
  in a scaling, unchecked return value. A data race on a shared map is seeded too; ThreadSanitizer in the unit tests
  finds it, not the static analysers.
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
  `[VSTATD-IF p.7 §3.2]`.
- `knowledge/cc1-platform-notes.md`: the target's cores, memory limit, start-up order, log format, and the log
  comparison's settings (timing tolerance, ignored fields).
- `knowledge/team-rules.md`: the team's C++ rules, cross-build flags, resource limits, the triage policy (fix,
  justify, defer) and the definition of done.
- A check confirms that every change and every justification cites a finding and, where it touches behaviour, a fact
  entry.

### 2. AI-DLC phases and gates

The five phases of AI-DLC Workflows 2.0, with the hardware steps of the
[framework](../README.md#2-ai-dlc-phases-with-people-deciding-at-the-gates) (packaged as the
[`hw` plugin](../aidlc-plugin/hw/)):

| AI-DLC phase | Work in this scenario | Human gate |
| --- | --- | --- |
| Initialization | AI-DLC's own set-up | None; automatic |
| Ideation | Decide which findings the batch takes (label `fix`) and whether the batch is worth the effort against the team's baseline | The batch scope approved |
| Inception | Detect the build server, the cross toolchain and sysroot, the emulated CC-1 and, if present, a real bench; fact entries from the specification and platform notes; triage of the findings against the rules and the specification (fix, justify or defer); the verification plan, including any requirement that needs the real target; units of work | The triage list approved; build start approved |
| Construction | Fixes and the refactor with unit tests; cross build with warnings as errors; static analysis; size check; the back-to-back check in the model-based profile | The checks decide; a unit returns to its owner on any failure |
| Operation | Deploy to the emulated target, restart `vstatd`, replay the recorded drive, collect the runtime log and memory figures, compare with the baseline; one evidence page for the batch | Each deploy, restart and target write, approved one at a time at the operator console; the release owner signs off |

Repair loops are bounded by settings recorded with each run: by default the agents may retry a failing cross build
three times and a failing log comparison twice; after that the unit stops and a person decides.

### 3. Checks and gates before the bench

Checks are command-line scripts with pass or fail. The build server runs them; the agents cannot change them.

| Check | When | Pass condition |
| --- | --- | --- |
| `checks/build.sh` | Before deploy | Cross build succeeds with `-Wall -Wextra -Werror` and the team's flags |
| `checks/static.sh` | Before deploy | Static analysis (cppcheck and clang-tidy with the team's rule set): every finding in the batch is fixed or has an approved justification, and there are no new findings |
| `checks/unit.sh` | Before deploy | Unit tests pass on the build server, including a new test for each fix; ThreadSanitizer reports no data race |
| `checks/size.sh` | Before deploy | Binary size within the limit in the platform notes |
| `checks/trace.sh` | Before deploy | Every change and justification cites a finding, and a fact entry where it touches behaviour |
| `checks/runtime-limits.sh` | After deploy | Peak memory of `vstatd` during the replay within the limit. CPU is reported only relative to the baseline on the same emulator, because emulated CPU time says little about the real SoC. Both are labelled as emulation results |
| `checks/logdiff.sh` | After deploy | The runtime log on the replay matches the baseline: same signals and values, same timeouts and errors, in the same order. Guest time runs on QEMU's instruction counter (`-icount`) so timing is repeatable; the tolerance is a setting in the platform notes. Differences listed in the approved triage are allowed |
| `checks/backtoback.sh` | Before deploy, model-based profile only | Software-in-the-loop results of the generated filter equal its model-in-the-loop results on every test, within the tolerances in the verification plan |
| `checks/release.sh` | Before sign-off | Every check passed on the final commit, and no requirement is blocked by its evidence tier |

The three gates of the framework apply:

- **Quality gate:** nothing is deployed until build, static, unit, size and trace pass, and back-to-back in the
  model-based profile.
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

### Optional: a component generated from a model

Some platform services include code generated from models, for example signal filters. The optional model-based profile
adds one: `soc_display_filter`, a Simulink model of the filter that smooths the displayed state of charge, generated as
C and linked into `vstatd`. A change request to the filter goes through the `hw-model-design` step: the agent changes the
model in Simulink through MathWorks' [MATLAB MCP Core
Server](https://www.mathworks.com/products/matlab-mcp-core-server.html) and [Simulink Agentic
Toolkit](https://www.mathworks.com/products/simulink-agentic-toolkit.html), which the agent uses as one more MCP server
with its own permission class, and runs model-in-the-loop tests. Generated code then has to match the model: a
back-to-back comparison of software-in-the-loop results with model-in-the-loop results, within the tolerances in the
verification plan, before the usual checks and the log comparison. The profile needs MathWorks licences; without them,
the generated code and recorded model results are committed and the agents cannot change the model.

### Where it runs

| Part | In Kiro (IDE or CLI) | In Kiro Crew |
| --- | --- | --- |
| `knowledge/` | Steering files | A knowledge source the agents search and cite |
| `mcp/build`, `mcp/bench` | MCP configuration | MCP servers of a custom agent |
| `checks/` | Hooks that block the next tool call on failure; a hook on raw target commands as defence in depth; the guardrails themselves are in the MCP servers | Run by a Kiro Crew app before each gate, as in the [agent-team sample](../../agent-team-on-kiro-crew/) |
| Roles (optional) | Custom agents | Team members |

The parts may also be packaged as an AI-DLC plugin; the plain parts stay usable on their own.

## How the sample is measured

The rehearsal scorecard records, for the batch:

- engineer hours on the batch, by phase and per finding, and engineer time at the operator console and the bench;
- findings fixed, justified and deferred, and how many justifications the reviewer overturned;
- changes that passed every pre-bench check on the first round;
- time from the backlog to an approved triage, to the first passing check run, and to the release sign-off;
- build repair rounds used;
- check failures caught before the bench, by check;
- log differences found, and how many were real behaviour changes;
- in the model-based profile, back-to-back differences found, and how many were real defects in the model or the
  code generation settings;
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

1. Synthetic interface specification and platform notes (Markdown and rendered PDF), fact entries, team rules and the
   findings backlog.
2. `vstatd` reference project: the service, its unit tests, CMake with the cross toolchain file, and the seeded
   findings and difficulties.
3. Bench emulation: a script that builds the emulated CC-1 image, the gateway socket and drive replay, the baseline
   log, the simulated supply, the operator console and a reset script. Also a `doctor` script that checks the host
   before a session.
4. Checks, each with a failing and a passing example; the release check and the evidence page generator.
5. MCP servers `build` and `bench`, with their guardrails, the audit log, a test for each guardrail and a smoke test
   of both.
6. Kiro and Kiro Crew configurations with the bypass hook; the permission probe test; optional AI-DLC plugin.
7. Rehearsal guide and scorecard. One dry run in which, after the triage is approved, nobody answers in the agent
   session and a person answers only at the operator console, followed by an independent rerun of the checks.
   Record the time and credits it used.
8. Optional model-based profile: the `soc_display_filter` model, its generated code, recorded model results and
   `checks/backtoback.sh`.

Definition of done for the sample itself: runs on one Linux host, or a Mac with a container runtime, from `setup.sh`
to a signed-off evidence page; `cleanup.sh` removes everything it created; every third-party tool is listed with its
licence; synthetic data only, with no customer names, code, data or identifying details; no credentials or account
identifiers; no `--trust-all-tools`.

## Layout

The optional model-based profile adds `model/` (the model, its generated code and recorded model results) and
`checks/backtoback.sh`.

| Folder | Contents |
| --- | --- |
| `knowledge/` | Synthetic interface specification, platform notes, fact entries, team rules, findings backlog |
| `checks/` | The seven checks, the release check and the evidence page generator |
| `mcp/` | `build` and `bench` servers and their guardrail tests |
| `agents/` | Kiro and Kiro Crew configurations, the bypass hook, the permission probe test |
| `reference-project/` | `vstatd`, its tests, the cross toolchain file |
| `bench/` | Emulated-target image build script, drive replay, baseline log, simulated supply, operator console, doctor script |
| `rehearsal/` | One-day guide and scorecard |

## Prerequisites

To be completed with the build: a Linux host, or a Mac with a container runtime (Docker, Podman or Colima), and Kiro
or Kiro Crew. Third-party tools and their licences will be listed here, among them CMake (BSD-3-Clause), the GNU
cross toolchain (GPL-3.0 with the GCC runtime library exception; glibc LGPL-2.1), QEMU (GPL-2.0), the emulated
target's Linux image built by `setup.sh` with Buildroot (GPL-2.0; Linux kernel GPL-2.0) and not committed to the
repository, GoogleTest (BSD-3-Clause), cppcheck (GPL-3.0) and clang-tidy (Apache-2.0 with LLVM exception). They are
used as tools and not redistributed.

The optional model-based profile also needs MATLAB, Simulink and Embedded Coder from MathWorks (commercial
licences), and the MATLAB MCP Core Server and the Simulink Agentic Toolkit, whose terms are checked before the profile
is built.

## Cost

To be measured with the dry run. The sample creates no AWS resources; the cost is the model usage of Kiro or Kiro
Crew for one batch (see [Kiro pricing](https://kiro.dev/pricing/)).

## Cleanup

`cleanup.sh` will remove the containers, the emulated target image and the run's working files.
