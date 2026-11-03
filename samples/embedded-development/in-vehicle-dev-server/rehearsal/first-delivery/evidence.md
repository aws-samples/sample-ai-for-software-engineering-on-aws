# Evidence page: vstatd: 待办 fix 发现 + 拆分 Service::run() 信号解码

- Commit: `f6014f0e3f1c6b0f17a9e54f01c2aafbd5438426`
- Build (SHA-256 of the stripped `vstatd`): `4cbb3cb4b7ad43e99a1d44d2a0fce4eefb3b01061ab7a38a27455548c3050f37`
- Triage: base `240596ff377f`, approved by 负责人 on 2026-11-03T06:20:33Z
- Release check: **PASS**

| Check | Verdict | Evidence tier | Result |
| --- | --- | --- | --- |
| `build` | **PASS** | n/a | vstatd sha256 4cbb3cb4b7ad43e99a1d44d2a0fce4eefb3b01061ab7a38a27455548c3050f37 |
| `static` | **PASS** | n/a | 9 findings, all in the backlog and consistent with the triage |
| `unit` | **PASS** | unit test | plain: 53 tests, tsan: 53 tests, asan: 53 tests |
| `size` | **PASS** | n/a | 133240 of 1572864 bytes (8 %) |
| `trace` | **PASS** | n/a | 22 commit(s), 26 finding(s) traced |
| `runtime-limits` | **PASS** | emulation | peak RSS 5896 of 8192 KiB (baseline 5860), 3 threads, CPU x1.008 of baseline; emulation |
| `logdiff` | **PASS** | emulation | 328 of 328 baseline entries paired; 0 unexplained difference(s), 0 allowed, 0 order change(s); emulation |
| `release` | **PASS** | n/a | every check passed on f6014f0e3f1c; vstatd 4cbb3cb4b7ad |

## Findings of the batch

22 fixed, 4 justified, 1 deferred.

| Finding | Decision | Cites | Static analysis now |
| --- | --- | --- | --- |
| F-001 | fix |  | gone |
| F-002 | fix |  | gone |
| F-003 | fix |  | gone |
| F-004 | fix |  | gone |
| F-005 | fix |  | gone |
| F-006 | fix |  | gone |
| F-007 | justify | [VSTATD-IF p.6 §3.3], DEC-INTEGER-PRODUCT | gone |
| F-008 | justify | [VSTATD-IF p.7 §4.2], SUP-GRACE | gone |
| F-010 | fix |  | gone |
| F-011 | fix | [VSTATD-IF p.9 §6.1], ERR-CODES | gone |
| F-012 | fix |  | gone |
| F-013 | fix |  | gone |
| F-014 | fix |  | gone |
| F-015 | fix |  | gone |
| F-016 | fix | [VSTATD-IF p.8 §5.2], [VSTATD-IF p.9 §6.1], IPC-REQUESTS, ERR-CODES | gone |
| F-017 | fix | [VSTATD-IF p.9 §6.1], ERR-CODES | gone |
| F-018 | fix | [VSTATD-IF p.8 §5.2], [VSTATD-IF p.9 §6.1], IPC-REQUESTS, ERR-CODES | gone |
| F-021 | justify | [VSTATD-IF p.8 §5.4], [CC1-PN §3], IPC-LIMITS | gone |
| F-023 | fix |  | gone |
| F-025 | defer | 这个 catch 吞掉解码一步里的所有 std::exception。去掉它，异常会跑出网关线程，违反 TR §1.3；改成记录日志，需要 VSTATD-IF §7.1 里没有的事件，会改变运行日志；bad_alloc 按 §6.4 应记 SERVICE_STOP（out_of_memory）并以非零状态退出，要改 main 和线程之间的协作。三种修法都超出本批的范围，需要先改规范。 | reported |
| F-027 | fix |  | gone |
| F-028 | justify | [VSTATD-IF p.9 §6.4], [VSTATD-IF p.11 §8.1], [CC1-PN §4.2] | gone |
| F-031 | fix |  | added under TR §4.4 (found by 工作项：拆分 Service::run()) |
| F-032 | fix |  | added under TR §4.4 (found by checks/build.sh) |
| F-033 | fix |  | added under TR §4.4 (found by checks/build.sh) |
| F-034 | fix |  | added under TR §4.4 (found by checks/build.sh) |
| F-035 | fix |  | added under TR §4.4 (found by checks/unit.sh) |

## Log comparison

328 of 328 baseline entries paired within 20 ms; 0 unexplained difference(s); 0 allowed.


## Runtime figures

Peak RSS 5896 KiB (limit 8192, baseline 5860); 3 threads at the end (limit 4); CPU time x1.008 of the baseline, reported only. Tier: emulation.

## What emulation cannot show

CPU load and timing on the real system-on-chip, cache and memory-bandwidth effects, and the real CAN controller. Results from the emulated CC-1 are labelled *emulation* on the evidence page.

## Bounded repair

Rounds used: `{"rounds": {"build": 6, "unit": 4, "trace": 1}, "limits": {"build": 3, "static": 2, "unit": 2, "size": 2, "trace": 2, "runtime-limits": 2, "logdiff": 2, "release": 2}, "granted": {"build": 4, "unit": 2}}`; limits `{"cross_build": 3, "log_comparison": 2}` (TR §5.1).

## Sign-off

Release owner: ____________________  Date: ____________

Decision: ☐ sign off  ☐ return to the batch
