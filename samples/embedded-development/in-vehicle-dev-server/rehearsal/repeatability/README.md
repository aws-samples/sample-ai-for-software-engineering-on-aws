# Repeatability and memory of the emulated CC-1

For facilitators, not for the agents' workspace. Answers two questions from the review of #21: is the log comparison's
20 ms time window wide enough for runs of the same build, and can the peak-RSS limit for F-021 come down to
6,400 KiB so that the `lines_{}` wrong fix fails `checks/runtime-limits.sh`.

## Method

[`measure.py`](measure.py), run as the bench owner on 2026-11-04 between 12:59 and 13:38 (UTC+8):

- Four fresh boots of the emulated CC-1 (`bench/cc1.sh stop`, `start --shift 3`, `wait`), each followed by a deploy.
- Boot 1: the normal build, **one baseline** (`replay --kind baseline`), then 20 runs. Boots 2 and 3: the same build
  deployed again, 20 runs each. Boot 4: the F-021 wrong fix, 10 runs. Every run is compared with the one baseline of
  boot 1.
- After each run, `checks/logdiff.sh` and `checks/runtime-limits.sh` judge it in the build container, with their own
  20 ms window and limits. The time difference of every paired entry is also measured with
  `checks/lib/check_logdiff.compare()` and a 200 ms window, so that differences beyond 20 ms are seen too (none of
  the entries stayed unpaired at 200 ms).
- **Approvals were scripted.** The measurement used a bench state of its own (`CC1_BENCH_STATE`, not the one of the
  Kiro Crew app), requests named `repeatability measurement`, and a small local script outside this repository that
  approved at `bench/console.py` exactly the deploys and replays of the two digests below, nothing else. Every action
  still passed the physical gate (13.5 V, KL15 on). `measure.py` itself approves nothing.
- **The host was in use.** During boots 1 and 2 the same Mac was also used to edit code (`host_in_use` = yes); during
  boots 3 and 4 it was not. The 1-minute load average at the start of each replay is recorded. During boot 3 the host
  stalled for about 23 minutes for a reason not found (run 3 took 1,415 s of wall clock, the load average rose to 230),
  which makes boot 3's runs 4 to 18 a test under very high load.

| | |
| --- | --- |
| Machine | Apple M3 Pro, macOS 26.7.2, Docker Desktop 29.2.0 (6 CPUs, 4.3 GiB for Docker) |
| Kiro Crew / kiro-cli | 0.12.0-rc.4 / 3.0.0 (not used by the measurement) |
| Target image | Buildroot 2026.02.3, Linux 6.18.7, `Image` `8aeb98e5…`, `rootfs.ext4` `cc413942…` (built 2026-11-04) |
| Normal build | `vstatd` of the Kiro Crew app's baseline (the current release with the CC-1 sysroot), `bc93723c0cb02e054acc5f25705b61a4443435c168351ec5914d0729bdce4d98` |
| F-021 wrong fix | the same source with `lines_{}` in `src/client_session.h`, built by `checks/build.sh` with the stand-in sysroot, `0d8cfee207ea9305165eee6fbcde8c96d75e0324fb8b958d0f591de89a84334a` |
| Baseline | boot 1, `vm_hwm_kib` 5,900, 3 threads, 2,640 ms CPU |

[`data/runs.csv`](data/runs.csv) has one row per run (boot, replay in the boot, build, the two verdicts, the largest
and 99th-percentile |dt|, the entries over 10, 15 and 20 ms, the entry with the largest |dt|, `vm_hwm_kib`,
`threads_at_end`, `cpu_ms`, wall clock, load, host in use). Everything it was computed from is here:

- [`data/runs/`](data/runs/): each run's `run-result.json` (`<boot>-<run>.json`) and its runtime log `run.jsonl`
  (`<boot>-<run>.jsonl`), as `cc1-bench finish` wrote them;
- [`data/baseline.jsonl`](data/baseline.jsonl) and [`data/baseline-result.json`](data/baseline-result.json): the
  baseline replay every run is compared with;
- [`data/checks/`](data/checks/): per run, the results of `checks/logdiff.sh` and `checks/runtime-limits.sh`
  (`logdiff.diff` for the two runs logdiff failed); [`data/triage.json`](data/triage.json) is the triage logdiff was given;
- [`data/measure.log`](data/measure.log): what `measure.py` ran and printed, in order (the repository's path is written
  `<repo>`, the home directory `~`).

Recomputing the table from these files with `dt_stats()` of `measure.py` gives the same largest and 99th-percentile
|dt|, counts over 10, 15 and 20 ms, entry with the largest |dt| and unpaired entries for all 70 runs; the
`vm_hwm_kib` and both verdicts match the run results and the check results.

## Results

**Time window (60 runs of the normal build).**

- `logdiff` PASS in 58 of 60; the two FAILs were boot 1, runs 4 and 19, with 24 and 23 ms. The longest series within
  20 ms is 41 runs (boot 1 run 20 to the end of boot 3).
- Largest |dt| per run: minimum 2, median 5, maximum 24 ms. Runs with an entry over 10 ms: 10; over 15 ms: 5; over
  20 ms: 2.
- In the normal runs every entry over 15 ms is a `CLIENT_CONNECTED` 1.24 to 1.54 s into the drive, when the 16
  replay clients connect, apart from one `SERVICE_STOP` (18 ms, boot 1 run 4). In four runs all 16 connections are
  late by the same amount (16 to 24 ms): boot 1 runs 4, 14 and 19 (load 7.9 to 10.2, host in use) and boot 3 run 8
  (load 118, host not in use); in boot 3 run 12 (load 66), clients 3 and 8 are 16 ms late. In the F-021 runs the
  three over 15 ms are `SERVICE_STOP` at the end of the drive (18 and 19 ms) and client 7's `CLIENT_CONNECTED` at
  1.36 s (20 ms).
- The first replay after a boot did not differ more: 3, 8 and 4 ms in boots 1 to 3 (3 ms in boot 4).
- Load did not explain it: the two FAILs came at load 8, while boot 3 ran at load 9 to 230 with no FAIL.

So at shift 3 the 20 ms window is too tight for the clients' connection times: about 1 run in 30 fails on the same
build. Widening the window, or pairing `CLIENT_CONNECTED` by client rather than by time, is a decision for the checks
(item 4); this measurement changes neither.

Since this measurement, CC1-PN §6.3 gives `CLIENT_CONNECTED` and `SERVICE_STOP` a 50 ms window and keeps 20 ms for
the drive's events, which differed by at most 9 ms here. Judged again with it, all 60 runs of the normal build pass;
the smallest margin of any paired entry to its window is 11 ms.

**Memory (`vm_hwm_kib`).**

| Build | Runs | Minimum | Median | Maximum | Spread | Std. dev. |
| --- | --- | --- | --- | --- | --- | --- |
| Normal | 60 | 5,644 | 5,834 | 5,944 | 300 | 62 |
| F-021 wrong fix | 10 | 6,608 | 6,796 | 6,872 | 264 | 69 |

- The wrong fix adds 664 to 1,228 KiB (its minimum less the normal maximum, its maximum less the normal minimum);
  the medians differ by 962 KiB.
- With a 6,400 KiB limit: no normal run would exceed it (largest 5,944, 456 KiB under); every wrong-fix run would
  (smallest 6,608, 208 KiB over). The limit of 8,192 KiB at the time passed all 70; it was lowered to 6,400 KiB
  after this measurement (CC1-PN §3).
- `threads_at_end` was 3 in every run.
