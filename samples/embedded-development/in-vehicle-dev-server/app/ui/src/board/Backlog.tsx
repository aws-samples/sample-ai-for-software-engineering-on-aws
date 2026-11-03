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

type Filter = 'all' | 'fix' | 'later'
const FILTERS: ReadonlyArray<[Filter, string]> = [['all', '全部'], ['fix', 'fix'], ['later', 'later']]
const NONE = '—'

export function BacklogTable({ rows }: { rows: BacklogRow[] }) {
  const [filter, setFilter] = useState<Filter>('all')
  const count = (f: Filter) => (f === 'all' ? rows.length : rows.filter((r) => r.label === f).length)
  const shown = filter === 'all' ? rows : rows.filter((r) => r.label === filter)
  return (
    <div className="kt-reqs-backlog">
      <div className="kt-reqs-filter" role="group" aria-label="按标注筛选">
        {FILTERS.map(([f, label]) => (
          <button key={f} type="button" className="kt-btn" aria-pressed={filter === f} onClick={() => setFilter(f)}>
            {label} {count(f)}
          </button>
        ))}
      </div>
      <div className="kt-reqs-scroll">
        <table className="kt-reqs-table" data-testid="kt-backlog-table">
          <thead>
            <tr><th>编号</th><th>工具</th><th>检查</th><th>位置</th><th>说明</th><th>标注</th></tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.id} data-testid="kt-backlog-row" data-id={r.id} className={`is-${r.label}`}>
                <td className="kt-mono">{r.id}</td>
                <td>{r.tool}</td>
                <td className="kt-mono">{r.check}</td>
                <td className="kt-mono">{r.location}</td>
                <td>{r.message}</td>
                <td><span className={`kt-reqs-label is-${r.label}`}>{r.label}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function refactorNote(nextId: string): string {
  return `分诊还会按 TR §4.4 把本批的重构（拆分 Service::run()）加成下一个空号${nextId ? ` ${nextId}` : ''}，决定 fix。`
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
    <section className="kt-ready kt-reqs" aria-label="需求清单" data-testid="kt-reqs-home">
      <header className="kt-ready-head">
        <h3>需求清单</h3>
        <span className="kt-dim">工作项和静态分析待办（findings-backlog.md）：标 fix 的进本批，每条在分诊里定修、说明或延后。</span>
      </header>
      {err && <p className="kt-error" role="alert">需求清单读不到：{err}</p>}
      {b?.error && <p className="kt-warn" role="status">{b.error}</p>}
      {!b && !err && <p className="kt-dim">正在读…</p>}
      {b && !b.error && (
        <>
          <p className="kt-reqs-work" data-testid="kt-work-item"><b>工作项：</b>{b.work_item || NONE}</p>
          <BacklogTable rows={b.rows} />
          <p className="kt-dim" data-testid="kt-reqs-note">{refactorNote(b.next_id)}</p>
        </>
      )}
    </section>
  )
}

const STATIC: Record<string, string> = { reported: '还在报', gone: '已消失', new: '新发现' }
const DECISION: Record<string, string> = { fix: '修复', justify: '说明', defer: '延后' }

function staticText(s: string | null): string {
  if (s === null || s === '') return NONE
  return STATIC[s] ?? s
}

function traceText(t: string[] | null): string {
  if (t === null) return NONE
  return t.length ? t.join(' ') : '没有提交引用'
}

function TriageTable({ rows, backlog }: { rows: TriageRow[]; backlog: Map<string, BacklogRow> }) {
  return (
    <div className="kt-reqs-scroll">
      <table className="kt-reqs-table" data-testid="kt-triage-table">
        <thead>
          <tr><th>发现</th><th>决定</th><th>引用</th><th>证据</th><th>行为</th><th>关卡上的回答</th><th>静态分析</th><th>追溯（提交）</th></tr>
        </thead>
        <tbody>
          {rows.map((f) => {
            const row = backlog.get(f.id)
            return (
              <tr key={f.id} data-testid="kt-triage-row" data-id={f.id} className={`is-${f.decision}`}>
                <td>
                  <b className="kt-mono">{f.id}</b>
                  <small className="kt-dim">{f.added ? ' TR §4.4 新加' : row ? ` ${row.location}` : ''}</small>
                </td>
                <td><span className={`kt-reqs-label is-${f.decision}`}>{DECISION[f.decision] ?? f.decision}</span></td>
                <td className="kt-mono">{[...f.cites, ...f.facts].join(' ') || NONE}</td>
                <td>{f.evidence ?? NONE}</td>
                <td>{f.behaviour === null ? NONE : f.behaviour ? '涉及' : '不涉及'}</td>
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

/** 需求清单 on the board, beside the knowledge panel. */
export function BacklogPanel({ run }: { run: RunDetail }) {
  const b = run.backlog
  if (!b) return null
  const t = b.triage
  const fix = b.rows.filter((r) => r.label === 'fix').length
  return (
    <section className="kt-card kt-reqs" aria-label="需求清单" data-testid="kt-reqs">
      <header className="kt-card-head">
        <h2>需求清单</h2>
        <span className="kt-dim" data-testid="kt-reqs-state">
          {!t
            ? `还没有分诊：待办 ${b.rows.length} 条，${fix} 条标了 fix`
            : t.state === 'approved'
              ? `分诊已批准${t.approved ? `（${t.approved.by}，${t.approved.at}）` : ''} · ${t.findings.length} 条`
              : `分诊的建议，等分诊关卡 · ${t.findings.length} 条`}
        </span>
      </header>
      {t ? (
        <TriageTable rows={t.findings} backlog={new Map(b.rows.map((r) => [r.id, r]))} />
      ) : (
        <>
          <BacklogTable rows={b.rows} />
          <p className="kt-dim">{refactorNote(b.next_id)}</p>
        </>
      )}
    </section>
  )
}
