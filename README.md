# AI for Software Engineering on AWS: AI-DLC Samples

Teams that already use AI coding assistants usually reach the same next question: how do we run the
AI-Driven Development Life Cycle (AI-DLC) on our own toolchain, against our own definition of done,
through our own release process? This repository answers that question one engineering domain at a
time.

Each sample takes a feature from requirement to a validated release on a realistic toolchain, using
[AI-DLC Workflows 2.0](https://github.com/awslabs/aidlc-workflows) with [Kiro](https://kiro.dev). It
packages what a team needs to repeat the work on its own code: the domain's standards as knowledge the
agents cite and as checks they cannot change, tool connectors (MCP servers) with guardrails, a small
reference project, and a guide for a one-day guided rehearsal. Samples run with Kiro (IDE or CLI) or
[Kiro Crew](https://kiro.dev/docs/crew/).

> [!IMPORTANT]
> **Maturity: early development.** The samples are for learning and evaluation. They are not
> production ready. Review every generated change, and keep human approval on any action that
> touches hardware, production systems or customer data. Generative AI can make mistakes; see the
> [AWS Responsible AI Policy](https://aws.amazon.com/ai/responsible-ai/policy/).

## Samples

| Sample | Scenario | Toolchain highlights | Status |
| --- | --- | --- | --- |
| [AI-DLC agent team on Kiro Crew](samples/agent-team-on-kiro-crew/) | A team of AI-DLC expert agents takes a web feature from a one-sentence requirement through human gates, company checks and an independent review to a local deployment and a sign-off | Kiro Crew app (Python backend, React board), git worktrees, Node.js test runner, Kiro Crew knowledge base | Available |
| [Embedded development](samples/embedded-development/) | Firmware and controller software in C and C++, including model-based design, validated in simulation and on hardware before an engineer signs off the release | A reference framework; contributors choose the toolchain, such as cross toolchains, QEMU, OpenOCD and GDB, hardware-in-the-loop benches; runs in Kiro and Kiro Crew | Open for contributions |
| [Enterprise application and data](samples/enterprise-application-and-data/) | Making legacy services, ERP, finance and supply-chain systems and their data usable by agents | OpenAPI specifications, row- and column-level access control, governed MCP servers | Planned |
| [Mobile app development, iOS first](samples/mobile-app-development/) | Swift and Kotlin apps on release trains, where the definition of done includes app store review and regulatory rules | Amazon EC2 Mac instances, AWS Device Farm | Planned |

## Sample overview: AI-DLC agent team on Kiro Crew

AI coding assistants make one engineer faster at writing code. With the
[agent-team sample](samples/agent-team-on-kiro-crew/), the organization delivers several times as much, end to end. It
is the first sample you can install and run.

- **So what: several times the delivery, end to end.** In the sample's CTO view, a simulated organization of 60
  people delivers 3.1 times as much in 12 weeks with the same people; a large requirement goes from issue to release
  in 6.8 days instead of 29.8; new applications and features reach users 8.8 days earlier; and defects after
  release fall by 44 %, from 10.9 to 6.1 per 100 new applications and features. The figures are simulated; the sample
  shows how a new user gets the same measures for their own deliveries. In measured runs, a promotion feature built
  by 8 agents went from requirement to local deployment in 13 to 20 minutes, and passed all 40 checks, 28 of them the
  company's, before a person approved the release.
- **How: AI-DLC, a knowledge base and a team of agents.** An orchestrator follows the AI-DLC phases with human gates
  (scope, build start, release) where a person answers the open questions one by one. The company's standards live
  in a knowledge base that the agents search and cite, and the same rules run as checks the agents cannot change.
  Each role runs as one of the 14 AI-DLC expert agents on its own git branch; failures go back to their owners, and
  an independent reviewer reads the result. Teams are JSON files, so the orchestrator is not tied to its example.
- **Why Kiro Crew.** The sample is a Kiro Crew app. Kiro Crew is open source and provides the agents' sessions, the
  members that make up a team, a knowledge base, memory that builds from the work, and an app platform with explicit
  trust and permissions; the app uses only Kiro Crew's local API.
- **Try it in 10 minutes.** On a Mac with Kiro Crew and Node.js 22: clone this repository, run `bash setup.sh` in
  the sample's folder, and hand a one-sentence requirement to the team; `cleanup.sh` removes what setup created. A run
  costs Kiro Crew credits (34 to 51 per delivery in the measured runs) and creates no AWS resources. See
  [Quick start](samples/agent-team-on-kiro-crew/README.md#quick-start).

![The CTO view of the agent-team sample: deliveries, cycle time and defects before and after the agent team, on a simulated organization](samples/agent-team-on-kiro-crew/docs/images/cto-view.jpg)

## Sample overview: embedded development

[`samples/embedded-development/`](samples/embedded-development/) is a reference framework, open for contributions: contributors
build samples for the embedded scenarios they know, and each one works in Kiro and in Kiro Crew.

- **What.** A sample takes one embedded feature from a requirement and the hardware documents to code that builds
  with the team's own toolchain and passes tests before any hardware is involved; hardware actions go only through
  guarded tools, and the engineer who owns the release signs it off with the evidence in front of them.
- **How.** Five building blocks: hardware knowledge with citations; AI-DLC phases with people deciding at the gates;
  checks and gates before hardware; tool connectors (MCP servers) with guardrails; and the agent running next to the
  bench. Built in plain formats (Markdown, MCP servers, scripts), the same parts run in Kiro and in Kiro Crew.
- **Why.** Embedded toolchains differ widely, so samples come from the people who use them, on one shared framework.
  Embedded work also differs from web work: requirements live in datasheets, a build-and-flash loop takes minutes to
  hours, and a failed run can damage hardware, so the loop is closed in simulation first and on hardware only behind
  the gates.

Two scenarios are in development on this framework:
[in-vehicle software on a development server next to the bench](samples/embedded-development/in-vehicle-dev-server/)
and [robot firmware and software, where a digital twin decides and a person flashes](samples/embedded-development/robot-twin-and-flash-gate/).

The [enterprise application and data](samples/enterprise-application-and-data/) and
[mobile app](samples/mobile-app-development/) samples are planned; their pages set out what, how and why.

## How a sample is organized

```text
samples/<sample-name>/
├── README.md            What it delivers, how it works and why; prerequisites, cost, cleanup
├── knowledge/           Standards and reference documents the agents look up and cite
├── checks/              Checks the agents do not control
├── mcp/                 Tool connectors the agents use, with their guardrails
├── reference-project/   A small runnable project to practice on
└── rehearsal/           Guide and scorecard for a one-day guided rehearsal
```

This layout is a suggestion; a sample may adapt it. The agent-team sample is a Kiro Crew app, and its README
describes its own layout.

Every sample README answers three questions: what it delivers, how it works, and why it is built that way. Samples
are built from plain parts (Markdown knowledge and rules, MCP servers, checks as scripts) so that they run in Kiro and
in Kiro Crew. A sample may also package its parts as an AI-DLC
[plugin](https://github.com/awslabs/aidlc-workflows/blob/main/docs/harness-engineering/10-authoring-a-plugin.md),
the official extension mechanism of AI-DLC Workflows 2.0, so that a team that runs AI-DLC can install it without
changing the framework.

## The one-day guided rehearsal

Every sample includes a guide for a one-day rehearsal on the team's own toolchain, in the team's own
AWS account. After one to two weeks of preparation, a group of the team's engineers build a real
feature with the sample. They keep the feature, its tests in their CI, and the rules the agents
worked under. The result is scored against the team's definition of done. That score is a baseline
that later delivery is measured against; it is not a productivity claim. See
[docs/guided-rehearsal.md](docs/guided-rehearsal.md).

## Getting started

1. Install Kiro IDE or Kiro CLI from [kiro.dev](https://kiro.dev), or [Kiro Crew](https://kiro.dev/docs/crew/) for
   the agent-team sample.
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
