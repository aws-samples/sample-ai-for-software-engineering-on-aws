/**
 * Every number of the CTO view, from the deliveries alone (types.ts): one set of formulas, so the cards, the chart, the
 * kanban and the ledger always agree, for the whole company or one business line. The method notes are at the foot of the CTO view (口径).
 */
import type { CtoData, CtoItem, CtoMeta, Kind, Size } from './types'

export const KIND: Record<Kind, string> = { app: '新应用', feat: '新功能', fix: '修复' }
export const KINDS: Kind[] = ['app', 'feat', 'fix']
export const SIZE: Record<Size, string> = { S: '小', M: '中', L: '大' }
export const KIND_VAR: Record<Kind, string> = { app: 'var(--s1)', feat: 'var(--s2)', fix: 'var(--s3)' }

export const fmt = (n: number) => Math.round(n).toLocaleString('zh-CN')
/** An amount in yuan: ¥20.6 万 · ¥8,000 · '' (none). */
export const money = (n: number | null | undefined) => (n == null ? '' : n >= 1e4 ? `¥${(n / 1e4).toFixed(1)} 万` : `¥${fmt(n)}`)
export const wan = (n: number) => (n >= 1e8 ? `${(n / 1e8).toFixed(2)} 亿` : `${fmt(n / 1e4)} 万`)
export const day1 = (d: number) => (d >= 10 ? Math.round(d) : Math.round(d * 10) / 10)
export const mean = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0)
export const md = (iso: string) => iso.slice(5)
export const waited = (h: number) => (h < 1 ? `${Math.max(1, Math.round(h * 60))} 分钟` : `${h.toFixed(1)} 小时`)

/** A calendar day *n* days before *iso* (local, no time zone drift). */
export function daysBefore(iso: string, n: number): string {
  const [y, m, d] = iso.split('-').map(Number)
  const t = new Date(y, m - 1, d - n)
  return `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, '0')}-${String(t.getDate()).padStart(2, '0')}`
}

/** 「以前」: the average cycle of the deliveries of each size in the 12 weeks before AI-DLC (the whole company). */
export function baseCycles(items: CtoItem[]): Record<Size, number> {
  const out = {} as Record<Size, number>
  for (const s of ['S', 'M', 'L'] as Size[]) out[s] = mean(items.filter((i) => i.period === 'base' && i.size === s).map((i) => i.cyc))
  return out
}

export const inLine = (line: number) => (i: { line: number }) => line < 0 || i.line === line

export type Metrics = ReturnType<typeof metrics>

export function metrics(data: CtoData, line: number, base: Record<Size, number>) {
  const M = data.meta
  const xs = data.items.filter(inLine(line))
  const before = xs.filter((i) => i.period === 'base')
  const agent = xs.filter((i) => i.period === 'agent')
  const count = (arr: CtoItem[], k: Kind) => arr.filter((i) => i.kind === k).length
  const cycle = (s: Size) => mean(agent.filter((i) => i.size === s && !i.real).map((i) => i.cyc))
  const eq = agent.reduce((a, i) => a + M.eq[i.size], 0)
  const human = agent.reduce((a, i) => a + M.human[i.size], 0)
  const seats = M.peoplePerLine * (line < 0 ? M.lines.length : 1)
  const sub = seats * M.seatUsdMonth * M.months * M.fx
  const cost = human * M.dayRate + sub
  const unit = eq ? cost / eq : 0
  const built = agent.filter((i) => i.kind !== 'fix')
  const adv = mean(built.map((i) => Math.max(0, base[i.size] - i.cyc)))
  return {
    before, agent, seats, eq, human, sub, unit, built, adv, count, cycle, steady: steady(before, agent),
    ratio: before.length ? agent.length / before.length : 0,
    save: eq * M.dayRate - cost,
    real: agent.filter((i) => i.real).length,
  }
}

/** 更稳: defects raised after release per 100 new apps and features, before AI-DLC and now (a measured run has had no
 * time after release yet: it is not counted), and what the measured runs sent back before release, with the risks
 * people noted when they sent something back (the largest first). */
export function steady(before: CtoItem[], agent: CtoItem[]) {
  const watched = (arr: CtoItem[]) => arr.filter((i) => i.kind !== 'fix' && !i.real)
  const defects = (arr: CtoItem[]) => arr.reduce((a, i) => a + (i.defects?.length ?? 0), 0)
  const per100 = (arr: CtoItem[]) => (arr.length ? (defects(arr) / arr.length) * 100 : 0)
  const wb = watched(before), wa = watched(agent)
  const reals = agent.filter((i) => i.real)
  const caught = { checks: 0, review: 0, person: 0 }
  for (const i of reals) {
    caught.checks += i.caught?.checks ?? 0
    caught.review += i.caught?.review ?? 0
    caught.person += i.caught?.person ?? 0
  }
  const risks = reals.flatMap((i) => (i.risks ?? []).map((r) => ({ ...r, item: i }))).sort((a, b) => (b.amount ?? 0) - (a.amount ?? 0))
  return {
    before: per100(wb), now: per100(wa), defectsBefore: defects(wb), defectsNow: defects(wa), watchedBefore: wb.length, watchedNow: wa.length,
    caught, caughtAll: caught.checks + caught.review + caught.person, reals: reals.length, risks,
    kept: risks.reduce((a, r) => a + (r.amount ?? 0), 0),
  }
}

/** 交付量倍数 of one business line (or all: -1), for the line buttons. */
export function ratioOf(items: CtoItem[], line: number): number {
  const xs = items.filter(inLine(line))
  const b = xs.filter((i) => i.period === 'base').length
  return b ? xs.filter((i) => i.period === 'agent').length / b : 0
}

export type Week = { start: string; app: number; feat: number; fix: number; total: number }

export function weekly(items: CtoItem[], meta: CtoMeta, line: number): Week[] {
  const t0 = new Date(`${meta.weeks[0]}T00:00:00`).getTime()
  const out: Week[] = meta.weeks.map((w) => ({ start: w, app: 0, feat: 0, fix: 0, total: 0 }))
  for (const i of items.filter(inLine(line))) {
    const k = Math.floor((new Date(`${i.ship}T00:00:00`).getTime() - t0) / 864e5 / 7)
    if (k >= 0 && k < out.length) {
      out[k][i.kind] += 1
      out[k].total += 1
    }
  }
  return out
}

/** The ledger: the 12 weeks with AI-DLC, measured runs first (the newest a person signed, then the others), then by day. */
/** 交付清单: 近 12 周 (a week picked on 每周上线: that week, before AI-DLC too), by line, type, size, 实测; 实测 first. */
export function ledger(items: CtoItem[], line: number, kind: Kind | 'all', realOnly: boolean, fresh: ReadonlySet<string>, extra: { size?: Size | null; week?: string | null; defects?: boolean } = {}): CtoItem[] {
  const wk = extra.week
  const end = wk ? daysBefore(wk, -7) : ''
  let xs = items.filter((i) => (wk ? i.ship >= wk && i.ship < end : i.period === 'agent') && inLine(line)(i))
  if (extra.size) xs = xs.filter((i) => i.size === extra.size)
  if (extra.defects) xs = xs.filter((i) => (i.defects?.length ?? 0) > 0)
  if (kind !== 'all') xs = xs.filter((i) => i.kind === kind)
  if (realOnly) xs = xs.filter((i) => i.real)
  const pin = (i: CtoItem) => (i.real && fresh.has(i.real) ? 0 : i.real ? 1 : 2)
  return [...xs].sort((a, b) => pin(a) - pin(b) || (a.ship < b.ship ? 1 : a.ship > b.ship ? -1 : 0))
}

/** 交付清单 as CSV for Excel: UTF-8 with a BOM, CRLF lines, quoted where needed. */
export function ledgerCsv(rows: CtoItem[], meta: CtoMeta, base: Record<Size, number>): string {
  const q = (v: string | number) => (/[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v))
  const head = ['交付', '业务线', '类型', '规模', 'Issue', '提出方', 'Issue 创建日', '上线日', '周期（天）', '以前同规模平均周期（天）', '签字', 'PR', '上线后缺陷', '修复的 Issue', '来源', '运行编号']
  const lines = rows.map((i) =>
    [i.t, meta.lines[i.line], KIND[i.kind], SIZE[i.size], i.issue ?? '', i.reporter ?? '', i.created ?? '', i.ship, (i.mins != null ? i.mins / 1440 : i.cyc).toFixed(2), base[i.size].toFixed(1), i.signer,
      i.pr ? `#${i.pr}` : '', (i.defects ?? []).join(' '), i.origin ?? '', i.real ? '实测' : '模拟', i.real ?? '']
      .map(q)
      .join(','),
  )
  return '\ufeff' + [head.join(','), ...lines].join('\r\n')
}
