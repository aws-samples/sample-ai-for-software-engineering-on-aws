---
target: build-and-test
plugin: hw
adds:
  consumes:
    - artifact: hw-verification-plan
      required: false
fragments:
  - anchor: after-step:1
    order: 200
  - anchor: after-step:2
    order: 210
  - anchor: after-step:9
    order: 220
---

## fragment: after-step:1

### Step 1a (hw): The checks before hardware are targets

When the `## Hardware environment (hw)` section of `requirements.md` lists an embedded target, add to the inventory
one target for the cross build and one for each of the team's checks before hardware (for example static analysis
against the findings backlog, resource and size limits, traceability of every change): source the team rules or
`hw-verification-plan.md`, expected value "exit status 0", and the command that produces it. The checks are the team's
command-line scripts; do not edit them, their settings or their limits.

Unless the team's checks document another convention, read a check's exit status this way: 0 pass (`Met`), 3 the
check could not judge, for example because an input is missing (`Unverified`), any other non-zero status fail
(`Not Met`). No test run, a skipped test or an empty result is never `Met`.

Do not add the checks that `hw-verification-plan.md` assigns to `hw-simulation-verification` or `hw-bench-deployment`
(simulation, twin, back-to-back, emulated or real target): those stages run them. If a core source of the inventory
(the NFR documents or the Testing Contract) still states one as a measurable target, keep it as Step 9 item 4 says,
with the hardware stage as Owning Stage and the verdict `Unverified`, and correct the source upstream; never change a
verdict to let the stage pass.

## fragment: after-step:2

### Step 2a (hw): The cross build and the checks in the build instructions

In `build-instructions.md`, add to the build commands the cross build with the team's cross toolchain and flags,
warnings as errors, and after it each check of Step 1a, so that Step 9 item 1 runs them with the build. As targets of
Step 1a, their verdicts go through Step 9's failure handling like any other target.

## fragment: after-step:9

### Step 9a (hw): Summary of the checks before hardware

As part of Step 9 item 5, on every exit path, add to `test-results.md` a section `## Checks before hardware (hw)` with
one row per target of Step 1a: the check, the commit it judged, its exit status, its verdict and where its log is.
Nothing goes to an emulated or real target until every row is `Met`.
