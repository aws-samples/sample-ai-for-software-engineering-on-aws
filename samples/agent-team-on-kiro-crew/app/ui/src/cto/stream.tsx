/**
 * 价值流 as a chart, in the CTO view's chart style (每周上线): one band on a time axis, cut into agent / 返工 / 等人批准 ·
 * 签字 segments (2 px surface gaps, the ends rounded), the board's role icons above the agent segments (green chips, as on
 * the board's 角色完成) and the person icon above a gate; labels under the wide segments; the moments of the run on a lane
 * of their own under the axis (the legend names it), each with its icon. Every segment and moment has a tooltip and opens the board there.
 * Colours: categorical slots validated on the card surface in both modes (violet · magenta · yellow; styles.ts).
 */
import { useState } from 'react'
import { RoleGlyph } from '../board/RoleIcon'
import { fmtClock } from '../board/format'
import type { BoardEntry } from '../nav'
import { Hit, Tip, fmtSec, useWidth, type TipState } from './charts'
import type { CtoFlow, FlowMark, FlowSegment } from './types'

export type SegKind = 'agent' | 'rework' | 'person'
export const VS_COLOR: Record<SegKind, string> = { agent: 'var(--vs-agent)', rework: 'var(--vs-rework)', person: 'var(--vs-person)' }
export const VS_NAME: Record<SegKind, string> = { agent: 'agent 在做', rework: '返工', person: '等人批准 · 签字' }
export const segKind = (s: FlowSegment): SegKind => (s.who === 'person' ? 'person' : s.label === '返工' ? 'rework' : 'agent')
export const MARK_ICON: Record<FlowMark['kind'], string> = { gate: 'wait', approved: 'approved', bounce: 'bounce', check: 'tester', review: 'reviewer', deployed: 'deploy', signoff: 'sign', merged: 'merge' }
export const MARK_TONE: Record<FlowMark['kind'], string> = { gate: 'is-wait', approved: 'is-ok', bounce: 'is-back', check: 'is-back', review: 'is-back', deployed: 'is-ok', signoff: 'is-ok', merged: 'is-ok' }

/** Where a segment of the 价值流 is on the board: its gate (a person's), else its phase, at its start. */
export function boardAt(run: string, s: FlowSegment): BoardEntry {
  if (s.gate === 'signoff') return { run, focus: 'signoff' }
  if (s.gate) return { run, gate: s.gate, at: Math.round(s.from) }
  return { run, ...(s.phase ? { phase: s.phase } : {}), at: Math.round(s.from) }
}
export function markAt(run: string, m: FlowMark): BoardEntry {
  return m.kind === 'signoff' || m.kind === 'merged' ? { run, focus: 'signoff' } : { run, ...(m.role ? { role: m.role } : {}), at: Math.round(m.at) }
}

/** The segment of the 价值流 at a moment (seconds from the run's start): the one it falls in, else (it falls in the second
 * between two, or a moment is rounded down) the next one. */
export function segAt(segments: readonly FlowSegment[], at: number | undefined): number {
  if (at === undefined) return -1
  const i = segments.findIndex((s) => at >= s.from && at < s.to)
  return i >= 0 ? i : segments.findIndex((s) => s.from > at)
}

const STEPS = [30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 14400, 28800, 86400]

export function StreamChart({ flow, run, onBoard, hlAt }: { flow: CtoFlow; run: string; onBoard: (e: BoardEntry) => void; hlAt?: number }) {
  const [ref, W] = useWidth(1100)
  const [tip, setTip] = useState<TipState>(null)
  const total = Math.max(1, flow.end)
  const L = 6, R = 6, pw = Math.max(10, W - L - R)
  const x = (t: number) => L + (Math.min(Math.max(t, 0), total) / total) * pw
  const BAND = 36, BH = 24, AXIS = 112, MOM = 148
  const step = STEPS.find((s) => total / s <= 8) ?? STEPS[STEPS.length - 1]
  const ticks = Array.from({ length: Math.floor(total / step) + 1 }, (_, i) => i * step)
  const icon = (k: string) => flow.team.find((m) => m.key === k)?.icon ?? k
  const who = (s: FlowSegment) => (s.who === 'person' ? '负责人' : s.roles.map((k) => flow.titles[k] ?? k).join('、'))
  // the moments in rows: one that would sit on top of the one before it goes a row down
  const rows: number[] = []
  const placed = flow.marks.map((m) => {
    const mx = Math.min(Math.max(x(m.at), L + 12), W - R - 12)  // the whole marker inside the chart
    let r = rows.findIndex((last) => mx - last >= 26)
    if (r < 0) r = rows.length < 3 ? rows.length : 2
    rows[r] = mx
    return { m, mx, my: MOM + r * 26 }
  })
  const H = MOM + Math.max(1, rows.length) * 26 + 4
  const hl = segAt(flow.segments, hlAt)
  return (
    <div className="cto-plot cto-vs-plot" ref={ref} style={{ height: H }}>
      <svg viewBox={`0 0 ${W} ${H}`} role="group" aria-label={`价值流：${flow.segments.map((s) => `${s.label} ${fmtSec(s.to - s.from)}`).join('，')}`} data-testid="item-stream">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={x(t)} x2={x(t)} y1={BAND - 6} y2={AXIS} stroke="var(--border)" strokeWidth={1} />
            <text x={x(t)} y={AXIS + 16} textAnchor={t === 0 ? 'start' : 'middle'}>{fmtClock(t)}</text>
          </g>
        ))}
        <line x1={L} x2={W - R} y1={AXIS} y2={AXIS} stroke="var(--border-strong)" strokeWidth={1} />
        {flow.segments.map((s, i) => {
          const k = segKind(s)
          const x0 = x(s.from), x1 = x(s.to), w = Math.max(2, x1 - x0 - (i < flow.segments.length - 1 ? 2 : 0))
          const first = i === 0, last = i === flow.segments.length - 1, r = 4
          const d = `M${x0 + (first ? r : 0)},${BAND} H${x0 + w - (last ? r : 0)}${last ? ` Q${x0 + w},${BAND} ${x0 + w},${BAND + r} V${BAND + BH - r} Q${x0 + w},${BAND + BH} ${x0 + w - r},${BAND + BH}` : ` V${BAND + BH}`} H${x0 + (first ? r : 0)}${first ? ` Q${x0},${BAND + BH} ${x0},${BAND + BH - r} V${BAND + r} Q${x0},${BAND} ${x0 + r},${BAND}` : ` V${BAND}`} Z`
          const chips = s.who === 'person' ? (s.gate === 'signoff' ? ['sign'] : ['wait']) : s.roles.map(icon)
          const fit = Math.max(0, Math.floor((w + 2) / 22))
          const showChips = chips.slice(0, fit >= chips.length ? chips.length : Math.max(0, fit - 1))
          const more = chips.length - showChips.length
          const label = s.who === 'person' ? s.label.replace('等人批准 · ', '') : s.label
          return (
            <g key={`${s.from}-${s.label}`} className={`cto-vs-seg is-${k}${i === hl ? ' is-hl' : ''}`} data-hl={i === hl ? 'true' : undefined}>
              <path d={d} fill={VS_COLOR[k]} />
              {showChips.map((c, j) => (
                <g key={j} className={`cto-vs-chip ${s.who === 'person' ? 'is-wait' : 'is-ok'}`} transform={`translate(${x0 + j * 22},${BAND - 28})`}>
                  <rect width={20} height={20} rx={6} />
                  <RoleGlyph role={c} cx={10} cy={10} size={14} />
                </g>
              ))}
              {more > 0 && fit > 0 && <text x={x0 + showChips.length * 22 + 2} y={BAND - 13}>+{more}</text>}
              {w >= 58 && (
                <>
                  <text x={x0} y={BAND + BH + 18} className="is-strong">{label.length * 13 > w ? `${label.slice(0, Math.max(1, Math.floor(w / 13) - 1))}…` : label}</text>
                  <text x={x0} y={BAND + BH + 34}>{fmtSec(s.to - s.from)}{s.decision && s.decision !== '签字' ? ` · ${s.decision}` : ''}</text>
                </>
              )}
              <Hit x={x0} y={BAND - 30} w={Math.max(6, w)} h={BH + 72} onTip={setTip} tipY={BAND + BH + 40}
                when={`${fmtClock(s.from)}–${fmtClock(s.to)} · ${VS_NAME[k]}`}
                rows={[[fmtSec(s.to - s.from), label, VS_COLOR[k]], [who(s), s.who === 'person' ? '谁决定' : '谁在做'], ...(s.decision ? [[s.decision, '结论'] as [string, string]] : []), ['点击', s.who === 'person' ? '到看板上的这个关卡' : '到看板上的这个阶段']]}
                onPick={() => onBoard(boardAt(run, s))} label={`${label}，${fmtSec(s.to - s.from)}：到团队看板的这个环节`} />
            </g>
          )
        })}
        {placed.map(({ m, mx, my }) => (
          <g key={`${m.at}-${m.kind}-${m.label}`} className={`cto-vs-moment ${MARK_TONE[m.kind]}`}>
            <line x1={mx} x2={mx} y1={BAND + BH} y2={my - 11} className="cto-vs-tick" />
            <circle cx={mx} cy={my} r={11} />
            <RoleGlyph role={MARK_ICON[m.kind]} cx={mx} cy={my} size={14} />
            <Hit x={mx - 13} y={my - 13} w={26} h={26} onTip={setTip} tipY={my + 16} when={fmtClock(m.at)} rows={[[m.label, ''], ['点击', '看板回放到这一刻']]}
              onPick={() => onBoard(markAt(run, m))} label={`${fmtClock(m.at)} ${m.label}：看板回放到这一刻`} />
          </g>
        ))}
      </svg>
      <Tip tip={tip} width={W} />
    </div>
  )
}
