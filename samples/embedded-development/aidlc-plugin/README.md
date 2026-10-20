# AI-DLC plugin: embedded development

An [AI-DLC 2.0 plugin](https://github.com/awslabs/aidlc-workflows/blob/main/docs/harness-engineering/10-authoring-a-plugin.md)
that adds embedded-specific behaviour to AI-DLC without changing the core framework.

Planned contents:

- `stages/`: a hardware-document ingestion stage for requirements and design, and validation stages
  for software-in-the-loop and hardware-in-the-loop runs;
- `contributions/`: additions to existing core stages, such as build and test steps for cross
  toolchains;
- `knowledge/`: methodology knowledge for the agents, such as working with HALs, registers and
  interrupt-safe code;
- `sensors/` and `tools/`: checks that enforce the action, physical and quality gates;
- `.aidlc-plugin/plugin.json`: the plugin manifest.
