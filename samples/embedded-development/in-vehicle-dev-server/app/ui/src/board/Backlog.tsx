/**
 * 需求清单: on the home page the work item and the findings backlog (GET /backlog), filtered by label; on the board the
 * backlog until the triage exists, then one row per finding of the triage with what the app recorded of it: the
 * person's answer at the triage gate, the latest static result's status and the commits the latest trace result
 * counts. What the app has no record of shows as —.
 */
import { useCallback, useEffect, useState } from 'react'
import { useAppApi } from '@kirocrew/app-sdk'
import type { BacklogIndex, BacklogRow, RunDetail, TriageRow } from '../types'
import { BASE } from './format'
import { errorText } from './useBoard'
import { t as tr } from '../i18n'

type Filter = 'all' | 'fix' | 'later'
const FILTERS: ReadonlyArray<[Filter, string]> = [['all', tr('board.Backlog.1')], ['fix', 'fix'], ['later', 'later']]
const NONE = '—'

export function BacklogTable({ rows }: { rows: BacklogRow[] }) {
  const [filter, setFilter] = useState<Filter>('all')
  const count = (f: Filter) => (f === 'all' ? rows.length : rows.filter((r) => r.label === f).length)
  const shown = filter === 'all' ? rows : rows.filter((r) => r.label === filter)
  return (
    <div className="kt-reqs-backlog">
      <div className="kt-reqs-filter" role="group" aria-label={tr('board.Backlog.2')}>
        {FILTERS.map(([f, label]) => (
          <button key={f} type="button" className="kt-btn" aria-pressed={filter === f} onClick={() => setFilter(f)}>
            {label} {count(f)}
          </button>
        ))}
      </div>
      <div className="kt-reqs-scroll">
        <table className="kt-reqs-table" data-testid="kt-backlog-table">
          <thead>
            <tr><th>{tr('board.Backlog.3')}</th><th>{tr('board.Backlog.4')}</th><th>{tr('board.Backlog.5')}</th><th>{tr('board.Backlog.6')}</th><th>{tr('board.Backlog.7')}</th><th>{tr('board.Backlog.8')}</th></tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.id} data-testid="kt-backlog-row" data-id={r.id} className={`is-${r.label}`}>
                <td className="kt-mono is-nowrap">{r.id}</td>
                <td className="is-nowrap">{r.tool}</td>
                <td className="kt-mono is-nowrap">{r.check}</td>
                <td className="kt-mono is-clip" title={r.location}>{r.location}</td>
                <td className="is-clip" title={r.message}>{r.message}</td>
                <td className="is-nowrap"><span className={`kt-reqs-label is-${r.label}`}>{r.label}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

/** 30 条（fix 22 / later 8） */
export function countText(rows: BacklogRow[]): string {
  const by = (l: string) => rows.filter((r) => r.label === l).length
  return tr('board.Backlog.9', { p0: rows.length, p1: by('fix'), p2: by('later') })
}

function refactorNote(nextId: string): string {
  return tr('board.Backlog.10', { p0: nextId ? ` ${nextId}` : '' })
}

/** 需求清单 on the home page. */
export function BacklogHome() {
  const api = useAppApi()
  const [b, setB] = useState<BacklogIndex | null>(null)
  const [err, setErr] = useState('')
  const load = useCallback(async () => {
    try {
      setB(await api.get<BacklogIndex>(`${BASE}/backlog`))
      setErr('')
    } catch (x) {
      setErr(errorText(x))
    }
  }, [api])
  useEffect(() => {
    void load()
  }, [load])
  return (
    <details className="kt-ready kt-reqs kt-fold" aria-label={tr('board.Backlog.11')} data-testid="kt-reqs-home">
      <summary data-testid="kt-reqs-sum">
        <h3>{tr('board.Backlog.11')}</h3>
        {b && !b.error && <span className="kt-dim">{countText(b.rows)}</span>}
      </summary>
      <div className="kt-fold-body">
      <p className="kt-dim">{tr('board.Backlog.12')}</p>
      {err && <p className="kt-error" role="alert">{tr('board.Backlog.13')}{err}</p>}
      {b?.error && <p className="kt-warn" role="status">{b.error}</p>}
      {!b && !err && <p className="kt-dim">{tr('board.Backlog.14')}</p>}
      {b && !b.error && (
        <>
          <p className="kt-reqs-work" data-testid="kt-work-item"><b>{tr('board.Backlog.15')}</b>{b.work_item || NONE}</p>
          <BacklogTable rows={b.rows} />
          <p className="kt-dim" data-testid="kt-reqs-note">{refactorNote(b.next_id)}</p>
        </>
      )}
      </div>
    </details>
  )
}

const STATIC: Record<string, string> = { reported: tr('board.Backlog.16'), gone: tr('board.Backlog.17'), new: tr('board.Backlog.18') }
const DECISION: Record<string, string> = { fix: tr('board.Backlog.19'), justify: tr('board.Backlog.7'), defer: tr('board.Backlog.20') }

function staticText(s: string | null): string {
  if (s === null || s === '') return NONE
  return STATIC[s] ?? s
}

function traceText(t: string[] | null): string {
  if (t === null) return NONE
  return t.length ? t.join(' ') : tr('board.Backlog.21')
}

function TriageTable({ rows, backlog }: { rows: TriageRow[]; backlog: Map<string, BacklogRow> }) {
  return (
    <div className="kt-reqs-scroll">
      <table className="kt-reqs-table" data-testid="kt-triage-table">
        <thead>
          <tr><th>{tr('board.Backlog.22')}</th><th>{tr('board.Backlog.23')}</th><th>{tr('board.Backlog.24')}</th><th>{tr('board.Backlog.25')}</th><th>{tr('board.Backlog.26')}</th><th>{tr('board.Backlog.27')}</th><th>{tr('board.Backlog.28')}</th><th>{tr('board.Backlog.29')}</th></tr>
        </thead>
        <tbody>
          {rows.map((f) => {
            const row = backlog.get(f.id)
            return (
              <tr key={f.id} data-testid="kt-triage-row" data-id={f.id} className={`is-${f.decision}`}>
                <td>
                  <b className="kt-mono">{f.id}</b>
                  <small className="kt-dim">{f.added ? tr('board.Backlog.30') : row ? ` ${row.location}` : ''}</small>
                </td>
                <td><span className={`kt-reqs-label is-${f.decision}`}>{DECISION[f.decision] ?? f.decision}</span></td>
                <td className="kt-mono">{[...f.cites, ...f.facts].join(' ') || NONE}</td>
                <td>{f.evidence ?? NONE}</td>
                <td>{f.behaviour === null ? NONE : f.behaviour ? tr('board.Backlog.31') : tr('board.Backlog.32')}</td>
                <td>{f.answer ?? NONE}</td>
                <td>{staticText(f.static)}</td>
                <td className="kt-mono">{traceText(f.trace)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

/** 需求清单 on the board, folded unless the triage waits at its gate. */
export function BacklogPanel({ run }: { run: RunDetail }) {
  const b = run.backlog
  if (!b) return null
  const t = b.triage
  const fix = b.rows.filter((r) => r.label === 'fix').length
  return (
    <details className="kt-card kt-reqs kt-fold" aria-label={tr('board.Backlog.11')} data-testid="kt-reqs" open={t?.state === 'proposed'}>
      <summary className="kt-card-head">
        <h2>{tr('board.Backlog.11')}</h2>
        <span className="kt-dim" data-testid="kt-reqs-state">
          {!t
            ? tr('board.Backlog.33', { p0: b.rows.length, p1: fix })
            : t.state === 'approved'
              ? tr('board.Backlog.34', { p0: t.approved ? tr('board.Backlog.approvedBy', { p0: t.approved.by, p1: t.approved.at }) : '', p1: t.findings.length })
              : tr('board.Backlog.35', { p0: t.findings.length })}
        </span>
      </summary>
      {t ? (
        <TriageTable rows={t.findings} backlog={new Map(b.rows.map((r) => [r.id, r]))} />
      ) : (
        <>
          <BacklogTable rows={b.rows} />
          <p className="kt-dim">{refactorNote(b.next_id)}</p>
        </>
      )}
    </details>
  )
}
