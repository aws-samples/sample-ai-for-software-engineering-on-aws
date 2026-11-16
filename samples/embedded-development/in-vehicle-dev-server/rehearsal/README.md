# One-day rehearsal of the in-vehicle scenario

> **Status: draft, not yet dry-run.** Build plan item 7 of the [scenario](../README.md#build-plan). This guide and the
> [scorecard](scorecard.md) become final after one dry run, done as described under [The dry run](#the-dry-run).

For facilitators. **Not part of the agents' workspace:** this folder holds the answers to the seeded difficulties
([facilitator-notes.md](facilitator-notes.md)). It follows the repository's [one-day guided
rehearsal](../../../../docs/guided-rehearsal.md) and adds what is particular to this scenario: a batch of static
analysis findings on `vstatd`, an emulated cockpit computer (CC-1) as the bench, and a release owner who signs off
from one evidence page.

## What the team does on the day

The team takes one batch through AI-DLC with the [Kiro Crew app](../README.md#the-kiro-crew-app): the findings
backlog of `vstatd` 2.7.0 in [knowledge/findings-backlog.md](../knowledge/findings-backlog.md), to be fixed, justified
or deferred without changing what the service does. The app gives the work to six roles. People decide at the gates
and approve every action on the bench. At the end the release owner signs off, or does not, from the evidence page of
the independent rerun.

A team that brings its own project instead of `vstatd` plugs it in through the team file
([D11](../docs/kiro-crew-app.md#d11-a-teams-own-project-plugs-in-through-the-team-file)); then the seeded
difficulties and their notes do not apply, and the scorecard is filled in the same way.

## Who

| Role | Who | What they do |
| --- | --- | --- |
| Facilitator | Someone who has run the sample before | Prepares the machines, runs the timeline, keeps the scorecard's hand-kept figures, says when to stop |
| Release owner | One engineer of the team | Answers the triage gate, approves build start, decides what the checks hand to a person, signs off or not |
| Bench owner | One engineer | Sits at the operator console (`bench/console.py`) and approves or refuses each deploy and replay |
| Engineers | The rest of the group, in pairs at one board each | Follow the agents' work on the board, review the merged change, and note every minute they spend on the batch |
| Control group (optional) | Two engineers | Work part of the same batch the usual way, without agents, for the baseline (see [The baseline](#the-baseline)) |

## Preparation, one to two weeks before

1. **Machines.** One per board: a Mac with Apple Silicon (as in the first delivery) or a Linux host, with Kiro Crew
   0.12 or later, Docker, Node.js 22, git and Python 3.11 or later, and no production credentials or customer data on
   it ([Guardrails](../README.md#guardrails)).
2. **Install and build once**, following the scenario's [Quick start](../README.md#quick-start): `bash setup.sh`, the
   build container, `bench/build-target.sh` (about 40 minutes on Apple Silicon; 68 minutes on an x86_64 host on
   2026-11-06), the baseline replay, then `bench/doctor.sh` until it passes.
3. **Check the memory limit on this host.** Replay the current release and the F-021 wrong fix 5 to 10 times each with
   [check-examples/bench.py](check-examples/README.md#after-deploy-on-the-bench), and calibrate again if either comes
   close to the limit, as [facilitator-notes.md](facilitator-notes.md) says. On an x86_64 host on 2026-11-16 the
   margins were 436 and 244 KiB, so no new calibration was needed there.
4. **Run the check examples** ([check-examples/](check-examples/README.md)): every verdict as expected, before and
   after the bench.
5. **Run the permission probe** ([agents/](../agents/README.md#the-permission-probe)) with the Kiro version of the
   day, and read what the bypass hook refuses and what gets through.
6. **Agree on the definition of done** with the release owner: by default, `release.sh` passes on the independent
   rerun and the release owner signs the evidence page. Write down anything the team adds.
7. **Decide the baseline** (next section) and print the [scorecard](scorecard.md) sheet, one per board.
8. **Credits.** The first delivery used 91.4 Kiro Crew credits for one batch ([Cost](../README.md#cost)). Plan about
   that per board, and more if the agents are often sent back.

## The baseline

The scorecard's figures mean little without something to compare them with. Use one of these, decided before the day
and written on the sheet:

- **The team's history:** engineer hours, cycle time and escapes of a comparable batch of static-analysis findings
  that the team handled the usual way, from its tracker or time records;
- **A control group on the day:** two engineers take a fixed part of the same backlog (for example F-001 to F-010)
  without agents, keep the same hand-kept figures, and stop at the same time.

The scenario's [business measures](../README.md#business-measures) state their targets as hypotheses (−50 % engineer
hours per finding, bench attendance and cycle time). The first rehearsal's figures are the baseline that corrects
them. They are not a productivity claim, and they are not compared across teams with different definitions of done.

## The day

| Time | What | Who decides |
| --- | --- | --- |
| 09:00 | The scenario in 20 minutes: the work item, the knowledge, the gates, the checks, the bench, and what the guardrails do and do not stop ([Guardrails](../README.md#guardrails)) | — |
| 09:30 | Each board: 新需求, the work item as filled in, handed to the team. The run's clock starts here | Release owner |
| | The triage role proposes fix, justify or defer for each finding, with citations; the release owner answers each question at the triage gate | Release owner |
| | The architect's plan and split; build start | Release owner |
| | Tests first, the fixes, the refactor, the review. The app runs the checks after each merge and sends failures back; BLOCKED, and a check out of its repair rounds, come to the release owner | Release owner |
| | Deploy and replay, each approved at the operator console within its timeout | Bench owner |
| | The independent rerun, `release.sh`, the evidence page | — |
| by 16:30 | Sign off, or not, and say why | Release owner |
| 16:30 | Fill in the scorecard: the app's 评分卡 plus the hand-kept figures. The facilitator goes through the seeded difficulties with [facilitator-notes.md](facilitator-notes.md) | Facilitator |
| 17:30 | Close: what the team keeps, and what it would change in the knowledge, the checks or the gates | Team |

The first delivery took 4.1 hours from start to sign-off, most of it held for a person while the app was being fixed
([Cost](../README.md#cost)); the times between 09:30 and 16:30 are not fixed in advance.

Rules for the day:

- **Nobody answers in an agent's session** once the triage is approved. A person answers at the gates on the board and
  at the operator console only; anything else an agent needs goes back through the app.
- **Every minute counts.** Each engineer notes the minutes spent on the batch, by phase (triage, gates, review,
  bench, sign-off), on the sheet. Watching without acting is not counted.
- **Stop rules.** A board that reaches 16:30 without a sign-off stops where it is, and its figures are kept as they
  are. The facilitator may stop a board that loops (the same send-back three times in a row) and notes why.
- **What the bench shows.** On one machine the operator console, the physical gate and the action record show how the
  guardrails work; they are not a boundary against the agents. Say so when you present it.

## What the team keeps

The approved triage, the merged change and its tests, the evidence page, the run's audit trail (`results/audit.md`
and `audit.json`, written at sign-off), the scorecard, and the knowledge and checks the agents worked under. A
redacted example of the audit trail and the evidence page is in [first-delivery/](first-delivery/README.md).

## The dry run

Before this guide is final, one dry run on one board, by the people who wrote the sample, as build plan item 7 says:

1. Prepare as above, on a machine with the Kiro Crew version of the day.
2. After the triage is approved, nobody answers in an agent's session; a person answers only at the operator console
   and at the board's gates.
3. After sign-off, rerun every check on the final commit in a new results directory, separately from the app's own
   independent rerun, and compare the verdicts.
4. Record the wall-clock times, the credits the run used, the engineer minutes, and the scorecard.
5. Correct this guide and the scorecard from what the dry run showed, and record the run under
   `rehearsal/dry-run/` as `first-delivery/` does (redacted copies of the audit trail and the evidence page).

Not done yet: no dry run of this guide has taken place.
