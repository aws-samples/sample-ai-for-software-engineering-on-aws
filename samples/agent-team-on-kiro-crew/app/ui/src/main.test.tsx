import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, test, vi } from 'vitest'
import type { Board } from './types'
import { apiCalls, apiError, setApiRoutes } from './test/stubs/app-sdk'
import { clone, emptyBoard, multiRunBoard, runningBoard, setCase, withEvent } from './test/fixtures'
import { TeamPage, mostActive } from './main'
import { SCENARIOS } from './board/Header'

const BOARD = 'GET /api/apps/aidlc-team/board*'
const ROUTE = 'POST /api/apps/aidlc-team/route'
const RUNS = '/api/apps/aidlc-team/runs'
/** What POST /route answers for an MVP requirement: the shop team, picked by the keyword. */
const shopPick = () => ({
  team: {
    file: 'team-shop.json', name: '网上小店 · MVP 团队', scope: 'mvp', keywords: ['mvp'], priority: 50, fallback: false, official_stages: 23,
    needs_source: false, starter: 'starters/shop', agents: ['aidlc-product-agent', 'aidlc-developer-agent'],
    stages: ['1.1 意图捕获', '3.5 代码生成'], extra_stages: [], extra_note: '',
    roles: [
      { key: 'product', title: '产品', phase: 'ideation', stage: '1.1 意图捕获', aidlc_agent: 'aidlc-product-agent', gate: false },
      { key: 'architect', title: '架构', phase: 'inception', stage: '2.8 接口约定', aidlc_agent: 'aidlc-architect-agent', gate: true },
      { key: 'catalog', title: '前端·商品列表', phase: 'construction', stage: '3.5 代码生成', aidlc_agent: 'aidlc-developer-agent', gate: false },
    ],
  },
  matched: ['mvp'], why: 'AI-DLC mvp 流程（新产品的第一版）', others: [], roster: [], teams: [],
})
const POLL = 25

/** A board route that serves *first* until `next()` switches it to *second*. */
function twoPhase(first: Board, second: Board) {
  let phase = 1
  setApiRoutes({ [BOARD]: () => clone(phase === 1 ? first : second) })
  return { next: () => (phase = 2) }
}

const lanes = () => screen.getAllByTestId('kt-lane')
const laneOf = (key: string) => lanes().find((l) => l.dataset.role === key)!
const particles = (c: HTMLElement) => c.querySelectorAll('.kt-p[data-src]')
const sleep = (ms: number) => act(() => new Promise<void>((r) => setTimeout(r, ms)))

function reduceMotion() {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: query.includes('reduce'),
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
}

afterEach(() => {
  delete (HTMLElement.prototype as { requestFullscreen?: unknown }).requestFullscreen
})

describe('the board', () => {
  test('renders the running fixture: 8 lanes, 6/12, the violation, the conflict, the reviewer waiting', async () => {
    setApiRoutes({ [BOARD]: () => runningBoard() })
    render(<TeamPage />)
    expect(await screen.findAllByTestId('kt-lane')).toHaveLength(8)
    expect(lanes().map((l) => l.dataset.role)).toEqual(['pm', 'architect', 'designer', 'tester', 'backend', 'frontend', 'ops', 'reviewer'])
    expect(screen.getByTestId('kt-tests-counter')).toHaveTextContent('6/12')
    expect(screen.getByTestId('kt-saving')).toHaveTextContent('并行省了 23 分钟')
    expect(within(laneOf('frontend')).getByRole('alert')).toHaveTextContent('改了不属于它的 backend/server.js')
    const conveyor = screen.getByTestId('kt-conveyor')
    expect(within(conveyor).getByText('backend/server.js').closest('.kt-belt-chip')).toHaveClass('is-conflict')
    expect(within(conveyor).getByText('1 次冲突')).toBeInTheDocument()
    expect(within(laneOf('reviewer')).getByText('等 后端、前端、运维')).toBeInTheDocument()
    expect(within(laneOf('backend')).getByText('第 2 轮')).toBeInTheDocument()
    expect(within(laneOf('backend')).getByText('Editing backend/validate.js')).toBeInTheDocument()
    expect(screen.getAllByTestId('kt-cell')).toHaveLength(12)
    expect(screen.getByTestId('kt-station')).toHaveAccessibleName('测试 6/12')
    expect(within(screen.getByTestId('kt-graph')).getByRole('button', { name: /后端：修复中，第 2 轮/ })).toBeInTheDocument()
    expect(apiCalls[0].path).toBe('/api/apps/aidlc-team/board')
  })

  test('the first snapshot does not animate; a new handoff after it flies along its edge', async () => {
    const first = runningBoard()
    const second = withEvent(runningBoard(), { kind: 'handoff', role: 'reviewer', from: 'ops', to: 'reviewer', text: '运维的脚本交给评审' })
    const p = twoPhase(first, second)
    const { container } = render(<TeamPage pollMs={POLL} />)
    await screen.findAllByTestId('kt-lane')
    await sleep(120) // several polls of the same snapshot
    expect(particles(container)).toHaveLength(0)
    expect(container.querySelectorAll('.kt-cell-face.is-flip, .kt-belt-chip.is-new, .kt-ev.is-new')).toHaveLength(0)
    p.next()
    await waitFor(() => expect(container.querySelector('.kt-p[data-src="r1006a#32"]')).not.toBeNull())
    expect(container.querySelector('.kt-p[data-src="r1006a#32"]')).toHaveAttribute('data-kind', 'handoff')
    expect(container.querySelector('.kt-ev.is-new[data-seq="32"]')).not.toBeNull()
  })

  test('a bounce flies red from the test station; a test case going red → green flips', async () => {
    const second = withEvent(setCase(runningBoard(), 'api-signup.test.js#AC-6', 'pass'), { kind: 'bounce', role: 'backend', from: 'tests', to: 'backend', text: 'AC-7 失败，打回后端' })
    const p = twoPhase(runningBoard(), second)
    const { container } = render(<TeamPage pollMs={POLL} />)
    await screen.findAllByTestId('kt-lane')
    const cell = () => container.querySelector('[data-case="api-signup.test.js#AC-6"]')!
    expect(cell()).toHaveAttribute('data-status', 'fail')
    expect(cell().querySelector('.is-flip')).toBeNull()
    p.next()
    await waitFor(() => expect(cell()).toHaveAttribute('data-status', 'pass'))
    expect(cell().querySelector('.kt-cell-face.is-flip')).not.toBeNull()
    await waitFor(() => expect(container.querySelector('.kt-p.is-bounce[data-src="r1006a#32"]')).not.toBeNull())
    expect(screen.getByTestId('kt-tests-counter')).toHaveAccessibleName('测试通过 7/12')
    expect(screen.getByTestId('kt-announce')).toHaveTextContent('测试 6/12 → 7/12')
  })

  test('with reduced motion nothing flies or pulses, but the state still changes', async () => {
    reduceMotion()
    const second = withEvent(runningBoard(), { kind: 'handoff', role: 'reviewer', from: 'ops', to: 'reviewer', text: '运维的脚本交给评审' })
    const p = twoPhase(runningBoard(), second)
    const { container } = render(<TeamPage pollMs={POLL} />)
    await screen.findAllByTestId('kt-lane')
    expect(screen.getByTestId('kt-root')).toHaveAttribute('data-motion', 'reduce')
    p.next()
    expect(await within(screen.getByTestId('kt-feed')).findByText('运维的脚本交给评审')).toBeInTheDocument()
    await sleep(150)
    expect(particles(container)).toHaveLength(0)
    expect(container.querySelector('.kt-node-halo[style]')).toBeNull()
  })

  test('projection: fullscreen where the API exists, bigger type, no chrome; Esc or 退出投影 leaves it', async () => {
    const user = userEvent.setup()
    const fs = vi.fn().mockResolvedValue(undefined)
    HTMLElement.prototype.requestFullscreen = fs
    setApiRoutes({ [BOARD]: () => runningBoard() })
    render(<TeamPage />)
    await screen.findAllByTestId('kt-lane')
    await user.click(screen.getByRole('button', { name: '投影' }))
    const root = screen.getByTestId('kt-root')
    expect(root).toHaveAttribute('data-projection', 'true')
    expect(root).toHaveClass('is-projection')
    expect(fs).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('button', { name: '新需求' })).toBeNull()
    expect(screen.queryByRole('button', { name: '停止' })).toBeNull()
    expect(screen.queryByText('调试：探针')).toBeNull()
    await user.click(screen.getByRole('button', { name: '退出投影' }))
    expect(root).not.toHaveAttribute('data-projection')
    expect(screen.getByRole('button', { name: '新需求' })).toBeInTheDocument()
    // without the Fullscreen API: the CSS overlay, and Esc leaves it
    delete (HTMLElement.prototype as { requestFullscreen?: unknown }).requestFullscreen
    await user.click(screen.getByRole('button', { name: '投影' }))
    expect(root).toHaveAttribute('data-projection', 'true')
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(root).not.toHaveAttribute('data-projection')
  })

  test('开一个新运行 posts the requirement, then shows the new run', async () => {
    const user = userEvent.setup()
    setApiRoutes({ [BOARD]: () => runningBoard(), [ROUTE]: () => shopPick(), 'POST /api/apps/aidlc-team/runs': () => ({ run: 'r1007b' }) })
    render(<TeamPage pollMs={POLL} />)
    await screen.findAllByTestId('kt-lane')
    await user.click(screen.getByRole('button', { name: '新需求' }))
    // 组队预览: the orchestrator's pick for the requirement, before anything starts
    expect(await screen.findByText(/AI-DLC mvp 流程（新产品的第一版）/)).toBeInTheDocument()
    expect(within(screen.getByTestId('kt-pick')).getByText(/覆盖 AI-DLC mvp 流程的 2 个阶段/)).toBeInTheDocument()
    await user.clear(screen.getByLabelText('交给 agent 团队的需求'))
    await user.type(screen.getByLabelText('交给 agent 团队的需求'), '做一个读书会报名页')
    await user.click(screen.getByRole('button', { name: '交给团队' }))
    await waitFor(() => expect(apiCalls.find((c) => c.method === 'POST' && c.path === RUNS)).toEqual({ method: 'POST', path: RUNS, body: { requirement: '做一个读书会报名页', team: 'auto' } }))
    await waitFor(() => expect(apiCalls.some((c) => c.method === 'GET' && c.path === '/api/apps/aidlc-team/board?run=r1007b')).toBe(true))
    expect(screen.queryByLabelText(/^需求/)).toBeNull()
  })

  test('the form proposes the demo requirement and auto 组队; a refused start shows why', async () => {
    const user = userEvent.setup()
    let ok = false
    setApiRoutes({
      [BOARD]: () => runningBoard(),
      'POST /api/apps/aidlc-team/runs': () => {
        if (!ok) throw apiError(409, 'busy', '已经有一个运行在跑')
        return { run: 'r1007b' }
      },
    })
    render(<TeamPage />)
    await screen.findAllByTestId('kt-lane')
    await user.click(screen.getByRole('button', { name: '新需求' }))
    await user.click(screen.getByRole('button', { name: '交给团队' }))
    expect(await within(screen.getByRole('form', { name: '给 agent 团队派需求' })).findByRole('alert')).toHaveTextContent('已经有一个运行在跑（409）')
    expect(apiCalls.filter((c) => c.method === 'POST' && c.path === RUNS).map((c) => c.body)).toEqual([{ requirement: SCENARIOS[0].text, team: 'auto' }])
    ok = true
    await user.click(screen.getByRole('button', { name: '交给团队' }))
    await waitFor(() => expect(screen.queryByLabelText(/^需求/)).toBeNull())
  })

  test('停止 asks first; only 确认停止 posts the stop', async () => {
    const user = userEvent.setup()
    setApiRoutes({ [BOARD]: () => runningBoard(), 'POST /api/apps/aidlc-team/runs/r1006a/stop': () => ({ ok: true }) })
    render(<TeamPage />)
    await screen.findAllByTestId('kt-lane')
    await user.click(screen.getByRole('button', { name: '停止' }))
    const dialog = screen.getByRole('alertdialog')
    expect(dialog).toHaveTextContent('停止「活动报名小站」？')
    expect(dialog).toHaveTextContent('在跑和排队的 2 个 agent 会被停掉')
    expect(apiCalls.some((c) => c.method === 'POST')).toBe(false)
    await user.click(within(dialog).getByRole('button', { name: '取消' }))
    expect(screen.queryByRole('alertdialog')).toBeNull()
    expect(apiCalls.some((c) => c.method === 'POST')).toBe(false)
    await user.click(screen.getByRole('button', { name: '停止' }))
    await user.click(screen.getByRole('button', { name: '确认停止' }))
    await waitFor(() => expect(apiCalls.filter((c) => c.method === 'POST').map((c) => c.path)).toEqual(['/api/apps/aidlc-team/runs/r1006a/stop']))
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull())
  })

  test('no runs: an inviting start panel with the AI-DLC team and the start form', async () => {
    const user = userEvent.setup()
    setApiRoutes({ [BOARD]: () => emptyBoard(), 'POST /api/apps/aidlc-team/runs': () => ({ id: 'r1' }) })
    render(<TeamPage />)
    const empty = await screen.findByTestId('kt-empty')
    expect(within(empty).getByRole('heading', { name: '做出来越来越便宜，好产品依然稀缺' })).toBeInTheDocument()
    for (const t of ['意图', '约束', '范围', '架构师', '需求', '界面', '合规与安全', '测试', '后端', '网页', '安卓', '运维', '评审']) expect(within(empty).getByText(t)).toBeInTheDocument()
    expect(screen.queryAllByTestId('kt-lane')).toHaveLength(0)
    expect(screen.queryByRole('button', { name: '停止' })).toBeNull()
    await user.clear(within(empty).getByLabelText('交给 agent 团队的需求'))
    await user.type(within(empty).getByLabelText('交给 agent 团队的需求'), '做一个社团招新页')
    await user.click(within(empty).getByRole('button', { name: '交给团队' }))
    await waitFor(() => expect(apiCalls.find((c) => c.method === 'POST' && c.path === RUNS)?.body).toEqual({ requirement: '做一个社团招新页', team: 'auto' }))
  })

  test('several runs: the picker asks the board for the chosen one', async () => {
    const user = userEvent.setup()
    setApiRoutes({ [BOARD]: (_b, path) => multiRunBoard(new URL(path, 'http://x').searchParams.get('run')) })
    render(<TeamPage pollMs={POLL} />)
    await screen.findAllByTestId('kt-lane')
    const picker = screen.getByRole('combobox', { name: '选择运行' })
    expect(within(picker).getAllByRole('option')).toHaveLength(3)
    await user.selectOptions(picker, 'r1005z')
    await waitFor(() => expect(screen.getByText('读书会报名页', { selector: '.kt-run-title' })).toBeInTheDocument())
    expect(apiCalls.some((c) => c.path === '/api/apps/aidlc-team/board?run=r1005z')).toBe(true)
    expect(screen.getByTestId('kt-tests-counter')).toHaveTextContent('12/12')
    expect(screen.queryByRole('button', { name: '停止' })).toBeNull()
  })

  test('clicking a role looks at that role only: the feed filters, the rest dims; again shows all', async () => {
    const user = userEvent.setup()
    setApiRoutes({ [BOARD]: () => runningBoard() })
    const { container } = render(<TeamPage />)
    await screen.findAllByTestId('kt-lane')
    const feed = screen.getByTestId('kt-feed')
    expect(within(feed).getByText('前端开工')).toBeInTheDocument()
    await user.click(within(laneOf('backend')).getByRole('button', { name: '只看后端' }))
    expect(within(feed).queryByText('前端开工')).toBeNull()
    expect(within(feed).getByText('后端开工')).toBeInTheDocument()
    expect(within(feed).getByText('AC-6、AC-7 失败，打回后端')).toBeInTheDocument()
    expect(laneOf('frontend')).toHaveClass('is-dim')
    expect(container.querySelector('.kt-node[data-role="frontend"]')).toHaveClass('is-dim')
    expect(container.querySelector('.kt-node[data-role="backend"]')).toHaveClass('is-focus')
    await user.click(within(laneOf('backend')).getByRole('button', { name: '不再只看后端' }))
    expect(within(feed).getByText('前端开工')).toBeInTheDocument()
  })

  test('跟随 enlarges and scrolls to the most active lane', async () => {
    const user = userEvent.setup()
    setApiRoutes({ [BOARD]: () => runningBoard() })
    render(<TeamPage />)
    await screen.findAllByTestId('kt-lane')
    expect(mostActive(runningBoard().run!)).toBe('frontend')
    await user.click(screen.getByRole('button', { name: '跟随' }))
    expect(laneOf('frontend')).toHaveClass('is-followed')
    expect(laneOf('backend')).not.toHaveClass('is-followed')
    expect(HTMLElement.prototype.scrollIntoView).toHaveBeenCalled()
  })

  test('a board without its route says so', async () => {
    render(<TeamPage />)
    expect(await screen.findByText(/后端还没有看板接口/)).toBeInTheDocument()
  })
})
