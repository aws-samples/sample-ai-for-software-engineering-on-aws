# Facilitator notes: the seeded difficulties

> For facilitators and for the people building items 2 to 4 of the build plan. **Not part of the agents'
> workspace:** `setup.sh` (build plan item 6) copies only `knowledge/` and `reference-project/` into it, so neither
> this page nor the scenario page is there, and the agent configurations do not load them. If agents can read this
> page, the rehearsal measures nothing.

The scenario page lists four seeded difficulties and a seeded data race, each meant to be caught by a check rather
than by luck. This page ties each one to the knowledge (item 1), and says what the reference project (item 2), the
bench (item 3) and the checks (item 4) must do so that it works.

| Seed | Where it starts | What the agents should do | What catches a wrong answer | Needed from later items |
| --- | --- | --- | --- | --- |
| A fix that changes a timeout | F-008, `knownConditionTrueFalse` on `entry.supervised` in `Supervisor::check`. The condition is how the start-up grace period of `[VSTATD-IF p.7 §4.2]` is implemented; the analyser cannot see where it changes | Justify the finding citing §4.2, or fix it without changing when supervision starts | Removing the condition starts supervision at `GATEWAY_CONNECTED`. On the recorded drive the log then gains at least one `SIGNAL_TIMEOUT` and `SIGNAL_RECOVERED` pair that the baseline does not have: `checks/logdiff.sh` | Item 2: the flag is set from a callback the analyser does not follow, and a message's last-receive time starts at the start of its supervision. Item 3: every message's first frame comes between 100 ms and 1.5 s after the gateway connects, so the baseline has no `SIGNAL_TIMEOUT` at start-up, while `VCU_Speed` (timeout 60 ms) and `VCU_Gear` (150 ms) would time out without the grace period |
| A false positive the specification explains | F-007, implicit widening of a `uint32_t` product in `scale_unsigned` | Justify citing `[VSTATD-IF p.6 §3.3]` (raw ≤ 24 bits, product < 2³²) with an inline suppression naming F-007 | Widening to 64 bits is not wrong, but it is a change and a test for nothing. The scorecard counts unnecessary fixes and overturned justifications | Item 2: the code computes exactly as §3.3 says, and assigns the `uint32_t` product to a `uint64_t` so that the check fires |
| A correct fix that breaks the memory limit | F-021, `cppcoreguidelines-pro-type-member-init` on `lines_` in `ClientSession` | Justify `lines_` as written before read (the bookkeeping that says which lines are valid is already initialised), citing `[CC1-PN §3]`; or defer | Value-initialising `lines_` (`lines_{}`) writes 64 KiB per client, so its pages become resident. With the replay's 16 clients that adds 1 MiB and peak RSS passes 8 MiB `[CC1-PN §3]`: `checks/runtime-limits.sh` | Item 2: `ClientSession` has a user-provided constructor and holds `std::array<std::array<char, 256>, 256> lines_`; the baseline's peak RSS with 16 clients sits about 0.5 MiB under the limit. Item 3: the replay connects 16 clients with subscriptions |
| A cross build that fails on a target-only header | `<systemd/sd-daemon.h>` exists only in the sysroot `[CC1-PN §7.2]` | Repair the toolchain file within the bounds of `[TR §5.1]`, or stop and hand back | `checks/build.sh`; the repair-round count on the scorecard | Item 2: `cmake/cc1-aarch64.cmake` does not set `CMAKE_SYSROOT` at first, so the cross compiler cannot find the header. The repair is the sysroot, not the stub path of `[CC1-PN §7.3]` |
| A data race the analysers miss | Shared signal table between the decoding and IPC threads `[VSTATD-IF p.11 §8.4]`; not in the backlog | Add it as F-031 under `[TR §4.4]` and fix it once ThreadSanitizer reports it | `checks/unit.sh` with ThreadSanitizer | Item 2: a unit test exercises decoding and `GET` at the same time |

Notes for item 2:

- [seed-checks/](seed-checks/) shows each seed and its wrong fix on the build server (`run.sh`), with the results of
  the last run. Memory figures there are host figures.

- F-011 is simply a bug: an off-by-one in `SignalTable::find` that reads past the table only when a path is not
  found. A unit test that looks up a path not in the table (the `E02` case of `[VSTATD-IF p.9 §6.1]`) under
  AddressSanitizer shows it `[TR §2.2]`.
- `char` is unsigned on 64-bit Arm Linux, so F-006 fires only if the code says `signed char` explicitly.
- No seeded finding may also be reported by GCC 12 with the flags of `[TR §2.1]`, or the current release does not
  build. Check F-010 and F-021 against `-Wmaybe-uninitialized` in particular.
