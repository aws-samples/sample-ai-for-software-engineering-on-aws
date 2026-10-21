/**
 * What changed between two consecutive snapshots of the same run (pure). Every animation on the board
 * comes from here, so every animation stands for a real change:
 *
 * - events newer than the previous snapshot's last `seq` become particles (handoff: along the edge
 *   from → to; merged: role → 运行分支; tests: 运行分支 → 测试, green or red by the score; bounce:
 *   测试 → role, red) or blips on a node (spawned, done, tool, committed, review, run), and conflict,
 *   violation and failed also flash the node red;
 * - test cases whose status changed flip; lanes whose status changed and merges that are new get a
 *   one-time highlight; the polite live region gets one sentence.
 *
 * The first snapshot of a run is history: nothing in it animates. So is a snapshot taken after the page
 * was hidden (a quiet catch-up), one whose events went backwards (the record restarted), and any event
 * more than LATE_S older than the snapshot (it still shows in the feed, it just does not fly).
 */
import type { LaneStatus, Merge, RunDetail, TeamEvent, TestCase } from '../types'
import type { Item, Prio, PTone, Shape } from './engine'
import { clip, parseScore, runMeta } from './format'
import { ORCH, RUN, TESTS } from './layout'

export const LATE_S = 30
export const MAX_ITEMS = 24

export interface Flash {
  key: string
  /** a role key, 'run' or 'tests' (all green flashes the station, a finished run every role) */
  target: string
  tone: 'bad' | 'ok'
  kind: string
}

export interface Flip {
  id: string
  from: TestCase['status']
  to: TestCase['status']
}

export interface LaneChange {
  key: string
  from: LaneStatus
  to: LaneStatus
}

export interface BoardDiff {
  run: string
  /** history (first snapshot, catch-up, restart): nothing animates */
  first: boolean
  /** events newer than the previous snapshot, oldest first (any age) */
  fresh: TeamEvent[]
  items: Item[]
  flashes: Flash[]
  flips: Flip[]
  /** mergeKey() of merges that are new */
  merges: string[]
  lanes: LaneChange[]
  announce: string | null
}

export interface DiffOptions {
  /** the snapshot's own time (Board.at): events much older than it do not fly */
  at?: number
  /** the page was hidden since the previous snapshot */
  resync?: boolean
  lateS?: number
  max?: number
}

export const maxSeq = (run: RunDetail) => run.events.reduce((m, e) => Math.max(m, e.seq), 0)
export const mergeKey = (m: Merge) => `${m.role}@${m.sha}@${m.status}`
export const eventKey = (run: string, seq: number) => `${run}#${seq}`

interface Ctx {
  roles: Set<string>
  tests: RunDetail['tests']
}

/** What a handoff hands over, from its text when the event carries no data:
 * 「验收标准交给架构师」 → 验收标准; 「产品经理把 验收标准 交给架构师」 → 验收标准. */
export function handoffLabel(text: string): string | null {
  const i = text.indexOf('交给')
  let what = i > 0 ? text.slice(0, i) : ''
  const ba = what.indexOf('把')
  if (ba >= 0) what = what.slice(ba + 1)
  what = what.trim()
  return what ? clip(what, 9) : null
}

/** The acceptance criteria a bounce names: 「AC-6、AC-7 失败，打回后端」 → AC-6、AC-7. */
export function bounceLabel(text: string): string | null {
  const acs = text.match(/AC-\d+/g)
  if (!acs?.length) return null
  return acs.length > 2 ? `${acs.slice(0, 2).join('、')}…` : acs.join('、')
}

/** An event as an engine item; null when nothing on the graph stands for it. */
export function eventItem(e: TeamEvent, runId: string, ctx: Ctx): Item | null {
  const base = { key: eventKey(runId, e.seq), t: e.at, kind: e.kind }
  const role = (k: string | null | undefined) => (k && ctx.roles.has(k) ? k : null)
  const blip = (at: string | null, tone: PTone, shape: Shape, prio: Prio): Item | null => (at ? { ...base, from: at, to: at, tone, shape, prio } : null)
  switch (e.kind) {
    case 'handoff': {
      const a = role(e.from)
      const b = role(e.to) ?? role(e.role)
      const carry = typeof e.data?.carry === 'string' && e.data.carry ? clip(e.data.carry, 9) : handoffLabel(e.text)
      if (a && b && a !== b) return { ...base, from: a, to: b, tone: 'handoff', shape: 'comet', prio: 2, label: carry }
      return blip(b ?? a, 'handoff', 'ring', 2)
    }
    case 'merged': {
      const a = role(e.from) ?? role(e.role)
      return a ? { ...base, from: a, to: RUN, tone: 'merge', shape: 'comet', prio: 3 } : blip(RUN, 'merge', 'check', 3)
    }
    case 'tests': {
      const given = typeof e.data?.passed === 'number' && typeof e.data?.total === 'number' ? { passed: e.data.passed, total: e.data.total } : null
      const score = given ?? parseScore(e.text) ?? (ctx.tests.total ? { passed: ctx.tests.passed, total: ctx.tests.total } : null)
      const green = !!score && score.passed === score.total
      return { ...base, from: RUN, to: TESTS, tone: green ? 'pass' : 'fail', shape: 'comet', prio: 3, label: score ? `${score.passed}/${score.total}` : null }
    }
    case 'bounce': {
      const b = role(e.to) ?? role(e.role)
      const cases = Array.isArray(e.data?.cases) ? e.data.cases.filter((c): c is string => typeof c === 'string') : []
      const label = cases.length ? (cases.length > 2 ? `${cases.slice(0, 2).join('、')}…` : cases.join('、')) : bounceLabel(e.text)
      if (e.from === 'person') return blip(b, 'bounce', 'cross', 3) // a person sent it back at a gate
      const src = role(e.from) ?? (e.from === RUN ? RUN : TESTS) // a review bounce leaves the reviewer
      return b ? { ...base, from: src, to: b, tone: 'bounce', shape: 'comet', prio: 3, label } : blip(TESTS, 'fail', 'cross', 3)
    }
    case 'conflict':
      return blip(role(e.role) ?? role(e.from), 'danger', 'cross', 3)
    case 'violation':
    case 'failed':
      return blip(role(e.role), 'danger', 'cross', 3)
    case 'spawned': {
      // the orchestrator dispatches it (a team without one: the node just rings)
      const r = role(e.role)
      return r ? { ...base, from: ORCH, to: r, tone: 'run', shape: 'comet', prio: 2, label: null } : null
    }
    case 'gate':
      return blip(role(e.role), 'info', 'ring', 3)
    case 'member':
      return blip(role(e.role), 'info', 'ring', 2)
    case 'talk':
      return blip(role(e.role), 'info', 'ring', 2)
    case 'approved':
      return blip(role(e.role), 'ok', 'check', 3)
    case 'ownership':
      return blip(ORCH, 'info', 'ring', 2)
    case 'skipped':
      return blip(role(e.role), 'tool', 'ring', 1)
    case 'done':
      return blip(role(e.role), 'ok', 'check', 2)
    case 'committed':
      return blip(role(e.role), 'info', 'spark', 1)
    case 'tool':
      return blip(role(e.role), 'tool', 'spark', 0)
    case 'review':
      return blip(role(e.role) ?? role('reviewer'), 'info', 'ring', 1)
    case 'run':
      return blip(RUN, 'info', 'ring', 2)
    default:
      return null
  }
}

/** The node flashes an event causes (besides its particle): the loud ones are red. */
export function eventFlashes(e: TeamEvent, runId: string, roles: Set<string>): Flash[] {
  const key = eventKey(runId, e.seq)
  const role = e.role && roles.has(e.role) ? e.role : e.from && roles.has(e.from) ? e.from : null
  switch (e.kind) {
    case 'conflict':
      return [...(role ? [{ key, target: role, tone: 'bad' as const, kind: e.kind }] : []), { key, target: RUN, tone: 'bad', kind: e.kind }]
    case 'violation':
    case 'failed':
      return role ? [{ key, target: role, tone: 'bad', kind: e.kind }] : []
    default:
      return []
  }
}

function quiet(run: string): BoardDiff {
  return { run, first: true, fresh: [], items: [], flashes: [], flips: [], merges: [], lanes: [], announce: null }
}

export function diffRuns(prev: RunDetail | null, next: RunDetail, opts: DiffOptions = {}): BoardDiff {
  const lateS = opts.lateS ?? LATE_S
  const max = opts.max ?? MAX_ITEMS
  if (!prev || prev.id !== next.id || opts.resync) return quiet(next.id)
  const before = maxSeq(prev)
  if (maxSeq(next) < before) return quiet(next.id)

  const fresh = next.events.filter((e) => e.seq > before).sort((a, b) => a.seq - b.seq)
  const roles = new Set(next.roles.map((r) => r.key))
  const ctx: Ctx = { roles, tests: next.tests }
  let items: Item[] = []
  const flashes: Flash[] = []
  for (const e of fresh) {
    if (opts.at !== undefined && opts.at - e.at > lateS) continue
    const it = eventItem(e, next.id, ctx)
    if (it) items.push(it)
    flashes.push(...eventFlashes(e, next.id, roles))
  }
  // two transitions of the whole run get one flash each, on everything they are about
  if (next.tests.total > 0 && next.tests.failed === 0 && (prev.tests.failed > 0 || prev.tests.total !== next.tests.total))
    flashes.push({ key: `${next.id}#green@${next.tests.at ?? ''}`, target: TESTS, tone: 'ok', kind: 'tests' })
  if (prev.status !== 'done' && next.status === 'done') for (const l of next.roles) flashes.push({ key: `${next.id}#done`, target: l.key, tone: 'ok', kind: 'run' })
  if (items.length > max) {
    // the most important ones fly; ties: the older first
    items = items
      .slice()
      .sort((a, b) => b.prio - a.prio || a.t - b.t)
      .slice(0, max)
      .sort((a, b) => a.t - b.t)
  }

  const was = new Map(prev.tests.cases.map((c) => [c.id, c.status]))
  const flips: Flip[] = next.tests.cases.filter((c) => was.has(c.id) && was.get(c.id) !== c.status).map((c) => ({ id: c.id, from: was.get(c.id)!, to: c.status }))

  const wasLane = new Map(prev.roles.map((l) => [l.key, l.status]))
  const lanes: LaneChange[] = next.roles.filter((l) => wasLane.has(l.key) && wasLane.get(l.key) !== l.status).map((l) => ({ key: l.key, from: wasLane.get(l.key)!, to: l.status }))

  const had = new Set(prev.merges.map(mergeKey))
  const merges = next.merges.map(mergeKey).filter((k) => !had.has(k))

  return { run: next.id, first: false, fresh, items, flashes, flips, merges, lanes, announce: announce(prev, next, fresh) }
}

/** One sentence for the polite live region: the most important change of this poll (or null). */
function announce(prev: RunDetail, next: RunDetail, fresh: TeamEvent[]): string | null {
  const parts: string[] = []
  if (prev.status !== next.status) parts.push(`运行${runMeta(next.status).label}`)
  if (prev.tests.passed !== next.tests.passed || prev.tests.total !== next.tests.total) parts.push(`测试 ${prev.tests.passed}/${prev.tests.total} → ${next.tests.passed}/${next.tests.total}`)
  const loud = [...fresh].reverse().find((e) => e.kind === 'bounce' || e.kind === 'conflict' || e.kind === 'violation' || e.kind === 'failed')
  if (loud) parts.push(loud.text)
  if (parts.length < 2) {
    const calm = [...fresh].reverse().find((e) => e.kind === 'merged' || e.kind === 'handoff' || e.kind === 'done')
    if (calm) parts.push(calm.text)
  }
  return parts.length ? parts.slice(0, 2).join('；') : null
}
