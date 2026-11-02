# Checks

The checks of the in-vehicle scenario ([scenario page, section 3](../README.md#3-checks-and-gates-before-the-bench)):
command-line scripts whose exit status is the verdict. The build server runs them in the build environment of
[`reference-project/tools/Dockerfile`](../reference-project/tools/Dockerfile); the agents can run them through the
`build` and `bench` tools but cannot change them, and `setup.sh` does not copy this folder into the agents'
workspace. The checks read the knowledge in [`../knowledge/`](../knowledge/) and their limits from
[`limits.json`](limits.json), and judge the project's committed tree; see "What the agents can and cannot write"
for the inputs they take on trust.

| Script | Judges | Tier of its evidence |
| --- | --- | --- |
| `build.sh` | The cross build of the project with its own toolchain file: every file compiled by `aarch64-linux-gnu-g++` with the flags of TR §2.1 in effect, against the CC-1 sysroot and without the unit tests' test double (CC1-PN §7), and `vstatd` linked against libsystemd. Strips `vstatd` and records its SHA-256, the digest a person approves at the operator console | — |
| `static.sh` | cppcheck 2.13 and clang-tidy 18 with the settings of TR §3.1 (the check's own copy, [`lib/clang-tidy.yaml`](lib/clang-tidy.yaml)) against the backlog and the triage | — |
| `unit.sh` | The unit tests in a plain, a ThreadSanitizer and an AddressSanitizer with UndefinedBehaviorSanitizer build (TR §2.2), each with every test of the base commit, and a new or changed test for each fix that needs one (TR §4.1) | unit test |
| `size.sh` | The stripped size of the artifact `build.sh` produced for the same commit (CC1-PN §3) | — |
| `trace.sh` | The commits from the triage's base commit to `HEAD` against the triage (TR §4.1, §7.2) | — |
| `runtime-limits.sh` | Peak RSS and thread count of `vstatd` on the replay (CC1-PN §3); CPU time reported against the baseline only | emulation, or real target |
| `logdiff.sh` | The runtime log of the replay against the baseline log, as CC1-PN §6 says | emulation, or real target |
| `release.sh` | Every check passed on the final commit, for the same triage, the same build and the same run, and no requirement is blocked by its tier (TR §6, §7) | — |
| `evidence-page.sh` | Writes one Markdown page for the batch from the results and the triage (TR §7.3, §7.4) | — |

## Running

In the build container, with the sysroot in `/opt/cc1-sysroot` and the project as a git work tree:

```bash
checks/build.sh  --project <project> --results <results>
checks/static.sh --project <project> --results <results> --triage <triage.json>
checks/unit.sh   --project <project> --results <results> --triage <triage.json>   # needs seccomp=unconfined, see below
checks/size.sh   --project <project> --results <results>
checks/trace.sh  --project <project> --results <results> --triage <triage.json>
checks/runtime-limits.sh --run <run dir> --baseline <baseline dir> --results <results>
checks/logdiff.sh        --run <run dir> --baseline <baseline dir> --results <results> --triage <triage.json>
checks/release.sh        --project <project> --results <results> --triage <triage.json>
checks/evidence-page.sh  --results <results> --triage <triage.json>      # writes <results>/evidence.md
```

`unit.sh` runs the ThreadSanitizer build under `setarch -R`, which in a container needs
`docker run --security-opt seccomp=unconfined` (see the reference project's README). Each check copies the committed
tree (`git archive HEAD`) to `<results>/work/` and builds there; files that git ignores never reach a build, and
nothing is written into the project.

## Verdict rules

These rules come from a bench proof of concept in which checks passed when they should not have. Each one has a test
in [`test/test_checks.py`](test/test_checks.py).

1. **The exit status is the verdict:** 0 PASS, 1 FAIL, 3 BLOCKED (the check cannot judge: an input is missing or
   incomplete, the run had not ended, the tree is not committed), 2 a usage or configuration error. The checks run
   every tool as a subprocess and read its exit status; no status is lost in a pipe, and a FAIL never ends in 0.
2. **No evidence is not a pass.** No test ran, a test was skipped or disabled, an analyser did not complete on every
   file, the log is empty or does not end with `SERVICE_STOP`, the figures were taken before the replay ended
   (CC1-PN §8.5), a check crashed: each is BLOCKED or FAIL, never PASS.
3. **Limits come from the knowledge, not from the caller.** Every limit is in [`limits.json`](limits.json) with its
   source, and a test checks that the source states it. No option or environment variable changes a limit; an
   unknown option is a usage error.
4. **Compare everything, filter nothing.** `logdiff.sh` compares every entry and every field except those CC1-PN §6.2
   ignores. A difference passes only when the approved triage allows it, for a finding it fixes or justifies.
5. **A result that a machine can read.** Each check writes `<results>/<check>.json` (fields below) and
   `<results>/<check>.log`.
6. **The committed tree is judged.** The source checks refuse a tree with uncommitted changes (BLOCKED). `--local`
   judges it anyway, for iterating; the result is marked `local` and `release.sh` refuses it.

The checks also stay independent of what they judge. `static.sh` uses its own copy of the analyser settings and of
the backlog matcher ([`lib/match_backlog.py`](lib/match_backlog.py), identical to the project's
`tools/match-backlog.py`; a test keeps them identical). `build.sh` and `unit.sh` read the flags and sanitizers in
effect from `compile_commands.json` (the last of conflicting flags counts) rather than trusting the project's CMake
files. `build.sh`, `static.sh` and `unit.sh` fail on code hidden from them: analyser guards such as `__CPPCHECK__`,
`#pragma GCC diagnostic`, `NOLINTBEGIN`, `no_sanitize` and the sanitizers' default-options hooks. Each justified
finding may be suppressed once, in its own function, in a form of TR §3.2.

What the checks cannot see: whether a test fails before its fix (TR §4.1 asks for it; `unit.sh` checks only that a
new or changed test names the finding and passes), and whether a change is the right one. Those stay with the
reviewer of the batch.

## Result files

```json
{
  "check": "logdiff", "verdict": "FAIL", "commit": null, "local": false, "tier": "emulation",
  "inputs": {"run_log": {"path": "...", "sha256": "..."}, "triage": {"path": "...", "sha256": "..."}},
  "details": {"...": "check-specific figures and tables"},
  "reasons": ["only in the run: {\"t_ms\":480,\"ev\":\"SIGNAL_TIMEOUT\",\"message\":\"VCU_Speed\"}"],
  "tools": {"...": "versions"}, "started": "...", "ended": "...", "summary": "..."
}
```

`commit` is the commit a source check judged (`<commit>-dirty` with `--local`); the after-deploy checks are tied to a
commit through the deployed digest instead. `release.sh` recomputes every input's SHA-256 and fails when one changed
after it was judged.

## What the agents can and cannot write

The checks trust four inputs that the agents must not be able to change: the approved triage and its approval
record, the baseline directory, the run directories the bench writes, and the results directory. In this sample they
live on the build server outside the agents' workspace; the agents reach the checks only through the `build` and
`bench` tools (build plan item 5), which run them with fixed arguments and return the results read-only. The
approval record `<triage>.sha256` holds the SHA-256 of the triage as a person approved it at the operator console;
every check that reads the triage refuses one that changed since (BLOCKED), and `release.sh` requires every check to
have judged the same one.

## The approved triage

The output of the Inception phase, approved before any code changes (TR §4.3); JSON, with its approval record
`<triage>.sha256` next to it. A complete example of the format is [`examples/triage.json`](examples/triage.json) with
[`examples/triage.json.sha256`](examples/triage.json.sha256) (it decides only two findings and defers the rest).

| Field | Contents |
| --- | --- |
| `batch` | Name of the batch |
| `base` | The commit the batch starts from (40 hex digits). `trace.sh` judges `base..HEAD`; `unit.sh` checks that every test of `base` still runs |
| `approved` | `by` and `at`. A triage without them is not approved: the checks are BLOCKED |
| `findings` | One entry per finding labelled `fix` in the backlog, and per finding added under TR §4.4 |
| `allowed_log_differences` | Log entries the run may lack or add, each for a finding the triage fixes or justifies |
| `requirements` | Requirements with their evidence: `id`, `real_target_only` (TR §6), `evidence` (names of checks) |

A finding entry:

| Field | Used for |
| --- | --- |
| `id`, `decision` | `F-nnn`; `fix`, `justify` or `defer` (TR §4.1) |
| `evidence` | For a fix: `unit-test` (a test that is new or changed in the batch and runs names the ID in its name or body, as `F-nnn`, `Fnnn` or `F_nnn`), `static-analysis` (the analyser run is the test) or `build` |
| `behaviour` | For a fix: `true` when it touches behaviour of VSTATD-IF; its commits then cite one of its `facts` |
| `cites` | Sections such as `[VSTATD-IF p.7 §4.2]` or `[CC1-PN §3]`; required for a justification and for a fix that touches behaviour, which cite VSTATD-IF or CC1-PN. The section must exist, and a VSTATD-IF citation gives its page |
| `facts` | Fact entry IDs of `knowledge/facts/`, such as `SUP-GRACE` |
| `reason`, `pick_up_when` | For a deferral |
| `added` | For a finding added during the batch (TR §4.4): `found_by`, `tool`, `location`. Added findings take the next free IDs in turn, from F-031 |

An allowed log difference: `{"finding": "F-nnn", "side": "baseline" or "run", "entry": {<the whole entry>},
"count": 1}`. The entry gives `ev` and every compared field; `t_ms`, if given, matches within the comparison window.

## Run and baseline directories

**Proposed interface with build plan item 3 (the bench).** The bench writes a run directory after each replay, and
the baseline directory once for the current release, as CC1-PN §8.5 says: after the replay ends it reads `VmHWM` and
the thread count, stops `vstatd`, then collects the log up to `SERVICE_STOP`. Before each replay the bench should also
write a marker line to the journal and read it back, so that a log that comes back empty means `vstatd` wrote
nothing, not that the log path was broken or flooded by another process.

| File | Contents |
| --- | --- |
| `run.jsonl` / `baseline.jsonl` | The runtime log of the run (CC1-PN §5), up to and including `SERVICE_STOP`. Every line has the keys in the order of CC1-PN §5.2 and the fields of VSTATD-IF §7.1; a line that does not is a FAIL |
| `run-result.json` / `baseline-result.json` | The fields below |

| Field | Type | Contents |
| --- | --- | --- |
| `replay_id` | string | The recorded drive and client script; run and baseline must have the same one |
| `target` | string | `emulated-cc1` or `real-cc1` |
| `qemu_command` | string | The exact QEMU command line (CC1-PN §2.2); required for `emulated-cc1`, with `-icount shift=<n>,sleep=off`. Run and baseline must use the same setting |
| `replay_finished` | boolean | The drive player reported the end of the drive |
| `replay_end` | string | How the end was detected: `player-end-of-drive` (the drive player's end-of-drive marker). The exit status of the script that started the replay does not count (CC1-PN §8.5) |
| `figures_after_replay_end` | boolean | `VmHWM` and threads were read after the end |
| `vm_hwm_kib`, `threads_at_end`, `cpu_ms` | integer | Read from `/proc/<pid>/status` and `/proc/<pid>/stat` before `vstatd` was stopped |
| `approved_digest`, `readback_digest` | string | SHA-256 of the build approved at the operator console, and as read back from the target (CC1-PN §8.4) |

## Tests

```bash
python3 checks/test/test_checks.py
```

runs every check on small synthetic inputs, a passing and a failing example each and the verdict rules above; it
needs only Python 3 and git. The checks' runs on the real reference project, including the seeded difficulties, are
in the facilitators' [`../rehearsal/check-examples/`](../rehearsal/check-examples/).

The checks use Python 3's standard library, git, CMake, Ninja, GCC 12, cppcheck (GPL-3.0) and clang-tidy (Apache-2.0
with LLVM exception), all from the build environment. They are run as tools; none is redistributed with the sample.
