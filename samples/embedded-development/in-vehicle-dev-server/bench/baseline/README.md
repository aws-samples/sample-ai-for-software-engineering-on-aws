# The final baseline

The baseline log of the current release on the recorded drive, for `checks/logdiff.sh` and `checks/runtime-limits.sh`
(build plan item 3). The team file of the Kiro Crew app uses it by default (`bench.baseline` is
`${sample}/bench/baseline`). Record one of your own only when the correct release does not pass `logdiff` against it
on your machine ([bench/README.md](../README.md)), and point `bench.baseline` at that folder.

- `baseline.jsonl`: the runtime log of `vstatd` on the replay, 328 entries.
- `baseline-result.json`: the run's figures and the bench's facts (the run directory format of
  [checks/README.md](../../checks/README.md#run-and-baseline-directories)).

## What was recorded

- **Source:** `reference-project/` at upstream `main` commit `062a121ca58bc7db3a5ac9c39477ade80a598a4f`, plus the F-031
  line in `cmake/cc1-aarch64.cmake`, `set(CMAKE_SYSROOT /opt/cc1-sysroot)`, as `rehearsal/check-examples/run.py` adds
  it.
- **Build:** as `checks/build.sh` does it: `cmake -G Ninja -DCMAKE_TOOLCHAIN_FILE=cmake/cc1-aarch64.cmake`,
  `ninja vstatd`, `aarch64-linux-gnu-strip`, against the Buildroot sysroot of the volume `cc1-sysroot`.
- **Build image:** `vstatd-build:arm64`, image
  `sha256:e219317340ee2c70f3429e17822c9b281207403f40cbd93219c00374734f1c5c`, with GCC 12.4.0
  (`aarch64-linux-gnu-g++`) and cmake 3.28.3.
- **Build digest:** `c95309f5d8aad3b686d23c39ea190c84da47cbc4d0f555525bdfaae667b687ff`, 133,240 bytes stripped.
- **Drive:** `drive-01.rec`, SHA-256 `39a3d0dec2abe53be91fef2664a43f927be23528c4ee038f83d62fb968e46503`; the client
  parameters' hash is `62abaaf5`, so `replay_id` is `drive-01@39a3d0dec2ab+62abaaf5`.
- **Recorded:** 2026-11-18, on an Apple Silicon Mac (macOS, Docker Desktop 29.2.0), QEMU 8.2.2 in the bench runner,
  `-icount shift=3,sleep=off` (`bench/cc1.sh start --shift 3`, a fresh boot before the deploy).

In `baseline-result.json`, `approved_digest` and `readback_digest` are both the build digest, `replay_finished` and
`figures_after_replay_end` are true and `vstatd_restarts` is 0.

The deploy and the replay were each approved by a person through the bench's `decide()`, with the digest prefix
typed: the deploy `20261118T223509-deploy-ec51` on the Kiro Crew board, the replay `20261118T223657-replay-fcd8` at
the operator console (`bench/console.py`).

## Two digests of the same source

The build digest depends on the build image's architecture:

- `c95309f5…` from `vstatd-build:arm64` on Apple Silicon, where the host `g++-12` and binutils target
  `aarch64-linux-gnu`: the build above.
- `bc93723c0cb02e054acc5f25705b61a4443435c168351ec5914d0729bdce4d98` from `vstatd-build:amd64`, with the cross
  compiler of Ubuntu's packages: the same source and the same commands. The x86_64 baseline in
  [rehearsal/check-examples/bench-data/baseline/](../../rehearsal/check-examples/bench-data/baseline/) and the normal
  build of [rehearsal/repeatability/](../../rehearsal/repeatability/README.md) are this build.

Both are GCC 12.4.0 and 133,240 bytes. They differ only in bytes 0x264 to 0x110b near the start of the file, the build
ID and the dynamic linking tables. A person approving a deploy sees the digest of the image their machine builds with.

## Checked against it

- Three more replays of the same build on the same boot (`--kind run`, each approved at the operator console:
  `20261118T223911-replay-4435`, `20261118T224105-replay-0377`, `20261118T224528-replay-d21b`), judged against this
  baseline with the approved triage of `rehearsal/repeatability/`, which allows no log difference: `logdiff.sh` and
  `runtime-limits.sh` 6 of 6 PASS. Each run paired 328 of 328 entries; peak RSS 5,808 to 5,944 KiB (baseline 5,824,
  limit 6,400).
- The 70 replays of `rehearsal/repeatability/` (2026-11-04, the same Mac: 60 of the normal build `bc93723c…` and 10 of
  the F-021 wrong fix, a memory defect that `logdiff` does not look for): `logdiff.sh` 70 of 70 PASS against this
  baseline.
- Across hosts: the same 70 Mac replays against the x86_64 baseline of `rehearsal/check-examples/bench-data/baseline/`
  (2026-11-16) are 70 of 70 PASS as well.
