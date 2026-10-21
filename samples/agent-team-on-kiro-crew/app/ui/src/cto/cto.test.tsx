import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, test, vi } from 'vitest'
import AidlcTeamApp from '../main'
import { GateDialog } from '../board/Header'
import { SignOff } from '../board/SignOff'
import { parseView, searchOf } from '../nav'
import { apiCalls, navigations, setApiRoutes } from '../test/stubs/app-sdk'
import { clone, finishedBoard, multiRunBoard, runningBoard } from '../test/fixtures'
import type { Delivery } from '../types'
import { CtoView } from './CtoView'
import { segAt } from './stream'
import { ctoData, ctoFlow } from './testdata'

const API = '/api/apps/aidlc-team'

function routes(data = ctoData()) {
  setApiRoutes({ [`GET ${API}/cto`]: () => clone(data), [`GET ${API}/cto/flow*`]: () => clone(ctoFlow()), [`GET ${API}/board*`]: () => clone(runningBoard()) })
}

describe('the CTO view and the board, both ways', () => {
  test('the app opens on the CTO view; its three views are tabs of one bar that stays where it is', async () => {
    const user = userEvent.setup()
    routes()
    render(<AidlcTeamApp pollMs={60_000} />)
    expect(await screen.findByTestId('cto-more')).toHaveTextContent('1.3 倍')
    expect(screen.getByTestId('cto-fast')).toHaveTextContent('30 天 → 7 天')
    expect(screen.getByText(/其中 2 项为真实运行（实测）/)).toBeInTheDocument()
    const bar = screen.getByTestId('kt-appbar')
    expect(within(bar).getByRole('tab', { name: 'CTO 视图' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1) // the app's name, once
    await user.click(within(bar).getByRole('tab', { name: '团队看板' }))
    expect(window.location.search).toBe('?view=board')
    expect(await screen.findByTestId('kt-run-status')).toBeInTheDocument()
    expect(screen.getByTestId('kt-appbar')).toBe(bar) // the same bar, not a second one
    expect(within(bar).getByRole('tab', { name: '团队看板' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
    expect(screen.queryByRole('button', { name: /CTO 视图/ })).toBeNull()
    expect(screen.getAllByRole('button', { name: '投影' })).toHaveLength(1) // the app's, not one per view
    await user.click(within(bar).getByRole('tab', { name: '交付详情' }))  // the delivery in hand: the board's run
    expect(window.location.search).toBe('?view=item&run=r1006a&from=board')  // ← 返回团队看板
    await user.click(within(bar).getByRole('tab', { name: 'CTO 视图' }))
    expect(window.location.search).toBe('?hl=r1006a')
    expect(await screen.findByTestId('cto-more')).toBeInTheDocument()
  })

  test('投影 is the app’s: switching views keeps it on; 退出投影 or Esc ends it', async () => {
    const user = userEvent.setup()
    routes()
    render(<AidlcTeamApp pollMs={60_000} />)
    await screen.findByTestId('cto-more')
    const bar = within(screen.getByTestId('kt-appbar'))
    await user.click(bar.getByRole('button', { name: '投影' }))
    expect(screen.getByTestId('kt-app')).toHaveClass('is-projection')
    expect(screen.getByTestId('cto-root')).toHaveClass('is-projection')
    await user.click(bar.getByRole('tab', { name: '团队看板' }))
    expect(await screen.findByTestId('kt-root')).toHaveClass('is-projection')
    expect(screen.getByTestId('kt-app')).toHaveClass('is-projection')
    await user.click(bar.getByRole('tab', { name: 'CTO 视图' }))
    expect(await screen.findByTestId('cto-root')).toHaveClass('is-projection')
    await user.keyboard('{Escape}')
    expect(screen.getByTestId('kt-app')).not.toHaveClass('is-projection')
    await user.click(bar.getByRole('button', { name: '投影' }))
    await user.click(bar.getByRole('button', { name: '退出投影' }))
    expect(screen.getByTestId('cto-root')).not.toHaveClass('is-projection')
  }, 15_000)

  test('every delivery shows its Issue and PR; one with a defect after it shipped says so', async () => {
    routes()
    render(<CtoView onOpen={() => {}} pollMs={60_000} />)
    await screen.findByTestId('cto-more')
    const table = within(screen.getByRole('region', { name: '交付清单' })).getByRole('table')
    const row = within(table).getByText('商品参数对比（冰箱）').closest('tr') as HTMLElement
    expect(row).toHaveTextContent('TY-2790')
    expect(row).toHaveTextContent('TY-2790 商品部PR #2990')
    expect(row).toHaveTextContent('上线后缺陷 1 · 修复见 TY-2801')
    expect(within(table).getByText('双十一家电大促活动页').closest('tr')).toHaveTextContent('PR #5123')
    expect(screen.getByTestId('cto-live-card')).toHaveTextContent('电商 · TY-4130')
  })

  test('a run of this app waiting at its gate is a card that opens the board at that gate', async () => {
    const user = userEvent.setup()
    routes()
    render(<AidlcTeamApp pollMs={60_000} />)
    const card = await screen.findByTestId('cto-live-card')
    expect(card).toHaveTextContent('上线关卡')
    expect(card).toHaveTextContent('独立审查已出结论，待负责人决定')
    await user.click(within(card).getByRole('button', { name: '去审批 ↗' }))
    expect(parseView(window.location.search)).toEqual({ kind: 'board', run: 'r1020gate', gate: 'compliance', from: 'cto' })
    await waitFor(() => expect(apiCalls.some((c) => c.path === `${API}/board?run=r1020gate`)).toBe(true))
  })

  test('a delivered 实测 opens its 交付详情: four numbers, the 价值流, what people decided; each opens the board there', async () => {
    const user = userEvent.setup()
    routes()
    render(<AidlcTeamApp pollMs={60_000} />)
    const flow = await screen.findByRole('region', { name: '需求流动' })
    await user.click(within(flow).getByRole('button', { name: /双十一家电大促活动页/ }))
    expect(parseView(window.location.search)).toEqual({ kind: 'item', run: 'r1013f04d', from: 'cto' })
    expect(await screen.findByTestId('item-cycle')).toHaveTextContent('17 分钟')
    const item = screen.getByTestId('item-root')
    expect(within(item).getByRole('article', { name: '时间花在哪' })).toHaveTextContent('8 分钟agent 在做 · 等人批准 9 分钟（3 次关卡）')
    expect(within(item).getByRole('article', { name: '质量' })).toHaveTextContent('检查 37/37')
    expect(within(item).getByRole('article', { name: '质量' })).toHaveTextContent('退回 1 次：人 1 · 审查 0 · 检查 0')
    const decided = within(item).getByRole('region', { name: '负责人的决定' })
    expect(decided).toHaveTextContent('退回上线价保退差 48.6 万元，超过 30 万需 CFO 审批')
    await user.click(within(decided).getAllByRole('button', { name: '看板 · 回放到这一刻 ↗' })[1])
    expect(parseView(window.location.search)).toEqual({ kind: 'board', run: 'r1013f04d', gate: 'compliance', at: 731, from: 'item' })
  })

  test('each segment and moment of the 价值流 opens the board at that phase or gate, at that moment', async () => {
    const user = userEvent.setup()
    routes()
    window.history.replaceState(null, '', '/apps/aidlc-team?view=item&run=r1013f04d')
    render(<AidlcTeamApp pollMs={60_000} />)
    const stream = await screen.findByTestId('item-stream')
    await user.click(within(stream).getByRole('button', { name: /^构建/ }))
    expect(parseView(window.location.search)).toEqual({ kind: 'board', run: 'r1013f04d', phase: 'construction', at: 260, from: 'item' })
  })

  test('a moment of the 价值流 and its PR open the board too', async () => {
    const user = userEvent.setup()
    routes()
    window.history.replaceState(null, '', '/apps/aidlc-team?view=item&run=r1013f04d')
    render(<AidlcTeamApp pollMs={60_000} />)
    const stream = await screen.findByTestId('item-stream')
    await user.click(within(stream).getByRole('button', { name: /退回上线：看板回放到这一刻/ }))
    expect(parseView(window.location.search)).toEqual({ kind: 'board', run: 'r1013f04d', role: 'compliance', at: 731, from: 'item' })
  })

  test('a simulated delivery says it has no run, and offers the 同类实测', async () => {
    const user = userEvent.setup()
    routes()
    render(<AidlcTeamApp pollMs={60_000} />)
    const table = within(await screen.findByRole('region', { name: '交付清单' })).getByRole('table')
    await user.click(within(table).getByText('商品参数对比（冰箱）'))
    expect(parseView(window.location.search)).toEqual({ kind: 'item', issue: 'TY-2790', from: 'cto' })
    expect(await screen.findByText('模拟交付，没有运行记录：环节明细只有真实运行才有。')).toBeInTheDocument()
    const twin = screen.getByTestId('item-twin')
    expect(twin).toHaveTextContent('双十一家电大促活动页')
    expect(screen.getByRole('article', { name: '质量' })).toHaveTextContent('上线后缺陷 1：TY-2801')
    await user.click(within(twin).getByRole('button', { name: '看它的价值流 ↗' }))
    expect(parseView(window.location.search)).toEqual({ kind: 'item', run: 'r1013f04d' })
  })

  test('the CTO view picks out the delivery it comes back to; its checks and signature open the board', async () => {
    const user = userEvent.setup()
    routes()
    window.history.replaceState(null, '', '/apps/aidlc-team?hl=TY-2790')
    render(<AidlcTeamApp pollMs={60_000} />)
    const table = within(await screen.findByRole('region', { name: '交付清单' })).getByRole('table')
    await waitFor(() => expect(within(table).getByText('商品参数对比（冰箱）').closest('tr')).toHaveClass('is-hl'))
    await user.click(within(table).getByRole('button', { name: '检查 37/37 通过 ↗' }))
    expect(parseView(window.location.search)).toEqual({ kind: 'board', run: 'r1013f04d', focus: 'tests', from: 'cto' })
  })

  test('a column of 需求流动 opens that phase on the board; 每周上线 and 更快 filter the ledger', async () => {
    const user = userEvent.setup()
    routes()
    const opened: unknown[] = []
    render(<CtoView onOpen={(e) => opened.push(e)} pollMs={60_000} />)
    const flow = await screen.findByRole('region', { name: '需求流动' })
    await user.click(within(flow).getByRole('button', { name: /^构建 ↗/ }))
    expect(opened).toEqual([{ run: 'r1013f04d', phase: 'construction', pick: 'latest' }])  // no run of this app is in 构建 now
    await user.click(within(screen.getByRole('article', { name: '更快' })).getByLabelText('中型：看这一规模的交付'))
    expect(screen.getByTestId('cto-ledger-count')).toHaveTextContent('共 3 项')
    await user.click(screen.getByRole('button', { name: '不按规模筛选' }))
    expect(screen.getByTestId('cto-ledger-count')).toHaveTextContent('共 5 项')
    await user.click(within(screen.getByRole('region', { name: '每周上线' })).getAllByLabelText(/起的一周：看这一周的交付/)[3])  // before AI-DLC: 06-01 and 06-02
    expect(screen.getByRole('button', { name: '不按周筛选' })).toBeInTheDocument()
    expect(screen.getByTestId('cto-ledger-count')).toHaveTextContent('共 2 项')
  }, 15_000)

  test('the 签字单 and 交付详情 go both ways', async () => {
    const user = userEvent.setup()
    const run = clone(finishedBoard()).run!
    run.signoff = { by: '研发负责人', note: '', at: run.ended_at ?? 0, tests: '37/37' }
    const onItem = vi.fn()
    render(<SignOff run={run} onCto={() => {}} onItem={onItem} />)
    await user.click(screen.getByRole('button', { name: '交付详情 ↗' }))
    expect(onItem).toHaveBeenCalled()
  })

  test('a 实测 row’s ▶ 回放 ↗ opens its replay, not its 交付详情', async () => {
    const user = userEvent.setup()
    routes()
    render(<AidlcTeamApp pollMs={60_000} />)
    const table = within(await screen.findByRole('region', { name: '交付清单' })).getByRole('table')
    await user.click(within(table).getAllByRole('button', { name: '▶ 回放 ↗' })[0])
    expect(parseView(window.location.search)).toEqual({ kind: 'board', run: 'r1013f04d', replay: 30, from: 'cto' })
  })

  test('a business line filters every number, the kanban and the ledger', async () => {
    const user = userEvent.setup()
    routes()
    render(<CtoView onOpen={() => {}} pollMs={60_000} />)
    await screen.findByTestId('cto-more')
    expect(screen.getByTestId('cto-ledger-count')).toHaveTextContent('共 5 项')
    await user.click(screen.getByRole('button', { name: /^供应链/ }))
    expect(screen.getByTestId('cto-more')).toHaveTextContent('1.0 倍')
    expect(screen.getByTestId('cto-ledger-count')).toHaveTextContent('共 1 项')
    expect(screen.getByTestId('cto-flow-stats')).toHaveTextContent('进行中 1 项·agent 在做 1 项·等人批准 0 项·需求池 0 项')
    await user.click(screen.getByRole('button', { name: /^电商/ }))
    expect(screen.getByTestId('cto-flow-stats')).toHaveTextContent('等人批准 1 项')
  })

  test('the ledger downloads as CSV, as filtered', async () => {
    const user = userEvent.setup()
    routes()
    const made: Blob[] = []
    URL.createObjectURL = vi.fn((b: Blob) => (made.push(b), 'blob:cto')) as unknown as typeof URL.createObjectURL
    URL.revokeObjectURL = vi.fn()
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    render(<CtoView onOpen={() => {}} pollMs={60_000} />)
    await screen.findByTestId('cto-more')
    await user.click(screen.getByRole('button', { name: '只看实测' }))
    await user.click(screen.getByText('下载 ▾'))
    await user.click(screen.getByRole('button', { name: '交付清单（CSV，按当前筛选）' }))
    expect(click).toHaveBeenCalled()
    const text = await new Promise<string>((ok) => { const r = new FileReader(); r.onload = () => ok(String(r.result)); r.readAsText(made[0]) })
    expect(text).toContain('r1013f04d')
    expect(text.split('\r\n')[0]).toContain('Issue,提出方,Issue 创建日,上线日')
    expect(text).toContain('TY-4127,运营部,2026-10-19')
    expect(screen.getByRole('status')).toHaveTextContent('已导出 2 行（全部业务线 · 只看实测）')
  })

  test('a run signed off since the last look is 刚刚, on the kanban and in the ledger', async () => {
    let calls = 0
    setApiRoutes({
      [`GET ${API}/cto`]: () => {
        const d = ctoData()
        if (++calls > 1) d.items.unshift({ ...d.items[0], t: '双十一官方商城大促', real: 'r1020gate', ship: '2026-10-20' })
        return d
      },
    })
    render(<CtoView onOpen={() => {}} pollMs={30} />)
    await screen.findByTestId('cto-more')
    await waitFor(() => expect(screen.getAllByText('刚刚').length).toBeGreaterThanOrEqual(2))
    expect(screen.getByText(/其中 3 项为真实运行/)).toBeInTheDocument()
  })

  test('the URL carries the view and the way into the board; anything else is the CTO view', () => {
    expect(parseView('')).toEqual({ kind: 'cto' })
    expect(parseView('?view=board&run=r1013f04d&replay=30&focus=signoff&gate=compliance')).toEqual({ kind: 'board', run: 'r1013f04d', gate: 'compliance', replay: 30, focus: 'signoff' })
    expect(parseView('?view=board&run=../x&replay=7&gate=Bad Role&new=promo')).toEqual({ kind: 'board', new: 'promo' })
    expect(searchOf({ kind: 'board', run: 'r1020gate', gate: 'compliance' })).toBe('?view=board&run=r1020gate&gate=compliance')
    expect(searchOf({ kind: 'cto' })).toBe('')
  })
})

describe('the board side of it', () => {
  const proposal: Delivery = { name: '双十一家电大促活动页', kind: '新功能', size: '中', line: '电商', why: '官方商城的大促活动页', confirmed: false }

  test('approving the planner’s gate confirms its 交付标签, as proposed or changed', async () => {
    const user = userEvent.setup()
    const onConfirm = vi.fn(async () => {})
    render(<GateDialog label="需求" decision="approve" delivery={proposal} onConfirm={onConfirm} onCancel={() => {}} />)
    const box = screen.getByTestId('kt-gate-delivery')
    expect(box).toHaveTextContent('交付标签（提议：官方商城的大促活动页）')
    await user.selectOptions(within(box).getByLabelText('规模'), '大')
    await user.click(screen.getByRole('button', { name: '确认批准' }))
    expect(onConfirm).toHaveBeenCalledWith('', { name: '双十一家电大促活动页', kind: '新功能', size: '大', line: '电商' })
  })

  test('sending the gate back asks nothing about labels', () => {
    render(<GateDialog label="需求" decision="revise" delivery={proposal} onConfirm={async () => {}} onCancel={() => {}} />)
    expect(screen.queryByTestId('kt-gate-delivery')).toBeNull()
  })

  test('a signed 签字单 says the delivery is in the CTO view, and goes there', async () => {
    const user = userEvent.setup()
    const run = clone(finishedBoard()).run!
    run.signoff = { by: '研发负责人', note: '', at: run.ended_at ?? 0, tests: '37/37' }
    const onCto = vi.fn()
    render(<SignOff run={run} onCto={onCto} />)
    await user.click(screen.getByRole('button', { name: '已计入 CTO 视图 ↗' }))
    expect(onCto).toHaveBeenCalled()
  })

  test('the 签字单 and the top bar carry the run’s Issue and PR: 待合并 until the signature, then merged into main', () => {
    const run = clone(finishedBoard()).run!
    run.issue = { id: 'TY-4127', kind: '需求', reporter: '运营部', created_at: run.started_at }
    run.pr = { number: 5123, head: `team/${run.id}/run`, base: 'main', state: 'open', opened_at: run.ended_at ?? 0, merged_at: null, merged_by: null,
      sha: '', files: 12, added: 340, removed: 8, checks: '37/37', review: '审查说可以合入' }
    const { rerender } = render(<SignOff run={run} onSign={async () => {}} />)
    expect(screen.getByTestId('kt-sign-pr')).toHaveTextContent(`Issue TY-4127（需求 · 运营部提出） → PR #5123：team/${run.id}/run → main · 待合并：签字放行时合入 main`)
    run.signoff = { by: '研发负责人', note: '', at: run.ended_at ?? 0, tests: '37/37' }
    run.pr = { ...run.pr, state: 'merged', sha: 'a1b2c3d' }
    rerender(<SignOff run={clone(run)} />)
    expect(screen.getByTestId('kt-sign-pr')).toHaveTextContent('已合入 main（a1b2c3d）')
    rerender(<SignOff run={{ ...clone(run), imported: { from: 'MacBook' }, pr: { ...run.pr, state: 'signed', sha: '' } }} />)
    expect(screen.getByTestId('kt-sign-pr')).toHaveTextContent('运行从其他电脑导入，代码仓库不在这里，没有在这里合并')
  })
})

describe('moving between the three views', () => {
  const ledgerOf = () => within(screen.getByRole('region', { name: '交付清单' })).getByRole('table')

  test('a move to another view is a history entry: back returns to the CTO view with its filters and the row left from', async () => {
    const user = userEvent.setup()
    routes()
    render(<AidlcTeamApp pollMs={60_000} />)
    await screen.findByTestId('cto-more')
    await user.click(screen.getByRole('button', { name: /^电商/ }))
    await user.click(within(screen.getByRole('region', { name: '交付清单' })).getByRole('button', { name: '新功能' }))
    expect(window.location.search).toBe('?line=0&kind=feat')  // a filter rewrites the entry
    const length = window.history.length
    await user.click(within(ledgerOf()).getByText('商品参数对比（冰箱）'))
    expect(parseView(window.location.search)).toEqual({ kind: 'item', issue: 'TY-2790', from: 'cto' })
    expect(window.history.length).toBe(length + 1)  // the move is a new entry
    expect(navigations).toEqual(['/apps/aidlc-team?view=item&issue=TY-2790&from=cto'])  // made by the host's router (its ← → know about it)
    expect((window.history.state as { ktDepth?: number }).ktDepth).toBe(1)
    window.history.back()
    await waitFor(() => expect(window.location.search).toBe('?line=0&kind=feat&hl=TY-2790'))
    expect(await screen.findByTestId('cto-ledger-count')).toHaveTextContent('共 3 项')
    await waitFor(() => expect(within(ledgerOf()).getByText('商品参数对比（冰箱）').closest('tr')).toHaveClass('is-hl'))
    window.history.forward()
    await waitFor(() => expect(window.location.search).toBe('?view=item&issue=TY-2790&from=cto'))
    expect(await screen.findByTestId('item-root')).toBeInTheDocument()
  })

  test('the breadcrumb back to the CTO view brings back the filters it was left with', async () => {
    const user = userEvent.setup()
    routes()
    render(<AidlcTeamApp pollMs={60_000} />)
    await screen.findByTestId('cto-more')
    await user.click(screen.getByRole('button', { name: /^电商/ }))
    await user.click(within(ledgerOf()).getByText('商品参数对比（冰箱）'))
    await user.click(await screen.findByRole('button', { name: 'CTO 视图' }))
    expect(parseView(window.location.search)).toEqual({ kind: 'cto', line: 0, hl: 'TY-2790' })
    expect(await screen.findByTestId('cto-ledger-count')).toHaveTextContent('共 3 项')
  })

  test('a row not under the filters it comes back to: they are relaxed, and the page says so', async () => {
    routes()
    window.history.replaceState(null, '', '/apps/aidlc-team?line=3&hl=TY-2790')  // 供应链, but 商品参数对比 is 电商
    render(<AidlcTeamApp pollMs={60_000} />)
    expect(await screen.findByText('这一项不在刚才的筛选里，已改为显示全部业务线和类型')).toBeInTheDocument()
    await waitFor(() => expect(within(ledgerOf()).getByText('商品参数对比（冰箱）').closest('tr')).toHaveClass('is-hl'))
  })

  test('a ledger row opens with the keyboard', async () => {
    const user = userEvent.setup()
    routes()
    render(<AidlcTeamApp pollMs={60_000} />)
    await screen.findByTestId('cto-more')
    within(ledgerOf()).getByText('商品参数对比（冰箱）').closest('tr')!.focus()
    await user.keyboard('{Enter}')
    expect(parseView(window.location.search)).toEqual({ kind: 'item', issue: 'TY-2790', from: 'cto' })
  })

  test('the run picked in the board picker is what the URL says; 看每位成员的用量 opens the lanes', async () => {
    const user = userEvent.setup()
    setApiRoutes({ [`GET ${API}/cto`]: () => clone(ctoData()), [`GET ${API}/cto/flow*`]: () => clone(ctoFlow()),
      [`GET ${API}/board*`]: (_b: unknown, path: string) => multiRunBoard(new URL(path, 'http://x').searchParams.get('run')) })
    window.history.replaceState(null, '', '/apps/aidlc-team?view=board&run=r1006a')
    render(<AidlcTeamApp pollMs={60_000} />)
    await user.selectOptions(await screen.findByRole('combobox', { name: '选择运行' }), 'r1005z')
    expect(window.location.search).toBe('?view=board&run=r1005z')
    window.history.replaceState(null, '', '/apps/aidlc-team?view=item&run=r1013f04d')
    window.dispatchEvent(new PopStateEvent('popstate'))
    await user.click(await screen.findByRole('button', { name: '看每位成员的用量 ↗' }))
    expect(parseView(window.location.search)).toEqual({ kind: 'board', run: 'r1013f04d', focus: 'lanes', from: 'item' })
  })

  test('a moment between two segments (or rounded down) picks out the next one', () => {
    const segs = [{ from: 55.3, to: 90.6 }, { from: 91.4, to: 260.8 }] as unknown as Parameters<typeof segAt>[0]
    expect([segAt(segs, 60), segAt(segs, 91), segAt(segs, 300), segAt(segs, undefined)]).toEqual([0, 1, -1, -1])
  })

  test('back on 交付详情 at a moment of the board: that segment of the 价值流 is picked out', async () => {
    routes()
    window.history.replaceState(null, '', '/apps/aidlc-team?view=item&run=r1013f04d&at=300')
    render(<AidlcTeamApp pollMs={60_000} />)
    const stream = await screen.findByTestId('item-stream')
    const picked = stream.querySelector('[data-hl="true"]')
    expect(picked?.textContent).toContain('构建')
    expect(screen.getByTestId('item-at')).toHaveTextContent('团队看板上的 5:00 在「构建」这一段，已框出')
  })

  test('交付详情 opened from the board has its way back there, beside its actions', async () => {
    const user = userEvent.setup()
    routes()
    window.history.replaceState(null, '', '/apps/aidlc-team?view=board&run=r1006a')
    render(<AidlcTeamApp pollMs={60_000} />)
    await screen.findByTestId('kt-graph')
    await user.click(screen.getByRole('tab', { name: '交付详情' }))
    await user.click(await screen.findByRole('button', { name: '← 返回团队看板' }))
    await waitFor(() => expect(window.location.search).toBe('?view=board&run=r1006a'))
  })
})
