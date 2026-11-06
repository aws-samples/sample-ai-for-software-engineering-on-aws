/**
 * 演示模式 / Presentation mode on, in English (set in this browser before anything loads): every request asks the
 * backend for the people as their role (?present=en), and what the backend reads back from an older run's text is
 * said in English: a round's label, a gate question and its options, the app's words around a name.
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, test, vi } from 'vitest'

vi.hoisted(() => {
  localStorage.setItem('vstatd-team:lang', 'en')
  localStorage.setItem('vstatd-team:present', 'on')
})

import { apiCalls, setApiRoutes } from '../test/stubs/app-sdk'
import { clone, vstatdBoard } from '../test/fixtures'
import VstatdTeamApp from '../main'
import { PRESENT_KEY, presentation } from './index'
import { doingText, optionText, person, questionText } from './events'

const API = '/api/apps/vstatd-team'

describe('presentation mode', () => {
  test('it is on from this browser, and every request asks for the people as their role', async () => {
    expect(presentation()).toBe(true)
    const b = vstatdBoard('bench')
    setApiRoutes({ [`GET ${API}/board*`]: () => clone(b) })
    render(<VstatdTeamApp pollMs={60_000} />)
    const sw = await screen.findByTestId('kt-present')
    expect(sw).toHaveAttribute('aria-pressed', 'true')
    expect(sw).toHaveTextContent('Presentation mode')
    await waitFor(() => expect(apiCalls.some((c) => c.path.startsWith(`${API}/board`))).toBe(true))
    expect(apiCalls.filter((c) => c.path.startsWith(API)).every((c) => c.path.includes('present=en'))).toBe(true)
    await userEvent.click(sw)
    expect(localStorage.getItem(PRESENT_KEY)).toBeNull()
  })

  test("the app's own words around a name, and what it read back from an older run's text, are English", () => {
    expect(person('负责人')).toBe('Release owner')
    expect(person('Kiro Crew 看板（Release owner，vstatd-team）')).toBe('Kiro Crew board (Release owner, vstatd-team)')
    expect(person('Release owner（在 Kiro 会话里让 Kiro 代点）')).toBe('Release owner (asked Kiro to click it in a Kiro session)')
    expect(doingText({ doing: '修 build、unit', doing_msg: { code: 'label.fix', params: { items: ['build', 'unit'] } } })).toBe('fix build, unit')
    expect(questionText({ q: 'F-007 分诊建议…', q_msg: { code: 'triage.q.justify', params: { id: 'F-007', label: 'fix', where: 'src/a.cpp' } } }))
      .toBe('F-007: triage proposes to explain it as a false positive or harmless, not fix it (the backlog says fix): src/a.cpp')
    expect(optionText({ text: '同意延后', msg: { code: 'triage.opt.defer', params: null } })).toBe('Agree to defer it')
  })

  test('the board in English: a lane sent back says what for in English', async () => {
    const b = vstatdBoard('bench')
    const lane = b.run!.roles.find((l) => l.key === 'dev-fix')!
    Object.assign(lane, { doing: '修 F-032', doing_msg: { code: 'label.fix', params: { items: ['F-032'] } } })
    setApiRoutes({ [`GET ${API}/board*`]: () => clone(b) })
    render(<VstatdTeamApp pollMs={60_000} />)
    const card = (await screen.findAllByTestId('kt-lane')).find((l) => l.dataset.role === 'dev-fix')!
    expect(within(card).getByText('fix F-032')).toBeInTheDocument()
  })
})
