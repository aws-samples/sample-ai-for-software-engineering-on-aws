import { describe, expect, it } from 'vitest'
import { diffRuns } from '../board/diff'
import { FIXTURES, failedBoard, finishedBoard, scenario, startedBoard, troubleBoard } from './fixtures'

describe('the preview fixtures', () => {
  it('scenario() plays forward: one run, seq only grows, tests go 6 → 12, it ends done', () => {
    const steps = scenario()
    expect(steps.length).toBeGreaterThanOrEqual(8)
    const ids = new Set(steps.map((b) => b.run!.id))
    expect([...ids]).toEqual(['r1006a'])
    let seq = 0
    let at = 0
    for (const b of steps) {
      const max = Math.max(...b.run!.events.map((e) => e.seq))
      expect(max).toBeGreaterThanOrEqual(seq)
      expect(b.at).toBeGreaterThanOrEqual(at)
      seq = max
      at = b.at
      expect(b.runs[0].tests.passed).toBe(b.run!.tests.passed)
    }
    expect(steps.map((b) => b.run!.tests.passed)).toEqual([6, 6, 9, 9, 11, 11, 12, 12, 12])
    const last = finishedBoard().run!
    expect(last.status).toBe('done')
    expect(last.roles.every((l) => l.status === 'merged' || l.status === 'done')).toBe(true)
  })

  it('every scripted step is something to see: new events that fly, and the flips the plan promises', () => {
    const steps = scenario()
    const diffs = steps.slice(1).map((b, i) => diffRuns(steps[i].run, b.run!, { at: b.at }))
    for (const d of diffs) {
      expect(d.first).toBe(false)
      expect(d.items.length).toBeGreaterThan(0)
    }
    const kinds = new Set(diffs.flatMap((d) => d.items.map((i) => i.kind)))
    for (const k of ['handoff', 'merged', 'tests', 'bounce', 'spawned', 'done', 'tool', 'committed']) expect(kinds.has(k)).toBe(true)
    expect(diffs.flatMap((d) => d.flips).filter((f) => f.from === 'fail' && f.to === 'pass')).toHaveLength(6)
  })

  it('the other fixtures hold the states they are for', () => {
    expect(startedBoard().run!.roles.filter((l) => l.status === 'running').map((l) => l.key)).toEqual(['pm'])
    expect(new Set(troubleBoard().run!.roles.map((l) => l.status))).toEqual(new Set(['merged', 'stalled', 'awaiting_approval', 'queued', 'waiting']))
    expect(failedBoard().run!.status).toBe('failed')
    expect(FIXTURES.empty().run).toBeNull()
    expect(FIXTURES.multi().runs).toHaveLength(3)
  })
})
