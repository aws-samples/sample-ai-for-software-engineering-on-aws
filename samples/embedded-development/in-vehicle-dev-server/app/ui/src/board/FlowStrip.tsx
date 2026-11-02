/**
 * The flow of flow.ts, drawn twice: as the numbered steps of the empty state (who acts at each and what happens), and
 * as the strip above the team graph during a run (the current step highlighted, done steps checked, failed or held ones
 * marked, and one line saying who must do what next). The strip is the overview; the graph, the lanes, the check wall
 * and the bench panel keep the details. Also the 准备情况 checklist of the empty state (GET /readiness).
 */
import { useCallback, useEffect, useState } from 'react'
import { useAppApi } from '@kirocrew/app-sdk'
import type { Readiness, ReadinessItem, RunDetail } from '../types'
import { BASE, fmtAgo } from './format'
import { FLOW, WHO_LABEL, flowOf, type StepState } from './flow'
import { errorText } from './useBoard'

const STATE_ICON: Record<StepState, string> = { todo: '', current: '●', done: '✔', failed: '✕', held: '✋' }
const STATE_LABEL: Record<StepState, string> = { todo: '还没到', current: '现在在这一步', done: '做完了', failed: '没过', held: '交给人决定' }

/** The empty state's flow: every step, numbered, with who acts and what happens there. */
export function FlowSteps() {
  return (
    <ol className="kt-flow-steps" aria-label="流程" data-testid="kt-flow-steps">
      {FLOW.map((s) => (
        <li key={s.key} className={`kt-flow-step${s.n ? '' : ' is-gate'}`} data-step={s.key}>
          <span className="kt-flow-n">{s.n || '◆'}</span>
          <b>{s.title}</b>
          <span className="kt-flow-who">{s.who.map((w) => <i key={w} className={`is-${w}`}>{WHO_LABEL[w]}</i>)}</span>
          <span className="kt-flow-does">{s.does}</span>
        </li>
      ))}
    </ol>
  )
}

/** During a run: the steps in one row, and 现在：… */
export function FlowStrip({ run }: { run: RunDetail }) {
  const f = flowOf(run)
  return (
    <section className="kt-flow" aria-label="流程" data-testid="kt-flow">
      <ol className="kt-flow-row">
        {f.steps.map(({ def, state }) => (
          <li key={def.key} className={`kt-flow-cell is-${state}${def.n ? '' : ' is-gate'}`} data-step={def.key} data-state={state}
            title={`${def.title}（${def.who.map((w) => WHO_LABEL[w]).join(' + ')}）：${def.does} · ${STATE_LABEL[state]}`}>
            <span className="kt-flow-mark" aria-hidden="true">{STATE_ICON[state] || (def.n ? '○' : '◆')}</span>
            <span className="kt-flow-name">{def.n ? `${def.n} ` : ''}{def.title}</span>
          </li>
        ))}
      </ol>
      <p className="kt-flow-now" data-testid="kt-flow-now"><b>现在：</b>{f.now}</p>
    </section>
  )
}

const NEEDED: Record<ReadinessItem['needed'], string> = { start: '开始就要', checks: '测试先行起要', bench: '上台架才要' }
const POLL_READY_MS = 5000

function itemState(i: ReadinessItem): { icon: string; tone: string; text: string } {
  if (i.running && i.ok === null) return { icon: '…', tone: 'run', text: '正在查' }
  if (i.ok === true) return { icon: '✔', tone: 'ok', text: '好了' }
  if (i.ok === false) return { icon: '✕', tone: i.needed === 'bench' ? 'warn' : 'bad', text: '没好' }
  return { icon: '?', tone: 'idle', text: '看不出' }
}

/** 准备情况: what a run needs on this Mac, each with its state and, when not ready, the command for it. */
export function ReadinessPanel() {
  const api = useAppApi()
  const [r, setR] = useState<Readiness | null>(null)
  const [err, setErr] = useState('')
  const [asking, setAsking] = useState(false)
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
  const doctor = r?.items.find((i) => i.key === 'doctor')
  const redo = async () => {
    setAsking(true)
    await load(true)
    setAsking(false)
  }
  return (
    <section className="kt-ready" aria-label="准备情况" data-testid="kt-ready">
      <header className="kt-ready-head">
        <h3>准备情况</h3>
        <span className="kt-dim">台架没准备好也能先开始：运行做到台架前会停下，看板上写着缺什么和要跑的命令。</span>
        {doctor && (
          <button type="button" className="kt-btn" onClick={() => void redo()} disabled={asking || doctor.running} title="在后台重跑 bench/doctor.sh，看板不用等它">
            {doctor.running ? 'doctor.sh 在跑…' : '重跑 doctor.sh'}
          </button>
        )}
      </header>
      {err && <p className="kt-error" role="alert">准备情况读不到：{err}</p>}
      {r?.error && <p className="kt-warn" role="status">{r.error}</p>}
      {!r && !err && <p className="kt-dim">正在读…</p>}
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
                  {i.age_s !== null && <small className="kt-dim">（{fmtAgo(i.age_s)}查的{i.running ? '，正在重查' : ''}）</small>}
                </span>
                {i.command && <code className="kt-ready-cmd">{i.command}</code>}
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
