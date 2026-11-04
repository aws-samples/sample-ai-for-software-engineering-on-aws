/**
 * The vstatd team's flow from the backlog to sign-off (team/team-vstatd.json, docs/kiro-crew-app.md D3–D10): the
 * steps, who acts at each (an agent role, a person, the app itself, the bench with its operator console), and, for a
 * run, where it is and who must do what next. Pure: no React. flow.test.ts keeps the role keys and check names in step
 * with the team file.
 */
import { evText, signBlock } from '../i18n/events'
import type { Lane, RunDetail } from '../types'
import { FINISHED, LIVE } from './format'
import { t as tr } from '../i18n'

export type Who = 'agent' | 'person' | 'app' | 'bench'
export const WHO_LABEL: Record<Who, string> = { agent: tr('board.flow.1'), person: tr('board.flow.2'), app: tr('board.flow.3'), bench: tr('board.flow.4') }

export type FlowKey = 'triage' | 'gate-triage' | 'architect' | 'gate-start' | 'tests-first' | 'dev' | 'before' | 'review' | 'bench' | 'after' | 'rerun' | 'signoff'

export interface FlowStepDef {
  key: FlowKey
  n: string // its number; '' for a gate between two steps
  title: string
  who: Who[]
  does: string
  roles?: string[] // the team file's roles that act here (a gate: the role whose gate it is)
  checks?: string[] // the team file's checks the app runs here
}

export const FLOW: FlowStepDef[] = [
  { key: 'triage', n: '1', title: tr('board.flow.5'), who: ['agent'], roles: ['triage'], does: tr('board.flow.6') },
  { key: 'gate-triage', n: '', title: tr('board.flow.7'), who: ['person'], roles: ['triage'], does: tr('board.flow.8') },
  { key: 'architect', n: '2', title: tr('board.flow.9'), who: ['agent'], roles: ['architect'], does: tr('board.flow.10') },
  { key: 'gate-start', n: '', title: tr('board.flow.11'), who: ['person'], roles: ['architect'], does: tr('board.flow.12') },
  { key: 'tests-first', n: '3', title: tr('board.flow.13'), who: ['agent', 'app'], roles: ['tester'], does: tr('board.flow.14') },
  { key: 'dev', n: '4', title: tr('board.flow.15'), who: ['agent'], roles: ['dev-fix', 'dev-refactor'], does: tr('board.flow.16') },
  { key: 'before', n: '5', title: tr('board.flow.17'), who: ['app'], checks: ['build', 'static', 'unit', 'size', 'trace'], does: tr('board.flow.18') },
  { key: 'review', n: '6', title: tr('board.flow.19'), who: ['agent'], roles: ['reviewer'], does: tr('board.flow.20') },
  { key: 'bench', n: '7', title: tr('board.flow.21'), who: ['bench'], does: tr('board.flow.22') },
  { key: 'after', n: '8', title: tr('board.flow.23'), who: ['app'], checks: ['logdiff', 'runtime-limits'], does: tr('board.flow.24') },
  { key: 'rerun', n: '9', title: tr('board.flow.25'), who: ['app'], checks: ['release'], does: tr('board.flow.26') },
  { key: 'signoff', n: '10', title: tr('board.flow.27'), who: ['person'], does: tr('board.flow.28') },
]

export type StepState = 'todo' | 'current' | 'done' | 'failed' | 'held'

export interface Flow {
  steps: { def: FlowStepDef; state: StepState }[]
  current: FlowKey | null // null: signed off, every step done
  now: string // 现在：who must do what next
}

const BENCH_ACTION: Record<string, string> = { deploy: tr('board.flow.29'), replay: tr('board.flow.30') }

/** Where *run* is in the flow, which steps are done, failed or held for a person, and what comes next. */
export function flowOf(run: RunDetail): Flow {
  const lane = (k: string): Lane | undefined => run.roles.find((l) => l.key === k)
  const busy = (l?: Lane) => !!l && (LIVE.has(l.status) || l.status === 'queued')
  const finished = (l?: Lane) => !l || l.status === 'skipped' || (FINISHED.has(l.status) && !busy(l))
  const gateOpen = (l?: Lane) => l?.gate === 'pending' || l?.gate === 'discussing'
  const lastKind = (l?: Lane) => (l && l.kinds.length ? l.kinds[l.kinds.length - 1] : '')
  const triage = lane('triage'), architect = lane('architect'), tester = lane('tester'), reviewer = lane('reviewer')
  const devs = ['dev-fix', 'dev-refactor'].map(lane).filter((l): l is Lane => !!l)
  const t = run.tests, bench = run.bench, rel = run.release
  const step = bench?.step ?? null

  const done: Record<FlowKey, boolean> = {
    triage: !busy(triage) && (finished(triage) || gateOpen(triage) || triage?.gate === 'approved'),
    'gate-triage': !triage || triage.gate === 'approved',
    architect: !busy(architect) && (finished(architect) || gateOpen(architect) || architect?.gate === 'approved'),
    'gate-start': !architect || architect.gate === 'approved',
    'tests-first': finished(tester) && (tester?.tests_first === 'passed' || (tester?.tests_first == null && devs.some((l) => l.status !== 'waiting'))),
    dev: devs.every(finished),
    before: t.total > 0 && t.failed === 0 && !t.held && !t.running,
    review: finished(reviewer),
    bench: step === 'after' || step === 'rerun' || step === 'done',
    after: step === 'rerun' || step === 'done',
    rerun: step === 'done' && (!rel || rel.release.verdict === 'PASS'),
    signoff: !!run.signoff,
  }
  const at = FLOW.findIndex((s) => !done[s.key])
  if (at < 0) return { steps: FLOW.map((def) => ({ def, state: 'done' })), current: null, now: tr('board.flow.31', { p0: run.signoff?.by ?? tr('board.flow.releaseOwner') }) }
  const cur = FLOW[at].key
  const marks: Partial<Record<FlowKey, StepState>> = {}
  let state: StepState = 'current'
  let now = ''

  const held = (cur === 'before' && t.held) || (['bench', 'after', 'rerun', 'signoff'].includes(cur) && bench?.held) || (run.status === 'failed' && (t.held || bench?.held)) || null
  const failedLane = run.roles.find((l) => l.status === 'failed')
  const asking = run.roles.find((l) => l.status === 'awaiting_approval')
  const titles = (ls: Lane[]) => ls.map((l) => l.title).join(tr('board.flow.32'))
  if (held) {
    state = 'held'
    now = tr('board.flow.33', { p0: evText({ text: held.why, ...('code' in held && held.code ? { code: held.code, params: held.params } : {}) }, run.roles) })
  } else if (run.status === 'stopped') {
    state = 'failed'
    now = tr('board.flow.34')
  } else if (failedLane) {
    state = 'failed'
    now = tr('board.flow.35', { p0: failedLane.title })
  } else if (asking) {
    now = tr('board.flow.36', { p0: asking.title })
  } else if (cur === 'triage') {
    now = busy(triage) ? tr('board.flow.37') : tr('board.flow.38')
  } else if (cur === 'gate-triage') {
    now = triage?.gate === 'discussing' ? tr('board.flow.39') : tr('board.flow.40')
  } else if (cur === 'architect') {
    now = tr('board.flow.41')
  } else if (cur === 'gate-start') {
    now = architect?.gate === 'discussing' ? tr('board.flow.42') : tr('board.flow.43')
  } else if (cur === 'tests-first') {
    if (busy(tester) && tester?.tests_first === 'sent_back') now = tr('board.flow.44')
    else now = busy(tester) || !finished(tester) ? tr('board.flow.45') : tr('board.flow.46')
  } else if (cur === 'dev') {
    const working = devs.filter(busy)
    const fixing = working.filter((l) => lastKind(l) === 'fix')
    const reviewed = working.filter((l) => lastKind(l) === 'review')
    if (fixing.length) {
      marks[step === 'after' && !bench?.running ? 'after' : 'before'] = 'failed'
      now = tr('board.flow.47', { p0: titles(fixing), p1: Math.max(1, t.round || 0) })
    } else if (reviewed.length) {
      marks.review = 'failed'
      now = tr('board.flow.48', { p0: titles(reviewed) })
    } else now = working.length ? tr('board.flow.49', { p0: titles(working) }) : tr('board.flow.50')
  } else if (cur === 'before') {
    now = t.running || t.at === null ? tr('board.flow.51', { p0: Math.max(1, t.round || 0) }) : tr('board.flow.52')
  } else if (cur === 'review') {
    now = tr('board.flow.53')
  } else if (cur === 'bench') {
    const action = step ? BENCH_ACTION[step] : undefined
    const req = action ? bench?.state.pending.find((r) => r.action === step && !r.expired) : undefined
    if (req) {
      const d = req.digest.slice(0, 6)
      now = tr('board.flow.54', { p0: action, p1: d })
    } else if (action) now = tr('board.flow.55', { p0: action })
    else now = step === 'doctor' ? tr('board.flow.56') : tr('board.flow.57')
  } else if (cur === 'after') {
    now = tr('board.flow.58')
  } else if (cur === 'rerun') {
    now = tr('board.flow.59')
  } else {
    now = run.sign_block ? tr('board.flow.60', { p0: signBlock(run) }) : tr('board.flow.61')
  }

  return {
    steps: FLOW.map((def, i) => ({ def, state: i < at ? marks[def.key] ?? 'done' : i === at ? state : marks[def.key] ?? 'todo' })),
    current: cur,
    now,
  }
}
