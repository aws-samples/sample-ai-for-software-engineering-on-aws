import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, test, vi } from 'vitest'
import { setApiRoutes } from '../test/stubs/app-sdk'
import { clone, vstatdBoard } from '../test/fixtures'
import { TeamPage } from '../main'
import { GateDialog, WORK_ITEM } from './Header'
import type { Board, TestCase } from '../types'

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
