# Source: AI-DLC expert agent definitions

`agents/` holds four files, unmodified, of `core/agents/` from
[awslabs/aidlc-workflows](https://github.com/awslabs/aidlc-workflows), release v2.10.0, commit
`8a04f0129f3f8985f414f81bb8f8fafe694d38c6`, licensed under MIT No Attribution (see [LICENSE](LICENSE)): the
four experts this team uses (`aidlc-developer-agent`, `aidlc-architect-agent`, `aidlc-quality-agent`,
`aidlc-architecture-reviewer-agent`). They were taken from the same copy in the
[agent-team sample](../../../../agent-team-on-kiro-crew/vendor/aidlc-workflows/), so that this sample does not depend on
that folder (D12 in [docs/kiro-crew-app.md](../../docs/kiro-crew-app.md)).

`setup.sh` turns each definition into a Kiro agent template: the definition is the prompt, followed by a short note on
how to work in Kiro Crew on `vstatd` ([agents/kiro-crew/make_templates.py](../../agents/kiro-crew/make_templates.py)).
The orchestrator in `app/` does not run the AI-DLC workflow engine; it borrows these expert definitions and follows the
AI-DLC phases and roles.

Do not edit the files in `agents/`. To move to a newer AI-DLC release, replace them and update this page.
