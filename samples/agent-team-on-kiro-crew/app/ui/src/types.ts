/**
 * The board contract: what `GET /api/apps/aidlc-team/board?run=<id>` returns. The backend (backend/team/board.py)
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
  standards: Standard[] // 命中规范: the company standards and data the requirement touches, by keywords
  roster?: RosterPerson[] | null // the company's whole team this run drew from, as it was when the run began (null: older runs)
  imported?: { from: string; exported_at?: number } | null // 导入: recorded on another Mac; its code and sessions stayed there
  knowledge: { source: KnowledgeSource | null; hits: KnowledgeHit[] } // the team's knowledge source and what roles looked up
  crew_members: string[] | null // the team's members on Kiro Crew's 「代理」 page now (its workspace's), null while not read yet
  signoff: SignOff | null // 签字放行: the person who took responsibility for the release, once they did
  requirement: string // the requirement as the person wrote it
  plan_skip: Record<string, string> // the optional members the planner's 分工提案 leaves out this run, with why (applied once a person approves)
  overruled: { role: string; note: string; review: string } | null // a person approved a gate over a review that still said 要改, and why
  sign_block: string // why this run cannot be signed off ('' when it can: it finished and what it deploys went out)
  delivery: Delivery // 交付标签: what the CTO view counts this run as, once a person signs it off
  issue: Issue // the requirement as the organisation tracks it
  pr: PullRequest | null // the run branch into main: open once the run delivered, merged when a person signs it off
}

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
export type SignOff = { by: string; note: string; at: number; tests: string }

/** One company standard (or knowledge-base data set) a requirement touches, and why. */
export type Standard = {
  id: string // 'RULE' | 'PII' | 'DATA-EMP' ...
  title: string // 年会抽奖规则
  kind: 'standard' | 'data'
  owner: string // who sets it: 人力资源部
  doc: string // its document in the knowledge source
  rules: string[] // RULE-1 ...
  why: string // 命中「抽奖」
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

export type Ownership = { roles?: Record<string, string[]>; test_areas?: Record<string, string>; error?: string }

export type Lane = {
  key: string // 'pm' | 'architect' | ...
  title: string // 产品经理 ...
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
  mission: string // one line: what it is for
  aidlc_agent: string // the official AI-DLC agent definition it uses, e.g. 'aidlc-architect-agent'
  gate: 'pending' | 'discussing' | 'approved' | null // a person's gate after this role (null: none, or not reached; discussing: it is answering the person's 讨论)
  gate_label: string // what the person approves, e.g. '范围'
  gate_preset: string // the team file's preset note for approving that gate (填入预设意见), '' when none
  gate_revise_preset: string // …and for sending it back (a review gate: says whom, 打回：前端开发 #2)
  kinds: string[] // every attempt's kind, oldest first: 'work' | 'fix' | 'conflict' | 'review' | 'revise' | 'discuss'
  session: string | null // the Kiro Crew chat session it works in, null before it opened
  deployed: { url: string; at: number } | null // 部署执行: where the app started the service a deploy role configured
  icon: string // which drawing stands for it ('frontend', 'tester' ...): the team file's, else its key
  assignment: string // what the orchestrator assigned this member in this run (the team plan), e.g. '抽奖接口和开奖记录'
  doing: string // what it is on right now: the assignment, or what it was sent back for ('修 RULE-2'、'解决合入冲突')
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
}

/** A question a gated role puts to the person (its questions file): options A/B…, its recommendation and why. */
export type GateQuestion = { id: string; q: string; options: { key: string; text: string }[]; recommend: string; why: string }

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
  status: 'pass' | 'fail' | 'skip'
  owner: string | null // the role that must make it pass (team.json test_owners)
  ms: number | null
  message: string | null // first line of the failure
}

export type TestWall = {
  at: number | null // when the run branch was last tested, null if never
  command: string
  cases: TestCase[]
  passed: number
  failed: number
  total: number
  history: { at: number; passed: number; failed: number }[] // one point per test run
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
  | 'deployed' // 部署执行: the app started the deploy role's service on this Mac and it answered
  | 'standards' // 命中规范: the company standards and data the requirement touches
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
  from: string | null // for particles: a role key, 'tests' or 'run'
  to: string | null
  data: EventData | null // structured facts behind the text; prefer these over parsing `text`
}

export type EventData = {
  carry?: string // handoff: what is handed over (验收标准、接口契约 …)
  cases?: string[] // bounce: the failing cases sent back (AC ids or test names)
  passed?: number // tests
  total?: number // tests
  paths?: string[] // conflict / violation: the files involved
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

/** `GET|POST /runs/<id>/site`, `POST /runs/<id>/site/stop`: the finished product on a local port. */
export type SiteStatus = {
  run: string
  state: 'off' | 'running' | 'failed'
  url: string | null
  port: number | null
  entry: string | null
  started_at: number | null
  expires_at: number | null // it stops by itself then
  error: string | null
  log: string[] // the server's last output lines
}

/** POST /route: 组队 — the team the orchestrator picks for a requirement by keywords, and why (no run started). */
export type RouteRole = {
  key: string
  title: string // the team member: 前端开发 #1
  phase: string
  stage: string
  aidlc_agent: string
  member: string // the Kiro Crew member it boots ('' when the team names none)
  icon: string
  assignment: string // what the orchestrator will assign it
  gate: boolean
  optional?: boolean // sits the run out when its member is not on Crew's 「代理」 page when the run is handed over
  on_crew?: boolean | null // is the member on Crew's 「代理」 page now (null: not read; absent: no member named)
}

/** One post on the company's team (team/roster-*.json): who could take part in a run. */
export interface RosterPerson {
  key: string
  title: string
  member: string
  icon: string
}

export type RouteTeam = {
  file: string
  name: string
  scope: string // the official AI-DLC scope it follows: 'mvp' | 'bugfix' | 'feature' …
  keywords: string[]
  priority: number
  fallback: boolean
  official_stages: number | null // how many stages the official scope runs
  needs_source: boolean
  starter: string | null
  source: string | null // the customer repository the team works on by default (no directory to type in)
  roles: RouteRole[]
  agents: string[] // the official AI-DLC agents its roles are
  stages: string[] // the official stages its roles cover that its scope has, e.g. '2.8 接口约定'
  extra_stages: string[] // stages it adds beyond its official scope (the shop adds 4.1 / 4.3 deployment to mvp)
  extra_note: string // why
  people?: RosterPerson[] | null
}

export type RoutePick = {
  team: RouteTeam | null
  matched: string[]
  why: string
  others: { file: string; name: string; scope: string; matched: string[] }[]
  roster: string[] // the 14 official AI-DLC agents, then the company's own its teams use
  teams: { file: string; name: string; scope: string; keywords: string[] }[]
  crew?: { members: string[] | null; error: string } // what Kiro Crew has (「代理」), as the app last read it
  standards?: Standard[] // 命中规范 for this requirement, with the picked team
  knowledge?: KnowledgeSource | null // the picked team's knowledge source
}
