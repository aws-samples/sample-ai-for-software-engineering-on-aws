/**
 * The app's views and the ways into them, as the page URL carries them (a link can open any of them, and the browser's
 * back and forward step between them: a move to another view is a history entry, a change inside a view — the run
 * picked — replaces the current one):
 *
 *   ?view=board                              团队看板 (the default: the newest active run, else the newest)
 *   ?view=board&run=<id>                     that run
 *     &phase=<ideation|inception|…>          …its AI-DLC phase picked out (a finished run: its replay paused where it began)
 *     &gate=<role> / &role=<role>            …the team graph focused on that role (its gate)
 *     &at=<seconds>                          …a finished run's replay, paused that many seconds after its start
 *     &replay=<speed>                        …its replay, playing at that speed
 *     &focus=signoff|tests|cost|lanes        …its 签字单, its 测试墙, its counters, its lanes (each member's use)
 *   ?view=board&new=promo                    the 新需求 form
 *   ?view=score                              评分卡 (scorecard/ScorecardView.tsx)
 *   ?view=item&run=<id>                      交付详情 of that run (item/ItemView.tsx)
 */

export type BoardFocus = 'signoff' | 'tests' | 'cost' | 'lanes'
export type BoardEntry = {
  run?: string; gate?: string; role?: string; phase?: string; at?: number; replay?: number; focus?: BoardFocus; new?: 'promo'
}
export type View = ({ kind: 'board' } & BoardEntry) | { kind: 'score' } | { kind: 'item'; run: string }

const RID = /^r[0-9a-z]{4,12}$/
const ROLE = /^[a-z][a-z0-9-]{0,23}$/
export const PHASE_KEYS = ['ideation', 'inception', 'construction', 'review', 'operation'] as const
const FOCUS: readonly string[] = ['signoff', 'tests', 'cost', 'lanes']
const seconds = (x: string | null) => {
  const n = Number(x ?? 'x')
  return x !== null && x !== '' && Number.isFinite(n) && n >= 0 ? Math.round(n) : undefined
}

export function parseView(search: string): View {
  const q = new URLSearchParams(search)
  if (q.get('view') === 'score') return { kind: 'score' }
  const run = q.get('run') ?? ''
  if (q.get('view') === 'item' && RID.test(run)) return { kind: 'item', run }
  const v: { kind: 'board' } & BoardEntry = { kind: 'board' }
  if (RID.test(run)) v.run = run
  if (v.run) {
    for (const k of ['gate', 'role'] as const) {
      const x = q.get(k) ?? ''
      if (ROLE.test(x)) v[k] = x
    }
    const phase = q.get('phase') ?? ''
    if ((PHASE_KEYS as readonly string[]).includes(phase)) v.phase = phase
    const at = seconds(q.get('at'))
    if (at !== undefined) v.at = at
    const replay = Number(q.get('replay'))
    if ([10, 30, 60, 120].includes(replay)) v.replay = replay
    const focus = q.get('focus') ?? ''
    if (FOCUS.includes(focus)) v.focus = focus as BoardFocus
  }
  if (q.get('new') === 'promo') v.new = 'promo'
  return v
}

export function searchOf(v: View): string {
  const q = new URLSearchParams()
  q.set('view', v.kind)
  if (v.kind === 'score') return `?${q.toString()}`
  if (v.kind === 'item') {
    q.set('run', v.run)
    return `?${q.toString()}`
  }
  for (const k of ['run', 'phase', 'gate', 'role', 'at', 'replay', 'focus', 'new'] as const) {
    const x = v[k]
    if (x !== undefined) q.set(k, String(x))
  }
  return `?${q.toString()}`
}
