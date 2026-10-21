# Source: AI-DLC expert agent definitions

`agents/` is an unmodified copy of `core/agents/` from
[awslabs/aidlc-workflows](https://github.com/awslabs/aidlc-workflows), release v2.10.0, commit
`8a04f0129f3f8985f414f81bb8f8fafe694d38c6`, licensed under MIT No Attribution (see [LICENSE](LICENSE)).

`scripts/install-example.sh` turns each definition into a Kiro agent template: the definition is the
prompt, followed by a short note on how to work in Kiro Crew in the example
(`example/agents/make_templates.py`). The orchestrator in `app/` does not run the AI-DLC workflow engine;
it borrows these expert definitions and follows the AI-DLC phases and roles.

Do not edit the files in `agents/`. To move to a newer AI-DLC release, replace the folder and update this page.
