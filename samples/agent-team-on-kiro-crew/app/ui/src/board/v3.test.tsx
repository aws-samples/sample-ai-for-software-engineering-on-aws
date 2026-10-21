import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, test, vi } from 'vitest'
import type { Board } from '../types'
import { apiCalls, setApiRoutes } from '../test/stubs/app-sdk'
import { clone, runningBoard } from '../test/fixtures'
import { TeamPage } from '../main'
import { layoutGraph } from './layout'
import { SCENARIOS, StartForm } from './Header'

const API = '/api/apps/aidlc-team'

/** The fixture run, finished green and not signed yet. */
function doneBoard(signed = false): Board {
  const b = runningBoard()
  b.run!.status = 'done'
  b.runs[0].status = 'done'
  b.run!.tests = { ...b.run!.tests, failed: 0, passed: b.run!.tests.total || 1, total: b.run!.tests.total || 1, cases: b.run!.tests.cases.map((c) => ({ ...c, status: 'pass' as const })) }
  b.run!.sign_block = '' // finished, and what it deploys went out
  if (!signed) b.run!.signoff = null
  return b
}

describe('V3：知识库、适用规范、签字单', () => {
  test('the board shows the standards the requirement touched and what the roles looked up', async () => {
    setApiRoutes({ [`GET ${API}/board*`]: () => clone(runningBoard()) })
    render(<TeamPage pollMs={60_000} />)
    const kb = await screen.findByTestId('kt-kb')
    expect(within(kb).getByText(/《年会抽奖规则》/)).toBeTruthy()
    expect(within(kb).getByText(/数据《员工花名册》/)).toBeTruthy()
    expect(within(kb).getByText('查知识库「年会抽奖规则 RULE-1」')).toBeTruthy()
    expect(within(kb).getByText('读数据 employees.json')).toBeTruthy()
    expect(within(kb).getByText(/9 份文档 · 已同步/)).toBeTruthy()
    expect(screen.queryByTestId('kt-sign')).toBeNull() // still running: nothing to sign yet
  })

  test('a finished run gets a sign-off card; the person signs for the release', async () => {
    const user = userEvent.setup()
    let signed = false
    setApiRoutes({
      [`GET ${API}/board*`]: () => clone(doneBoard(signed)),
      [`POST ${API}/runs/r1006a/signoff`]: () => {
        signed = true
        return { ok: true }
      },
    })
    render(<TeamPage pollMs={60_000} />)
    const card = await screen.findByTestId('kt-sign')
    expect(within(card).getByText('发布前由负责人确认')).toBeTruthy()
    await user.type(within(card).getByLabelText('签字人'), '研发负责人')
    await user.click(within(card).getByRole('button', { name: '签字放行' }))
    expect(apiCalls.filter((c) => c.method === 'POST' && c.path.endsWith('/signoff')).map((c) => c.body)).toEqual([{ by: '研发负责人', note: '' }])
    expect(await within(await screen.findByTestId('kt-sign')).findByText(/签字放行/)).toBeTruthy()
  })
})

describe('谁这次不参与、什么能签字', () => {
  test('a run that delivered nothing gets a sign-off card that says why it cannot be signed', async () => {
    const b = doneBoard()
    b.run!.status = 'failed'
    b.runs[0].status = 'failed'
    b.run!.sign_block = '运行失败了，没有交付，不能签字放行（可以重试失败的角色）'
    setApiRoutes({ [`GET ${API}/board*`]: () => clone(b) })
    render(<TeamPage pollMs={60_000} />)
    const card = await screen.findByTestId('kt-sign')
    expect(within(card).getByTestId('kt-sign-blocked')).toHaveTextContent('运行失败了，没有交付')
    expect(within(card).queryByLabelText('签字人')).toBeNull()
  })

  test('a member sitting the run out has no node or lane of its own, and the board says why', async () => {
    const b = clone(runningBoard())
    const designer = b.run!.roles.find((l) => l.key === 'designer')!
    designer.status = 'skipped'
    designer.summary = '未入职'
    setApiRoutes({ [`GET ${API}/board*`]: () => b })
    const { container } = render(<TeamPage pollMs={60_000} />)
    expect(await screen.findByTestId('kt-lanes-out')).toHaveTextContent('这次不参与：UI 设计（未入职）')
    expect(container.querySelector('.kt-nodes [data-role="designer"]')).toBeNull()
    expect(container.querySelector('.kt-nodes [data-role="backend"]')).not.toBeNull()
  })

  test('the open form asks again who the team would be, so a member just added in Crew shows up without retyping', async () => {
    const preview = vi.fn(() => Promise.reject(new Error('not needed here')))
    render(<StartForm onStart={async () => {}} preview={preview} refreshMs={400} />)
    await waitFor(() => expect(preview.mock.calls.length).toBeGreaterThanOrEqual(3), { timeout: 3000 })
    expect(new Set(preview.mock.calls.map((c) => (c as unknown[])[0]))).toEqual(new Set([SCENARIOS[0].text]))
  })

  test('the decisions people made are on the sign-off card in the order they were made', async () => {
    const b = doneBoard()
    const r = b.run!
    const pm = r.roles.find((l) => l.key === 'pm')!
    const reviewer = r.roles.find((l) => l.key === 'reviewer')!
    pm.gate_label = '需求'
    reviewer.gate_label = '上线'
    r.gate_notes = { pm: '补充一条：每人限购 2 台', reviewer: '价保退差按 28 万预留' }
    const ev = (seq: number, kind: string, role: string, text: string, from: string | null = null) =>
      ({ seq, at: 1791230000 + seq, kind, role, text, from, to: null, data: null }) as (typeof r.events)[number]
    r.events = [...r.events, ev(900, 'approved', 'pm', '人批准了需求'), ev(901, 'bounce', 'backend', '人在上线关卡退回：电视改 9 折', 'person'),
      ev(902, 'approved', 'reviewer', '人批准了上线')]
    setApiRoutes({ [`GET ${API}/board*`]: () => clone(b) })
    render(<TeamPage pollMs={60_000} />)
    const card = await screen.findByTestId('kt-sign')
    const items = within(card).getAllByRole('listitem').map((li) => li.textContent)
    expect(items.slice(0, 3)).toEqual(['批准需求：补充一条：每人限购 2 台', '在上线关卡退回：电视改 9 折', '批准上线：价保退差按 28 万预留'])
  })

  test('an overruled review is one of the decisions people made, on the sign-off card', async () => {
    const b = doneBoard()
    b.run!.overruled = { role: 'reviewer', note: '风险我担，活动后财务复核', review: '要改：F-1' }
    const reviewer = b.run!.roles.find((l) => l.key === 'reviewer')!
    reviewer.gate_label = '上线'
    setApiRoutes({ [`GET ${API}/board*`]: () => clone(b) })
    render(<TeamPage pollMs={60_000} />)
    const card = await screen.findByTestId('kt-sign')
    expect(within(card).getByTestId('kt-sign-overruled')).toHaveTextContent('推翻审查结论，批准上线：风险我担，活动后财务复核')
  })
})

/** The fixture's roles in AI-DLC phases: the product manager does 1.1 and 2.3; the reviewer of an older team file
 * still says phase 'review'. */
function phasedBoard(): Board {
  const b = runningBoard()
  const at: Record<string, [string, string]> = {
    pm: ['inception', '1.1 意图捕获 · 2.3 需求分析'], architect: ['inception', '2.8 接口约定'], designer: ['inception', '2.5 界面细化'],
    tester: ['construction', '3.6 构建与测试'], backend: ['construction', '3.5 代码生成'], frontend: ['construction', '3.5 代码生成'],
    ops: ['operation', '4.1 部署流水线'], reviewer: ['review', '审查关卡'],
  }
  for (const l of b.run!.roles) [l.phase, l.stage] = at[l.key]
  return b
}

describe('V3：阶段、悬停卡片、合规关卡', () => {
  test('the phases read 0 to 4: the orchestrator is initialization, a member spanning two phases says so, no review phase', async () => {
    setApiRoutes({ [`GET ${API}/board*`]: () => clone(phasedBoard()) })
    const { container } = render(<TeamPage pollMs={60_000} />)
    await screen.findByTestId('kt-orch')
    const titles = [...container.querySelectorAll('.kt-phase-title')].map((t) => t.textContent ?? '')
    expect(titles[0]).toMatch(/^0 初始化/)
    expect(titles.some((t) => t.startsWith('1–2 构思 · 启动'))).toBe(true)
    expect(titles.some((t) => t.includes('评审关卡'))).toBe(false)
    expect(titles.some((t) => t.startsWith('3 构建'))).toBe(true)
  })

  test('resting the pointer on a member shows what it did, with 看产出 and its session', async () => {
    const user = userEvent.setup()
    setApiRoutes({ [`GET ${API}/board*`]: () => clone(phasedBoard()) })
    const { container } = render(<TeamPage pollMs={60_000} />)
    await screen.findByTestId('kt-orch')
    await user.hover(container.querySelector('.kt-node[data-role="backend"]')!)
    const card = await screen.findByTestId('kt-ncard', {}, { timeout: 2000 })
    expect(within(card).getByRole('button', { name: '看产出' })).toBeTruthy()
    expect(within(card).getByRole('button', { name: '在 Crew 里打开会话' })).toBeTruthy()
    expect(within(card).getByText(/负责的检查/)).toBeTruthy()
  })
})

test('a team that skips an official phase still reads 0 to 4: the skipped one is a narrow grey band', () => {
  const roles = [
    { key: 'pm', depends_on: [], phase: 'inception', aidlc_agent: 'aidlc-product-agent' },
    { key: 'fe', depends_on: ['pm'], phase: 'construction', aidlc_agent: 'aidlc-developer-agent' },
    { key: 'ops', depends_on: ['fe'], phase: 'operation', aidlc_agent: 'aidlc-pipeline-deploy-agent' },
  ]
  const lay = layoutGraph(roles, [['pm', 'fe'], ['fe', 'ops']])
  expect(lay.phases.map((p) => `${p.n}${p.used ? '' : '·灰'}`)).toEqual(['0', '1·灰', '2', '3', '4'])
  const grey = lay.phases.find((p) => p.key === 'ideation')!
  const pm = lay.phases.find((p) => p.key === 'inception')!
  expect(grey.x2 <= pm.x1 && grey.x2 - grey.x1 < 100).toBe(true)
  expect(lay.nodes.get('pm')!.x - 92).toBeGreaterThan(grey.x2) // the column made room for it
})

test('the roster lists the whole company team: the picked in green, the rest grey and without a node', async () => {
  const b = phasedBoard()
  const roles = b.run!.roles.map((l) => ({ key: l.key, title: l.title, member: l.aidlc_agent.split(',')[0], icon: l.key }))
  b.run!.roster = [...roles, { key: 'backend2', title: '后端开发 #2', member: 'aidlc-developer-agent', icon: 'backend' },
    { key: 'compliance', title: '合规审查', member: 'aidlc-compliance-agent', icon: 'compliance' }]
  setApiRoutes({ [`GET ${API}/board*`]: () => clone(b) })
  const { container } = render(<TeamPage pollMs={60_000} />)
  const roster = await screen.findByTestId('kt-roster')
  expect(within(roster).getByText(`团队 ${roles.length + 2} 人 · 这次 ${roles.length} 位`)).toBeTruthy()
  const bench = [...roster.querySelectorAll('[data-state="bench"] > text')].map((t) => t.textContent)
  expect(bench).toEqual(['后端开发 #2', '合规审查'])
  expect(roster.querySelectorAll('.kt-roster-item').length).toBe(roles.length + 2)
  expect(container.querySelector('.kt-node[data-role="backend2"]')).toBeNull() // not picked: not in the workflow
  expect(container.querySelector('.kt-node[data-role="compliance"]')).toBeNull()
  // the graph is tall enough for everyone on the list
  const lay = layoutGraph(b.run!.roles, b.run!.edges, b.run!.roster)
  const without = layoutGraph(b.run!.roles, b.run!.edges)
  expect(lay.rail.y).toBeGreaterThanOrEqual(without.rail.y)
})

test('a run imported from another Mac says so and offers nothing that needs its code', async () => {
  const b = runningBoard()
  b.run!.status = 'failed'
  b.runs[0].status = 'failed'
  b.run!.imported = { from: '另一台 Mac' }
  setApiRoutes({ [`GET ${API}/board*`]: () => clone(b) })
  render(<TeamPage pollMs={60_000} />)
  expect(await screen.findByText('导入 · 另一台 Mac')).toBeTruthy()
  expect(screen.queryByRole('button', { name: '📁 文件夹' })).toBeNull()
  expect(screen.queryByRole('button', { name: /重试失败的/ })).toBeNull()
  expect(screen.getByRole('button', { name: '▶ 回放' })).toBeTruthy()
})
