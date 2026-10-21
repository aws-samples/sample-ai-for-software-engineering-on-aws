# Embedded development with AI-DLC

> **Status: in development.** The structure and scope below are agreed; the plugin, connectors and
> reference project are being built. Contributions are welcome; see
> [Contributing to this sample](#contributing-to-this-sample).

## What this sample covers

Firmware and controller software in C and C++, including code generated from model-based design. In
this domain the code is bound to hardware, a build-and-flash cycle can take minutes to hours, and a
change is not done until it passes simulation and hardware-in-the-loop validation and an engineer
signs off the release.

The sample takes one feature through AI-DLC and shows what changes for an embedded team at each step.

| Step | What is different for embedded teams | What the sample provides |
| --- | --- | --- |
| Requirements and design | Requirements come from datasheets, reference manuals, schematics and model diagrams, not only from user stories | A knowledge-ingestion step that turns hardware documents into Markdown with page references; steering for the hardware specification |
| Build | Code drives registers and HALs; builds use cross toolchains, often on a shared Linux build server; repositories can be very large | Steering for coding standards and toolchain usage; skills that a whole team shares; connectors for build, simulator, flash and debug, and serial console |
| Validate and release | Software-in-the-loop comes before hardware-in-the-loop; a failed run can damage hardware or create a safety risk | Three gates (action, physical, quality) and an evidence record for every run |

## Gates and guardrails

The guardrails are on from the first run, not added later.

- **Action gate.** Flashing, power cycling and hardware-in-the-loop write operations need a person's
  approval every time.
- **Physical gate.** Thresholds such as battery level, supply voltage and temperature block agent
  actions outside a safe range.
- **Quality gate.** A build moves to hardware only after its simulation tests pass, and to release
  only after hardware-in-the-loop evidence is reviewed.
- **Lease.** One session holds a bench or target board at a time.
- **Operation digest.** Every physical action leaves a record for audit and replay.
- **Reconcile before retry.** After an interruption the target state is treated as unknown and checked
  before anything else runs; nothing retries automatically.
- **Permission tiers.** Read-only, controlled write and physical operation, granted by role.
- **No `--trust-all-tools`.** Tools are approved one by one.

## Deployment pattern: the agent next to the bench

Many embedded teams build on a shared Linux development server that can reach their benches, and keep
source code, toolchains, license dongles and benches on their own network. The sample runs the agent
on that server, which engineers reach over remote SSH. Builds, flashing and on-target checks then run
inside the team's network, and only the agent's service traffic leaves it, through the team's egress
proxy. The sample documents this setup.

## Reference project

The reference project runs on a simulated target (QEMU), so you can follow the whole flow without
hardware. A hardware profile shows how to point the same flow at a real board and bench.

## Layout

| Folder | Contents |
| --- | --- |
| [`aidlc-plugin/`](aidlc-plugin/) | AI-DLC 2.0 plugin: embedded stages, agent knowledge, sensors for the gates |
| [`steering/`](steering/) | Kiro steering for hardware specifications, coding standards and toolchains |
| [`mcp/`](mcp/) | Connectors for build, simulator, flash and debug, serial console and bench, with guardrails |
| [`reference-project/`](reference-project/) | Firmware project that runs on QEMU, plus a hardware profile |
| [`rehearsal/`](rehearsal/) | One-day rehearsal guide and scorecard for embedded teams |

## Prerequisites, cost and cleanup

To be published with the first release. The simulated-target path will run on a single Linux
development machine or one Amazon EC2 instance.

## Contributing to this sample

We are especially interested in:

- model-based design, including code generated from Simulink models;
- in-vehicle infotainment and HMI user interface development and testing;
- hardware-in-the-loop bench integration;
- turning datasheets and schematics into knowledge that agents can cite.

See [docs/adding-a-sample.md](../../docs/adding-a-sample.md) for the rules every contribution
follows.
