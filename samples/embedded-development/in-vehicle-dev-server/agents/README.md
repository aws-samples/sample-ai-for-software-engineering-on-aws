# Agent configurations, the bypass hook and the permission probe

Build plan item 6 of the [in-vehicle scenario](../README.md#build-plan).

| Path | What it is |
| --- | --- |
| [`kiro-crew/make_templates.py`](kiro-crew/make_templates.py) | The Kiro agent templates of the team's roles, which `setup.sh` installs. Each one carries the bypass hook |
| [`hooks/guard.py`](hooks/guard.py) | The bypass hook, a Kiro `preToolUse` hook on the shell and on file writes |
| [`hooks/test_guard.py`](hooks/test_guard.py) | Its tests without Kiro: what it refuses, what it lets run, and the bypasses it does not stop |
| [`probe/probe.py`](probe/probe.py) | The permission probe: the same calls through a real Kiro session |
| [`probe/runs/`](probe/runs/) | The probe's results, one folder per run |

## The bypass hook

The `build` and `bench` MCP servers are the only paths meant to work. The hook is defence in depth: it makes the other
paths fail too, as far as a check on the command text can ([Around the
servers](../README.md#4-tool-connectors-with-guardrails)). It refuses:

- **Reaching the bench without the `bench` server.** These shell commands are refused:
  - Docker (every `docker*` command), Podman, nerdctl, and a container runtime's socket;
  - `bench/cc1.sh` and `bench/console.py`;
  - SSH, SCP, SFTP, rsync, netcat, socat and telnet to the target's forwarded port or to loopback;
  - anything that names the bench's container or volumes.
- **Touching the bench state or a run's check results.** Shell commands and file writes that touch the bench state
  (`$CC1_BENCH_STATE`, default `~/.cc1-bench`) or the check results of the Kiro Crew app's runs
  (`~/workplace/vstatd-team/runs/<run>/results/`) are refused, also through a link. A shell command that only reads
  them is refused too; reads with the agent's read tool still work, because the hook is not on that tool.
- **`git push` and history rewrites.** This covers `push` (also `send-pack`, `http-push`, `hub push`), `rebase`,
  `reset --hard`, `filter-branch`, `update-ref`, `commit --amend`, `branch -D/-f`, `checkout -B`, `switch -C`,
  `tag -f/-d`, `reflog expire`, `gc --prune`, and aliases, hooks or remote URLs set with `git config` or `git -c`.
  The hook also catches them in these forms:
  - with git options before the subcommand (`git -C <dir> push`);
  - behind `env`, `sudo`, `command`, `exec`, `timeout`, `xargs` and the like;
  - inside `sh -c`, `eval`, `find -exec` and `submodule foreach`;
  - in compound commands and command substitutions, also inside quotes;
  - quoted or escaped.

The command line is split at unquoted operators, so a commit message or a `grep` pattern that mentions `git push` or
`docker` runs; the lines of a here-document are judged as commands, so a here-document that mentions them is refused.
Line continuations and redirections (also next to an operator, as in `true;>/dev/null git push`) are followed. Command
substitutions and process substitutions are judged on their own, also nested and inside double quotes; text in single
quotes is not a substitution. A command line over 64 KiB, more than eight levels of shells and substitutions, or more
than 64 substitutions is refused, and so is anything the hook fails to judge. A tool call the hook does not recognise,
or a write without a path it can read, is refused.

**One file for both engines.** The templates are in the format that kiro-cli's V2 and V3 engines both load. They have
`tools` and `allowedTools` for V2 and a `permissions` block for V3, which allows reads, writes, the shell, skills and
the Kiro Crew MCP server's tools without asking. The hook is in the array form: one entry each for the tags `shell`
and `write`. V2 does not evaluate regular expressions in a matcher, so the tags are used. The two engines name the
tools differently: V2 says `shell` and `write`, V3 says `execute_bash` and `fs_write`. The hook knows both.

Two differences remain. In V3 the roles get `fs_write`, which writes a whole file; V2's `fs_write` also replaces and
appends, so under V3 a partial edit is a whole-file write or a shell command. V3 also keeps Kiro's own limits: writes
to `.git/**` and `.kiro/agents` ask, which a session without a person treats as a deny (commits go through the
shell, so they are not affected). `kiro-cli agent upgrade` leaves these files alone, as files it did not write.

When the hook refuses a call, it exits with status 2, and Kiro returns the hook's message to the agent. In the templates
the hook command is `python3 -I <sample>/agents/hooks/guard.py || exit 2`, which kiro-cli 2.34.0 runs with `bash -c`.
Kiro lets a call run when a hook exits with any status other than 2, so the `|| exit 2` keeps the hook closed when
python3 is missing or the hook fails. The path is absolute, so run `setup.sh` again after you move the sample folder.

**What it does not stop.** The hook judges the text of the call, not what the call runs. These get through, and
`test_guard.py` lists them:

- a command written to a script and then run, which the probe shows in a real session;
- a program that starts the command itself (`python3 -c "subprocess.run(...)"`);
- a string piped or redirected to a shell (`echo 'git push' | sh`, `sh <<< ...`), or decoded first;
- a variable or ANSI-C quoting that holds the command (`$G push`, `$'\x67it' push`);
- a relative path from inside a protected folder, a URL to the target's port, a global git alias, and `gh`.

The hook is only on the shell and on file writes. The templates also auto-approve one tool of Kiro Crew's own MCP
server, `@kirocrew-core/local_knowledge_search`, which does not pass through the hook. The roles do not get the
server's other tools, which include previewing a deploy of a web artifact to a public URL on the user's AWS account,
workflows and tasks, the browser, messages to the user and writes to the knowledge library.

Measured on 2026-11-18 with Kiro Crew 0.12.2 and kiro-cli 2.34.0:

- In a Kiro Crew chat session bound to the developer template, the session had that server's
  `local_knowledge_search` and none of its other tools; asked to call `send_notification`, it found no such tool.
  Kiro Crew also adds its own cron server to the session (`kirocrew-cron`: list, add, update, remove and remove all,
  pause, resume and trigger jobs, and `cron_secret_request`). The templates do not list it; Kiro Crew adds it.
- With kiro-cli's V2 engine, the session listed `local_knowledge_search` as its only tool of the server and called it
  without asking.
- With `--v3`, the session listed no MCP tool (only `execute_bash`, `fs_write` and `disclose_context`), whether the
  template named the whole server or the one tool. The V3 rule in `permissions` is therefore untested, and the
  knowledge search needs the V2 engine or Kiro Crew.

The boundary is a build server whose agents have no target key, no Docker access and no push credentials
([D2](../docs/kiro-crew-app.md#d2-kiro-crew-runs-on-the-users-own-machine-agents-have-a-shell-sessions-auto-approve)).

```bash
python3 agents/hooks/test_guard.py        # no Kiro needed; 8 tests, each with its own cases
```

## The permission probe

`probe/probe.py` runs one non-interactive Kiro session, which costs a few credits. The session uses a throwaway agent
in its own folder that has the templates' tools, auto-approval and hook command, and the probe asks it to make 14
calls. Each probe is judged by its effect, not by what the agent says:

- a push that gets through lands on a local bare repository;
- `docker`, `ssh`, `scp`, `podman` and `nc` are stand-ins that only record their arguments;
- the bench state is a new folder, and git may use local paths only (`GIT_ALLOW_PROTOCOL=file`);
- a canary probe checks that the session's shell finds the stand-ins, not the real tools.

A wrapper around the hook command records each call the hook saw. The result depends on the agent sending each
command as written: a probe the hook did not see as written is "not tested", never a pass, and the probe exits
non-zero. That happened while the probe was being written: with commands that read a key and wrote "forged"
approvals, the model declined most of them and Kiro stopped the conversation; the commands are now harmless ones of
the same form. Run the probe again after each Kiro or Kiro Crew update. It also writes the session's transcript;
read it before you publish it.

```bash
python3 agents/probe/probe.py --harness none --out <new folder>   # also --harness v2 or v3
```

### Last run

2026-11-16, kiro-cli 2.34.0 on an x86_64 Ubuntu 24.04 host, with the templates' format for both engines; results in
[`probe/runs/2026-11-16/`](probe/runs/2026-11-16/):

| Harness | Result |
| --- | --- |
| The version's default (none given, V2) | 14 of 14 as expected, in 49 s (the agent sent one call twice, so 15 reached the hook). Every probe reached the hook as written, under the tool names `shell` and `write`; the hook saw the session's `CC1_BENCH_STATE`, and the shell found the stand-ins. Refused with no effect: five forms of `git push`, `reset --hard`, `docker exec` into the bench, `ssh` to the target, a shell write and a file-tool write to the bench state. Ran: a `git status` and a file write in the repository. Got through as known: the push written to a script and run |
| `--v2` | The same, 14 of 14, in 42 s |
| `--v3` | The same, 14 of 14, in 44 s and again in a second session (44 s), under the tool names `execute_bash` and `fs_write` |

The templates themselves, generated with this host's Kiro Crew MCP server, were also loaded once in each engine
in a throwaway repository with a local bare remote: asked to `git push`, the developer role's session was refused by
the hook under `--v3` and under `--v2`, and nothing reached the remote.

Before the templates had a `permissions` block, the V3 engine did not load them at all (exit status 4: agent not
found), and the probe reported nothing tested. The hook ran although `allowedTools` and `permissions` approved the
calls. Once, when the hook refused one of two parallel calls, Kiro skipped the other one too and the agent sent it
again on its own (a single observation, not recorded by the probe).

In Kiro Crew 0.12.2 (2026-11-17, same host), the developer role's template, generated by `make_templates.py` with
that version's `kirocrew` and copied to `~/.kiro/agents/` under a throwaway name, was opened as a chat session
bound to the template, in trust mode, on a throwaway repository with a local bare remote. Kiro Crew ran the
session on its KAS engine (shell tool `run_command`); the hook ran there unchanged.

| Call | Result |
| --- | --- |
| `git status`, a file write, `git add` and `git commit` | Ran without asking |
| `git push origin HEAD:refs/heads/zz-feature` | Refused by the hook, with its message; nothing reached the remote |
| `git push origin main` and `git reset --hard HEAD~1` | Each became an approval card from Kiro Crew's own policy (rules `git-publish-push-protected-branch-name` and `git reset --hard.*`); the hook's decision was not seen. Nobody approved them, the session was stopped, and nothing changed |
| `@kirocrew-core/local_knowledge_search` | Ran without asking; the host has no `vstatd` source, and it answered "No relevant knowledge found." |

Kiro Crew reads `~/.kiro/agents/` when the gateway starts and when an app registers or removes its agents. The
template copied in while the gateway ran was refused for a chat session (`agent_choice_unavailable`), although Kiro
Crew's own scanner accepted the file; after a gateway restart the session started. setup.sh installs the app (step 2)
before it copies the templates (step 3, `scripts/install-team.sh`), and does not restart the gateway. The app opens
its role sessions through Kiro Crew's internal spawn call, not the chat API used here.

The app itself was then run on a Mac (Apple Silicon, Kiro Crew 0.13.0-rc.1, kiro-cli 3.4.0). The four templates
were generated by this `make_templates.py` and installed over the earlier ones with `scripts/templates.py`, as
setup.sh does. The gateway had been running since the day before and was not restarted. Every role session the app
opened (triage, architect, tester and two developer sessions) reported `agent_kind: template`, and no
`agent_choice_unavailable` was seen.

The run went up to tests first. The hook refused none of the tool calls in the triage (31), architect (25) and
tester (22) sessions. The hook prints nothing when it lets a call run, and the session records show no trace of it,
so this run does not show that it was invoked on those calls.

These templates replaced files of the same names. On a first install, where the names are new to Kiro Crew, restart
Kiro Crew after setup.sh until that case is checked.

Not verified yet:

- a first install by setup.sh (template names new to Kiro Crew) without a gateway restart;
- the whole app on Kiro Crew 0.12 on a Mac (the run above was on 0.13.0-rc.1);
- the hook in the Kiro IDE.
