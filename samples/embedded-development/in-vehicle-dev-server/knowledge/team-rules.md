# TR: team rules for `vstatd`

> Synthetic, written for the AI-DLC embedded sample. Cite as `[TR §<section>]`. These are the rules of the fictional
> platform team that owns `vstatd`; the agents follow them, and the checks enforce the ones that can be checked.

## §1 C++ rules

- **§1.1** C++17. No compiler extensions in product code.
- **§1.2** Ownership through RAII: no `new` or `delete` outside a smart pointer or container; file descriptors and
  sockets are owned by a class that closes them.
- **§1.3** No exceptions cross a thread boundary or the IPC boundary. Errors on the gateway and IPC sides are handled
  as in `[VSTATD-IF p.9 §6]`.
- **§1.4** Times use `std::chrono::steady_clock` (`[VSTATD-IF p.7 §4.5]`). No wall-clock time in supervision.
- **§1.5** Shared state between threads is protected by a mutex or is immutable after start-up
  (`[VSTATD-IF p.11 §8.4]`).
- **§1.6** Integer arithmetic follows `[VSTATD-IF p.6 §3.3]`. Narrowing conversions are explicit; widening conversions
  may be implicit.

## §2 Build

- **§2.1** Cross build with `-Wall -Wextra -Werror -O2 -fstack-protector-strong -D_FORTIFY_SOURCE=2` and the
  toolchain of `[CC1-PN §7]`.
- **§2.2** The unit tests run in two builds for the build server: one with `-fsanitize=thread` (ThreadSanitizer) and
  one with `-fsanitize=address,undefined`. The two cannot be combined in one build.

## §3 Static analysis

- **§3.1** cppcheck 2.13 with `--std=c++17 --library=posix --enable=warning,style,performance,portability
  --inline-suppr`, and clang-tidy 18 on the cross build's `compile_commands.json` with the checks `bugprone-*`,
  `cert-err33-c`, `cert-err34-c`, `cppcoreguidelines-init-variables`, `cppcoreguidelines-pro-type-member-init`,
  `clang-analyzer-*` and `performance-*`. `bugprone-unused-return-value` has its option `CheckedFunctions` set to the
  check's default list with `::fcntl;::sd_notify` appended. clang-tidy reports in the project's own headers too
  (header filter on `src/`); the settings are in `reference-project/.clang-tidy`.
- **§3.2** An inline suppression is allowed only for a finding whose justification was approved in triage, and it
  names the finding ID: `// cppcheck-suppress <check> ; F-nnn justified` or `// NOLINT(<check>) F-nnn justified`.

## §4 Triage of findings

- **§4.1** Each finding labelled `fix` in the backlog gets one decision: *fix*, *justify* or *defer*.
  - **Fix:** change the code and cite the finding. When the finding has an observable effect (crash, leak, wrong
    value, race), add a unit test that fails before the fix. When it has none (performance, style), the analyser run
    of `checks/static.sh` is the test, and the change says so.
  - **Justify:** the finding is a false positive or harmless; the justification cites the page and section of
    VSTATD-IF or CC1-PN that makes it so. The reviewer approves or overturns it.
  - **Defer:** a reason and the condition for picking it up again.
- **§4.2** No decision may change behaviour described in VSTATD-IF. If a fix would, it is deferred and a
  specification change is proposed instead.
- **§4.3** The triage list is approved before any code changes.
- **§4.4** A defect that a check finds during the batch and that is not in the backlog, such as a ThreadSanitizer
  report, is added with the next free ID (from F-031), the tool or check that found it, and label `fix`. It is
  triaged like the others.

## §5 Bounded repair

- **§5.1** An agent may retry a failing cross build at most 3 times and a failing log comparison at most 2 times for
  one unit of work. Then the unit stops and a person decides.
- **§5.2** The limits in use are recorded with each run.

## §6 Requirements that need the real target

- **§6.1** Requirements that the emulated CC-1 cannot show (`[CC1-PN §2.3]`) are marked *real-target only* in the
  triage. Their evidence from emulation is reported as blocked, not passed.
- **§6.2** The current batch has no real-target-only requirement.

## §7 Definition of done for a batch

- **§7.1** All checks pass on the final commit: build, static analysis, unit tests with the sanitizers of §2.2, size,
  trace, runtime limits and log comparison.
- **§7.2** Every change cites its finding; every behaviour-related change and every justification also cites a
  specification page.
- **§7.3** The release owner signs off from the evidence page.
- **§7.4** A check's verdict is its exit status and its log. An agent's summary of a run, or a count reported by a
  tool, is not a verdict; where they disagree, the evidence page shows both.
