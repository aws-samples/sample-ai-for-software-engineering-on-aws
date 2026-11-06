import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, test } from 'vitest'
import type { Board, RunDetail, TeamEvent } from '../types'
import { apiCalls, setApiRoutes } from '../test/stubs/app-sdk'
import { clone, runningBoard } from '../test/fixtures'
import raw from '../test/fixtures/replay-im.json'
import { TeamPage } from '../main'
import { pickSpeed } from './Replay'
import { replayAt, replaySpan } from './timeline'

const API = '/api/apps/vstatd-team'

/** A real finished run: the Private IM password rules, sent back once at the 安全 gate (r1012307c). */
const im = () => clone(raw) as unknown as { run: RunDetail; events: TeamEvent[] }
const at = (dt: number) => {
  const { run, events } = im()
  return replayAt(run, events, replaySpan(run, events).start + dt)
}
const lane = (r: RunDetail, key: string) => r.roles.find((l) => l.key === key)!

describe('回放：一次跑完的运行按记录重放', () => {
  test("a check's verdict and the bench's step are what the record said by then, not how the run ended", () => {
    const { run } = im()
    const s = replaySpan(run, im().events).start
    const ev = (dt: number, kind: string, code: string, data: unknown = null) => ({ seq: dt, at: s + dt, kind, role: null, text: code, from: null, to: null, data, code, params: {} }) as unknown as TeamEvent
    run.tests.cases = [{ ...run.tests.cases[0], id: 'build', status: 'pass', verdict: 'PASS' }]
    run.bench = { step: 'done', running: null, held: null, history: [], state: { supply: null } } as unknown as RunDetail['bench']
    const events = [ev(1, 'tests', 'tests.score', { passed: 0, total: 1, cases: [['build', 'fail']] }), ev(2, 'bench', 'bench.go'), ev(3, 'bench', 'bench.replay'), ev(4, 'run', 'run.done_ok')]
    const r1 = replayAt(run, events, s + 1.5)
    expect(r1.tests.cases[0]).toMatchObject({ status: 'fail', verdict: 'FAIL' })
    expect(r1.bench?.step).toBeNull()
    expect(replayAt(run, events, s + 3.5).bench?.step).toBe('replay')
    expect(replayAt(run, events, s + 4.5).bench?.step).toBe('done')
  })

  test('the bench at a moment of the replay is what the record said then; what it did not say is not shown', async () => {
    const { benchAt } = await import('./timeline')
    const at = (s: string) => Date.parse(s) / 1000
    const bench = { step: 'done', running: null, held: null, doctor: null, run_dir: null, artifact: null, console: null,
      state: { target: { state: 'off', why: 'now' }, supply: { voltage_v: 0, kl15: 'off', set_by: '' }, pending: [], actions: [] },
      history: [
        { at: '2026-11-03T02:15:21Z', event: 'target', state: 'known', why: 'done: replay (an earlier run)' },
        { at: '2026-11-03T01:40:17Z', event: 'supply', voltage_v: 13.5, kl15: 'on', by: 'Release owner' },
        { at: '2026-11-03T10:01:29Z', event: 'request', id: 'q1', action: 'deploy', digest: 'abc', detail: 'vstatd' },
        { at: '2026-11-03T10:03:12Z', event: 'target', state: 'busy', why: 'deploy in progress' },
      ] } as unknown as NonNullable<RunDetail['bench']>
    const deploy = benchAt(bench, at('2026-11-03T10:02:00Z'))  // waiting at the console: the bench as it was before the run
    expect(deploy.state.target).toEqual({ state: 'known', why: 'done: replay (an earlier run)' })
    expect(deploy.state.supply).toMatchObject({ voltage_v: 13.5, kl15: 'on' })
    expect(deploy.state.pending.map((p) => p.id)).toEqual(['q1'])
    expect(benchAt(bench, at('2026-11-03T10:03:13Z')).state.target.state).toBe('busy')
    const before = benchAt(bench, at('2026-11-03T00:00:00Z'))  // nothing recorded yet: not the bench as it is now
    expect(before.replay).toEqual({ target: false, supply: false })
    expect(before.state.target.state).not.toBe('off')
    const { BenchPanel } = await import('./Bench')
    render(<BenchPanel bench={{ ...before, doctor: null } as NonNullable<RunDetail['bench']>} />)
    const panel = screen.getByTestId('kt-bench')
    expect(panel).toHaveTextContent('回放中，台架状态不显示')
    expect(panel).not.toHaveTextContent('没开机')
  })

  test('tests first shows the new tests failing; after the bench, the checks that ran with what the rerun says of them', () => {
    const { run } = im()
    const s = replaySpan(run, im().events).start
    const ev = (dt: number, data: unknown) => ({ seq: dt, at: s + dt, kind: 'tests', role: null, text: '', from: null, to: null, data, code: null, params: {} }) as unknown as TeamEvent
    run.release = { checks: [{ name: 'logdiff', verdict: 'PASS', tier: 'emulation', summary: '328 of 328 baseline entries paired', reasons: [] }] } as unknown as RunDetail['release']
    const events = [ev(1, { first: ['A.F003_Fails', 'B.fails'] }), ev(2, { checks: [['runtime-limits', 'PASS'], ['logdiff', 'PASS']], phase: 'after_bench' })]
    const first = replayAt(run, events, s + 1.5).tests
    expect([first.passed, first.total]).toEqual([0, 2])
    expect(first.cases.map((c) => [c.ac, c.status])).toEqual([['F-003', 'fail'], [null, 'fail']])
    const after = replayAt(run, events, s + 2.5).tests
    expect([after.passed, after.total]).toEqual([2, 2])
    expect(after.cases.find((c) => c.id === 'logdiff')).toMatchObject({ verdict: 'PASS', tier: 'emulation', message: '328 of 328 baseline entries paired' })
  })

  test('the run spans its record; the speed plays it in about a minute and a half', () => {
    const { run, events } = im()
    const sp = replaySpan(run, events)
    expect(Math.round(sp.end - sp.start)).toBe(458)
    expect(pickSpeed(458)).toBe(10)
    expect(pickSpeed(4664)).toBe(60)
    expect(pickSpeed(20_000)).toBe(120)
  })

  test('at the requirement gate: the product manager waits for the person, nobody else has started', () => {
    const r = at(80)
    expect(r.status).toBe('gating')
    expect(r.ended_at).toBeNull()
    expect(lane(r, 'product')).toMatchObject({ status: 'merged', gate: 'pending' })
    expect(['frontend1', 'frontend2', 'tester', 'security', 'deploy'].map((k) => lane(r, k).status)).toEqual(Array(5).fill('waiting'))
    expect(r.tests.total).toBe(0)
    expect(r.merges).toHaveLength(1)
    expect(r.signoff).toBeNull()
    expect(r.credits).toBe(lane(r, 'product').credits) // only the product manager's round is over
  })

  test('the test wall is what the last test run before t left: 8 of 9 after the first merge', () => {
    const r = at(170)
    expect([r.tests.passed, r.tests.total]).toEqual([8, 9])
    expect(r.tests.cases).toHaveLength(9)
    expect(r.tests.cases.filter((c) => c.status === 'fail')).toHaveLength(1)
    expect(lane(r, 'frontend1').status).toBe('merged')
    expect(lane(r, 'frontend2').status).toBe('running')
  })

  test('the person sends it back at the 安全 gate: 前端开发 #1 does a second round, the reviewer waits', () => {
    const before = at(260)
    expect(before.status).toBe('gating')
    expect(lane(before, 'security')).toMatchObject({ status: 'done', gate: 'pending' })
    const r = at(280)
    expect(lane(r, 'frontend1')).toMatchObject({ status: 'fixing', attempt: 2, doing: '按评审意见改' })
    expect(lane(r, 'frontend1').agent?.elapsed_s).toBeGreaterThan(0)
    expect(lane(r, 'security')).toMatchObject({ status: 'waiting', gate: null })
    const again = at(320)
    expect(lane(again, 'security')).toMatchObject({ status: 'running', attempt: 2 }) // a second look, not a fix
    expect(again.status).toBe('reviewing')
  })

  test("a member's credits show once its last round is over; the run's are the sum of those so far", () => {
    const { run } = im()
    const r = at(170)
    expect(lane(r, 'product').credits).toBe(lane(run, 'product').credits)
    expect(lane(r, 'frontend1').credits).toBeNull() // merged, but the 安全 gate sends it back for a second round later
    expect(lane(r, 'frontend2').credits).toBeNull() // still working
    expect(r.credits).toBe(lane(run, 'product').credits)
    expect(at(80 - 79).credits).toBeNull()
  })

  test('the knowledge lookups show up when they happened', () => {
    expect(at(10).knowledge.hits).toHaveLength(0)
    expect(at(120).knowledge.hits.length).toBeGreaterThan(0)
  })

  test('a member the approved plan left out is in the flow until its 「skipped」 event, then out with the reason', () => {
    const { run, events } = im()
    const start = replaySpan(run, events).start
    const out = run.roles.find((l) => l.key !== 'product' && l.writable.length > 0)!
    Object.assign(out, { status: 'skipped', summary: '这次用不到：这次只改价格' })
    const ev = { seq: 99_999, at: start + 60, kind: 'skipped', role: out.key, text: `${out.title}：这次用不到`, from: null, to: null, data: null } as TeamEvent
    const all = [...events, ev]
    expect(replayAt(run, all, start + 30).roles.find((l) => l.key === out.key)!.status).toBe('waiting')
    const after = replayAt(run, all, start + 90).roles.find((l) => l.key === out.key)!
    expect([after.status, after.summary]).toEqual(['skipped', '这次用不到：这次只改价格'])
  })

  test('at the end the board is the run as it finished', () => {
    const { run } = im()
    const r = at(10_000)
    expect(r.status).toBe(run.status)
    expect(r.tests.passed).toBe(run.tests.passed)
    expect(r.roles.map((l) => l.status)).toEqual(run.roles.map((l) => l.status))
  })

  test('a way into the board opens the run and starts its replay at the speed asked for', async () => {
    const { run, events } = im()
    const board = runningBoard() as Board
    board.run = run
    board.runs = [{ ...board.runs[0], id: run.id, title: run.title, status: run.status, started_at: run.started_at, ended_at: run.ended_at, tests: { passed: 21, failed: 0, total: 21 } }]
    setApiRoutes({
      [`GET ${API}/board*`]: () => clone(board),
      [`GET ${API}/runs/${run.id}/events`]: () => ({ run: run.id, events }),
    })
    render(<TeamPage pollMs={60_000} entry={{ run: run.id, replay: 30 }} />)
    const bar = await screen.findByRole('group', { name: '回放' })
    expect(apiCalls.some((c) => c.path === `${API}/board?run=${run.id}`)).toBe(true)
    await waitFor(() => expect(within(bar).getByRole('radio', { name: '30×' }).getAttribute('aria-checked')).toBe('true'))
  })

  test('a way in at a moment of a finished run: its replay, paused there; at a phase: paused where it began, the phase picked out', async () => {
    const { run, events } = im()
    const board = runningBoard() as Board
    board.run = run
    board.runs = [{ ...board.runs[0], id: run.id, title: run.title, status: run.status, started_at: run.started_at, ended_at: run.ended_at, tests: { passed: 21, failed: 0, total: 21 } }]
    setApiRoutes({
      [`GET ${API}/board*`]: () => clone(board),
      [`GET ${API}/runs/${run.id}/events`]: () => ({ run: run.id, events }),
    })
    const { unmount } = render(<TeamPage pollMs={60_000} entry={{ run: run.id, role: 'security', at: 120 }} />)
    const bar = await screen.findByRole('group', { name: '回放' })
    await waitFor(() => expect(within(bar).getByRole('button', { name: '播放' })).toBeInTheDocument())  // paused
    expect(bar).toHaveTextContent('2:00 /')
    expect(screen.getByText('安全审查', { selector: '.kt-focuschip, .kt-focuschip *' })).toBeInTheDocument()
    unmount()
    render(<TeamPage pollMs={60_000} entry={{ run: run.id, phase: 'construction' }} />)
    const bar2 = await screen.findByRole('group', { name: '回放' })
    await waitFor(() => expect(bar2).toHaveTextContent('1:33 /'))  // the first construction role was set to work 92.9 s in
    const chip = screen.getByTestId('kt-phasebar')
    expect(chip).toHaveTextContent('3 构建')
  })

  test('a way in at a gate looks at that role; one for 新需求 opens the form', async () => {
    const board = runningBoard() as Board
    setApiRoutes({ [`GET ${API}/board*`]: () => clone(board) })
    const key = board.run!.roles[1].key
    const { unmount } = render(<TeamPage pollMs={60_000} entry={{ run: board.run!.id, gate: key }} />)
    expect(await screen.findByText(board.run!.roles[1].title, { selector: '.kt-focuschip, .kt-focuschip *' })).toBeInTheDocument()
    unmount()
    render(<TeamPage pollMs={60_000} entry={{ new: 'promo' }} />)
    expect(await screen.findByRole('form', { name: '给 agent 团队派需求' })).toBeInTheDocument()
  })

  test('the board replays a finished run: no write actions while it plays, back to the record on exit', async () => {
    const user = userEvent.setup()
    const { run, events } = im()
    const board = runningBoard() as Board
    board.run = run
    board.runs = [{ ...board.runs[0], id: run.id, title: run.title, status: run.status, started_at: run.started_at, ended_at: run.ended_at, tests: { passed: 21, failed: 0, total: 21 } }]
    setApiRoutes({
      [`GET ${API}/board*`]: () => clone(board),
      [`GET ${API}/runs/${run.id}/events`]: () => ({ run: run.id, events }),
    })
    render(<TeamPage pollMs={60_000} />)
    await user.click(await screen.findByRole('button', { name: '▶ 回放' }))
    const bar = await screen.findByRole('group', { name: '回放' })
    expect(apiCalls.some((c) => c.method === 'GET' && c.path.endsWith(`/runs/${run.id}/events`))).toBe(true)
    expect(within(bar).getByRole('radio', { name: '10×' }).getAttribute('aria-checked')).toBe('true')
    expect(screen.queryByRole('button', { name: '新需求' })).toBeNull()
    expect(screen.queryByRole('button', { name: '从列表里删除这次运行' })).toBeNull()

    await user.click(within(bar).getByRole('button', { name: '暂停' }))
    const sp = replaySpan(run, events)
    fireEvent.change(within(bar).getByRole('slider', { name: '回放进度' }), { target: { value: String(Math.round(sp.start + 262)) } })
    expect(await within(bar).findByText(/^4:22 \/ 7:38$/)).toBeTruthy()
    const gate = await screen.findByTestId('kt-gate')
    expect(within(gate).getByText('✓ 批准安全')).toBeTruthy()
    expect(within(gate).queryByRole('button')).toBeNull() // a replay's gate is a picture, not a decision
    expect(screen.queryByTestId('kt-sign')).toBeNull()

    await user.click(within(bar).getByRole('button', { name: '退出回放' }))
    expect(screen.queryByRole('group', { name: '回放' })).toBeNull()
    expect(await screen.findByRole('button', { name: '新需求' })).toBeTruthy()
    expect(screen.queryByTestId('kt-gate')).toBeNull()
  })
})
