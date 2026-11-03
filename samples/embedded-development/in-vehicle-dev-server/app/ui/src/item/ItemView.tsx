/**
 * 交付详情 (GET /runs/<id>/flow): where one run's time went, measured from its records only (backend/team/flow.py). The
 * totals as cards, then the stream: a row per role (its attempts), 等人 (human gates, the operator console), 检查 (the
 * check rounds, the independent rerun) and the moments; every segment and moment opens the board's replay there.
 * A figure with no record behind it is —. Refreshed every 10 s while the run is going.
 */
import { useEffect, useState } from 'react'
import { useAppApi } from '@kirocrew/app-sdk'
import { BOARD_CSS } from '../board/styles'
import { fmtClock, fmtCredits, fmtSpan, paths, runMeta } from '../board/format'
import { RoleIcon } from '../board/RoleIcon'
import { errorText } from '../board/useBoard'
import { KIT_CSS } from '../kit'
import type { BoardEntry } from '../nav'
import type { FlowMark, FlowSegment, RunFlow } from '../types'

export const ITEM_POLL_MS = 10000
const EMPTY = '—'

const IT_CSS = `
.it-root .cto-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); }
.it-root .cto-card { margin: 0; }
.it-root .cto-value { font-size: 2em; }
.it-root .cto-value.is-empty { color: var(--muted); }
.it-head { display: flex; align-items: baseline; flex-wrap: wrap; gap: 4px 12px; }
.it-head h2 { margin: 0; font-size: 1.4em; color: var(--text-strong); }
.it-stream { display: grid; grid-template-columns: 9.5em minmax(0, 1fr); gap: 6px 10px; align-items: center; }
.it-row-name { display: flex; align-items: center; gap: 6px; font-size: .88em; font-weight: 650; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.it-track { position: relative; height: 22px; border-radius: 6px; background: var(--kt-glass); }
.it-seg { position: absolute; top: 2px; bottom: 2px; min-width: 3px; padding: 0; border: 0; border-radius: 4px; cursor: pointer; background: var(--it-c); }
.it-seg.is-open { background: repeating-linear-gradient(135deg, var(--it-c) 0 6px, color-mix(in srgb, var(--it-c) 55%, transparent) 6px 12px); }
.it-seg.is-bad { box-shadow: inset 0 0 0 2px var(--kt-bad); }
.it-seg:hover, .it-seg:focus-visible, .it-mark:hover, .it-mark:focus-visible { outline: 2px solid var(--text-strong); outline-offset: 1px; z-index: 1; }
.it-root .k-agent { --it-c: var(--kt-run); } .it-root .k-gate { --it-c: var(--kt-approve); } .it-root .k-console { --it-c: var(--kt-warn); }
.it-root .k-checks { --it-c: var(--kt-info); } .it-root .k-rerun { --it-c: var(--kt-handoff); }
.it-mark { position: absolute; top: 3px; width: 16px; height: 16px; margin-left: -8px; padding: 0; border-radius: 50%; cursor: pointer; border: 2px solid var(--card); background: var(--it-c); }
.it-root .k-bounce { --it-c: var(--kt-bad); } .it-root .k-check_fail { --it-c: var(--kt-fix); } .it-root .k-approved { --it-c: var(--kt-ok); } .it-root .k-signoff { --it-c: var(--kt-done); }
.it-axis { position: relative; height: 16px; font-size: .76em; color: var(--muted); font-variant-numeric: tabular-nums; }
.it-axis span { position: absolute; transform: translateX(-50%); white-space: nowrap; }
.it-axis span:first-child { transform: none; }
.it-legend { display: flex; flex-wrap: wrap; gap: 4px 14px; margin: 10px 0 0; padding: 0; list-style: none; font-size: .84em; color: var(--muted); }
.it-legend i { display: inline-block; width: 12px; height: 12px; margin-right: 5px; vertical-align: -1px; border-radius: 3px; background: var(--it-c); }
.it-root section.cto-card > h3 { margin: 0 0 10px; font-size: 1.1em; color: var(--text-strong); }
`

const KIND_NAME: Record<FlowSegment['kind'], string> = { agent: 'agent 在做', gate: '等人批准', console: '等操作台', checks: '跑检查', rerun: '独立重跑' }
const MARK_NAME: Record<FlowMark['kind'], string> = { bounce: '打回', check_fail: '检查不过', approved: '批准', signoff: '签字' }
const STEPS = [30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 14400, 28800, 86400]

const span = (x: number | null) => (x === null ? EMPTY : fmtSpan(x))

/** Where a segment opens the board: the replay at its start, on its role (its gate). */
export function boardAt(run: string, s: FlowSegment): BoardEntry {
  return { run, at: Math.floor(s.from), ...(s.role ? (s.kind === 'gate' ? { gate: s.role } : { role: s.role }) : {}) }
}
export function markAt(run: string, m: FlowMark): BoardEntry {
  return m.kind === 'signoff' ? { run, focus: 'signoff' } : { run, at: Math.floor(m.at), ...(m.role ? { role: m.role } : {}) }
}

function Card({ label, value, of }: { label: string; value: string; of?: string }) {
  const empty = value === EMPTY
  return (
    <div className="cto-card" data-testid="it-card">
      <div className="cto-eyebrow">{label}</div>
      <div className={`cto-value${empty ? ' is-empty' : ''}`}>
        {value}
        {of && !empty && <span className="cto-of"> {of}</span>}
      </div>
    </div>
  )
}

function Track({ segs, marks = [], total, run, onBoard }: { segs: FlowSegment[]; marks?: FlowMark[]; total: number; run: string; onBoard: (e: BoardEntry) => void }) {
  const pct = (t: number) => `${(Math.min(Math.max(t, 0), total) / total) * 100}%`
  return (
    <div className="it-track">
      {segs.map((s) => {
        const what = `${s.label} · ${fmtClock(s.from)}–${fmtClock(s.to)} · ${fmtSpan(s.to - s.from)}${s.result ? ` · ${s.result}` : ''}${s.open ? ' · 还在进行' : ''}`
        return (
          <button key={`${s.kind}-${s.from}-${s.role ?? ''}`} type="button" data-testid="it-seg" data-kind={s.kind}
            className={`it-seg k-${s.kind}${s.open ? ' is-open' : ''}${s.result === '不过' || s.result === '退回' || s.result === '拒绝' || s.result === '超时' || s.result === '不同' ? ' is-bad' : ''}`}
            style={{ left: pct(s.from), width: `calc(${pct(s.to)} - ${pct(s.from)})` }} title={what} aria-label={`${what}：在看板上回放到这一刻`}
            onClick={() => onBoard(boardAt(run, s))} />
        )
      })}
      {marks.map((m) => (
        <button key={`${m.kind}-${m.at}-${m.label}`} type="button" data-testid="it-mark" data-kind={m.kind} className={`it-mark k-${m.kind}`} style={{ left: pct(m.at) }}
          title={`${fmtClock(m.at)} ${m.label}`} aria-label={`${fmtClock(m.at)} ${MARK_NAME[m.kind]}：${m.label}：在看板上回放到这一刻`} onClick={() => onBoard(markAt(run, m))} />
      ))}
    </div>
  )
}

export function Stream({ flow, onBoard }: { flow: RunFlow; onBoard: (e: BoardEntry) => void }) {
  const total = Math.max(1, flow.end)
  const step = STEPS.find((s) => total / s <= 8) ?? STEPS[STEPS.length - 1]
  const ticks = Array.from({ length: Math.floor(total / step) + 1 }, (_, i) => i * step)
  const of = (...kinds: FlowSegment['kind'][]) => flow.segments.filter((s) => kinds.includes(s.kind))
  const rows = flow.roles.map((r) => ({ key: r.key, name: r.title, icon: r.icon, segs: of('agent').filter((s) => s.role === r.key) })).filter((r) => r.segs.length)
  return (
    <div data-testid="it-stream">
      <div className="it-stream">
        {rows.map((r) => (
          <div key={r.key} style={{ display: 'contents' }} data-testid="it-row" data-row={r.key}>
            <span className="it-row-name"><RoleIcon role={r.icon || r.key} size={14} /> {r.name}</span>
            <Track segs={r.segs} total={total} run={flow.run} onBoard={onBoard} />
          </div>
        ))}
        <div style={{ display: 'contents' }} data-testid="it-row" data-row="person">
          <span className="it-row-name"><RoleIcon role="wait" size={14} /> 等人</span>
          <Track segs={of('gate', 'console')} total={total} run={flow.run} onBoard={onBoard} />
        </div>
        <div style={{ display: 'contents' }} data-testid="it-row" data-row="checks">
          <span className="it-row-name"><RoleIcon role="tester" size={14} /> 检查</span>
          <Track segs={of('checks', 'rerun')} total={total} run={flow.run} onBoard={onBoard} />
        </div>
        <div style={{ display: 'contents' }} data-testid="it-row" data-row="marks">
          <span className="it-row-name">时刻</span>
          <Track segs={[]} marks={flow.marks} total={total} run={flow.run} onBoard={onBoard} />
        </div>
        <span />
        <div className="it-axis" aria-hidden="true">
          {ticks.map((t) => <span key={t} style={{ left: `${(t / total) * 100}%` }}>{fmtClock(t)}</span>)}
        </div>
      </div>
      <ul className="it-legend" aria-label="图例">
        {(Object.keys(KIND_NAME) as FlowSegment['kind'][]).map((k) => <li key={k} className={`k-${k}`}><i />{KIND_NAME[k]}</li>)}
        <li>斜纹：还在进行；红框：退回、不过、拒绝、超时或重跑结果不同</li>
      </ul>
    </div>
  )
}

export function ItemView({ run, onBoard, pollMs = ITEM_POLL_MS }: { run: string; onBoard: (e: BoardEntry) => void; pollMs?: number }) {
  const api = useAppApi()
  const [flow, setFlow] = useState<RunFlow | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let alive = true
    let timer: ReturnType<typeof setTimeout> | undefined
    const pull = async () => {
      let again = true
      try {
        const f = await api.get<RunFlow>(paths.flow(run))
        if (!alive) return
        setFlow(f)
        setError('')
        again = f.live
      } catch (e) {
        if (alive) setError(errorText(e))
      }
      if (alive && again) timer = setTimeout(() => void pull(), pollMs)
    }
    void pull()
    return () => {
      alive = false
      clearTimeout(timer)
    }
  }, [api, run, pollMs])
  const t = flow?.totals
  return (
    <div className="kt-root cto-root it-root" data-testid="it-root">
      <style>{BOARD_CSS}</style>
      <style>{KIT_CSS}</style>
      <style>{IT_CSS}</style>
      <header className="it-head">
        <h2>交付详情</h2>
        {flow && <b>{flow.title || flow.run}</b>}
        {flow && <span className="kt-dim">{flow.run} · {runMeta(flow.status).label}{flow.signed ? ' · 已签字' : ''}</span>}
        <span className="kt-grow" />
        <button type="button" className="kt-btn" onClick={() => onBoard({ run })}>到团队看板</button>
      </header>
      <p className="kt-dim">每一段都取自运行记录、检查结果和台架的动作记录；没有记录的数空着（{EMPTY}）。点一段或一个时刻，看板就回放到那一刻。</p>
      {error && <div className="kt-banner" role="status">交付详情读不到：{error}{flow ? '，显示的是上一次拿到的数据' : ''}</div>}
      {!flow && !error && <p className="kt-loading">正在读交付详情…</p>}
      {flow && t && (
        <>
          <div className="cto-cards">
            <Card label={flow.signed ? '到签字' : flow.live ? '到现在' : '到结束'} value={fmtSpan(t.elapsed_s)} />
            <Card label="agent 在做" value={span(t.agent_s)} />
            <Card label="等人" value={span(t.person_s)} of={t.person_s === null ? undefined : `关卡 ${span(t.gate_s)} · 操作台 ${span(t.console_s)}`} />
            <Card label="跑检查" value={span(t.check_s)} />
            <Card label="credits" value={fmtCredits(t.credits)} />
            <Card label="检查轮数" value={t.check_rounds === null ? EMPTY : String(t.check_rounds)} />
            <Card label="打回" value={String(t.send_backs)} />
          </div>
          <section className="cto-card" aria-label="价值流">
            <h3>时间花在哪</h3>
            {flow.segments.length || flow.marks.length ? <Stream flow={flow} onBoard={onBoard} /> : <p className="kt-dim">{EMPTY} 这次运行还没有记录下来的时间段</p>}
          </section>
        </>
      )}
    </div>
  )
}
