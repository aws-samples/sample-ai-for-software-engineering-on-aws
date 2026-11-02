import { describe, expect, it } from 'vitest'
import type { Board, RunDetail, TeamEvent } from '../types'
import { clone, lane, runningBoard, setCase, withEvent } from '../test/fixtures'
import { LATE_S, MAX_ITEMS, bounceLabel, diffRuns, eventItem, handoffLabel, mergeKey } from './diff'

const run = (b: Board): RunDetail => b.run!

/** The fixture plus one new event at the snapshot's time. */
function plus(e: Parameters<typeof withEvent>[1], base: Board = runningBoard()): Board {
  return withEvent(clone(base), e)
}

describe('diffRuns', () => {
  it('treats the first snapshot as history: nothing animates', () => {
    const b = runningBoard()
    const d = diffRuns(null, run(b), { at: b.at })
    expect(d.first).toBe(true)
    expect(d.items).toEqual([])
    expect(d.flips).toEqual([])
    expect(d.flashes).toEqual([])
    expect(d.fresh).toEqual([])
    expect(d.merges).toEqual([])
  })

  it('finds nothing new in the same snapshot twice', () => {
    const b = runningBoard()
    const d = diffRuns(run(b), run(runningBoard()), { at: b.at })
    expect(d.first).toBe(false)
    expect(d.fresh).toEqual([])
    expect(d.items).toEqual([])
    expect(d.announce).toBeNull()
  })

  it('turns a new handoff into a particle along the edge from → to', () => {
    const prev = runningBoard()
    const next = plus({ kind: 'handoff', role: 'reviewer', from: 'ops', to: 'reviewer', text: '运维的脚本交给评审' })
    const d = diffRuns(run(prev), run(next), { at: next.at })
    expect(d.fresh.map((e) => e.seq)).toEqual([32])
    expect(d.items).toEqual([expect.objectContaining({ key: 'r1006a#32', kind: 'handoff', from: 'ops', to: 'reviewer', tone: 'handoff', shape: 'comet', label: '运维的脚本' })])
  })

  it('turns a bounce into a red particle from the test station to the role', () => {
    const prev = runningBoard()
    const next = plus({ kind: 'bounce', role: 'frontend', from: 'tests', to: 'frontend', text: 'AC-8 失败，打回前端' })
    const d = diffRuns(run(prev), run(next), { at: next.at })
    expect(d.items).toEqual([expect.objectContaining({ key: 'r1006a#32', from: 'tests', to: 'frontend', tone: 'bounce', prio: 3, label: 'AC-8' })])
  })

  it('sends a merge down to the run branch and a test run from the branch to the station, green only when all pass', () => {
    const prev = runningBoard()
    let next = plus({ kind: 'merged', role: 'ops', from: 'ops', to: 'run', text: '运维的分支合入运行分支' })
    next = plus({ kind: 'tests', text: '测试 7/12' }, next)
    let d = diffRuns(run(prev), run(next), { at: next.at })
    expect(d.items.map((i) => [i.from, i.to, i.tone, i.label ?? null])).toEqual([
      ['ops', 'run', 'merge', null],
      ['run', 'tests', 'fail', '7/12'],
    ])
    d = diffRuns(run(prev), run(plus({ kind: 'tests', text: '测试 12/12：全绿' })), { at: next.at })
    expect(d.items[0].tone).toBe('pass')
  })

  it('flashes the node red for a conflict (and the run branch) and for a violation', () => {
    const prev = runningBoard()
    let next = plus({ kind: 'conflict', role: 'backend', from: 'backend', to: 'run', text: '后端合入冲突' })
    next = plus({ kind: 'violation', role: 'ops', text: '运维改了不属于它的 backend/x.js' }, next)
    const d = diffRuns(run(prev), run(next), { at: next.at })
    expect(d.flashes.map((f) => [f.target, f.tone, f.kind])).toEqual([
      ['backend', 'bad', 'conflict'],
      ['run', 'bad', 'conflict'],
      ['ops', 'bad', 'violation'],
    ])
    // they do not travel: a red cross on the node
    expect(d.items.map((i) => [i.from, i.to, i.shape])).toEqual([
      ['backend', 'backend', 'cross'],
      ['ops', 'ops', 'cross'],
    ])
  })

  it('flashes the station when the run turns all green, and every role when the run is done', () => {
    const prev = runningBoard()
    const green = runningBoard()
    for (const c of run(green).tests.cases) setCase(green, c.id, 'pass')
    let d = diffRuns(run(prev), run(green), { at: green.at })
    expect(d.flashes.map((f) => [f.target, f.tone])).toEqual([['tests', 'ok']])
    const done = clone(green)
    run(done).status = 'done'
    d = diffRuns(run(green), run(done), { at: done.at })
    expect(d.flashes.map((f) => f.target)).toEqual(run(done).roles.map((l) => l.key))
    expect(d.flashes.every((f) => f.tone === 'ok')).toBe(true)
    expect(d.announce).toBe('运行已完成')
  })

  it('flips a test case whose status changed (red → green), and only that one', () => {
    const prev = runningBoard()
    const next = setCase(runningBoard(), 'api-signup.test.js#AC-6', 'pass')
    const d = diffRuns(run(prev), run(next), { at: next.at })
    expect(d.flips).toEqual([{ id: 'api-signup.test.js#AC-6', from: 'fail', to: 'pass' }])
    expect(d.announce).toContain('测试 6/12 → 7/12')
  })

  it('reports lane status changes and new merges', () => {
    const prev = runningBoard()
    const next = runningBoard()
    lane(next, 'ops').status = 'merged'
    run(next).merges.push({ role: 'ops', sha: '0a6d3e1', at: next.at, status: 'merged', files: 3, note: null })
    const d = diffRuns(run(prev), run(next), { at: next.at })
    expect(d.lanes).toEqual([{ key: 'ops', from: 'done', to: 'merged' }])
    expect(d.merges).toEqual([mergeKey(run(next).merges[run(next).merges.length - 1])])
  })

  it('starts over (history again) for another run, after the page was hidden, or when the record went backwards', () => {
    const prev = runningBoard()
    const other = plus({ kind: 'handoff', from: 'ops', to: 'reviewer', role: 'reviewer' })
    run(other).id = 'r2'
    expect(diffRuns(run(prev), run(other), { at: other.at }).first).toBe(true)
    const next = plus({ kind: 'handoff', from: 'ops', to: 'reviewer', role: 'reviewer' })
    const hidden = diffRuns(run(prev), run(next), { at: next.at, resync: true })
    expect(hidden.first).toBe(true)
    expect(hidden.items).toEqual([])
    const shorter = runningBoard()
    run(shorter).events = run(shorter).events.slice(0, 10)
    expect(diffRuns(run(prev), run(shorter), { at: shorter.at }).first).toBe(true)
  })

  it('lists an old event as new but does not fly it', () => {
    const prev = runningBoard()
    const next = plus({ kind: 'handoff', from: 'ops', to: 'reviewer', role: 'reviewer', at: runningBoard().at - LATE_S - 5 })
    const d = diffRuns(run(prev), run(next), { at: next.at })
    expect(d.fresh).toHaveLength(1)
    expect(d.items).toEqual([])
  })

  it('caps one poll at MAX_ITEMS particles, keeping the important ones', () => {
    const prev = runningBoard()
    let next = clone(prev)
    for (let i = 0; i < MAX_ITEMS + 10; i++) next = withEvent(next, { kind: 'tool', role: 'frontend', text: `前端：tool ${i}`, at: next.at - 10 + i * 0.1 })
    next = withEvent(next, { kind: 'bounce', role: 'backend', from: 'tests', to: 'backend', text: 'AC-6 失败，打回后端' })
    const d = diffRuns(run(prev), run(next), { at: next.at })
    expect(d.items).toHaveLength(MAX_ITEMS)
    expect(d.items.some((i) => i.kind === 'bounce')).toBe(true)
    // still in time order
    expect(d.items.map((i) => i.t)).toEqual([...d.items.map((i) => i.t)].sort((a, b) => a - b))
  })
})

describe('particle labels: what a particle carries, read from its event', () => {
  it('names the handed-over output and the failing criteria', () => {
    expect(handoffLabel('验收标准交给架构师')).toBe('验收标准')
    expect(handoffLabel('测试、契约、设计交给前端')).toBe('测试、契约、设计')
    expect(handoffLabel('前端开工')).toBeNull()
    expect(bounceLabel('AC-6、AC-7 失败，打回后端')).toBe('AC-6、AC-7')
    expect(bounceLabel('AC-1、AC-2、AC-3 失败')).toBe('AC-1、AC-2…')
    expect(bounceLabel('打回后端')).toBeNull()
  })
})

describe('eventItem', () => {
  const b = runningBoard()
  const ctx = { roles: new Set(run(b).roles.map((l) => l.key)), tests: run(b).tests }
  const ev = (kind: string, more: Record<string, unknown> = {}) => ({ seq: 99, at: b.at, kind, role: null, text: '', from: null, to: null, ...more }) as Parameters<typeof eventItem>[0]

  it('blips the node for spawned, done, tool, committed', () => {
    expect(eventItem(ev('spawned', { role: 'backend' }), 'r', ctx)).toMatchObject({ from: 'orch', to: 'backend', tone: 'run', shape: 'comet' }) // dispatched by the orchestrator
    expect(eventItem(ev('done', { role: 'ops' }), 'r', ctx)).toMatchObject({ to: 'ops', tone: 'ok', shape: 'check' })
    expect(eventItem(ev('tool', { role: 'frontend' }), 'r', ctx)).toMatchObject({ to: 'frontend', shape: 'spark', prio: 0 })
    expect(eventItem(ev('committed', { role: 'frontend' }), 'r', ctx)).toMatchObject({ to: 'frontend', shape: 'spark' })
  })

  it('ignores roles that are not on the graph', () => {
    expect(eventItem(ev('spawned', { role: 'nobody' }), 'r', ctx)).toBeNull()
    expect(eventItem(ev('handoff', { from: 'nobody', to: 'reviewer' }), 'r', ctx)).toMatchObject({ from: 'reviewer', to: 'reviewer' })
  })
})

describe('structured event data wins over text parsing', () => {
  const ctx = { roles: new Set(['pm', 'architect', 'backend']), tests: { at: null, command: '', cases: [], passed: 0, failed: 0, total: 0, history: [] } }
  const ev = (over: Partial<TeamEvent>): TeamEvent => ({ seq: 1, at: 1, kind: 'handoff', role: null, text: '', from: null, to: null, data: null, ...over })
  it('handoff label comes from data.carry, and the backend wording parses too', () => {
    expect(eventItem(ev({ kind: 'handoff', from: 'pm', to: 'architect', text: '产品经理把 验收标准 交给架构师', data: { carry: '验收标准' } }), 'r', ctx)?.label).toBe('验收标准')
    expect(eventItem(ev({ kind: 'handoff', from: 'pm', to: 'architect', text: '产品经理把 验收标准 交给架构师' }), 'r', ctx)?.label).toBe('验收标准')
  })
  it('tests score and bounce cases come from data', () => {
    expect(eventItem(ev({ kind: 'tests', text: '测试', data: { passed: 3, total: 5 } }), 'r', ctx)?.label).toBe('3/5')
    expect(eventItem(ev({ kind: 'bounce', to: 'backend', text: '打回后端', data: { cases: ['AC-6'] } }), 'r', ctx)?.label).toBe('AC-6')
  })
})
