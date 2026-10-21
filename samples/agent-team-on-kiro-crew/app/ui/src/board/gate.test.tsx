import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import type { RoutePick, RouteRole } from '../types'
import { GateDialog, TeamPick } from './Header'

test('填入预设意见 puts the demo note in, and 确认批准 sends what is in the box', async () => {
  const user = userEvent.setup()
  const onConfirm = vi.fn(async () => {})
  render(<GateDialog label="方案" decision="approve" preset="批准。库存少于 5 件显示仅剩 N 件。" onConfirm={onConfirm} onCancel={() => {}} />)
  await user.click(screen.getByRole('button', { name: '填入预设意见' }))
  expect(screen.getByLabelText('意见')).toHaveValue('批准。库存少于 5 件显示仅剩 N 件。')
  expect(screen.queryByRole('button', { name: '填入预设意见' })).toBeNull()
  await user.click(screen.getByRole('button', { name: '确认批准' }))
  expect(onConfirm).toHaveBeenCalledWith('批准。库存少于 5 件显示仅剩 N 件。')
})

test('a review gate shows the review, and 退回 fills in its own preset (who is sent back, and why)', async () => {
  const user = userEvent.setup()
  const onConfirm = vi.fn(async () => {})
  const back = '按风险提示退回。\n打回：前端开发 #2。开奖记录页加一行数据使用提示。'
  render(<GateDialog label="合规" decision="revise" preset={back} report="可以交付；不阻塞的风险提示 2 条" onConfirm={onConfirm} onCancel={() => {}} />)
  expect(screen.getByText(/可以交付；不阻塞的风险提示 2 条/)).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: '填入预设意见' }))
  await user.click(screen.getByRole('button', { name: '确认退回' }))
  expect(onConfirm).toHaveBeenCalledWith(back.trim())
})

test('over a review that still says 要改, approving is overruling it: it takes a reason', async () => {
  const user = userEvent.setup()
  const onConfirm = vi.fn(async () => {})
  render(<GateDialog label="上线" decision="approve" overrule report="要改：F-1 价保退差超过 30 万" onConfirm={onConfirm} onCancel={() => {}} />)
  expect(screen.getByText('仍然批准上线')).toBeInTheDocument()
  expect(screen.getByText('审查还说要改：')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: '确认推翻并批准' }))
  expect(onConfirm).not.toHaveBeenCalled()
  expect(screen.getByRole('alert')).toHaveTextContent('推翻它放行要写理由')
  await user.type(screen.getByLabelText('意见'), '风险我担，活动后财务复核')
  await user.click(screen.getByRole('button', { name: '确认推翻并批准' }))
  expect(onConfirm).toHaveBeenCalledWith('风险我担，活动后财务复核')
})

test('sending it back over such a review needs no note: the members the review named do one more round', async () => {
  const user = userEvent.setup()
  const onConfirm = vi.fn(async () => {})
  render(<GateDialog label="上线" decision="revise" overrule report="要改：F-1" onConfirm={onConfirm} onCancel={() => {}} />)
  expect(screen.getByText('退回上线，再改一轮')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: '确认退回' }))
  expect(onConfirm).toHaveBeenCalledWith('')
})

test('a gate shows the documents of its stage, and in a 讨论 what each side said and whether it changed its documents', async () => {
  const user = userEvent.setup()
  const onOpen = vi.fn()
  render(<GateDialog label="启动" who="需求" decision="discuss" outputs={[{ key: 'architect', title: '架构师', icon: 'architect', onOpen }, { key: 'pm', title: '需求', icon: 'pm', onOpen }]}
    talk={[{ who: 'person', text: '接口为什么不分页？', at: 1, changed: null }, { who: 'agent', text: '商品只有 20 款，已改成分页。', at: 2, changed: true }]} onConfirm={async () => {}} onCancel={() => {}} />)
  expect(screen.getByText('讨论启动')).toBeInTheDocument()
  expect(screen.getByText(/需求会回答/)).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: /架构师 ↗/ }))
  expect(onOpen).toHaveBeenCalled()
  const talk = screen.getByTestId('kt-gate-talk')
  expect(within(talk).getAllByRole('listitem').map((li) => li.textContent)).toEqual(['你接口为什么不分页？', '需求商品只有 20 款，已改成分页。（改了文档）'])
  expect(screen.queryByRole('button', { name: '填入预设意见' })).toBeNull()
})

test('the proposal at the 需求 gate says whom it leaves out this run', () => {
  render(<GateDialog label="需求" decision="approve" split={[{ key: 'backend1', title: '后端开发 #1', icon: 'backend', assignment: '价格引擎' }]} skips={[{ key: 'motion', title: '动效设计师', why: '这次只改价格，页面不动' }]} onConfirm={async () => {}} onCancel={() => {}} />)
  const out = screen.getByTestId('kt-gate-skips')
  expect(within(out).getByText(/这次不要：这次只改价格，页面不动/)).toBeInTheDocument()
  expect(within(out).getByText(/批准后它们这次不参与/)).toBeInTheDocument()
})

test('the start form says an optional post whose member is not on Crew sits the run out; another is stood in for', () => {
  const role = (key: string, title: string, member: string, extra: Partial<RouteRole> = {}): RouteRole =>
    ({ key, title, phase: 'construction', stage: '3.5 代码生成', aidlc_agent: member, member, icon: key, assignment: '', gate: false, on_crew: false, ...extra })
  const pick = {
    team: { file: 'team-taoyuan-promo.json', name: '桃源科技研发团队 · 双十一大促', scope: 'mvp', keywords: [], priority: 35, fallback: false, official_stages: null, needs_source: false, starter: 'starters/mall', source: null,
      roles: [role('motion', '动效设计师', 'taoyuan-motion-agent', { optional: true }), role('tester', '测试工程师', 'aidlc-quality-agent')], agents: [], stages: [], extra_stages: [], extra_note: '' },
    matched: ['双十一'], why: '', others: [], roster: [], teams: [],
  } as RoutePick
  render(<TeamPick pick={pick} />)
  expect(screen.getByTestId('kt-pick-unhired')).toHaveTextContent('动效设计师还没入职，这次不参与（在 Crew「代理」里加上 taoyuan-motion-agent，再交给团队就会带上它）')
  expect(screen.getByText(/测试工程师还没加入团队/)).toHaveTextContent('没加的话轮到它时会停下等')
})
