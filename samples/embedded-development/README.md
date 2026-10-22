# Embedded development with AI-DLC

> **Status: in development.** This page sets out what the sample delivers, how it works and why it is built this
> way. The sample is delivered as an AI-DLC plugin, `embedded-firmware`, with a reference project and tool
> connectors; they are being built, and contributions are welcome (see [Contributing](#contributing)).

- [What: a firmware feature from datasheet to validated build, with the engineer still signing off](#what-a-firmware-feature-from-datasheet-to-validated-build-with-the-engineer-still-signing-off)
- [How: an AI-DLC plugin for embedded work](#how-an-ai-dlc-plugin-for-embedded-work)
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
hardware, and checks passed at first gate. The first measured runs will be published here.

## How: an AI-DLC plugin for embedded work

The sample extends [AI-DLC Workflows 2.0](https://github.com/awslabs/aidlc-workflows) with a
[plugin](https://github.com/awslabs/aidlc-workflows/blob/main/docs/harness-engineering/10-authoring-a-plugin.md), the
framework's official extension mechanism. The plugin adds stages, checks and agent knowledge for embedded work to a
team's AI-DLC install without changing the core, and is enabled per project. Four parts work together.

### 1. Hardware documents become facts the agents cite

A plugin stage in Inception turns the hardware documents into Markdown in the project, one fact per entry with the
page it came from: registers, pin assignments, timing, electrical limits. Each extracted value is cross-checked
against its page. Agents cite the entry they followed, so a reviewer checks a register value against its datasheet
page instead of trusting the model. The team's coding standard, toolchain conventions and safety limits ship with the
plugin as knowledge for the agents.

### 2. AI-DLC phases with people deciding at the gates

| AI-DLC phase | What the agents do in embedded work | Gate |
| --- | --- | --- |
| Inception: requirements | Read the requirement and the hardware facts; write requirements with IDs, acceptance criteria and the open questions | **Requirements:** a person answers the questions and approves |
| Inception: design | Driver and HAL design, interrupt and timing plan, memory budget, how the work is split | **Build start:** nothing is built before a person approves |
| Construction | Write the code and the host unit tests; turn acceptance criteria into simulation tests; build and run them on the emulated target | The checks below must pass before the gate opens |
| Operation | Hardware profile: flash and test on a real board and bench through the guarded connectors | **Hardware:** a person approves each flash and power cycle |
| Release | Collect the evidence for the release | **Release:** the engineer who owns it signs off |

### 3. Checks that decide, run by the engine

The team's rules run as AI-DLC sensors bound to the stage gates as blocking. The engine runs them, not the agents,
and a gate does not open until they pass; going past a failing check is a separate human decision that the audit log
records.

- the firmware builds with the cross toolchain, warnings treated as errors;
- coding rules from the team's standard, such as no dynamic allocation and no unbounded loops in interrupt handlers;
- the image fits the flash and RAM budget;
- host unit tests pass;
- simulation tests pass on the emulated target: the image boots, and the console output matches each acceptance
  criterion;
- the run recorded its evidence: build log, test reports, image checksum.

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

### Where it runs

Wherever AI-DLC Workflows 2.0 runs. For embedded teams the natural place is [Kiro](https://kiro.dev) IDE or Kiro CLI
on the team's Linux build server, the machine that already has the toolchain, license dongles and access to the
bench (engineers usually reach it over remote SSH). In Kiro the plugin is installed by copying its Kiro build into the
project and running `aidlc engine plugin sync`; the same plugin can be built for the other harnesses AI-DLC supports.
Builds, flashing and on-target checks stay inside the team's network. What leaves it is the agent's traffic to the
model service, which includes the code and documents the agent reads, through the team's egress proxy; use only
material you are allowed to send there.

## Why it is built this way

- **Embedded work is not web work.** Requirements live in datasheets and schematics, not user stories. A
  build-and-flash loop takes minutes to hours, not seconds. A failed run can damage a board or create a safety risk,
  and the bench usually sits on a closed network. A general AI-DLC flow does not cover any of this, so the plugin adds
  exactly these steps and nothing else.
- **A plugin, so it spreads.** A plugin is the official way to extend AI-DLC. Any team that already runs AI-DLC adds
  embedded work to its install without forking the framework, keeps receiving upstream releases, turns the plugin on
  only for firmware projects, and can carry its own rules in the same form.
- **No feedback, no reliable firmware.** An agent that cannot build, run and read the result of its own code is
  guessing. The sample closes that loop on an emulator first, where it is cheap and safe, and on hardware only behind
  the gates.
- **Citations instead of trust.** Hardware facts are cited to a page so that the engineer reviews evidence, not the
  model's memory of a part.
- **The team's rules, enforced, not suggested.** Blocking checks are what make the output reviewable. The agents keep
  fixing until the team's own rules pass; people spend their time on decisions.
- **Engineers keep the safety decisions.** Every irreversible action has a person's approval, and the release is
  signed by the engineer who owns it. AI output is not safety evidence on its own; the evidence the run records
  supports the team's existing safety process.
- **Simulation first, so anyone can try it.** The reference project runs on a QEMU-emulated board. A team can follow
  the whole flow on a laptop, then point the same flow at its own board with the hardware profile.

## Layout

| Folder | Contents |
| --- | --- |
| [`embedded-firmware/`](embedded-firmware/) | The AI-DLC plugin: stages, blocking sensors and their scripts, agent knowledge, a doctor check |
| [`mcp/`](mcp/) | Connectors for build, simulator, flash and debug, serial console and bench, with the guardrails above |
| [`reference-project/`](reference-project/) | Firmware for a QEMU-emulated board with its hardware facts, a backlog of features to try, and a hardware profile |
| [`rehearsal/`](rehearsal/) | One-day rehearsal guide and scorecard for embedded teams |

## Prerequisites, cost and cleanup

Final versions will be published with the first release. Planned for the simulated path: Linux or macOS, AI-DLC
Workflows 2.0, Kiro (IDE or CLI), the Arm GNU Toolchain, QEMU and CMake. The simulated path creates no AWS resources;
its cost is the Kiro credits the agents use. A team that runs it on an Amazon EC2 build server pays for that instance.
Removing the plugin from a project is a plugin selection change in AI-DLC; the steps will be documented here.

## Contributing

We are especially interested in:

- model-based design, including integrating code generated from Simulink models;
- in-vehicle infotainment and HMI user interface development and testing;
- hardware-in-the-loop bench connectors;
- turning datasheets, reference manuals and schematics into knowledge that agents can cite;
- integrations with issue trackers and code hosting, such as Jira and GitLab.

See [docs/adding-a-sample.md](../../docs/adding-a-sample.md) for the rules every contribution follows.
