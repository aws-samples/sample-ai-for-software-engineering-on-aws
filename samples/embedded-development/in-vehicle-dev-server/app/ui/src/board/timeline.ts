/**
 * 回放: a finished run, played again. The board at any moment *t* of the run, rebuilt from its event log (every event,
 * GET /runs/{id}/events) and its final record: who had been dispatched, was working, was sent back, merged, failed; the
 * gates; the test wall as the last test run before *t* left it; the merges, the deployment, the knowledge lookups.
 * Pure: the same run and *t* always give the same board, so the replay can be scrubbed back and forth. What the log
 * does not carry is not made up: a member's credits show once its last round is over (the record has only the total);
 * its last tool call is the last one logged.
 */
import type { AgentLive, Lane, LaneStatus, Msg, RunDetail, RunStatus, TeamEvent, TestCase } from '../types'
import { msgText } from '../i18n/events'

export interface ReplaySpan {
  start: number
  end: number
}

/** When the run happened: its first event to its end (or its last event). */
export function replaySpan(run: RunDetail, events: TeamEvent[]): ReplaySpan {
  const start = run.started_at
  const last = events.length ? Math.max(...events.map((e) => e.at)) : start
  return { start, end: Math.max(run.ended_at ?? last, last, start + 1) }
}

interface RoleState {
  status: LaneStatus
  attempts: number
  doing: string
  doingMsg: Msg | null // the round's label by code (label.*): the board says it in English
  summary: string | null
  spans: { a: number; b: number | null }[]
  gate: 'pending' | 'discussing' | 'approved' | null
  lastTool: string
  lastAt: number | null
}

// an older run's events have no code: what follows the colon of their Chinese text
const afterColon = (text: string) => {
  const i = text.indexOf('：') // i18n-keep: parses the backend's Chinese text
  return i >= 0 ? text.slice(i + 1).trim() : ''
}
/** A param of the event's code, else what follows the colon of its text. */
const said = (e: TeamEvent, code: string, name: string): string =>
  e.code ? (e.code === code && e.params?.[name] != null ? String(e.params[name]) : '') : afterColon(e.text)

/** The board of *run* as it stood at *t* (seconds since the epoch, between its start and end). */
export function replayAt(run: RunDetail, events: TeamEvent[], t: number): RunDetail {
  const span = replaySpan(run, events)
  if (t >= span.end) return { ...run, events: run.events }
  const seen = events.filter((e) => e.at <= t).sort((a, b) => a.seq - b.seq)
  const byKey = new Map(run.roles.map((l) => [l.key, l]))
  const st = new Map<string, RoleState>()
  // a role that sat the run out is skipped from its 「skipped」 event on (未入职 at the start, 这次用不到 at the gate)
  const outAt = new Set(events.filter((e) => e.kind === 'skipped' && e.role).map((e) => e.role as string))
  for (const l of run.roles) {
    st.set(l.key, { status: l.status === 'skipped' && !outAt.has(l.key) ? 'skipped' : 'waiting', attempts: 0, doing: l.assignment, doingMsg: null, summary: null,
      spans: [], gate: null, lastTool: '', lastAt: null })
  }
  const close = (s: RoleState, at: number) => {
    const open = s.spans[s.spans.length - 1]
    if (open && open.b === null) open.b = at
  }
  let lastTests: TeamEvent | null = null
  const history: { at: number; passed: number; failed: number }[] = []
  for (const e of seen) {
    const s = e.role ? st.get(e.role) : undefined
    switch (e.kind) {
      case 'spawned':
        if (s) {
          s.attempts += 1
          s.status = s.attempts > 1 && byKey.get(e.role!)?.writable.length ? 'fixing' : 'running' // a reviewer's second look is not a fix
          s.spans.push({ a: e.at, b: null })
          const given = e.code === 'spawned.round' ? e.params?.label : undefined
          const msg = given && typeof given === 'object' && typeof (given as Msg).code === 'string' ? given as Msg : null
          const label = msg ? msgText(msg.code, msg.params) : e.code ? said(e, 'spawned.round', 'label')
            : /第 \d+ 轮：/.test(e.text) ? afterColon(e.text) : '' // i18n-keep: an older run's text
          s.doing = label || byKey.get(e.role!)?.assignment || ''
          s.doingMsg = label ? msg : null
        }
        break
      case 'tool':
        if (s) {
          s.lastTool = said(e, 'tool', 'tool') || e.text
          s.lastAt = e.at
        }
        break
      case 'done':
        if (s) {
          close(s, e.at)
          s.status = 'done'
          s.summary = said(e, 'done', 'summary') || s.summary
        }
        break
      case 'review':
        if (s) {
          close(s, e.at)
          s.status = 'done'
          s.summary = said(e, 'review', 'summary') || s.summary
        }
        break
      case 'merged':
        if (s) {
          close(s, e.at)
          s.status = 'merged'
        }
        break
      case 'failed':
        if (s) {
          close(s, e.at)
          s.status = 'failed'
        }
        break
      case 'skipped':
        if (s) {
          s.status = 'skipped'
          s.summary = byKey.get(e.role!)?.summary ?? null
        }
        break
      case 'gate':
        if (s) s.gate = 'pending'
        break
      case 'talk': // the person opened a 讨论: it answers, and the next gate event opens the gate again
        if (s && e.from === 'person') s.gate = 'discussing'
        break
      case 'approved':
        if (s) s.gate = 'approved'
        break
      case 'bounce': {
        const to = e.to ? st.get(e.to) : undefined
        if (e.from === 'person' && to) {
          to.gate = null // a person sent it back at the gate: a reviewer waits for the fixes, a writer redoes its part
          if (!byKey.get(e.to!)?.writable.length) to.status = 'waiting'
        } else if (to && to.status !== 'waiting') to.status = 'fixing'
        break
      }
      case 'tests': {
        lastTests = e
        const d = e.data as { passed?: number; total?: number } | null
        if (d && typeof d.passed === 'number' && typeof d.total === 'number') history.push({ at: e.at, passed: d.passed, failed: d.total - d.passed })
        break
      }
      default:
        break
    }
  }

  const roles: Lane[] = run.roles.map((l) => {
    const s = st.get(l.key)!
    const active = s.spans.reduce((n, sp) => n + Math.max(0, (sp.b ?? t) - sp.a), 0)
    const open = s.spans[s.spans.length - 1]
    const live = s.status === 'running' || s.status === 'fixing'
    const agent: AgentLive | null = live && open
      ? { id: `replay-${l.key}`, turns: 0, tool_count: 0, last_tool: s.lastTool, last_activity: s.lastAt ?? open.a, started: open.a,
          elapsed_s: Math.max(0, t - open.a), queued_reason: null, error: null, recent_tools: [], text_tail: null, credits: null }
      : null
    const finished = s.status === 'merged' || s.status === 'done'
    const over = s.attempts >= l.attempt && !live && s.status !== 'waiting' // its last round is behind it
    return {
      ...l,
      status: s.status,
      attempt: Math.max(1, s.attempts),
      agent,
      doing: s.doing,
      doing_msg: s.doingMsg,
      summary: finished || s.status === 'failed' || s.status === 'skipped' ? s.summary ?? l.summary : null,
      active_s: Math.round(active * 10) / 10,
      started_at: s.spans[0]?.a ?? null,
      done_at: finished ? s.spans[s.spans.length - 1]?.b ?? null : null,
      gate: l.gate_label ? s.gate : l.gate,
      credits: over ? l.credits : null,
      files: s.status === 'merged' ? l.files : [],
      lines: s.status === 'merged' ? l.lines : { added: 0, removed: 0 },
      commits: l.commits.filter((c) => c.at <= t),
      kinds: l.kinds.slice(0, Math.max(1, s.attempts)),
    }
  })

  // the test wall: the cases the last test run before t had, with the statuses it gave them
  const statusOf = new Map<string, TestCase['status']>()
  const last = lastTests as TeamEvent | null
  const d = (last?.data ?? null) as { passed?: number; total?: number; cases?: [string, TestCase['status']][] } | null
  for (const [id, status] of d?.cases ?? []) statusOf.set(id, status)
  // a check's verdict as that run gave it (the record keeps the last verdict only): PASS, or the last one that was not
  const verdictAt = (c: TestCase, st: TestCase['status']): TestCase['verdict'] => (!c.verdict ? c.verdict : st === 'pass' ? 'PASS' : c.verdict !== 'PASS' ? c.verdict : 'FAIL')
  const cases = run.tests.cases.filter((c) => statusOf.has(c.id)).map((c) => ({ ...c, status: statusOf.get(c.id)!, verdict: verdictAt(c, statusOf.get(c.id)!), message: statusOf.get(c.id) === 'fail' ? c.message : null }))
  const passed = d?.passed ?? cases.filter((c) => c.status === 'pass').length
  const total = d?.total ?? cases.length
  const tests = { ...run.tests, at: last?.at ?? null, cases, passed, failed: total - passed, total, history }

  const gating = roles.some((l) => l.gate === 'pending')
  const reviewing = roles.some((l) => l.writable.length === 0 && (l.status === 'running' || l.status === 'fixing'))
  const status: RunStatus = gating ? 'gating' : reviewing ? 'reviewing' : 'running'
  const spent = roles.filter((l) => l.credits !== null)
  return {
    ...run,
    status,
    ended_at: null,
    wall_s: Math.round(Math.max(0, t - span.start) * 10) / 10,
    serial_s: roles.reduce((n, l) => n + l.active_s, 0),
    credits: spent.length ? spent.reduce((n, l) => n + (l.credits ?? 0), 0) : null,
    roles,
    tests,
    merges: run.merges.filter((m) => m.at <= t),
    bench: run.bench ? { ...benchAt(run.bench, t), step: benchStepAt(seen), running: null, held: null } : run.bench,
    events: seen.slice(-200),
    gate_notes: Object.fromEntries(Object.entries(run.gate_notes).filter(([k]) => roles.find((l) => l.key === k)?.gate === 'approved')),
    signoff: null,
    knowledge: { ...run.knowledge, hits: run.knowledge.hits.filter((h) => h.at <= t) },
  }
}

// the app's step on the bench that each of its bench events starts (team.py's bench steps)
const BENCH_STEP: Record<string, NonNullable<NonNullable<RunDetail['bench']>['step']>> = {
  'bench.go': 'doctor', 'bench.deploy': 'deploy', 'bench.replay': 'replay', 'bench.replayed': 'after', 'bench.rerun': 'rerun', 'run.done_ok': 'done',
}

/** The app's step on the bench after the events seen so far: none before it went to the bench. */
export function benchStepAt(seen: TeamEvent[]): NonNullable<RunDetail['bench']>['step'] {
  let step: NonNullable<RunDetail['bench']>['step'] = null
  for (const e of seen) if (e.code && e.code in BENCH_STEP && (e.code !== 'run.done_ok' || step)) step = BENCH_STEP[e.code]
  return step
}

const epoch = (x: unknown) => { const n = Date.parse(String(x ?? '')); return Number.isFinite(n) ? n / 1000 : null }

/** The bench as it stood at *t*: from the run's own part of the action record (BenchView.history), not the bench
 * as it is now. Without a history (an older reply) the bench is shown as it is. */
export function benchAt(bench: NonNullable<RunDetail['bench']>, t: number): NonNullable<RunDetail['bench']> {
  if (!bench.history) return bench
  const seen = bench.history.filter((r) => (epoch(r.at) ?? Infinity) <= t)
  const last = (event: string) => [...seen].reverse().find((r) => r.event === event)
  const target = last('target')
  const supply = last('supply')
  const decided = new Set(seen.filter((r) => r.event === 'decision').map((r) => String(r.id)))
  const pending = seen.filter((r) => r.event === 'request' && !decided.has(String(r.id))).map((r) => ({
    id: String(r.id), action: String(r.action ?? ''), digest: String(r.digest ?? ''), detail: String(r.detail ?? ''),
    requested_at: String(r.at ?? ''), requested_by: String(r.requested_by ?? ''), expired: false,
  }))
  return {
    ...bench,
    state: {
      ...bench.state,
      target: target ? { state: target.state, why: target.why } : { state: 'off', why: '' },
      supply: supply ? { voltage_v: supply.voltage_v, kl15: supply.kl15, set_by: supply.by } : bench.state.supply,
      pending,
      actions: seen,
    },
  }
}

