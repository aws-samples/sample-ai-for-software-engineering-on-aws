import { describe, expect, it } from 'vitest'
import { ARRIVE_MS, BUDGET_MS, CALM_FOR_MS, Engine, LATE_MS, PER_EDGE, SPREAD_MS, TRAVEL_MS, type Item } from './engine'

function fakeClock(start = 1_000_000) {
  let t = start
  return { now: () => t, set: (v: number) => (t = v), add: (d: number) => (t += d) }
}

const T0 = 1_791_231_500
let n = 0
function item(over: Partial<Item> = {}): Item {
  n++
  return { key: `r1#${n}`, t: T0, kind: 'handoff', from: 'pm', to: 'architect', prio: 2, shape: 'comet', tone: 'handoff', ...over }
}

function setup(opts: { reducedMotion?: boolean } = {}) {
  const clock = fakeClock()
  const engine = new Engine({ now: clock.now, ...opts })
  return { clock, engine }
}

describe('Engine', () => {
  it('drops what it has seen (by key), and history is remembered without playing', () => {
    const { engine } = setup()
    const a = item()
    expect(engine.ingest([a, a])).toHaveLength(1)
    expect(engine.ingest([a])).toHaveLength(0)
    expect(engine.dropped.duplicate).toBe(2)
    const old = item()
    engine.history([old])
    expect(engine.ingest([old])).toHaveLength(0)
  })

  it('plays a batch from when it arrived, in its own spacing, squeezed into SPREAD_MS', () => {
    const { clock, engine } = setup()
    const batch = [0, 1, 2, 4].map((dt, i) => item({ t: T0 + dt, kind: `k${i}`, to: `n${i}` }))
    engine.ingest(batch, clock.now())
    const starts = new Map<string, number>()
    for (let t = 0; t <= 4000; t += 10) {
      clock.set(1_000_000 + t)
      for (const p of engine.frame().particles) if (p.travel && !starts.has(p.key)) starts.set(p.key, p.start - 1_000_000)
    }
    const squeeze = SPREAD_MS / 4000
    expect([...starts.values()]).toEqual([0, 1000 * squeeze, 2000 * squeeze, 4000 * squeeze])
  })

  it('a particle that gets there leaves one ring (or cross / tick) on its target', () => {
    const { clock, engine } = setup()
    engine.ingest([item({ tone: 'bounce', from: 'tests', to: 'backend', prio: 3 })], clock.now())
    let f = engine.frame()
    expect(f.particles).toEqual([expect.objectContaining({ travel: true, from: 'tests', to: 'backend' })])
    clock.add(TRAVEL_MS + 20)
    f = engine.frame()
    expect(f.particles).toEqual([expect.objectContaining({ travel: false, from: 'backend', to: 'backend', shape: 'cross' })])
    clock.add(ARRIVE_MS)
    expect(engine.frame().particles).toEqual([])
    expect(engine.busy).toBe(false)
  })

  it('merges one channel within 250 ms into one bigger particle', () => {
    const { clock, engine } = setup()
    engine.ingest([item({ kind: 'tool', from: 'fe', to: 'fe' }), item({ kind: 'tool', from: 'fe', to: 'fe', t: T0 + 0.05 })], clock.now())
    clock.add(100)
    const f = engine.frame()
    expect(f.particles).toHaveLength(1)
    expect(f.particles[0].count).toBe(2)
    expect(engine.dropped.merged).toBe(1)
  })

  it(`admits ${PER_EDGE} per edge; priority 3 always gets in`, () => {
    const { clock, engine } = setup()
    const edge = Array.from({ length: PER_EDGE + 2 }, (_, i) => item({ kind: `e${i}`, prio: 0 }))
    engine.ingest(edge, clock.now())
    expect(engine.frame().particles).toHaveLength(PER_EDGE)
    expect(engine.dropped.admission).toBe(2)
    engine.ingest([item({ kind: 'bounce', prio: 3 })], clock.now())
    const f = engine.frame()
    expect(f.particles.some((p) => p.kind === 'bounce')).toBe(true)
    expect(f.particles).toHaveLength(PER_EDGE)
  })

  it('flies nothing with reduced motion (level 3 for good)', () => {
    const { clock, engine } = setup({ reducedMotion: true })
    engine.ingest([item(), item({ prio: 3, kind: 'merged' })], clock.now())
    for (let t = 0; t < 3000; t += 100) {
      clock.add(100)
      expect(engine.frame().particles).toEqual([])
    }
    expect(engine.dropped.level).toBe(2)
    engine.report(50)
    expect(engine.level).toBe(3)
  })

  it('pauses while hidden and drops what was due meanwhile instead of playing it late', () => {
    const { clock, engine } = setup()
    engine.setHidden(true)
    engine.ingest([item()], clock.now())
    expect(engine.busy).toBe(false)
    expect(engine.frame().particles).toEqual([])
    clock.add(LATE_MS + 1000)
    engine.setHidden(false)
    expect(engine.dropped.expired).toBe(1)
    expect(engine.frame().particles).toEqual([])
  })

  it('goes down a level when a frame is over budget and back up after a calm stretch', () => {
    const { clock, engine } = setup()
    engine.report(BUDGET_MS + 1)
    expect(engine.level).toBe(1)
    engine.report(BUDGET_MS + 1)
    expect(engine.level).toBe(2)
    engine.report(0.5)
    clock.add(CALM_FOR_MS)
    engine.report(0.5)
    expect(engine.level).toBe(1)
    // level 2: priority 2 and up only
    engine.report(BUDGET_MS + 1)
    engine.ingest([item({ prio: 1, kind: 'committed', from: 'x', to: 'x' }), item({ prio: 3, kind: 'merged', to: 'run' })], clock.now())
    expect(engine.frame().particles.map((p) => p.kind)).toEqual(['merged'])
  })
})
