import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, test, vi } from 'vitest'
import { apiCalls, setApiRoutes } from '../test/stubs/app-sdk'
import { clone, vstatdBoard } from '../test/fixtures'
import { TeamPage } from '../main'
import { GateDialog, WORK_ITEM } from './Header'
import type { BenchRequest, Board, TestCase } from '../types'

const API = '/api/apps/vstatd-team'
const serve = (b: Board) => setApiRoutes({ [`GET ${API}/board*`]: () => clone(b) })

describe('the vstatd board', () => {
  test('the flow strip above the team graph: done steps checked, the bench step current, and what comes next', async () => {
    const b = vstatdBoard('bench')
    serve(b)
    render(<TeamPage pollMs={60_000} />)
    const flow = await screen.findByTestId('kt-flow')
    expect(flow.compareDocumentPosition(screen.getByTestId('kt-graph')) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    const cells = Object.fromEntries([...flow.querySelectorAll<HTMLElement>('[data-step]')].map((c) => [c.dataset.step, c.dataset.state]))
    expect(cells).toMatchObject({ triage: 'done', 'gate-start': 'done', review: 'done', bench: 'current', after: 'todo', signoff: 'todo' })
    const req = b.run!.bench!.state.pending[0]
    expect(within(flow).getByTestId('kt-flow-now')).toHaveTextContent('现在：等你批准部署（摘要 bc9372…）：在右边台架面板输入摘要前 6 位')
  })

  test('the check wall shows each check\'s verdict, evidence tier, owner and reasons', async () => {
    const b = vstatdBoard('bench')
    const cases = b.run!.tests.cases
    const fail: Partial<TestCase> = { status: 'fail', verdict: 'FAIL', message: 'src/frame_decoder.cpp:88: new finding nullPointer' }
    Object.assign(cases.find((c) => c.id === 'static')!, fail)
    Object.assign(cases.find((c) => c.id === 'trace')!, { status: 'blocked', verdict: 'BLOCKED', owner: null, message: 'triage: no approved triage' })
    serve(b)
    render(<TeamPage pollMs={60_000} />)
    const wall = await screen.findByTestId('kt-wall')
    expect(within(wall).getByRole('heading', { name: '检查墙' })).toBeInTheDocument()
    const rows = Object.fromEntries(within(wall).getAllByTestId('kt-check').map((r) => [r.dataset.case, r.textContent]))
    expect(rows.unit).toMatch(/^PASSunit证据：unit test\s*归开发 · 修复/)
    expect(rows.static).toMatch(/^FAILstatic/)
    expect(rows.static).toContain('src/frame_decoder.cpp:88: new finding nullPointer')
    expect(rows.trace).toMatch(/^BLOCKEDtrace交给人决定/)
    expect(rows.build).not.toContain('证据：') // tier n/a is not shown
  })

  test('the bench panel: target, supply, the request waiting with its digest and the console command, the record', async () => {
    serve(vstatdBoard('bench'))
    render(<TeamPage pollMs={60_000} />)
    const bench = await screen.findByTestId('kt-bench')
    expect(within(bench).getByTestId('kt-bench-step')).toHaveTextContent('部署：等操作台批准 · 进行中')
    expect(bench).toHaveTextContent('状态已知')
    expect(bench).toHaveTextContent('13.5 V · KL15 on')
    expect(within(bench).getByTestId('kt-bench-doctor')).toHaveTextContent('通过 · doctor: ready')
    const pending = within(bench).getByTestId('kt-bench-pending')
    const full = 'bc93723c5a1f0e8d2b7c46e19a0d3f58c2e7b1a49d6f0c38e5b2a71d94c06e3f'
    const digest = within(pending).getByTestId('kt-digest')
    expect(digest).toHaveTextContent(/^bc93723c5a1f 复制$/)
    expect(digest.querySelector('code')).toHaveAttribute('title', full)
    // the commands once, shortened to bench/console.py; 复制命令 copies the full one
    const cmds = within(pending).getAllByTestId('kt-cli')
    expect(cmds.map((c) => c.querySelector('code')!.textContent)).toEqual(['python3 bench/console.py',
      'python3 bench/console.py approve 20261102T101500-deploy-3fa1 --digest bc93723c5a1f', 'python3 bench/console.py refuse 20261102T101500-deploy-3fa1 --reason <原因>'])
    await userEvent.click(within(cmds[1]).getByRole('button', { name: '复制命令' }))
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(cmds[1].querySelector('code')!.title)
    expect(cmds[1].querySelector('code')!.title).toMatch(/^python3 \/\S+\/bench\/console\.py approve /)
    expect(await within(cmds[1]).findByRole('status')).toHaveTextContent('已复制')
    const record = within(bench).getAllByRole('listitem').map((li) => li.textContent).filter((t) => t?.startsWith('2026'))
    expect(record[0]).toContain('请求 deploy bc93723c5a1f，vstatd-team r1006a')
    expect(record.at(-1)).toContain('电源 13.5 V，KL15 on（李工）')
  })

  test('in servers mode (D17) a waiting request is approved at the console: no 批准 / 拒绝 on the board', async () => {
    const b = vstatdBoard('bench')
    expect(b.run!.bench!.state.pending.length).toBeGreaterThan(0)
    b.run!.bench!.board_decides = false
    serve(b)
    render(<TeamPage pollMs={60_000} />)
    const pending = within(await screen.findByTestId('kt-bench')).getByTestId('kt-bench-pending')
    expect(within(pending).queryByTestId('kt-decide')).toBeNull()
    expect(within(pending).getByTestId('kt-console-only')).toHaveTextContent('在操作台 bench/console.py 上批')
    expect(within(pending).getAllByTestId('kt-cli').length).toBe(3)  // the console commands stay
  })

  test('a request past its timeout is not listed as waiting: no 批准 / 拒绝, no console command', async () => {
    const b = vstatdBoard('bench')
    const st = b.run!.bench!.state
    st.pending = [{ ...st.pending[0], id: '20261103T094046-deploy-2570', requested_by: 'bench tools', expired: true }]
    serve(b)
    render(<TeamPage pollMs={60_000} />)
    const pending = within(await screen.findByTestId('kt-bench')).getByTestId('kt-bench-pending')
    expect(pending).toHaveTextContent('等操作台批准的请求没有')
    expect(within(pending).queryByTestId('kt-decide')).toBeNull()
    expect(within(pending).queryByTestId('kt-cli')).toBeNull()
    expect(within(pending).getByTestId('kt-bench-expired'))
      .toHaveTextContent('已超时、没人能再批的旧请求 1 条，不用处理：20261103T094046-deploy-2570')
  })

  // an ended run's panel shows the bench as it was then; a request made since (a person recording the baseline) is
  // decided under 台架现在, with the bench state as read now
  const ended = (live: Partial<BenchRequest & { expires: number }> = {}) => {
    const b = vstatdBoard('release')
    const bench = b.run!.bench!
    bench.history = clone(bench.state.actions)
    bench.state.pending = [{ id: '20261118T212800-deploy-6bb0', action: 'deploy',
      digest: 'e5b2a71d94c06e3fbc93723c5a1f',
      detail: '', requested_at: '2026-11-18T13:28:00Z', requested_by: 'bench tools', expired: false,
      expires: b.at + 200, ...live } as BenchRequest]
    return b
  }

  test('an ended run: a live request waiting at the console now is listed under 台架现在 with 批准', async () => {
    const user = userEvent.setup()
    const b = ended()
    setApiRoutes({
      [`GET ${API}/board*`]: () => clone(b),
      [`POST ${API}/bench/decide`]: () => ({ ok: true, decision: {} }),
    })
    render(<TeamPage pollMs={60_000} />)
    const bench = await screen.findByTestId('kt-bench')
    expect(within(bench).getByTestId('kt-bench-pending')).toHaveTextContent('等操作台批准的请求没有')  // as it ended
    const live = within(bench).getByTestId('kt-bench-live')
    expect(live).toHaveTextContent('台架现在')
    expect(live).toHaveTextContent('deploy · 20261118T212800-deploy-6bb0 · bench tools')
    expect(within(live).getByTestId('kt-digest')).toHaveTextContent(/^e5b2a71d94c0 复制$/)
    expect(live).toHaveTextContent(/还剩 (199|200) 秒/)
    await user.type(within(live).getByRole('textbox', { name: '构建摘要的前 6 位' }), 'e5b2a7')
    await user.click(within(live).getByRole('button', { name: '批准' }))
    expect(apiCalls.find((c) => c.method === 'POST' && c.path === `${API}/bench/decide`)?.body)
      .toEqual({ id: '20261118T212800-deploy-6bb0', verdict: 'approve', digest: 'e5b2a7', reason: '' })
  })

  test('an ended run: a live request past its timeout is one grey line, with no 批准', async () => {
    serve(ended({ expired: true }))
    render(<TeamPage pollMs={60_000} />)
    const live = within(await screen.findByTestId('kt-bench')).getByTestId('kt-bench-live')
    expect(within(live).queryByTestId('kt-decide')).toBeNull()
    expect(within(live).getByTestId('kt-bench-expired'))
      .toHaveTextContent('已超时、没人能再批的旧请求 1 条，不用处理：20261118T212800-deploy-6bb0')
  })

  test('an ended run in servers mode without board_decides: 台架现在 says to approve at the console', async () => {
    const b = ended()
    b.run!.bench!.board_decides = false
    serve(b)
    render(<TeamPage pollMs={60_000} />)
    const live = within(await screen.findByTestId('kt-bench')).getByTestId('kt-bench-live')
    expect(within(live).queryByTestId('kt-decide')).toBeNull()
    expect(within(live).getByTestId('kt-console-only')).toHaveTextContent('在操作台 bench/console.py 上批')
  })

  test('an ended run: a request made after the page opened shows up on the next poll', async () => {
    const b = ended()
    const later = clone(b)
    b.run!.bench!.state.pending = []
    let n = 0
    setApiRoutes({ [`GET ${API}/board*`]: () => clone(++n > 1 ? later : b) })
    render(<TeamPage pollMs={50} />)
    const live = await screen.findByTestId('kt-bench-live')
    expect(live).toHaveTextContent(/^台架现在.*没有$/)
    await waitFor(() => expect(within(live).getByTestId('kt-decide')).toBeInTheDocument())
  })

  test('a replay of an ended run, and 投影, have no 台架现在', async () => {
    const user = userEvent.setup()
    const b = ended()
    setApiRoutes({
      [`GET ${API}/board*`]: () => clone(b),
      [`GET ${API}/runs/${b.run!.id}/events`]: () => ({ run: b.run!.id, events: b.run!.events }),
    })
    const { unmount } = render(<TeamPage pollMs={60_000} />)
    await screen.findByTestId('kt-bench-live')
    await user.click(screen.getByRole('button', { name: '▶ 回放' }))
    await screen.findByRole('group', { name: '回放' })
    expect(screen.getByTestId('kt-bench')).toBeInTheDocument()
    expect(screen.queryByTestId('kt-bench-live')).toBeNull()
    unmount()
    serve(b)
    render(<TeamPage pollMs={60_000} projection />)
    await screen.findByTestId('kt-bench')
    expect(screen.queryByTestId('kt-bench-live')).toBeNull()
  })

  test('the merge conveyor shows only once there is a merge', async () => {
    const b = vstatdBoard('bench')
    expect(b.run!.merges).toEqual([])
    serve(b)
    const { unmount } = render(<TeamPage pollMs={60_000} />)
    await screen.findByTestId('kt-bench')
    expect(screen.queryByTestId('kt-conveyor')).toBeNull()
    unmount()
    b.run!.merges = [{ role: 'dev-fix', sha: 'a1b2c3d', at: b.at - 60, status: 'merged', files: 2, note: null }]
    serve(b)
    render(<TeamPage pollMs={60_000} />)
    expect(await screen.findByTestId('kt-conveyor')).toHaveTextContent('1 次合入')
  })

  test('a bench held for a person says why and the commands to run', async () => {
    const b = vstatdBoard('bench')
    b.run!.bench!.held = { step: 'doctor', why: '台架没准备好：没有基线目录 ~/workplace/vstatd-team/baseline（baseline-result.json）', commands: ['部署当前版本以后运行 bench/cc1.sh replay --kind baseline --out ~/workplace/vstatd-team/baseline'], at: b.at }
    b.run!.bench!.state.pending = []
    serve(b)
    render(<TeamPage pollMs={60_000} />)
    const held = await screen.findByTestId('kt-bench-held')
    expect(held).toHaveTextContent('没有基线目录')
    expect(within(held).getByText(/replay --kind baseline/).tagName).toBe('CODE')
    expect(within(screen.getByTestId('kt-bench-pending')).getByText('没有')).toBeInTheDocument()
  })

  test('the triage gate shows each question\'s citations', () => {
    const q = vstatdBoard('triage').run!.roles.find((l) => l.key === 'triage')!.questions
    render(<GateDialog label="分诊" decision="approve" questions={q} onConfirm={vi.fn(async () => {})} onCancel={() => {}} />)
    const f008 = screen.getByRole('group', { name: '决定 F-008' })
    expect(within(f008).getByTestId('kt-gate-cites')).toHaveTextContent('引用的规范：[VSTATD-IF p.7 §4.2]')
    expect(within(screen.getByRole('group', { name: '决定 F-021' })).queryByTestId('kt-gate-cites')).toBeNull()
  })

  test('in a replay the triage gate shows its questions and answers nothing', async () => {
    const user = userEvent.setup()
    const q = vstatdBoard('triage').run!.roles.find((l) => l.key === 'triage')!.questions
    const onConfirm = vi.fn(async () => {})
    const onCancel = vi.fn()
    render(<GateDialog label="分诊" decision="approve" questions={q} replay onConfirm={onConfirm} onCancel={onCancel} />)
    const dialog = screen.getByTestId('kt-gate-dialog')
    expect(dialog).toHaveTextContent('分诊关卡（回放）')
    expect(within(dialog).getByTestId('kt-gate-questions')).toBeInTheDocument()
    expect(within(screen.getByRole('group', { name: '决定 F-008' })).getAllByRole('radio').every((r) => (r as HTMLInputElement).disabled)).toBe(true)
    expect(within(dialog).queryByRole('textbox')).toBeNull()
    expect(within(dialog).queryByRole('button', { name: /批准/ })).toBeNull()
    await user.click(within(dialog).getByRole('button', { name: '关闭' }))
    expect(onCancel).toHaveBeenCalled()
    expect(onConfirm).not.toHaveBeenCalled()
  })

  test('sign-off: release.sh\'s verdict, the check that differed, the evidence page as text, then the signature', async () => {
    const user = userEvent.setup()
    serve(vstatdBoard('release'))
    render(<TeamPage pollMs={60_000} />)
    const card = await screen.findByTestId('kt-sign')
    expect(within(card).getByTestId('kt-sign-release')).toHaveTextContent('release.sh PASS · every check passed on 7c3e9a1')
    expect(within(card).getByTestId('kt-sign-release')).toHaveTextContent('logdiff PASS · emulation')
    expect(within(card).getByTestId('kt-sign-differs')).toHaveTextContent('unit（FAIL → PASS）')
    const page = within(card).getByTestId('kt-sign-evidence')
    expect(page.querySelector('pre')).toHaveTextContent('A commit message an agent wrote: <script>alert(1)</script>')
    expect(page.querySelector('script, table')).toBeNull() // shown as text: nothing in it becomes markup
    const sign = within(card).getByRole('button', { name: '签字放行' })
    expect(sign).toBeDisabled()
    await user.type(within(card).getByLabelText('签字人'), '王经理')
    expect(sign).toBeEnabled()
  })

  test('until release.sh passes on the rerun the sign-off button stays off and says why', async () => {
    const b = vstatdBoard('release')
    const r = b.run!
    r.release!.release = { verdict: 'FAIL', summary: '', reasons: ['unit: FAIL - see reasons'] }
    Object.assign(r, { status: 'failed', sign_block: '独立重跑后 release.sh 没通过，不能签字放行：unit: FAIL - see reasons' })
    serve(b)
    const user = userEvent.setup()
    render(<TeamPage pollMs={60_000} />)
    const card = await screen.findByTestId('kt-sign')
    expect(within(card).getByTestId('kt-sign-blocked')).toHaveTextContent('release.sh 没通过')
    await user.type(within(card).getByLabelText('签字人'), '王经理')
    expect(within(card).getByRole('button', { name: '签字放行' })).toBeDisabled()
  })

  test('the start form offers the scenario\'s work item', () => {
    expect(WORK_ITEM).toContain('把信号表的处理从 750 行的 Service::run() 里拆出去')
  })
})
