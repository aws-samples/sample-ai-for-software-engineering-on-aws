# HL: hazard log for RB-1 firmware changes

> Synthetic, written for the AI-DLC embedded sample. Cite as `HL-<n>`. It follows the risk assessment that
> ISO 13482:2014 takes from ISO 12100: identify the hazards, estimate and evaluate each risk, then reduce it, and
> check that the measure works. It cites no clause of either standard and claims no conformity. Severity and
> likelihood use the team's own three-step scales below.

Severity: **S1** no harm, the robot needs a person's attention; **S2** damage to the robot or to things near it;
**S3** possible injury. Likelihood without the measure: **L1** unlikely; **L2** possible during a change like this one;
**L3** expected. A risk with S3, or with S2 and L2 or above, needs a measure that a check or a gate verifies.

| ID | Hazard and situation | S | L | Measure | Verified by |
| --- | --- | --- | --- | --- | --- |
| HL-1 | After a push the robot falls over | S2 | L2 | Requirement AC-1; the fall stop of `[RB1-NOTES p.4 §3.4]` stays unchanged | `checks/fidelity.sh`, then `checks/twin.sh`; the fall stop's unit test in `checks/unit.sh` |
| HL-2 | After a push the robot rolls off the table it stands on | S2 | L3 | Requirement AC-2, the travel limit | `checks/fidelity.sh`, then `checks/twin.sh` |
| HL-3 | Wheels spin faster or push harder than the guard allows | S2 | L2 | Requirements AC-3 and AC-4; limits only in `src/limits.h` `[TR §1.6]` | `checks/twin.sh`; `checks/unit.sh`; `checks/trace.sh` |
| HL-4 | A new image does not start or does not balance, and the robot cannot be used | S2 | L2 | Trial start and swap back to the previous image `[RB1-NOTES p.6 §5.4]`; full backup before every flash `[RB1-NOTES p.7 §6.1]` | The self-test and trial start on the emulated board; the flash gate's backup and read-back |
| HL-5 | An image nobody approved, or an older one, is written | S2 | L2 | Signed images, sequence number, manifest approved at the operator console `[TR §6.1]` | The flash gate; the bootloader's signature check |
| HL-6 | The robot moves unexpectedly after an update or a restart | S3 | L1 | Motion disabled after every restart and flash; only a person enables it `[RB1-NOTES p.7 §6.2]` | The main computer app's tests in `checks/unit.sh`; the self-test checks that motion is disabled `[RB1-NOTES p.6 §5.5]` |
| HL-7 | A flash or an update runs while the robot is moving or the battery is low | S2 | L2 | Flash preconditions `[RB1-NOTES p.7 §6.1]`; update deferral `[RB1-NOTES p.7 §6.3]` | The flash gate refuses; the update client's tests in `checks/unit.sh` |
| HL-8 | An agent loosens a threshold, a test or the twin to make a design pass | S2 | L2 | Frozen tests and versioned thresholds `[TR §4.2]`; twin parameters from the facts `[TR §4.3]`; the agents' tools cannot write them | `checks/trace.sh` (frozen sha256); the `twin` server's read-only guardrail |
| HL-9 | The controller build overruns its loop or its stack, which the twin cannot show (it runs the host build) | S2 | L2 | Size limits `[TR §3.1]`; the self-test checks the loop period `[RB1-NOTES p.6 §5.5]` | `checks/size.sh`; the self-test on the emulated board |

A change that touches a measure in this table, or adds a hazard, updates the table in the same change request.
