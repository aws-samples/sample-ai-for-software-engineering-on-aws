/**
 * Words, tones and number formats every part of the board shares. Pure: no React, no DOM.
 *
 * A tone is a meaning, not a colour: styles.ts maps each to a colour per host mode (kiro-dark /
 * kiro-light), so the same word always has the same colour and every colour has a word next to it.
 */
import type { Lane, LaneStatus, RunDetail, RunStatus, TeamEventKind, TestCase } from '../types'
import { t as tr } from '../i18n'

export const BASE = '/api/apps/vstatd-team'
export const POLL_MS = 2000
const enc = encodeURIComponent

export const paths = {
  board: (run?: string | null) => `${BASE}/board${run ? `?run=${enc(run)}` : ''}`,
  runs: () => `${BASE}/runs`,
  scorecard: () => `${BASE}/scorecard`,
  stop: (run: string) => `${BASE}/runs/${enc(run)}/stop`,
  role: (run: string, role: string) => `${BASE}/runs/${enc(run)}/roles/${enc(role)}`,
  file: (run: string, role: string, path: string, view: 'content' | 'diff') =>
    `${BASE}/runs/${enc(run)}/roles/${enc(role)}/file?path=${enc(path)}&view=${view}`,
  retry: (run: string) => `${BASE}/runs/${enc(run)}/retry`,
  finding: (run: string) => `${BASE}/runs/${enc(run)}/finding`,
  gate: (run: string) => `${BASE}/runs/${enc(run)}/gate`,
  open: (run: string) => `${BASE}/runs/${enc(run)}/open`,
  cleanup: () => `${BASE}/sessions/cleanup`,
  signoff: (run: string) => `${BASE}/runs/${enc(run)}/signoff`,
  hide: (run: string) => `${BASE}/runs/${enc(run)}/hide`,
  events: (run: string) => `${BASE}/runs/${enc(run)}/events`,
  flow: (run: string) => `${BASE}/runs/${enc(run)}/flow`,
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
  waiting: { label: tr('board.format.1'), tone: 'idle', icon: '⏳', hint: tr('board.format.2') },
  queued: { label: tr('board.format.3'), tone: 'queue', icon: '⏸', hint: tr('board.format.4') },
  running: { label: tr('board.format.5'), tone: 'run', icon: '●', hint: tr('board.format.6') },
  stalled: { label: tr('board.format.7'), tone: 'warn', icon: '⚠', hint: tr('board.format.8') },
  awaiting_approval: { label: tr('board.format.9'), tone: 'approve', icon: '✋', hint: tr('board.format.10') },
  done: { label: tr('board.format.11'), tone: 'done', icon: '✓', hint: tr('board.format.12') },
  merged: { label: tr('board.format.13'), tone: 'ok', icon: '✔', hint: tr('board.format.14') },
  fixing: { label: tr('board.format.15'), tone: 'fix', icon: '↻', hint: tr('board.format.16') },
  failed: { label: tr('board.format.17'), tone: 'bad', icon: '✕', hint: tr('board.format.18') },
  skipped: { label: tr('board.format.19'), tone: 'idle', icon: '–', hint: tr('board.format.20') },
}

export const RUN_META: Record<RunStatus, { label: string; tone: Tone; active: boolean }> = {
  starting: { label: tr('board.format.21'), tone: 'run', active: true },
  running: { label: tr('board.format.22'), tone: 'run', active: true },
  fixing: { label: tr('board.format.15'), tone: 'fix', active: true },
  reviewing: { label: tr('board.format.23'), tone: 'run', active: true },
  gating: { label: tr('board.format.9'), tone: 'approve', active: true },
  done: { label: tr('board.format.24'), tone: 'ok', active: false },
  failed: { label: tr('board.format.17'), tone: 'bad', active: false },
  stopped: { label: tr('board.format.25'), tone: 'idle', active: false },
}

export const EVENT_META: Record<TeamEventKind, { icon: string; label: string; tone: Tone }> = {
  run: { icon: '🏁', label: tr('board.format.26'), tone: 'info' },
  handoff: { icon: '📨', label: tr('board.format.27'), tone: 'handoff' },
  spawned: { icon: '▶️', label: tr('board.format.28'), tone: 'run' },
  tool: { icon: '🔧', label: tr('board.format.29'), tone: 'idle' },
  committed: { icon: '📝', label: tr('board.format.30'), tone: 'info' },
  merged: { icon: '⤵️', label: tr('board.format.31'), tone: 'ok' },
  conflict: { icon: '⚡', label: tr('board.format.32'), tone: 'bad' },
  tests: { icon: '🧪', label: tr('board.format.33'), tone: 'info' },
  bounce: { icon: '↩️', label: tr('board.format.34'), tone: 'bad' },
  violation: { icon: '🚫', label: tr('board.format.35'), tone: 'bad' },
  done: { icon: '✅', label: tr('board.format.36'), tone: 'ok' },
  failed: { icon: '❌', label: tr('board.format.17'), tone: 'bad' },
  review: { icon: '🔍', label: tr('board.format.37'), tone: 'info' },
  ownership: { icon: '🧭', label: tr('board.format.38'), tone: 'info' },
  skipped: { icon: '–', label: tr('board.format.19'), tone: 'idle' },
  gate: { icon: '✋', label: tr('board.format.39'), tone: 'approve' },
  approved: { icon: '👍', label: tr('board.format.40'), tone: 'ok' },
  finding: { icon: '📌', label: tr('board.format.41'), tone: 'approve' },
  signoff: { icon: '✍️', label: tr('board.format.42'), tone: 'approve' },
  plan: { icon: '🗂️', label: tr('board.format.43'), tone: 'handoff' },
  member: { icon: '⏸', label: tr('board.format.44'), tone: 'warn' },
  talk: { icon: '💬', label: tr('board.format.45'), tone: 'approve' },
  bench: { icon: '🔌', label: tr('board.format.46'), tone: 'info' },
}

export const CASE_META: Record<TestCase['status'], { label: string; glyph: string }> = {
  pass: { label: tr('board.format.47'), glyph: '✓' },
  fail: { label: tr('board.format.17'), glyph: '✕' },
  skip: { label: tr('board.format.19'), glyph: '–' },
  blocked: { label: tr('board.format.48'), glyph: '!' },
}

/** The meaning of a lane's status: a role that writes nothing (the reviewer) has nothing to merge, so
 * for it `done` is the end (完成), not 完成·待合并. */
export function laneMeta(lane: Pick<Lane, 'status' | 'writable'>): StatusMeta {
  if (lane.status === 'done' && lane.writable.length === 0) return { label: tr('board.format.36'), tone: 'ok', icon: '✔', hint: tr('board.format.49') }
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
  { key: 'ideation', n: '1', title: tr('board.format.50'), en: 'Ideation' },
  { key: 'inception', n: '2', title: tr('board.format.51'), en: 'Inception' },
  { key: 'construction', n: '3', title: tr('board.format.52'), en: 'Construction' },
  { key: 'review', n: '✓', title: tr('board.format.53'), en: 'Review gate' },
  { key: 'operation', n: '4', title: tr('board.format.54'), en: 'Operation' },
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
  if (s < 60) return tr('board.format.55', { p0: s })
  const m = Math.round(s / 60)
  if (m < 60) return tr('board.format.56', { p0: m })
  const h = Math.floor(m / 60)
  const mm = m % 60
  return mm ? tr('board.format.57', { p0: h, p1: mm }) : tr('board.format.58', { p0: h })
}

export function fmtAgo(delta: number): string {
  const s = Math.max(0, Math.round(delta))
  if (s < 5) return tr('board.format.59')
  if (s < 60) return tr('board.format.60', { p0: s })
  const m = Math.floor(s / 60)
  if (m < 60) return tr('board.format.61', { p0: m })
  const h = Math.floor(m / 60)
  if (h < 24) return tr('board.format.62', { p0: h })
  return tr('board.format.63', { p0: Math.floor(h / 24) })
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
  if (w.length) return tr('board.format.64', { p0: w.map((l) => l.title).join(tr('common.sep')) })
  return lane.depends_on.length ? tr('board.format.65') : tr('board.format.66')
}

/** 'AC-12' → 12 (sorting); no number → a big one, last. */
/** Case-id groups, in wall order: 功能验收 AC，然后是规范包里的安全 SEC、体验 UX、合规 COMP、上架 STORE. */
export const CASE_GROUPS: { prefix: string; label: string }[] = [
  { prefix: 'AC', label: tr('board.format.67') },
  { prefix: 'RULE', label: tr('board.format.68') },
  { prefix: 'ACC', label: tr('board.format.69') },
  { prefix: 'PII', label: tr('board.format.70') },
  { prefix: 'SEC', label: tr('board.format.71') },
  { prefix: 'FE', label: tr('board.format.72') },
  { prefix: 'UX', label: tr('board.format.73') },
  { prefix: 'BR', label: tr('board.format.74') },
  { prefix: 'COMP', label: tr('board.format.75') },
  { prefix: 'STORE', label: tr('board.format.76') },
  { prefix: 'PRC', label: tr('board.format.77') },
  { prefix: 'MGN', label: tr('board.format.78') },
  { prefix: 'PP', label: tr('board.format.79') },
  { prefix: 'DATA', label: tr('board.format.80') },
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
  { key: 'aidlc-product-agent', name: tr('board.format.81') },
  { key: 'aidlc-architect-agent', name: tr('board.format.82') },
  { key: 'aidlc-design-agent', name: tr('board.format.83') },
  { key: 'aidlc-developer-agent', name: tr('board.format.84') },
  { key: 'aidlc-quality-agent', name: tr('board.format.85') },
  { key: 'aidlc-devsecops-agent', name: tr('board.format.71') },
  { key: 'aidlc-compliance-agent', name: tr('board.format.75') },
  { key: 'aidlc-pipeline-deploy-agent', name: tr('board.format.86') },
  { key: 'aidlc-aws-platform-agent', name: tr('board.format.87') },
  { key: 'aidlc-operations-agent', name: tr('board.format.54') },
  { key: 'aidlc-delivery-agent', name: tr('board.format.88') },
  { key: 'aidlc-architecture-reviewer-agent', name: tr('board.format.89') },
  { key: 'aidlc-product-lead-agent', name: tr('board.format.90') },
  { key: 'aidlc-composer-agent', name: tr('board.format.91') },
]

/** Experts a company adds to the official 14 (a Crew member of its own), by their member name. */
export const CUSTOM_EXPERTS: Readonly<Record<string, string>> = { 'taoyuan-motion-agent': tr('board.format.92') }

export const expertName = (key: string) => AIDLC_AGENTS.find((a) => a.key === key)?.name ?? CUSTOM_EXPERTS[key] ?? key

/** The experts a run shows: the official 14, then the company's own its roles use. */
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
