import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, test } from 'vitest'
import { setApiRoutes } from '../test/stubs/app-sdk'
import { auditOf, clone, vstatdBoard } from '../test/fixtures'
import { TeamPage } from '../main'
import { divisionOf, plannedOf } from './division'
import { FLOW } from './flow'
import type { AuditEntry } from '../types'

const API = '/api/apps/vstatd-team'
const e = (at: number, actor: AuditEntry['actor'], step: string, what: string, evidence = '', who = ''): AuditEntry =>
  ({ at, iso: '', seq: null, actor, who, step, what, evidence })

describe('人机分工', () => {
  test('each cell counts what that actor did at that step, with its times and figures from the evidence', () => {
    const d = divisionOf([
      e(100, 'person', 'gate-start', '人批准了开工', 'Q1=B（与建议不同）；Q2=A；Q3=A'),
      e(50, 'agent', 'triage', '分诊完成', 'F-001 F-002 VSTATD-IF-3.2'),
      e(60, 'agent', 'triage', '分诊提议分工', 'F-003'),
      e(70, 'agent', 'triage', '第三条'),
      e(200, 'app', 'before', '测试 4/5', 'build=FAIL static=PASS'),
      e(300, 'app', 'before', '测试 5/5', 'build=PASS static=PASS'),
      e(400, 'person', 'bench', '看板批准部署', '', 'Kiro Crew 看板（you，vstatd-team）'),
      e(410, 'person', 'bench', '操作台批准回放', '', 'you@mac (/dev/ttys003)'),
      e(420, 'bench', 'bench', '部署结果 ok：installed'),
      e(10, 'person', '', '运行开始'),
    ])
    expect(d['gate-start'].person).toMatchObject({ count: 1, first: 100, last: 100, notes: ['逐题回答 3 题，1 题改了建议'] })
    expect(d.triage.agent).toMatchObject({ count: 3, first: 50, last: 70, lines: ['分诊提议分工', '第三条'], notes: ['引用发现或规范 4 次'] })
    expect(d.before.app.notes).toEqual(['1 轮检查有不过'])
    expect(d.bench.person.notes).toEqual(['看板上决定 1 次', '操作台上决定 1 次'])
    expect(d.bench.bench.notes).toEqual(['动作完成 1 次'])
    expect(d.triage.person).toMatchObject({ count: 0, first: null, lines: [], notes: [] })
    expect(Object.keys(d)).toEqual(FLOW.map((s) => s.key)) // the step-less run start is in no column
  })

  test('the planned grid splits a shared step between its actors', () => {
    const tf = FLOW.find((s) => s.key === 'tests-first')!
    expect([plannedOf(tf, 'agent'), plannedOf(tf, 'app'), plannedOf(tf, 'person')]).toEqual(['测试给要测的修复写测试', 'app 在基线提交上跑，每个都必须失败', ''])
  })

  test('on the board: under the flow strip, the current step marked, a cell shows its entries in the audit panel', async () => {
    const b = vstatdBoard('bench')
    setApiRoutes({ [`GET ${API}/board*`]: () => clone(b), [`GET ${API}/runs/${b.run!.id}/audit`]: () => auditOf(b) })
    render(<TeamPage pollMs={60_000} />)
    const grid = await screen.findByTestId('kt-division')
    expect(screen.getByTestId('kt-flow').compareDocumentPosition(grid) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    const cell = await within(grid).findByRole('button', { name: /逐题回答 5 题/ })
    expect(cell.closest('td')).toHaveAttribute('data-step', 'gate-triage')
    expect(grid.querySelector('tr[data-actor="person"] td[data-step="bench"]')).toHaveClass('is-current')
    expect(grid.querySelector('tr[data-actor="agent"] td[data-step="bench"]')).toHaveClass('is-empty')
    const panel = screen.getByTestId('kt-audit')
    expect(panel).not.toHaveAttribute('open') // the run is live
    await userEvent.click(within(grid).getByTitle('在审计记录里看 台架：部署、回放 · 人'))
    expect(panel).toHaveAttribute('open')
    const rows = within(panel).getAllByTestId('kt-audit-row')
    expect(rows.map((r) => [r.dataset.step, r.dataset.actor])).toEqual([['bench', 'person'], ['bench', 'person']])
    expect(within(panel).getByRole('button', { name: '不再只看这一步' })).toBeInTheDocument()
  })
})
