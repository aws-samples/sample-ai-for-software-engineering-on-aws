---
slug: hw-evidence-signoff
number: 4.9
name: Hardware Evidence Sign-off
plugin: hw
phase: operation
execution: CONDITIONAL
condition: Execute when the Hardware environment (hw) section of requirements.md lists an embedded target and hw-verification-plan exists.
lead_agent: aidlc-quality-agent
support_agents:
  - aidlc-compliance-agent
mode: inline
produces:
  - hw-evidence-page
consumes:
  - artifact: hw-verification-plan
    required: true
  - artifact: build-test-results
    required: true
  - artifact: hw-simulation-results
    required: false
  - artifact: hw-bench-results
    required: false
requires_stage:
  - hw-bench-deployment
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
  targets: [ve]
  cost: 2
inputs: the verification plan and every hardware result of this workflow
outputs: hw-evidence-page.md (under this stage's record dir, engine-resolved)
---

# Hardware Evidence Sign-off

MANDATORY: Follow stage-protocol.md for approval gates, question format, and completion messages.

Puts every result of the work on one page, labelled by the tier of its evidence, for the engineer who owns the
release to sign off.

## Steps

### Step 0: Check That the Stage Applies

The stage applies when the `## Hardware environment (hw)` section of `requirements.md` lists an embedded target and
`hw-verification-plan.md` exists. If it does not apply, run
`{{INVOKE}} engine orchestrate report --stage hw-evidence-signoff --result skipped --reason "<specific reason>"`
and stop.

### Step 1: Collect the Results

Read the verification plan, the `## Checks before hardware (hw)` section of `test-results.md` and, for the stages that
ran, `hw-simulation-results.md` and `hw-bench-results.md`. Where the team's checks write their own evidence page, use
it and add only what is missing.

### Step 2: Write the Evidence Page

Write `hw-evidence-page.md`. Its first line names its sources: `Sources: hw-verification-plan, build-test-results`.
Then:

- the commit and the digest of the build;
- one row per requirement: its check, verdict and tier;
- each requirement marked real-target only whose only evidence comes from a lower tier, listed as **blocked**;
- each requirement the plan assigns to a stage that did not run, listed as **not verified**;
- what the tiers used cannot show;
- differences the plan allows, each with its reason;
- where an agent's summary of a run disagrees with a check's verdict, both, side by side;
- a sign-off line for the release owner.

A check's verdict is its exit status and its log, never an agent's summary.

### Step 3: Open the Approval Gate

Run `{{INVOKE}} engine orchestrate report --stage hw-evidence-signoff --result awaiting-approval`.

### Step 4: Present Completion & Request Approval

Completion emoji: :white_check_mark:
Review path: this stage's engine-resolved record dir.
Standard 2-option approval (Approve / Request Changes).
The release owner approves only when no requirement is failed, blocked or not verified.
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
