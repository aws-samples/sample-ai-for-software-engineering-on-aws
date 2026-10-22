# AI-DLC plugin: embedded-firmware

An [AI-DLC plugin](https://github.com/awslabs/aidlc-workflows/blob/main/docs/harness-engineering/10-authoring-a-plugin.md)
that adds embedded firmware work to AI-DLC Workflows 2.0 without changing the core framework. A team enables it per
project; with the plugin disabled, AI-DLC behaves as it does without it.

> **Status: in development.** This folder will be created with the official scaffold (`aidlc-plugin-create.ts`)
> and checked with the official validator (`aidlc-plugin-validate.ts`) before its first release.

## Planned contents

The layout follows the official plugin structure.

| Path | What it adds |
| --- | --- |
| `.aidlc-plugin/plugin.json` | The plugin manifest |
| `scopes/embedded-firmware-delivery.md` | The scope that turns the plugin's stages on for firmware work |
| `stages/inception/embedded-firmware-hardware-knowledge.md` | Turns datasheets, reference manuals and schematics into hardware facts with page references, cross-checked against their pages |
| `stages/construction/embedded-firmware-simulation-test.md` | Builds the image and runs the simulation tests on the emulated target |
| `stages/operation/embedded-firmware-hardware-validation.md` | Hardware profile: flashes and tests on a real board through the guarded connectors |
| `contributions/construction/` | Additions to core stages: cross-toolchain builds, interrupt and timing design, memory budget |
| `sensors/` and `tools/` | Blocking gate sensors and their scripts: build with warnings as errors, coding rules, memory budget, unit tests, simulation tests, evidence |
| `agents/embedded-firmware-hardware-agent.md` | A support agent for registers, HALs and interrupt-safe code |
| `knowledge/` | Methodology knowledge for the agents: the coding standard, toolchain conventions, safety limits |
| `tools/embedded-firmware-doctor.ts` | Checks that the cross toolchain, QEMU and the connectors are installed |
| `tests/` | The plugin's own content and compose tests |

The hardware facts of a specific board belong to the project, not to the plugin; the reference project ships them
for its emulated board.
