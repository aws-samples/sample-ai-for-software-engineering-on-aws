import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, test } from 'vitest'
import { setApiRoutes } from '../test/stubs/app-sdk'
import { backlogOf, clone, emptyBoard, vstatdBoard } from '../test/fixtures'
import { TeamPage } from '../main'
import { SCENARIOS } from './Header'
import type { Board } from '../types'

const API = '/api/apps/vstatd-team'
const serve = (b: Board) => setApiRoutes({ [`GET ${API}/board*`]: () => clone(b) })
const cells = (row: HTMLElement) => [...row.querySelectorAll('td')].map((td) => td.textContent)

describe('需求清单', () => {
  test('the home page: the work item, the backlog filtered by label with counts, and the refactor note', async () => {
    const user = userEvent.setup()
    setApiRoutes({ [`GET ${API}/board*`]: () => emptyBoard(), [`GET ${API}/backlog`]: () => backlogOf() })
    render(<TeamPage pollMs={60_000} />)
    const home = await screen.findByTestId('kt-reqs-home')
    expect(within(screen.getByTestId('kt-empty')).getByTestId('kt-reqs-home')).toBe(home)
    expect(await within(home).findByTestId('kt-work-item')).toHaveTextContent(`工作项：${SCENARIOS[0].text}`)
    expect(within(home).getAllByTestId('kt-backlog-row')).toHaveLength(30)
    const filter = within(home).getByRole('group', { name: '按标注筛选' })
    expect(within(filter).getAllByRole('button').map((b) => b.textContent)).toEqual(['全部 30', 'fix 22', 'later 8'])
    expect(within(filter).getByRole('button', { name: '全部 30' })).toHaveAttribute('aria-pressed', 'true')
    await user.click(within(filter).getByRole('button', { name: 'later 8' }))
    const later = within(home).getAllByTestId('kt-backlog-row')
    expect(later.map((r) => r.dataset.id)).toEqual(['F-009', 'F-019', 'F-020', 'F-022', 'F-024', 'F-026', 'F-029', 'F-030'])
    expect(cells(later[0])).toEqual(['F-009', 'cppcheck', 'variableScope', 'src/supervisor.cpp › Supervisor::check', "The scope of the variable 'now' can be reduced.", 'later'])
    await user.click(within(filter).getByRole('button', { name: 'fix 22' }))
    expect(within(home).getAllByTestId('kt-backlog-row').every((r) => r.textContent?.endsWith('fix'))).toBe(true)
    expect(within(home).getByTestId('kt-reqs-note')).toHaveTextContent('按 TR §4.4 把本批的重构（拆分 Service::run()）加成下一个空号 F-031')
  })

  test('on the board before the triage exists: the backlog', async () => {
    const b = vstatdBoard('triage')
    b.run!.backlog!.triage = null
    serve(b)
    render(<TeamPage pollMs={60_000} />)
    const panel = await screen.findByTestId('kt-reqs')
    expect(screen.getByTestId('kt-kb').compareDocumentPosition(panel) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(within(panel).getByTestId('kt-reqs-state')).toHaveTextContent('还没有分诊：待办 30 条，22 条标了 fix')
    expect(within(panel).getAllByTestId('kt-backlog-row')).toHaveLength(30)
    expect(within(panel).queryByTestId('kt-triage-table')).toBeNull()
  })

  test('the proposed triage: one row per finding, what the app has no record of as —', async () => {
    serve(vstatdBoard('triage'))
    render(<TeamPage pollMs={60_000} />)
    const panel = await screen.findByTestId('kt-reqs')
    expect(within(panel).getByTestId('kt-reqs-state')).toHaveTextContent('分诊的建议，等分诊关卡 · 23 条')
    const rows = Object.fromEntries(within(panel).getAllByTestId('kt-triage-row').map((r) => [r.dataset.id, cells(r)]))
    expect(Object.keys(rows)).toHaveLength(23)
    expect(rows['F-008']).toEqual(['F-008 src/supervisor.cpp › Supervisor::check', '说明', '[VSTATD-IF p.7 §4.2]', '—', '—', '—', '—', '—'])
    expect(rows['F-018']).toEqual(['F-018 src/client_session.cpp › parse_interval', '修复', '[VSTATD-IF p.8 §5.2] IPC-REQUESTS', 'unit-test', '涉及', '—', '—', '—'])
    expect(rows['F-031'][0]).toBe('F-031 TR §4.4 新加')
  })

  test('the approved triage: the person\'s answers, the latest static status and the commits that cite each finding', async () => {
    serve(vstatdBoard('bench'))
    render(<TeamPage pollMs={60_000} />)
    const panel = await screen.findByTestId('kt-reqs')
    expect(within(panel).getByTestId('kt-reqs-state')).toHaveTextContent('分诊已批准（李工，2026-11-02T09:12:00Z） · 23 条')
    const rows = Object.fromEntries(within(panel).getAllByTestId('kt-triage-row').map((r) => [r.dataset.id, cells(r)]))
    expect(rows['F-008'].slice(5)).toEqual(['A 同意说明（评审还会复核引用）', '还在报', '没有提交引用'])
    expect(rows['F-021'].slice(1, 2)).toEqual(['延后'])
    expect(rows['F-003'].slice(5, 7)).toEqual(['—', '已消失'])
    expect(rows['F-003'][7]).toMatch(/^[0-9a-f]{11}$/)
  })
})
