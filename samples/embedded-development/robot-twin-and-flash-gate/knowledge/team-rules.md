# TR: team rules for the RB-1 firmware

> Synthetic, written for the AI-DLC embedded sample. Cite as `[TR §<section>]`. These are the rules of the fictional
> controls team that owns the RB-1 controller firmware; the agents follow them, and the checks enforce the ones that
> can be checked.

## §1 Firmware rules

- **§1.1** C11. No compiler extensions in product code outside the hardware abstraction layer (HAL).
- **§1.2** No dynamic memory: no `malloc`, `free` or variable-length arrays.
- **§1.3** Fixed-point arithmetic as in `[RB1-NOTES p.4 §3.2]`. No `float` or `double` in code that the controller
  build links; the host build's test code may use them.
- **§1.4** The balance loop's interrupt handler does no blocking call, no serial output and no flash access.
- **§1.5** Everything that touches a register goes through the HAL, so that the same source builds for the controller
  and for the host.
- **§1.6** Limits, thresholds and gains come from one header, `src/limits.h`, each with the fact entry it implements in
  a comment.

## §2 Build

- **§2.1** Controller build: `arm-none-eabi-gcc` with `-mcpu=cortex-m3 -mthumb -Os -Wall -Wextra -Werror
  -ffunction-sections -fdata-sections`, linked with the layout of `[RB1-NOTES p.6 §5.1]`.
- **§2.2** Host build, for the unit tests and the twin: the host compiler with `-Wall -Wextra -Werror -O2`, and for the
  unit tests also `-fsanitize=address,undefined`.
- **§2.3** Both builds come from the same source commit. The evidence page records both digests.
- **§2.4** Static analysis on the controller build's `compile_commands.json`: cppcheck 2.13 with `--std=c11
  --enable=warning,style,performance,portability --inline-suppr`, and clang-tidy 18 with the checks `bugprone-*`,
  `cert-*`, `clang-analyzer-*` and `readability-magic-numbers` (limits and gains belong in `src/limits.h`, §1.6). An
  inline suppression names the reason. A team that follows MISRA C replaces these with its own tool and rule set.

## §3 Resource limits

- **§3.1** The controller build's application image fits in 184 KiB of flash and 64 KiB of RAM, stack included
  (`[RB1-NOTES p.4 §3.5]`). `checks/size.sh` enforces 90 % of each, to leave room for the next change.

## §4 Requirements and tests

- **§4.1** A behaviour change starts from a change request whose acceptance criteria each cite a fact entry.
- **§4.2** The push tests, their seeds and their pass thresholds are frozen and versioned in `tests/push-tests.yaml`
  before any code is written. Changing them is a change to the requirement, approved by a person, never part of a
  firmware change.
- **§4.3** The twin judges a design only while its error on the recorded pushes is within the verification plan.
  Its parameters come from the fact entries; they are not tuned to the recorded pushes.
- **§4.4** A unit test for each changed function of the guard and the controller, against fakes of the HAL.

## §5 Bounded repair

- **§5.1** An agent may retry a failing controller build at most 3 times, and a failing twin test at most 3 times,
  for one unit of work. Then the unit stops and a person decides.

## §6 Physical actions

- **§6.1** Flashing, a test move and a software release to the main computer are each requested through the `robot`
  server and approved by a person at the operator console, for the exact build digest. A chat reply is not an
  approval.
- **§6.2** The conditions of `[RB1-NOTES p.7 §6]` apply to every flash, move and update. An agent never sets the
  robot state inputs or the motion switch.
- **§6.3** After an interrupted write the robot is *unknown* until a person reconciles it; nothing is retried
  automatically.

## §7 Definition of done for a change

- **§7.1** All checks pass on the final commit: build (both targets), static analysis, unit tests, size, sbom,
  fidelity, twin and trace. A BLOCKED check is not a pass.
- **§7.2** The image is flashed to the emulated board through the gate, passes its self-test and is kept by the
  bootloader after its trial start (`[RB1-NOTES p.6 §5.4]`).
- **§7.3** Every result on the evidence page carries its tier (`[RB1-NOTES p.8 §7.1]`) and is never reported at a
  higher one. The release owner signs off from that page.
