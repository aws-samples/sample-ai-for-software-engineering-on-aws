# Embedded development with AI-DLC

> **Status: open for contributions.** This page is a reference framework for embedded samples: the outcome a sample
> should show, the building blocks it is expected to cover, and why. Contributors choose the scenario, the toolchain
> and the implementation. Whatever they build must work in [Kiro](https://kiro.dev) and in
> [Kiro Crew](https://kiro.dev/docs/crew/).

- [What: the outcome an embedded sample should show](#what-the-outcome-an-embedded-sample-should-show)
- [How: five building blocks](#how-five-building-blocks)
- [Works in Kiro and in Kiro Crew](#works-in-kiro-and-in-kiro-crew)
- [Why a framework, and why these blocks](#why-a-framework-and-why-these-blocks)
- [Contributing an embedded sample](#contributing-an-embedded-sample)

Scenarios built on this framework:

| Scenario | What it shows | Status |
| --- | --- | --- |
| [In-vehicle software on a development server next to the bench](in-vehicle-dev-server/) | Static analysis fixes and a refactor of a C++ platform service, cross-built with bounded repair and checked on an emulated target against a baseline log | In development |
| [Robot firmware and software: a digital twin decides, a person flashes](robot-twin-and-flash-gate/) | A controller firmware change judged in a twin that runs the firmware itself, flashed through a gate a person operates, with a separate software update path | In development |

## What: the outcome an embedded sample should show

Embedded teams that try AI coding assistants usually find that the assistant writes plausible C quickly, and that
little of it survives contact with the real target: it does not know the board, it cannot see the result of a build
or a flash, and nobody wants it touching a bench unsupervised.

A sample in this folder takes one embedded feature through AI-DLC on a realistic toolchain and shows a team how to
change that. A good sample gets from the left column to the right one:

| A team starts with | The sample shows how to end with |
| --- | --- |
| A requirement and the hardware documents: datasheets, reference manuals, schematics, models | Requirements with acceptance criteria, each hardware fact traceable to its source |
| The team's coding standard, toolchain and resource limits | Code that builds with the team's own toolchain and stays within its limits |
| The team's definition of done | Tests that pass before any hardware is involved, in simulation or emulation where the domain allows, and a record of every build, test and hardware action |
| A bench the team does not want agents to damage | Hardware actions only through guarded tools, with a person's approval |
| An engineer who owns the release | The same engineer signs it off, with the evidence in front of them |

For the team, the time an engineer spends on a feature moves from writing and re-flashing code to deciding and
reviewing evidence, and defects are caught before a board is involved. A sample states how it measures that, for
example with the one-day [guided rehearsal](../../docs/guided-rehearsal.md).

**Business measures come first.** A scenario page opens with the few business measures a team would use to decide
whether the work pays off, for example engineer hours per change, cycle time from request to sign-off, bench time,
and defects that escape to the bench or later. Each measure has a target, stated as a hypothesis, and the scorecard
item that measures it. A claim such as "50 % less time" needs a baseline: the team's own history for comparable work,
or the same work done the usual way. Quality measures are always reported with efficiency measures. A sample built on
synthetic data shows that the mechanism works; the headline numbers come from a rehearsal on a team's own work.

## How: five building blocks

These are the parts field engagements have found necessary. Each block lists a reference approach; a sample may
implement a block differently, or leave out one that does not apply to its scenario, and says why.

### 1. Hardware knowledge with citations

Hardware facts (registers, pin assignments, timing, electrical limits) are extracted from the documents into
Markdown with their source and page, and checked against those pages. Agents cite the entry they used, so a reviewer
checks evidence instead of the model's memory of a part. Complex drawings may need their own processing step, for
example a vision model plus cross-checks, before the facts reach the development flow.

### 2. AI-DLC phases with people deciding at the gates

Embedded samples keep the five phases of [AI-DLC Workflows 2.0](https://github.com/awslabs/aidlc-workflows) and its
core stages. Hardware work is added inside those phases the way an
[AI-DLC plugin](https://github.com/awslabs/aidlc-workflows/blob/main/docs/harness-engineering/10-authoring-a-plugin.md)
does it: new stages, and contributions that adjust core stages, so that a team that already runs AI-DLC keeps its
lifecycle. Which phases run depends on the scope: Initialization always runs and has no approval gate; small scopes
may skip Ideation. A reference mapping, to adapt to the scenario:

| AI-DLC phase | Embedded work | Human gate |
| --- | --- | --- |
| Initialization | Detect the toolchain, licence server, benches and simulators; record which evidence tiers the run can reach | None; automatic |
| Ideation | Intent; feasibility including the hardware (resource budget, target, bench availability); scope, including whether functional safety applies | Scope approved |
| Inception | Hardware facts from datasheets and specifications; requirements; interfaces in the domain's formats (for example DBC, ARXML, VSS); a verification plan with the evidence tier each requirement needs; units of work | Requirements and verification plan approved; build start |
| Construction | Code or model changes and tests; build with the cross toolchain; tests in simulation, emulation or a twin; back-to-back comparison where code is generated from models | The checks in block 3 decide |
| Operation | Deploy or flash through guarded tools; validation on an emulator, a bench or a device, labelled by tier; sign-off from one evidence page | Each irreversible hardware action; the engineer who owns the release signs off |

Hardware stages proposed for an embedded AI-DLC plugin, each added to the phase shown (their order inside a phase
follows from the stages each one requires):

| Stage | Phase | What it adds |
| --- | --- | --- |
| `hw-environment-detection` | Initialization | Toolchain, licences, benches, simulators and reachable evidence tiers |
| `hardware-knowledge` | Inception | Datasheets, specifications and interface files turned into fact entries with page and section |
| `verification-planning` | Inception | Evidence tier per requirement, requirements that need a real target, coverage and back-to-back tolerances |
| `model-design` | Construction | Model changes made by the agent in the modelling tool through its MCP server, with model-in-the-loop tests (when the scenario uses model-based design) |
| `simulation-verification` | Construction | Simulation, emulation or twin runs; back-to-back comparison of generated code with the model; log comparison with a baseline |
| `bench-deployment` | Operation | Deploys and flashes only through guarded tools, approved for a build digest at an operator console, refused outside safe physical conditions |
| `evidence-signoff` | Operation | One evidence page with every result labelled by tier, signed off by the release owner |

### 3. Checks and gates before hardware

The team's rules run as checks that the agents do not control: for example, the build with warnings treated as
errors, coding rules, resource limits, unit tests and simulation tests. A failure goes back to the work that caused
it. Three gates are a useful reference:

- **Quality gate:** nothing reaches hardware until its checks pass in simulation or emulation.
- **Action gate:** flashing, power cycling and bench write operations wait for a person's approval, every time.
- **Physical gate:** limits such as battery level, supply voltage and temperature block an action outside a safe
  range.

### 4. Tool connectors with guardrails

Agents reach the toolchain through MCP servers: build, simulator, flash and debug, serial console, bench. The
connectors enforce their guardrails themselves, whatever the agent session allows. A reference set: one session per
bench or board at a time; a record of every physical action; after an interruption, check the target's state before
anything else runs, with no automatic retry; read-only, controlled-write and physical permissions by role; and no
`--trust-all-tools`.

### 5. The agent next to the bench

Many embedded teams build on a shared Linux development server that can reach their benches, and keep code,
toolchains, licence dongles and benches on their own network. A reference pattern is to run the agent on that
server, which engineers reach over remote SSH, so that builds, flashing and on-target checks stay inside the network.
What leaves it is the agent's traffic to the model service, which includes the code and documents the agent reads;
use only material you are allowed to send there.

## Works in Kiro and in Kiro Crew

Build the parts in plain formats, and the same sample runs in either:

| Part | Format | In Kiro (IDE or CLI) | In Kiro Crew |
| --- | --- | --- | --- |
| Knowledge and rules | Markdown | Steering files, or the knowledge of an AI-DLC plugin | A knowledge source the agents search and cite |
| Tool connectors | MCP servers | MCP configuration | MCP servers of a custom agent or an app |
| Checks | Command-line scripts with clear pass or fail | Hooks, or blocking gate sensors in an AI-DLC plugin | Checks run by an app, as in the [agent-team sample](../agent-team-on-kiro-crew/) |
| Agent roles (optional) | Markdown prompts | Custom agents | Members of a team |

A sample may also package its parts as an
[AI-DLC plugin](https://github.com/awslabs/aidlc-workflows/blob/main/docs/harness-engineering/10-authoring-a-plugin.md),
the official extension mechanism of AI-DLC Workflows 2.0, so that any team that runs AI-DLC can install it without
changing the framework. Keep the plain parts usable on their own so that the sample still works in Kiro Crew.

## Why a framework, and why these blocks

- **Embedded toolchains differ widely.** Microcontroller firmware, model-based design and in-vehicle software each
  have their own tools, tests and release rules. Samples built by people who work with those toolchains every day are
  more useful than one generic implementation; a shared framework keeps them comparable and reusable.
- **Embedded work is not web work.** Requirements live in datasheets and models, a build-and-flash loop takes minutes
  to hours, a failed run can damage hardware, and benches sit on closed networks. A general AI-DLC flow does not cover
  this; the five blocks do.
- **No feedback, no reliable firmware.** An agent that cannot build, run and read the result of its own code is
  guessing. Close the loop in simulation first, where it is cheap and safe, and on hardware only behind the gates.
- **Citations instead of trust.** Engineers review evidence traced to a source, not the model's memory.
- **Rules enforced, not suggested.** Checks the agents do not control make the output reviewable.
- **Engineers keep the safety decisions.** AI output is not safety evidence on its own; the record a run leaves
  supports the team's existing safety process.

## Contributing an embedded sample

1. **Pick a scenario you know.** For example: in-vehicle software built on a development server next to the bench;
   microcontroller firmware on an emulated board. Model-based design fits inside such a scenario, as in the two
   scenarios above.
2. **Give it its own folder,** `samples/embedded-development/<scenario>/`, with a README that opens with its business
   measures, answers what the sample delivers, how it works and why, and maps it to the five building blocks and the
   five AI-DLC phases.
3. **State how it runs in Kiro and in Kiro Crew.**
4. **Follow the repository rules** in [docs/adding-a-sample.md](../../docs/adding-a-sample.md): synthetic data and no
   customer information, a simulator or emulator wherever the domain allows, a person's approval on irreversible
   actions, and prerequisites, cost and cleanup.

Everything else, including the toolchain, the layout and the packaging, is the contributor's choice.
