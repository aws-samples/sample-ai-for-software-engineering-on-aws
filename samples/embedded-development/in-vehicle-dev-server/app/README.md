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

`GET /runs/{rid}/flow` is the run's 交付详情 (`?view=item&run=<id>`, from the board's run header and the scorecard's rows): measured segments on one timeline (each role's attempts, the human gates, the waits at the operator console from the bench's action record, each check round from its checks' own wall times, the independent rerun), the moments (send-backs, failing rounds, approvals, sign-off) and the totals; a segment opens the board's replay at its start. [backend/team/flow.py](backend/team/flow.py) says where each one comes from.

`GET /runs/{rid}/audit` is the run's 审计记录 (D14): one chronological list of who (人 / AI / app / 台架) did what at which step, with its evidence, from the run's events and the bench's action records for the run's requests; `?format=md` or `?format=json` downloads it, and sign-off writes `results/audit.md` and `results/audit.json` beside the repository and names their sha256 on the sign-off record. `GET /audit/bench` lists the bench's requests no run made (newest 50) for the home page. [backend/team/audit.py](backend/team/audit.py).

The scorecard (`GET /scorecard`) is computed from each run's `run.json`, `events.jsonl`, approved triage, results
directories and the bench's `actions.jsonl`; [backend/team/scorecard.py](backend/team/scorecard.py) says how each figure
is taken (D8).

With no run yet, the board shows the work item, the flow from triage to sign-off as a 人机分工 grid (steps × 人 / AI / app / 台架, what each is to do; `ui/src/board/division.ts`), and a
checklist from `GET /readiness`: the knowledge source, the build container image, `bench/doctor.sh`, the target, the
baseline and the operator console (which the app cannot see), each with the command for it when it is not ready. The
image and doctor.sh are probed in the background and cached (doctor.sh runs once by itself and again on
`POST /readiness/doctor`); the bench state is only read. Above it, the requests waiting at the operator console now
(from a run or from setting up the baseline), each with 批准 (after typing the first six characters of its digest) and
拒绝 (with a reason): `POST /bench/decide` runs the bench's own `benchstate.decide()` (D3). During a run, a strip above the team graph shows the same
steps and what comes next (`ui/src/board/flow.ts`), and the 人机分工 grid under it what each actor did at each step, counted from the run's 审计记录; a cell opens those entries in the 审计记录 panel. The strip and the grid sit at the top of the run, under the counters; each event in the feed carries the actor chip its 审计记录 entry has, and the app bar shows 下一步需要你 N while gates or bench requests of the run wait for the person.

`POST /runs/{rid}/finding` is 补登发现 (D15): on a run held for a person after the checks, a person registers what a check found under TR §4.4 with the next free ID (body: `check, tool, location, decision, evidence, behaviour, facts, cites, reason, pick_up_when, role, paths, note, by, continue`); the app appends it to the approved triage (`triage.problems()` must pass, else 400 with `problems`), rewrites `triage.json` and its `.sha256`, adds `paths` to the role's write scope, and with `continue` (the default) ends the hold and sends the role a fix round; 409 when the run is not held. It answers `{id, triage_sha256, held, status}`. [backend/team/team.py](backend/team/team.py) `register_finding`. With `extend` (an ID a check added already; body: `extend, role, paths, note, by, continue`) it adds no finding and leaves the triage as it is: the role gets the paths and that check one more round. On a held run the board's `tests.held.suggest` proposes such paths (from what the role said it cannot change, and the test file a unit-test finding still needs, TR §4.1), for a person to agree to; `team.path_suggestions`.

`POST /runs/{rid}/retry` takes `note` and `by` (who decides, named in the audit). On a run that ended on a 要改 review after its rounds (the board's `review_redo`), it sends that review back once more with the person's decision (按评审意见再改一轮); on a held bench step it carries on from that step.

`GET /knowledge` lists the knowledge documents the team uses (title, citation key, figures counted from the files on each request) with Kiro Crew's source state, and `GET /knowledge/file?path=` returns one of them as text for a read-only viewer (listed files inside `knowledge/` only, no PDF, up to 1 MB); the board's knowledge panel counts each document's citations in the roles' replies.

`GET /team` returns the default team for the start form's 组队预览: the roles in flow order (AI-DLC expert, template, write scope, gate, phase), the checks with `when`, `owner` and `max_rounds`, the knowledge source's state, and whether each template's `~/.kiro/agents/<template>.json` exists (only stat-ed).

`GET /backlog` returns the default team's work item (`work_item` in the team file, the start form's default) and the findings backlog rows; the home page shows them as 需求清单 with a label filter, and the board's 需求清单 shows the backlog until the triage exists, then each finding's decision, citations, evidence, behaviour, the answer at the triage gate and what the latest round's `static` and `trace` results recorded (— where there is no record).

## Code map

| Path | What it is |
| --- | --- |
| `app.json` | Kiro Crew app manifest |
| `backend/` | `routes.py` and `hooks.py` (the host's entry points); `team/team.py` (one run's state machine and the tasks), `team/service.py` (all runs, the tick, gates, sign-off), `team/checks.py` (the check adapter and tests first), `team/triage.py`, `team/bench.py`, `team/paths.py`, `team/scorecard.py`, `team/board.py` (`GET /board`), `team/readiness.py` (`GET /readiness`), `team/library.py` (`GET /knowledge`), `team/roster.py` (`GET /team`), `team/flow.py` (`GET /runs/{rid}/flow`), `team/audit.py` (`GET /runs/{rid}/audit`, `GET /audit/bench`), `team/gitwork.py`, `team/sessions.py`, `team/handlers.py` |
| `ui/src/` | The page: `main.tsx`, `AppBar.tsx`, `nav.ts`, `board/` (team board: flow strip and readiness, audit trail (`Audit.tsx`), 人机分工 (`DivisionGrid.tsx`, `division.ts`), graph, lanes, check wall, bench panel, gates, sign-off, replay), `scorecard/`, `item/` (交付详情), `types.ts` (the contract with the backend) |
| `ui/preview/` | A preview page on test data, without Kiro Crew (`npm run preview:build`; `?fixture=vstatd` (the default), `vstatd-triage`, `vstatd-release`, `empty`, `?view=score`, `?view=item&run=<id>`) |
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

The tests of `setup.sh` and `cleanup.sh` are in
the scenario's `scripts/tests/` (`python3 -m pytest -q scripts/tests` in the scenario's folder).
