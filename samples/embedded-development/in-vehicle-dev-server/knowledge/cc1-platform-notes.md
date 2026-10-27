# CC1-PN: CC-1 platform notes for `vstatd`

> Synthetic, written for the AI-DLC embedded sample. Cite as `[CC1-PN §<section>]`.

## §1 Target

- **§1.1 Hardware.** CC-1 is a fictional cockpit computer with a 64-bit Arm system-on-chip: four application cores,
  2 GiB of RAM shared by all cockpit software.
- **§1.2 Software.** Embedded Linux with systemd. `vstatd` runs as user `vstat`, group `vstat`, with the runtime
  directory `/run/vstatd`.

## §2 The emulated CC-1 in this sample

- **§2.1 Emulator.** QEMU system emulation of the `virt` machine with a 64-bit Arm CPU, four virtual CPUs and 512 MiB
  of guest RAM, booting a Linux image built with Buildroot by the bench scripts.
- **§2.2 Time.** Guest time runs on QEMU's instruction counter with a fixed shift and no real-time sleep
  (`-icount shift=<n>,sleep=off`, not `shift=auto`), so that timing on a replay is repeatable. The drive player runs
  inside the emulated CC-1 in place of `cc1-gwd`, paces its records by the guest's monotonic clock and starts the
  drive when `vstatd` connects. The replay's clients connect one at a time at fixed offsets after `SERVICE_READY`. The
  exact QEMU command line is recorded with each run.
- **§2.3 What emulation cannot show.** CPU load and timing on the real system-on-chip, cache and memory-bandwidth
  effects, and the real CAN controller. Results from the emulated CC-1 are labelled *emulation* on the evidence page.

## §3 Resource limits for `vstatd`

| Limit | Value | How it is checked |
| --- | --- | --- |
| Peak resident memory (RSS) during the recorded drive | 8 MiB | `checks/runtime-limits.sh` on the emulated CC-1 |
| Memory limit of the service unit (`MemoryMax`) | 12 MiB | Set in the unit file; exceeding it kills the service |
| Binary size, stripped | 1.5 MiB | `checks/size.sh` |
| Threads at the end of the replay | at most 4 | `checks/runtime-limits.sh` |
| CPU time | No absolute limit in emulation; reported relative to the baseline on the same emulator | Reported, not pass or fail |

The baseline figures of the current release are measured by the bench scripts on the same replay and kept with the
baseline log.

## §4 Start-up order

- **§4.1** `cc1-gwd.service` starts before `vstatd.service` (`After=cc1-gwd.service`). The gateway socket may still
  be missing when `vstatd` starts; `vstatd` handles this as in `[VSTATD-IF p.7 §4.4]`.
- **§4.2** `vstatd.service` is `Type=notify`: readiness is reported with `sd_notify("READY=1")` from libsystemd.
  `Restart=on-failure`, `RestartSec=1`.

## §5 Runtime log format

- **§5.1** `vstatd` writes its runtime log to standard output; the journal stores it. The bench scripts copy the log
  of a run to `run.jsonl` on the build server.
- **§5.2** One JSON object per line. Keys, in this order: `t_ms` (milliseconds of the monotonic clock since process
  start, integer), `ev` (event name of `[VSTATD-IF p.10 §7.1]`), then the event's fields in the order of that table.
- **§5.3** All field values except `t_ms` are JSON strings. Signal values use the formatting of
  `[VSTATD-IF p.8 §5.3]`; an absent value is `"-"`.
- **§5.4** Example:

```json
{"t_ms":412,"ev":"GATEWAY_CONNECTED"}
{"t_ms":831,"ev":"SIGNAL_VALUE","path":"Vehicle.Speed","value":"0.00","status":"AVAILABLE"}
```

## §6 Log comparison settings

`checks/logdiff.sh` compares the run's log with the baseline log of the same replay.

- **§6.1 Compared:** the sequence of entries, each with `ev` and all its fields.
- **§6.2 Ignored:** the `version` field of `SERVICE_START`.
- **§6.3 Matching:** two entries match when `ev` and every compared field are equal and their `t_ms` differ by at
  most 20 ms. The comparison takes the baseline entries in order and pairs each with the first unpaired run entry
  that matches it. Entries with the same baseline `t_ms` (one decoding step) shall also keep their order in the run.
  Every entry left unpaired on either side is a difference.
- **§6.4 Allowed differences:** only those listed in the approved triage, each with the finding it belongs to.

## §7 Toolchain and build

- **§7.1** Cross compiler `aarch64-linux-gnu-g++` (GCC 12), C++17, CMake with the toolchain file
  `cmake/cc1-aarch64.cmake`.
- **§7.2** The sysroot, produced by the same Buildroot build as the target image, provides glibc and the libsystemd
  headers (`<systemd/sd-daemon.h>`). These headers exist only in the sysroot.
- **§7.3** Unit tests are built for the build server itself (not cross-compiled) and use the test double
  `tests/stubs/systemd/sd-daemon.h` in place of libsystemd.

## §8 Bench states and runs

- **§8.1 Physical preconditions.** The bench refuses an action outside these states:

| Action | Supply voltage | Ignition (KL15) |
| --- | --- | --- |
| Deploy a build | 11.0 to 14.8 V | on |
| Restart `vstatd` | 11.0 to 14.8 V | on |
| Start the drive replay | 11.0 to 14.8 V | on |
| Stop `vstatd` | any | any |
| Reads (supply, ignition, logs, memory figures) | any | any |

- **§8.2 Ignition is the bench's.** KL15 is the simulated supply's ignition output. The replayed
  `Vehicle.LowVoltageSystemState` is recorded data and does not change it.
- **§8.3 Known state.** Before each run the bench returns to a known state: `vstatd` stopped, `/run/vstatd` empty, the
  last approved build installed. Any other change a run makes to the bench is recorded with how to undo it, and undone
  at the end of the run.
- **§8.4 Digest read-back.** After a deploy the bench reads back the SHA-256 of the installed `vstatd` and compares it
  with the approved digest. A mismatch stops the run.
- **§8.5 Results after the end.** The checks that run after a deploy judge a run only once it has ended: when the
  drive replay has finished, the bench reads `vstatd`'s peak memory (`VmHWM`) and thread count, stops `vstatd`, and
  then collects the log up to `SERVICE_STOP`. `checks/runtime-limits.sh` and `checks/logdiff.sh` read only these
  results. Figures taken while the replay was still running are discarded and marked as such. The exit status of the
  script that started the replay does not count as its end.
