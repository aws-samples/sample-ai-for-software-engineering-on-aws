# Check examples: the checks on the reference project

> For facilitators. **Not part of the agents' workspace:** the batch below contains the answers to the seeds.

[`run.py`](run.py) copies `reference-project/` into a temporary git work tree and walks a batch commit by commit:
the toolchain seed with two wrong repairs and the right one (added as F-031, the first free ID), the ThreadSanitizer
race added as F-032 and fixed, a fix the
triage did not approve, a justification with and without the suppression of TR §3.2, the F-008 wrong fix, and the
F-021 wrong fix on a branch of its own from before F-008. After each step it runs the check the step is about and
compares the exit status with the expected verdict. It keeps three of the builds, the release with only the toolchain
repair, the F-008 wrong fix and the F-021 wrong fix, for [`bench.py`](bench.py), which deploys them to the bench and
runs the two after-deploy checks ([After deploy, on the bench](#after-deploy-on-the-bench)). The synthetic
examples of every check, and the tests of the verdict rules, are in [`../../checks/test/`](../../checks/test/).
[`../build-server-run/`](../build-server-run/) walks the same batch through the `build` MCP server.

```bash
docker run --rm --security-opt seccomp=unconfined -v "$PWD":/sample:ro -v /opt/cc1-sysroot:/opt/cc1-sysroot:ro \
    vstatd-build:arm64 python3 /sample/rehearsal/check-examples/run.py   # vstatd-build:amd64 on x86_64
```

Run from the scenario folder, with the image of `reference-project/tools/Dockerfile` and the stand-in sysroot of
`reference-project/tools/make-standin-sysroot.py`. It takes about ten minutes, most of it in the three unit-test
builds that `unit.sh` makes on each call.

## Last run

2026-11-16, amd64 build container `vstatd-build` on an x86_64 Ubuntu 24.04 host (GCC 12.4.0, cppcheck 2.13.0,
clang-tidy 18.1.3, git 2.43.0), Buildroot sysroot from the volume `cc1-sysroot`. 27 of 27 as expected, in 568 s. The
table is that run's ([`bench-data/run-py.md`](bench-data/run-py.md)); the checks no longer print a reason when they
pass, and ThreadSanitizer names the race with the absolute path of the check's copy.

Earlier runs: 2026-11-03, native arm64 image on Apple Silicon, stand-in sysroot, the 23 rows up to step 6 as expected
in 215 s; with `cc1-sysroot` 23 of 23 in 359 s once `bench/build-target.sh` exported the C++ headers (2026-11-04),
before that the seven `static` rows from step 2 on were BLOCKED. The amd64 image under Rosetta cannot run
ThreadSanitizer, so there the `unit` rows fail for that reason. `checks/test/test_checks.py` had 72 tests OK in the
arm64 container on 2026-11-03.

| Step | Check | Expected | Verdict | First reason |
| --- | --- | --- | --- | --- |
| 0 release as is | `build` | FAIL | FAIL | src/main.cpp:12:10: fatal error: systemd/sd-daemon.h: No such file or directory |
| 0 release as is | `static` | BLOCKED | BLOCKED | src/main.cpp:12:10: error: 'systemd/sd-daemon.h' file not found [clang-diagnostic-error] |
| 0 release as is | `trace` | BLOCKED | BLOCKED | no commit between the triage's base and HEAD |
| 1 stub path (uncommitted) | `build` | BLOCKED | BLOCKED | uncommitted changes in the project; commit them, or use --local for local iteration |
| 1 stub path (local) | `build` | FAIL | FAIL | collect2: error: ld returned 1 exit status |
| 1 stub copied into src (local) | `build` | FAIL | FAIL | vstatd is not linked against libsystemd.so.0 (readiness via sd_notify, CC1-PN §4.2, §7.2) |
| 2 sysroot | `size` | BLOCKED | BLOCKED | no result of checks/build.sh in the results directory |
| 2 sysroot | `build` | PASS | PASS |  |
| 2 sysroot | `size` | PASS | PASS |  |
| 2 sysroot | `static` | PASS | PASS |  |
| 2 sysroot | `unit` | FAIL | FAIL | tsan: SUMMARY: ThreadSanitizer: data race /out/results/2/work/unit/tree/src/signal_table.cpp:90 in vstatd::Sig |
| 2 sysroot | `trace` | PASS | PASS |  |
| 3 race fixed | `unit` | PASS | PASS |  |
| 3 race fixed | `trace` | PASS | PASS |  |
| 4 F-013 fixed, triage defers it | `static` | FAIL | FAIL | F-013: no longer reported, but triaged as defer; a change outside the batch removed it |
| 4 F-013 fixed, triage fixes it | `static` | PASS | PASS |  |
| 5 F-007 suppressed without an ID | `static` | FAIL | FAIL | src/frame_decoder.cpp:144: suppression not in a form of TR §3.2: std::uint64_t physical{raw * def.int_factor}; |
| 5 F-007 suppressed, triage defers it | `static` | FAIL | FAIL | src/frame_decoder.cpp:144: suppression names F-007, which the approved triage does not justify |
| 5 F-007 justified | `static` | PASS | PASS |  |
| 5 F-007 justified | `trace` | PASS | PASS |  |
| 6 F-008 wrong fix | `static` | PASS | PASS |  |
| 6 F-008 wrong fix | `trace` | PASS | PASS |  |
| 6 F-008 wrong fix | `unit` | FAIL | FAIL | F-008: triaged as fix with evidence unit-test, but no test that is new or changed in the batch and runs names  |
| 6 F-008 wrong fix | `build` | PASS | PASS |  |
| 7 F-021 wrong fix | `static` | PASS | PASS |  |
| 7 F-021 wrong fix | `trace` | PASS | PASS |  |
| 7 F-021 wrong fix | `build` | PASS | PASS |  |

Step 6 is the point of the F-008 seed: the wrong fix removes the finding, is traced and cites its fact entry, so
static analysis and trace pass. Here `unit.sh` fails only because the example adds no test that names F-008; with such a test, it
would pass unless the test covers the start-up grace period, which no baseline test does. `logdiff.sh` on the bench
catches it ([After deploy, on the bench](#after-deploy-on-the-bench)). Step 7 is the opposite case: the F-021 fix is
correct, so every check before the bench passes, and only `runtime-limits.sh` on the bench sees what it costs.

## After deploy, on the bench

`runtime-limits.sh` and `logdiff.sh` judge the run directories the bench writes (build plan item 3).
[`bench.py`](bench.py) takes the three builds `run.py` kept and, on the bench host as the bench owner:

1. boots the emulated CC-1 once (`bench/cc1.sh stop`, `start --shift 3`, `wait`);
2. deploys the release build and replays the recorded drive once as the baseline;
3. deploys each build in turn, the release, the F-008 wrong fix and the F-021 wrong fix, and replays it `--runs`
   times;
4. after each replay runs both checks in the build container against that baseline, with the triage `run.py`
   approved last, which allows no log difference, and compares their verdicts with the expected ones.

```bash
mkdir /tmp/check-examples
docker run --rm --security-opt seccomp=unconfined --user "$(id -u):$(id -g)" -e HOME=/tmp -e OUT=/out \
    -v /tmp/check-examples:/out -v "$PWD":/sample:ro -v cc1-sysroot:/opt/cc1-sysroot:ro \
    vstatd-build:amd64 python3 /sample/rehearsal/check-examples/run.py      # vstatd-build:arm64 on Apple Silicon
python3 bench/console.py supply --voltage 13.5 --kl15 on
CC1_BENCH_STATE=<state dir> python3 rehearsal/check-examples/bench.py --state <state dir> \
    --artifacts /tmp/check-examples/artifacts --out <new data dir> --runs 10 --image vstatd-build:amd64
```

Each deploy and replay is a request that waits for a person at `bench/console.py` for the same state directory;
`bench.py` approves nothing. Give it a state directory of its own, not the Kiro Crew app's.

### Last run

2026-11-16, on the x86_64 host of the build container above (AMD EPYC 7R13, 8 vCPUs, Docker 29.8.2), QEMU 8.2.2,
`-icount shift=3,sleep=off`, the target image of `bench/build-target.sh`, drive `drive-01@39a3d0dec2ab+62abaaf5`.
30 of 30 runs as expected, in 14.1 minutes. **Approvals were scripted:** a small local script outside this repository
approved at `bench/console.py`, in a state directory of its own, exactly the deploys and replays of the three digests
below, 34 requests, nothing else; every action still passed the physical gate (13.5 V, KL15 on). The host was also
running other work: the 1-minute load average at the start of a replay was 7.3 to 18.9.

| Build | Digest | Runs | `logdiff` expected | `logdiff` | `runtime-limits` expected | `runtime-limits` | VmHWM KiB |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Release (F-031 only) | `bc93723c…` | 10 | PASS | PASS | PASS | PASS | 5,768 to 5,964 |
| F-008 wrong fix | `66ac3124…` | 10 | FAIL | FAIL | PASS | PASS | 5,676 to 5,944 |
| F-021 wrong fix | `49093835…` | 10 | PASS | PASS | FAIL | FAIL | 6,644 to 6,832 |

- **F-008.** Every run fails `logdiff` with 20 unexplained differences, all 328 baseline entries paired: the wrong fix
  starts supervision at `GATEWAY_CONNECTED`, so the log gains `SIGNAL_TIMEOUT` and `SIGNAL_RECOVERED` pairs that the
  baseline does not have, for example `only in the run: {"t_ms":97,"ev":"SIGNAL_TIMEOUT","message":"VCU_Speed"}`. Its
  memory stays within the limit.
- **F-021.** Every run fails `runtime-limits`, for example `peak RSS 6772 KiB is over the limit of 6400 KiB
  (CC1-PN §3)`; its log equals the baseline's. The F-021 build also carries steps 3 to 5 of the batch (the race fix,
  F-013 and the F-007 justification), and so does the F-008 build; the release runs and the F-021 runs show that these
  steps change neither the log nor the memory figure.
- **Time window.** The largest time difference of a paired entry was 17 ms in any run (20 ms allowed, CC1-PN §6.3).
- **The F-021 limit on this host.** [facilitator-notes.md](../facilitator-notes.md) asks for this check on any host
  other than the one the limit was calibrated on: the release peaked at most 5,964 KiB, 436 KiB under the limit
  (more than the 300 KiB it asks for), the wrong fix at least 6,644 KiB, 244 KiB over it (more than 200 KiB). The
  6,400 KiB limit holds here without a new calibration.
- **Same build, two hosts.** The release build has the digest of the normal build of the repeatability measurement
  on Apple Silicon ([repeatability/](../repeatability/README.md), `bc93723c…`): the cross build is reproducible across
  the two build hosts.

[`bench-data/`](bench-data/) holds everything the table was computed from: `runs.csv` (one row per run with both
verdicts, their first reasons, `vm_hwm_kib`, threads, CPU, the largest |dt| and the load), `builds.json` (the three
digests), each run's `run-result.json` and `run.jsonl` under `runs/`, the baseline under `baseline/`, both checks'
results per run under `results/`, the triage given to `logdiff`, and `bench.log`, what `bench.py` ran and printed (the
scenario folder is written `<sample>`, the data directory `<data>`).
