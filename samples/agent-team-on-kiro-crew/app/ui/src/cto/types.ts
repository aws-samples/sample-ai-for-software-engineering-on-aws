/**
 * The CTO view's contract: what `GET /api/apps/aidlc-team/cto` returns (backend/team/cto.py). The offline page
 * (cto/offline.html) reads the same shape. Dates are local calendar days (YYYY-MM-DD).
 */

export type Kind = 'app' | 'feat' | 'fix' // 新应用 · 新功能 · 修复
export type Size = 'S' | 'M' | 'L' // 小 · 中 · 大

export type CtoData = {
  meta: CtoMeta
  items: CtoItem[] // deliveries a person signed off: the simulated history, and this app's runs (实测), newest first
  wip: CtoWip[] // the kanban: what is in progress now
}

export type CtoMeta = {
  today: string
  agentStart: string // the first day of the 12 weeks with AI-DLC
  weeks: string[] // 24 week starts: 12 before AI-DLC, then 12 with it
  lines: string[] // the business lines; items point into it by index
  peoplePerLine: number
  eq: Record<Size, number> // person-days the same work takes people alone
  human: Record<Size, number> // person-days people still put in with the agent team
  dayRate: number // ¥ per person-day
  seatUsdMonth: number
  fx: number
  months: number
  realAvgMins: number // a measured run's average time, minutes
}

export type CtoItem = {
  t: string
  line: number
  kind: Kind
  size: Size
  period: 'base' | 'agent'
  ship: string
  cyc: number // days from its Issue to release
  signer: string
  real: string | null // the run id when it is a run of this app (实测)
  issue?: string // TY-2795
  reporter?: string // who raised it: 运营部 …
  created?: string // the Issue's day
  pr?: number | null // the PR that took it into main
  defects?: string[] // the Issues of defects raised after it shipped (a fix links back with origin)
  origin?: string // a fix of a defect: the Issue of what it fixes
  mins?: number // 实测: the run's own time
  tests?: string // 实测: the checks when it was signed, 37/37
  members?: number // 实测: agent members that took part
  decisions?: [string, string][] // 实测: what people decided at its gates
  caught?: { person: number; review: number; checks: number } // 实测: what was sent back before release, and by whom
  risks?: CtoRisk[] // 实测: what people who sent work back at a gate noted it kept from going live
}

/** 拦下的风险: noted by the person who sent work back at a gate; the amount is in yuan (or none). ``at``: seconds from
 * the run's start, to open its moment. */
export type CtoRisk = { what: string; amount: number | null; gate: string; role?: string | null; at: number }

/** One run's 价值流 (`GET /cto/flow?run=`, backend/team/cto.py flow): seconds count from the run's start. */
export type FlowSegment = {
  from: number
  to: number
  who: 'agent' | 'person'
  col: string // the kanban column: 构思 · 启动 · 构建 · 运维
  phase: string // the AI-DLC phase of its roles (the board's phase key)
  label: string // 启动 · 构建 · 返工 · 等人批准 · 上线关卡 · 签字放行
  roles: string[]
  gate: string | null // a person's segment: the gated role, or 'signoff'
  decision: '批准' | '退回' | '签字' | null
}
export type FlowMark = { at: number; kind: 'gate' | 'approved' | 'bounce' | 'check' | 'review' | 'deployed' | 'signoff' | 'merged'; role: string | null; label: string }
export type CtoFlow = {
  run: string
  status: string
  started_at: number
  end: number
  segments: FlowSegment[]
  marks: FlowMark[]
  decisions: { at: number; role: string; gate: string; note: string }[]
  agent_s: number
  person_s: number
  gates: number
  credits: number | null
  members: number
  tests: { passed: number; total: number; enterprise: number }
  sent_back: { person: number; review: number; checks: number }
  risks: CtoRisk[]
  rework: number
  review: string
  deployed: boolean
  issue: { id: string; kind: string; reporter: string; created_at: number }
  pr: import('../types').PullRequest | null
  titles: Record<string, string>
  team: { key: string; title: string; icon: string; skipped: boolean; credits: number }[] // the members, in the team's order
}

export type CtoWip = {
  t: string
  line: number
  kind: Kind
  size: Size
  state: 'pool' | 'agent' | 'wait'
  col: '需求池' | '构思' | '启动' | '构建' | '运维'
  mins?: number // pool: since it came in; agent: since the run began
  members?: number // agent: members at work
  gate?: string // wait: 上线关卡 …
  role?: string // wait (a run of this app): the gated role, to open the board at it
  who?: string
  hours?: number // wait: how long it has waited
  focus?: string // wait: what the person is to decide
  live?: boolean // a run of this app
  real?: string // its run id
  issue?: string
  reporter?: string
  pr?: number | null // 签字放行: the PR waiting for the signature
}
