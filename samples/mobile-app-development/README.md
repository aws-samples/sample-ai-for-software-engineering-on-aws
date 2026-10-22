# Mobile app development with AI-DLC (iOS first)

> **Status: planned.** This page sets out what the sample will deliver, how and why. Contributions are welcome.

## What: faster coding that becomes faster releases, because they pass review

Mobile teams ship on release trains. A release is done only when it passes app store review and the privacy and
regulatory rules that apply to the app; one rejection can cost a whole train. Faster coding does not help if those
rules are checked only at the end.

| You start with | You end with |
| --- | --- |
| An app on a release train, starting with iOS (Swift) and followed by Android (Kotlin) | A feature built with the store and privacy rules in its definition of done from the first step |
| Store review guidelines and privacy rules in documents | The same rules as knowledge the agents cite and as checks they cannot change, for example that every permission the app requests has a purpose string and that the privacy declaration matches what the code collects |
| A build that needs a Mac | Builds on [Amazon EC2 Mac instances](https://aws.amazon.com/ec2/instance-types/mac/) |
| Testing on the devices someone has at hand | Tests on real devices in [AWS Device Farm](https://aws.amazon.com/device-farm/), driven by the agent |
| A release candidate | A release candidate with the evidence a reviewer asks for |

**What it means for the team.** Fewer rejected submissions and fewer trains missed, because the review is part of
the work instead of a surprise at the end.

## How

1. **Rules as knowledge and checks.** Store and privacy rules are written down for the agents to cite, and the
   checkable ones run as checks.
2. **AI-DLC with gates.** Requirements, design and release each wait for a person's approval.
3. **Build in the cloud.** The app builds on an EC2 Mac instance.
4. **Test on real devices.** The agent runs tests on Device Farm devices through an MCP connector and reads the
   results, screenshots included.
5. **Where it runs.** [Kiro](https://kiro.dev) IDE or CLI, or [Kiro Crew](https://kiro.dev/docs/crew/) with a team
   of AI-DLC expert agents as in the [agent-team sample](../agent-team-on-kiro-crew/).

## Why

- **The release, not the code, is the unit of value.** A feature counts when it ships.
- **Review rules belong in the definition of done.** Checked at every step, they stop being a late surprise.
- **No device lab to own.** EC2 Mac and Device Farm give a team builds and real devices on demand.
