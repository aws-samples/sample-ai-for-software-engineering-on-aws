# REQ-RB1-007: a recovery limit in the actuator guard

> Synthetic, written for the AI-DLC embedded sample. Cite as `REQ-RB1-007 AC-<n>`. Status: approved for work. The
> rated push impulse and the travel limit are frozen, with the push tests, before any code is written ([TR §4.2]).

## Why

After a push, RB-1's balance controller recovers by driving under the body. On a table that can take the robot off the
edge: with the current firmware it travels further than the space it is shown in allows (hazard HL-2 of the hazard log).
The team wants the travel after a push bounded, without making the robot fall more often.

## What

Add a recovery limit to the actuator guard: after a push, the robot shall return to stable without travelling more
than the travel limit, while keeping the existing guard limits and not falling for pushes up to the rated impulse.

## Acceptance criteria

| ID | Criterion | Cites |
| --- | --- | --- |
| AC-1 | For every push test up to the rated push impulse (*to be set*), the robot does not fall | `PUSH-RATED`, `FALL-DEF` |
| AC-2 | For every such push, the travel from the push to stable stays within 0.15 m (*to be confirmed*) | `TRAVEL-LIMIT` |
| AC-3 | The wheel speed the guard commands never exceeds 0.80 m/s | `GUARD-SPEED` |
| AC-4 | The torque the guard commands per wheel never exceeds 0.315 N·m | `GUARD-TORQUE` |
| AC-5 | The robot is stable within 2.0 s of the end of the push: tilt within 3° of the calibrated balance angle and wheel speed below 0.05 m/s, held for 0.5 s | `STABLE-DEF`, `CAL-DATA` |
| AC-6 | The fall stop of `[RB1-NOTES p.4 §3.4]` is unchanged | `FALL-STOP` |
| AC-7 | The application image still fits the limits of `[TR §3.1]` | `MEM-LIMITS` |

## What "fall" means here

For this requirement a fall is a tilt beyond 45° held for 0.3 s (`FALL-DEF`). This is stricter than the firmware's
fall stop (60° for 0.3 s, `FALL-STOP`), which this change does not alter. Every test and the twin judge falls by this
definition.

## Out of scope

Pushes from the side, driving commands during a push, and the main computer's software.
