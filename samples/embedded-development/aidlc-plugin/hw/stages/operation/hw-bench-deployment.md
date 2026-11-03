---
slug: hw-bench-deployment
number: 4.85
name: Hardware Bench Deployment
plugin: hw
phase: operation
execution: CONDITIONAL
condition: Execute when the verification plan assigns checks to an emulated or real target and that target is reachable through the team's guarded bench or flash tools.
lead_agent: aidlc-pipeline-deploy-agent
support_agents:
  - aidlc-quality-agent
mode: inline
produces:
  - hw-bench-results
consumes:
  - artifact: hw-verification-plan
    required: true
  - artifact: build-test-results
    required: true
  - artifact: hw-simulation-results
    required: false
requires_stage:
  - hw-simulation-verification
  - build-and-test
  - hw-verification-planning
sensors:
  - required-sections
  - upstream-coverage
scopes:
  - enterprise
  - feature
  - bugfix
  - refactor
  - security-patch
  - workshop
  - express
ars:
  targets: [r]
  cost: 5
inputs: hw-verification-plan, test-results.md of build-and-test and, when it ran, hw-simulation-results
outputs: hw-bench-results.md (under this stage's record dir, engine-resolved)
---

# Hardware Bench Deployment

MANDATORY: Follow stage-protocol.md for approval gates, question format, and completion messages.

Deploys, flashes or updates the verified build on an emulated target, a bench or a device through guarded tools, and runs the
checks that need the target, for example a recorded replay with its runtime log compared with the baseline log. Core
`deployment-execution`, which pushes through a CD pipeline, is not used for this: every action on a target is
approved one at a time by a person. All core Operation stages of the scope run before this one; the core deployment
stages apply only to what the project deploys through a CD pipeline.

## Steps

### Step 0: Check That the Stage Applies

The stage applies when `hw-verification-plan.md` exists and assigns at least one check to an emulated or real target and that
target is reachable through the team's guarded bench or flash MCP server. If it does not apply, run
`{{INVOKE}} engine orchestrate report --stage hw-bench-deployment --result skipped --reason "<specific reason>"`
and stop.

### Step 1: Confirm What Must Pass First

Read the `## Checks before hardware (hw)` section of `test-results.md` and, when `hw-simulation-verification` ran,
`hw-simulation-results.md`. If the section is missing, or any row or check that the plan requires before a target is
not `Met`, stop, report it and ask the person.
When the plan has both an emulated and a real target, the emulated target's checks pass before the real target is
used.

### Step 2: Use Only the Guarded Bench Tools

Reach the target only through the team's bench or flash MCP server, never through a raw shell command. The server
holds the guardrails: one session per target at a time, a record of every physical action, the preconditions of the
verification plan (for example supply voltage, ignition state, battery level), and a check of the target's state after
any interruption before anything else runs.

### Step 3: Request Each Action

Request each deploy, flash, software update, restart or target write for the digest of the build that passed the
checks before hardware. Each request waits for a person's approval at the operator console. Never retry a refused or failed action
by yourself; report it and ask.

### Step 4: Run the Checks on the Target

Run the checks the plan assigns to the target, and read back the installed build's digest; a digest that differs
from the approved one stops the run. A check judges a run only once the run has ended. Retry a failing check only
within the repair bounds of the plan.

### Step 5: Write the Results

Write `hw-bench-results.md`. Its first line names its sources: `Sources: hw-verification-plan, build-test-results`.
Then every action requested, approved, refused or reconciled; every check with its verdict
and tier (emulation or real target); and the installed digest.

### Step 6: Open the Approval Gate

Run `{{INVOKE}} engine orchestrate report --stage hw-bench-deployment --result awaiting-approval`.

### Step 7: Present Completion & Request Approval

Completion emoji: :electric_plug:
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
