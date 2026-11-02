import { describe, expect, it } from 'vitest'
import { runningBoard } from '../test/fixtures'
import { NODE_H, NODE_W, RUN, TESTS, anchorBox, bez, headX, layoutGraph, measure, particlePath, pointAt, stagesOf, visibleGraph, type Pt } from './layout'

const run = runningBoard().run!
const lay = layoutGraph(run.roles, run.edges)

const inside = (p: Pt, key: string, pad = 0) => {
  const n = lay.nodes.get(key)!
  return Math.abs(p.x - n.x) < NODE_W / 2 + pad && Math.abs(p.y - n.y) < NODE_H / 2 + pad
}

describe('stagesOf', () => {
  it('puts the team in the five stages of the plan: pm → architect ∥ designer → tester → backend ∥ frontend ∥ ops → reviewer', () => {
    expect(Object.fromEntries(stagesOf(run.roles, run.edges))).toEqual({ pm: 0, architect: 1, designer: 1, tester: 2, backend: 3, frontend: 3, ops: 3, reviewer: 4 })
  })

  it('survives a cycle and an edge to an unknown role', () => {
    const roles = [
      { key: 'a', depends_on: ['b'] },
      { key: 'b', depends_on: ['a'] },
      { key: 'c', depends_on: ['zz'] },
    ]
    const s = stagesOf(roles, [['a', 'b'], ['b', 'a'], ['zz', 'c']])
    expect([...s.keys()].sort()).toEqual(['a', 'b', 'c'])
  })
})

describe('layoutGraph', () => {
  it('places every role once, in stage columns, with no two nodes overlapping', () => {
    expect(lay.nodes.size).toBe(8)
    expect(lay.stages.map((s) => s.keys)).toEqual([['pm'], ['architect', 'designer'], ['tester'], ['backend', 'frontend', 'ops'], ['reviewer']])
    const nodes = [...lay.nodes.values()]
    for (const a of nodes)
      for (const b of nodes) {
        if (a === b) continue
        expect(Math.abs(a.x - b.x) >= NODE_W || Math.abs(a.y - b.y) >= NODE_H).toBe(true)
      }
    for (let i = 1; i < lay.stages.length; i++) expect(lay.stages[i].x).toBeGreaterThan(lay.stages[i - 1].x + NODE_W)
  })

  it('draws every dependency as an edge from the upstream right side to the downstream left side', () => {
    expect(lay.edges).toHaveLength(run.edges.length)
    for (const e of lay.edges) {
      const a = lay.nodes.get(e.from)!
      const b = lay.nodes.get(e.to)!
      const info = measure(e.path)
      expect(pointAt(info, 0)).toEqual({ x: a.x + NODE_W / 2, y: a.y })
      const end = pointAt(info, 1)
      expect(end.x).toBeCloseTo(b.x - NODE_W / 2)
      expect(end.y).toBeCloseTo(b.y)
      expect(e.d.startsWith('M')).toBe(true)
    }
  })

  it('gives a team with many stages a wider graph instead of overlapping columns (the AI-DLC team, mobile left out)', () => {
    const r = (key: string, phase: string, depends_on: string[] = []) => ({ key, phase, depends_on })
    const roles = [r('intent', 'ideation'), r('feasibility', 'ideation'), r('scope', 'ideation', ['intent', 'feasibility']),
      r('architect', 'inception', ['scope']), r('pm', 'inception', ['architect']), r('designer', 'inception', ['architect']),
      r('compliance', 'construction', ['architect']), r('tester', 'construction', ['pm']), r('backend', 'construction', ['architect', 'compliance']),
      r('frontend', 'construction', ['architect', 'designer', 'compliance']), r('reviewer', 'review', ['backend', 'frontend', 'compliance', 'tester']),
      r('ops', 'operation', ['reviewer'])]
    const wide = layoutGraph(roles, roles.flatMap((x) => x.depends_on.map((d) => [d, x.key] as const)))
    expect(wide.stages).toHaveLength(8)
    expect(wide.width).toBeGreaterThan(1640)
    for (let i = 1; i < wide.stages.length; i++) expect(wide.stages[i].x - wide.stages[i - 1].x).toBeGreaterThanOrEqual(NODE_W + 20)
    expect(wide.station.x).toBeGreaterThan(wide.nodes.get('ops')!.x + NODE_W / 2)
    expect(layoutGraph(run.roles, run.edges).width).toBe(lay.width) // a team that fits keeps its size
  })

  it('routes the edges that skip the tester around it', () => {
    for (const e of lay.edges.filter((g) => g.from === 'architect' && ['backend', 'frontend', 'ops'].includes(g.to))) {
      const info = measure(e.path)
      for (let t = 0; t <= 1; t += 0.01) expect(inside(pointAt(info, t), 'tester', 4)).toBe(false)
    }
  })
})

describe('particle routes', () => {
  const head = headX(lay, run.merges)

  it('the head of the run branch is the newest successful merge', () => {
    expect(head).toBe(lay.mergeX.get('backend'))
  })

  it('a merge goes down its own lane to the rail; a test run along the rail to the station', () => {
    const merge = measure(particlePath(lay, 'ops', RUN, head)!)
    expect(pointAt(merge, 1)).toEqual({ x: lay.mergeX.get('ops'), y: lay.rail.y })
    const tests = measure(particlePath(lay, RUN, TESTS, head)!)
    expect(pointAt(tests, 0).y).toBe(lay.rail.y)
    expect(pointAt(tests, 1)).toEqual({ x: lay.station.x - lay.station.r, y: lay.rail.y })
  })

  it('a bounce runs the merge route backwards: station → rail → the role', () => {
    const b = measure(particlePath(lay, TESTS, 'frontend', head)!)
    expect(pointAt(b, 0)).toEqual({ x: lay.station.x - lay.station.r, y: lay.rail.y })
    const fe = lay.nodes.get('frontend')!
    const end = pointAt(b, 1)
    expect(end.x).toBeCloseTo(fe.x + NODE_W / 2)
    expect(end.y).toBeCloseTo(fe.y)
  })

  it('a handoff follows its edge; a blip has no route', () => {
    expect(particlePath(lay, 'pm', 'architect', head)).toBe(lay.edges.find((e) => e.from === 'pm' && e.to === 'architect')!.path)
    expect(particlePath(lay, 'backend', 'backend', head)).toBeNull()
    expect(anchorBox(lay, 'backend', head)).toMatchObject({ w: NODE_W, h: NODE_H })
    expect(anchorBox(lay, TESTS, head)).toMatchObject({ x: lay.station.x, y: lay.station.y })
  })

  it('bez and pointAt agree at the ends', () => {
    const seg = [
      { x: 0, y: 0 },
      { x: 10, y: 0 },
      { x: 20, y: 10 },
      { x: 30, y: 10 },
    ] as const
    expect(bez(seg, 0)).toEqual({ x: 0, y: 0 })
    expect(bez(seg, 1)).toEqual({ x: 30, y: 10 })
    const info = measure([seg])
    expect(info.total).toBeGreaterThan(30)
    expect(pointAt(info, 0.5).x).toBeCloseTo(15, 0)
  })
})

describe('visibleGraph', () => {
  it('leaves out a role that sits the run out and keeps the waits that went through it', () => {
    const roles = [
      { key: 'pm', depends_on: [] },
      { key: 'motion', depends_on: ['pm'], status: 'skipped' },
      { key: 'backend', depends_on: ['pm'] },
      { key: 'tester', depends_on: ['motion', 'backend'] },
    ]
    const g = visibleGraph(roles, [['pm', 'motion'], ['pm', 'backend'], ['motion', 'tester'], ['backend', 'tester']])
    expect(g.roles.map((r) => r.key)).toEqual(['pm', 'backend', 'tester'])
    expect([...g.roles.find((r) => r.key === 'tester')!.depends_on].sort()).toEqual(['backend', 'pm'])
    expect(g.edges).toContainEqual(['pm', 'tester'])
    expect(g.edges.some(([a, b]) => a === 'motion' || b === 'motion')).toBe(false)
    expect(visibleGraph(roles.slice(0, 1), []).roles).toHaveLength(1) // nothing skipped: as it is
  })
})
