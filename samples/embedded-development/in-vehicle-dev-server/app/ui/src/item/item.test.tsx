import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, test, vi } from 'vitest'
import type { RunFlow } from '../types'
import { setApiRoutes } from '../test/stubs/app-sdk'
import { clone, emptyBoard, flowOf, scorecardOf, vstatdBoard } from '../test/fixtures'
import { parseView, searchOf } from '../nav'
import VstatdTeamApp from '../main'
import { ItemView } from './ItemView'

const API = '/api/apps/vstatd-team'
const cards = () => Object.fromEntries(screen.getAllByTestId('it-card').map((c) => [c.querySelector('.cto-eyebrow')!.textContent, c.querySelector('.cto-value')!.textContent]))

afterEach(() => window.history.replaceState(null, '', '/'))

describe('交付详情', () => {
  test('the URL opens it for a run', () => {
    expect(parseView('?view=item&run=r1006a')).toEqual({ kind: 'item', run: 'r1006a' })
    expect(parseView('?view=item&run=../x')).toEqual({ kind: 'board' })
    expect(searchOf({ kind: 'item', run: 'r1006a' })).toBe('?view=item&run=r1006a')
  })

  test('the totals as cards and the stream by role, person and checks; a segment opens the board there', async () => {
    const user = userEvent.setup()
    const f = flowOf()
    setApiRoutes({ [`GET ${API}/runs/${f.run}/flow`]: () => clone(f) })
    const onBoard = vi.fn()
    render(<ItemView run={f.run} onBoard={onBoard} pollMs={60_000} />)
    await waitFor(() => expect(screen.getAllByTestId('it-card')).toHaveLength(7))
    expect(cards()).toEqual({ 到结束: '2 小时 2 分', 'agent 在做': '1 小时 18 分', 等人: '9 分钟 关卡 7 分钟 · 操作台 2 分钟', 跑检查: '21 分钟',
      credits: '18.4', 检查轮数: '3', 打回: '1' })
    const rows = screen.getAllByTestId('it-row')
    expect(rows.map((r) => r.dataset.row)).toEqual(['triage', 'architect', 'tester', 'dev-fix', 'dev-refactor', 'reviewer', 'person', 'checks', 'marks'])
    const kinds = (row: string) => within(rows.find((r) => r.dataset.row === row)!).queryAllByTestId('it-seg').map((s) => s.dataset.kind)
    expect(kinds('dev-fix')).toEqual(['agent', 'agent'])
    expect(kinds('person')).toEqual(['gate', 'gate', 'console', 'console'])
    expect(kinds('checks')).toEqual(['checks', 'checks', 'checks', 'rerun'])
    const gate = within(rows.find((r) => r.dataset.row === 'person')!).getAllByTestId('it-seg')[1]
    expect(gate).toHaveAttribute('title', '等人批准 · 开工 · 43:30–45:00 · 2 分钟 · 批准')
    await user.click(gate)
    expect(onBoard).toHaveBeenLastCalledWith({ run: f.run, at: 2610, gate: 'architect' })
    const bad = within(rows.find((r) => r.dataset.row === 'checks')!).getAllByTestId('it-seg')[0]
    expect(bad.className).toContain('is-bad')
    await user.click(screen.getAllByTestId('it-mark').find((m) => m.dataset.kind === 'bounce')!)
    expect(onBoard).toHaveBeenLastCalledWith({ run: f.run, at: 4901, role: 'dev-fix' })
  })

  test('what has no record is —, a live run has open segments', async () => {
    const f: RunFlow = { ...flowOf(), live: true, status: 'running', signed: false, marks: [],
      segments: [{ kind: 'agent', from: 20, to: 300, role: 'triage', label: '分诊 · 第 1 轮', result: null, open: true }],
      totals: { elapsed_s: 300, agent_s: 280, person_s: null, gate_s: null, console_s: null, check_s: null, credits: null, check_rounds: null, send_backs: 0 } }
    setApiRoutes({ [`GET ${API}/runs/${f.run}/flow`]: () => clone(f) })
    render(<ItemView run={f.run} onBoard={() => {}} pollMs={60_000} />)
    await waitFor(() => expect(screen.getAllByTestId('it-card')).toHaveLength(7))
    expect(cards()).toEqual({ 到现在: '5 分钟', 'agent 在做': '5 分钟', 等人: '—', 跑检查: '—', credits: '—', 检查轮数: '—', 打回: '0' })
    expect(screen.getByTestId('it-seg').className).toContain('is-open')
  })

  test('the board and the scorecard open it; a segment goes back to the board replay at that moment', async () => {
    const user = userEvent.setup()
    const b = vstatdBoard('release')
    const f = flowOf(b)
    setApiRoutes({ [`GET ${API}/board*`]: () => clone(b), [`GET ${API}/runs/${f.run}/flow`]: () => clone(f),
      [`GET ${API}/scorecard`]: () => scorecardOf(b), [`GET ${API}/runs/${f.run}/events`]: () => ({ run: f.run, events: clone(b.run!.events) }) })
    render(<VstatdTeamApp pollMs={60_000} />)
    await user.click(await screen.findByRole('button', { name: '交付详情' }))
    await screen.findByTestId('it-root')
    expect(window.location.search).toBe(`?view=item&run=${f.run}`)
    expect(screen.getAllByRole('tab').every((t) => t.getAttribute('aria-selected') === 'false')).toBe(true)
    await user.click(within(screen.getAllByTestId('it-row').find((r) => r.dataset.row === 'checks')!).getAllByTestId('it-seg')[0])
    await waitFor(() => expect(window.location.search).toBe(`?view=board&run=${f.run}&at=4520`))
    await user.click(screen.getByRole('tab', { name: '评分卡' }))
    await user.click(await screen.findByRole('button', { name: `交付详情：${b.run!.title}` }))
    await screen.findByTestId('it-root')
    expect(window.location.search).toBe(`?view=item&run=${f.run}`)
  })

  test('no board run, no button', async () => {
    setApiRoutes({ [`GET ${API}/board*`]: () => emptyBoard() })
    render(<VstatdTeamApp pollMs={60_000} />)
    await screen.findByTestId('kt-empty')
    expect(screen.queryByRole('button', { name: '交付详情' })).toBeNull()
  })
})
