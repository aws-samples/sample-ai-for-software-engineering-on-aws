---
slug: hw-simulation-verification
number: 3.85
name: Hardware Simulation Verification
plugin: hw
phase: construction
execution: CONDITIONAL
condition: Execute once after build-and-test when the verification plan assigns checks to simulation or twin runs on the build server, or a back-to-back comparison.
lead_agent: aidlc-quality-agent
support_agents:
  - aidlc-developer-agent
mode: inline
produces:
  - hw-simulation-results
consumes:
  - artifact: hw-verification-plan
    required: true
  - artifact: build-test-results
    required: true
  - artifact: code-summary
    required: false
requires_stage:
  - build-and-test
  - hw-verification-planning
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
  targets: [ve, r]
  cost: 4
inputs: hw-verification-plan and test-results.md of build-and-test, with its Checks before hardware (hw) section
outputs: hw-simulation-results.md (under this stage's record dir, engine-resolved)
---

# Hardware Simulation Verification

MANDATORY: Follow stage-protocol.md for approval gates, question format, and completion messages.

Runs the build in simulators or digital twins on the build server, with no deploy or flash to any target, and
compares the generated code with its model where there is one. Deploys and flashes to emulated or real targets belong
to `hw-bench-deployment`.

## Steps

### Step 0: Check That the Stage Applies

The stage applies when `hw-verification-plan.md` exists and assigns at least one check to simulation or twin runs on the build
server, or a back-to-back comparison. If it does not apply, run
`{{INVOKE}} engine orchestrate report --stage hw-simulation-verification --result skipped --reason "<specific reason>"`
and stop.

### Step 1: Confirm the Checks Before Hardware Passed

Read the `## Checks before hardware (hw)` section of `test-results.md`. If the section is missing or any row is not
`Met`, stop, report it and ask the person.

### Step 2: Run the Simulation Checks

Through the team's simulator or twin MCP server, run what the verification plan assigns to this tier, for example a
twin run of frozen tests or model-in-the-loop and software-in-the-loop tests. Each check's verdict is its exit status
and its log, as in `build-and-test`.

### Step 3: Back-to-Back Comparison (Units Built from a Model)

For each unit built from a model (its `code-summary.md` has a `## Model changes (hw)` section), compare the results
of the generated code with those of the model on every test, within the tolerances of the verification plan.

### Step 4: Write the Results

Write `hw-simulation-results.md`. Its first line names its sources: `Sources: hw-verification-plan, build-test-results`.
Then one row per check with its verdict and its tier, the differences found and whether
the plan allows each one, and what this tier cannot show. A requirement marked real-target only is listed as blocked
here, not passed.

### Step 5: Open the Approval Gate

Run `{{INVOKE}} engine orchestrate report --stage hw-simulation-verification --result awaiting-approval`.

### Step 6: Present Completion & Request Approval

Completion emoji: :test_tube:
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
