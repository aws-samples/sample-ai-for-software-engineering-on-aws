/**
 * Where the team graph puts everything. Pure: the same team always gives the same picture, and events
 * never move anything. Roles are placed by dependency depth, in stage columns, left → right.
 *
 * - A role's stage is 1 + the deepest stage among the roles it depends on (ASAP). A role whose every
 *   dependent is a final role (nothing depends on those) moves right next to them: it feeds the last
 *   stage, so it is drawn with the others that do (运维 sits with 后端 and 前端, before 评审).
 * - Roles of one stage stack vertically in team order. Edges leave a role's right side and enter the
 *   downstream role's left side; an edge that skips a stage runs straight across that column in the
 *   free space above or below its roles, and bends only in the gaps between columns.
 * - The run branch is a rail along the bottom; each role drops into it in its own lane just right of
 *   its column (its merge point), and the test station sits at the rail's right end. A bounce runs the
 *   merge route backwards: station → rail → the role's lane → the role.
 */
import type { Lane } from '../types'
import { PHASES } from './format'

export const GW = 1320
export const NODE_W = 184
export const NODE_H = 80
export const ROW_GAP = 100
export const STATION_R = 28
/** Top of the first row (stage titles and the parallel badges sit above it). */
const TOP = 86
const PAD_X = 24
/** Room kept free around a role when an edge passes its column; below it, room for its live ticker. */
const ROUTE_PAD = 12
const TICKER_PAD = 26

export interface Pt {
  x: number
  y: number
}
export type Seg = readonly [Pt, Pt, Pt, Pt]
export type Path = Seg[]

export interface NodeBox extends Pt {
  key: string
  stage: number
  row: number
}

export interface StageInfo {
  index: number
  x: number
  keys: string[]
  phase: string // the AI-DLC phase of its roles ('' when the team has none)
}

/** An AI-DLC phase over the columns of its roles (or, for one no role is in, a greyed box of its own). */
export interface PhaseBand {
  key: string
  n: string
  title: string
  en: string
  x1: number
  x2: number
  used: boolean
}

export interface EdgeGeom {
  from: string
  to: string
  path: Path
  d: string
}

export interface GraphLayout {
  width: number
  height: number
  nodes: Map<string, NodeBox>
  stages: StageInfo[]
  edges: EdgeGeom[]
  rail: { x1: number; x2: number; y: number }
  station: Pt & { r: number }
  /** Where each role's merge lane meets the rail. */
  mergeX: Map<string, number>
  /** A phased team: the AI-DLC phase bands, and the orchestrator node at the far left that dispatches the roles. */
  phases: PhaseBand[]
  orch: Pt | null
}

type RoleLike = Pick<Lane, 'key' | 'depends_on'> & { phase?: string; aidlc_agent?: string; status?: string }

/** AI-DLC has no review phase of its own: a review role (teams from before) is drawn at the end of Construction. */
const phaseOf = (p?: string) => (p === 'review' ? 'construction' : p)

/** The team list under the orchestrator (TeamGraph's Roster): the same sizes here, so the graph is tall enough for it. */
export const ROSTER = { top: 26, title: 16, group: 17, row: 16, gap: 3 }

/** Its groups (one per expert definition) and members. With the company's whole team (*roster*): everyone on it, in
 * its order, the ones this run does not use included (drawn grey, no node); without: the run's roles only. */
export function rosterGroups(roles: ReadonlyArray<RoleLike>, roster?: ReadonlyArray<{ key: string; member: string }> | null): { key: string; keys: string[] }[] {
  const groups: { key: string; keys: string[] }[] = []
  const add = (group: string, key: string) => {
    const g = groups.find((x) => x.key === group)
    if (g) g.keys.push(key)
    else groups.push({ key: group, keys: [key] })
  }
  const groupOf = (r: RoleLike) => (r.aidlc_agent ?? '').split(',')[0]?.trim() || r.key
  if (roster?.length) {
    for (const p of roster) add(p.member || p.key, p.key)
    for (const r of roles) if (r.status !== 'skipped' && !roster.some((p) => p.key === r.key)) add(groupOf(r), r.key)
    return groups
  }
  for (const r of roles) if (r.status !== 'skipped') add(groupOf(r), r.key)
  return groups
}
type EdgeList = ReadonlyArray<readonly [string, string]>

/** The flow as this run has it: a role that sits the run out (skipped: 未入职, or the approved plan leaves it out) is not
 * drawn, and a role that waited for it is drawn waiting for what that one waited for. */
export function visibleGraph<T extends RoleLike>(roles: ReadonlyArray<T>, edges: EdgeList): { roles: T[]; edges: [string, string][] } {
  const out = new Set(roles.filter((r) => r.status === 'skipped').map((r) => r.key))
  if (!out.size) return { roles: [...roles], edges: edges.map(([a, b]) => [a, b]) }
  const byKey = new Map(roles.map((r) => [r.key, r]))
  const ups = (key: string, seen: Set<string>): string[] =>
    (byKey.get(key)?.depends_on ?? []).flatMap((d) => (seen.has(d) ? [] : (seen.add(d), out.has(d) ? ups(d, seen) : [d])))
  const kept = roles.filter((r) => !out.has(r.key)).map((r) => ({ ...r, depends_on: [...new Set(ups(r.key, new Set()))] }))
  return { roles: kept, edges: kept.flatMap((r) => r.depends_on.map((d) => [d, r.key] as [string, string])) }
}

const round = (v: number) => Math.round(v * 10) / 10

/** Stage (column) of every role, 0 = leftmost; compacted so no column is empty. */
export function stagesOf(roles: RoleLike[], edges: EdgeList): Map<string, number> {
  const keys = new Set(roles.map((r) => r.key))
  const ups = new Map<string, Set<string>>()
  const downs = new Map<string, Set<string>>()
  const link = (a: string, b: string) => {
    if (!keys.has(a) || !keys.has(b) || a === b) return
    if (!ups.has(b)) ups.set(b, new Set())
    ups.get(b)!.add(a)
    if (!downs.has(a)) downs.set(a, new Set())
    downs.get(a)!.add(b)
  }
  for (const r of roles) for (const d of r.depends_on) link(d, r.key)
  for (const [a, b] of edges) link(a, b)

  const depth = new Map<string, number>()
  const visiting = new Set<string>()
  const asap = (k: string): number => {
    const known = depth.get(k)
    if (known !== undefined) return known
    if (visiting.has(k)) return 0 // a cycle: cut it here rather than loop
    visiting.add(k)
    let d = 0
    for (const u of ups.get(k) ?? []) d = Math.max(d, asap(u) + 1)
    visiting.delete(k)
    depth.set(k, d)
    return d
  }
  for (const r of roles) asap(r.key)

  const stage = new Map(depth)
  const isFinal = (k: string) => !(downs.get(k)?.size ?? 0)
  for (const r of roles) {
    const ds = [...(downs.get(r.key) ?? [])]
    if (!ds.length || !ds.every(isFinal)) continue
    const target = Math.min(...ds.map((d) => depth.get(d) ?? 0)) - 1
    if (target > (stage.get(r.key) ?? 0)) stage.set(r.key, target)
  }

  // a phased team: columns go phase by phase (an upstream role is always in an earlier phase or deeper in the same)
  const rank = phaseRank(roles)
  const keyOf = (k: string) => (rank ? (rank.get(k) ?? 0) * 1000 : 0) + (stage.get(k) ?? 0)
  const used = [...new Set(roles.map((r) => keyOf(r.key)))].sort((a, b) => a - b)
  const compact = new Map(used.map((s, i) => [s, i]))
  return new Map(roles.map((r) => [r.key, compact.get(keyOf(r.key)) ?? 0]))
}

/** Each role's AI-DLC phase index, when every role names a known phase; else null (an unphased team). */
function phaseRank(roles: RoleLike[]): Map<string, number> | null {
  const idx = new Map(PHASES.map((p, i) => [p.key, i]))
  if (!roles.length || !roles.every((r) => phaseOf(r.phase) && idx.has(phaseOf(r.phase)!))) return null
  return new Map(roles.map((r) => [r.key, idx.get(phaseOf(r.phase)!)!]))
}

export function bez(s: Seg, t: number): Pt {
  const u = 1 - t
  const a = u * u * u
  const b = 3 * u * u * t
  const c = 3 * u * t * t
  const d = t * t * t
  return { x: a * s[0].x + b * s[1].x + c * s[2].x + d * s[3].x, y: a * s[0].y + b * s[1].y + c * s[2].y + d * s[3].y }
}

const lerp = (p: Pt, q: Pt, t: number): Pt => ({ x: p.x + (q.x - p.x) * t, y: p.y + (q.y - p.y) * t })

/** A straight piece as a cubic (so a path is one kind of segment). */
export const line = (p: Pt, q: Pt): Seg => [p, lerp(p, q, 1 / 3), lerp(p, q, 2 / 3), q]

/** An S bend with horizontal tangents at both ends. */
export function sCurve(p: Pt, q: Pt): Seg {
  const dx = (q.x - p.x) / 2
  return [p, { x: p.x + dx, y: p.y }, { x: q.x - dx, y: q.y }, q]
}

/** Heading right at *p*, turning to head down (or up) into *q*. */
const turnDown = (p: Pt, q: Pt): Seg => [p, { x: q.x, y: p.y }, { x: q.x, y: p.y }, q]

/** Heading down at *p*, turning to head right into *q*. */
const turnRight = (p: Pt, q: Pt): Seg => [p, { x: p.x, y: q.y }, { x: p.x, y: q.y }, q]

export function reversePath(p: Path): Path {
  return p
    .slice()
    .reverse()
    .map((s) => [s[3], s[2], s[1], s[0]] as const)
}

export function pathD(path: Path): string {
  if (!path.length) return ''
  const f = (p: Pt) => `${round(p.x)},${round(p.y)}`
  return `M${f(path[0][0])}${path.map((s) => ` C${f(s[1])} ${f(s[2])} ${f(s[3])}`).join('')}`
}

export interface PathInfo {
  segs: Path
  lens: number[]
  total: number
}

export function measure(path: Path): PathInfo {
  const lens = path.map((s) => {
    let len = 0
    let prev = s[0]
    for (let i = 1; i <= 12; i++) {
      const p = bez(s, i / 12)
      len += Math.hypot(p.x - prev.x, p.y - prev.y)
      prev = p
    }
    return len
  })
  return { segs: path, lens, total: lens.reduce((a, b) => a + b, 0) }
}

/** The point *t* (0…1) of the way along the path, by length. */
export function pointAt(info: PathInfo, t: number): Pt {
  const n = info.segs.length
  if (!n) return { x: 0, y: 0 }
  let d = Math.min(1, Math.max(0, t)) * info.total
  for (let i = 0; i < n; i++) {
    const len = info.lens[i]
    if (d <= len || i === n - 1) return bez(info.segs[i], len > 0 ? Math.min(1, d / len) : 1)
    d -= len
  }
  return info.segs[n - 1][3]
}

function routeEdge(a: NodeBox, b: NodeBox, stages: StageInfo[], nodes: Map<string, NodeBox>, usage: Map<string, number>): Path {
  const start = { x: a.x + NODE_W / 2, y: a.y }
  const end = { x: b.x - NODE_W / 2, y: b.y }
  if (b.stage <= a.stage) {
    // not a forward edge (the contract does not have these): a loop out to the right and back
    const out = { x: Math.max(start.x, b.x + NODE_W / 2) + 40, y: (a.y + b.y) / 2 }
    return [sCurve(start, out), sCurve(out, { x: b.x + NODE_W / 2, y: b.y })]
  }
  const pts: Pt[] = [start]
  for (let s = a.stage + 1; s < b.stage; s++) {
    const st = stages[s]
    const t = (st.x - start.x) / (end.x - start.x || 1)
    let y = start.y + (end.y - start.y) * t
    const bands = st.keys
      .map((k) => nodes.get(k)!)
      .sort((p, q) => p.y - q.y)
      .map((n) => [n.y - NODE_H / 2 - ROUTE_PAD, n.y + NODE_H / 2 + ROUTE_PAD + TICKER_PAD] as [number, number])
      .reduce<Array<[number, number]>>((acc, band) => {
        const last = acc[acc.length - 1]
        if (last && band[0] <= last[1]) last[1] = Math.max(last[1], band[1])
        else acc.push([...band])
        return acc
      }, [])
    let side = 0
    for (const [lo, hi] of bands) {
      if (y > lo && y < hi) {
        side = y - lo < hi - y ? -1 : 1
        y = side < 0 ? lo : hi
        break
      }
    }
    const slot = `${s}:${Math.round(y)}`
    const used = usage.get(slot) ?? 0
    usage.set(slot, used + 1)
    // later edges through the same spot sit beside the first, away from the roles
    if (used) y += (side || (used % 2 ? 1 : -1)) * 7 * (side ? used : Math.ceil(used / 2))
    pts.push({ x: st.x - NODE_W / 2 - 10, y }, { x: st.x + NODE_W / 2 + 10, y })
  }
  pts.push(end)
  const path: Path = []
  for (let i = 0; i < pts.length - 1; i++) path.push(i % 2 === 1 ? line(pts[i], pts[i + 1]) : sCurve(pts[i], pts[i + 1]))
  return path
}

/** A phased team's graph is wider: the orchestrator on the left, the greyed operation phase on the right. */
export const GW_PHASED = 1640
const ORCH_W = 176
const OPS_W = 96
/** An official phase this team does not run, between ones it does (feature work skips 1 构思): a narrow grey band. */
const GREY_W = 92
const OFFICIAL = PHASES.filter((p) => p.key !== 'review')
/** Columns are never closer than a node and a gap: a team with many stages (the AI-DLC team's 8) gets a wider graph,
 * drawn smaller, rather than nodes on top of each other. */
const MIN_STEP = NODE_W + 28

export function layoutGraph(roles: RoleLike[], edgeList: EdgeList, roster?: ReadonlyArray<{ key: string; member: string }> | null): GraphLayout {
  const stageOf = stagesOf(roles, edgeList)
  const phased = phaseRank(roles) !== null
  const count = Math.max(1, ...roles.map((r) => (stageOf.get(r.key) ?? 0) + 1))
  const stages: StageInfo[] = Array.from({ length: count }, (_, i) => ({ index: i, x: 0, keys: [], phase: '' }))
  for (const r of roles) {
    const st = stages[stageOf.get(r.key) ?? 0]
    st.keys.push(r.key)
    if (phased) st.phase = phaseOf(r.phase) ?? ''
  }
  const maxRows = Math.max(1, ...stages.map((s) => s.keys.length))
  // official phases the team skips before its last one get a grey band of their own: room is kept for each
  const usedPhases = new Set(stages.map((s) => s.phase))
  const lastUsed = Math.max(-1, ...OFFICIAL.map((p, i) => (usedPhases.has(p.key) ? i : -1)))
  const skipped = phased ? OFFICIAL.filter((p, i) => i < lastUsed && !usedPhases.has(p.key)) : []
  const skippedBefore = (phase: string) => skipped.filter((p) => OFFICIAL.indexOf(p) < OFFICIAL.findIndex((x) => x.key === phase)).length
  const left = PAD_X + NODE_W / 2 + (phased ? ORCH_W : 0)
  const margin = 70 + NODE_W / 2 + (phased ? OPS_W : 0) + skipped.length * GREY_W
  const W = Math.max(phased ? GW_PHASED : GW, round(left + (count - 1) * MIN_STEP + margin))
  const right = W - margin
  const step = count > 1 ? (right - left) / (count - 1) : 0
  // tall enough for the roles, and (a phased team) for the team list under the orchestrator
  const groups = phased ? rosterGroups(roles, roster) : []
  const rosterBottom = TOP + ORCH_BOX.h - 6 + ROSTER.top + ROSTER.title +
    groups.reduce((h, g) => h + ROSTER.group + g.keys.length * ROSTER.row + ROSTER.gap, 0)
  const railY = Math.max(TOP + (maxRows - 1) * ROW_GAP + NODE_H + 58, phased ? rosterBottom + 40 : 0)
  const yc = TOP + (railY - 58 - TOP) / 2
  const nodes = new Map<string, NodeBox>()
  const mergeX = new Map<string, number>()
  stages.forEach((s, i) => {
    s.x = round((count > 1 ? left + i * step : GW / 2 - 40) + (phased ? skippedBefore(s.phase) * GREY_W : 0))
    const k = s.keys.length
    s.keys.forEach((key, row) => {
      nodes.set(key, { key, stage: i, row, x: s.x, y: round(yc + (row - (k - 1) / 2) * ROW_GAP) })
      mergeX.set(key, round(s.x + NODE_W / 2 + 18 + 20 * row))
    })
  })
  const usage = new Map<string, number>()
  const edges: EdgeGeom[] = []
  for (const [from, to] of edgeList) {
    const a = nodes.get(from)
    const b = nodes.get(to)
    if (!a || !b || from === to) continue
    const path = routeEdge(a, b, stages, nodes, usage)
    edges.push({ from, to, path, d: pathD(path) })
  }
  const station = { x: W - 42, y: railY, r: STATION_R }
  const phases: PhaseBand[] = []
  if (phased) {
    for (const p of PHASES) {
      const cols = stages.filter((s) => s.phase === p.key)
      if (cols.length) phases.push({ ...p, x1: round(cols[0].x - NODE_W / 2 - 14), x2: round(cols[cols.length - 1].x + NODE_W / 2 + 14), used: true })
    }
    // neighbours meet half way between their columns, a small gap apart (never overlapping bands)
    for (let i = 1; i < phases.length; i++) {
      const mid = (phases[i - 1].x2 - 14 - NODE_W / 2 + NODE_W / 2 + (phases[i].x1 + 14)) / 2
      const edgeL = phases[i - 1].x2 - 14
      const edgeR = phases[i].x1 + 14
      const m = (edgeL + edgeR) / 2 || mid
      phases[i - 1].x2 = round(Math.min(phases[i - 1].x2, m - 4))
      phases[i].x1 = round(Math.max(phases[i].x1, m + 4))
    }
    // the skipped ones: a grey band right before the first phase after them
    for (const p of [...skipped].reverse()) {
      const next = phases.filter((b) => OFFICIAL.findIndex((x) => x.key === b.key) > OFFICIAL.indexOf(p)).sort((a, b) => a.x1 - b.x1)[0]
      if (!next) continue
      const x2 = round(next.x1 - 8)
      phases.push({ ...p, x1: round(x2 - (GREY_W - 12)), x2, used: false })
    }
    phases.sort((a, b) => a.x1 - b.x1)
    const last = phases.length ? phases[phases.length - 1].x2 : left
    if (!phases.some((p) => p.key === 'operation')) {
      const op = PHASES.find((p) => p.key === 'operation')!
      phases.push({ ...op, x1: round(last + 16), x2: round(W - 20), used: false })
    }
    // AI-DLC's phase 0: choosing the flow, staffing the team, setting up the repository — the orchestrator's part
    if (phases.length) phases.unshift({ key: 'init', n: '0', title: '初始化', en: 'Initialization', x1: 8, x2: round(phases[0].x1 - 8), used: true })
  }
  const orch = phased ? { x: round(PAD_X + ORCH_W / 2 - 10), y: TOP + ORCH_BOX.h / 2 - 6 } : null
  return { width: W, height: railY + 44, nodes, stages, edges, rail: { x1: PAD_X, x2: station.x - STATION_R, y: railY }, station, mergeX, phases, orch }
}

// ---------------------------------------------------------------------------------------------
// anchors and the routes particles take
// ---------------------------------------------------------------------------------------------

/** 'run' (the run branch), 'tests' (the test station) or a role key. */
export type Anchor = string
export const RUN = 'run'
export const TESTS = 'tests'
/** The orchestrator (a phased team): every role is dispatched from here. */
export const ORCH = 'orch'
export const ORCH_BOX = { w: 132, h: 76 }

/** Where an anchor sits. *headX*: the run branch's head on the rail (its newest merge). */
export function anchorPoint(lay: GraphLayout, a: Anchor, headX: number): Pt | null {
  if (a === TESTS) return { x: lay.station.x, y: lay.station.y }
  if (a === RUN) return { x: headX, y: lay.rail.y }
  if (a === ORCH) return lay.orch
  const n = lay.nodes.get(a)
  return n ? { x: n.x, y: n.y } : null
}

/** The box an anchor takes up (a blip pulses around it). */
export function anchorBox(lay: GraphLayout, a: Anchor, headX: number): (Pt & { w: number; h: number; rx: number }) | null {
  if (a === TESTS) return { x: lay.station.x, y: lay.station.y, w: lay.station.r * 2, h: lay.station.r * 2, rx: lay.station.r }
  if (a === RUN) return { x: headX, y: lay.rail.y, w: 22, h: 22, rx: 11 }
  if (a === ORCH) return lay.orch ? { ...lay.orch, w: ORCH_BOX.w, h: ORCH_BOX.h, rx: 18 } : null
  const n = lay.nodes.get(a)
  return n ? { x: n.x, y: n.y, w: NODE_W, h: NODE_H, rx: 16 } : null
}

/** The y of the orchestrator's command bus: just under the phase titles. */
const BUS_Y = 64

/** The orchestrator's command line to a role: along the bus under the phase titles, down the gap left of the
 * role's column, into its left side. */
export function commandPath(lay: GraphLayout, role: string): Path | null {
  const o = lay.orch
  const n = lay.nodes.get(role)
  if (!o || !n) return null
  const p0 = { x: o.x + ORCH_BOX.w / 2, y: o.y }
  const gap = n.x - NODE_W / 2 - 18
  const bus = { x: Math.min(p0.x + 28, gap - 18), y: BUS_Y }
  const down = { x: gap, y: Math.max(BUS_Y + 18, n.y - 18) }
  const end = { x: n.x - NODE_W / 2, y: n.y }
  return [sCurve(p0, bus), line(bus, { x: gap - 18, y: BUS_Y }), turnDown({ x: gap - 18, y: BUS_Y }, down), turnRight(down, end)]
}

/** A role's merge route: out of its right side, down its lane to the rail. */
export function mergePath(lay: GraphLayout, role: string): Path | null {
  const n = lay.nodes.get(role)
  const mx = lay.mergeX.get(role)
  if (!n || mx === undefined) return null
  const p0 = { x: n.x + NODE_W / 2, y: n.y }
  const turn = { x: mx, y: n.y + 24 }
  return [turnDown(p0, turn), line(turn, { x: mx, y: lay.rail.y })]
}

/** The route a particle takes from *from* to *to*; null when it does not travel (a blip on *to*). */
export function particlePath(lay: GraphLayout, from: Anchor, to: Anchor, headX: number): Path | null {
  if (from === to) return null
  const st = lay.station
  if (from === ORCH && lay.orch && lay.nodes.has(to)) return commandPath(lay, to)
  if (to === RUN && lay.nodes.has(from)) return mergePath(lay, from)
  if (from === RUN && to === TESTS) return [line({ x: Math.min(headX, st.x - st.r - 20), y: lay.rail.y }, { x: st.x - st.r, y: lay.rail.y })]
  if (from === TESTS && lay.nodes.has(to)) {
    const m = mergePath(lay, to)
    const mx = lay.mergeX.get(to)
    if (!m || mx === undefined) return null
    return [line({ x: st.x - st.r, y: lay.rail.y }, { x: mx, y: lay.rail.y }), ...reversePath(m)]
  }
  if (lay.nodes.has(from) && lay.nodes.has(to)) {
    const e = lay.edges.find((g) => g.from === from && g.to === to)
    if (e) return e.path
    const a = lay.nodes.get(from)!
    const b = lay.nodes.get(to)!
    return b.x >= a.x ? [sCurve({ x: a.x + NODE_W / 2, y: a.y }, { x: b.x - NODE_W / 2, y: b.y })] : [sCurve({ x: a.x - NODE_W / 2, y: a.y }, { x: b.x + NODE_W / 2, y: b.y })]
  }
  const a = anchorPoint(lay, from, headX)
  const b = anchorPoint(lay, to, headX)
  return a && b ? [sCurve(a, b)] : null
}

/** The run branch's head on the rail: the merge point of the newest successful merge. */
export function headX(lay: GraphLayout, merges: ReadonlyArray<{ role: string; status: string }>): number {
  for (let i = merges.length - 1; i >= 0; i--) {
    if (merges[i].status !== 'merged') continue
    const x = lay.mergeX.get(merges[i].role)
    if (x !== undefined) return x
  }
  return lay.rail.x1 + 120
}
