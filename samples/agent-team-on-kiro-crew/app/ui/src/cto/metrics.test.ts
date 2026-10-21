import { describe, expect, test } from 'vitest'
import { baseCycles, daysBefore, ledger, ledgerCsv, metrics, ratioOf, weekly } from './metrics'
import { ctoData } from './testdata'

describe('the CTO view numbers', () => {
  test('a day before is a calendar day, whatever the time zone', () => {
    expect(daysBefore('2026-10-20', 6)).toBe('2026-10-14')
    expect(daysBefore('2026-03-02', 2)).toBe('2026-02-28')
  })

  test('更多 · 更快 · 更省 for the company and for one business line', () => {
    const d = ctoData()
    const base = baseCycles(d.items)
    expect(base).toEqual({ S: 2, M: 10, L: 30 })
    const all = metrics(d, -1, base)
    expect([all.before.length, all.agent.length, all.real]).toEqual([4, 5, 2])
    expect(all.ratio).toBe(1.25)
    expect(all.cycle('L')).toBe(7) // a measured run's minutes are not a size's typical cycle
    expect(all.cycle('M')).toBe(2.5)
    // equivalent work 1 + 5 + 30 + 5 + 5 = 46 person-days; people put in 0.25 + 1 + 7 + 1 + 1 = 10.25
    expect(all.eq).toBe(46)
    expect(all.human).toBe(10.25)
    const sub = 60 * 40 * 3 * 7.1
    expect(all.unit).toBeCloseTo((10.25 * 2000 + sub) / 46)
    expect(all.save).toBeCloseTo(46 * 2000 - 10.25 * 2000 - sub)
    const ec = metrics(d, 0, base)
    expect([ec.before.length, ec.agent.length, ec.seats]).toEqual([2, 3, 12])
    expect(ratioOf(d.items, 0)).toBe(1.5)
  })

  test('the weekly releases fall in their weeks; the ledger puts what was just signed first, then measured runs', () => {
    const d = ctoData()
    const w = weekly(d.items, d.meta, -1)
    expect(w).toHaveLength(24)
    expect(w.reduce((n, x) => n + x.total, 0)).toBe(d.items.length)
    expect(w[23]).toMatchObject({ feat: 3, fix: 1 })
    const rows = ledger(d.items, -1, 'all', false, new Set())
    expect(rows[0].real).toBe('r1013f04d')
    expect(rows.every((r) => r.period === 'agent')).toBe(true)
    expect(ledger(d.items, -1, 'all', true, new Set()).map((r) => r.real)).toEqual(['r1013f04d', 'r1020live'])
    expect(ledger(d.items, -1, 'all', true, new Set(['r1020live']))[0].real).toBe('r1020live')
    expect(ledger(d.items, -1, 'fix', false, new Set()).map((r) => r.kind)).toEqual(['fix'])
  })

  test('the ledger as CSV opens in Excel: a BOM, CRLF, quoted where it has to be', () => {
    const d = ctoData()
    const csv = ledgerCsv(ledger(d.items, -1, 'all', true, new Set()), d.meta, baseCycles(d.items))
    expect(csv.charCodeAt(0)).toBe(0xfeff)
    const lines = csv.slice(1).split('\r\n')
    expect(lines[0]).toBe('交付,业务线,类型,规模,Issue,提出方,Issue 创建日,上线日,周期（天）,以前同规模平均周期（天）,签字,PR,上线后缺陷,修复的 Issue,来源,运行编号')
    expect(lines[1]).toBe('双十一家电大促活动页,电商,新功能,中,TY-4127,运营部,2026-10-19,2026-10-19,0.01,10.0,研发负责人,#5123,,,实测,r1013f04d')
    expect(lines[2]).toContain('"带,逗号的交付"')
  })
})
