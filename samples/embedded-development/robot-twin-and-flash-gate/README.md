# Robot firmware and software: a digital twin decides, a person flashes

> **Status: in development.** This page defines the scenario: the work, the knowledge, the gates, the tools and the
> definition of done that the runnable sample must meet. The runnable parts are being built against it (see
> [Build plan](#build-plan)). It follows the [embedded framework](../README.md) and its five building blocks.

## Business measures

The measures a robot team would use to decide whether this pays off, each with a target stated as a hypothesis and
the [scorecard](#how-the-sample-is-measured) item that measures it. Targets are set against the team's own baseline
(its history for comparable changes, or the same change done the usual way) and corrected after the first
rehearsal.

| Business measure | Target (hypothesis) | Business goal | Scorecard item |
| --- | --- | --- | --- |
| Cycle time of a firmware change, from request to sign-off | −50 % | The agents try designs in the twin against a frozen requirement; only passing designs reach a person | Time to an approved requirement, to the first candidate that passes the twin and to sign-off; engineer hours on the change |
| Flashes and test moves on real hardware | −70 % | Most verification happens in the twin and the emulator | Flashes and test moves approved, refused and reconciled; results by evidence tier |
| Behaviour on the device that the twin did not predict | 0 | The twin's verdict holds on the emulated board and the device | Behaviour on the emulated board or the device that the twin did not predict |
| Unsafe physical actions carried out | 0 | Nothing flashes or moves the robot unsupervised | Requests refused because the robot was not in a safe state; actions carried out outside a safe state |

## What: change how a robot behaves, prove it in a twin, then update the robot through two separate paths

Robots, and many physical AI devices, have two computers. A real-time controller (a microcontroller running
firmware) keeps the machine safe and stable: balance, motor limits, fall detection. A main computer (embedded Linux)
runs perception, voice, apps and the connection to the cloud.

AI agents can now write code for both, and they can run the development loop themselves: write, simulate, test,
score. On a robot, though, a wrong step has physical consequences. A firmware change that looks right can make the
machine fall, and an agent that flashes firmware unsupervised can damage it.

This sample takes one behaviour change through AI-DLC on that setup:

- the change touches the controller firmware, so it is judged in a digital twin that runs the firmware itself, not a
  rewrite of it, against a frozen requirement;
- it reaches the controller only through a flash gate that a person operates;
- the main computer's software is updated through a separate path with health checks and rollback.

Everything runs on one machine without a robot. The twin runs the firmware in the loop, and an emulated
controller board and a container stand in for the two computers. A real robot is an optional device profile; the AWS
profile further down is optional too.

| A team starts with | The sample shows how to end with |
| --- | --- |
| A behaviour change, the robot's controller firmware and its documents (motor and sensor datasheets, the controller's interface) | Requirements with acceptance criteria, each limit and register traced to its source page, frozen before any code is written |
| The team's firmware rules, toolchains for both computers and the controller's limits | A firmware change that builds for the controller and for the twin from the same source commit, within flash and RAM limits |
| A simulator that nobody fully trusts | A twin that runs the unmodified firmware against a physics model, with the requirement's tests and their results, labelled as simulation |
| A robot the team does not want agents to flash or move unsupervised | Firmware writes only through a flash gate a person operates, refused outside safe physical conditions; software updates through a separate path that defers and rolls back |
| An engineer who owns the release | The same engineer signs it off from one evidence page, with every result labelled by its evidence tier |

**What it means for the team.** The agents can try many designs in the twin, and only designs that pass the frozen
requirement reach a person. The engineer's time moves from re-flashing and watching test runs to deciding at four
points: the change, the requirement, the flash, the release. The sample measures this with the
[one-day guided rehearsal](../../../docs/guided-rehearsal.md); the [scorecard](#how-the-sample-is-measured) lists
what is recorded. It reports no productivity figures until a rehearsal has produced them.

## The scenario

All names, code and data in this scenario are synthetic.

- **Robot:** a fictional two-wheeled self-balancing robot, *RB-1*. Its documents hold a synthetic model: mass, wheel
  radius, motor characteristics, those of its inertial measurement unit (IMU, the accelerometer and gyroscope the
  controller balances with), and the rated push impulse it must withstand.
- **Controller firmware:** a small C firmware written for the sample: IMU read, a balance controller, a motor command
  path, fall detection and an actuator guard (speed and torque limits). It uses fixed-point arithmetic, because the
  Cortex-M3 target has no floating-point unit. It builds for that target. From the same
  source commit, with a hardware abstraction layer, it also builds for the host so the twin can run it.
- **Main computer:** a Linux container with a robot app (commands, telemetry, a "behaviour" API) and an update
  client.
- **Twin:** a physics model of RB-1 in MuJoCo, with the firmware compiled for the host in the loop. It emulates the
  IMU with noise and bias and the motor driver, and uses a fixed physics step. Pushes are applied as impulses at a
  fixed body point, with many random seeds per test point.
- **Bench:** an emulated controller board, QEMU's `mps2-an385` (Cortex-M3), for the flash path. Here "flash" writes
  the emulated board's flash image file, and a test move is the firmware's boot and self-test over the emulated
  serial port, since the board has no sensors or motors. A simulated robot state reports battery level, "moving",
  "on its stand" and "a person present".
- **Operator console:** a separate terminal process, outside the agents' tools. A person sees each requested flash
  or test move with its build digest (the SHA-256 of the exact image) and approves or refuses it there. The robot
  state inputs are set only at this console or by a scripted scenario; the agents' tools can read them but not
  change them.
- **Change request:** *Add a recovery limit to the actuator guard. After a push, wheel speed must stay within the
  guard's limit, and the robot must not travel more than 0.15 m before it is stable again. It must still not fall for
  pushes up to the rated impulse.* The requirement, the push points, the seeds and the pass thresholds are frozen and
  versioned before any code is written.
- **Seeded difficulties** for the rehearsal, each caught by a check rather than by luck:
  - a rewrite of the controller in another language "passes" in a simple simulator, but the design fails when the
    real firmware runs in the twin;
  - the firmware's balance point is not zero, which only its own code shows;
  - the first candidate meets the travel limit by cutting torque, and falls at the rated impulse;
  - "fall" means different angles in the requirement, the twin and the firmware, and the mismatch has to be resolved
    in the requirement, not in the test.

## How

### 1. Knowledge with citations

- `knowledge/rb1-robot-notes.md` (with a rendered PDF): the synthetic robot documents with numbered pages. They cover
  geometry and mass, motor and IMU characteristics, the controller's command and telemetry interface, the safe
  operating limits and the physical gate's settings. A fact extraction step turns them into `knowledge/facts/`, one
  entry per limit, register and parameter, each with its page, for example `[RB1-NOTES p.9 §4.1]`.
- `knowledge/team-rules.md`: firmware rules, build flags for both targets, flash and RAM limits, the evidence tiers,
  and the definition of done.
- A check confirms that every requirement, test and twin parameter cites a fact entry.

### 2. AI-DLC phases and gates

The five phases of AI-DLC Workflows 2.0, with the hardware steps of the
[framework](../README.md#2-ai-dlc-phases-with-people-deciding-at-the-gates):

| AI-DLC phase | Work in this scenario | Human gate |
| --- | --- | --- |
| Initialization | AI-DLC's own set-up | None; automatic |
| Ideation | Decide whether the behaviour change is worth doing and whether it touches safety functions | The change approved for work |
| Inception | Detect the toolchains for both computers, the twin, the emulated board and, if present, a real robot; requirements and acceptance criteria from the fact entries; the push points, seeds and thresholds frozen and versioned; the verification plan: the evidence tier each requirement needs and, in the model-based profile, the back-to-back tolerances; design of the guard change | Requirements and test definition approved; build start approved |
| Construction | Firmware change, or a change to the control-law model, with unit tests; builds for the controller and for the twin; static checks; the twin runs the frozen tests | The checks and the twin decide; a candidate returns to its owner on any failure |
| Operation | Flash the emulated board through the gate, or a real robot in the device profile; update the main computer's software through its own path; boot and self-test on the target; one evidence page with every result labelled by tier | Each flash and test move, approved for its build digest at the operator console; each software release to the robot; the release owner signs off |

### 3. Checks and gates before the robot

Checks are command-line scripts with pass or fail. The agents cannot change them, the frozen tests or the twin's
parameters.

| Check | Pass condition |
| --- | --- |
| `checks/build.sh` | Firmware builds for the controller and the host from the same source commit with warnings as errors; the main computer's app builds |
| `checks/static.sh` | Static analysis (cppcheck and clang-tidy with the team's rule set): no new findings |
| `checks/unit.sh` | Unit tests pass for the guard, the controller and the app |
| `checks/size.sh` | Flash and RAM use of the controller build within the limits in the team rules |
| `checks/twin.sh` | The frozen push tests in the twin, with the firmware in the loop: no falls up to the rated impulse, travel and wheel speed within the limits, for every seed |
| `checks/trace.sh` | Every requirement, test and twin parameter cites a fact entry; every result carries its evidence tier |
| `checks/backtoback.sh` | Model-based profile only: the twin's results with the generated control code equal the model-in-the-loop results on every frozen test, within the tolerances in the verification plan |

**Evidence tiers.** Every test result on the evidence page carries one of four tiers: *mock* (unit tests against
fakes), *simulation* (the twin), *emulation* (the QEMU board) and *device* (a real robot, in the optional device
profile only). The page links one source commit to both build digests, host and Cortex-M, so a reviewer can see that
the twin and the flashed image come from the same source. It also lists what each tier cannot show. The twin runs
the host build, so it shows neither interrupt timing nor the controller's stack use. The emulator runs the Cortex-M
build, but not real interrupt timing, sensors or motors. Simulation and emulation results are never reported as
device results.

The three gates of the framework apply:

- **Quality gate:** nothing is flashed until the checks pass. The twin, not the agent, decides whether a design meets
  the requirement.
- **Action gate:** the flash gate writes only the application partition (the bootloader and the calibration data
  are never written; the layout is in the robot notes), and only the image whose digest a person
  approved at the operator console, not in the agent's chat. It backs up first, reads back and verifies, and never
  retries by itself. Software releases to the main computer are approved by a person.
- **Physical gate:** the flash gate refuses below the battery threshold, when the robot is not on its stand, or with
  nobody present. The main computer's update client defers updates while the robot is moving or the battery is low.
  The thresholds are settings in the robot notes, for example 50 % battery for a flash.

### 4. Tool connectors with guardrails

Three MCP servers. Their guardrails live in the servers, whatever the agent session allows.

- **`build`**: build both firmware targets and the app, run a check, read its log.
- **`twin`**: run the frozen tests on a given build, return per-seed results and traces. The tests and the model are
  read-only.
- **`robot`**: read state and telemetry; request a flash plan for a build, which returns the digest and the
  preconditions; request a test move; release software to the main computer. The flash itself runs only after
  approval at the operator console.
  - A lease gives one session the robot at a time.
  - Risk tiers: observe (lease, no approval), test move (lease and one approval), persistent write (lease, approval,
    person present), recovery (a separate approval).
  - After an interrupted write the robot is *unknown*. It accepts only reads and a reconcile (a person checks and
    records its actual state); nothing is retried automatically.

Every call is recorded with its tier, its result and the build digest. Neither server needs `--trust-all-tools`, and
the sample's agent configurations do not use it.

**Optional AWS profile.** The `robot` server can sit behind Amazon Bedrock AgentCore Gateway with AgentCore Policy.
A deterministic policy on the caller, the tool and its arguments then decides before any call reaches the robot, for
example "this agent may call the read tools, and request a test move only with a speed of at most 0.2 m/s". The
physical checks, such as the battery level, stay in the `robot` server. The gateway runs in AWS, so it must be able to
reach the `robot` server, for example through a tunnel the team controls. That endpoint accepts only authenticated
calls from the gateway, and every flash still waits for the operator console. Check AgentCore's current
availability and Regions before choosing this profile. It needs an AWS
account and credentials allowed to create the gateway and the policy, it is charged at AgentCore's prices, and
`cleanup.sh` deletes what it created.

### Optional: a control law designed in Simulink

Controller teams often design control laws as models and generate the firmware's control code from them. The optional
model-based profile does this for the balance controller and the actuator guard: a Simulink model with a plant model of
RB-1, configured to generate fixed-point C for the Cortex-M3. In the `hw-model-design` step the agent changes the model
through MathWorks' [MATLAB MCP Core Server](https://www.mathworks.com/products/matlab-mcp-core-server.html) and
[Simulink Agentic Toolkit](https://www.mathworks.com/products/simulink-agentic-toolkit.html), which the agent uses as
one more MCP server with its own permission class, and runs model-in-the-loop tests. The generated code goes into the
firmware, and the twin then runs that firmware against the frozen requirement as usual. A back-to-back comparison of the
twin's results with the model-in-the-loop results shows that, on the frozen tests, the generated code matches the model
within the tolerances in the verification plan; fixed-point saturation is one difference it can catch. Flashing still
goes through the gate. The profile needs MathWorks licences; without them, the generated code and recorded model results
are committed and the agents cannot change the model.

### 5. The agent next to the robot

The agents run on the team's development host next to the twin and the robot. Flashing waits for the operator
console. What leaves the network is the agents' traffic to the model service, which includes the code and documents
they read. In the optional AWS profile the gateway's calls also pass through the tunnel into the network. Use only
material you are allowed to send to the model service.

### Where it runs

| Part | In Kiro (IDE or CLI) | In Kiro Crew |
| --- | --- | --- |
| `knowledge/` | Steering files | A knowledge source the agents search and cite |
| `mcp/build`, `mcp/twin`, `mcp/robot` | MCP configuration | MCP servers of a custom agent |
| `checks/` | Hooks that block the next tool call on failure; a deny rule on raw flash commands as defence in depth; the guardrails themselves are in the MCP servers | Run by a Kiro Crew app before each gate, as in the [agent-team sample](../../agent-team-on-kiro-crew/) |
| Roles (optional) | Custom agents: the coder edits firmware and never flashes | Team members |

The parts may also be packaged as an AI-DLC plugin; the plain parts stay usable on their own.

## How the sample is measured

The rehearsal scorecard records:

- engineer hours on the change, by phase;
- candidates tried in the twin, and how many passed;
- time from the change request to an approved requirement, to the first candidate that passes the twin, and to the
  release sign-off;
- check failures caught before the flash, by check;
- flashes and test moves approved, refused and reconciled, by target (emulated board or device);
- results by evidence tier;
- any behaviour on the emulated board or the device that the twin did not predict;
- flash and move requests refused because the robot was not in a safe state, and any action carried out outside a
  safe state;
- in the model-based profile, back-to-back differences found, and how many were real defects in the model or the
  code generation settings.

The first rehearsal's numbers are the baseline. The sample publishes measured numbers only, with how they were
measured, and labels each by its evidence tier.

## Why

- **Run the firmware itself, not an AI rewrite of it.** A controller rewritten by an agent can look right in a simple
  simulator and hide exactly what makes the real machine fall. The twin runs the firmware that will be flashed.
- **A frozen requirement makes the twin a judge.** If the agent can change the test or the thresholds, the twin
  proves nothing. Freezing and versioning them before any code is what lets the loop run unattended.
- **Two update paths.** Software that can roll back ships often; control firmware waits for a person and a safe
  physical state. One update system, two risk classes.
- **Approvals bound to the exact image.** An approval that an agent can type, or that covers "a flash" in general,
  is not a control. A digest approved at the operator console is.
- **Label every result by its tier.** Simulation results are useful, and they are not device results. The evidence
  page keeps them apart and states what the twin cannot show.

## Build plan

Each item is a pull request. The sample becomes available when all of them are merged and the rehearsal guide has
been dry-run once.

1. Synthetic RB-1 documents (Markdown and rendered PDF), fact entries, team rules, the frozen requirement and tests.
2. Firmware reference project with its hardware abstraction layer, builds for the controller and the host, unit
   tests; the main computer's app and update client.
3. Twin: MuJoCo model, firmware-in-the-loop harness, push tests with seeds, trace output. For the first seeded
   difficulty, a simple simulator and the rewritten controller that passes in it.
4. Bench: the emulated board for the flash path with boot and self-test, the simulated robot state, the operator
   console, and the flash gate with backup and read-back.
5. Checks, each with a failing and a passing example.
6. MCP servers `build`, `twin` and `robot` with a test for each guardrail; the optional AWS profile.
7. Kiro and Kiro Crew configurations; optional AI-DLC plugin.
8. The evidence page generator; rehearsal guide and scorecard; one dry run with the time and credits it used.
9. Optional model-based profile: the Simulink model of the balance controller and actuator guard with the RB-1 plant
   model, generated code, recorded model results and `checks/backtoback.sh`.

Definition of done for the sample itself: runs on one Linux host, or a Mac with a container runtime, from `setup.sh`
to a signed-off evidence page without a robot; `cleanup.sh` removes everything it created, including the optional
AWS profile's resources; every third-party tool is listed with its licence; synthetic data only, with no customer
names, code, data or identifying details; no credentials or account identifiers; no `--trust-all-tools`.

## Layout

| Folder | Contents |
| --- | --- |
| `knowledge/` | Synthetic robot notes, fact entries, team rules, the frozen requirement and tests |
| `checks/` | The six checks and the back-to-back check of the model-based profile |
| `model/` | The optional model-based profile: model, generated code, recorded model results |
| `mcp/` | `build`, `twin` and `robot` servers and their guardrail tests |
| `reference-project/` | Controller firmware with its hardware abstraction layer, the main computer's app and update client |
| `twin/` | MuJoCo model, firmware-in-the-loop harness, the simple simulator and the rewritten controller |
| `bench/` | Emulated board setup, simulated robot state, operator console, flash gate |
| `cloud/` | The optional AWS profile |
| `evidence/` | Evidence page generator |
| `rehearsal/` | One-day guide and scorecard |

## Prerequisites

To be completed with the build: a Linux host, or a Mac with a container runtime (Docker, Podman or Colima), and Kiro
or Kiro Crew. Third-party tools and their licences will be listed here, among them MuJoCo (Apache-2.0), QEMU
(GPL-2.0), the Arm GNU toolchain (GPL-3.0 with the GCC runtime library exception; newlib under its BSD-style
licences), CMake (BSD-3-Clause), Unity (ThrowTheSwitch, MIT) for firmware unit tests, GoogleTest (BSD-3-Clause) for
the app, cppcheck (GPL-3.0) and clang-tidy (Apache-2.0 with LLVM exception). They are used as tools and
not redistributed. The optional AWS profile also needs an AWS account and the AWS CLI.

The optional model-based profile also needs MATLAB, Simulink, Stateflow and Embedded Coder from MathWorks
(commercial licences), and the MATLAB MCP Core Server and the Simulink Agentic Toolkit, whose terms are checked before
the profile is built.

## Cost

To be measured with the dry run. Without the optional AWS profile the sample creates no AWS resources; the cost is the
model usage of Kiro or Kiro Crew (see [Kiro pricing](https://kiro.dev/pricing/)). The optional AWS profile adds
AgentCore Gateway and Policy charges for as long as its resources exist.

## Cleanup

`cleanup.sh` will remove the containers, the emulated board image, the twin's run files and, for the optional
AWS profile, the gateway and policy it created.
