# Seed checks

> For facilitators and the people building items 3 and 4. **Not part of the agents' workspace**, like the rest of
> `rehearsal/`.

`run.sh` shows, on the build server, that each seeded difficulty of the reference project is real and what its
"wrong fix" does. It copies `reference-project/` into a temporary directory, builds the variants it needs and prints
one table. Run it in the build environment of `reference-project/tools/Dockerfile`, with the sysroot mounted:

```bash
docker run --rm --security-opt seccomp=unconfined -v "$PWD":/sample -v /opt/cc1-sysroot:/opt/cc1-sysroot:ro \
  -w /sample vstatd-build rehearsal/seed-checks/run.sh      # from samples/embedded-development/in-vehicle-dev-server
```

`seccomp=unconfined` is for `setarch -R`, which ThreadSanitizer needs on kernels with high address-space
randomisation. The script exits non-zero when a seed does not behave as described.

| Seed (facilitator notes) | What `run.sh` does | Expected |
| --- | --- | --- |
| Cross build fails on a target-only header | Cross build with `cmake/cc1-aarch64.cmake` as committed, then with `-DCMAKE_SYSROOT` | Fails on `<systemd/sd-daemon.h>`; builds with the sysroot |
| Data race on the signal table | Baseline unit tests under ThreadSanitizer | Tests pass; ThreadSanitizer reports the race in `SignalTable::get` (`GET` while decoding) |
| F-011 | Baseline unit tests under AddressSanitizer and UBSan, then `miss_lookup.cpp`: one lookup of a path that is not published (the `E02` case) | Tests pass; the miss reads past `entries_` (`heap-buffer-overflow` in `SignalTable::find`) |
| F-008, the fix that changes a timeout | Host builds of the baseline and of the baseline with `entry.supervised &&` removed from `Supervisor::check`; `replay.py --scenario drive`: first frames 200 ms after the connection | Baseline: no `SIGNAL_TIMEOUT`; wrong fix: `SIGNAL_TIMEOUT` and `SIGNAL_RECOVERED` for `VCU_Speed` and `VCU_Gear` |
| F-021, the correct fix that breaks the memory limit | Host builds of the baseline and of `lines_{}`; `replay.py` with 16 clients that subscribe to 4 signals each | `VmHWM` grows by about 1 MiB (16 × 64 KiB) |

`replay.py` is a tiny stand-in for the gateway, for these checks only; the bench's drive player is build plan
item 3. Its `demo` scenario adds a speed timeout and recovery, an out-of-range speed, a bad record, a short frame, a
gateway loss and reconnection, and an app that sends `GET`, `LIST` and erroneous requests.

## Last run

Build server: Ubuntu 24.04 container, GCC 12.4, on an x86_64 host. Memory figures are **host** figures of the
host build, not CC-1 figures; the bench (item 3) measures the target.

| Seed | Result | Evidence |
| --- | --- | --- |
| Cross build, target-only header | PASS | without sysroot: fails on `<systemd/sd-daemon.h>`; with the stand-in sysroot: builds |
| Data race | PASS | tests pass; ThreadSanitizer: 1 race report, `signal_table.cpp` in `vstatd::SignalTable::get(unsigned long) const` |
| F-011 | PASS | baseline tests pass under ASan+UBSan; the miss lookup: `heap-buffer-overflow` in `SignalTable::find` |
| F-008 | PASS | baseline: 0 `SIGNAL_TIMEOUT`, 0 `SIGNAL_RECOVERED`; condition removed: 2 and 2 (`VCU_Speed`, `VCU_Gear`) |
| F-021 | PASS | host `VmHWM` with 16 clients: 4120 KiB; with `lines_{}`: 4984 KiB (+864 KiB) |

## Notes for later items

- The analysers' messages differ from the first draft of the backlog in punctuation and type names; the backlog now
  has the real text. F-014 is in `IpcServer::open_listener` (`listen_fd`), because cppcheck's POSIX library
  models `socket()` as a resource and `accept()` not.
- `reference-project/tools/match-backlog.py` is the mapping that `checks/static.sh` (item 4) can reuse.
- The baseline unit tests do not test the start-up grace period, peak memory or a lookup miss, so that only the
  log comparison, the runtime limits and the sanitizers catch the seeds.
