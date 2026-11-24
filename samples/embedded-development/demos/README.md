# Demos: the embedded samples running

Three short recordings of the embedded samples on their synthetic data. Each has burned-in English captions, an
[`.srt` file](captions/) beside it and a synthetic narration (Amazon Polly). Waits are shortened by speeding up or
cutting; nothing is reordered or staged. No people and no customer data appear in them.

| Recording | What it shows | Length |
| --- | --- | --- |
| [The `hw` plugin in Kiro CLI](#the-hw-plugin-in-kiro-cli) | A real `/aidlc` run with the [`hw` plugin](../aidlc-plugin/hw/), up to its first hardware approval gate | 1:46 |
| [One delivery on the Kiro Crew board](#one-delivery-on-the-kiro-crew-board) | The [in-vehicle app](../in-vehicle-dev-server/README.md#the-kiro-crew-app) from the triage gate to sign-off | 1:25 |
| [The build server's guardrails](#the-build-servers-guardrails) | The [`build` MCP server](../in-vehicle-dev-server/mcp/build/README.md) refusing, bounding repairs and handing over to a person | 1:03 |

## The hw plugin in Kiro CLI

[![The hw plugin in Kiro CLI](images/hw-plugin-in-kiro-cli.jpg)](VIDEO_HW_PLUGIN)

VIDEO_HW_PLUGIN

Kiro CLI 2.34.0 runs AI-DLC Workflows 2.11.2 as shipped, with the `hw` plugin, on the in-vehicle scenario's
reference project. It shows the plugin's step in Requirements Analysis, a reviewer's gaps answered by a person, and the
plugin's Hardware Verification Planning stage, where every requirement gets an evidence tier and the check that judges
it. The run stops at that stage's approval gate, which was not approved. Recorded 2026-11-05: 78 minutes and
88.73 credits, shortened to under two minutes. Construction and Operation have not run with the plugin.

## One delivery on the Kiro Crew board

[![One delivery on the Kiro Crew board](images/board-delivery-replay.jpg)](VIDEO_BOARD)

VIDEO_BOARD

A replay of run `r11032637` (2026-11-03, a Mac with Apple Silicon) on the board of the
[in-vehicle Kiro Crew app](../in-vehicle-dev-server/README.md#the-kiro-crew-app): six AI roles, people only at the
gates and the operator console, the checks sending failures back to the role that owns them, the bench, the independent
rerun and the release owner's sign-off. The board is in presentation mode, so people are shown by role. The agents'
notes are in Chinese. The 3:38 screen recording is cut to 1:25 by speed changes and holds only. Two things differ from
the sample today: the memory limit on the screen is the 8,192 KiB of that day, later set to 6,400 KiB from 70 replays
([facilitator notes](../in-vehicle-dev-server/rehearsal/facilitator-notes.md)), and the scorecard's top row adds two
runs (the per-run row is this delivery). The figures of this run are in the scenario's
[Cost](../in-vehicle-dev-server/README.md#cost).

## The build server's guardrails

[![The build server's guardrails](images/build-server-guardrails.jpg)](VIDEO_BUILD_SERVER)

VIDEO_BUILD_SERVER

[`rehearsal/build-server-run/run.py`](../in-vehicle-dev-server/rehearsal/build-server-run/README.md) on an Ubuntu
build host: a script plays the agent, calling the `build` MCP server's tools, and the people. Calls outside the agent's
grant are refused, wrong repairs of the cross build count until the server refuses the next attempt, a person resets
the count, ThreadSanitizer finds the seeded data race, and the release check fails with its reasons because there are
no bench results in this walk. 35 of 35 rows as expected; the real run took about six minutes.
