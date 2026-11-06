/**
 * The board contract: what `GET /api/apps/vstatd-team/board?run=<id>` returns. The backend (backend/team/board.py)
 * builds exactly this; the page renders only this. Times are epoch seconds. Keep both sides in step.
 */

export type RunStatus = 'starting' | 'running' | 'fixing' | 'reviewing' | 'gating' | 'done' | 'failed' | 'stopped' // gating: a person's gate waits

export type LaneStatus =
  | 'waiting' // dependencies not done yet
  | 'queued' // its session is opened, Kiro Crew has not started the turn yet: see agent.queued_reason
  | 'running'
  | 'stalled' // KiroCrew flags it stalled
  | 'awaiting_approval' // a tool call waits for the person
  | 'done' // the agent finished, not merged yet
  | 'merged' // its branch is merged into the run branch
  | 'fixing' // sent back with failing tests, a fix attempt is running
  | 'failed'
  | 'skipped' // the ownership file gave it nothing: this project does not need it

export type Board = {
  at: number
  runs: RunCard[] // newest first
  run: RunDetail | null // the selected run (?run=), else the newest active one, else the newest
}

export type RunCard = {
  id: string
  title: string
  status: RunStatus
  started_at: number
  ended_at: number | null
  roles_done: number
  roles_total: number
  tests: { passed: number; failed: number; total: number }
  imported?: boolean // recorded on another Mac and imported here (POST /runs/import): look and replay only
  name: string // the 交付名 (its 交付标签's name): what the run is called in the list
  issue: string // its Issue number, TY-3456
}

export type RunDetail = {
  id: string
  title: string // first line of the requirement
  status: RunStatus
  repo: string // the run's repository
  folder: string // the run branch checked out on this Mac: the whole project as merged so far
  base: string // the requirement commit every role branched from (short sha)
  branch: string // the run branch roles are merged into
  started_at: number
  ended_at: number | null
  wall_s: number // real elapsed time
  serial_s: number // sum of every role's own working time: what one agent doing it all would roughly take
  credits: number | null // total for the run when KiroCrew reports it, else null
  roles: Lane[] // team order
  edges: [string, string][] // dependency: [upstream role, downstream role]
  tests: TestWall
  merges: Merge[] // oldest first (the conveyor)
  events: TeamEvent[] // latest 200, oldest first
  team: { name: string; orchestrator: string } // the team file's name; what orchestrates it (the deterministic engine)
  ownership: Ownership | null // who writes where, once the ownership file is read
  review_rounds: number // times a 要改 review sent work back
  gate_notes: Record<string, string> // what a person said when approving a gate, by role
  gate_discuss: boolean // the team offers 讨论 at its gates
  imported?: { from: string; exported_at?: number } | null // 导入: recorded on another Mac; its code and sessions stayed there
  knowledge: { source: KnowledgeSource | null; hits: KnowledgeHit[]; docs: KnowledgeChip[] } // the team's knowledge source, what roles looked up, the documents they cite
  crew_members: string[] | null // the team's members on Kiro Crew's 「代理」 page now (its workspace's), null while not read yet
  signoff: SignOff | null // 签字放行: the person who took responsibility for the release, once they did
  risks: Risk[] // 拦下的风险: what people who sent work back at a gate noted it kept from going live
  requirement: string // the requirement as the person wrote it
  plan_skip: Record<string, string> // the optional members the planner's 分工提案 leaves out this run, with why (applied once a person approves)
  overruled: { role: string; note: string; review: string } | null // a person approved a gate over a review that still said 要改, and why
  sign_block: string // why this run cannot be signed off ('' when it can: it finished and what it deploys went out)
  sign_block_msg: Msg | null // …by code, for the board's language (null when it can be signed)
  review_redo?: ReviewRedo | null // the run ended on a 要改 review a person can send back once more (按评审意见再改一轮)
  delivery: Delivery // 交付标签: what the CTO view counts this run as, once a person signs it off
  issue: Issue // the requirement as the organisation tracks it
  pr: PullRequest | null // the run branch into main: open once the run delivered, merged when a person signs it off
  bench: BenchView | null // the bench actions of a team with a bench (D3, D10); null for a team without one
  release: ReleaseView | null // the independent rerun and release.sh (D9); null before it ran
  backlog: BacklogView | null // 需求清单: the findings backlog and the triage's findings; null for a team without a triage
}

/** The independent rerun of every check on the final commit (D9): release.sh's verdict (sign-off needs PASS), the
 * checks whose verdict differs from the run's last result, and the evidence page (Markdown) for the sign-off dialog. */
export type ReleaseView = {
  at: number
  head: string
  results: string
  release: { verdict: 'PASS' | 'FAIL' | 'BLOCKED' | 'USAGE'; summary: string; reasons: string[] }
  checks: { name: string; verdict: 'PASS' | 'FAIL' | 'BLOCKED' | 'USAGE'; tier: string | null; summary: string; reasons: string[] }[]
  differs: { name: string; was: string | null; now: string | null }[]
  evidence: string | null
}

/** The bench: the app's step there, what holds it for a person (and the commands they run), doctor.sh's result, the
 * app's own bench actions, and the bench state as the bench writes it (read only). */
export type BenchView = {
  step: 'doctor' | 'deploy' | 'replay' | 'after' | 'rerun' | 'done' | null
  running: string | null // the step running in the background
  held: { step: string; why: string; code?: string; params?: MsgParams | null; commands: string[]; at: number } | null
  doctor: { ok: boolean; rc: number | null; at: number; fails: string[]; warns: string[]; summary: string } | null
  artifact: string | null // the build deployed: build.sh's stripped vstatd
  run_dir: string | null // where the replay writes the run directory
  baseline: string
  actions: { action: string; at: number; outcome: 'ok' | 'refused' | 'timeout' | 'unknown' | 'failed'; why: string; rc: number | null }[]
  state: { dir: string; target: Record<string, unknown>; supply: Record<string, unknown> | null; pending: BenchRequest[]; actions: Record<string, unknown>[] }
  history?: Record<string, unknown>[] // the action record as it concerns this run (its requests and what names them, the target and supply while it ran): the bench of its replay
  console: string | null // the command that opens the operator console (python3 …/bench/console.py), null when there is none
}

/** A request waiting at the operator console: the action and the digest the person approves. */
/** `GET /readiness`: what a run of the default team needs (D10). ok null: the app cannot tell, or has not read it yet;
 * needed: from which step on (start: from the first role, checks: from 测试先行, bench: from the first bench action). */
export type Readiness = {
  at: number
  team: string
  items: ReadinessItem[]
  pending?: PendingRequest[] // bench requests waiting at the operator console now, from a run or from setting up the baseline
  error: string // the scenario folder is not known (setup.sh has not run): no items
}

export type PendingRequest = {
  id: string
  action: string
  digest: string
  requested_by: string
  left_s: number | null // seconds before the console's timeout refuses it
  approve: string // the console command that approves it
  refuse: string
}

export type ReadinessItem = {
  key: string // knowledge | image | doctor | target | baseline | console
  label: string
  ok: boolean | null
  detail: string
  command: string // what a person runs when it is not ready, '' when it is
  needed: 'start' | 'checks' | 'bench'
  age_s: number | null // how old the cached probe is
  running: boolean // its probe is running now
}

export type BenchRequest = { id: string; action: string; digest: string; detail: string; requested_at: string; requested_by: string; expired: boolean }

/** The run's Issue: its number, 需求 or 缺陷, who raised it and when (the run's start, unless its record says). */
export type Issue = { id: string; kind: '需求' | '缺陷'; reporter: string; created_at: number }

/** The run's pull request: its run branch into main, merged when a person signs it off (签字放行). */
export type PullRequest = {
  number: number
  head: string // team/<run>/run
  base: 'main'
  state: 'open' | 'merged' | 'signed' // signed: a person signed it off, but it was not merged on this computer (an imported run)
  opened_at: number // when the run delivered
  merged_at: number | null
  merged_by: string | null
  sha: string // main's commit after the merge; '' when it was not merged on this computer (an imported run)
  files: number
  added: number
  removed: number
  checks: string // the machine checks, 26/26
  review: string // the independent review's conclusion
}

/** 交付标签: proposed by the run's first gated role, confirmed (or changed) by the person at that gate; the team file's defaults until then. */
export type Delivery = {
  name: string // 双十一家电大促活动页
  kind: '新应用' | '新功能' | '修复'
  size: '小' | '中' | '大'
  line: '电商' | '移动应用' | '客户关系管理' | '供应链' | '内部系统' // 业务线
  why: string // the proposer's one-line reason, '' when none
  confirmed: boolean // a person confirmed them at the gate
}

/** A person's signature on a finished run: what the machine checks said when they signed. */
/** 拦下的风险: noted by the person who sent work back at a gate (amount in yuan, or none). */
export type Risk = { what: string; amount: number | null; gate: string; role: string | null; at: number }

export type SignOff = { by: string; note: string; at: number; tests: string; audit?: SignOffAudit }
/** results/audit.md and audit.json, written at sign-off, with their sha256. */
export type SignOffAudit = { dir: string; md: string; json: string }

/** 审计记录 (GET /runs/<id>/audit, GET /audit/bench; backend/team/audit.py): who did what, from the records only. */
export type AuditActor = 'person' | 'agent' | 'app' | 'bench'
export type AuditEntry = {
  at: number
  iso: string
  seq: number | null // the run event it comes from; null for a bench record
  actor: AuditActor
  who: string
  step: string // a FlowKey of board/flow.ts; '' when no step applies
  what: string
  evidence: string // '' when there is none
  flags: AuditFlags
}
/** What the board counts in an entry, so that it reads none of its words (audit.py). */
export type AuditFlags = { differs?: number; where?: 'board' | 'console'; result?: string }
export type AuditTrail = {
  run: string
  title: string
  requirement: string
  team: string
  base: string
  status: string
  entries: AuditEntry[]
}

/** A knowledge source of Kiro Crew (「知识库 → 来源」). */
export type KnowledgeSource = {
  name: string
  present: boolean | null // null: not read yet
  items: number | null
  status: string // Crew's sync state
  files_total: number | null
  files_done: number | null
  path: string
}

/** A role looking something up: a 查知识库 call (kind search) or a read of a knowledge-base data file (kind data). */
export type KnowledgeHit = { role: string; at: number; kind: 'search' | 'data'; text: string }

/** A citable knowledge document on the board, and how often the roles' replies cite it (`[VSTATD-IF` …). */
export type KnowledgeChip = { key: string; title: string; path: string; cites: number }

/** One knowledge document of GET /knowledge; counts are read from the file now. */
export type KnowledgeDoc = {
  path: string // relative to the knowledge folder
  title: string
  key: string | null // citation key: VSTATD-IF, CC1-PN, TR
  desc: string
  counts: { label: string; n: number }[]
  present: boolean
  text: boolean // false: binary (the PDF), not shown in the viewer
  rendered_from: string | null // the PDF: the Markdown file it is rendered from
}

/** GET /knowledge: the documents and Kiro Crew's source state (null: not read yet). */
export type KnowledgeIndex = { docs: KnowledgeDoc[]; source: KnowledgeSource | null; error: string }

/** GET /knowledge/file: one document's text for the read-only viewer. */
export type KnowledgeText = { path: string; title: string; text: string; size: number }

/** One role in the start form's 组队预览 (GET /team), in flow order. */
export type TeamRoleView = {
  key: string
  title: string
  icon: string
  aidlc_agent: string // the AI-DLC expert the role follows
  template: string // the Kiro agent template its session runs (~/.kiro/agents/<template>.json)
  writable: string // what it may write: paths, 按…的分工, or 只读
  gate: string // the human gate's label; '' when none
  phase: string
}

/** One check of the team file; when: before_bench | after_bench | release. */
export type TeamCheckView = { name: string; when: string; owner: string | null; max_rounds: number }

/** GET /team: the default team for the start form; templates say whether each template's file is installed. */
export type TeamPreview = {
  name: string
  roles: TeamRoleView[]
  checks: TeamCheckView[]
  templates: { name: string; present: boolean }[]
  knowledge: KnowledgeSource | null
  error: string
}

/** One measured span of a run (seconds from its start); open: still going (to is now). */
export type FlowSegment = {
  kind: 'agent' | 'gate' | 'console' | 'checks' | 'rerun'
  from: number
  to: number
  role: string | null // agent, gate: the role
  label: string
  code: string // the label's message code (backend/team/messages.py)
  params: MsgParams | null
  result: string | null // gate: 批准 | 退回; console: 批准 | 拒绝 | 超时; checks: 通过 | 不过; rerun: 一致 | 不同
  result_code: FlowResult | null // the same, by code
  open: boolean
}

export type FlowResult = 'error' | 'approved' | 'sent_back' | 'refused' | 'timeout' | 'differs' | 'same' | 'fail' | 'pass'

/** A moment of a run: a send-back, a round with a failing check, an approval, the sign-off. */
export type FlowMark = { at: number; kind: 'bounce' | 'check_fail' | 'approved' | 'signoff'; role: string | null; label: string; code: string | null; params: MsgParams | null }

/** 交付详情's figures; null: nothing recorded for it. person_s: gates and the console, overlaps counted once. */
export type FlowTotals = {
  elapsed_s: number
  agent_s: number | null // some agent working (parallel roles counted once)
  person_s: number | null
  gate_s: number | null
  console_s: number | null
  check_s: number | null
  credits: number | null
  check_rounds: number | null
  send_backs: number
}

/** GET /runs/<id>/flow: 交付详情, where one run's time went. */
export type RunFlow = {
  run: string
  title: string
  status: string
  started_at: number
  end: number // seconds from the start to the sign-off, else the end, else now
  live: boolean
  signed: boolean
  segments: FlowSegment[]
  marks: FlowMark[]
  roles: { key: string; title: string; title_en: string; gate_label: string; gate_label_en: string; icon: string }[]
  totals: FlowTotals
}

/** A row of the findings backlog (findings-backlog.md); label fix puts it in this batch. */
export type BacklogRow = { id: string; tool: string; check: string; location: string; message: string; label: string }

/** GET /backlog: the work item and the backlog; next_id is the free ID the triage gives the refactor (TR §4.4). */
export type BacklogIndex = { work_item: string; rows: BacklogRow[]; next_id: string; error: string }

/** A 要改 review the run ended on: the reviewer, its verdict line, the roles it sends back. */
export type ReviewRedo = { role: string; summary: string; targets: string[] }

/** The app's proposal on a held run: give *role* the files *paths* for the finding *extend* added already (note: why). */
export type PathSuggestion = { extend: string; check: string; role: string; paths: string[]; note: string }

/** One finding of the triage, with only what the app records about it (null: no record). */
export type TriageRow = {
  id: string
  decision: string // fix | justify | defer
  added: boolean // added under TR §4.4
  found_by?: string | null // an added one's: checks/<check>.sh, or the work item
  location?: string | null // an added one's: where it was found (file:line)
  cites: string[]
  facts: string[]
  evidence: string | null // a fix's: unit-test | static-analysis | build
  behaviour: boolean | null
  answer: string | null // the person's answer at the triage gate
  answer_key?: string | null // its option's key, when the option's words are the app's (answer_msg)
  answer_msg?: Msg | null
  static: string | null // the latest static result's status: reported | gone | …
  trace: string[] | null // commits citing it in the latest trace result
}

export type TriageApproval = { by: string; at: string }

/** The triage: proposed (merged, at its gate) or approved. */
export type TriageView = { state: 'proposed' | 'approved'; approved: TriageApproval | null; findings: TriageRow[] }

/** 需求清单 on the board: the backlog, and once there is one the triage. */
export type BacklogView = { rows: BacklogRow[]; next_id: string; triage: TriageView | null }

export type Ownership = { roles?: Record<string, string[]>; test_areas?: Record<string, string>; error?: string }

export type Lane = {
  key: string // 'pm' | 'architect' | ...
  title: string // 产品经理 ...
  title_en: string // its English name from the team file ('' when it has none: the board shows title)
  emoji: string
  model: string
  status: LaneStatus
  depends_on: string[]
  writable: string[]
  attempt: number // 1, then +1 per fix round
  agent: AgentLive | null // the current (or last) KiroCrew sub-agent of this role
  worktree: string | null
  branch: string | null
  files: FileChange[] // vs the run base, biggest first, at most 12
  lines: { added: number; removed: number }
  commits: { sha: string; subject: string; at: number }[] // newest last, at most 8
  violations: string[] // paths it changed outside its writable globs
  owns_tests: string[] // test case ids attributed to this role
  started_at: number | null
  done_at: number | null
  active_s: number // its own working time so far
  credits: number | null // all finished attempts of this role
  summary: string | null // the agent's `DONE: ...` line
  phase: string // AI-DLC phase: 'ideation' | 'inception' | 'construction' | 'review' | 'operation' | ''
  stage: string // e.g. '2.1 逆向工程'
  stage_en: string
  mission: string // one line: what it is for
  mission_en: string // …in English, from the team file ('' when it has none)
  aidlc_agent: string // the official AI-DLC agent definition it uses, e.g. 'aidlc-architect-agent'
  gate: 'pending' | 'discussing' | 'approved' | null // a person's gate after this role (null: none, or not reached; discussing: it is answering the person's 讨论)
  gate_label: string // what the person approves, e.g. '范围'
  gate_label_en: string
  gate_preset: string // the team file's preset note for approving that gate (填入预设意见), '' when none
  gate_revise_preset: string // …and for sending it back (a review gate: says whom, 打回：前端开发 #2)
  gate_revise_risk: { what: string; amount: number | null } | null // …and the risk that send-back keeps from going live
  kinds: string[] // every attempt's kind, oldest first: 'work' | 'fix' | 'conflict' | 'review' | 'revise' | 'discuss'
  session: string | null // the Kiro Crew chat session it works in, null before it opened
  icon: string // which drawing stands for it ('frontend', 'tester' ...): the team file's, else its key
  assignment: string // what the orchestrator assigned this member in this run (the team plan), e.g. '抽奖接口和开奖记录'
  doing: string // what it is on right now: the assignment, or what it was sent back for ('修 RULE-2'、'解决合入冲突')
  doing_msg: Msg | null // the round's own words by code (label.*), for the board in English; null for the role's assignment
  member: string // the Kiro Crew member it is (「代理」), '' when the team does not name one
  member_kind: string | null // how its session was booted: 'member' | 'template' | 'default'; null before one opened
  optional: boolean // a post that may sit a run out: its member not on Crew's 「代理」 page (未入职), or the approved plan leaves it out
  overrule: boolean // its gate waits for a person over a review that still says 要改 with its rounds used up
  awaiting_member: string | null // ready to start, but its Crew member is not on 「代理」: held until a person adds it
  delivery_gate: boolean // this role proposes the 交付标签: its gate is where a person confirms them
  questions: GateQuestion[] // 要人决定的: what the role asks the person to decide at its gate, answered one by one
  answers: GateAnswer[] // what the person decided, once they approved its gate
  talk: TalkLine[] // 讨论 at its gate: the person's words and the role's answers, oldest first
  can_discuss: boolean // its gate offers 讨论 (the team allows it, and its rounds are not used up)
  tests_first: 'pending' | 'passed' | 'failed' | 'sent_back' | null // a test writer's tests run on the base commit, which must fail there (D6)
}

/** A question a gated role puts to the person (its questions file): options A/B…, its recommendation and why. The
 * triage gate's (D4) also carry the finding's proposed decision and the specification pages it cites. */
export type GateQuestion = { id: string; q: string; q_msg?: Msg | null; options: { key: string; text: string; msg?: Msg | null }[]; recommend: string; why: string; cites?: string[]; decision?: string }

/** The person's answer: an option's key, or 'other' with their own words (text); differs: not what the role recommended. */
export type GateAnswer = { id: string; choice: string; option: string; text: string; differs: boolean }

/** One turn of a 讨论 at a gate: the person ('person') or the role ('agent'); changed: it changed its documents in that turn. */
export type TalkLine = { who: 'person' | 'agent'; text: string; at: number; changed: boolean | null }

/** What a person does at a gate: 批准, 讨论 (it answers; the gate stays), or 退回. */
export type GateDecision = 'approve' | 'discuss' | 'revise'

export type AgentLive = {
  id: string
  turns: number
  tool_count: number
  last_tool: string // e.g. "Running: node --test tests/" / "Editing backend/server.js"
  last_activity: number | null
  started: number
  elapsed_s: number
  queued_reason: string | null
  error: string | null
  recent_tools: ToolCall[] // newest last, at most 8: from KiroCrew's live tool-call log
  text_tail: string | null // the last ~300 characters the agent wrote (its live output), or null
  credits: number | null // known once this attempt has finished
}

export type ToolCall = { at: number; tool: string; kind: string | null; detail: string | null }

export type FileChange = { path: string; added: number; removed: number; status: 'A' | 'M' | 'D' }

export type TestCase = {
  id: string // stable: file + name
  ac: string | null // 'AC-3' parsed from the test name, if any
  name: string
  file: string
  status: 'pass' | 'fail' | 'skip' | 'blocked' // blocked: the check could not judge, or is misconfigured: a person decides
  owner: string | null // the role that must make it pass (team.json test_owners; a check: by file, else its owner)
  ms: number | null
  message: string | null // first line of the failure
  verdict?: 'PASS' | 'FAIL' | 'BLOCKED' | 'USAGE' | null // a team file check's own verdict (its exit status)
  tier?: string | null // the tier of a check's evidence: 'unit test', 'emulation', 'real target' (checks/README.md)
}

export type TestWall = {
  at: number | null // when the run branch was last tested, null if never
  command: string
  cases: TestCase[]
  passed: number
  failed: number
  total: number
  history: { at: number; passed: number; failed: number }[] // one point per test run
  held: { checks: string[]; why: string; suggest?: PathSuggestion[] } | null // a check a person decides: BLOCKED, misconfigured, or out of its repair rounds (D7)
  round: number // the team file's checks: how many rounds before the bench were started
  running: boolean // a round of checks is due or running on what is merged
}

export type Merge = {
  role: string
  sha: string
  at: number
  status: 'merged' | 'conflict'
  files: number
  note: string | null // conflict paths, or null
}

export type TeamEventKind =
  | 'run' // run started / finished / stopped
  | 'bench' // the app's step on the bench (doctor, deploy, replay, the checks after it)
  | 'handoff' // an upstream role's output unblocked a downstream role (from -> to)
  | 'spawned' // a role's agent was started
  | 'tool' // a role's agent made a tool call (last_tool changed)
  | 'committed'
  | 'merged' // role branch merged into the run branch (from role -> to 'run')
  | 'conflict'
  | 'tests' // the run branch was tested: text says 7/12
  | 'bounce' // failing tests sent back to their owner (from 'tests' -> to role)
  | 'violation' // a role changed files outside its area
  | 'done' // a role's agent finished
  | 'failed'
  | 'review'
  | 'ownership' // the orchestrator read who writes where
  | 'skipped' // a role this project does not need
  | 'gate' // a role's output waits for a person (from role -> to 'person')
  | 'approved' // the person approved it (from 'person' -> to role)
  | 'finding' // 补登发现 (TR §4.4): a person registered what a check found and handed it to a role (person -> role)
  | 'signoff' // 签字放行: a person signed for the release
  | 'plan' // 分工提案: the gated role proposed who does what; it holds once a person approves the gate
  | 'member' // a required role is held for its Crew member (and starts once a person adds it)
  | 'talk' // 讨论 at a gate: the person said something (person -> role), or the role answered (role -> person)

export type TeamEvent = {
  seq: number // increasing per run
  at: number
  kind: TeamEventKind
  role: string | null
  text: string // one line, Chinese, ready to show
  code: string | null // what it says, by code (backend/team/messages.py): the board says it in its language; null on an older run's events, shown as text
  params: MsgParams | null
  from: string | null // for particles: a role key, 'tests' or 'run'
  to: string | null
  data: EventData | null // structured facts behind the text; prefer these over parsing `text`
}

/** A message by code: ev.<code> in ui/src/i18n with these params (r_…: role keys, g_…: a role's gate). */
export type Msg = { code: string; params: MsgParams | null }
export type MsgParams = Record<string, unknown>

export type EventData = {
  carry?: string // handoff: what is handed over (验收标准、接口契约 …)
  cases?: string[] // bounce: the failing cases sent back (AC ids or test names)
  passed?: number // tests
  total?: number // tests
  paths?: string[] // conflict / violation: the files involved
  phase?: 'before_bench' | 'after_bench' | 'rerun' // tests: which round of the team file's checks
  ms?: number | null // tests: the round's check time, its checks' wall times added up
  step?: string // bench: the step that starts (rerun)
}

/**
 * The 产出 view: `GET /runs/<id>/roles/<role>` — what one role produced. Role `run` is the whole product (the run
 * branch against the requirement commit), with no attempts.
 */
export type RoleOutput = {
  run: string
  role: string // a role key, or 'run'
  title: string
  emoji: string
  status: string // the lane's status (LaneStatus); for 'run' the run's (RunStatus)
  branch: string | null // the branch holding its deliverable
  folder: string | null // where that is checked out on this Mac: its worktree; for 'run' the run branch's
  base: string | null // what it is compared against (short sha)
  head: string | null // the branch head (short sha)
  writable: string[]
  files: OutputFile[] // committed on its branch since it started, by path
  attempts: OutputAttempt[] // oldest first
  ended: boolean // the run has ended
}

export type OutputFile = {
  path: string
  added: number
  removed: number
  status: 'A' | 'M' | 'D'
  output: boolean // one of the outputs team.json promises for this role
  owner: string | null // the role whose area it is in
}

export type OutputAttempt = {
  n: number
  kind: 'work' | 'fix' | 'conflict' | 'review' | 'revise' // review: a 要改 review sent it back; revise: a person or the ownership check did
  label: string // '修 AC-19' …, '' for the first one
  agent: string | null
  started: number | null
  ended: number | null
  credits: number | null
  error: string | null
  summary: string | null // its DONE line
  reply: string | null // its whole last reply (markdown)
  task: string // what the app told it
  calls: ToolCall[] // every tool call, oldest first
  live: boolean // still working
}

/** `GET /runs/<id>/roles/<role>/file?path=&view=content|diff` */
export type FileView = {
  path: string
  view: 'content' | 'diff'
  lang: string // 'markdown', 'javascript' … or 'diff'
  binary: boolean
  size: number
  truncated: boolean // only the first 300 KB are sent
  text: string
}


/**
 * `GET /scorecard` (D8): the rehearsal scorecard, from the runs' records only (backend/team/scorecard.py says how each
 * figure is taken). null: no run behind the figure, shown empty, never as 0.
 */
export type Scorecard = {
  runs: ScoreRun[] // the runs on the board's list, newest first
  total: ScoreTotal // summed over the runs
}

export type ScoreRun = {
  id: string
  title: string
  status: RunStatus
  started_at: number
  signed: boolean
  findings: ScoreFindings | null // the approved triage's decisions; the entries it added (TR §4.4) left out
  overturned: ScoreOverturned | null // justifications a person or the reviewer overturned
  times: ScoreTimes
  build_rounds: number | null // fix rounds for a failing build check
  caught: Record<string, number> | null // check → rounds before the bench in which it FAILed
  logdiff: ScoreLogdiff | null // over the replays on the bench
  bench: ScoreBench | null // the console's decisions on the run's requests, and reconciles after them
  rerun_differs: string[] | null // checks whose verdict differed on the independent rerun
}

export type ScoreFindings = { fixed: number; justified: number; deferred: number }
export type ScoreOverturned = { ids: string[]; by_person: string[]; by_reviewer: string[] }
/** Seconds since the run started. */
export type ScoreTimes = { triage_s: number | null; first_pass_s: number | null; signoff_s: number | null }
export type ScoreLogdiff = { differences: number; unexplained: number }
export type ScoreBench = { approved: number; refused: number; reconciled: number }

/** Sums over the runs (of the figures that exist); times are per run only. */
export type ScoreTotal = {
  runs: number
  findings: ScoreFindings | null
  overturned: number | null
  build_rounds: number | null
  caught: Record<string, number> | null
  logdiff: ScoreLogdiff | null
  bench: ScoreBench | null
  rerun_differs: number | null
}
