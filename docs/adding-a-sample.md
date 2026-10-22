# Adding or extending a sample

Read [CONTRIBUTING.md](../CONTRIBUTING.md) first. This page adds the rules specific to this
repository.

## What makes a good sample

A sample shows AI-DLC on one engineering domain whose toolchain, definition of done or release process
differs from general application development. It is worth adding when a team in that domain would
otherwise have to work out on its own how to fit AI-DLC to its work.

## Rules for every contribution

- **No customer information.** Use synthetic data and domain-neutral names. Do not include customer
  names, customer code, customer data or details that identify a customer, even in disguised form.
- **Public dependencies only.** Everything must build from public packages. Document every
  third-party tool the sample needs and its licence.
- **Runs without special hardware where possible.** Prefer simulators, emulators and managed services
  so that anyone can follow the sample; describe real hardware as an optional profile.
- **Human approval on irreversible actions.** Flashing, deployment, data changes and similar actions
  wait for a person. Do not rely on `--trust-all-tools`.
- **No secrets or account identifiers.** No credentials, account IDs, ARNs or private endpoints,
  including in tests and examples.
- **Prerequisites, cost and cleanup.** Every runnable part states what it needs, what it costs to run
  and how to remove what it created.
- **English.** Code, comments and documentation are in English.

## Starting a new sample

1. Copy [`templates/sample/`](../templates/sample/) to `samples/<sample-name>/`, using a lowercase,
   hyphenated name.
2. Fill in the sample README so that it answers what the sample delivers, how it works and why it is
   built that way, followed by layout, prerequisites, cost and cleanup. Package the domain's stages, checks
   and agent knowledge as an AI-DLC plugin where the domain allows; scaffold it with the official
   `aidlc-plugin-create.ts` and check it with `aidlc-plugin-validate.ts`.
3. Add the sample to the table in the [repository README](../README.md#samples).
4. Open a pull request from a branch. Keep each pull request focused on one sample or one part of a
   sample.
