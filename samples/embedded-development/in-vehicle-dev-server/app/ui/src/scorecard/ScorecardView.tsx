/**
 * 评分卡 (D8): the rehearsal scorecard of the scenario page, from `GET /scorecard` every 10 s. Only measured figures,
 * each from the runs' records (backend/team/scorecard.py); a figure no run is behind is shown empty (—), never 0. The
 * cards are the sums over the runs, the table each run, the notes at the foot say how each figure is taken and which
 * figures of the scenario page are left out. The cards and blocks are the kit's (kit.ts), as the CTO view's were.
 */
import { useEffect, useState } from 'react'
import { useAppApi } from '../api'
import { BOARD_CSS } from '../board/styles'
import { fmtSpan, paths, runMeta } from '../board/format'
import { errorText } from '../board/useBoard'
import { KIT_CSS } from '../kit'
import type { ScoreRun, Scorecard } from '../types'
import { t as tr } from '../i18n'

export const SCORE_POLL_MS = 10000

const SC_CSS = `
.sc-root .cto-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(210px, 1fr)); }
.sc-root .cto-card { margin: 0; }
.sc-head h2 { margin: 0 0 4px; font-size: 1.4em; color: var(--text-strong); }
.sc-head p { margin: 0; color: var(--muted); }
.sc-root .cto-value.is-empty { color: var(--muted); }
.sc-table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
.sc-table th, .sc-table td { text-align: left; padding: 6px 10px 6px 0; border-bottom: 1px solid var(--border); vertical-align: top; }
.sc-table th { color: var(--muted); font-weight: 650; font-size: .93em; }
.sc-wide { overflow-x: auto; }
.sc-detail { margin-top: 4px; font-size: 12px; padding: 3px 10px; }
.sc-root section.cto-card > h3 { margin: 0 0 10px; font-size: 1.1em; color: var(--text-strong); }
.sc-notes { color: var(--muted); font-size: 13px; }
.sc-notes summary { cursor: pointer; color: var(--text); }
.sc-notes ul { margin: 8px 0 0; padding-left: 18px; display: grid; gap: 4px; }
.kt-app.is-projection > .sc-root { flex: 1 1 auto; min-height: 0; overflow: auto; font-size: 18px; }
`

const EMPTY = '—'
const n = (x: number | null | undefined) => (x === null || x === undefined ? EMPTY : String(x))
const span = (x: number | null) => (x === null ? EMPTY : fmtSpan(x))
const isEmpty = (x: unknown) => x === null || x === undefined

function Card({ label, value, of, empty }: { label: string; value: string; of?: string; empty: boolean }) {
  return (
    <div className="cto-card" data-testid="sc-card">
      <div className="cto-eyebrow">{label}</div>
      <div className={`cto-value${empty ? ' is-empty' : ''}`} title={empty ? tr('scorecard.ScorecardView.1') : undefined}>
        {value}
        {of && !empty && <span className="cto-of"> {of}</span>}
      </div>
    </div>
  )
}

function caughtText(c: Record<string, number> | null): string {
  if (!c) return EMPTY
  const failed = Object.entries(c).filter(([, v]) => v > 0)
  return failed.length ? failed.map(([k, v]) => `${k} ${v}`).join(tr('scorecard.ScorecardView.2')) : '0'
}

function RunRow({ r, onDetail }: { r: ScoreRun; onDetail?: (rid: string) => void }) {
  return (
    <tr data-testid="sc-run" data-run={r.id}>
      <td>
        <b>{r.title || r.id}</b>
        <div className="kt-dim">{r.id} · {runMeta(r.status).label}{r.signed ? tr('scorecard.ScorecardView.3') : ''}</div>
        {onDetail && <button type="button" className="kt-btn sc-detail" onClick={() => onDetail(r.id)} aria-label={tr('scorecard.ScorecardView.4', { p0: r.title || r.id })}>{tr('scorecard.ScorecardView.5')}</button>}
      </td>
      <td>{r.findings ? `${r.findings.fixed} / ${r.findings.justified} / ${r.findings.deferred}` : EMPTY}</td>
      <td title={r.overturned ? tr('scorecard.ScorecardView.6', { p0: r.overturned.by_person.join(tr('common.sep')) || tr('common.none'), p1: r.overturned.by_reviewer.join(tr('common.sep')) || tr('common.none') }) : undefined}>
        {r.overturned ? (r.overturned.ids.length ? tr('scorecard.ScorecardView.7', { p0: r.overturned.ids.length, p1: r.overturned.ids.join(tr('common.sep')) }) : '0') : EMPTY}
      </td>
      <td>{span(r.times.triage_s)}</td>
      <td>{span(r.times.first_pass_s)}</td>
      <td>{span(r.times.signoff_s)}</td>
      <td>{n(r.build_rounds)}</td>
      <td>{caughtText(r.caught)}</td>
      <td>{r.logdiff ? tr('scorecard.ScorecardView.8', { p0: r.logdiff.differences, p1: r.logdiff.unexplained }) : EMPTY}</td>
      <td>{r.bench ? `${r.bench.approved} / ${r.bench.refused} / ${r.bench.reconciled}` : EMPTY}</td>
      <td>{r.rerun_differs ? (r.rerun_differs.length ? r.rerun_differs.join(tr('scorecard.ScorecardView.2')) : '0') : EMPTY}</td>
    </tr>
  )
}

export function ScorecardView({ pollMs = SCORE_POLL_MS, onDetail }: { pollMs?: number; onDetail?: (rid: string) => void }) {
  const api = useAppApi()
  const [data, setData] = useState<Scorecard | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let alive = true
    let timer: ReturnType<typeof setTimeout> | undefined
    const pull = async () => {
      try {
        const d = await api.get<Scorecard>(paths.scorecard())
        if (!alive) return
        setData(d)
        setError('')
      } catch (e) {
        if (alive) setError(errorText(e))
      }
      if (alive) timer = setTimeout(() => void pull(), pollMs)
    }
    void pull()
    return () => {
      alive = false
      clearTimeout(timer)
    }
  }, [api, pollMs])

  const t = data?.total
  const checks = t?.caught ? Object.entries(t.caught) : []
  return (
    <div className="kt-root cto-root sc-root" data-testid="sc-root">
      <style>{BOARD_CSS}</style>
      <style>{SC_CSS}</style>
      <style>{KIT_CSS}</style>
      <header className="sc-head">
        <h2>{tr('scorecard.ScorecardView.9')}</h2>
        <p>{tr('scorecard.ScorecardView.10')}{EMPTY}{tr('scorecard.ScorecardView.11')}{t ? tr('scorecard.ScorecardView.12', { p0: t.runs }) : ''}</p>
      </header>
      {error && <div className="kt-banner" role="status">{tr('scorecard.ScorecardView.13')}{error}{data ? tr('scorecard.ScorecardView.14') : ''}</div>}
      {!data && !error && <p className="kt-loading">{tr('scorecard.ScorecardView.15')}</p>}
      {t && (
        <>
          <div className="cto-cards">
            <Card label={tr('scorecard.ScorecardView.16')} value={t.findings ? `${t.findings.fixed} / ${t.findings.justified} / ${t.findings.deferred}` : EMPTY} empty={isEmpty(t.findings)} />
            <Card label={tr('scorecard.ScorecardView.17')} value={n(t.overturned)} empty={isEmpty(t.overturned)} />
            <Card label={tr('scorecard.ScorecardView.18')} value={n(t.build_rounds)} empty={isEmpty(t.build_rounds)} />
            <Card label={tr('scorecard.ScorecardView.19')} value={n(t.logdiff?.differences)} of={t.logdiff ? tr('scorecard.ScorecardView.20', { p0: t.logdiff.unexplained }) : undefined} empty={isEmpty(t.logdiff)} />
            <Card label={tr('scorecard.ScorecardView.21')} value={t.bench ? `${t.bench.approved} / ${t.bench.refused} / ${t.bench.reconciled}` : EMPTY} empty={isEmpty(t.bench)} />
            <Card label={tr('scorecard.ScorecardView.22')} value={n(t.rerun_differs)} empty={isEmpty(t.rerun_differs)} />
          </div>
          <section className="cto-card" data-testid="sc-caught">
            <h3>{tr('scorecard.ScorecardView.23')}</h3>
            {checks.length ? (
              <table className="sc-table">
                <thead><tr><th>{tr('scorecard.ScorecardView.24')}</th><th>{tr('scorecard.ScorecardView.25')}</th></tr></thead>
                <tbody>{checks.map(([k, v]) => <tr key={k}><td><code>{k}</code></td><td>{v}</td></tr>)}</tbody>
              </table>
            ) : <p className="kt-dim">{EMPTY} {tr('scorecard.ScorecardView.26')}</p>}
          </section>
          <section className="cto-card" data-testid="sc-runs">
            <h3>{tr('scorecard.ScorecardView.27')}</h3>
            {data.runs.length ? (
              <div className="sc-wide">
                <table className="sc-table">
                  <thead>
                    <tr>
                      <th>{tr('scorecard.ScorecardView.28')}</th><th>{tr('scorecard.ScorecardView.29')}</th><th>{tr('scorecard.ScorecardView.17')}</th><th>{tr('scorecard.ScorecardView.30')}</th><th>{tr('scorecard.ScorecardView.31')}</th><th>{tr('scorecard.ScorecardView.32')}</th>
                      <th>{tr('scorecard.ScorecardView.18')}</th><th>{tr('scorecard.ScorecardView.33')}</th><th>{tr('scorecard.ScorecardView.19')}</th><th>{tr('scorecard.ScorecardView.34')}</th><th>{tr('scorecard.ScorecardView.35')}</th>
                    </tr>
                  </thead>
                  <tbody>{data.runs.map((r) => <RunRow key={r.id} r={r} onDetail={onDetail} />)}</tbody>
                </table>
              </div>
            ) : <p className="kt-dim">{tr('scorecard.ScorecardView.36')}</p>}
          </section>
        </>
      )}
      <details className="sc-notes">
        <summary>{tr('scorecard.ScorecardView.37')}</summary>
        <ul>
          <li>{tr('scorecard.ScorecardView.38')}</li>
          <li>{tr('scorecard.ScorecardView.39')}</li>
          <li>{tr('scorecard.ScorecardView.40')}</li>
          <li>{tr('scorecard.ScorecardView.41')}</li>
          <li>{tr('scorecard.ScorecardView.42')}</li>
          <li>{tr('scorecard.ScorecardView.43')}</li>
          <li>{tr('scorecard.ScorecardView.44')}</li>
          <li>{tr('scorecard.ScorecardView.45')}</li>
        </ul>
      </details>
    </div>
  )
}
