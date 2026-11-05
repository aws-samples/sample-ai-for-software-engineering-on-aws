/**
 * 人机分工 (division.ts): the flow's steps as columns, 人 / AI / app / 台架 as rows. On the home page each cell says what
 * that actor is to do at that step; during a run, what it did there (from the 审计记录), the current step highlighted,
 * and a click on a cell shows that step and actor in the 审计记录 panel.
 */
import type { AuditActor, AuditTrail } from '../types'
import { ACTOR_LABEL, ActorChip, type AuditPick } from './Audit'
import { divisionOf, plannedOf, ROWS } from './division'
import { FLOW, type FlowKey } from './flow'
import { locale, t as tr } from '../i18n'

const hm = (t: number) => new Date(t * 1000).toLocaleTimeString(locale(), { hour: '2-digit', minute: '2-digit', hour12: false })

function Head() {
  return (
    <thead>
      <tr>
        <th scope="col"><span className="kt-sr">{tr('board.DivisionGrid.1')}</span></th>
        {FLOW.map((s) => (
          <th key={s.key} scope="col" className={s.n ? '' : 'is-gate'} data-step={s.key}>
            <span className="kt-flow-n">{s.n || '◆'}</span> <b>{s.title}</b>
          </th>
        ))}
      </tr>
    </thead>
  )
}

/** The home page's flow: who is to do what at each step. */
export function FlowSteps() {
  return (
    <div className="kt-div-wrap">
      <table className="kt-div" aria-label={tr('board.DivisionGrid.2')} data-testid="kt-flow-steps">
        <Head />
        <tbody>
          {ROWS.map((a) => (
            <tr key={a} data-actor={a}>
              <th scope="row"><ActorChip actor={a} /></th>
              {FLOW.map((s) => {
                const text = plannedOf(s, a)
                return <td key={s.key} className={text ? '' : 'is-empty'} data-step={s.key}>{text}</td>
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** During a run: what each actor did at each step, from the trail. */
export function DivisionView({ trail, current, onPick }: { trail: AuditTrail | null; current: FlowKey | null; onPick: (p: AuditPick) => void }) {
  const cells = divisionOf(trail?.entries ?? [])
  return (
    <details className="kt-card kt-div-card" data-testid="kt-division" open>
      <summary className="kt-card-head">
        <h2>{tr('board.DivisionGrid.3')}</h2>
        <span className="kt-dim">{tr('board.DivisionGrid.4')}</span>
      </summary>
      <div className="kt-div-wrap">
        <table className="kt-div">
          <Head />
          <tbody>
            {ROWS.map((a: AuditActor) => (
              <tr key={a} data-actor={a}>
                <th scope="row"><ActorChip actor={a} /></th>
                {FLOW.map((s) => {
                  const c = cells[s.key][a]
                  const cls = `${c.count ? '' : 'is-empty'}${s.key === current ? ' is-current' : ''}`
                  return (
                    <td key={s.key} className={cls} data-step={s.key} data-count={c.count}>
                      {c.count > 0 && (
                        <button type="button" className="kt-div-cell" onClick={() => onPick({ step: s.key, actor: a, n: Date.now() })}
                          title={tr('board.DivisionGrid.5', { p0: s.title, p1: ACTOR_LABEL[a] })}>
                          <b>{c.count} {tr('board.DivisionGrid.6')}</b>
                          <small className="kt-dim">{c.first === c.last ? hm(c.first!) : `${hm(c.first!)}–${hm(c.last!)}`}</small>
                          {c.notes.map((n) => <span key={n} className="kt-div-note">{n}</span>)}
                          {c.lines.map((l, i) => <span key={i} className="kt-div-line">{l}</span>)}
                        </button>
                      )}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  )
}
