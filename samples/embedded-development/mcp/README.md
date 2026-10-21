# Tool connectors: embedded development

MCP servers that let the agent use the team's embedded toolchain, each with the guardrails described
in the [sample README](../README.md#gates-and-guardrails).

Planned connectors:

| Connector | Purpose |
| --- | --- |
| Build | Run the cross toolchain and return compiler diagnostics |
| Simulator | Start, drive and inspect a QEMU target |
| Flash and debug | OpenOCD, GDB and similar tools, behind the action gate |
| Serial console | Read logs and send commands over UART, SSH or AWS Systems Manager |
| Bench | Hardware-in-the-loop operations, behind the action and physical gates |
