/**
 * The board in English: the page loads in the language this browser keeps (set here before anything loads), the
 * titles of the board, the check wall, the bench panel, the scorecard and the audit trail switch, an event with a
 * code is said in English and an older run's event without one keeps its Chinese text, and 中文 / English remembers
 * the choice.
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, test, vi } from 'vitest'

vi.hoisted(() => localStorage.setItem('vstatd-team:lang', 'en'))

import { apiCalls, setApiRoutes } from '../test/stubs/app-sdk'
import { auditOf, clone, runningBoard, scorecardOf, vstatdBoard } from '../test/fixtures'
import VstatdTeamApp from '../main'
import { errorText } from '../board/useBoard'
import { GateDialog } from '../board/Header'
import { lang, LANG_KEY, locale } from './index'
import type { Board } from '../types'

const API = '/api/apps/vstatd-team'

function serve(b: Board) {
  const trail = auditOf(b)
  setApiRoutes({
    [`GET ${API}/board*`]: () => clone(b),
    [`GET ${API}/runs/${b.run!.id}/audit*`]: () => trail,
    [`GET ${API}/scorecard`]: () => scorecardOf(vstatdBoard('release')),
  })
}

describe('the board in English', () => {
  test('the page loads in English when this browser chose it, dates and numbers in en-US', () => {
    expect(lang()).toBe('en')
    expect(locale()).toBe('en-US')
    expect(document.documentElement.lang).toBe('en')
  })

  test('the board, the check wall, the bench panel and the audit trail have English titles', async () => {
    const b = vstatdBoard('release')
    b.run!.status = 'done'
    b.run!.ended_at = b.at
    serve(b)
    render(<VstatdTeamApp pollMs={60_000} />)
    const bar = await screen.findByTestId('kt-appbar')
    expect(within(bar).getByRole('tab', { name: 'Team board' })).toHaveAttribute('aria-selected', 'true')
    expect(within(bar).getByRole('tab', { name: 'Scorecard' })).toBeInTheDocument()
    const wall = await screen.findByTestId('kt-wall')
    expect(within(wall).getByRole('heading', { name: 'Check wall' })).toBeInTheDocument()
    expect(screen.getByTestId('kt-bench')).toHaveAccessibleName('Bench')
    const audit = await screen.findByTestId('kt-audit')
    expect(within(audit).getByRole('heading', { name: 'Audit trail' })).toBeInTheDocument()
    await waitFor(() => expect(apiCalls.some((c) => c.path === `${API}/runs/${b.run!.id}/audit?lang=en`)).toBe(true))
    // the roles by their English names, from the team file's title_en
    const triage = screen.getAllByTestId('kt-lane').find((l) => l.dataset.role === 'triage')!
    expect(triage).toHaveTextContent('Triage')
    expect(triage).not.toHaveTextContent('分诊')
    // an event with a code is said in English; the agents' own words stay as they wrote them
    const feed = screen.getByTestId('kt-feed')
    expect(feed).toHaveTextContent(`Run started: ${b.run!.title}`)
    expect(feed).toHaveTextContent('Independent rerun: release.sh PASS')
    expect(feed).not.toHaveTextContent('运行开始')
  })

  test('the scorecard has English titles', async () => {
    serve(vstatdBoard('release'))
    render(<VstatdTeamApp pollMs={60_000} />)
    await userEvent.click(await screen.findByRole('tab', { name: 'Scorecard' }))
    expect(await screen.findByRole('heading', { name: 'Scorecard' })).toBeInTheDocument()
    expect(screen.getAllByText('Overturned explanations').length).toBeGreaterThan(0)
  })

  test('an older run whose events have only text shows that text as it is', async () => {
    const b = runningBoard()
    expect(b.run!.events.every((e) => e.code === null)).toBe(true)
    serve(b)
    render(<VstatdTeamApp pollMs={60_000} />)
    const feed = await screen.findByTestId('kt-feed')
    expect(feed).toHaveTextContent('运行开始：活动报名小站')
    expect(within(await screen.findByTestId('kt-appbar')).getByRole('tab', { name: 'Team board' })).toBeInTheDocument()
  })

  test('an error the dictionary knows is said by its code; others keep the app\'s words', () => {
    const said = errorText(new Error('API 400: {"error": "退回要写明打回给谁", "code": "no_target"}'))
    expect(said).toContain('Send back: Developer · fix')
    expect(said).not.toContain('退回')
    expect(errorText(new Error('API 409: {"error": "已经签过了", "code": "signed"}'))).toContain('It has been signed off already')
    // what the app passes on stays as it said it, inside the English sentence
    expect(errorText(new Error('API 409: {"error": "没批成：digest mismatch", "code": "bench_refused"}'))).toContain('Not approved (没批成：digest mismatch)')
    expect(errorText(new Error('API 409: {"error": "x", "code": "no_such_code"}'))).toContain('x')
  })

  test('the English audit trail downloads as audit-<run>.en.*, not as the signed audit.md', async () => {
    const b = vstatdBoard('release')
    b.run!.status = 'done'
    b.run!.ended_at = b.at
    serve(b)
    const names: string[] = []
    Object.assign(URL, { createObjectURL: () => 'blob:x', revokeObjectURL: () => {} })
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) { names.push(this.download) })
    render(<VstatdTeamApp pollMs={60_000} />)
    const audit = await screen.findByTestId('kt-audit')
    await userEvent.click(await within(audit).findByRole('button', { name: 'JSON' }))
    await waitFor(() => expect(names).toEqual([`audit-${b.run!.id}.en.json`]))
  })

  test('the delivery labels at a gate are English, the values sent stay the stored ones', async () => {
    const onConfirm = vi.fn(async () => {})
    render(<GateDialog label="Scope" decision="approve" delivery={{ name: 'x', kind: '修复', size: '中', line: '内部系统', why: '', confirmed: false }}
      onConfirm={onConfirm} onCancel={() => {}} />)
    const kind = screen.getByRole('combobox', { name: /kind|type/i }) as HTMLSelectElement
    expect([...kind.options].map((o) => [o.value, o.textContent])).toEqual([['新应用', 'New app'], ['新功能', 'New feature'], ['修复', 'Fix']])
    expect(kind.value).toBe('修复')
  })

  test('中文 / English: the choice is kept in this browser (the page reloads in it)', async () => {
    serve(vstatdBoard('bench'))
    render(<VstatdTeamApp pollMs={60_000} />)
    const sw = await screen.findByTestId('kt-lang')
    expect(within(sw).getByRole('button', { name: 'English' })).toHaveAttribute('aria-pressed', 'true')
    await userEvent.click(within(sw).getByRole('button', { name: '中文' }))
    expect(localStorage.getItem(LANG_KEY)).toBe('zh')
  })
})
