# AI-DLC agent team on Kiro Crew

> **Status: available, early development.** The sample installs and runs end to end on macOS with
> Kiro Crew. The board, the team definitions and the example company are in Simplified Chinese; see
> [Known limitations](#known-limitations).

## What this sample covers

A one-sentence requirement goes in. An orchestrator forms a team of
[AI-DLC](https://github.com/awslabs/aidlc-workflows) expert agents for it, each role a real
[Kiro Crew](https://kiro.dev/docs/crew/) session. The roles work in parallel on their own git branches and
look up the company's standards in a Kiro Crew knowledge base. Company-issued checks decide what passes and
failures go back to the role that owns them. An independent reviewer reads the diff, and a person approves
at the gates. The result is deployed on the local machine, and the person who owns the delivery signs it off.
A live board shows all of it as it happens, and a CTO view rolls signed-off deliveries up into
throughput, cycle time and cost.

| Step | What is different with an agent team | What the sample provides |
| --- | --- | --- |
| Requirements and design | Several agents need one agreed scope, and a person has to settle the open questions before anything is built | Roles that write the scope, the questions that need a decision and a work split; human gates where the person answers each question, discusses with the role, approves or sends back |
| Build | Roles work at the same time and must not overwrite each other | One git worktree and branch per role, write scopes per role, merges by the orchestrator, conflicts sent back to their owner |
| Validate and release | "Done" is decided by the company, not by the agent that wrote the code | Company checks the agents cannot edit, failures routed to their owners, an independent read-only review, a release gate, local deployment, and a sign-off record |

## Two layers: a general orchestrator, and Kiro Crew underneath

**The app is general.** Nothing in the orchestrator is specific to the example company. A team is a JSON
file: its roles, who depends on whom, what each role may write, which checks run, who owns which failing
test, where the human gates are, and what a run starts from (a starter project or an existing repository).
The sample ships three teams, and a run picks one by the words in the requirement (a fourth, `team.json`, is a
minimal built-in team that the tests use):

| Team file | Roles | Human gates | Starts from | Checks | Deploys to |
| --- | --- | --- | --- | --- | --- |
| `team-aidlc.json`, AI-DLC expert team (any new requirement) | 13 | 范围 scope, 启动 build start, 上线 release | `starters/web` | 8 company checks (`packs/taoyuan-web`) | `127.0.0.1:8085` |
| `team-taoyuan-promo.json`, shopping-festival promotion | 8 | 需求 requirements, 上线 release | `starters/mall` | 28 company checks (`packs/taoyuan-promo`) | `127.0.0.1:8090` |
| `team-bugfix.json`, two-person bug fix | 2 | none | a project folder you name | none | none |

The test wall shows the company checks together with the tests the team writes itself, so a run usually counts
more checks than the table. The ports are defaults: the deploy role writes the port it wants, and when that port
is taken the site goes on a free one.

To use the app for your own work, write a team file and point it at your own starter, checks and knowledge
source. See [Use it with your own team](#use-it-with-your-own-team).

**Kiro Crew provides the platform.** The app is a Kiro Crew app: a Python backend that Kiro Crew loads, and
a React page in the Kiro Crew window. It works only through Kiro Crew's local HTTP API, and does not reach
into the Kiro Crew process.

| The app relies on Kiro Crew for | Kiro Crew feature |
| --- | --- |
| One chat session per role, its replies and tool calls, credits used, model choice | Chat sessions (`/api/chat`, `/api/models`) |
| Which person-like member a role runs as, and whether that member exists | Members, shown under Customize → Teammates (`/api/agents`) |
| Company standards and data the agents look up | Knowledge base with a local-folder source (`/api/knowledge`) |
| Letting the team work without a click per tool call | App permission `sessionApproval`, granted by you (see [Guardrails](#guardrails)) |
| The board page, its storage and its place in the sidebar | App runtime and app SDK |
| Watching every agent at work, optionally | Agent Worlds, a built-in Kiro Crew app |

```text
 you ──▶ board (Kiro Crew app page) ──▶ orchestrator (app backend, ticks every 2 s)
                                          │ forms the team from a team file
                                          │ one git worktree + branch per role
                                          │ merges, runs the checks, routes failures,
                                          │ stops at human gates, deploys on 127.0.0.1
                                          ▼
                          Kiro Crew local API (127.0.0.1:5476)
            ┌─────────────────────────┼──────────────────────────┐
     a chat session per role   members (Teammates)       knowledge source 桃源科技
```

## The example company

Taoyuan Tech (桃源科技) is a fictitious home-appliance brand with an online store. It exists so that the
sample has realistic standards to follow and data to work with; every name, number and record is synthetic.
`example-company/` holds:

- `knowledge/`: the company's standards (brand, front-end engineering, personal-information display, account
  security, annual-party lottery rules, price and promotion compliance, margin and pricing, price protection) and
  descriptions of its data;
- `data/`: products, 60 days of orders, a promotion plan, an employee list, prizes and a list of weak passwords;
- `agents/make_templates.py`: builds the Kiro agent templates of the team's 15 members, the 14 AI-DLC experts
  and one expert the company adds itself (brand motion).

The app's `starters/` (the company's project templates), `packs/` (the checks the company issues) and
`team/roster-taoyuan.json` (the company's development team) belong to the same example.

## Guardrails

What the sample enforces:

- **Human gates.** A run stops at each gate until a person decides. At a gate you answer the questions the
  role raised one by one (its recommendation is the default), discuss with the role (it answers in its own
  session, and may revise its documents; the gate stays open), approve, or send it back with a note. Your
  decisions go into every later role's task and into `docs/aidlc/decisions.md` on the run branch. On the
  AI-DLC expert team nothing is built before you approve the 启动 gate.
- **Company checks.** The checks under `packs/<pack>/tests/enterprise/` are copied into every run repository
  and run by the orchestrator, not by the agents. A failure goes back to the role that owns the file, up to a
  fixed number of fix rounds.
- **Write scopes.** Each role has the paths it may write. Changes outside them are recorded as violations when
  the orchestrator merges the role's branch.
- **Independent review.** A read-only reviewer reads the whole diff and can send work back.
- **Local deployment only.** The app starts each site with `HOST=127.0.0.1`, and after it answers, asks `lsof`
  what it listens on: a site that listens on all interfaces or on a network address is stopped, with the reason on
  the board. Nothing is deployed to any cloud account.
- **Sign-off.** Only a delivered run can be signed. Signing fast-forwards the run branch into `main` of the
  run's own repository and records who signed and every human decision.

What it does not enforce, and how to run it safely:

- If you agree during setup, the app sets **the sessions it opens** to auto-approve their tool calls,
  and the members' templates allow file reads and writes and shell commands. The agents can then run shell
  commands on your Mac without asking. Write scopes are checked at merge time, not prevented while an agent
  works. Run the sample on a machine and user account **without production credentials or customer data**.
  If you do not agree, every tool call waits for your approval in Kiro Crew.
- The agents' sessions send their prompts, the code they read and the knowledge they look up to the model service
  that Kiro Crew uses. Use only data you are allowed to send there; the example company's data is synthetic.
- Generated code is not reviewed for production use. Read what the team built before you use any of it.
  Generative AI can make mistakes; see the [AWS Responsible AI Policy](https://aws.amazon.com/ai/responsible-ai/policy/).

## Layout

| Path | Contents |
| --- | --- |
| `app/` | The Kiro Crew app `aidlc-team`: orchestrator (`backend/`), board and CTO view (`ui/`), teams (`team/`), starter projects (`starters/`), company checks (`packs/`), tests. See [app/README.md](app/README.md) |
| `example-company/` | The fictitious company: knowledge base, data, member templates |
| `vendor/aidlc-workflows/` | The 14 AI-DLC expert definitions, copied unmodified from awslabs/aidlc-workflows (MIT-0) |
| `setup.sh`, `cleanup.sh`, `scripts/` | Install into Kiro Crew; remove what setup created (recorded in `.install-state.json`) |

## Prerequisites

- A Mac with macOS. The scripts and the app have been tested on macOS on Apple silicon only.
- [Kiro Crew](https://kiro.dev/docs/crew/) 0.8.0 or newer, running and signed in, with credits on the
  account. The sample has been run end to end on Kiro Crew 0.8.0.9 and 0.9.0.4.
- Node.js 22 or newer, git and python3 (`xcode-select --install` provides git and python3).
- Network access to registry.npmjs.org for the board's build dependencies (about 100 MB).

## Set up

```bash
git clone https://github.com/aws-samples/sample-ai-for-software-engineering-on-aws.git
cd sample-ai-for-software-engineering-on-aws/samples/agent-team-on-kiro-crew
bash setup.sh
```

`setup.sh` takes about 10 minutes and is safe to re-run. It:

1. checks the prerequisites and that Kiro Crew is running;
2. builds the board, installs the app into Kiro Crew and adds it to Kiro Crew's trusted apps (this one app only).
   It asks once whether the app may auto-approve the sessions it opens (see [Guardrails](#guardrails)). If Kiro
   Crew keeps its trusted apps in a local configuration file that the API cannot change, setup says so: add
   `aidlc-team` to the trusted apps in Kiro Crew's settings and run `setup.sh` again;
3. installs the example company: files under `~/workplace/taoyuan/`, 15 agent templates in `~/.kiro/agents/`,
   the Kiro Crew workspace `taoyuan`, 15 members, and the knowledge source 桃源科技. What exists already is kept;
   an agent template with the same name and other content is backed up to `~/.kiro/agents/.aidlc-team-sample-backup/`
   before it is replaced;
4. waits until Kiro Crew has indexed the knowledge source.

Keep the folder where it is after setup: Kiro Crew installs the app from it.

## Run it

1. In Kiro Crew, open **Apps → AI-DLC 多 Agent 团队**. The app opens on the CTO view (CTO 视图). Switch to
   **团队看板** (team board) in the app bar.
2. Click **新需求** (new requirement). Pick the scenario **双十一 · 家电大促** to fill in a shopping-festival
   promotion, or write your own requirement in one sentence. Leave the team on automatic: the preview shows
   which team the words select, which members it uses and which standards apply. Click **交给团队** (hand
   to the team).
3. Watch the team graph. Hover over a role to see its task, what it did and the credits it used, and to open
   its Kiro Crew session. The test wall turns green as checks pass; failures go back to their owners.
4. At each gate, click **✓ 批准** (approve), **讨论** (discuss) or **退回** (send back). The dialog shows the
   role's documents, the questions it wants you to decide, and the discussion so far.
5. When the run has been delivered, the site is deployed: open it from the deploy role's outputs (**看产出 →
   打开网站**, view outputs → open site), or at the port the board shows. Then fill in **签字人** (who signs) and click
   **签字放行** (sign off). The delivery now counts in the CTO view.

The CTO view starts with synthetic history (`app/cto/history.json`, made by `app/scripts/cto_history.py`) so
that its charts are not empty. Those numbers are illustrative, not a productivity claim. Deliveries you sign
off are added and marked 实测 (measured).

## Use it with your own team

- **A team file** in `app/team/` defines the roles (`key`, `member`, `depends_on`, `writable`, `outputs`,
  `brief`, `gate`, `questions`, `deploy`), what a run starts from (`starter` or `source`), the checks
  (`spec_pack`, `test_command`, `test_owners`), the knowledge source, the Kiro Crew workspace and the words
  that select it (`scope`, `keywords`, `priority`, `fallback`). [app/README.md](app/README.md) lists every key
  and the code that reads it.
- **A starter** in `app/starters/` is the project a run begins from. **A pack** in `app/packs/` holds the checks
  your company issues (`tests/enterprise/`), which the agents cannot change.
- **Members**: each role runs as a Kiro Crew member. Create the members in Customize → Teammates, or adapt
  `example-company/agents/make_templates.py`. A role marked `"optional": true` whose member does not exist sits
  the run out, and its checks do not run.
- **Knowledge**: add a local folder as a Kiro Crew knowledge source and name it in the team file.

After a change to the app, run `bash setup.sh` again (or `app/scripts/dev-install.sh`) to update it in Kiro Crew.

## Develop and test

```bash
cd app
python3 -m pytest -q          # backend: Python 3.10+ and pytest; fake Kiro Crew sessions, real git and node
cd ui && npm ci && npm run check   # board: type check, component tests, build
```

`npm run preview:build` builds `ui/preview-dist/index.html`, the board and CTO view on test data without Kiro Crew.

## Cost

The sample creates no AWS resources. The cost is Kiro Crew credits for the agents' sessions; see
[Kiro pricing](https://kiro.dev/pricing/). In our test runs in October 2026, the promotion team used 34 and 36
credits in two runs (8 roles; 40 of 40 checks on the test wall passed; 13 minutes from requirement to deployment
when the gates were answered right away), and the AI-DLC expert team used 48 and 51 credits in two runs (13 roles;
26 of 26 checks passed). How long a run takes depends mostly on how long the gates wait for a person.

## Cleanup

```bash
bash cleanup.sh --dry-run   # list what will be removed
bash cleanup.sh             # remove it: type "remove" to confirm
```

It removes only what `setup.sh` recorded as created in `.install-state.json`: the app (stopping any site it
deployed), the sessions of finished runs, the app's data and the run repositories in `~/workplace/aidlc-team/`; the
members, the workspace and the knowledge source; the agent templates, putting back any it replaced; and
`~/workplace/taoyuan/`. Whatever existed before setup is left alone, and so is Kiro Crew itself.

## Known limitations

- The board, the team definitions, the agents' briefs and the example company (including the READMEs of the
  starters and packs it owns) are in Simplified Chinese.
- macOS only; one run at a time.
- Kiro Crew 0.9 renamed the members page to Customize → Teammates. Some hints on the board still call it
  「代理」(agents), the name in Kiro Crew 0.8.
- The orchestrator follows the AI-DLC phases and uses the official expert definitions; it does not run the
  AI-DLC workflow engine or its plugins.

## Acknowledgements

The app started as a fork of the `kirocrew-team` Kiro Crew app by ychchen. The expert definitions come from
[AI-DLC Workflows](https://github.com/awslabs/aidlc-workflows).
