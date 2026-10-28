---
target: nfr-design
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

The same holds for performance budgets and capacity thresholds of this stage: a budget only such a tier can show
cites the verification plan instead of stating a measurable target.
