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

27 of 27 as expected; results in /out/results
