# Enterprise application and data with AI-DLC

> **Status: planned.** This page describes the intended scope. Contributions are welcome.

## What this sample will cover

Most of the work that runs a business happens in existing systems: internal services, ERP, finance
and supply-chain applications, and the data behind them. Agents can only help with that work once
those systems are described, reachable and governed. This sample uses AI-DLC to make a legacy system
usable by agents under the enterprise's own access rules.

Planned contents:

- generating and reviewing OpenAPI specifications for undocumented internal services;
- applying row- and column-level access control so that agents see only what the requesting user may
  see;
- exposing the system through governed MCP servers, with authentication, authorization and audit, for
  example on [Amazon Bedrock AgentCore](https://aws.amazon.com/bedrock/agentcore/) Gateway;
- a reference project with a synthetic ERP-style data set;
- a one-day rehearsal guide and scorecard.

The folder layout follows the [repository convention](../../README.md#how-a-sample-is-organized).
