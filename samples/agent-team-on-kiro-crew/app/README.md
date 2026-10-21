# aidlc-team: the Kiro Crew app

The app turns a one-sentence requirement into a run of an agent team defined by a team file. Every role is a
Kiro Crew chat session running as a Kiro Crew member, working in its own git worktree and branch. The app
dispatches the roles by their dependencies, merges their work, runs the checks itself, sends failures back to
the role that owns them, stops at human gates, deploys on the local machine, and draws all of it on a live
board. A finished run can be replayed and signed off.

The page has three views that share one app bar: the **CTO view** (CTO 视图, all deliveries), **delivery
detail** (交付详情, one delivery) and the **team board** (团队看板, how the team delivered it).

## How a run goes

| Step | What happens | Code |
| --- | --- | --- |
| 1 Requirement | The team is chosen by the words in the requirement: every team file with a `scope` and without `"routable": false` matches when one of its `keywords` occurs; the lowest `priority` wins; with no match the `fallback` team runs. One run at a time | `routing.route`, `service.create_run` |
| 2 Team | The team file is validated (dependency order, keys, gates, paths inside the app). The task template, the company standards that match, the roster and the knowledge source are read. An optional role whose member is missing sits the run out | `team.check_team`, `standards.py`, `team.leave_out_unhired` |
| 3 Repository | `~/workplace/aidlc-team/runs/<run>/repo` starts from the team's `starter`, its `source` or `demo/target-template`; the requirement goes into the README; the `spec_pack` is overlaid, including its `tests/enterprise/` checks | `team._setup`, `gitwork.create_repo` |
| 4 Tick | Every 2 seconds the sessions are polled and each live run advances one step | `service.pulse`, `team.TeamRun.tick` |
| 5 Start | A role starts when everything it depends on is merged and, where there is a human gate, approved. A deploy role waits for all checks to pass; a read-only reviewer waits for every writing role upstream. A writing role gets a worktree `wt/<role>` on branch `team/<run>/<role>` | `team._ready`, `team._start` |
| 6 Task | The task template filled in with the role, its branch, the paths it may write, upstream outputs, matching standards, the role's `brief`, the approved work split, and the person's notes and decisions at the gates. A fix round continues the role's own session | `team._work_task`, `team._launch` |
| 7 Merge | Uncommitted changes inside the write scope are committed for the role; changes outside it are recorded as violations; the branch is merged into the run branch, and a conflict goes back to the role. A human gate then stops the run | `team._integrate`, `gitwork.merge` |
| 8 Checks | The app runs `node --test` file by file on the run branch and assigns failures to roles by `test_owners` | `checks.run_tests`, `team._test_and_bounce` |
| 9 Review | The read-only reviewer answers `DONE: 可以交付` (deliverable) or `DONE: 要改：…` (changes needed) with the roles to send back to | `team._review_done` |
| 10 Gates | Approve: later roles start with the note and the per-question decisions, which are also written to `docs/aidlc/decisions.md` on the run branch. Discuss: the role answers in its own session and may revise its documents while the gate stays open. Send back: the role reworks with the note | `team.TeamRun.gate` |
| 11 Deploy | The deploy role writes `deploy/local.json` (port, health path); the app starts the site with `HOST=127.0.0.1`, waits for the health check, and stops a site that listens beyond loopback (checked with `lsof`) | `service._deploy`, `site.Site` |
| 12 End | `done` when every role merged, `failed` when a role failed. Only a delivered run can be signed off; signing merges the run branch into the run repository's `main` | `team._settle`, `service.signoff` |

## Code map

| Path | What it is |
| --- | --- |
| `app.json` | Kiro Crew app manifest |
| `backend/` | The orchestrator: `team/team.py` (one run's state machine and the tasks), `team/service.py` (all runs, the tick, gates, sign-off, deploy), `team/routing.py`, `team/standards.py`, `team/checks.py`, `team/gitwork.py`, `team/sessions.py`, `team/board.py`, `team/cto.py` |
| `ui/src/` | The page: `main.tsx`, `AppBar.tsx`, `board/` (team board), `cto/` (CTO view and delivery detail) |
| `ui/preview/` | A preview page on test data, without Kiro Crew |
| `team/` | Team files `team*.json`, the roster, task templates |
| `starters/` | Project templates of the example company: `mall` (store promotion), `web` (internal web pages) |
| `packs/` | Company checks in `tests/enterprise/`, reference implementations in `_reference/` for the checks' own tests, and the standards index `taoyuan/standards.json` |
| `cto/history.json` | Synthetic history for the CTO view, made by `scripts/cto_history.py` |
| `demo/target-template/` | The project the built-in team (`team/team.json`) starts from |
| `scripts/dev-install.sh` | Installs or updates the app in the local Kiro Crew |
| `tests/` | Backend tests with a fake session manager and real git and node |

## Team file keys

Team level:

| Key | Meaning |
| --- | --- |
| `roles` | The roles; a role comes after the roles it depends on |
| `scope`, `keywords`, `priority`, `fallback`, `routable` | Choosing the team by the words in the requirement |
| `starter` / `source` / `needs_source` | Start from a project template / change an existing project / a project folder must be given |
| `spec_pack` | Pack(s) overlaid on the run repository, with the company checks |
| `standards`, `standards_always` | The company standards index; the standards that always apply |
| `knowledge` `{source, data_dir}` | The Kiro Crew knowledge source name; where the data files are |
| `roster`, `workspace` | The company's team shown on the board; the Kiro Crew workspace of the members |
| `task_template` | Task template in `team/` |
| `test_command`, `test_timeout_s`, `test_owners` | Command shown on the test wall; timeout per test file; who owns failures (globs) |
| `delivery_defaults` | Default delivery labels (kind, size, business line) |
| `defaults` | `model`, `max_fix_rounds` (2), `max_review_rounds` (0), `gate_discuss` (off), `max_discuss_rounds` (5) |

Role level:

| Key | Meaning |
| --- | --- |
| `key`, `title`, `icon`, `phase`, `stage` | Name and place on the board (`phase` is the AI-DLC phase) |
| `member`, `aidlc_agent` | The Kiro Crew member the session runs as; the AI-DLC expert it stands for |
| `depends_on`, `writable`, `outputs` | Whom it waits for; paths it may write (`!` excludes); outputs handed downstream |
| `brief`, `mission`, `assignment` | The task; what the board shows it is doing |
| `gate: "human"`, `gate_label`, `plan` | A human gate after this role; its button label; the work split file |
| `questions` | File on the run branch with the questions the person decides at the gate: `{"questions": [{id, q, options: [{key, text}], recommend, why}]}` |
| `delivery` | File on the run branch with the proposed delivery labels |
| `optional` | Sits the run out when its member does not exist or the approved work split leaves it out |
| `deploy` `{mode: local, port, health}` | Deploy on this machine |
| `model` | The role's own model |

## Test

```bash
python3 -m pytest -q                 # backend tests: Python 3.10+ and pytest
(cd ui && npm ci && npm run check)   # UI: type check, component tests, build
```

Two timing-based UI tests can time out on a heavily loaded machine when test files run in parallel;
`npx vitest run --no-file-parallelism` runs them one file at a time.
