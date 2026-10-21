# AI for Software Engineering on AWS: AI-DLC Samples

Teams that already use AI coding assistants usually reach the same next question: how do we run the
AI-Driven Development Life Cycle (AI-DLC) on our own toolchain, against our own definition of done,
through our own release process? This repository answers that question one engineering domain at a
time.

Each sample takes a feature from requirement to a validated release on a realistic toolchain, using
[AI-DLC Workflows 2.0](https://github.com/awslabs/aidlc-workflows) with [Kiro](https://kiro.dev). It
packages what a team needs to repeat the work on its own code: an AI-DLC plugin for the domain, Kiro
steering rules, tool connectors (MCP servers) with guardrails, a small reference project, and a guide
for a one-day guided rehearsal.

> [!IMPORTANT]
> **Maturity: early development.** The samples are for learning and evaluation. They are not
> production ready. Review every generated change, and keep human approval on any action that
> touches hardware, production systems or customer data. Generative AI can make mistakes; see the
> [AWS Responsible AI Policy](https://aws.amazon.com/ai/responsible-ai/policy/).

## Samples

| Sample | Scenario | Toolchain highlights | Status |
| --- | --- | --- | --- |
| [AI-DLC agent team on Kiro Crew](samples/agent-team-on-kiro-crew/) | A team of AI-DLC expert agents takes a web feature from a one-sentence requirement through human gates, company checks and an independent review to a local deployment and a sign-off | Kiro Crew app (Python backend, React board), git worktrees, Node.js test runner, Kiro Crew knowledge base | Available |
| [Embedded development](samples/embedded-development/) | Firmware and controller software in C and C++, including model-based design, validated in simulation and on hardware before an engineer signs off the release | Cross-compilers on a shared Linux build server, QEMU, OpenOCD and GDB, serial console, hardware-in-the-loop bench | In development |
| [Enterprise application and data](samples/enterprise-application-and-data/) | Making legacy services, ERP, finance and supply-chain systems and their data usable by agents | OpenAPI specifications, row- and column-level access control, governed MCP servers | Planned |
| [Mobile app development, iOS first](samples/mobile-app-development/) | Swift and Kotlin apps on release trains, where the definition of done includes app store review and regulatory rules | Amazon EC2 Mac instances, AWS Device Farm | Planned |

## Sample overview: AI-DLC agent team on Kiro Crew

[`samples/agent-team-on-kiro-crew/`](samples/agent-team-on-kiro-crew/) is the first sample you can install and run.
It turns a one-sentence requirement into a delivery by a team of AI-DLC expert agents, and shows what that changes
for an organization rather than for one engineer.

- **What it shows.** Each delivery leaves a record of elapsed time, agent work versus time waiting for a person,
  credits, checks passed and what was sent back. In the measured runs in its README, a promotion feature built by
  8 agents went from requirement to local deployment in 13 to 20 minutes, of which the agents needed about 7 to 10;
  the rest was a person deciding at the gates. Every change passed all 40 checks, 28 of them issued by the company,
  before a person approved the release.
- **How it works.** An orchestrator follows the AI-DLC phases: scope and the questions that need a decision, a
  build-start gate, parallel construction on separate git branches, company-issued checks the agents cannot change,
  failures routed back to their owners, an independent review, a release gate and a sign-off. Each role runs as one
  of the 14 AI-DLC expert agents, using its official definition. Teams are JSON files, so the orchestrator is not tied
  to the example it ships with.
- **Why Kiro Crew.** The sample is a Kiro Crew app. Kiro Crew provides the agents' sessions, the members that make up
  a team, a knowledge base the agents search and cite, memory that builds from the work, and an app platform with
  explicit trust and permissions. The app uses only Kiro Crew's local API.
- **What you need.** A Mac with Kiro Crew and Node.js 22; `setup.sh` installs everything in about 10 minutes and
  `cleanup.sh` removes what it created. A run costs Kiro Crew credits (34 to 51 per delivery in the measured runs) and
  creates no AWS resources.

![The team board during a run of the agent-team sample](samples/agent-team-on-kiro-crew/docs/images/team-board.jpg)

## How a sample is organized

```text
samples/<sample-name>/
├── README.md            What the sample covers, prerequisites, how to run it, cost, cleanup
├── aidlc-plugin/        AI-DLC 2.0 plugin for the domain: stages, agents, knowledge, sensors
├── steering/            Kiro steering rules: domain standards, coding standards, toolchain usage
├── mcp/                 Tool connectors the agents use, with their guardrails
├── reference-project/   A small runnable project to practice on
└── rehearsal/           Guide and scorecard for a one-day guided rehearsal
```

The agent-team sample is a Kiro Crew app rather than a plugin, and its README describes its own layout.

A sample adds domain knowledge to AI-DLC as a
[plugin](https://github.com/awslabs/aidlc-workflows/blob/main/docs/harness-engineering/10-authoring-a-plugin.md)
instead of changing the framework. Teams keep receiving upstream AI-DLC releases, and they can
enable or disable the domain plugin per project.

## The one-day guided rehearsal

Every sample includes a guide for a one-day rehearsal on the team's own toolchain, in the team's own
AWS account. After one to two weeks of preparation, a group of the team's engineers build a real
feature with the sample. They keep the feature, its tests in their CI, and the rules the agents
worked under. The result is scored against the team's definition of done. That score is a baseline
that later delivery is measured against; it is not a productivity claim. See
[docs/guided-rehearsal.md](docs/guided-rehearsal.md).

## Getting started

1. Install Kiro IDE or Kiro CLI from [kiro.dev](https://kiro.dev).
2. Install AI-DLC by following the
   [AI-DLC Quick Start](https://github.com/awslabs/aidlc-workflows#quick-start).
3. Pick a sample and follow its README. Each sample lists its own prerequisites, expected cost and
   cleanup steps.

## Contributing

Contributions of new samples, domain knowledge and tool connectors are welcome. Read
[CONTRIBUTING.md](CONTRIBUTING.md) and [docs/adding-a-sample.md](docs/adding-a-sample.md) first. In
short, every contribution must:

- use synthetic data and domain-neutral names, with no customer names or customer data;
- build from public packages, and run on a simulated target wherever the domain allows;
- keep a human approval step on irreversible actions, and never rely on `--trust-all-tools`;
- document prerequisites, cost and cleanup.

## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.

## License

This library is licensed under the MIT-0 License. See the [LICENSE](LICENSE) file.
