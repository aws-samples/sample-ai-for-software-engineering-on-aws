/**
 * 审计记录 (D14): every decision and action of a run, as GET /runs/<id>/audit gives it (backend/team/audit.py, from the
 * run's events and the bench's action record only), filtered by who acted and by step, with the Markdown and JSON
 * downloads; and, on the home page, the bench actions that belong to no run (GET /audit/bench), so an approval of the
 * baseline made on the board is seen too. A decision made on the board (DecideRequest) refreshes both.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useAppApi } from '@kirocrew/app-sdk'
import type { AuditActor, AuditEntry, AuditTrail } from '../types'
import { FLOW } from './flow'
import { BASE } from './format'
import { errorText } from './useBoard'

export const ACTOR_LABEL: Record<AuditActor, string> = { person: '人', agent: 'AI', app: 'app', bench: '台架' }
const ACTORS: AuditActor[] = ['person', 'agent', 'app', 'bench']
const REFRESH = 'kt-audit-refresh'
const STEP_TITLE: Record<string, string> = Object.fromEntries(FLOW.map((s) => [s.key, `${s.n ? `${s.n} ` : ''}${s.title}`]))

/** Tell the audit lists a bench decision was just recorded. */
export function auditChanged(): void {
  window.dispatchEvent(new Event(REFRESH))
}

/** The trail at *path* (null: none), read again when *key* changes and after a decision on the board. */
export function useAudit(path: string | null, key: unknown): { trail: AuditTrail | null; err: string } {
  const api = useAppApi()
  const [trail, setTrail] = useState<AuditTrail | null>(null)
  const [err, setErr] = useState('')
  const load = useCallback(async () => {
    if (!path) return
    try {
      setTrail(await api.get<AuditTrail>(path))
      setErr('')
    } catch (x) {
      setErr(errorText(x))
    }
  }, [api, path])
  useEffect(() => {
    void load()
  }, [load, key])
  useEffect(() => {
    const on = () => void load()
    window.addEventListener(REFRESH, on)
    return () => window.removeEventListener(REFRESH, on)
  }, [load])
  return { trail, err }
}

export function ActorChip({ actor }: { actor: AuditActor }) {
  return <i className={`kt-actor is-${actor}`} data-actor={actor}>{ACTOR_LABEL[actor]}</i>
}

function Rows({ entries }: { entries: AuditEntry[] }) {
  return (
    <ol className="kt-audit-list">
      {entries.map((x, i) => (
        <li key={`${x.at}-${i}`} className="kt-audit-row" data-testid="kt-audit-row" data-actor={x.actor} data-step={x.step}>
          <time dateTime={x.iso} title={x.iso}>{new Date(x.at * 1000).toLocaleString('zh-CN', { hour12: false })}</time>
          <ActorChip actor={x.actor} />
          <span className="kt-audit-who">{x.who || '—'}</span>
          <span className="kt-audit-step">{STEP_TITLE[x.step] ?? '—'}</span>
          <span className="kt-audit-what">{x.what}</span>
          <code className="kt-audit-ev">{x.evidence || '—'}</code>
        </li>
      ))}
    </ol>
  )
}

/** A step and/or actor picked elsewhere (the 人机分工 grid); *n* changes on every pick. */
export type AuditPick = { step: string | null; actor: AuditActor | null; n: number }

function Downloads({ path, name, trail }: { path: string; name: string; trail: AuditTrail }) {
  const api = useAppApi()
  const [err, setErr] = useState('')
  const save = async (fmt: 'md' | 'json') => {
    try {
      const body = api.raw ? await (await api.raw(`${path}?format=${fmt}`)).text() : JSON.stringify(trail, null, 2)
      const a = document.createElement('a')
      a.href = URL.createObjectURL(new Blob([body], { type: fmt === 'md' ? 'text/markdown' : 'application/json' }))
      a.download = `${name}.${fmt}`
      a.click()
      URL.revokeObjectURL(a.href)
      setErr('')
    } catch (x) {
      setErr(errorText(x))
    }
  }
  return (
    <span className="kt-audit-dl">
      下载审计记录（
      <button type="button" className="kt-out-btn" disabled={!api.raw} title={api.raw ? '' : '这个 Kiro Crew 版本下载不了 Markdown'} onClick={() => void save('md')}>Markdown</button>
      {' / '}
      <button type="button" className="kt-out-btn" onClick={() => void save('json')}>JSON</button>）
      {err && <span className="kt-error" role="alert">{err}</span>}
    </span>
  )
}

/** The run's 审计记录 panel: open by default once the run has ended. */
export function AuditPanel({ runId, ended, trail, err, pick }: { runId: string; ended: boolean; trail: AuditTrail | null; err: string; pick?: AuditPick | null }) {
  const [actor, setActor] = useState<AuditActor | null>(null)
  const [step, setStep] = useState<string | null>(null)
  const [open, setOpen] = useState(ended)
  const ref = useRef<HTMLDetailsElement | null>(null)
  useEffect(() => setOpen((o) => o || ended), [ended])
  useEffect(() => {
    if (!pick) return
    setActor(pick.actor)
    setStep(pick.step)
    setOpen(true)
    ref.current?.scrollIntoView?.({ block: 'start', behavior: 'smooth' })
  }, [pick])
  const all = trail?.entries ?? []
  const shown = all.filter((x) => (!actor || x.actor === actor) && (!step || x.step === step))
  const path = `${BASE}/runs/${runId}/audit`
  return (
    <details ref={ref} className="kt-card kt-audit" data-testid="kt-audit" open={open} onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary className="kt-card-head">
        <h2>审计记录</h2>
        <span className="kt-dim">{trail ? `${all.length} 条，来自运行事件和台架动作记录` : ''}</span>
      </summary>
      <div className="kt-audit-bar">
        <span className="kt-seg" role="group" aria-label="按谁筛选">
          <button type="button" className="kt-btn is-small" aria-pressed={!actor} onClick={() => setActor(null)}>全部</button>
          {ACTORS.map((a) => (
            <button key={a} type="button" className="kt-btn is-small" aria-pressed={actor === a} onClick={() => setActor(a)}>{ACTOR_LABEL[a]}</button>
          ))}
        </span>
        {step && (
          <button type="button" className="kt-filter" onClick={() => setStep(null)} aria-label="不再只看这一步">只看 {STEP_TITLE[step] ?? step} ✕</button>
        )}
        {trail && <Downloads path={path} name={`audit-${runId}`} trail={trail} />}
      </div>
      {err && <p className="kt-error" role="alert">审计记录读不到：{err}</p>}
      {!trail && !err && <p className="kt-dim">正在读…</p>}
      {trail && shown.length === 0 && <p className="kt-dim">没有这样的记录</p>}
      {shown.length > 0 && <Rows entries={shown} />}
    </details>
  )
}

/** Home page: the bench actions no run made (the baseline set up at the console or on the board), newest first. */
export function BenchAudit() {
  const { trail, err } = useAudit(`${BASE}/audit/bench`, null)
  const entries = (trail?.entries ?? []).slice().reverse()
  return (
    <section className="kt-audit-bench" data-testid="kt-audit-bench" aria-label="台架动作记录">
      <h4>台架动作记录（不属于任何运行）</h4>
      {err && <p className="kt-error" role="alert">读不到：{err}</p>}
      {trail && entries.length === 0 && <p className="kt-dim">还没有</p>}
      {entries.length > 0 && <Rows entries={entries} />}
    </section>
  )
}
