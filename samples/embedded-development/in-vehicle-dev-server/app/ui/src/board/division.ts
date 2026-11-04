/**
 * 人机分工: the steps of flow.ts against who acts (人, AI, app, 台架). For the home page, what each is to do at each
 * step (flow.ts's who and does); for a run, what each did there, from its 审计记录 entries only (counts, times, the
 * latest lines and figures read from the entries' evidence). Pure: no React.
 */
import type { AuditActor, AuditEntry } from '../types'
import { FLOW, type FlowKey, type FlowStepDef } from './flow'
import { t as tr } from '../i18n'

export const ROWS: AuditActor[] = ['person', 'agent', 'app', 'bench']

/** What *who* is to do at *def*: a step two actors share has its `does` in two parts, one each (；). */
export function plannedOf(def: FlowStepDef, who: AuditActor): string {
  const at = def.who.indexOf(who)
  if (at < 0) return ''
  const parts = def.does.split(/；|; /) // i18n-keep: the two parts of a shared step, in either language
  return def.who.length > 1 && parts.length === def.who.length ? parts[at] : def.does
}

export interface Cell {
  count: number
  first: number | null
  last: number | null
  lines: string[] // the latest entries' what, newest last (at most LINES)
  notes: string[] // figures read from the entries' evidence
}

export const LINES = 2

function notesOf(actor: AuditActor, rows: AuditEntry[]): string[] {
  const out: string[] = []
  const ev = rows.map((r) => r.evidence).join(' ')
  if (actor === 'person') {
    const answers = ev.match(/\bQ\d+=/g)?.length ?? 0
    const differ = ev.match(/与建议不同/g)?.length ?? 0 // i18n-keep: parses the backend's Chinese evidence
    if (answers) out.push(tr('board.division.1', { p0: answers, p1: differ ? tr('board.division.changed', { p0: differ }) : '' }))
    if (rows[0]?.step === 'bench') { // a bench decision says where it was made in its who
      const board = rows.filter((r) => r.who.includes('Kiro Crew 看板')).length // i18n-keep: parses the backend's Chinese who
      if (board) out.push(tr('board.division.2', { p0: board }))
      if (rows.length > board) out.push(tr('board.division.3', { p0: rows.length - board }))
    }
  } else if (actor === 'agent') {
    const cites = ev.match(/\b(?:F-\d{3}|VSTATD-[A-Z]+[-\w.]*)/g)?.length ?? 0
    if (cites) out.push(tr('board.division.4', { p0: cites }))
  } else if (actor === 'app') {
    const rounds = rows.filter((r) => /=(?:FAIL|fail|BLOCKED)\b/.test(r.evidence)).length
    if (rounds) out.push(tr('board.division.5', { p0: rounds }))
    const commits = ev.match(/\bcommit [0-9a-f]+/g)?.length ?? 0
    if (commits) out.push(tr('board.division.6', { p0: commits }))
  } else {
    const ok = rows.filter((r) => /结果 ok/.test(r.what)).length // i18n-keep: parses the backend's Chinese what
    if (ok) out.push(tr('board.division.7', { p0: ok }))
  }
  return out
}

/** Each step's cells, one per actor, from *entries* (an entry with no step is left out). */
export function divisionOf(entries: AuditEntry[]): Record<FlowKey, Record<AuditActor, Cell>> {
  const out = {} as Record<FlowKey, Record<AuditActor, Cell>>
  for (const s of FLOW) {
    out[s.key] = {} as Record<AuditActor, Cell>
    for (const a of ROWS) {
      const rows = entries.filter((e) => e.step === s.key && e.actor === a).sort((x, y) => x.at - y.at)
      out[s.key][a] = {
        count: rows.length,
        first: rows.length ? rows[0].at : null,
        last: rows.length ? rows[rows.length - 1].at : null,
        lines: rows.slice(-LINES).map((r) => r.what),
        notes: notesOf(a, rows),
      }
    }
  }
  return out
}
