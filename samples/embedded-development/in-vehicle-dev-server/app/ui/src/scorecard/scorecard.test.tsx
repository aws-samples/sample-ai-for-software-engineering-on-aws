import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, test } from 'vitest'
import type { Scorecard } from '../types'
import { setApiRoutes } from '../test/stubs/app-sdk'
import { clone, emptyBoard } from '../test/fixtures'
import VstatdTeamApp from '../main'
import { ScorecardView } from './ScorecardView'

const API = '/api/apps/vstatd-team'

const EMPTY: Scorecard = {
  runs: [],
  total: { runs: 0, findings: null, overturned: null, build_rounds: null, caught: null, logdiff: null, bench: null, rerun_differs: null },
}

const ONE: Scorecard = {
  runs: [{
    id: 'r1115done', title: 'vstatd 本批', status: 'done', started_at: 1_800_000_000, signed: true,
    findings: { fixed: 17, justified: 2, deferred: 3 },
    overturned: { ids: ['F-008'], by_person: [], by_reviewer: ['F-008'] },
    times: { triage_s: 1800, first_pass_s: 5400, signoff_s: null },
    build_rounds: 1, caught: { build: 1, static: 0, unit: 2 }, logdiff: { differences: 4, unexplained: 2 },
    bench: { approved: 3, refused: 1, reconciled: 0 }, rerun_differs: [],
  }],
  total: { runs: 1, findings: { fixed: 17, justified: 2, deferred: 3 }, overturned: 1, build_rounds: 1,
    caught: { build: 1, static: 0, unit: 2 }, logdiff: { differences: 4, unexplained: 2 },
    bench: { approved: 3, refused: 1, reconciled: 0 }, rerun_differs: 0 },
}

const cards = () => Object.fromEntries(screen.getAllByTestId('sc-card').map((c) => [c.querySelector('.cto-eyebrow')!.textContent, c.querySelector('.cto-value')!.textContent]))

describe('评分卡', () => {
  test('with no runs every figure is empty, none is 0', async () => {
    setApiRoutes({ [`GET ${API}/scorecard`]: () => clone(EMPTY) })
    render(<ScorecardView pollMs={60_000} />)
    await waitFor(() => expect(screen.getAllByTestId('sc-card')).toHaveLength(6))
    expect(Object.values(cards())).toEqual(['—', '—', '—', '—', '—', '—'])
    expect(screen.getByTestId('sc-runs')).toHaveTextContent('还没有运行')
    expect(screen.getByTestId('sc-caught')).toHaveTextContent('还没有运行跑过台架之前的检查')
    expect(screen.queryByText(/permission|权限类别的工具调用：\d/)).toBeNull()
  })

  test('a run: its figures, the sums, and what it never reached stays empty', async () => {
    setApiRoutes({ [`GET ${API}/scorecard`]: () => clone(ONE) })
    render(<ScorecardView pollMs={60_000} />)
    await waitFor(() => expect(screen.getAllByTestId('sc-run')).toHaveLength(1))
    expect(cards()).toMatchObject({ '发现：修复 / 说明 / 延后': '17 / 2 / 3', 被推翻的说明: '1', 构建修复轮数: '1',
      日志差异: '4 未解释 2', '台架动作：批准 / 拒绝 / 核对': '3 / 1 / 0', 独立重跑结果不同的检查: '0' })
    const cells = within(screen.getByTestId('sc-run')).getAllByRole('cell').map((c) => c.textContent)
    expect(cells.slice(1)).toEqual(['17 / 2 / 3', '1（F-008）', '30 分钟', '1 小时 30 分', '—', '1', 'build 1、unit 2',
      '4（未解释 2）', '3 / 1 / 0', '0'])
    expect(within(screen.getByTestId('sc-caught')).getAllByRole('row').map((r) => r.textContent)).toEqual(['检查失败的轮数', 'build1', 'static0', 'unit2'])
  })

  test('评分卡 is a tab next to 团队看板', async () => {
    const user = userEvent.setup()
    setApiRoutes({ [`GET ${API}/board*`]: () => clone(emptyBoard()), [`GET ${API}/scorecard`]: () => clone(EMPTY) })
    render(<VstatdTeamApp pollMs={60_000} />)
    const tabs = screen.getAllByRole('tab').map((t) => t.textContent)
    expect(tabs).toEqual(['团队看板', '评分卡'])
    await user.click(screen.getByRole('tab', { name: '评分卡' }))
    await waitFor(() => expect(screen.getByTestId('sc-root')).toBeInTheDocument())
    expect(window.location.search).toBe('?view=score')
    window.history.replaceState(null, '', '/')
  })
})
