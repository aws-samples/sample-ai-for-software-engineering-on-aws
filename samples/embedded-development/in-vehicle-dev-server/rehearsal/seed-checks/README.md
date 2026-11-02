# Seed checks

> For facilitators and the people building items 3 and 4. **Not part of the agents' workspace**, like the rest of
> `rehearsal/`.

`run.sh` shows, on the build server, that each seeded difficulty of the reference project is real and what its
"wrong fix" does, and that the analysers still reproduce the backlog. It copies `reference-project/` into `$OUT`,
builds the variants it needs, prints one table and removes the build trees again, keeping the logs. Run it in the
build environment of `reference-project/tools/Dockerfile`, with the sysroot mounted and `$OUT` on a host directory so
that the logs outlive the container:

```bash
mkdir -p /tmp/seed-checks                                   # from samples/embedded-development/in-vehicle-dev-server
docker run --rm --security-opt seccomp=unconfined -v "$PWD":/sample:ro -v /opt/cc1-sysroot:/opt/cc1-sysroot:ro \
  -e OUT=/out -v /tmp/seed-checks:/out -w /sample vstatd-build rehearsal/seed-checks/run.sh
```

`seccomp=unconfined` is for `setarch -R`, which ThreadSanitizer needs on kernels with high address-space
randomisation. The script exits non-zero when a seed does not behave as described. Run it on an otherwise idle
machine: `replay.py` plays the records in real time, and `VCU_Speed` times out after 60 ms, so a heavily loaded host
can produce timeouts the seeds do not explain.

| Seed (facilitator notes) | What `run.sh` does | Expected |
| --- | --- | --- |
| Cross build fails on a target-only header | Cross build with `cmake/cc1-aarch64.cmake` as committed, then with `-DCMAKE_SYSROOT` | Fails on `<systemd/sd-daemon.h>`; builds with the sysroot |
| Data race on the signal table | Baseline unit tests under ThreadSanitizer (`halt_on_error=0 exitcode=0`, so the exit status is the tests') | Tests pass; ThreadSanitizer reports the race in `SignalTable::get` (`GET` while decoding), and nothing else |
| F-011 | Baseline unit tests under AddressSanitizer and UBSan (`UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1`; any `runtime error:` fails), then `miss_lookup.cpp`: one lookup of a path that is not published (the `E02` case) | Tests pass; the miss reads past `entries_` (`heap-buffer-overflow` in `SignalTable::find`) |
| F-008, the fix that changes a timeout | Host builds of the baseline and of the baseline with `entry.supervised &&` removed from `Supervisor::check`; `replay.py --scenario drive`: first frames 200 ms after the connection | Baseline: no `SIGNAL_TIMEOUT`; wrong fix: `SIGNAL_TIMEOUT` and `SIGNAL_RECOVERED` for `VCU_Speed` and `VCU_Gear` |
| F-021, the correct fix that breaks the memory limit | Host builds of the baseline and of `lines_{}`; `replay.py` with 16 clients that subscribe to 4 signals each | `VmHWM` grows by about 0.9–1.0 MiB on the host: 16 × 64 KiB, less the pages of each queue the baseline already touches (about one 4 KiB page per client), with run-to-run noise |
| The backlog | `reference-project/tools/run-analysers.sh` on the cross build, then `match-backlog.py` | `30 findings, 30 backlog rows, 0 problem(s)` |

`replay.py` is a tiny stand-in for the gateway, for these checks only; the bench's drive player is build plan
item 3. Its `demo` scenario adds a speed timeout and recovery, an out-of-range speed, a bad record, a short frame, a
gateway loss and reconnection, and an app that sends `GET`, `LIST` and erroneous requests.

## Last run

2026-10-27, on the commit that adds this section (parent `f018eac` on `embedded/in-vehicle-reference`), three runs in a
row. Build server: the container of `reference-project/tools/Dockerfile` (`ubuntu:24.04` at
`sha256:24737cef17f4e22b1977df7d9a05e77c4e28b7da5b8911f8d8ccda136bf3573c`, Ubuntu 24.04.5; GCC 12.4.0-2ubuntu1~24.04.1,
cppcheck 2.13.0, clang-tidy 18.1.3) with the stand-in sysroot, on an 8-vCPU x86_64 host that was not idle (load
average 7–9). Memory figures are **host** figures of the host build, not CC-1 figures; the bench measures the target.
All three runs passed with the same results except the memory figures:

| Seed | Result | Evidence |
| --- | --- | --- |
| Cross build, target-only header | PASS | without sysroot: fails on `<systemd/sd-daemon.h>`; with the stand-in sysroot: builds |
| Data race | PASS | tests pass (exit status 0); ThreadSanitizer: 1 race report, `signal_table.cpp` in `vstatd::SignalTable::get(unsigned long) const`, nothing else |
| F-011 | PASS | baseline tests pass under ASan+UBSan, no `runtime error:`; the miss lookup: `heap-buffer-overflow` in `SignalTable::find` |
| F-008 | PASS | baseline: 0 `SIGNAL_TIMEOUT`, 0 `SIGNAL_RECOVERED`; condition removed: 2 and 2 (`VCU_Speed`, `VCU_Gear`) |
| F-021 | PASS | host `VmHWM` with 16 clients, baseline → `lines_{}`: 4112 → 5076 KiB (+964), 4104 → 4996 KiB (+892), 3996 → 5040 KiB (+1044); range +892 to +1044 KiB |
| The backlog | PASS | `30 findings, 30 backlog rows, 0 problem(s)` |

## Notes for later items

- The analysers' messages differ from the first draft of the backlog in punctuation and type names; the backlog now
  has the real text. F-014 is in `IpcServer::open_listener` (`listen_fd`), because cppcheck's POSIX library
  models `socket()` as a resource and `accept()` not.
- `reference-project/tools/match-backlog.py` is the mapping that `checks/static.sh` (item 4) can reuse.
- The baseline unit tests do not test the start-up grace period, peak memory or a lookup miss, so that only the
  log comparison, the runtime limits and the sanitizers catch the seeds.
