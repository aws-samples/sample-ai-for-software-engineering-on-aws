# First delivery of the Kiro Crew app: audit trail and evidence page

For facilitators, not for the agents' workspace: these records show how the seeded difficulties were found and
fixed.

Run `r11032637` of the [Kiro Crew app](../../app/README.md), 2026-11-03, on an Apple Silicon Mac. It went from the
triage gate to a signed-off evidence page. What the run showed, and the app fixes made during it, are in
[docs/kiro-crew-app.md](../../docs/kiro-crew-app.md#seen-in-the-first-delivery). The measured cost is in the scenario
README's [Cost](../../README.md#cost) section. The peak-RSS limit was 8,192 KiB at the time; it is 6,400 KiB since
2026-11-04 (CC1-PN §3), and this run's 5,896 KiB is within both.

| File | What it is |
| --- | --- |
| [`audit.md`](audit.md) | The audit trail as the app writes it at sign-off (D14): every action by a person, an agent, the app and the bench, step by step, with its evidence (commit, finding IDs, digest, triage hash) |
| [`audit.json`](audit.json) | The same entries as data |
| [`evidence.md`](evidence.md) | The evidence page of the independent rerun, written by `checks/evidence-page.sh`; `release.sh` PASS |

What to look for:

- **The gates.** The person approved the triage at its gate (all A) and approved build start.
- **The two seeded difficulties.** The cross build fails on `<systemd/sd-daemon.h>` until the toolchain file sets
  `CMAKE_SYSROOT`. ThreadSanitizer reports the race in `SignalTable::get`. Both stop the run for a person, are
  registered under TR §4.4 (F-032 to F-035) and are handed to the developer with the files it may write.
- **The review.** The reviewer asked for the citations of F-028's justification. The person decided on an empty
  commit, so that no merged history was rewritten.
- **The bench.** The person approved deploy and replay on the board. The record shows the physical gate, the digest
  that was installed and read back, the replay and the after-bench checks.
- **The rerun and sign-off.** The first rerun's `release.sh` failed because its container could not see the
  baseline, an app defect that was fixed during the run. The second rerun passed, and the person signed off.

## How these copies differ from the run's own files

They are redacted copies. The originals are in the run's `results/` directory on the machine that ran it, and the
sign-off record holds their SHA-256: `daaf3fbebb6c…` (`audit.md`) and `d92f2afaddf7…` (`audit.json`). The changes
are text replacements only:

- the scenario folder became `<sample>` (`<sample>…` where the app had already cut the path short);
- the home directory became `~`;
- the person's login name became 负责人 (the person in charge), the name the app uses when nobody is named.

Nothing else was changed. The evidence page needed no change.
