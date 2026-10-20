# The one-day guided rehearsal

Every sample in this repository includes a guide for a one-day rehearsal. The rehearsal is how a team
finds out what AI-DLC does on its own code, its own toolchain and its own definition of done, instead
of on a demo project.

## Format

- **Where:** in the team's own AWS account, on the team's own repository and toolchain.
- **Who:** a group of the team's engineers, typically 16 to 32, with a facilitator who knows the
  sample.
- **What:** the group builds one real feature with the sample, from requirement to a validated build.
- **Preparation:** one to two weeks before the day.

## Preparation

1. Agree on the feature. It should be real, small enough for one day, and representative of the
   team's normal work.
2. Write down the team's definition of done for that feature: tests, reviews, validation steps and any
   release checks.
3. Set up access: AWS account, Kiro, AI-DLC with the sample's plugin, and the tools the sample's
   connectors need.
4. Run the sample's reference project once in the team's environment to confirm that the toolchain and
   connectors work.

## On the day

1. Start an AI-DLC workflow for the feature, with the sample's plugin enabled.
2. People review and approve each AI-DLC gate: requirements, design, and each unit of work.
3. Agents build within what people approved; every irreversible action waits for a person.
4. Close by scoring the result against the definition of done.

## What the team keeps

- the feature, in its own repository;
- the feature's tests, running in its own CI;
- the steering rules, knowledge and connector settings the agents worked under.

## The baseline

The score against the definition of done is the team's baseline: the starting point that later
delivery is measured against. The team's leadership signs it off. The baseline is not a productivity
claim, and it should not be compared across teams with different definitions of done.
