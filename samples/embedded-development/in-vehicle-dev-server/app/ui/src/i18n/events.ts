/**
 * What the app says, by code (backend/team/messages.py): an event, a status line or a 交付详情 segment carries a
 * code and its params beside its Chinese text. In Chinese the board shows the text as the app wrote it; in English
 * it renders ev.<code> from en.json with the params. Without a code (an older run's events) it shows the text.
 *
 * The template syntax is the backend's: {name} a param, [[name|then]] / [[name|then|else]] a part shown only when the
 * param is set, r_… a role key shown as the role's name, g_… a role key shown as its gate's label, a list joined,
 * a list of objects each rendered with ev.<code>.<name>, an object with a code rendered as that message.
 */
import type { Board, Lane, Msg, MsgParams, RunFlow } from '../types'
import { has, lang, t } from './index'

export type RoleNames = ReadonlyArray<Pick<Lane, 'key' | 'title'> & { gate_label?: string }>

const OPT = /\[\[(\w+)\|([^|\]]*)(?:\|([^\]]*))?\]\]/g
const VAR = /\{(\w+)\}/g
const truthy = (v: unknown) => !(v === undefined || v === null || v === false || v === 0 || v === '' || (Array.isArray(v) && v.length === 0))

/** Message *code* with *params*, in the board's language (roles named from *roles*, already in that language). */
export function msgText(code: string, params: MsgParams | null | undefined, roles: RoleNames = []): string {
  const p = params ?? {}
  const by = new Map(roles.map((r) => [r.key, r]))
  const value = (name: string, v: unknown): string => {
    if (v && typeof v === 'object' && !Array.isArray(v) && typeof (v as Msg).code === 'string' && has(`ev.${(v as Msg).code}`))
      return msgText((v as Msg).code, (v as Msg).params, roles)
    if (Array.isArray(v)) {
      if (v.length && v.every((x) => x && typeof x === 'object')) return v.map((x) => msgText(`${code}.${name}`, x as MsgParams, roles)).join(t('ev.sep.item'))
      return v.map((x) => value(name, x)).join(t('ev.sep.list'))
    }
    if (name === 'by' || name === 'who') return person(String(v))
    if (name.startsWith('r_')) return by.get(String(v))?.title ?? String(v)
    if (name.startsWith('g_')) { const r = by.get(String(v)); return r?.gate_label || r?.title || String(v) }
    return String(v)
  }
  const template = t(`ev.${code}`).replace(OPT, (_m, name: string, then: string, otherwise?: string) => (truthy(p[name]) ? then : otherwise ?? ''))
  return template.replace(VAR, (m, name: string) => (name in p ? value(name, p[name]) : m))
}

/** A person as the records name them, with the app's own words around a name said in the board's language: 负责人
 * (no name given), 「Kiro Crew 看板（name，app）」 (a decision on the board), 「name（在 Kiro 会话里让 Kiro 代点）」. */
export function person(who: string): string {
  if (lang() === 'zh') return who
  if (who === '负责人') return t('common.owner') // i18n-keep: the app's word for no name
  const board = /^Kiro Crew 看板（(.+?)，(.+?)）$/.exec(who) // i18n-keep: bench.py DECIDED_BY
  if (board) return t('common.board', { p0: board[1], p1: board[2] })
  if (who.endsWith('（在 Kiro 会话里让 Kiro 代点）')) return who.slice(0, -'（在 Kiro 会话里让 Kiro 代点）'.length) + t('common.viaKiro') // i18n-keep: a by the retry was given
  return who
}

type Doing = { doing: string; doing_msg?: Msg | null; assignment?: string; mission?: string; mission_en?: string }

/** A role's assignment in the board's language: the team file's mission in English when it is the mission (the
 * planner's own line for this run stays as it wrote it). */
export function assignmentText(l: Doing): string {
  const a = l.assignment ?? ''
  return lang() !== 'zh' && a && a === l.mission && l.mission_en ? l.mission_en : a
}

/** What a role is on now in the board's language: its round's label by code (doing_msg), its assignment, or its words. */
export function doingText(l: Doing): string {
  if (lang() === 'zh') return l.doing
  if (l.doing_msg && has(`ev.${l.doing_msg.code}`)) return msgText(l.doing_msg.code, l.doing_msg.params)
  return l.doing === l.assignment ? assignmentText(l) : l.doing
}

/** A gate question's words (and its options') in the board's language, by code when it has one. */
export function questionText(q: { q: string; q_msg?: Msg | null }): string {
  return evText({ text: q.q, code: q.q_msg?.code, params: q.q_msg?.params })
}
export function optionText(o: { text: string; msg?: Msg | null }): string {
  return evText({ text: o.text, code: o.msg?.code, params: o.msg?.params })
}

/** An event's (or a status line's) words: its text in Chinese or without a known code, else its code rendered. */
export function evText(e: { text?: string | null; label?: string | null; code?: string | null; params?: MsgParams | null }, roles: RoleNames = []): string {
  const text = e.text ?? e.label ?? ''
  return lang() === 'zh' || !e.code || !has(`ev.${e.code}`) ? text : msgText(e.code, e.params, roles)
}

/** Why *run* cannot be signed off yet, in the board's language ('' when it can). */
export function signBlock(run: { sign_block: string; sign_block_msg?: Msg | null }): string {
  return run.sign_block_msg ? evText({ text: run.sign_block, ...run.sign_block_msg }) : run.sign_block
}

const named = <T extends { title: string; title_en?: string; gate_label?: string; gate_label_en?: string; stage?: string; stage_en?: string }>(r: T): T =>
  ({ ...r, title: r.title_en || r.title, ...(r.gate_label !== undefined ? { gate_label: r.gate_label_en || r.gate_label } : {}),
    ...(r.stage !== undefined ? { stage: r.stage_en || r.stage } : {}) })

/** The board with its roles named in the board's language (the team file's title_en, stage_en, gate_label_en). */
export function localizeBoard<B extends Board | null | undefined>(b: B): B {
  if (lang() === 'zh' || !b?.run) return b
  return { ...b, run: { ...b.run, roles: b.run.roles.map(named) } }
}

/** 交付详情 in the board's language: its roles named, its segments, results and moments said by code. */
export function localizeFlow<F extends RunFlow | null | undefined>(f: F): F {
  if (lang() === 'zh' || !f) return f
  const roles = f.roles.map(named)
  return {
    ...f, roles,
    segments: f.segments.map((s) => ({ ...s, label: evText(s, roles), result: s.result_code ? t(`ev.result.${s.result_code}`) : s.result })),
    marks: f.marks.map((m) => ({ ...m, label: evText(m, roles) })),
  }
}
