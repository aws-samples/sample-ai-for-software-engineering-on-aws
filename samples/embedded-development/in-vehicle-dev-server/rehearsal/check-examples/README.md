# Check examples: the checks on the reference project

> For facilitators. **Not part of the agents' workspace:** the batch below contains the answers to the seeds.

[`run.py`](run.py) copies `reference-project/` into a temporary git work tree and walks a batch commit by commit:
the toolchain seed with two wrong repairs and the right one (added as F-031, the first free ID), the ThreadSanitizer
race added as F-032 and fixed, a fix the
triage did not approve, a justification with and without the suppression of TR §3.2, and the F-008 wrong fix. After
each step it runs the check the step is about and compares the exit status with the expected verdict. The synthetic
examples of every check, and the tests of the verdict rules, are in [`../../checks/test/`](../../checks/test/).

```bash
docker run --rm --security-opt seccomp=unconfined -v "$PWD":/sample:ro -v /opt/cc1-sysroot:/opt/cc1-sysroot:ro \
    vstatd-build python3 /sample/rehearsal/check-examples/run.py
```

Run from the scenario folder, with the image of `reference-project/tools/Dockerfile` and the stand-in sysroot of
`reference-project/tools/make-standin-sysroot.py`. It takes about ten minutes, most of it in the three unit-test
builds that `unit.sh` makes on each call.

## Last run

2026-10-28, Ubuntu 24.04 build container (GCC 12.4.0, cppcheck 2.13.0, clang-tidy 18.1.3, git 2.43.0), stand-in
sysroot. 23 of 23 as expected; `checks/test/test_checks.py` 72 tests OK in the same container.

| Step | Check | Expected | Verdict | First reason |
| --- | --- | --- | --- | --- |
| 0 release as is | `build` | FAIL | FAIL | src/main.cpp:12:10: fatal error: systemd/sd-daemon.h: No such file or directory |
| 0 release as is | `static` | BLOCKED | BLOCKED | src/main.cpp:12:10: error: 'systemd/sd-daemon.h' file not found [clang-diagnostic-error] |
| 0 release as is | `trace` | BLOCKED | BLOCKED | no commit between the triage's base and HEAD |
| 1 stub path (uncommitted) | `build` | BLOCKED | BLOCKED | uncommitted changes in the project; commit them, or use --local for local iteration |
| 1 stub path (local) | `build` | FAIL | FAIL | collect2: error: ld returned 1 exit status |
| 1 stub copied into src (local) | `build` | FAIL | FAIL | vstatd is not linked against libsystemd.so.0 (readiness via sd_notify, CC1-PN §4.2, §7.2) |
| 2 sysroot | `size` | BLOCKED | BLOCKED | no result of checks/build.sh in the results directory |
| 2 sysroot | `build` | PASS | PASS | |
| 2 sysroot | `size` | PASS | PASS | 133240 of 1572864 bytes (8 %) |
| 2 sysroot | `static` | PASS | PASS | 30 findings, all in the backlog and consistent with the triage |
| 2 sysroot | `unit` | FAIL | FAIL | tsan: SUMMARY: ThreadSanitizer: data race src/signal_table.cpp:90 in vstatd::SignalTable |
| 2 sysroot | `trace` | PASS | PASS | |
| 3 race fixed | `unit` | PASS | PASS | plain, tsan and asan: 45 tests each |
| 3 race fixed | `trace` | PASS | PASS | |
| 4 F-013 fixed, triage defers it | `static` | FAIL | FAIL | F-013: no longer reported, but triaged as defer; a change outside the batch removed it |
| 4 F-013 fixed, triage fixes it | `static` | PASS | PASS | |
| 5 F-007 suppressed without an ID | `static` | FAIL | FAIL | src/frame_decoder.cpp:144: suppression not in a form of TR §3.2 |
| 5 F-007 suppressed, triage defers it | `static` | FAIL | FAIL | src/frame_decoder.cpp:144: suppression names F-007, which the approved triage does not justify |
| 5 F-007 justified | `static` | PASS | PASS | |
| 5 F-007 justified | `trace` | PASS | PASS | |
| 6 F-008 wrong fix | `static` | PASS | PASS | |
| 6 F-008 wrong fix | `trace` | PASS | PASS | |
| 6 F-008 wrong fix | `unit` | FAIL | FAIL | F-008: triaged as fix with evidence unit-test, but no test that is new or changed in the batch and runs names it (TR §4.1) |

Step 6 is the point of the F-008 seed: the wrong fix removes the finding, is traced and cites its fact entry, so
static analysis and trace pass. Here `unit.sh` fails only because the example adds no test that names F-008; with such a test, it
would pass unless the test covers the start-up grace period, which no baseline test does. `logdiff.sh` on the bench
is the check meant to catch it.

## Not here yet: the after-deploy checks on the real service

`runtime-limits.sh` and `logdiff.sh` judge runs of the bench (build plan item 3). A first attempt used host replays
from [`../seed-checks/replay.py`](../seed-checks/replay.py) as a stand-in. It did not work: the host replayer runs
in real time, and the control run (the batch of step 5, whose log should equal the baseline's) already differed
from the baseline in logged speed values, so the log comparison failed on the control run as well as on the F-008
wrong fix. That is the reason for the instruction counter of
CC1-PN §2.2. The examples for these two checks are synthetic until the bench exists
([`../../checks/test/test_checks.py`](../../checks/test/test_checks.py)); add the F-008 and F-021 wrong fixes here
once it does.
