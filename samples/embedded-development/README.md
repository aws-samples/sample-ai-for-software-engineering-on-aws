# Embedded development with AI-DLC

> **Status: in development.** This page sets out what the sample delivers, how it works and why it is built this
> way. The reference project, checks and connectors are being built; contributions are welcome (see
> [Contributing](#contributing)).

- [What: a firmware feature from datasheet to validated build, with the engineer still signing off](#what-a-firmware-feature-from-datasheet-to-validated-build-with-the-engineer-still-signing-off)
- [How: hardware knowledge, AI-DLC gates, checks the agents cannot change, and guarded tools](#how-hardware-knowledge-ai-dlc-gates-checks-the-agents-cannot-change-and-guarded-tools)
- [Why it is built this way](#why-it-is-built-this-way)
- [Layout](#layout) · [Prerequisites, cost and cleanup](#prerequisites-cost-and-cleanup) · [Contributing](#contributing)

## What: a firmware feature from datasheet to validated build, with the engineer still signing off

Embedded teams that try AI coding assistants usually find that the assistant writes plausible C quickly, and that
little of it survives contact with the real target: it does not know the board, it cannot see the result of a build
or a flash, and nobody wants it touching a bench unsupervised. This sample shows a team how to change that on its own
toolchain.

A run takes one firmware feature, for example a new peripheral driver or a new command on the device's console,
through the AI-DLC phases:

| You start with | You end with |
| --- | --- |
| A one-sentence requirement and the hardware documents: datasheet, reference manual, schematic | Requirements with IDs and acceptance criteria, each hardware fact cited to a page of its source document |
| The team's coding standard, toolchain and memory budget | Driver and application code in C that builds with the team's cross toolchain and stays within the flash and RAM budget |
| The team's definition of done | Host unit tests and simulation tests on an emulated target, all passing, plus a record of every build, test and hardware action |
| A bench the team does not want agents to damage | Hardware runs only through guarded tools: one session per bench, a person's approval for every flash and power cycle, safe limits checked first |
| An engineer who owns the release | The same engineer signs the release off, with the evidence in front of them |

**What it means for the team.** The time an engineer spends on a feature moves from writing and re-flashing code to
deciding: approving requirements and design, and reviewing evidence. Defects are caught in simulation before a
board is involved. The rules the team already has (coding standard, memory budget, safety limits) are applied to
every change automatically instead of in review. The sample's [rehearsal](rehearsal/) measures this on the team's
own feature: time from requirement to validated build, build-flash-test loops per feature, defects found before
hardware, and checks passed at first merge. The first measured runs will be published here.

## How: hardware knowledge, AI-DLC gates, checks the agents cannot change, and guarded tools

### 1. Hardware documents and team standards become knowledge the agents cite

Before any code, the hardware documents are turned into Markdown, one fact per entry with the page it came from:
registers, pin assignments, timing, electrical limits. The team's coding standard, toolchain conventions and safety
rules are written down the same way. Agents look these up and cite the entry they followed, so a reviewer can check a
register value against its datasheet page instead of trusting the model. See [`knowledge/`](knowledge/).

### 2. AI-DLC phases with people deciding at the gates

| AI-DLC phase | What the agents do in embedded work | Gate |
| --- | --- | --- |
| Inception: requirements | Read the requirement and the hardware knowledge; write requirements with IDs, acceptance criteria and the open questions | **Requirements:** a person answers the questions and approves |
| Inception: design | Driver and HAL design, interrupt and timing plan, memory budget, how the work is split | **Build start:** nothing is built before a person approves |
| Construction | Write the code and the host unit tests; turn acceptance criteria into simulation tests | Checks decide; failures go back to the agent that owns them |
| Validation | Build the image, run it on the emulated target, then (hardware profile) on a real board and bench | **Hardware:** a person approves each flash and power cycle |
| Release | Collect the evidence for the release | **Release:** the engineer who owns it signs off |

### 3. Checks the agents cannot change

The team's rules also exist as checks, kept where the agents cannot edit them and run by the workflow rather than by
the agents (see [`checks/`](checks/)):

- the firmware builds with the cross toolchain, warnings treated as errors;
- coding rules from the team's standard, such as no dynamic allocation and no unbounded loops in interrupt handlers;
- the image fits the flash and RAM budget;
- host unit tests pass;
- simulation tests pass on the emulated target: the image boots, and the console output matches each acceptance
  criterion;
- every run leaves its evidence: build log, test reports, image checksum.

Nothing goes to hardware until every check passes in simulation.

### 4. Tools the agents use, behind guardrails

The agents reach the toolchain through MCP connectors (see [`mcp/`](mcp/)): build, simulator, flash and debug,
serial console, and the bench. The connectors enforce the guardrails themselves, whatever the agent session allows:

- **Action gate:** flashing, power cycling and bench write operations wait for a person's approval, every time.
- **Physical gate:** limits such as battery level, supply voltage and temperature are checked before an action and
  block it outside a safe range.
- **Quality gate:** an image reaches hardware only after its simulation checks pass.
- **Lease:** one session holds a bench or board at a time.
- **Operation digest:** every physical action is recorded for audit and replay.
- **Reconcile before retry:** after an interruption the target is treated as unknown and checked before anything else
  runs; nothing retries automatically.
- **Permission tiers:** read-only, controlled write and physical operation, granted by role.
- **No `--trust-all-tools`:** tools are approved one by one.

### 5. Where it runs: Kiro or Kiro Crew

The knowledge, checks and connectors are plain files and MCP servers, so the same sample runs either way:

- **[Kiro](https://kiro.dev) IDE or Kiro CLI** on the team's Linux build server, the machine that already has the
  toolchain, license dongles and access to the bench (engineers usually reach it over remote SSH). An engineer runs
  the AI-DLC workflow and approves at each gate. Builds, flashing and on-target checks stay inside the team's network.
  What leaves it is the agent's traffic to the model service, which includes the code and documents the agent reads,
  through the team's egress proxy; use only material you are allowed to send there.
- **[Kiro Crew](https://kiro.dev/docs/crew/)**, with a team of AI-DLC expert agents as in the
  [agent-team sample](../agent-team-on-kiro-crew/): one agent each for requirements, design, code, tests and review,
  working in parallel, with the same gates on a board.

## Why it is built this way

- **Embedded work is not web work.** Requirements live in datasheets and schematics, not user stories. A
  build-and-flash loop takes minutes to hours, not seconds. A failed run can damage a board or create a safety risk,
  and the bench usually sits on a closed network. A general AI-DLC flow does not cover any of this, so the sample adds
  exactly these steps and nothing else.
- **No feedback, no reliable firmware.** An agent that cannot build, run and read the result of its own code is
  guessing. The sample closes that loop on an emulator first, where it is cheap and safe, and on hardware only behind
  the gates.
- **Citations instead of trust.** Hardware facts are cited to a page so that the engineer reviews evidence, not the
  model's memory of a part.
- **The team's rules, enforced, not suggested.** Checks the agents cannot change are what make the output
  reviewable. The agents keep fixing until the team's own rules pass; people spend their time on decisions.
- **Engineers keep the safety decisions.** Every irreversible action has a person's approval, and the release is
  signed by the engineer who owns it. AI output is not safety evidence on its own; the evidence the run records
  supports the team's existing safety process.
- **Simulation first, so anyone can try it.** The reference project runs on a QEMU-emulated board. A team can follow
  the whole flow on a laptop, then point the same flow at its own board with the hardware profile.

## Layout

| Folder | Contents |
| --- | --- |
| [`knowledge/`](knowledge/) | Hardware documents turned into cited Markdown; coding standard, toolchain conventions, safety limits |
| [`checks/`](checks/) | Checks the team issues and the agents cannot change: build, coding rules, memory budget, unit and simulation tests, evidence |
| [`mcp/`](mcp/) | Connectors for build, simulator, flash and debug, serial console and bench, with the guardrails above |
| [`reference-project/`](reference-project/) | Firmware for a QEMU-emulated board, a backlog of features to try, and a hardware profile |
| [`rehearsal/`](rehearsal/) | One-day rehearsal guide and scorecard for embedded teams |

## Prerequisites, cost and cleanup

Final versions will be published with the first release. Planned for the simulated path: Linux or macOS, the Arm GNU
Toolchain, QEMU and CMake, and Kiro (IDE or CLI) or Kiro Crew. The simulated path creates no AWS resources; its cost
is the Kiro or Kiro Crew credits the agents use. A team that runs it on an Amazon EC2 build server pays for that
instance.

## Contributing

We are especially interested in:

- model-based design, including integrating code generated from Simulink models;
- in-vehicle infotainment and HMI user interface development and testing;
- hardware-in-the-loop bench connectors;
- turning datasheets, reference manuals and schematics into knowledge that agents can cite;
- integrations with issue trackers and code hosting, such as Jira and GitLab.

See [docs/adding-a-sample.md](../../docs/adding-a-sample.md) for the rules every contribution follows.
