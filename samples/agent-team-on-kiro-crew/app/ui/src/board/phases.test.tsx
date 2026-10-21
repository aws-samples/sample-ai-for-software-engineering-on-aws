/** v2 board: AI-DLC phase bands, the orchestrator, the gates card, and a person's gate answered from the graph. */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, test, vi } from 'vitest'
import { TeamPage } from '../main'
import { apiCalls, setApiRoutes } from '../test/stubs/app-sdk'
import { aidlcBoard } from '../test/fixtures'

const BOARD = 'GET /api/apps/aidlc-team/board*'

afterEach(() => vi.restoreAllMocks())

describe('a phased team', () => {
  test('phases left to right, the orchestrator, the grey operation phase, and the gates card', async () => {
    setApiRoutes({ [BOARD]: () => aidlcBoard() })
    render(<TeamPage pollMs={60_000} />)
    const graph = await screen.findByTestId('kt-graph')
    expect(within(graph).getByTestId('kt-orch')).toBeInTheDocument()
    for (const p of ['构思', '启动', '构建', '评审关卡', '运维']) expect(graph.textContent).toContain(p)
    expect(graph.textContent).toContain('本次未执行')
    expect(graph.textContent).toContain('2.1 逆向工程')
    const gates = screen.getByTestId('kt-gates')
    expect(gates.textContent).toContain('40/82')
    expect(screen.getByText('这次用到了什么')).toBeInTheDocument()
    expect(screen.queryByTestId('kt-saving')).toBeNull()
  })

  test('a gate waits for the person: 批准范围 posts the answer with the note', async () => {
    const user = userEvent.setup()
    setApiRoutes({ [BOARD]: () => aidlcBoard(true), 'POST /api/apps/aidlc-team/runs/*': () => ({ ok: true }) })
    render(<TeamPage pollMs={60_000} />)
    const gate = await screen.findByTestId('kt-gate')
    await user.click(within(gate).getByRole('button', { name: /批准范围/ }))
    const dialog = await screen.findByTestId('kt-gate-dialog') // in the page: the desktop app has no window.prompt
    await user.type(within(dialog).getByLabelText('意见'), '这次先不做 STORE-4')
    await user.click(within(dialog).getByRole('button', { name: '确认批准' }))
    await waitFor(() =>
      expect(apiCalls.find((c) => c.method === 'POST')).toMatchObject({ path: expect.stringMatching(/\/runs\/[^/]+\/gate$/), body: { role: 'scope', decision: 'approve', note: '这次先不做 STORE-4' } }),
    )
  })
})

describe('a gate where the team offers 讨论 and the role put questions to the person', () => {
  const asked = (gate: 'pending' | 'discussing' = 'pending') => {
    const b = aidlcBoard(true)
    const scope = b.run!.roles.find((l) => l.key === 'scope')!
    Object.assign(scope, {
      gate, can_discuss: true,
      questions: [
        { id: '1', q: '助手怎么沟通？', options: [{ key: 'A', text: '站内规则' }, { key: 'B', text: '外部大模型' }], recommend: 'A', why: '不出公司' },
        { id: '2', q: '小桃子当头像？', options: [{ key: 'A', text: '用' }, { key: 'B', text: '不用' }], recommend: 'B', why: '' },
      ],
      talk: [{ who: 'person', text: '第 2 题为什么不用？', at: 1, changed: null }, { who: 'agent', text: 'BR-4 没列头像这个场景。', at: 2, changed: false }],
    })
    b.run!.gate_discuss = true
    return b
  }

  test('批准 · 讨论 · 退回 under it; 讨论 sends what the person asks, the gate stays', async () => {
    const user = userEvent.setup()
    setApiRoutes({ [BOARD]: () => asked(), 'POST /api/apps/aidlc-team/runs/*': () => ({ ok: true }) })
    render(<TeamPage pollMs={60_000} />)
    const gate = await screen.findByTestId('kt-gate')
    expect(within(gate).getAllByRole('button').map((b) => b.textContent)).toEqual(['✓ 批准范围', '讨论', '退回'])
    await user.click(within(gate).getByRole('button', { name: '讨论' }))
    const dialog = await screen.findByTestId('kt-gate-dialog')
    expect(within(dialog).getByText('讨论范围')).toBeInTheDocument()
    const talk = within(dialog).getByTestId('kt-gate-talk')
    expect(talk.textContent).toContain('你第 2 题为什么不用？')
    expect(talk.textContent).toContain('BR-4 没列头像这个场景。')
    expect(within(dialog).queryByTestId('kt-gate-questions')).toBeNull() // the questions are answered when approving
    await user.click(within(dialog).getByRole('button', { name: '发出' }))
    expect(within(dialog).getByRole('alert')).toHaveTextContent('写下你想问的或想商量的')
    await user.type(within(dialog).getByLabelText('讨论'), '改成用小桃子会怎样？')
    await user.click(within(dialog).getByRole('button', { name: '发出' }))
    await waitFor(() => expect(apiCalls.find((c) => c.method === 'POST')).toMatchObject({ body: { role: 'scope', decision: 'discuss', note: '改成用小桃子会怎样？' } }))
  })

  test('批准 answers each question: its recommendation picked first, another choice marked, 其他 needs words', async () => {
    const user = userEvent.setup()
    setApiRoutes({ [BOARD]: () => asked(), 'POST /api/apps/aidlc-team/runs/*': () => ({ ok: true }) })
    render(<TeamPage pollMs={60_000} />)
    await user.click(within(await screen.findByTestId('kt-gate')).getByRole('button', { name: /批准范围/ }))
    const qs = within(await screen.findByTestId('kt-gate-dialog')).getByTestId('kt-gate-questions')
    const q1 = within(qs).getByRole('group', { name: '决定 1' })
    const q2 = within(qs).getByRole('group', { name: '决定 2' })
    expect(within(q1).getByRole('radio', { name: /A\. 站内规则/ })).toBeChecked()
    expect(within(q2).getByRole('radio', { name: /B\. 不用/ })).toBeChecked()
    await user.click(within(q2).getByRole('radio', { name: /A\. 用/ }))
    expect(q2.textContent).toContain('与建议（B）不同')
    await user.click(within(q1).getByRole('radio', { name: '其他' }))
    await user.click(screen.getByRole('button', { name: '确认批准' }))
    expect(screen.getByRole('alert')).toHaveTextContent('决定 1 选了「其他」：写下你的决定')
    await user.type(within(q1).getByLabelText('决定 1 的其他答案'), '先用规则，下期再评估')
    await user.click(screen.getByRole('button', { name: '确认批准' }))
    await waitFor(() => expect(apiCalls.find((c) => c.method === 'POST')).toMatchObject({
      body: { role: 'scope', decision: 'approve', answers: { 1: { choice: 'other', text: '先用规则，下期再评估' }, 2: { choice: 'A', text: '' } } },
    }))
  })

  test('while the role answers, the gate says so and offers nothing to click', async () => {
    setApiRoutes({ [BOARD]: () => asked('discussing') })
    render(<TeamPage pollMs={60_000} />)
    const gate = await screen.findByTestId('kt-gate')
    expect(gate.textContent).toBe('讨论中 · 在回答')
    expect(within(gate).queryByRole('button')).toBeNull()
  })
})

describe('AI-DLC 官方 14 位专家', () => {
  test('all 14 are shown, each in one of four states: at work, called, not its turn yet, not on this team', async () => {
    const { render: r, screen: s, within: w } = await import('@testing-library/react')
    const { ExpertStrip } = await import('./Header')
    const { aidlcBoard } = await import('../test/fixtures')
    const run = aidlcBoard(false).run!
    r(<ExpertStrip run={run} />)
    const strip = s.getByTestId('kt-experts')
    const items = w(strip).getAllByRole('listitem')
    expect(items).toHaveLength(14)
    const states = new Set(items.map((li) => li.getAttribute('data-state')))
    expect(states.has('none')).toBe(true) // e.g. AWS 平台: no task on this team, shown greyed
    for (const li of items) expect(['干活中', '已调用', '待命', '不参与']).toContain(li.querySelector('small')?.textContent)
  })

  test("a company's own copies of the official experts are those experts; only a truly new one is custom", async () => {
    const { render: r, screen: s, within: w } = await import('@testing-library/react')
    const { ExpertStrip } = await import('./Header')
    const { officialOf } = await import('./format')
    const { aidlcBoard } = await import('../test/fixtures')
    expect([officialOf('luming-architect-agent'), officialOf('luming-motion-agent'), officialOf('aidlc-architect-agent')]).toEqual(['aidlc-architect-agent', '', 'aidlc-architect-agent'])
    const run = { ...aidlcBoard(false).run!, crew_members: ['luming-architect-agent', 'luming-operations-agent', 'luming-recruit-agent'] }
    r(<ExpertStrip run={run} />)
    const strip = s.getByTestId('kt-experts')
    const joined = w(strip).getAllByRole('listitem').filter((li) => li.getAttribute('data-state') === 'joined')
    expect(joined.map((li) => li.querySelector('b')?.textContent)).toEqual(['luming-recruit']) // on the page, nothing to do this time
    expect(strip.textContent).toContain('+ 自定义 1 位')
  })
})
