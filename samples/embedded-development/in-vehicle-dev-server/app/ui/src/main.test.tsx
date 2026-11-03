import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, test, vi } from 'vitest'
import type { Board } from './types'
import { apiCalls, apiError, setApiRoutes } from './test/stubs/app-sdk'
import { clone, emptyBoard, multiRunBoard, readinessOf, runningBoard, setCase, withEvent } from './test/fixtures'
import { TeamPage, mostActive } from './main'
import { SCENARIOS } from './board/Header'

const BOARD = 'GET /api/apps/vstatd-team/board*'
const RUNS = '/api/apps/vstatd-team/runs'
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
    expect(apiCalls[0].path).toBe('/api/apps/vstatd-team/board')
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
    setApiRoutes({ [BOARD]: () => runningBoard(), 'POST /api/apps/vstatd-team/runs': () => ({ run: 'r1007b' }) })
    render(<TeamPage pollMs={POLL} />)
    await screen.findAllByTestId('kt-lane')
    await user.click(screen.getByRole('button', { name: '新需求' }))
    await user.clear(screen.getByLabelText('交给 agent 团队的需求'))
    await user.type(screen.getByLabelText('交给 agent 团队的需求'), '做一个读书会报名页')
    await user.click(screen.getByRole('button', { name: '交给团队' }))
    await waitFor(() => expect(apiCalls.find((c) => c.method === 'POST' && c.path === RUNS)).toEqual({ method: 'POST', path: RUNS, body: { requirement: '做一个读书会报名页' } }))
    await waitFor(() => expect(apiCalls.some((c) => c.method === 'GET' && c.path === '/api/apps/vstatd-team/board?run=r1007b')).toBe(true))
    expect(screen.queryByLabelText(/^需求/)).toBeNull()
  })

  test('the form proposes the demo requirement; a refused start shows why', async () => {
    const user = userEvent.setup()
    let ok = false
    setApiRoutes({
      [BOARD]: () => runningBoard(),
      'POST /api/apps/vstatd-team/runs': () => {
        if (!ok) throw apiError(409, 'busy', '已经有一个运行在跑')
        return { run: 'r1007b' }
      },
    })
    render(<TeamPage />)
    await screen.findAllByTestId('kt-lane')
    await user.click(screen.getByRole('button', { name: '新需求' }))
    await user.click(screen.getByRole('button', { name: '交给团队' }))
    expect(await within(screen.getByRole('form', { name: '给 agent 团队派需求' })).findByRole('alert')).toHaveTextContent('已经有一个运行在跑（409）')
    expect(apiCalls.filter((c) => c.method === 'POST' && c.path === RUNS).map((c) => c.body)).toEqual([{ requirement: SCENARIOS[0].text }])
    ok = true
    await user.click(screen.getByRole('button', { name: '交给团队' }))
    await waitFor(() => expect(screen.queryByLabelText(/^需求/)).toBeNull())
  })

  test('停止 asks first; only 确认停止 posts the stop', async () => {
    const user = userEvent.setup()
    setApiRoutes({ [BOARD]: () => runningBoard(), 'POST /api/apps/vstatd-team/runs/r1006a/stop': () => ({ ok: true }) })
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
    await waitFor(() => expect(apiCalls.filter((c) => c.method === 'POST').map((c) => c.path)).toEqual(['/api/apps/vstatd-team/runs/r1006a/stop']))
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull())
  })

  test('no runs: the work item, the flow from 分诊 to 签字, what this Mac still needs, and the start form', async () => {
    const user = userEvent.setup()
    setApiRoutes({ [BOARD]: () => emptyBoard(), 'GET /api/apps/vstatd-team/readiness': () => readinessOf(),
      'POST /api/apps/vstatd-team/readiness/doctor': () => readinessOf(), 'POST /api/apps/vstatd-team/bench/decide': () => ({ ok: true, decision: { verdict: 'approved' } }), 'POST /api/apps/vstatd-team/runs': () => ({ id: 'r1' }) })
    render(<TeamPage />)
    const empty = await screen.findByTestId('kt-empty')
    expect(within(empty).getByRole('heading', { name: 'vstatd 本批：修待办里的发现，拆分 Service::run()，行为不变' })).toBeInTheDocument()
    const steps = within(empty).getByTestId('kt-flow-steps')
    expect([...steps.querySelectorAll('thead th b')].map((b) => b.textContent)).toEqual(
      ['分诊', '关卡：分诊', '架构', '关卡：开工', '测试先行', '开发 ×2 并行', '上台架前检查', '评审', '台架：部署、回放', '台架后检查', '独立重跑', '签字放行'])
    const cell = (actor: string, step: string) => steps.querySelector(`tr[data-actor="${actor}"] td[data-step="${step}"]`)!
    expect(cell('bench', 'bench')).toHaveTextContent('每个动作在 bench/console.py 按构建摘要批准')
    expect(cell('agent', 'tests-first')).toHaveTextContent(/^测试给要测的修复写测试$/)
    expect(cell('app', 'tests-first')).toHaveTextContent(/^app 在基线提交上跑，每个都必须失败$/)
    expect(cell('person', 'gate-triage')).toHaveTextContent('你逐题决定')
    expect(cell('agent', 'gate-triage')).toHaveClass('is-empty')
    const items = await within(empty).findAllByTestId('kt-ready-item')
    expect(items.map((i) => i.dataset.key)).toEqual(['knowledge', 'image', 'doctor', 'target', 'baseline', 'console'])
    const item = (k: string) => items.find((i) => i.dataset.key === k)!
    expect(item('image')).toHaveTextContent('✔构建容器镜像 vstatd-build:amd64测试先行起要在本机（12 秒前查的）')
    expect(item('image').querySelector('code')).toBeNull()
    expect(item('target')).toHaveTextContent('上台架才要')
    expect(item('target').querySelector('code')).toHaveTextContent(/bench\/cc1\.sh start$/)
    expect(item('console')).toHaveTextContent('?操作台上台架才要app 看不出操作台开着没有')
    expect(within(empty).getByTestId('kt-ready')).toHaveTextContent('台架没准备好也能先开始')
    const waiting = within(empty).getByTestId('kt-ready-pending')
    expect(waiting).toHaveTextContent('台架上有 1 个请求等你批准')
    expect(waiting).toHaveTextContent('部署 bc93723c0cb0')
    expect(waiting).toHaveTextContent('还剩 168 秒，超时自动拒绝')
    const cmds = Array.from(waiting.querySelectorAll('code.kt-ready-cmd')).map((c) => c.textContent)
    expect(cmds[0]).toMatch(/console\.py approve 20261103T094307-deploy-ac78 --digest bc93723c0cb0$/)
    expect(cmds[1]).toMatch(/console\.py refuse 20261103T094307-deploy-ac78 --reason <原因>$/)
    // approving needs the digest typed, as at the console; the bench's own decide() then decides
    const approve = within(waiting).getByRole('button', { name: '批准' })
    expect(approve).toBeDisabled()
    await user.type(within(waiting).getByLabelText('构建摘要的前 6 位'), 'bc9372')
    expect(approve).toBeEnabled()
    await user.click(approve)
    await waitFor(() => expect(apiCalls.find((c) => c.path === '/api/apps/vstatd-team/bench/decide')?.body)
      .toEqual({ id: '20261103T094307-deploy-ac78', verdict: 'approve', digest: 'bc9372', reason: '' }))
    expect(await within(waiting).findByRole('status')).toHaveTextContent('已批准')
    expect(within(empty).queryByText(/好产品|意图|安卓/)).toBeNull()
    await user.click(within(empty).getByRole('button', { name: '重跑 doctor.sh' }))
    await waitFor(() => expect(apiCalls.some((c) => c.method === 'POST' && c.path === '/api/apps/vstatd-team/readiness/doctor')).toBe(true))
    expect(screen.queryAllByTestId('kt-lane')).toHaveLength(0)
    expect(screen.queryByRole('button', { name: '停止' })).toBeNull()
    await user.clear(within(empty).getByLabelText('交给 agent 团队的需求'))
    await user.type(within(empty).getByLabelText('交给 agent 团队的需求'), '做一个社团招新页')
    await user.click(within(empty).getByRole('button', { name: '交给团队' }))
    await waitFor(() => expect(apiCalls.find((c) => c.method === 'POST' && c.path === RUNS)?.body).toEqual({ requirement: '做一个社团招新页' }))
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
    expect(apiCalls.some((c) => c.path === '/api/apps/vstatd-team/board?run=r1005z')).toBe(true)
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
