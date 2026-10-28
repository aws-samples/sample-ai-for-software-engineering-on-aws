# hw: hardware steps for AI-DLC

An [AI-DLC plugin](https://github.com/awslabs/aidlc-workflows/blob/9863ec8b8485af5953266df550caf5a26e709ab1/docs/harness-engineering/10-authoring-a-plugin.md)
that adds the hardware steps of the [embedded framework](../../README.md#2-ai-dlc-phases-with-people-deciding-at-the-gates)
to AI-DLC Workflows 2.0, without changing its five phases. Install it in a project whose work runs on embedded
hardware. Written and tested against AI-DLC Workflows 2.11.2 (commit `9863ec8`); the plugin mechanism is still
evolving, so check the plugin guide of the version you run.

## What it adds, and how each step relates to the core stages

A plugin cannot override or remove anything in a core stage; it can only add to it. It adds new stages, and
contributions that add steps and inputs to core stages. In 2.11.2, AI-DLC marks the Initialization stages complete
when it sets up a workflow, so a plugin stage there would never run; and a plugin's stages are ordered after the core
stages of their phase, with no way yet for a core stage of the same phase to wait for them (RFC #1100). The steps that
must come earlier therefore extend a core stage at the right place.

| Step | Phase | Form | Relation to the core stage |
| --- | --- | --- | --- |
| `hw-environment-detection` | Inception | Contribution to `requirements-analysis`: after its Step 1 it finds toolchains, licences, targets and reachable evidence tiers, kept in the questions file's context; after its Step 10 it writes them into `requirements.md` | New; **not a rewrite of `workspace-detection`**, which is unchanged. That stage is AI-DLC's own workspace scan at set-up |
| `hw-knowledge` | Inception | Contribution to `requirements-analysis`: after Step 1 it reads the hardware sources through the stage's `document-input` and collects fact entries with their sources; after Step 10 the requirements cite them | New |
| `hw-verification-planning` | Inception | New stage, after the core Inception stages | New |
| `hw-model-design` | Construction | Contribution to `code-generation`, for units built from a model: the plan names the model change (before Step 3), the delegation prompt carries the rules for changing the model (after Step 3), and the change is recorded after Step 5 | New |
| `hw-simulation-verification` | Construction | New stage at the end of Construction, after `build-and-test` and `ci-pipeline` | New; **not a rewrite of `build-and-test`**. The plugin also adds steps to `build-and-test`: the cross build and the checks before hardware become targets of its inventory (after Step 1) and commands of its build instructions (after Step 2), so its own failure handling applies to them, and they are summarised in `test-results.md` (after Step 9). The core build and tests are unchanged |
| `hw-bench-deployment` | Operation | New stage | New; **not a rewrite of `deployment-execution`**, which is unchanged and not used for this: it deploys through a CD pipeline and needs its artifacts, while every action on an emulated or real target is approved one at a time at an operator console |
| `hw-evidence-signoff` | Operation | New stage | New |

Two more contributions, to `nfr-requirements` and `nfr-design`, keep limits that need a tier above `build-and-test`
(simulation, twin, emulated or real target) out of the measurable targets of those stages: `build-and-test` must
verify every such target itself and fails on one it cannot, so those limits stay in the verification plan, where the
hardware stages check them.

The contributions add no outputs to the core stages: the hardware sections go into `requirements.md`,
`test-results.md` and `code-summary.md`, which those stages write anyway, and they are skipped when the project has
no embedded target. When summary confirmation is on, `requirements-analysis` asks the person to confirm its summary
before it writes `requirements.md`; the hardware findings are part of that summary and go into `requirements.md` only
after it.

The four new stages are `CONDITIONAL`. Each one first checks whether it applies (an embedded target in
`requirements.md`, checks assigned to its tier in the verification plan) and reports itself skipped when it does not.
They join the core scopes in which `build-and-test` runs, except that the two Operation stages stay out of `classic`,
`mvp` and `poc`, which have no Operation stages in core. In the other scopes, all core Operation stages of the scope
run before the two hardware stages. The stages reuse core personas (`aidlc-quality-agent`, `aidlc-architect-agent`, `aidlc-developer-agent`,
`aidlc-pipeline-deploy-agent`, `aidlc-compliance-agent`), so the plugin ships no agents.

Simulation and twin runs on the build server belong to `hw-simulation-verification`; anything that needs a deploy or
a flash to a target, emulated or real, goes through `hw-bench-deployment` and its guarded tools.

| File | Contents |
| --- | --- |
| `.aidlc-plugin/plugin.json` | The manifest |
| `stages/` | The four new stages |
| `contributions/` | The steps added to `requirements-analysis`, `nfr-requirements`, `nfr-design`, `code-generation` and `build-and-test` |
| `tests/` | `verify.sh` and `check_compose.py` |

## The checks stay the team's

The plugin says when checks run and how their verdicts are read. The checks themselves are the team's command-line
scripts and MCP servers, for example the
[in-vehicle sample's checks](../../in-vehicle-dev-server/README.md#3-checks-and-gates-before-the-bench). Unless the
team's checks document another convention, the plugin reads exit status 0 as pass (`Met` in `build-and-test`), 3 as
could not judge (`Unverified`) and any other non-zero status as fail (`Not Met`). The plugin ships no AI-DLC sensors of its own. An AI-DLC sensor
always exits 0 and reports its verdict in JSON (`pass`), so turning these checks into blocking sensors needs a small
wrapper; that is a later step. The stages import the core `required-sections` sensor, which checks headings only where
a template exists; a team that wants the stages' section names enforced adds templates as the sensor's documentation
describes.

## Prerequisites

- An AI-DLC Workflows 2.11.2 install in the project (Kiro, Kiro CLI, Claude Code, Codex or another supported harness),
  which brings the plugin tools under its `tools/` directory, and [Bun](https://bun.sh) (MIT), which AI-DLC uses.
- The team's MCP servers (build, simulator or twin, bench or flash, modelling tool) configured for the agents. On
  Kiro CLI v2 (the `kiro` projection), the core personas' agent files list their MCP servers by name: add the team's
  servers to `.kiro/agents/aidlc-developer-agent.json` (and the other personas that use them), and add them again
  after each AI-DLC upgrade, which rewrites those files. The `kiro-ide` projection needs no such change.
- To run `tests/verify.sh`: a checkout of [aidlc-workflows](https://github.com/awslabs/aidlc-workflows) at that
  version, packaged with `bun scripts/package.ts`, and Python 3 (PSF-2.0).

## Install

Build the projection for your harness and install it the way the
[plugin guide](https://github.com/awslabs/aidlc-workflows/blob/9863ec8b8485af5953266df550caf5a26e709ab1/docs/harness-engineering/10-authoring-a-plugin.md)
describes for that harness. For Kiro IDE or Kiro CLI v3 (the `kiro-ide` projection; use `kiro` for Kiro CLI v2):

```bash
bun <project>/.kiro/tools/aidlc-plugin-build.ts . kiro-ide build/
cp -R build/.kiro/. <project>/.kiro/
AIDLC_PLUGIN_ROOT=<project>/.kiro/aidlc-plugins/hw AIDLC_PROJECT_DIR=<project> AIDLC_HARNESS_DIR=.kiro \
  bun <project>/.kiro/aidlc-plugins/hw/hooks/compose.ts
```

The `kiro-ide` projection also registers a session-start hook that composes the plugin again at the start of each
session; the `kiro` projection has none, so run the compose command after every AI-DLC upgrade. Kiro has no trust
prompt for a plugin dropped into the project folder, and the hook runs the plugin's compose script each session:
review the plugin before you install it.

## Cost

The plugin is Markdown and runs no service of its own. It adds steps that the agent carries out, so a workflow uses
more model requests than without it.

## Cleanup

Deleting `.kiro/aidlc-plugins/hw` alone does not undo what compose merged into the install. First disable the plugin
with the project selection command of the plugin guide, naming the plugins you keep:
`bun .kiro/tools/aidlc.ts engine plugin select aidlc` (or `aidlc engine plugin select aidlc` with the `aidlc` command
on the PATH) keeps core only. It strips the plugin's steps from the core stages and disables its four stages, and it
refuses while an active workflow still needs the plugin. Then delete `.kiro/aidlc-plugins/hw` and, for the
`kiro-ide` projection, the session-start hook `.kiro/hooks/aidlc-hw-compose.json`, which would otherwise fail at every
session. The disabled stage files stay in the install and do not run: `.kiro/aidlc-common/stages/*/hw-*.md`,
`.kiro/skills/hw-*/`, and `.kiro/tools/data/plugin-files-hw.json` and `plugin-owned-hw.json`.

## Verify

```bash
tests/verify.sh <aidlc-workflows>/dist/kiro-ide kiro-ide
```

runs the official `aidlc-plugin-validate` and `aidlc-plugin-test` on the plugin. On `kiro` and `kiro-ide` it then
composes the plugin into a copy of the install and checks the stages, their edges, scopes and order, where each step
is spliced into a core stage, and that every core stage reads as before outside the plugin's blocks.

Last run on 2026-10-28 with AI-DLC Workflows 2.11.2: clean on `kiro`, `kiro-ide`, `claude` and `codex`, with the
placement checks on `kiro` and `kiro-ide`. The new stages compile to `hw-verification-planning` 2.10 (after
`delivery-planning`), `hw-simulation-verification` 3.8 (after `ci-pipeline`), `hw-bench-deployment` 4.8 and
`hw-evidence-signoff` 4.9. No agent has run a workflow with the plugin yet; the first rehearsal of a scenario will.
