/**
 * 人机分工: the steps of flow.ts against who acts (人, AI, app, 台架). For the home page, what each is to do at each
 * step (flow.ts's who and does); for a run, what each did there, from its 审计记录 entries only (counts, times, the
 * latest lines and figures read from the entries' evidence). Pure: no React.
 */
import type { AuditActor, AuditEntry } from '../types'
import { FLOW, type FlowKey, type FlowStepDef } from './flow'

export const ROWS: AuditActor[] = ['person', 'agent', 'app', 'bench']

/** What *who* is to do at *def*: a step two actors share has its `does` in two parts, one each (；). */
export function plannedOf(def: FlowStepDef, who: AuditActor): string {
  const at = def.who.indexOf(who)
  if (at < 0) return ''
  const parts = def.does.split('；')
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
    const differ = ev.match(/与建议不同/g)?.length ?? 0
    if (answers) out.push(`逐题回答 ${answers} 题${differ ? `，${differ} 题改了建议` : ''}`)
    if (rows[0]?.step === 'bench') { // a bench decision says where it was made in its who
      const board = rows.filter((r) => r.who.includes('Kiro Crew 看板')).length
      if (board) out.push(`看板上决定 ${board} 次`)
      if (rows.length > board) out.push(`操作台上决定 ${rows.length - board} 次`)
    }
  } else if (actor === 'agent') {
    const cites = ev.match(/\b(?:F-\d{3}|VSTATD-[A-Z]+[-\w.]*)/g)?.length ?? 0
    if (cites) out.push(`引用发现或规范 ${cites} 次`)
  } else if (actor === 'app') {
    const rounds = rows.filter((r) => /=(?:FAIL|fail|BLOCKED)\b/.test(r.evidence)).length
    if (rounds) out.push(`${rounds} 轮检查有不过`)
    const commits = ev.match(/\bcommit [0-9a-f]+/g)?.length ?? 0
    if (commits) out.push(`合入 ${commits} 次`)
  } else {
    const ok = rows.filter((r) => /结果 ok/.test(r.what)).length
    if (ok) out.push(`动作完成 ${ok} 次`)
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
