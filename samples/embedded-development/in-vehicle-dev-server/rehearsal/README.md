# One-day rehearsal of the in-vehicle scenario

> **Status: draft.** Build plan item 7 of the [scenario](../README.md#build-plan). This guide and the
> [scorecard](scorecard.md) have not been dry-run with people. A team's first rehearsal is their dry run: correct both
> from it, as described under [The dry run](#the-dry-run).

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

A *board* is one machine, one Kiro Crew board (团队看板) and one run of the batch. Plan a board for every three to four
engineers.

| Role | Who | What they do |
| --- | --- | --- |
| Facilitator | Someone who has run the sample before, one for the room | Prepares the machines, runs the timeline, collects the sheets, says when a board stops |
| Release owner | One engineer per board | Answers the triage gate, approves build start, decides what the checks hand to a person, signs off or not |
| Bench owner | One engineer per board | Sits at that board's operator console (`bench/console.py`) and approves or refuses each deploy and replay |
| Engineers | The others at the board | Follow the agents' work, review the merged change, and record every minute they spend on the batch |
| Control group (optional) | Two engineers | Work part of the same batch the usual way, without agents, for the comparison (see [What the figures are compared with](#what-the-figures-are-compared-with)) |

## Preparation, one to two weeks before

1. **Machines.** One per board: a Mac with Apple Silicon (the app has run to sign-off there, on Kiro Crew 0.12.0-rc.4)
   or a Linux host (run on Ubuntu 24.04 x86_64 with Kiro Crew 0.12.2 to the checks before the bench only; the app's
   manifest asks for 0.8.0 or newer), Docker, Node.js 22, git and Python 3.11 or later (the MCP servers need 3.11), and
   no production credentials or customer data on it
   ([Prerequisites](../README.md#prerequisites), [Guardrails](../README.md#guardrails)).
2. **Install and build once**, following the scenario's [Quick start](../README.md#quick-start): `bash setup.sh`, the
   build container, `bench/build-target.sh` (about 40 minutes on Apple Silicon,
   [bench/README.md](../bench/README.md#quick-start); 68 minutes on an x86_64 bench host,
   [mcp/bench/README.md](../mcp/bench/README.md)), the bench's baseline replay, then `bench/doctor.sh` until it
   passes.
3. **Check the memory limit on this host.** Replay the current release and the F-021 wrong fix 5 to 10 times each with
   [check-examples/bench.py](check-examples/README.md#after-deploy-on-the-bench). Calibrate the limit again from
   replays on that host if the release comes within about 300 KiB of it, or the wrong fix within about 200 KiB of it
   or under it, and never use a limit the wrong fix passes ([facilitator-notes.md](facilitator-notes.md)). On an
   x86_64 host on 2026-11-16 the margins were 436 and 244 KiB
   ([check-examples/](check-examples/README.md#last-run-on-the-bench)).
4. **Run the check examples** ([check-examples/](check-examples/README.md)): every verdict as expected, before and
   after the bench.
5. **Run the permission probe** ([agents/README.md](../agents/README.md#the-permission-probe)) with the Kiro version
   of the day, and read what the bypass hook refuses and what gets through. The probe shows which of the paths that
   [Guardrails](../README.md#guardrails) lists the hook closes. The rest stay open, and the boundary is still a build
   server without Docker access, as Guardrails says.
6. **Agree on the definition of done** with the release owner: by default, `release.sh` passes on the independent
   rerun and the release owner signs the evidence page. Write down anything the team adds.
7. **Decide what the figures are compared with** (next section) and print the [scorecard](scorecard.md) sheet, one
   per board.
8. **Credits.** The first delivery used 91.4 Kiro Crew credits for one batch ([Cost](../README.md#cost)). Plan about
   that per board, and more if the agents are often sent back.

## What the figures are compared with

The scorecard's figures mean little without a comparison. Use one of these, decided before the day
and written on the sheet:

- **The team's history:** engineer hours, cycle time and escapes of a comparable batch of static-analysis findings
  that the team handled the usual way, from its tracker or time records;
- **A control group on the day:** two engineers take a fixed part of the same backlog (for example F-001 to F-010)
  without agents, keep the same hand-kept figures, and stop at the same time.

The scenario's [business measures](../README.md#business-measures) state their targets as hypotheses (−50 % engineer
hours per finding, bench attendance and cycle time). The first rehearsal's figures, set against the comparison, are the
team's baseline: the team's leadership signs it off, and it corrects the targets. The baseline is not a productivity
claim, and it is not compared across teams with different definitions of done.

## The day

| Time | What | Who decides |
| --- | --- | --- |
| 09:00 | The scenario in 20 minutes: the work item, the knowledge, the gates, the checks, the bench, and what the guardrails do and do not stop ([Guardrails](../README.md#guardrails)) | — |
| 09:30 | Each board: 新需求, the work item as filled in, handed to the team. The run's clock starts here | Release owner |
| | The triage role proposes fix, justify or defer for each finding, with citations; the release owner answers each question at the triage gate | Release owner |
| | The architect's plan and split; build start | Release owner |
| | Tests first, the fixes, the refactor, the review. The app runs the checks after each merge and sends failures back; BLOCKED, and a check out of its repair rounds, come to the release owner | Release owner |
| | Deploy and replay, each approved at the board's operator console within its timeout | Bench owner |
| | The independent rerun, `release.sh`, the evidence page | — |
| by 16:30 | Sign off, or not, and say why | Release owner |
| 16:30 | Fill in the scorecard: the app's 评分卡 plus the hand-kept figures. The facilitator goes through the seeded difficulties with [facilitator-notes.md](facilitator-notes.md) | Facilitator |
| 17:30 | Close: what the team keeps, and what it would change in the knowledge, the checks or the gates | Team |

The first delivery took 4.1 hours from start to sign-off, most of it held for a person while the app was being fixed
([Cost](../README.md#cost)); the times between 09:30 and 16:30 are not fixed in advance.

Rules for the day:

- **Nobody answers in an agent's session** once the triage is approved. A person answers only at the board's gates
  (build start, what the checks hand to a person, sign-off) and at the operator console; anything else an agent
  needs goes back through the app.
- **Bench approvals at the console.** Approve deploys and replays at `bench/console.py`, not on the board, as
  [Guardrails](../README.md#guardrails) asks for a run on one machine.
- **Record every minute.** Each engineer writes the minutes spent on the batch on the sheet, by phase: triage, fix
  (gates, send-backs and decisions while the roles work), verification (review, bench, rerun) and sign-off. Watching
  without acting is not counted.
- **Stop rules.** A board that reaches 16:30 without a sign-off stops where it is, and its figures are kept as they
  are. The facilitator may stop a board that loops (the same send-back three times in a row) and notes why.
- **What the bench shows.** On one machine the operator console, the physical gate and the action record show how the
  guardrails work; they are not a boundary against the agents. Say so when you present it.

## What the team keeps

The approved triage, the merged change and its tests, the evidence page, the run's audit trail (`results/audit.md`
and `audit.json`, written at sign-off), the scorecard, and the knowledge and checks the agents worked under. A
redacted example of the audit trail and the evidence page is in [first-delivery/](first-delivery/README.md).

## The dry run

Neither this guide nor the scorecard has been dry-run yet. Until they are, a team's first rehearsal serves as the dry
run: run it on one board as below, then correct both from it.

1. Prepare as above, on a machine with the Kiro Crew version of the day.
2. After the triage is approved, nobody answers in an agent's session; a person answers only at the operator console
   and at the board's gates.
3. After sign-off, run every check on the final commit once more, by hand, in the build container and a new results
   directory, with the commands of [checks/README.md](../checks/README.md), the run's approved `triage.json` and the
   run directory of the last replay on the bench. Compare the verdicts with the app's independent rerun. The app's
   rerun ([D9](../docs/kiro-crew-app.md#d9-the-app-reruns-every-check-independently-before-sign-off)) is the one
   build plan item 7 asks for; this second one shows that it did not depend on the app's own state. Write the checks
   whose verdict differed on the sheet.
4. Record the wall-clock times, the credits the run used, the engineer minutes, and the scorecard.
5. Correct this guide and the scorecard from what the dry run showed, and record the run under
   `rehearsal/dry-run/` as `first-delivery/` does (redacted copies of the audit trail and the evidence page).
