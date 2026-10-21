/**
 * Words, tones and number formats every part of the board shares. Pure: no React, no DOM.
 *
 * A tone is a meaning, not a colour: styles.ts maps each to a colour per host mode (kiro-dark /
 * kiro-light), so the same word always has the same colour and every colour has a word next to it.
 */
import type { Lane, LaneStatus, RunDetail, RunStatus, TeamEventKind, TestCase } from '../types'

export const BASE = '/api/apps/aidlc-team'
export const POLL_MS = 2000
const enc = encodeURIComponent

export const paths = {
  board: (run?: string | null) => `${BASE}/board${run ? `?run=${enc(run)}` : ''}`,
  runs: () => `${BASE}/runs`,
  stop: (run: string) => `${BASE}/runs/${enc(run)}/stop`,
  role: (run: string, role: string) => `${BASE}/runs/${enc(run)}/roles/${enc(role)}`,
  file: (run: string, role: string, path: string, view: 'content' | 'diff') =>
    `${BASE}/runs/${enc(run)}/roles/${enc(role)}/file?path=${enc(path)}&view=${view}`,
  site: (run: string) => `${BASE}/runs/${enc(run)}/site`,
  siteStop: (run: string) => `${BASE}/runs/${enc(run)}/site/stop`,
  retry: (run: string) => `${BASE}/runs/${enc(run)}/retry`,
  gate: (run: string) => `${BASE}/runs/${enc(run)}/gate`,
  open: (run: string) => `${BASE}/runs/${enc(run)}/open`,
  route: () => `${BASE}/route`,
  cleanup: () => `${BASE}/sessions/cleanup`,
  signoff: (run: string) => `${BASE}/runs/${enc(run)}/signoff`,
  hide: (run: string) => `${BASE}/runs/${enc(run)}/hide`,
  events: (run: string) => `${BASE}/runs/${enc(run)}/events`,
  cto: () => `${BASE}/cto`,
  ctoOffline: () => `${BASE}/cto/offline`,
  ctoFlow: (run: string) => `${BASE}/cto/flow?run=${encodeURIComponent(run)}`,
}

export type Tone = 'run' | 'fix' | 'ok' | 'done' | 'queue' | 'warn' | 'approve' | 'bad' | 'idle' | 'handoff' | 'info'

export interface StatusMeta {
  label: string
  tone: Tone
  icon: string
  /** One line for a person who does not know the word. */
  hint: string
}

export const LANE_META: Record<LaneStatus, StatusMeta> = {
  waiting: { label: '等待', tone: 'idle', icon: '⏳', hint: '上游还没合并，它还不能开工' },
  queued: { label: '排队', tone: 'queue', icon: '⏸', hint: '已派出，KiroCrew 还没让它开始' },
  running: { label: '在跑', tone: 'run', icon: '●', hint: 'agent 正在干活' },
  stalled: { label: '卡住', tone: 'warn', icon: '⚠', hint: 'KiroCrew 标记它卡住了' },
  awaiting_approval: { label: '等你批准', tone: 'approve', icon: '✋', hint: '一个工具调用在等你批准' },
  done: { label: '完成·待合并', tone: 'done', icon: '✓', hint: 'agent 做完了，分支还没合进运行分支' },
  merged: { label: '已合并', tone: 'ok', icon: '✔', hint: '它的分支已经合进运行分支' },
  fixing: { label: '修复中', tone: 'fix', icon: '↻', hint: '测试没过被打回，正在修' },
  failed: { label: '失败', tone: 'bad', icon: '✕', hint: '这个角色失败了' },
  skipped: { label: '跳过', tone: 'idle', icon: '–', hint: '这次不参与：未入职，或批准的分工里不要它（原因写在它的卡片上）' },
}

export const RUN_META: Record<RunStatus, { label: string; tone: Tone; active: boolean }> = {
  starting: { label: '启动中', tone: 'run', active: true },
  running: { label: '进行中', tone: 'run', active: true },
  fixing: { label: '修复中', tone: 'fix', active: true },
  reviewing: { label: '评审中', tone: 'run', active: true },
  gating: { label: '等你批准', tone: 'approve', active: true },
  done: { label: '已完成', tone: 'ok', active: false },
  failed: { label: '失败', tone: 'bad', active: false },
  stopped: { label: '已停止', tone: 'idle', active: false },
}

export const EVENT_META: Record<TeamEventKind, { icon: string; label: string; tone: Tone }> = {
  run: { icon: '🏁', label: '运行', tone: 'info' },
  handoff: { icon: '📨', label: '交接', tone: 'handoff' },
  spawned: { icon: '▶️', label: '开工', tone: 'run' },
  tool: { icon: '🔧', label: '工具', tone: 'idle' },
  committed: { icon: '📝', label: '提交', tone: 'info' },
  merged: { icon: '⤵️', label: '合入', tone: 'ok' },
  conflict: { icon: '⚡', label: '冲突', tone: 'bad' },
  tests: { icon: '🧪', label: '测试', tone: 'info' },
  bounce: { icon: '↩️', label: '打回', tone: 'bad' },
  violation: { icon: '🚫', label: '越界', tone: 'bad' },
  done: { icon: '✅', label: '完成', tone: 'ok' },
  failed: { icon: '❌', label: '失败', tone: 'bad' },
  review: { icon: '🔍', label: '审查', tone: 'info' },
  ownership: { icon: '🧭', label: '派活', tone: 'info' },
  skipped: { icon: '–', label: '跳过', tone: 'idle' },
  gate: { icon: '✋', label: '等人批准', tone: 'approve' },
  approved: { icon: '👍', label: '人批准', tone: 'ok' },
  deployed: { icon: '🚀', label: '部署', tone: 'ok' },
  standards: { icon: '📚', label: '命中规范', tone: 'info' },
  signoff: { icon: '✍️', label: '签字放行', tone: 'approve' },
  plan: { icon: '🗂️', label: '分工提案', tone: 'handoff' },
  member: { icon: '⏸', label: '缺成员', tone: 'warn' },
  talk: { icon: '💬', label: '讨论', tone: 'approve' },
}

export const CASE_META: Record<TestCase['status'], { label: string; glyph: string }> = {
  pass: { label: '通过', glyph: '✓' },
  fail: { label: '失败', glyph: '✕' },
  skip: { label: '跳过', glyph: '–' },
}

/** The meaning of a lane's status: a role that writes nothing (the reviewer) has nothing to merge, so
 * for it `done` is the end (完成), not 完成·待合并. */
export function laneMeta(lane: Pick<Lane, 'status' | 'writable'>): StatusMeta {
  if (lane.status === 'done' && lane.writable.length === 0) return { label: '完成', tone: 'ok', icon: '✔', hint: '它只读不写，做完就结束了' }
  // a status this page does not know yet (a newer backend) is shown as is, never a crash
  return LANE_META[lane.status] ?? { label: String(lane.status), tone: 'idle', icon: '•', hint: '' }
}

export function caseMeta(status: string): { label: string; glyph: string } {
  return CASE_META[status as TestCase['status']] ?? { label: status, glyph: '?' }
}

export function runMeta(status: string): { label: string; tone: Tone; active: boolean } {
  return RUN_META[status as RunStatus] ?? { label: status, tone: 'idle', active: false }
}

/** Nothing more will happen to this lane in this run. */
export const isFinal = (lane: Pick<Lane, 'status' | 'writable'>) => lane.status === 'merged' || (lane.status === 'done' && lane.writable.length === 0)

/** The AI-DLC phases, in order: the team graph's column groups. */
export const PHASES: ReadonlyArray<{ key: string; n: string; title: string; en: string }> = [
  { key: 'ideation', n: '1', title: '构思', en: 'Ideation' },
  { key: 'inception', n: '2', title: '启动', en: 'Inception' },
  { key: 'construction', n: '3', title: '构建', en: 'Construction' },
  { key: 'review', n: '✓', title: '评审关卡', en: 'Review gate' },
  { key: 'operation', n: '4', title: '运维', en: 'Operation' },
]

/** An agent of this role is alive in KiroCrew right now. */
export const LIVE: ReadonlySet<LaneStatus> = new Set<LaneStatus>(['running', 'fixing', 'stalled', 'awaiting_approval'])
/** …and making progress (these glow; stalled and awaiting-approval get their own loud look). */
export const WORKING: ReadonlySet<LaneStatus> = new Set<LaneStatus>(['running', 'fixing'])
/** Finished its part. */
export const FINISHED: ReadonlySet<LaneStatus> = new Set<LaneStatus>(['done', 'merged'])

export const isRunActive = (s: RunStatus) => RUN_META[s]?.active ?? false

/** 0:05, 25:00, 1:02:03 */
export function fmtClock(sec: number): string {
  const s = Math.max(0, Math.floor(sec))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const r = s % 60
  return `${h ? `${h}:${String(m).padStart(2, '0')}` : m}:${String(r).padStart(2, '0')}`
}

/** 45 秒, 23 分钟, 1 小时 5 分 */
export function fmtSpan(sec: number): string {
  const s = Math.max(0, Math.round(sec))
  if (s < 60) return `${s} 秒`
  const m = Math.round(s / 60)
  if (m < 60) return `${m} 分钟`
  const h = Math.floor(m / 60)
  const mm = m % 60
  return mm ? `${h} 小时 ${mm} 分` : `${h} 小时`
}

export function fmtAgo(delta: number): string {
  const s = Math.max(0, Math.round(delta))
  if (s < 5) return '刚刚'
  if (s < 60) return `${s} 秒前`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m} 分钟前`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h} 小时前`
  return `${Math.floor(h / 24)} 天前`
}

export function fmtCredits(c: number | null | undefined): string {
  if (c === null || c === undefined || !Number.isFinite(c)) return '—'
  return c >= 100 ? String(Math.round(c)) : (Math.round(c * 10) / 10).toFixed(1)
}

/** The parallel saving: what one agent doing it all would take, minus what it really took. */
export function saving(run: Pick<RunDetail, 'wall_s' | 'serial_s'>): { saved_s: number; speedup: number | null } {
  const saved = Math.max(0, run.serial_s - run.wall_s)
  const speedup = run.wall_s > 0 && run.serial_s > 0 ? run.serial_s / run.wall_s : null
  return { saved_s: saved, speedup }
}

/** The upstream roles a lane still waits for: its dependencies whose branch is not merged yet. */
export function waitingFor(lane: Pick<Lane, 'depends_on'>, lanes: Lane[]): Lane[] {
  const by = new Map(lanes.map((l) => [l.key, l]))
  return lane.depends_on.map((k) => by.get(k)).filter((l): l is Lane => !!l && l.status !== 'merged')
}

export function waitingText(lane: Pick<Lane, 'depends_on'>, lanes: Lane[]): string {
  const w = waitingFor(lane, lanes)
  if (w.length) return `等 ${w.map((l) => l.title).join('、')}`
  return lane.depends_on.length ? '上游都合并了，马上开工' : '马上开工'
}

/** 'AC-12' → 12 (sorting); no number → a big one, last. */
/** Case-id groups, in wall order: 功能验收 AC，然后是规范包里的安全 SEC、体验 UX、合规 COMP、上架 STORE. */
export const CASE_GROUPS: { prefix: string; label: string }[] = [
  { prefix: 'AC', label: '功能' },
  { prefix: 'RULE', label: '业务规则' },
  { prefix: 'ACC', label: '账号安全' },
  { prefix: 'PII', label: '个人信息' },
  { prefix: 'SEC', label: '安全' },
  { prefix: 'FE', label: '前端工程' },
  { prefix: 'UX', label: '体验' },
  { prefix: 'BR', label: '品牌' },
  { prefix: 'COMP', label: '合规' },
  { prefix: 'STORE', label: '上架' },
  { prefix: 'PRC', label: '价格合规' },
  { prefix: 'MGN', label: '毛利' },
  { prefix: 'PP', label: '价保' },
  { prefix: 'DATA', label: '数据' },
]

export function caseGroup(ac: string | null): number {
  const prefix = ac ? ac.split('-')[0] : ''
  const i = CASE_GROUPS.findIndex((g) => g.prefix === prefix)
  return i < 0 ? CASE_GROUPS.length : i
}

/** Sort key of a case id: its group, then its number; ids without a number go last. */
export function acNumber(ac: string | null): number {
  const m = ac ? /(\d+)/.exec(ac) : null
  return m ? caseGroup(ac) * 1e6 + Number(m[1]) : 1e9
}

export const baseName = (p: string) => p.replace(/\/+$/, '').split('/').pop() || p

/** Approximate rendered width in em: CJK ≈ 1, emoji ≈ 1.2, latin ≈ 0.58, space ≈ 0.3. */
export function textWidth(s: string): number {
  let w = 0
  for (const ch of s) w += charWidth(ch)
  return w
}

function charWidth(ch: string): number {
  const c = ch.codePointAt(0) ?? 0
  if (c === 0x20) return 0.3
  if (c > 0x1f000) return 1.2
  if ((c >= 0x2e80 && c <= 0x9fff) || (c >= 0xff00 && c <= 0xffef) || (c >= 0x3000 && c <= 0x303f)) return 1
  return 0.58
}

/** Cut *s* to about *maxEm* em with an ellipsis (SVG text does not ellipsize by itself). */
export function clip(s: string, maxEm: number): string {
  if (textWidth(s) <= maxEm) return s
  let out = ''
  let w = 0
  for (const ch of s) {
    const cw = charWidth(ch)
    if (w + cw > maxEm - 0.8) break
    out += ch
    w += cw
  }
  return `${out.trimEnd()}…`
}

/** An emoji-ish icon for a tool call kind (KiroCrew's live tool log). */
export function toolIcon(kind: string | null, tool: string): string {
  const k = (kind ?? '').toLowerCase()
  const t = tool.toLowerCase()
  if (k === 'read' || /read|cat\b|view/.test(t)) return '📖'
  if (k === 'write' || k === 'edit' || /write|edit|patch|replace/.test(t)) return '✏️'
  if (k === 'search' || /grep|glob|search|find/.test(t)) return '🔎'
  if (k === 'shell' || /bash|shell|exec|command/.test(t)) return '⌘'
  if (/web|fetch|http/.test(t)) return '🌐'
  return '🔧'
}

/** 'passed/total' parsed from a tests event's text ("测试 7/12"), or null. */
export function parseScore(text: string): { passed: number; total: number } | null {
  const m = /(\d+)\s*\/\s*(\d+)/.exec(text)
  if (!m) return null
  const passed = Number(m[1])
  const total = Number(m[2])
  return total > 0 && passed <= total ? { passed, total } : null
}

/** The lane an event is about, for filtering: its role, or the role at either end. */
export function eventTouches(e: { role: string | null; from: string | null; to: string | null }, role: string): boolean {
  return e.role === role || e.from === role || e.to === role
}

/** The 14 agents AWS AI-DLC ships (core/agents): 11 domain experts, 2 reviewers, 1 composer. */
export const AIDLC_AGENTS: ReadonlyArray<{ key: string; name: string }> = [
  { key: 'aidlc-product-agent', name: '产品' },
  { key: 'aidlc-architect-agent', name: '架构' },
  { key: 'aidlc-design-agent', name: '设计' },
  { key: 'aidlc-developer-agent', name: '开发' },
  { key: 'aidlc-quality-agent', name: '质量' },
  { key: 'aidlc-devsecops-agent', name: '安全' },
  { key: 'aidlc-compliance-agent', name: '合规' },
  { key: 'aidlc-pipeline-deploy-agent', name: '流水线部署' },
  { key: 'aidlc-aws-platform-agent', name: 'AWS 平台' },
  { key: 'aidlc-operations-agent', name: '运维' },
  { key: 'aidlc-delivery-agent', name: '交付' },
  { key: 'aidlc-architecture-reviewer-agent', name: '架构评审' },
  { key: 'aidlc-product-lead-agent', name: '产品负责人' },
  { key: 'aidlc-composer-agent', name: '组队 Composer' },
]

/** Experts a company adds to the official 14 (a Crew member of its own), by their member name. */
export const CUSTOM_EXPERTS: Readonly<Record<string, string>> = { 'taoyuan-motion-agent': '品牌动效' }

export const expertName = (key: string) => AIDLC_AGENTS.find((a) => a.key === key)?.name ?? CUSTOM_EXPERTS[key] ?? key

/** The experts a run shows: the official 14, then the company's own its roles use. */
/** The official expert a company's own copy of it stands for: a company's `acme-architect-agent` is AI-DLC's
 * `aidlc-architect-agent` with the company's working notes (example/agents/make_templates.py); "" for anything else. */
export function officialOf(member: string): string {
  const key = member.replace(/^[a-z0-9]+-(.+-agent)$/, 'aidlc-$1')
  return AIDLC_AGENTS.some((a) => a.key === key) ? key : ''
}

export function expertsOf(roles: ReadonlyArray<Pick<Lane, 'aidlc_agent'>>): { key: string; name: string; custom: boolean }[] {
  const official = new Set(AIDLC_AGENTS.map((a) => a.key))
  const custom = [...new Set(roles.flatMap((l) => l.aidlc_agent.split(',').map((x) => x.trim())).filter((k) => k && !official.has(k)))]
  return [...AIDLC_AGENTS.map((a) => ({ ...a, custom: false })), ...custom.map((k) => ({ key: k, name: expertName(k), custom: true }))]
}

/** The official agents a run's roles use (comma-separated per role), and those of roles at work right now. */
export function aidlcUse(roles: ReadonlyArray<Pick<Lane, 'aidlc_agent' | 'status'>>): { team: Set<string>; used: Set<string>; busy: Set<string> } {
  const split = (s: string) => s.split(',').map((x) => x.trim()).filter(Boolean)
  const team = new Set(roles.filter((l) => l.status !== 'skipped').flatMap((l) => split(l.aidlc_agent)))
  const used = new Set(roles.filter((l) => l.status !== 'skipped' && l.status !== 'waiting').flatMap((l) => split(l.aidlc_agent)))
  const busy = new Set(roles.filter((l) => LIVE.has(l.status) || l.status === 'queued').flatMap((l) => split(l.aidlc_agent)))
  return { team, used, busy }
}
