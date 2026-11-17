# Rehearsal scorecard

> **Status: draft, not yet dry-run** (build plan item 7). Fill in one sheet per board. Copy
> [scorecard-template.csv](scorecard-template.csv) for the hand-kept figures.

This is the scorecard of the scenario page ([How the sample is measured](../README.md#how-the-sample-is-measured)).
Each figure comes from one of three sources, and keeps the definition its source uses:

- **App:** the Kiro Crew app's 评分卡 (scorecard) view. It is filled in from the run's records, with the definitions of
  [D8](../docs/kiro-crew-app.md#d8-a-scorecard-view-with-measured-figures-only-in-place-of-the-cto-view), and the
  source is `app/backend/team/scorecard.py`. A figure with no run behind it stays empty, never 0.
- **Hand:** kept by the facilitator and the engineers on the day, on the sheet.
- **Servers:** the audit log of the `build` and `bench` MCP servers. The app uses them in `servers` mode only
  ([D17](../docs/kiro-crew-app.md#d17-app-通过-build--bench-服务器跑检查和台架)); in `direct` mode these figures stay
  empty and the sheet says so.

| Scorecard item | Source | How it is taken |
| --- | --- | --- |
| Engineer hours on the batch, by phase and per finding | Hand | Each engineer's minutes on the batch, by phase (triage, fix, verification, sign-off; [README.md](README.md#the-day) says what each phase covers), summed over the board. Per finding: the triage, fix and verification minutes over the findings the approved triage decided, as the business measure counts them |
| Engineer time at the operator console and the bench | Hand | The bench owner's minutes at the console, and anyone's minutes spent on the bench itself (doctor, start, reset) |
| Findings fixed, justified and deferred | App | The decisions of the approved triage. The entries it added under TR §4.4 (the refactor, findings found on the way) are counted separately, by hand |
| Justifications overturned | App | A justification the release owner answered other than A at the triage gate, or that a reviewer's 要改 verdict names on a `推翻说明：` line while the approved triage justifies it |
| Changes that passed every pre-bench check on the first round | Hand, from the app's rounds | Whether the first round of checks after the merge passed every check (one board, one batch: yes or no), and which checks failed |
| Time to an approved triage, to the first passing check run, and to sign-off | App | Wall clock from the run's start to each. Per run only: separate runs' times are not added up |
| Build repair rounds | App | The fix rounds the app gave for a failing `build` check |
| Check failures caught before the bench, by check | App | Per check, the rounds before the bench whose result was FAIL |
| Log differences, and how many were real behaviour changes | App, then Hand | `logdiff`'s differences over the runs on the bench, and how many no approved difference explained (App). Whether each was a real change of behaviour is a person's judgement, written on the sheet with the finding it came from (Hand) |
| Bench actions approved, refused and reconciled | App | The console's decisions on the run's requests (a timeout counts as a refusal), and the reconciles after the run's own latest request |
| Tool calls by permission class, and how many were refused | Servers | The app's calls, in `servers` mode (below) |
| Checks whose result changed on the independent rerun | App | The checks whose verdict on the final commit differed in the app's independent rerun |
| In the model-based profile, back-to-back differences and real defects | — | Not applicable until build plan item 9; leave empty |
| Defects found later that a check should have caught | Hand, later | Kept open after the day: defects in the batch's change found after sign-off, with the check that should have caught them |

Tool calls by permission class, in `servers` mode: the app's calls in the two servers' audit logs, as the app's
评分卡 shows them. Each outcome line is one call, counted by its class, with those the servers refused. The figure
stays empty in `direct` mode. Do not fill it from the agents' sessions: they do not use the servers.

Also write on the sheet:
- the credits the run used, from Kiro Crew;
- the Kiro Crew and kiro-cli versions;
- the host;
- whether the bypass hook was in the templates;
- what the board is compared with: the team's history, or the control group's figures for the same part of the
  backlog;
- every stop, and why;
- in the dry run, the checks whose verdict differed on the second rerun by hand.

A control group fills in a sheet of its own, with the hand-kept figures for its part of the backlog.

## What the figures are not

The first rehearsal's figures are the team's baseline, not a result. The business measures' targets (−50 % engineer
hours per finding, bench attendance and cycle time) are hypotheses until the first rehearsal has produced figures with
a comparison behind them ([Business measures](../README.md#business-measures)). Report quality figures (justifications
overturned, real behaviour changes, defects found later) together with the time figures.
