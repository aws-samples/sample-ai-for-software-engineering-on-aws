import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, test } from 'vitest'
import { apiCalls, setApiRoutes } from '../test/stubs/app-sdk'
import { auditOf, benchAuditOf, clone, emptyBoard, readinessOf, vstatdBoard } from '../test/fixtures'
import VstatdTeamApp, { TeamPage } from '../main'

const API = '/api/apps/vstatd-team'

describe('审计记录', () => {
  test('the run panel: open once the run has ended, every row with who, step and evidence, filtered by actor', async () => {
    const b = vstatdBoard('release')
    b.run!.status = 'done'
    b.run!.ended_at = b.at
    setApiRoutes({ [`GET ${API}/board*`]: () => clone(b), [`GET ${API}/runs/${b.run!.id}/audit`]: () => auditOf(b) })
    render(<TeamPage pollMs={60_000} />)
    const panel = await screen.findByTestId('kt-audit')
    expect(panel).toHaveAttribute('open')
    const rows = await within(panel).findAllByTestId('kt-audit-row')
    expect(rows).toHaveLength(auditOf(b).entries.length)
    const board = rows.find((r) => r.textContent?.includes('看板批准部署'))!
    expect(board.dataset.actor).toBe('person')
    expect(board).toHaveTextContent('Kiro Crew 看板（you，vstatd-team）')
    expect(board).toHaveTextContent('7 台架：部署、回放')
    expect(board).toHaveTextContent('摘要 bc93723c0cb0')
    await userEvent.click(within(panel).getByRole('button', { name: 'AI' }))
    expect(within(panel).getAllByTestId('kt-audit-row').every((r) => r.dataset.actor === 'agent')).toBe(true)
    await userEvent.click(within(panel).getByRole('button', { name: '台架' }))
    expect(within(panel).getAllByTestId('kt-audit-row').map((r) => r.dataset.actor)).toEqual(['bench'])
    await userEvent.click(within(panel).getByRole('button', { name: '全部' }))
    expect(within(panel).getAllByTestId('kt-audit-row')).toHaveLength(rows.length)
    expect(within(panel).getByRole('button', { name: 'Markdown' })).toBeEnabled()
  })

  test('the home page lists the bench actions of no run, and reads them again after a decision on the board', async () => {
    setApiRoutes({ [`GET ${API}/board*`]: () => emptyBoard(), [`GET ${API}/readiness`]: () => readinessOf(), [`GET ${API}/audit/bench`]: () => benchAuditOf(),
      [`POST ${API}/bench/decide`]: () => ({ ok: true, decision: { verdict: 'approved' } }) })
    render(<TeamPage pollMs={60_000} />)
    const list = await screen.findByTestId('kt-audit-bench')
    expect(list).toHaveTextContent('台架动作记录（不属于任何运行）')
    const rows = await within(list).findAllByTestId('kt-audit-row')
    expect(rows[0]).toHaveTextContent('回放结果 ok') // newest first
    expect(rows[1]).toHaveTextContent('看板批准回放')
    const reads = () => apiCalls.filter((c) => c.path === `${API}/audit/bench`).length
    const before = reads()
    const req = await screen.findByTestId('kt-ready-request')
    await userEvent.type(within(req).getByLabelText('构建摘要的前 6 位'), 'bc9372')
    await userEvent.click(within(req).getByRole('button', { name: '批准' }))
    await waitFor(() => expect(reads()).toBeGreaterThan(before))
  })

  test('the event feed marks who acted, as the audit trail has it; the app bar counts what waits for the person', async () => {
    const b = vstatdBoard('bench')
    const trail = auditOf(b)
    const ev = b.run!.events.at(-1)!
    trail.entries[0] = { ...trail.entries[0], seq: ev.seq, actor: 'bench' }
    setApiRoutes({ [`GET ${API}/board*`]: () => clone(b), [`GET ${API}/runs/${b.run!.id}/audit`]: () => trail })
    render(<VstatdTeamApp pollMs={60_000} />)
    const feed = await screen.findByTestId('kt-feed')
    const row = await waitFor(() => {
      const li = feed.querySelector(`[data-seq="${ev.seq}"]`)!
      expect(li.querySelector('[data-actor="bench"]')).toHaveTextContent('台架')
      return li
    })
    expect(row).toBeTruthy()
    expect(feed.querySelectorAll('.kt-actor')).toHaveLength(1) // an event the trail does not list has none
    const waiting = b.run!.bench!.state.pending.filter((r) => !r.expired).length + b.run!.roles.filter((l) => l.gate === 'pending').length
    expect(waiting).toBeGreaterThan(0)
    expect(await screen.findByTestId('kt-needs')).toHaveTextContent(`下一步需要你 ${waiting}`)
    const flow = screen.getByTestId('kt-flow')
    expect(flow.compareDocumentPosition(screen.getByTestId('kt-experts')) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy() // 现在 near the top
  })
})

