---
target: code-generation
plugin: hw
adds:
  consumes:
    - artifact: hw-verification-plan
      required: false
fragments:
  - anchor: before-step:3
    order: 100
  - anchor: after-step:3
    order: 110
  - anchor: after-step:5
    order: 120
---

## fragment: before-step:3

### Step 2a (hw): Hardware in the plan

When `hw-verification-plan.md` exists:

- Keep the `## Testing Contract` exactly as rendered. Do not write limits that need a tier above `build-and-test`
  (simulation, twin, emulated or real target) into the plan steps or `unit-test-instructions.md`: they stay in the
  verification plan, and the hardware stages check them.
- For a unit whose code is generated from a model (hw-model-design; for example a Simulink model), the plan names the
  model files to change, the model's tests (model-in-the-loop) and modelling-rule checks to run, the code generation
  settings, and the generated files, so that the plan of Step 3 covers the model change.

## fragment: after-step:3

### Step 3a (hw): Rules for a unit built from a model

For a unit whose code is generated from a model, include these rules in the delegation prompt of Step 4:

- Make the change in the model, in the modelling tool, through its MCP server. Do not edit the generated code.
- Run the model's tests and modelling-rule checks in the tool, as the plan names them; their results decide.
- Generate the code with the team's code generation settings, unchanged, and keep the generated code and the model
  together in the change.

The back-to-back comparison of the generated code with the model runs in `hw-simulation-verification`, against the
tolerances of the verification plan.

## fragment: after-step:5

### Step 5a (hw): Record the model change

For work built from a model, `code-summary.md` has a section `## Model changes (hw)` with what changed in the model,
the model tests run and their results, and the code generation settings used. For a Unit, `source-manifest.json` also
lists the model files and every generated file it changed.
