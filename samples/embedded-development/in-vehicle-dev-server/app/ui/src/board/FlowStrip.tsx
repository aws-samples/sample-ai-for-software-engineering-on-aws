/**
 * The flow of flow.ts as the strip above the team graph during a run (the current step highlighted, done steps
 * checked, failed or held ones marked, and one line saying who must do what next); the home page draws the flow as
 * the 人机分工 grid (DivisionGrid.tsx). The strip is the overview; the graph, the lanes, the check wall
 * and the bench panel keep the details. Also the 准备情况 checklist of the empty state (GET /readiness).
 */
import { useCallback, useEffect, useState } from 'react'
import { useAppApi } from '../api'
import type { Readiness, ReadinessItem, RunDetail } from '../types'
import { Cmd, DecideRequest, Digest } from './Bench'
import { BASE, fmtAgo } from './format'
import { WHO_LABEL, flowOf, type StepState } from './flow'
import { errorText } from './useBoard'
import { SuggestAgree, type Confirm } from './Finding'
import { ReviewRedoBox } from './ReviewRedo'
import { t as tr } from '../i18n'

const STATE_ICON: Record<StepState, string> = { todo: '', current: '●', done: '✔', failed: '✕', held: '✋' }
const STATE_LABEL: Record<StepState, string> = { todo: tr('board.FlowStrip.1'), current: tr('board.FlowStrip.2'), done: tr('board.FlowStrip.3'), failed: tr('board.FlowStrip.4'), held: tr('board.FlowStrip.5') }

/** During a run: the steps in one row, and 现在：… */
export function FlowStrip({ run, onFinding, onAgree, onRedo }: { run: RunDetail; onFinding?: () => void; onAgree?: Confirm; onRedo?: (b: { note: string; by: string }) => Promise<void> }) {
  const f = flowOf(run)
  return (
    <section className="kt-flow" aria-label={tr('board.FlowStrip.6')} data-testid="kt-flow">
      <ol className="kt-flow-row">
        {f.steps.map(({ def, state }) => (
          <li key={def.key} className={`kt-flow-cell is-${state}${def.n ? '' : ' is-gate'}`} data-step={def.key} data-state={state}
            title={tr('board.FlowStrip.7', { p0: def.title, p1: def.who.map((w) => WHO_LABEL[w]).join(' + '), p2: def.does, p3: STATE_LABEL[state] })}>
            <span className="kt-flow-mark" aria-hidden="true">{STATE_ICON[state] || (def.n ? '○' : '◆')}</span>
            <span className="kt-flow-name">{def.n ? `${def.n} ` : ''}{def.title}</span>
          </li>
        ))}
      </ol>
      {onFinding && run.tests.held && f.steps.some((s) => s.state === 'held') ? (
        <div className="kt-ready-pending" role="status" data-testid="kt-flow-held">
          <b>{tr('board.FlowStrip.8')}</b>
          <ul>
            {run.tests.held.why.split('；').filter(Boolean).map((w) => <li key={w}>{w}</li>) /* i18n-keep: the app joins the reasons with ； */}
          </ul>
          {onAgree && <SuggestAgree run={run} onConfirm={onAgree} />}
          <span className="kt-dim">{tr('board.FlowStrip.9')}</span>
          <span className="kt-start-actions">
            <button type="button" className={`kt-btn${run.tests.held.suggest?.length ? '' : ' is-solid is-primary'}`} onClick={onFinding}>{run.tests.held.suggest?.length ? tr('board.FlowStrip.10') : tr('board.FlowStrip.11')}</button>
          </span>
        </div>
      ) : onRedo && run.review_redo ? (
        <ReviewRedoBox key={run.id} run={run} onConfirm={onRedo} />
      ) : (
        <p className="kt-flow-now" data-testid="kt-flow-now"><b>{tr('board.FlowStrip.12')}</b>{f.now}</p>
      )}
    </section>
  )
}

const NEEDED: Record<ReadinessItem['needed'], string> = { start: tr('board.FlowStrip.13'), checks: tr('board.FlowStrip.14'), bench: tr('board.FlowStrip.15') }
const POLL_READY_MS = 5000
const ACTION: Record<string, string> = { deploy: tr('board.FlowStrip.16'), restart: tr('board.FlowStrip.17'), replay: tr('board.FlowStrip.18') }

function itemState(i: ReadinessItem): { icon: string; tone: string; text: string } {
  if (i.running && i.ok === null) return { icon: '…', tone: 'run', text: tr('board.FlowStrip.19') }
  if (i.ok === true) return { icon: '✔', tone: 'ok', text: tr('board.FlowStrip.20') }
  if (i.ok === false) return { icon: '✕', tone: i.needed === 'bench' ? 'warn' : 'bad', text: tr('board.FlowStrip.21') }
  return { icon: '?', tone: 'idle', text: tr('board.FlowStrip.22') }
}

export type ReadinessState = { r: Readiness | null; err: string; load: (doctor?: boolean) => Promise<void> }

/** GET /readiness, polled; the home page reads it once for the start form's summary and the checklist. */
export function useReadiness(): ReadinessState {
  const api = useAppApi()
  const [r, setR] = useState<Readiness | null>(null)
  const [err, setErr] = useState('')
  const load = useCallback(async (doctor = false) => {
    try {
      setR(await (doctor ? api.post<Readiness>(`${BASE}/readiness/doctor`, {}) : api.get<Readiness>(`${BASE}/readiness`)))
      setErr('')
    } catch (x) {
      setErr(errorText(x))
    }
  }, [api])
  useEffect(() => {
    void load()
    const t = setInterval(() => void load(), POLL_READY_MS)
    return () => clearInterval(t)
  }, [load])
  return { r, err, load }
}

/** The start form's one line: how many readiness items are ready, linking to the checklist. */
export function ReadinessSummary({ r }: { r: Readiness | null }) {
  if (!r || r.items.length === 0) return null
  const ok = r.items.filter((i) => i.ok === true).length
  const waiting = r.pending?.length ?? 0
  return (
    <a className="kt-ready-sum" href="#kt-ready" data-testid="kt-ready-sum">
      {tr('board.FlowStrip.23')}{ok}/{r.items.length} {tr('board.FlowStrip.24')}{waiting > 0 ? tr('board.FlowStrip.25', { p0: waiting }) : ''}
    </a>
  )
}

/** 准备情况: what a run needs on this Mac, each with its state and, when not ready, the command for it. */
export function ReadinessPanel({ state }: { state: ReadinessState }) {
  const { r, err, load } = state
  const [asking, setAsking] = useState(false)
  const doctor = r?.items.find((i) => i.key === 'doctor')
  const redo = async () => {
    setAsking(true)
    await load(true)
    setAsking(false)
  }
  return (
    <section className="kt-ready" id="kt-ready" aria-label={tr('board.FlowStrip.26')} data-testid="kt-ready">
      <header className="kt-ready-head">
        <h3>{tr('board.FlowStrip.26')}</h3>
        <span className="kt-dim">{tr('board.FlowStrip.27')}</span>
        {doctor && (
          <button type="button" className="kt-btn" onClick={() => void redo()} disabled={asking || doctor.running} title={tr('board.FlowStrip.28')}>
            {doctor.running ? tr('board.FlowStrip.29') : tr('board.FlowStrip.30')}
          </button>
        )}
      </header>
      {err && <p className="kt-error" role="alert">{tr('board.FlowStrip.31')}{err}</p>}
      {r?.error && <p className="kt-warn" role="status">{r.error}</p>}
      {!r && !err && <p className="kt-dim">{tr('board.FlowStrip.32')}</p>}
      {r?.pending && r.pending.length > 0 && (
        <div className="kt-ready-pending" role="status" data-testid="kt-ready-pending">
          <b>{tr('board.FlowStrip.33')} {r.pending.length} {tr('board.FlowStrip.34')}</b>
          <span className="kt-dim">{tr('board.FlowStrip.35')}</span>
          <ul>
            {r.pending.map((p) => (
              <li key={p.id} data-testid="kt-ready-request" data-id={p.id}>
                <span>
                  <b>{ACTION[p.action] ?? p.action}</b> <Digest digest={p.digest} />
                  <small className="kt-dim">
                    {' '}{p.id} · {p.requested_by}
                    {p.left_s !== null && tr('board.FlowStrip.36', { p0: Math.max(0, p.left_s) })}
                  </small>
                </span>
                <DecideRequest id={p.id} digest={p.digest} onDone={() => void load()} />
                <details className="kt-ready-cli">
                  <summary>{tr('board.FlowStrip.37')}</summary>
                  <Cmd cmd={p.approve} />
                  <Cmd cmd={p.refuse} />
                </details>
              </li>
            ))}
          </ul>
        </div>
      )}
      {r && r.items.length > 0 && (
        <ul className="kt-ready-list">
          {r.items.map((i) => {
            const st = itemState(i)
            return (
              <li key={i.key} className={`kt-ready-item tone-${st.tone}`} data-testid="kt-ready-item" data-key={i.key} data-ok={String(i.ok)}>
                <span className="kt-ready-mark" aria-label={st.text}>{st.icon}</span>
                <b>{i.label}</b>
                <span className={`kt-ready-needed${i.needed === 'bench' ? ' is-later' : ''}`}>{NEEDED[i.needed]}</span>
                <span className="kt-ready-detail">
                  {i.detail}
                  {i.age_s !== null && <small className="kt-dim">{tr('board.FlowStrip.38')}{fmtAgo(i.age_s)}{tr('board.FlowStrip.39')}{i.running ? tr('board.FlowStrip.40') : ''}{tr('board.FlowStrip.41')}</small>}
                </span>
                {i.command && <Cmd cmd={i.command} />}
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
