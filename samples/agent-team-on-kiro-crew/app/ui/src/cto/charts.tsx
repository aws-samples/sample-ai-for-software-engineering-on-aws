/**
 * The CTO view's charts, drawn as SVG: the three cards' small charts (更多: two stacked bars, 更快: a dumbbell per size,
 * 更省: two bars) and the weekly releases (stacked columns, a line where AI-DLC came in). Marks follow the dataviz
 * specs: bars at most 24 px thick with a 4 px rounded end, a 2 px gap between stacked segments, hairline grid, a
 * tooltip on every mark (values first, then the name) and a table view for the weekly chart.
 */
import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import { KIND, KINDS, KIND_VAR, day1, fmt, md, mean, type Metrics, type Week } from './metrics'
import type { CtoMeta, Kind, Size } from './types'

export type TipRow = [value: string, label: string, color?: string]
export type TipState = { x: number; y: number; rows: TipRow[]; when?: string } | null

/** The width of an element, followed as it changes (a fixed width where there is no ResizeObserver, as in tests). */
export function useWidth(fallback = 600): [React.RefObject<HTMLDivElement>, number] {
  const ref = useRef<HTMLDivElement>(null)
  const [w, setW] = useState(fallback)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const read = () => el.clientWidth > 0 && setW(el.clientWidth)
    read()
    if (typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(read)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, w]
}

export function Tip({ tip, width }: { tip: TipState; width: number }) {
  const ref = useRef<HTMLDivElement>(null)
  const [left, setLeft] = useState(0)
  useEffect(() => {
    if (!tip || !ref.current) return
    const w = ref.current.offsetWidth || 200
    setLeft(Math.min(Math.max(tip.x - w / 2, 0), Math.max(0, width - w)))
  }, [tip, width])
  if (!tip) return null
  return (
    <div ref={ref} className="cto-tip" role="tooltip" style={{ left, top: tip.y }}>
      {tip.when && <div className="cto-when">{tip.when}</div>}
      {tip.rows.map(([v, label, color], i) => (
        <div className="cto-row" key={i}>
          <b>{v}</b>
          {color && <i className="cto-key" style={{ background: color }} />}
          <span>{label}</span>
        </div>
      ))}
    </div>
  )
}

/** A hover and focus target bigger than its mark: shows the tooltip under it. */
export function Hit({ x, y, w, h, rows, onTip, when, tipY, onPick, label }: { x: number; y: number; w: number; h: number; rows: TipRow[]; when?: string; tipY?: number; onTip: (t: TipState) => void; onPick?: () => void; label?: string }) {
  const show = () => onTip({ x: x + w / 2, y: tipY ?? y + h + 6, rows, when })
  const key = onPick ? (e: KeyboardEvent) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), onPick()) : undefined
  return (
    <rect className={`cto-hit${onPick ? ' is-pick' : ''}`} x={x} y={y} width={w} height={h} rx={6} tabIndex={0} role={onPick ? 'button' : undefined} aria-label={label}
      onPointerEnter={show} onFocus={show} onPointerLeave={() => onTip(null)} onBlur={() => onTip(null)} onClick={onPick} onKeyDown={key} />
  )
}

/** A bar growing right from the baseline: square at the baseline, a 4 px rounded data end. */
function BarEnd({ x, y, w, h, fill }: { x: number; y: number; w: number; h: number; fill: string }) {
  const r = Math.min(4, w, h / 2)
  return <path d={`M${x},${y} H${x + w - r} Q${x + w},${y} ${x + w},${y + r} V${y + h - r} Q${x + w},${y + h} ${x + w - r},${y + h} H${x} Z`} fill={fill} />
}

export function Mini({ label, height, children }: { label: string; height: number; children: (w: number, onTip: (t: TipState) => void) => ReactNode }) {
  const [ref, w] = useWidth(360)
  const [tip, setTip] = useState<TipState>(null)
  return (
    <div className="cto-mini" ref={ref}>
      <svg viewBox={`0 0 ${w} ${height}`} height={height} role="img" aria-label={label}>
        {children(w, setTip)}
      </svg>
      <Tip tip={tip} width={w} />
    </div>
  )
}

/** 更多: 前 12 周 and 近 12 周 as stacked bars on one scale, segments by type, each bar's count at its end. */
export function MiniMore({ m }: { m: Metrics }) {
  const bh = 22, gap = 14, H = 2 * bh + gap + 4, L = 64, R = 70
  const rows: [string, typeof m.agent][] = [['前 12 周', m.before], ['近 12 周', m.agent]]
  return (
    <Mini label={`交付量：前 12 周 ${m.before.length} 项，近 12 周 ${m.agent.length} 项`} height={H}>
      {(W, onTip) => {
        const max = Math.max(m.before.length, m.agent.length, 1), pw = Math.max(10, W - L - R)
        return rows.map(([lab, arr], r) => {
          const y0 = 2 + r * (bh + gap), now = r === 1
          let cum = 0
          const segs = KINDS.map((k) => [k, m.count(arr, k)] as [Kind, number]).filter(([, n]) => n > 0)
          const marks = segs.map(([k, n], j) => {
            const x0 = L + (cum / max) * pw + (cum > 0 ? 2 : 0), x1 = L + ((cum + n) / max) * pw
            cum += n
            if (x1 - x0 <= 0.5) return null
            return j === segs.length - 1 ? <BarEnd key={k} x={x0} y={y0} w={x1 - x0} h={bh} fill={KIND_VAR[k]} /> : <rect key={k} x={x0} y={y0} width={x1 - x0} height={bh} fill={KIND_VAR[k]} />
          })
          const end = L + (cum / max) * pw
          return (
            <g key={lab}>
              <text x={0} y={y0 + bh / 2 + 4} className={now ? 'is-strong' : undefined}>{lab}</text>
              {marks}
              <text x={end + 8} y={y0 + bh / 2 + 4} className={now ? 'is-strong' : undefined}>{fmt(arr.length)} 项</text>
              <Hit x={L - 4} y={y0 - 3} w={end - L + 8} h={bh + 6} onTip={onTip} rows={[[fmt(arr.length), `${lab} 合计`], ...KINDS.map((k) => [fmt(m.count(arr, k)), KIND[k], KIND_VAR[k]] as TipRow)]} />
            </g>
          )
        })
      }}
    </Mini>
  )
}

/** 更快: one dumbbell per size, 以前 (grey) → 现在 (violet), the numbers at the right. */
export function MiniFast({ m, base, onPick }: { m: Metrics; base: Record<Size, number>; onPick?: (s: Size) => void }) {
  const sizes: Size[] = ['L', 'M', 'S']
  const rows = ([['大型', 'L'], ['中型', 'M'], ['小型', 'S']] as [string, Size][]).map(([lab, s]) => [lab, base[s], m.cycle(s)] as [string, number, number])
  const rh = 26, H = rows.length * rh, L = 40, R = 104
  return (
    <Mini label={'交付周期，以前与现在：' + rows.map(([l, b, a]) => `${l} ${day1(b)} 天 → ${day1(a)} 天`).join('，')} height={H}>
      {(W, onTip) => {
        const max = Math.max(...rows.map(([, b, a]) => Math.max(b, a)), 1), pw = Math.max(10, W - L - R)
        const x = (v: number) => L + (v / max) * pw
        return (
          <>
            <line x1={L} x2={L} y1={2} y2={H - 2} stroke="var(--border-strong)" strokeWidth={1} />
            {rows.map(([lab, b, a], r) => {
              const cy = r * rh + rh / 2
              return (
                <g key={lab}>
                  <text x={0} y={cy + 4} className={r === 0 ? 'is-strong' : undefined}>{lab}</text>
                  <line x1={x(a)} x2={x(b)} y1={cy} y2={cy} stroke="var(--border-strong)" strokeWidth={2} strokeLinecap="round" />
                  <circle cx={x(b)} cy={cy} r={4.5} fill="var(--deemph)" stroke="var(--card)" strokeWidth={2} />
                  <circle cx={x(a)} cy={cy} r={5} fill="var(--s4)" stroke="var(--card)" strokeWidth={2} />
                  <text x={W} y={cy + 4} textAnchor="end">
                    {day1(b)} → <tspan style={{ fill: 'var(--text-strong)', fontWeight: 600 }}>{day1(a)} 天</tspan>
                  </text>
                  <Hit x={0} y={cy - rh / 2 + 1} w={W} h={rh - 2} onTip={onTip} rows={[[`${day1(b)} 天`, '以前', 'var(--deemph)'], [`${day1(a)} 天`, '现在', 'var(--s4)'], [b ? `${Math.round((1 - a / b) * 100)}%` : '—', '缩短'], ...(onPick ? [['点击', '看这一规模的交付'] as TipRow] : [])]}
                    onPick={onPick ? () => onPick(sizes[r]) : undefined} label={`${lab}：看这一规模的交付`} />
                </g>
              )
            })}
          </>
        )
      }}
    </Mini>
  )
}

/** 交付详情 · 周期: this delivery against the same size before AI-DLC, the 更快 card's dumbbell for one row. */
export function MiniCycle({ size, before, days, now }: { size: string; before: number; days: number; now: string }) {
  const rh = 26, L = 40, R = 132
  return (
    <Mini label={`${size}，以前约 ${day1(before)} 天，这次 ${now}`} height={rh}>
      {(W, onTip) => {
        const pw = Math.max(10, W - L - R), x = (v: number) => L + (Math.min(v, before) / Math.max(before, days, 1e-6)) * pw, cy = rh / 2
        return (
          <>
            <line x1={L} x2={L} y1={2} y2={rh - 2} stroke="var(--border-strong)" strokeWidth={1} />
            <text x={0} y={cy + 4} className="is-strong">{size}</text>
            <line x1={x(days)} x2={x(before)} y1={cy} y2={cy} stroke="var(--border-strong)" strokeWidth={2} strokeLinecap="round" />
            <circle cx={x(before)} cy={cy} r={4.5} fill="var(--deemph)" stroke="var(--card)" strokeWidth={2} />
            <circle cx={x(days)} cy={cy} r={5} fill="var(--s4)" stroke="var(--card)" strokeWidth={2} />
            <text x={W} y={cy + 4} textAnchor="end">
              {day1(before)} 天 → <tspan style={{ fill: 'var(--text-strong)', fontWeight: 600 }}>{now}</tspan>
            </text>
            <Hit x={0} y={1} w={W} h={rh - 2} onTip={onTip} rows={[[`${day1(before)} 天`, `以前同规模（${size}）平均`, 'var(--deemph)'], [now, '这次', 'var(--s4)']]} />
          </>
        )
      }}
    </Mini>
  )
}

/** 交付详情 · 时间花在哪: one stacked bar (2 px surface gaps, the data end rounded), the total at its end. */
export function MiniSplit({ parts, total }: { parts: { label: string; s: number; color: string; onPick?: () => void }[]; total: string }) {
  const bh = 14, H = bh + 8, R = 70
  const shown = parts.filter((p) => p.s > 0)
  const sum = shown.reduce((a, p) => a + p.s, 0) || 1
  return (
    <Mini label={'时间花在哪：' + shown.map((p) => `${p.label} ${fmtSec(p.s)}`).join('，')} height={H}>
      {(W, onTip) => {
        const pw = Math.max(10, W - R - 8)
        let x = 0
        return (
          <>
            {shown.map((p, i) => {
              const w = Math.max(2, (p.s / sum) * pw - (i < shown.length - 1 ? 2 : 0))
              const x0 = x
              x += (p.s / sum) * pw
              const mark = i === shown.length - 1 ? <BarEnd x={x0} y={4} w={w} h={bh} fill={p.color} /> : <rect x={x0} y={4} width={w} height={bh} fill={p.color} />
              return (
                <g key={p.label}>
                  {mark}
                  <Hit x={x0} y={0} w={Math.max(8, w)} h={H} onTip={onTip} rows={[[fmtSec(p.s), p.label, p.color], [`${Math.round((p.s / sum) * 100)}%`, '占整段时间']]}
                    onPick={p.onPick} label={`${p.label} ${fmtSec(p.s)}`} />
                </g>
              )
            })}
            <text x={pw + 8} y={4 + bh - 2} className="is-strong">{total}</text>
          </>
        )
      }}
    </Mini>
  )
}

/** seconds as the board writes a span: 52 秒 · 8 分钟 · 1 小时 5 分 */
export function fmtSec(sec: number): string {
  const s = Math.max(0, Math.round(sec))
  if (s < 60) return `${s} 秒`
  const m = Math.round(s / 60)
  if (m < 60) return `${m} 分钟`
  const h = Math.floor(m / 60)
  return m % 60 ? `${h} 小时 ${m % 60} 分` : `${h} 小时`
}

/** 更省: the cost of a person-day of work, 以前 and 现在 (its split into people's time and the agent subscription on hover). */
/** 更稳: defects raised after release per 100 new apps and features, 以前 (grey) and 现在 (violet), on one scale. */
export function MiniSteady({ m }: { m: Metrics }) {
  const st = m.steady
  const bh = 22, gap = 14, H = 2 * bh + gap + 4, L = 40, R = 70
  const rows: [string, number, string, number, number][] = [
    ['以前', st.before, 'var(--deemph)', st.defectsBefore, st.watchedBefore],
    ['现在', st.now, 'var(--s4)', st.defectsNow, st.watchedNow],
  ]
  const max = Math.max(st.before, st.now, 0.1)
  return (
    <Mini label={`每 100 项新应用和新功能的上线后缺陷：以前 ${st.before.toFixed(1)}，现在 ${st.now.toFixed(1)}`} height={H}>
      {(W, onTip) => {
        const pw = Math.max(10, W - L - R)
        return rows.map(([lab, v, fill, d, n], r) => {
          const y0 = 2 + r * (bh + gap), w = (v / max) * pw
          return (
            <g key={lab}>
              <text x={0} y={y0 + bh / 2 + 4} className={r === 1 ? 'is-strong' : undefined}>{lab}</text>
              <BarEnd x={L} y={y0} w={Math.max(w, 1)} h={bh} fill={fill} />
              <text x={L + w + 8} y={y0 + bh / 2 + 4} className={r === 1 ? 'is-strong' : undefined}>{v.toFixed(1)}</text>
              <Hit x={L - 4} y={y0 - 3} w={w + 8} h={bh + 6} onTip={onTip} rows={[[v.toFixed(1), '每 100 项的上线后缺陷'], [fmt(d), '上线后缺陷'], [fmt(n), '新应用和新功能']]} />
            </g>
          )
        })
      }}
    </Mini>
  )
}

export function MiniCheap({ m, meta }: { m: Metrics; meta: CtoMeta }) {
  const bh = 22, gap = 14, H = 2 * bh + gap + 4, L = 40, R = 70
  const human = m.eq ? (m.human * meta.dayRate) / m.eq : 0, agentPart = m.eq ? m.sub / m.eq : 0
  const rows: [string, number, string][] = [['以前', meta.dayRate, 'var(--deemph)'], ['现在', m.unit, 'var(--s4)']]
  return (
    <Mini label={`每人日工作量的成本：以前 ¥${fmt(meta.dayRate)}，现在 ¥${fmt(m.unit)}`} height={H}>
      {(W, onTip) => {
        const pw = Math.max(10, W - L - R)
        return rows.map(([lab, v, fill], r) => {
          const y0 = 2 + r * (bh + gap), w = (v / meta.dayRate) * pw
          return (
            <g key={lab}>
              <text x={0} y={y0 + bh / 2 + 4} className={r === 1 ? 'is-strong' : undefined}>{lab}</text>
              <BarEnd x={L} y={y0} w={Math.max(w, 1)} h={bh} fill={fill} />
              <text x={L + w + 8} y={y0 + bh / 2 + 4} className={r === 1 ? 'is-strong' : undefined}>¥{fmt(v)}</text>
              <Hit x={L - 4} y={y0 - 3} w={w + 8} h={bh + 6} onTip={onTip} rows={r === 0 ? [[`¥${fmt(v)}`, '人工完成，每人日']] : [[`¥${fmt(v)}`, 'agent 协作，每人日'], [`¥${fmt(human)}`, '其中人的时间'], [`¥${fmt(agentPart)}`, '其中 agent 订阅']]} />
            </g>
          )
        })
      }}
    </Mini>
  )
}

function niceMax(v: number): number {
  const p = Math.pow(10, Math.floor(Math.log10(Math.max(v, 1))))
  for (const f of [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) if (f * p >= v) return f * p
  return 10 * p
}

export const slash = (iso: string) => md(iso).replace(/^0/, '').replace('-0', '-').replace('-', '/')

/** 每周上线: 24 weeks of releases stacked by type, a line where AI-DLC came in; or the same as a table. */
export function WeeklyChart({ weeks, today, onWeek }: { weeks: Week[]; today: string; onWeek?: (start: string) => void }) {
  const [asTable, setAsTable] = useState(false)
  const [ref, Wd] = useWidth(1100)
  const [tip, setTip] = useState<TipState>(null)
  const before = mean(weeks.slice(0, 12).map((w) => w.total)), after = mean(weeks.slice(12).map((w) => w.total))
  const H = 270, L = 44, R = 12, T = 26, B = 30
  const pw = Math.max(10, Wd - L - R), ph = H - T - B, slot = pw / weeks.length, bw = Math.min(24, slot * 0.56)
  const ymax = niceMax(Math.max(1, ...weeks.map((w) => w.total)))
  const y = (v: number) => T + ph - (v / ymax) * ph
  const xm = Math.round(L + 12 * slot) + 0.5
  return (
    <section className="cto-card" aria-label="每周上线" data-anchor="weekly">
      <div className="cto-chart-head">
        <h3>每周上线</h3>
        <span className="cto-dim">
          前 12 周平均每周 {fmt(before)} 项 → 近 12 周平均每周 {fmt(after)} 项；最近一周 {fmt(weeks[weeks.length - 1]?.total ?? 0)} 项（截至 {md(today)}）
        </span>
        <span className="cto-grow" />
        <div className="cto-seg cto-noprint" role="group" aria-label="图或表格">
          <button type="button" aria-pressed={!asTable} onClick={() => setAsTable(false)}>图</button>
          <button type="button" aria-pressed={asTable} onClick={() => setAsTable(true)}>表格</button>
        </div>
      </div>
      {!asTable && (
        <div className="cto-legend">
          {KINDS.map((k) => (
            <span key={k}><i className="cto-sw" style={{ background: KIND_VAR[k] }} />{KIND[k]}</span>
          ))}
        </div>
      )}
      <div className="cto-plot" ref={ref} hidden={asTable}>
        <svg viewBox={`0 0 ${Wd} ${H}`} role="img" aria-label="每周上线数量，按类型堆叠">
          {[0, 1, 2, 3, 4].map((t) => {
            const v = (ymax / 4) * t, yy = Math.round(y(v)) + 0.5
            return (
              <g key={t}>
                <line x1={L} x2={Wd - R} y1={yy} y2={yy} stroke={t === 0 ? 'var(--border-strong)' : 'var(--border)'} strokeWidth={1} />
                <text x={L - 8} y={yy + 4} textAnchor="end">{fmt(v)}</text>
              </g>
            )
          })}
          <line x1={xm} x2={xm} y1={T - 8} y2={T + ph} stroke="var(--muted)" strokeWidth={1} />
          <text x={xm + 6} y={T - 10} className="cto-mark">引入 AI-DLC</text>
          <text x={L + 6 * slot} y={T - 10} className="cto-mark" textAnchor="middle">引入前 12 周</text>
          {weeks.map((w, i) => {
            const cx = L + slot * i + slot / 2, x0 = cx - bw / 2
            let cum = 0
            const segs = KINDS.filter((k) => w[k] > 0)
            const marks = segs.map((k, j) => {
              const yb = y(cum) - (cum > 0 ? 2 : 0), yt = y(cum + w[k])
              cum += w[k]
              const h = yb - yt
              if (h <= 0.5) return null
              if (j === segs.length - 1) {
                const r = Math.min(4, h, bw / 2)
                return <path key={k} d={`M${x0},${yb} V${yt + r} Q${x0},${yt} ${x0 + r},${yt} H${x0 + bw - r} Q${x0 + bw},${yt} ${x0 + bw},${yt + r} V${yb} Z`} fill={KIND_VAR[k]} />
              }
              return <rect key={k} x={x0} y={yt} width={bw} height={h} fill={KIND_VAR[k]} />
            })
            return (
              <g key={w.start}>
                {marks}
                {i % 2 === 0 && <text x={cx} y={T + ph + 18} textAnchor="middle">{slash(w.start)}</text>}
                <Hit x={L + slot * i} y={T} w={slot} h={ph} onTip={setTip} tipY={Math.max(0, y(w.total) - 110)}
                  when={`${slash(w.start)} 起的一周 · ${i < 12 ? '引入前' : `引入后第 ${i - 11} 周`}`}
                  rows={[[fmt(w.total), '合计'], ...KINDS.map((k) => [fmt(w[k]), KIND[k], KIND_VAR[k]] as TipRow), ...(onWeek ? [['点击', '看这一周的交付'] as TipRow] : [])]}
                  onPick={onWeek ? () => onWeek(w.start) : undefined} label={`${slash(w.start)} 起的一周：看这一周的交付`} />
              </g>
            )
          })}
        </svg>
        <Tip tip={tip} width={Wd} />
      </div>
      {asTable && (
        <div className="cto-weeks">
          <table className="cto-table">
            <thead>
              <tr><th>一周起始</th>{KINDS.map((k) => <th key={k} className="is-num">{KIND[k]}</th>)}<th className="is-num">合计</th></tr>
            </thead>
            <tbody>
              {weeks.map((w, i) => (
                <tr key={w.start}>
                  <td>{w.start}{i === 12 ? '（引入 AI-DLC）' : ''}</td>
                  {KINDS.map((k) => <td key={k} className="is-num">{fmt(w[k])}</td>)}
                  <td className="is-num">{fmt(w.total)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
