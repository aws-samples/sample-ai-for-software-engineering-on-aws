# Enterprise application and data with AI-DLC

> **Status: planned.** This page sets out what the sample will deliver, how and why. Contributions are welcome.

## What: agents that work on the enterprise's own systems, under its own access rules

Most of the work that runs a business happens in systems that already exist: internal services, ERP, finance and
supply-chain applications, and the data behind them. AI coding assistants help with new code, but they stop at these
systems because nobody can say what an agent may call, with whose permissions, and what it saw.

| You start with | You end with |
| --- | --- |
| An internal service with little or no API documentation | An OpenAPI specification of the service, reviewed and approved by its owners |
| Data that different people may see differently | Row- and column-level access rules, tested as checks, so an agent sees only what the person it acts for may see |
| No safe way for an agent to reach the system | Governed MCP servers with authentication, authorization and an audit record of every call |
| A change the business needs in that system | The change delivered through AI-DLC, with people approving at the gates |

**What it means for the enterprise.** AI moves past new code into the changes that run the business, and the
security team can approve it, because every agent call is described, permitted and recorded.

## How

1. **Describe.** Agents read the service's code and traffic samples and write its OpenAPI specification; the owners
   answer the open questions and approve it at a gate.
2. **Govern.** The access rules are written down and turned into checks that the agents cannot change.
3. **Expose.** The approved operations are served as MCP servers with authentication, authorization and audit, for
   example on [Amazon Bedrock AgentCore](https://aws.amazon.com/bedrock/agentcore/) Gateway.
4. **Deliver.** A change runs through the AI-DLC phases with human gates; the agents use the governed MCP servers,
   never direct database access.
5. **Where it runs.** [Kiro](https://kiro.dev) IDE or CLI, or [Kiro Crew](https://kiro.dev/docs/crew/) with a team
   of AI-DLC expert agents as in the [agent-team sample](../agent-team-on-kiro-crew/).

## Why

- **The value is in existing systems.** Most changes a business needs touch systems that are already running.
- **Governance first.** Agents get access only through described, permitted and audited operations, which is what
  lets a security team say yes.
- **Synthetic data, so anyone can try it.** The reference project uses an invented ERP-style system and data set.
