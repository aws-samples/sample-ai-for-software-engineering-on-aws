---
target: nfr-requirements
plugin: hw
adds:
  consumes:
    - artifact: hw-verification-plan
      required: false
fragments:
  - anchor: before-step:1
    order: 100
---

## fragment: before-step:1

### Before you start (hw): limits that need a later tier

When `hw-verification-plan.md` exists, the limits it assigns to a tier above `build-and-test` (simulation, twin,
back-to-back, emulated or real target; for example peak memory on the target, timing on the real chip, a log
comparison on a replay) are checked by `hw-simulation-verification` or `hw-bench-deployment`. Do not write them as
measurable targets of this stage: `build-and-test` must verify every such target itself, and cannot.

For an Inception NFR that only such a tier can show, write its `NFRx.y` as an obligation on the code, with no
measurable value: cite the section `## Limits and tolerances` of `hw-verification-plan.md` and name the hardware stage
that verifies it.
