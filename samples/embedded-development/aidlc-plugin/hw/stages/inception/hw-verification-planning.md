---
slug: hw-verification-planning
number: 2.95
name: Hardware Verification Planning
plugin: hw
phase: inception
execution: CONDITIONAL
condition: Execute when the Hardware environment (hw) section of requirements.md lists an embedded target.
lead_agent: aidlc-quality-agent
support_agents:
  - aidlc-architect-agent
mode: inline
produces:
  - hw-verification-plan
consumes:
  - artifact: requirements
    required: true
requires_stage:
  - requirements-analysis
sensors:
  - required-sections
  - upstream-coverage
scopes:
  - enterprise
  - feature
  - mvp
  - poc
  - bugfix
  - refactor
  - security-patch
  - classic
  - workshop
  - express
ars:
  targets: [ve, ua]
  cost: 2
inputs: requirements.md with its Hardware environment (hw) and Hardware facts (hw) sections
outputs: hw-verification-plan.md (under this stage's record dir, engine-resolved)
---

# Hardware Verification Planning

MANDATORY: Follow stage-protocol.md for approval gates, question format, and completion messages.

Decides, before any code changes, what evidence each requirement needs and where it can come from. The checks and the
evidence page later hold the work to this plan.

## Steps

### Step 0: Check That the Stage Applies

The stage applies when the `## Hardware environment (hw)` section of `requirements.md` lists an embedded target. If
it does not apply, run
`{{INVOKE}} engine orchestrate report --stage hw-verification-planning --result skipped --reason "<specific reason>"`
and stop.

### Step 1: Read the Inputs

Read `requirements.md`, including its sections `## Hardware environment (hw)` and `## Hardware facts (hw)`, and the
team rules among the hardware sources.

### Step 2: Assign an Evidence Tier to Each Requirement

For every requirement, write the lowest tier of the team's rules that can show it (for example unit test, simulation
or twin, emulation, real target) and the check that will judge it. Simulation and twin runs on the build server
belong to `hw-simulation-verification`; anything that needs a deploy or a flash to an emulated or real target belongs
to `hw-bench-deployment`. A requirement marked real-target only stays real-target only: if the real target is not
reachable, the plan says that its evidence will be reported as blocked, not passed.

### Step 3: Set the Limits and Tolerances

From the fact entries and team rules, write the limits the checks apply (resource limits, timing windows, physical
preconditions for actions on a target) and, where code is generated from a model, the back-to-back tolerances between
model and code. Each value cites its fact entry; none is chosen here.

### Step 4: Bound the Repair Loops on a Target

Write how many times a failing check on an emulated or real target may be retried before the work stops and a person
decides, from the team rules where they say so. The build and the checks before hardware follow the failure handling
of `build-and-test`.

### Step 5: Write the Plan

Write `hw-verification-plan.md`. Its first line names its source: `Sources: requirements`. Then the sections
`## Evidence per requirement`, `## Limits and tolerances` and `## Repair bounds`, and what the reachable tiers cannot
show.

### Step 6: Open the Approval Gate

Run `{{INVOKE}} engine orchestrate report --stage hw-verification-planning --result awaiting-approval`.

### Step 7: Present Completion & Request Approval

Completion emoji: :clipboard:
Review path: this stage's engine-resolved record dir.
Standard 2-option approval (Approve / Request Changes).
STOP for the human response. Report Approve with
`--result approved --user-input "<exact choice>"`; report
Request Changes with `--result rejected --user-input "<feedback>"`, revise the
artifacts, then report `--result revised` before re-presenting.

## Sensors

This stage writes one markdown artefact under its record dir. It imports `required-sections` and
`upstream-coverage`; the plugin ships no template for its artefact, so `required-sections` has no sections to check
there, and the sections named in the steps are this stage's own rule.

## Learn

When `directive.protocol_modules` lists `learnings`, follow
`stage-protocol-learnings.md`: keep the diary at `directive.memory_path` while
working, and take the learnings step before the approval gate; that module says
when it asks the person anything. When the module is absent, skip both the diary
and the step.
