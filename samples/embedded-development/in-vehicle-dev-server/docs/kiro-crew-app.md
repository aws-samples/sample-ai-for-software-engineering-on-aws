# Design notes: the in-vehicle scenario as a Kiro Crew app

Working notes for turning this scenario into a Kiro Crew app modelled on the
[agent-team sample](../../../agent-team-on-kiro-crew/). Decisions are recorded as they are made; open questions are
listed at the end.

## Decisions

### D1. Scope: run vstatd first, keep the seams for a team's own project

The first version runs this scenario end to end on `vstatd`. The team file and the check adapter are written so that
a team can later point them at its own project, toolchain and checks, the way the agent-team app is a general
orchestrator with an example team.

### D2. Kiro Crew runs on the user's own machine; agents have a shell, sessions auto-approve

As in the agent-team sample: the app is installed into the Kiro Crew the user already runs, and the members'
templates allow file reads and writes and shell commands. The human gates are the orchestrator's: a role after a gate
gets no session until a person approves, and the app itself, not an agent, deploys and acts on the bench after the
gate.

What this does not enforce, and the README must say so:

- An agent's shell can reach the emulated target without the app: `docker exec` into the bench runner, whose volume
  `cc1-bench-secrets` holds the target's SSH key.
- An agent can write the bench state in `~/.cc1-bench`, including approval decisions.

So in this app the physical gate, the operator console and the action record show how the guardrails work; they are
not a boundary against the agents. The claim "only `bench` can reach the target" holds only in a set-up where the
agents' shell has no Docker access and no write access to the bench state, such as the containerised build server
below. The target is emulated, so a bypass damages no hardware.

Alternatives considered:

- No shell for the agents; the app builds, checks and deploys. Rejected for the first version: every fix round waits
  for the app's checks.
- Kiro Crew in a build-server container (official image, no Docker socket, no target key). Measured on 2026-11-02:
  the official image installs and enables the agent-team app; the inner sandbox works with the official seccomp
  profile; ThreadSanitizer's `setarch -R` needs one extra rule, `personality(0x40000)`. Rejected as the default: users
  would run a second Kiro Crew with its own sign-in, knowledge and memory. Kept as an option for a team's own build
  server.

Facts found on the way (2026-11-02, kiro-cli 2.37.1, Kiro Crew 0.12.0-rc.3 on macOS):

- Write-scope rules in an agent's own configuration did not stop writes outside the allowed paths, with or without
  `--trust-all-tools`: neither `permissions.rules` with `deny`, nor `toolsSettings.fs_write.deniedPaths`, nor leaving
  `fs_write` out of `allowedTools`. The user-level `~/.kiro/settings/permissions.yaml` on that machine allowed all
  capabilities; its own `deny` rules did apply. Not re-tested on a clean machine. See also
  [kirodotdev/Kiro#7799](https://github.com/kirodotdev/Kiro/issues/7799).
- Kiro Crew's macOS sandbox (Seatbelt, `standard` level) hides `~/.docker` but does not stop connections to the
  Docker socket, and does not hide `~/.cc1-bench`.

### D3. Bench actions are approved at the operator console only

The app calls `bench/cc1.sh` for deploy, restart and replay; each call waits until a person approves that action and
build digest at `bench/console.py`, as the bench already does. The board adds no gate of its own for bench actions:
it shows the pending request and its digest, read from the bench state, and the action record. The bench owner
approves at the console; the release owner signs off on the board.

Alternatives considered: a board gate in front of the console (two approvals for one action), and the board writing
approvals in place of the console (a change to the bench design of build plan item 3, and the console unused).

### D4. The triage gate asks only about the findings that need judgement

At the triage gate, a question is put to the person for each finding that the triage role proposes to justify or
defer, and for each finding where its proposal differs from the decision marked in the backlog. A question about a
justification carries the specification page it cites. The other findings are listed in the gate's document and
approved with it.

Why: a justification is where an agent can leave a real defect in place or "fix" correct code, and the scorecard
counts the justifications a reviewer overturned. Thirty questions would be approved without being read.

Alternatives considered: a question for every finding in the backlog; no questions, the triage file approved as a
whole.

How an answer is applied (step 5): each question's option A takes the proposal as it is. When every answer is A, the
app writes the triage with `approved: {by, at}` and its record `triage.json.sha256` beside the run's repository. An
answer that changes a decision (another option, or the person's own words) sends the triage back to the triage role
with the person's decisions, and the gate comes again: a fix needs its evidence and behaviour, and a deferral its
condition, which only the role that read the code can give. Before the gate, the app checks `triage.json` by the rules
of `checks/lib/common.py` (mirrored, not imported) and sends a malformed one back. Since every finding labelled
`later` is refused by those rules, "a proposal that differs from the backlog" is in practice a justification or a
deferral of a finding labelled `fix`; its question says so.

### D5. The app is a copy of the agent-team app, kept in this scenario's folder

The app lives in `app/` of this scenario, with its own name, setup and cleanup, and is changed there. The agent-team
sample stays as it is. Fixes made in one copy are carried to the other by hand. Which parts are general is decided
once this app runs end to end; a shared package for both samples can follow then.

Alternatives considered: extending the agent-team app with an embedded team and pluggable checks and deployment (one
code base, but every change here would have to keep an available sample green); a shared orchestration package first
(a refactor of the agent-team sample before anything runs here).

### D6. Six roles, tests first

| Role | Expert | Gate after it | Writes |
| --- | --- | --- | --- |
| Triage | `aidlc-developer-agent` | Triage (D4) | `triage.json` and the gate's questions |
| Architect | `aidlc-architect-agent` | Build start | The refactor plan of `Service::run()` and the work split by source file |
| Tester | `aidlc-quality-agent` | — | A failing test for each fix that needs one, before the developers start |
| Developer: fixes | `aidlc-developer-agent` | — | The fixes, in the files the split gives it |
| Developer: refactor | `aidlc-developer-agent` | — | The refactor, in the files the split gives it |
| Reviewer | `aidlc-architecture-reviewer-agent` | — | Nothing (read-only); looks hardest at justifications and at behaviour kept by the refactor |

No role deploys: the app runs the bench actions (D3), and the release owner signs off.

The roles run as Kiro agent templates, not as Kiro Crew members: `embedded-developer-agent`,
`embedded-architect-agent`, `embedded-quality-agent` and `embedded-architecture-reviewer-agent` (descriptions 「Embedded
开发」 and so on), each built from the expert's definition; a role's session boots its template. Kiro Crew 0.12 builds a
new member from its own worker and refuses one built from a template (`mate_template_unsupported`), and refuses a member
named like any template (`template_name_in_use`). The agent-team sample's templates carry the experts' own names, so the
two samples install side by side.

Why tests first: TR §4.1 asks that a test fails before its fix, which `unit.sh` cannot see. With the tester's tests
written first, the app can run them on the base commit and require that they fail before the developers start.

Alternatives considered: four roles, with triage and architecture in one role and one gate; three roles (triage, one
developer, reviewer).

### D7. Check results: who a failure goes back to, and when a person decides

- **A failure goes to the owner of the file it names.** The check adapter takes the file paths from the check's
  result (the file of a compiler error, the location of a static analysis finding, the finding of a failing test) and
  sends the failure to the developer whose write scope from the work split covers that file. A failure that names no
  file (for example `logdiff` or `runtime-limits`) goes to the default owner the team file sets for that check.
- **BLOCKED goes to a person.** A check that cannot judge (exit status 3) is not sent back to a role.
- **Repair rounds are bounded per check,** as the scenario says: three for a failing cross build, two for a failing
  log comparison. After that the unit stops and a person decides.

Checked on 2026-11-02 in `checks/lib/`: the file paths are in `reasons`, not in `details`, so the adapter takes
them from there and keeps the paths that are files of the judged project:

- `build`: compiler errors, flag problems and hidden code start with `src/<file>[:<line>]`. A link error or a
  missing libsystemd names no file.
- `static`: new findings, findings still reported and suppression problems give `<file>:<line>`. A finding that is
  gone against its triage, and triage problems, give only the finding ID.
- `unit`: only sanitizer reports name a file; a path into the check's copy of the tree (`…/work/unit/tree/src/…`)
  is taken relative to it. Failing tests, missing tests for a fix and base tests that no longer run name none.
- `size`, `trace` (commits, not files), `runtime-limits`, `logdiff` and `release` name no file.

A reason that names no file goes to the check's default owner. On the reference project as shipped, `build` FAILs
on `src/main.cpp:12:10` (the toolchain seed) and goes to the owner of `src/main.cpp`; `static` is BLOCKED by the
same header.

Alternatives considered: sending every failure to every developer who changed code; one fixed owner per check.

### D8. A scorecard view with measured figures only, in place of the CTO view

The agent-team app opens on a CTO view of a simulated organization. This app replaces it with the rehearsal
scorecard of the scenario page ("How the sample is measured"), filled in from the records of the runs: findings
fixed, justified and deferred, and justifications overturned; the times from the backlog to an approved triage, to
the first passing check run and to sign-off; build repair rounds; check failures caught before the bench, by check;
log differences and how many were real behaviour changes; bench actions approved, refused and reconciled; checks
whose result changed on the independent rerun. A figure with no run behind it stays empty. The cards and charts of
the CTO view are reused.

The scorecard's "tool calls by permission class" comes from the audit log of the `build` and `bench` MCP servers. In
this app the agents use no such server (D2, D3), so the view leaves that figure out rather than showing zero.

How (step 8): `GET /scorecard` reads each run's `run.json`, `events.jsonl`, approved triage and results directories,
and the bench's `actions.jsonl` (entries tied to the run by the requester the app passes to `cc1.sh`). A
justification counts as overturned when a person answers other than A to its question at the triage gate (the
send-back event names it) or a reviewer's 要改 reply names a finding the approved triage justifies. Findings leave
out the entries the triage added (the refactor, D13). Times are wall clock from the run's start and are not summed
over runs. Log differences are `logdiff`'s over the after-bench rounds, with how many no approved difference
explained; whether a difference was a real change of behaviour is not recorded by the app, so that figure is left
out. Reconciles count for the run whose request came last before them.

Why: the scenario publishes measured numbers only, and reports no productivity figures until a rehearsal has produced
them.

Alternatives considered: the CTO view with simulated figures for an embedded team; no summary view at all.

### D9. The app reruns every check independently before sign-off

When every role has merged and the replay on the bench has ended, the app reruns every check on the final commit in a
new results directory, from a clean build with no build cache, and then runs `release.sh`. Checks whose result
differs from the run's last result are counted on the scorecard. The sign-off button is enabled only when
`release.sh` passes, and the sign-off dialog shows the evidence page.

Why: the rerun has to be independent of any earlier cache or state; a new directory with no cache, run by the check
scripts and not by an agent, gives that without a manual step.

How (step 7): the rerun goes into `runs/<run>/results/rerun/`, emptied first. Every check removes and rebuilds its own
`<results>/work/<check>/` from `git archive HEAD` and none uses a compiler cache (checked in `checks/lib/`), so a new
results directory is a clean build. The rerun judges the commit the bench deployed, and `logdiff` and `runtime-limits`
judge the run directory of the last replay: `checks/README.md` does not ask for a fresh replay, and `release.sh`
requires that the after-deploy checks judged the build it checked, which another replay would only give after another
deploy approval. The app writes `repair-rounds.json` (rounds used and limits, TR §5.2) into the rerun's results, runs
`release.sh` there, then `evidence-page.sh`. Checks whose verdict differs from the run's last round are recorded with
the rerun for the scorecard. A failing `release.sh` holds the run for a person; 重试 reruns everything. The board's
`release` carries `release.sh`'s verdict, the differing checks and the evidence page's text.

Alternatives considered: a person reruns the checks and hands the results to the app; no rerun.

### D10. Setup installs the app; the bench images are built by a separate command

`setup.sh` installs the app, the knowledge source and the agent templates, in about the time the agent-team setup takes. The
build environment, the CC-1 image and sysroot, and the QEMU runner are built by a separate command. The board shows
the result of `bench/doctor.sh` and, while the bench is not ready, what is missing and the command that builds it.
Until then a run goes on with triage, architecture, tests, development and the checks that do not need the bench; it
stops before the first bench action, with the reason on the board.

Why: the Buildroot build of the target image takes long (not yet measured), and the images are not published because
the target's Linux image is used as a tool and not redistributed.

How (step 6): the team file's `bench` has, besides deploy, restart and replay, `doctor` (run by the app),
`build` and `start` (the bench owner's commands, shown on the board, never run by the app) and `baseline`, the
baseline directory; for `vstatd` it is `~/workplace/vstatd-team/baseline`, written once by the bench owner with
`cc1.sh replay --kind baseline`, since the bench ships no baseline yet. When the before-bench checks pass on what is
merged and the reviewer has let it through, the app runs `doctor.sh`; it holds the run for a person when doctor
fails, the target is off or not known, or the baseline is missing, with the command for each. Then deploy (the
artifact of `build.sh` from that round's results), replay into `runs/<run>/bench/run-<n>/`, and the after-bench
checks on that run directory. A refusal, a timeout at the console, a target left unknown, or an app restart in the
middle of an action holds the run; 重试 carries on from that step. A failing after-bench check goes to its owner as
in D7; the reviewer looks again, and the bench starts over with the new build.

How (step 10): `setup.sh` checks Docker, git, Python, Node 22 and Kiro Crew, builds the board and installs the app
with `app/scripts/dev-install.sh`, writes `sample.json` into the app's data directory, and runs
`scripts/install-team.sh` (knowledge copy, the four templates, the knowledge source
`vstatd`); it ends with the commands for the build container (`vstatd-build:amd64`, the image the team file's check
runner names) and the bench. The app's data directory is `~/.kiro/crew/apps/<app>/data/`: on this machine the
installed agent-team app keeps its `runs/` and `sessions.json` there (2026-11-02). `setup.sh --dry-run` changes
nothing. Neither script has been run against a real Kiro Crew yet.

Alternatives considered: one `setup.sh` that builds everything; published prebuilt images.

### D11. A team's own project plugs in through the team file

The team file declares three things, so that a team can point the app at its own work without changing the app's
code:

- **The project:** `source`, the team's own repository, and the knowledge source with the team's own documents.
- **The checks:** a list, each with a name, its command, whether it runs before or after the bench actions, its
  default owner (D7) and its repair-round limit. A team's own check plugs in when it keeps the existing protocol:
  exit status 0 PASS, 1 FAIL, 2 usage error, 3 BLOCKED, and `<results>/<check>.json`.
- **The bench actions:** the commands for deploy, restart and replay, `bench/cc1.sh` by default. A team that swaps in
  its own bench takes on the physical gate, the approval and the action record in its own commands.

Alternatives considered: documentation only, with the team changing the app's code; loadable adapter modules with a
plugin API.

### D12. The app refers to the scenario's folders by path; names

Kiro Crew installs an app by copying its folder, and the agent-team orchestrator accepts a `starter` only inside the
app. The checks find the knowledge as their sibling folder (`checks/lib/common.py`), and `bench/cc1.sh` mounts its own
folder. So the app does not copy `checks/`, `knowledge/`, `bench/` or `reference-project/`: `setup.sh` records the
absolute path of this scenario's folder in the app's data, and the team file writes `${sample}/...`, which the app
replaces with that path (`"source": "${sample}/reference-project"`, `${sample}/checks/build.sh`). The checks and the
bench run from this folder, as their own READMEs describe, and the same files serve Kiro and Kiro Crew. As in the
agent-team sample, the folder stays where it is after setup; after a move, `setup.sh` runs again.

Names: the app `vstatd-team`, its board titled 「车载平台服务 · AI-DLC 团队」, run repositories under
`~/workplace/vstatd-team/runs/<run>/`, the knowledge copy under `~/workplace/vstatd/`.

Left out of the copy: team routing and the standards index (one team; the rules are in the knowledge and enforced by
the checks), `starters/`, `packs/`, `demo/` and the simulated CTO history.

The four AI-DLC experts this team uses are copied unmodified into `vendor/aidlc-workflows/`, so that this sample does
not depend on the agent-team sample's folder.

**A third path around the guardrails (D2):** the check results of each round are written under
`~/workplace/vstatd-team/runs/<run>/results/`, outside the worktrees so that they are never merged, but an agent's
shell can write there too. The README lists it with the other two.

### D13. Every commit after the triage's base cites a finding, the refactor included

`trace.sh` judges every commit from the triage's `base` to `HEAD` and requires each to cite a finding (TR §7.2). Two
things follow, and neither changes a check:

- **The refactor is a triage entry.** No backlog finding covers the split of `Service::run()`, so the triage role
  adds it under TR §4.4 as the next free ID (F-031 on the shipped backlog), with `added.found_by` naming the work
  item, decision `fix`, evidence `build`, `behaviour: false`; the log comparison shows that behaviour is kept. TR §4.4
  and `checks/README.md` say that a change the work item asks for is added this way.
- **The app's own commits cite what they carry.** The triage's `base` is the run branch's head once the build-start
  gate is approved and its decisions are committed; the roles commit their own work with the finding IDs (and, for a
  fix that touches behaviour, a fact entry) in the message; the app's merge commit lists the finding and fact IDs of
  the commits it merges.

How (step 5): the build-start gate is the last human gate of the team file. From the base on, the app does not commit
a role's leftovers: a role with uncommitted work, or a commit that `trace.sh` would refuse (no finding, a finding the
triage defers, a behaviour fix without one of its fact entries), is sent back before its merge, in a round of its own.
Carrying the IDs of the role's other commits into an app commit was not chosen: it would tie files to findings the role
never tied them to, and `trace.sh` would pass on that guess. The merge commit ends with `Findings: …` and, when the
merged commits cite fact entries, `Facts: …`.

Alternatives considered: `trace.sh` accepting work-item IDs (a change to a check the agents cannot change); leaving
the refactor out of this version.

## Implementation plan

Each step ends with its verification; a step is done when that verification passes. Steps 1 to 11 run without the
bench images; step 12 needs them.

1. **Copy the app.** Copy `agent-team-on-kiro-crew/app/` to `app/`; rename it `vstatd-team` (manifest, namespace,
   data paths); remove what D12 leaves out with their tests; keep the minimal built-in team for the tests.
   *Verify:* the remaining backend tests pass; `npm run check` in `ui/` passes.
2. **Paths and the team file.** `paths.py` and the `${sample}` substitution; `team-vstatd.json` with the six roles
   and two gates of D6 and the declarations of D11; the task template. *Verify:* tests for the team file's
   validation and the substitution; a test run repository is created from `reference-project/`.
3. **Check adapter.** First read every check's result file for the file paths D7 needs. Then: run the team file's
   check list in the build container, in the background so that the tick is not held; the exit status protocol; one
   results directory per round outside the worktrees; failures to the owner of the file, else the check's default
   owner; BLOCKED and exhausted repair rounds to a person. *Verify:* tests with stand-in check scripts for each exit
   status and each routing case; `build.sh` and `static.sh` run once through the adapter on `reference-project/`.
4. **Tests first.** After the tester merges, the app runs the new tests on the base commit and sends them back to
   the tester when any of them passes there. *Verify:* a test with a new test that passes on the base commit.
5. **Triage gate.** `triage.py` turns `triage.json` and the backlog into the gate's questions (D4). *Verify:* tests
   on a triage file with fixes, justifications, deferrals and a disagreement with the backlog.
6. **Bench.** `bench.py` calls `cc1.sh` for deploy, restart and replay, and reads the pending requests, the action
   record and the result of `doctor.sh`; a run stops before its first bench action while the bench is not ready.
   *Verify:* tests with a stand-in `cc1.sh` and bench state directory.
7. **Rerun and sign-off.** The independent rerun of D9, `release.sh`, the evidence page in the sign-off dialog, and
   sign-off only after `release.sh` passes. *Verify:* tests where the rerun differs and where `release.sh` fails.
8. **Scorecard.** `scorecard.py` and the scorecard view of D8. *Verify:* tests on recorded run events; with no runs,
   every figure is empty.
9. **Board.** The check wall (PASS, FAIL, BLOCKED, evidence tier), the bench panel, the triage questions with their
   citations, the evidence page at sign-off. *Verify:* `npm run check`; the preview page builds.
10. **Members, setup and cleanup.** `agents/kiro-crew/make_templates.py`, `vendor/aidlc-workflows/`, `setup.sh`,
    `cleanup.sh`, `scripts/`. *Verify:* setup runs twice without change the second time; `cleanup.sh --dry-run`
    lists exactly what setup recorded; a template with the same name is backed up and put back.
11. **Documentation.** The scenario README (the app, the three paths around the guardrails, prerequisites) and
    `app/README.md`. *Verify:* links resolve; the README's claims match these notes.
12. **One delivery end to end.** With the bench images built: from the triage gate to sign-off, approving bench
    actions at the console. Record the time and credits it used and how long the checks, the rerun and the image
    build took. *Verify:* `release.sh` passes on the rerun and the scorecard shows the run.

## Not yet verified

- Whether the build container's ThreadSanitizer reports give the absolute path of the check's copy, as the adapter
  expects, or a relative one (D7); both are handled, neither has been seen in a run of the adapter.
- How long a full check run, the independent rerun (D9) and the Buildroot image build (D10) take on a Mac.
- Whether write-scope rules in an agent's own configuration are enforced on a machine whose user-level
  `permissions.yaml` does not allow everything (D2).
