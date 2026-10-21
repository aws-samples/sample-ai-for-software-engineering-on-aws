/**
 * The app's three views and the ways into them, as the page URL carries them (a link can open any of them, and the
 * browser's back and forward step between them: a move to another view is a history entry, a change inside a view —
 * a filter, the run picked — replaces the current one):
 *
 *   /apps/aidlc-team                         CTO 视图 (the default): every delivery of the company
 *     ?line=0..4&kind=app|feat|fix&size=S|M|L&week=<YYYY-MM-DD>&real=1   …its filters (业务线, 类型, 规模, 一周, 只看实测)
 *     ?hl=<run | TY-1234>                    …that delivery picked out (its ledger row or its kanban card)
 *     ?at=more|fast|cheap|weekly|flow|ledger …scrolled to that part
 *   ?view=item&run=<id>                      交付详情 of a run of this app (实测, or still going)
 *   ?view=item&issue=TY-1234                 交付详情 of a delivery of the simulated history
 *     &at=<seconds>                          …the segment of its 价值流 at that moment picked out
 *     &from=cto|board                        …opened from that view: the way back is beside its actions
 *   ?view=board                              团队看板 (the newest active run, else the newest)
 *   ?view=board&run=<id>                     that run
 *     &phase=<ideation|inception|…>          …its AI-DLC phase picked out (a finished run: its replay paused where it began)
 *     &gate=<role> / &role=<role>            …the team graph focused on that role (its gate)
 *     &at=<seconds>                          …a finished run's replay, paused that many seconds after its start
 *     &replay=<speed>                        …its replay, playing at that speed
 *     &focus=signoff|tests|cost|lanes        …its 签字单, its 测试墙, its counters, its lanes (each member's use)
 *     &from=cto|item                         …opened from that view: the board says where it is and the way back
 *     &pick=latest                           …the newest 实测 stands in (no run of this app was where the link points)
 *   ?view=board&new=promo                    the 新需求 form (the 双十一 · 家电大促 scenario is its first)
 */

export type BoardFocus = 'signoff' | 'tests' | 'cost' | 'lanes'
export type BoardEntry = {
  run?: string; gate?: string; role?: string; phase?: string; at?: number; replay?: number; focus?: BoardFocus; new?: 'promo'
  from?: 'cto' | 'item'; pick?: 'latest'
}
export type ItemEntry = { run?: string; issue?: string; at?: number; from?: 'cto' | 'board' }
export type CtoAnchor = 'more' | 'fast' | 'cheap' | 'weekly' | 'flow' | 'ledger'
/** the CTO view's filters, as the URL carries them (absent: not filtered) */
export type CtoFilters = { line?: number; type?: 'app' | 'feat' | 'fix'; size?: 'S' | 'M' | 'L'; week?: string; real?: boolean } // type: the URL's kind=
export type CtoEntry = CtoFilters & { hl?: string; at?: CtoAnchor }
export type View = ({ kind: 'cto' } & CtoEntry) | ({ kind: 'item' } & ItemEntry) | ({ kind: 'board' } & BoardEntry)

const RID = /^r[0-9a-z]{4,12}$/
const ROLE = /^[a-z][a-z0-9-]{0,23}$/
const ISSUE = /^TY-\d{4}$/
const DAY = /^\d{4}-\d{2}-\d{2}$/
export const PHASE_KEYS = ['ideation', 'inception', 'construction', 'review', 'operation'] as const
const FOCUS: readonly string[] = ['signoff', 'tests', 'cost', 'lanes']
const ANCHORS: readonly string[] = ['more', 'fast', 'cheap', 'weekly', 'flow', 'ledger']
const seconds = (x: string | null) => {
  const n = Number(x ?? 'x')
  return x !== null && x !== '' && Number.isFinite(n) && n >= 0 ? Math.round(n) : undefined
}

export function parseView(search: string): View {
  const q = new URLSearchParams(search)
  const run = q.get('run') ?? ''
  if (q.get('view') === 'item') {
    const at = seconds(q.get('at'))
    const from = q.get('from')
    const tail = { ...(at !== undefined ? { at } : {}), ...(from === 'cto' || from === 'board' ? { from: from as 'cto' | 'board' } : {}) }
    if (RID.test(run)) return { kind: 'item', run, ...tail }
    const issue = q.get('issue') ?? ''
    return ISSUE.test(issue) ? { kind: 'item', issue, ...tail } : { kind: 'cto' }
  }
  if (q.get('view') !== 'board') {
    const v: View = { kind: 'cto', ...parseFilters(q) }
    const hl = q.get('hl') ?? ''
    if (RID.test(hl) || ISSUE.test(hl)) v.hl = hl
    const at = q.get('at') ?? ''
    if (ANCHORS.includes(at)) v.at = at as CtoAnchor
    return v
  }
  const v: View = { kind: 'board' }
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
    const from = q.get('from')
    if (from === 'cto' || from === 'item') v.from = from
    if (q.get('pick') === 'latest') v.pick = 'latest'
  }
  if (q.get('new') === 'promo') v.new = 'promo'
  return v
}

function parseFilters(q: URLSearchParams): CtoFilters {
  const f: CtoFilters = {}
  const line = Number(q.get('line') ?? 'x')
  if (Number.isInteger(line) && line >= 0 && line < 20) f.line = line
  const type = q.get('kind')
  if (type === 'app' || type === 'feat' || type === 'fix') f.type = type
  const size = q.get('size')
  if (size === 'S' || size === 'M' || size === 'L') f.size = size
  const week = q.get('week') ?? ''
  if (DAY.test(week)) f.week = week
  if (q.get('real') === '1') f.real = true
  return f
}

/** Only the filters of a CTO view entry (what coming back to the CTO view restores). */
export function filtersOf(e: CtoEntry): CtoFilters {
  const { line, type, size, week, real } = e
  return Object.fromEntries(Object.entries({ line, type, size, week, real }).filter(([, x]) => x !== undefined && x !== false)) as CtoFilters
}

export function searchOf(v: View): string {
  const q = new URLSearchParams()
  if (v.kind === 'cto') {
    const f = filtersOf(v)
    if (f.line !== undefined) q.set('line', String(f.line))
    if (f.type) q.set('kind', f.type)
    if (f.size) q.set('size', f.size)
    if (f.week) q.set('week', f.week)
    if (f.real) q.set('real', '1')
    if (v.hl) q.set('hl', v.hl)
    if (v.at) q.set('at', v.at)
  } else if (v.kind === 'item') {
    q.set('view', 'item')
    if (v.run) q.set('run', v.run)
    else if (v.issue) q.set('issue', v.issue)
    if (v.at !== undefined) q.set('at', String(v.at))
    if (v.from) q.set('from', v.from)
  } else {
    q.set('view', 'board')
    for (const k of ['run', 'phase', 'gate', 'role', 'at', 'replay', 'focus', 'from', 'pick', 'new'] as const) {
      const x = v[k]
      if (x !== undefined) q.set(k, String(x))
    }
  }
  const s = q.toString()
  return s ? `?${s}` : ''
}

/** The 交付详情 a delivery of the CTO view opens: by its run when it has one, else by its Issue. */
export function itemOf(x: { real?: string | null; issue?: string }): ItemEntry {
  return x.real ? { run: x.real } : { issue: x.issue }
}
