# vstatd-team: the Kiro Crew app

The app takes the scenario's work item through an agent team defined by a team file
([team/team-vstatd.json](team/team-vstatd.json)). Every role is a Kiro Crew chat session running a Kiro agent
template, working in its own git worktree and branch. The app dispatches the roles by their dependencies, merges their
work, runs the scenario's checks itself, sends failures back to the role that owns the file, stops at human gates, runs
the bench actions through `bench/cc1.sh` (each one approved at the operator console), reruns every check before
sign-off, and draws all of it on a live board. A finished run can be replayed and signed off.

It is a copy of the [agent-team sample's app](../../../agent-team-on-kiro-crew/app/), changed here (D5 in
[docs/kiro-crew-app.md](../docs/kiro-crew-app.md)). The page has two views that share one app bar: the **team board**
(团队看板, one run) and the **scorecard** (评分卡, the measured figures of every run). Installing it, and what it does
not enforce: [the scenario README](../README.md#the-kiro-crew-app).

## How a run goes

| Step | What happens | Code |
| --- | --- | --- |
| 1 Requirement | One run at a time. The team file is read and validated, and `${sample}` in it becomes the scenario's folder: `sample.json` in the app's data directory (written by `setup.sh`), else `$VSTATD_SAMPLE`, else the app's parent folder in a checkout (D12) | `service.create_run`, `team.check_team`, `paths.py` |
| 2 Repository | `~/workplace/vstatd-team/runs/<run>/repo` starts from the team's `source` (`reference-project/`); the requirement goes into its README | `team._setup`, `gitwork.create_repo` |
| 3 Tick | Every 2 seconds the sessions are polled and each live run advances one step; checks, the tests on the base commit and bench actions run in the background so that a tick never waits for them | `service.pulse`, `team.TeamRun.tick` |
| 4 Start | A role starts when everything it depends on is merged and its human gate, if any, approved. A writing role gets a worktree `wt/<role>` on branch `team/<run>/<role>`; the developers' write scopes come from the architect's work split | `team._ready`, `team._start`, `team._resolve_ownership` |
| 5 Task | The task template ([team/task_template-vstatd.md](team/task_template-vstatd.md)) filled in with the role, its branch, its write scope, the upstream outputs, its `brief`, the build container's command line and the person's decisions at the gates. A fix round continues the role's own session | `team._work_task`, `team._fix_task` |
| 6 Triage gate | The app checks `triage.json` by the rules of `checks/lib/common.py` (mirrored) and sends a malformed one back; the gate asks a question for each justification (with its citations), deferral, added entry and disagreement with the backlog (D4). All answered A: the triage is written beside the repository with `approved` and its `.sha256` record; any other answer sends it back to the triage role | `triage.py`, `team._approve_triage` |
| 7 Build start | Once approved, the triage's `base` becomes the run branch's head; from then on every commit must cite a finding, and a role whose commits would fail `trace.sh` is sent back before its merge (D13) | `team._set_base`, `team._trace_back` |
| 8 Tests first | Once the tester is merged, its new tests are built with the base commit's code in the build container; each must fail there, or the tests go back to the tester (D6) | `checks.tests_first`, `team._tests_first` |
| 9 Checks | When every developer is merged, the checks with `when: before_bench` run in the build container, each round in `runs/<run>/results/<n>/`. A failure goes to the role whose write scope covers a file its reasons name, else to the check's `owner`; BLOCKED, a usage error, or a check out of its `max_rounds` holds the run for a person (D7) | `checks.run_checks`, `team._check_bounce` |
| 10 Review | The read-only reviewer answers `DONE: 可以交付` or `DONE: 要改：…` with the roles to send back to | `team._review_done` |
| 11 Bench | `doctor.sh`, then deploy of `build.sh`'s artifact and replay into `runs/<run>/bench/run-<n>/`, each waiting at the operator console, then the checks with `when: after_bench`. Doctor failing, the target off or unknown, a missing baseline, a refusal or a timeout at the console hold the run with the reason and the command; 重试 carries on from that step (D3, D10) | `bench.py`, `team._bench_step` |
| 12 Rerun | Every check again on the final commit in `runs/<run>/results/rerun/`, `repair-rounds.json`, `release.sh` and `evidence-page.sh`; the checks whose verdict differs from the run's last are recorded (D9) | `team._rerun` |
| 13 Sign-off | Possible only when `release.sh` passed on the rerun; signing merges the run branch into the run repository's `main` | `team.sign_block`, `service.signoff` |

The scorecard (`GET /scorecard`) is computed from each run's `run.json`, `events.jsonl`, approved triage, results
directories and the bench's `actions.jsonl`; [backend/team/scorecard.py](backend/team/scorecard.py) says how each figure
is taken (D8).

With no run yet, the board shows the work item, the flow from triage to sign-off with who acts at each step, and a
checklist from `GET /readiness`: the knowledge source, the build container image, `bench/doctor.sh`, the target, the
baseline and the operator console (which the app cannot see), each with the command for it when it is not ready. The
image and doctor.sh are probed in the background and cached (doctor.sh runs once by itself and again on
`POST /readiness/doctor`); the bench state is only read. During a run, a strip above the team graph shows the same
steps and what comes next (`ui/src/board/flow.ts`).

## Code map

| Path | What it is |
| --- | --- |
| `app.json` | Kiro Crew app manifest |
| `backend/` | `routes.py` and `hooks.py` (the host's entry points); `team/team.py` (one run's state machine and the tasks), `team/service.py` (all runs, the tick, gates, sign-off), `team/checks.py` (the check adapter and tests first), `team/triage.py`, `team/bench.py`, `team/paths.py`, `team/scorecard.py`, `team/board.py` (`GET /board`), `team/readiness.py` (`GET /readiness`), `team/gitwork.py`, `team/sessions.py`, `team/handlers.py` |
| `ui/src/` | The page: `main.tsx`, `AppBar.tsx`, `nav.ts`, `board/` (team board: flow strip and readiness, graph, lanes, check wall, bench panel, gates, sign-off, replay), `scorecard/`, `types.ts` (the contract with the backend) |
| `ui/preview/` | A preview page on test data, without Kiro Crew (`npm run preview:build`; `?fixture=vstatd` (the default), `vstatd-triage`, `vstatd-release`, `empty`, `?view=score`) |
| `team/` | `team-vstatd.json` and its task template |
| `scripts/dev-install.sh` | Builds the board and installs or updates the app in the local Kiro Crew; `scripts/kcapi.sh` calls Kiro Crew's local API as the dashboard owner |
| `tests/` | Backend tests with a fake session manager, real git, and stand-in checks and bench; `tests/fixtures/` has a small web team that the orchestrator's own tests run |

## Team file keys

Team level:

| Key | Meaning |
| --- | --- |
| `roles` | The roles; a role comes after the roles it depends on |
| `source` / `needs_source` | The project the team changes (`${sample}/reference-project`) / a project folder must be given |
| `knowledge` `{source, data_dir}` | The Kiro Crew knowledge source name (`vstatd`); where its files are on disk |
| `workspace` | The Kiro Crew workspace of the members; a role whose member is not there is held (the vstatd team has none) |
| `task_template` | Task template in `team/` |
| `ownership` `{file, from}` | The work split file and the role that writes it; roles with `writable_from` get their write scope from it |
| `check_runner` `{docker, image}` | The build container the checks run in: the `docker run` command line and the image |
| `checks` | Each `{name, command, args, when, owner, max_rounds, timeout_s}`. `args` of `project`, `triage`, `run`, `baseline` (besides `--results`); `when` is `before_bench`, `after_bench` or `release`; `owner` gets a failure that names no file (none for a release check); `max_rounds` defaults to 2. A check keeps the protocol of [checks/README.md](../checks/README.md): exit 0 PASS, 1 FAIL, 2 usage error, 3 BLOCKED, and `<results>/<name>.json` |
| `evidence_page` | The command that writes `evidence.md` into the rerun's results |
| `bench` | `deploy`, `replay` (and `restart`) with `{artifact}` and `{run}`, run by the app; `doctor`, run by the app; `build` and `start`, the bench owner's commands shown on the board; `baseline`, the baseline directory |
| `test_owners`, `test_command` | For a team without `checks`: who owns failing tests (globs), and the command the test wall shows |
| `delivery_defaults` | Default delivery labels |
| `defaults` | `model`, `max_fix_rounds` (2), `max_review_rounds` (0), `gate_discuss` (off), `max_discuss_rounds` (5) |

Role level:

| Key | Meaning |
| --- | --- |
| `key`, `title`, `icon`, `phase`, `stage`, `mission` | Name and place on the board (`phase` is the AI-DLC phase) |
| `member` or `template`, `aidlc_agent` | The Kiro Crew member the session runs as, or the Kiro agent template it runs without a member (the vstatd team); the AI-DLC expert it stands for |
| `depends_on`, `writable`, `writable_from`, `outputs` | Whom it waits for; paths it may write (`!` excludes), or `ownership` for the work split's; outputs handed downstream |
| `brief` | The task |
| `gate: "human"`, `gate_label` | A human gate after this role and its label |
| `triage` `{file, knowledge}` | The role writes the triage: checked by the checks' rules, its gate asks D4's questions |
| `plan`, `questions`, `delivery` | Files on the run branch: the proposed assignments, the questions for the person at the gate, the proposed delivery labels |
| `gate_preset`, `gate_revise_preset`, `gate_revise_risk` | Notes the gate dialog can fill in |
| `optional` | Sits the run out when its member does not exist or the approved plan leaves it out |
| `model` | The role's own model |

## Test

```bash
python3 -m pytest -q                 # backend tests: Python 3.10+ and pytest; git; checks/ and knowledge/ of the scenario
(cd ui && npm ci && npm run check)   # UI: type check, component tests, build
(cd ui && npm run preview:build)     # the preview page, into ui/preview-dist/
```

Two timing-based UI tests can time out on a heavily loaded machine when test files run in parallel;
`npx vitest run --no-file-parallelism` runs them one file at a time. The tests of `setup.sh` and `cleanup.sh` are in
the scenario's `scripts/tests/` (`python3 -m pytest -q scripts/tests` in the scenario's folder).
