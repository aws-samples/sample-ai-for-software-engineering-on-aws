import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, test, vi } from 'vitest'
import type { Board, RunDetail, TeamEvent } from '../types'
import { apiCalls, setApiRoutes } from '../test/stubs/app-sdk'
import { clone, runningBoard } from '../test/fixtures'
import raw from '../test/fixtures/replay-im.json'
import { TeamPage } from '../main'
import { pickSpeed } from './Replay'
import { replayAt, replaySpan } from './timeline'

const API = '/api/apps/aidlc-team'

/** A real finished run: the Private IM password rules, sent back once at the 安全 gate (r1012307c). */
const im = () => clone(raw) as unknown as { run: RunDetail; events: TeamEvent[] }
const at = (dt: number) => {
  const { run, events } = im()
  return replayAt(run, events, replaySpan(run, events).start + dt)
}
const lane = (r: RunDetail, key: string) => r.roles.find((l) => l.key === key)!

describe('回放：一次跑完的运行按记录重放', () => {
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

  test('the deployment and the knowledge lookups show up when they happened', () => {
    expect(lane(at(400), 'deploy').deployed).toBeNull()
    expect(lane(at(458), 'deploy').deployed?.url).toBe('http://127.0.0.1:3300/')
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

  test('a way into the board (from the CTO view) opens the run and starts its replay at the speed asked for', async () => {
    const { run, events } = im()
    const board = runningBoard() as Board
    board.run = run
    board.runs = [{ ...board.runs[0], id: run.id, title: run.title, status: run.status, started_at: run.started_at, ended_at: run.ended_at, tests: { passed: 21, failed: 0, total: 21 } }]
    setApiRoutes({
      [`GET ${API}/board*`]: () => clone(board),
      [`GET ${API}/runs/${run.id}/events`]: () => ({ run: run.id, events }),
    })
    render(<TeamPage pollMs={60_000} entry={{ run: run.id, replay: 30 }} onCto={() => {}} />)
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
    const onItem = vi.fn()
    const { unmount } = render(<TeamPage pollMs={60_000} entry={{ run: run.id, role: 'security', at: 120 }} onItem={onItem} />)
    const bar = await screen.findByRole('group', { name: '回放' })
    await waitFor(() => expect(within(bar).getByRole('button', { name: '播放' })).toBeInTheDocument())  // paused
    expect(bar).toHaveTextContent('2:00 /')
    expect(screen.getByText('安全审查', { selector: '.kt-focuschip, .kt-focuschip *' })).toBeInTheDocument()
    unmount()
    render(<TeamPage pollMs={60_000} entry={{ run: run.id, phase: 'construction' }} onItem={onItem} />)
    const bar2 = await screen.findByRole('group', { name: '回放' })
    await waitFor(() => expect(bar2).toHaveTextContent('1:33 /'))  // the first construction role was set to work 92.9 s in
    const chip = screen.getByTestId('kt-phasebar')
    expect(chip).toHaveTextContent('3 构建')
    fireEvent.click(within(chip).getByRole('button', { name: '这次交付的价值流 ↗' }))
    expect(onItem).toHaveBeenCalledWith({ run: run.id, at: 93 })  // back to its 价值流 at the moment the board is at
  })

  test('opened from another view: where it is, why this run, the way back; the role bar leads back to the 价值流 at the moment', async () => {
    const { run, events } = im()
    const board = runningBoard() as Board
    board.run = run
    board.runs = [{ ...board.runs[0], id: run.id, title: run.title, status: run.status, started_at: run.started_at, ended_at: run.ended_at, tests: { passed: 21, failed: 0, total: 21 } }]
    setApiRoutes({ [`GET ${API}/board*`]: () => clone(board), [`GET ${API}/runs/${run.id}/events`]: () => ({ run: run.id, events }) })
    const onBack = vi.fn(), onCto = vi.fn(), onItem = vi.fn()
    const { unmount } = render(<TeamPage pollMs={60_000} entry={{ run: run.id, phase: 'construction', from: 'cto', pick: 'latest' }} onBack={onBack} onCto={onCto} onItem={onItem} />)
    const where = await screen.findByTestId('kt-where')
    await waitFor(() => expect(where).toHaveTextContent('团队看板 · 构建阶段 · 回放 1:32（暂停）'))
    expect(where).toHaveTextContent('此刻没有运行在「构建」这一列，这里打开的是最近一次实测。')
    fireEvent.click(within(where).getByRole('button', { name: '← 返回 CTO 视图' }))
    expect(onBack).toHaveBeenCalled()
    fireEvent.click(within(where).getByRole('button', { name: 'CTO 视图' }))
    expect(onCto).toHaveBeenCalledWith({ hl: run.id })
    unmount()
    render(<TeamPage pollMs={60_000} entry={{ run: run.id, role: 'security', at: 120, from: 'item' }} onItem={onItem} />)
    const bar = await screen.findByTestId('kt-focusbar')
    await waitFor(() => expect(screen.getByTestId('kt-where')).toHaveTextContent('安全关卡'))
    fireEvent.click(within(bar).getByRole('button', { name: '这次交付的价值流 ↗' }))
    expect(onItem).toHaveBeenCalledWith({ run: run.id, at: 120 })
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
