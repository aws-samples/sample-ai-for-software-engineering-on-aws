/**
 * The event feed: newest first, an icon per kind, the role chips (click one to look at that role
 * only, everywhere on the board), the relative time. Events that are new since the previous poll slide
 * in. Tool calls are many and quiet; they can be hidden.
 */
import { useState } from 'react'
import type { Lane, RunDetail, TeamEvent } from '../types'
import { EVENT_META, eventTouches, fmtAgo } from './format'
import { useServerNow } from './hooks'
import { RoleIcon } from './RoleIcon'

export interface EventFeedProps {
  run: RunDetail
  focus: string | null
  onRole: (key: string) => void
  fresh: ReadonlySet<number>
  /** Projection: only the milestones a room can follow (no tool calls, commits or raw commands). */
  milestones?: boolean
}

/** The events worth telling a room: the flow, the gates and what they caught. */
const MILESTONES = new Set(['run', 'spawned', 'handoff', 'merged', 'tests', 'bounce', 'review', 'gate', 'approved', 'ownership', 'skipped', 'failed', 'conflict'])

export function EventFeed({ run, focus, onRole, fresh, milestones = false }: EventFeedProps) {
  const now = useServerNow()
  const [tools, setTools] = useState(true)
  const byKey = new Map(run.roles.map((l) => [l.key, l]))
  const shown = run.events
    .slice()
    .reverse()
    .filter((e) => (milestones ? MILESTONES.has(e.kind) : tools || e.kind !== 'tool') && (!focus || eventTouches(e, focus)))
  const focused = focus ? byKey.get(focus) : undefined
  return (
    <section className="kt-card kt-feed" data-testid="kt-feed" aria-label="事件">
      <header className="kt-card-head">
        <h2>事件</h2>
        {focused && (
          <button type="button" className="kt-filter" onClick={() => onRole(focused.key)} aria-label={`不再只看${focused.title}`}>
            只看 <RoleIcon role={focused.icon || focused.key} size={14} /> {focused.title} ✕
          </button>
        )}
        <label className="kt-check">
          <input type="checkbox" checked={tools} onChange={(e) => setTools(e.target.checked)} />
          工具调用
        </label>
      </header>
      <ol className="kt-feed-list">
        {shown.length === 0 && <li className="kt-dim kt-feed-empty">{focus ? '这个角色还没有事件' : '还没有事件'}</li>}
        {shown.map((e) => {
          const meta = EVENT_META[e.kind] ?? { icon: '•', label: e.kind, tone: 'idle' }
          return (
            <li key={e.seq} className={`kt-ev is-${e.kind} tone-${meta.tone}${fresh.has(e.seq) ? ' is-new' : ''}`} data-seq={e.seq}>
              <span className="kt-ev-icon" aria-hidden="true" title={meta.label}>
                {meta.icon}
              </span>
              <span className="kt-ev-text">{e.text}</span>
              <RoleChips e={e} byKey={byKey} onRole={onRole} />
              <time className="kt-ev-time" dateTime={new Date(e.at * 1000).toISOString()}>
                {fmtAgo(now - e.at)}
              </time>
            </li>
          )
        })}
      </ol>
    </section>
  )
}

function RoleChips({ e, byKey, onRole }: { e: TeamEvent; byKey: Map<string, Lane>; onRole: (k: string) => void }) {
  const chip = (k: string | null) => {
    const l = k ? byKey.get(k) : undefined
    if (!l) return null
    return (
      <button key={l.key} type="button" className="kt-ev-role" onClick={() => onRole(l.key)} title={`只看${l.title}`} aria-label={`只看${l.title}`}>
        <RoleIcon role={l.icon || l.key} size={15} />
      </button>
    )
  }
  if (e.kind === 'handoff' && e.from && e.to && byKey.has(e.from) && byKey.has(e.to)) {
    return (
      <span className="kt-ev-roles">
        {chip(e.from)}
        <span aria-hidden="true">→</span>
        {chip(e.to)}
      </span>
    )
  }
  const k = e.role ?? (e.from && byKey.has(e.from) ? e.from : e.to && byKey.has(e.to) ? e.to : null)
  return <span className="kt-ev-roles">{chip(k)}</span>
}
