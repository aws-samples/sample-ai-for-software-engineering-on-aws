# Checks: embedded development

Checks the team issues and the agents cannot change. The workflow runs them, not the agents, and sends each failure
back to the agent that owns the failing part.

Planned checks:

| Check | Passes when |
| --- | --- |
| Build | The firmware builds with the cross toolchain, with warnings treated as errors |
| Coding rules | The code follows the rules in the team's coding standard, for example no dynamic allocation and no unbounded loops in interrupt handlers |
| Memory budget | The image fits the flash and RAM budget of the target |
| Unit tests | The host unit tests pass |
| Simulation tests | The image boots on the emulated target and its console output matches each acceptance criterion |
| Evidence | The run recorded its build log, test reports and image checksum |

An image goes to hardware only when every check passes in simulation.
