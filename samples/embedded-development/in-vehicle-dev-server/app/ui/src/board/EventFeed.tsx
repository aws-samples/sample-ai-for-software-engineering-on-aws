/**
 * The event feed: newest first, an icon per kind, who acted (人 / AI / app / 台架, as the 审计记录 has it), the role chips (click one to look at that role
 * only, everywhere on the board), the relative time. Events that are new since the previous poll slide
 * in. Tool calls are many and quiet; they can be hidden.
 */
import { evText } from '../i18n/events'
import { useState } from 'react'
import type { AuditActor, Lane, RunDetail, TeamEvent } from '../types'
import { ActorChip } from './Audit'
import { EVENT_META, eventTouches, fmtAgo } from './format'
import { useServerNow } from './hooks'
import { RoleIcon } from './RoleIcon'
import { t as tr } from '../i18n'

export interface EventFeedProps {
  run: RunDetail
  focus: string | null
  onRole: (key: string) => void
  fresh: ReadonlySet<number>
  /** Projection: only the milestones a room can follow (no tool calls, commits or raw commands). */
  milestones?: boolean
  /** who acted, by event seq, from the 审计记录 (an event it does not list has no chip) */
  actors?: ReadonlyMap<number, AuditActor>
}

/** The events worth telling a room: the flow, the gates and what they caught. */
const MILESTONES = new Set(['run', 'spawned', 'handoff', 'merged', 'tests', 'bounce', 'review', 'gate', 'approved', 'ownership', 'skipped', 'failed', 'conflict'])

export function EventFeed({ run, focus, onRole, fresh, milestones = false, actors }: EventFeedProps) {
  const now = useServerNow()
  const [tools, setTools] = useState(true)
  const byKey = new Map(run.roles.map((l) => [l.key, l]))
  const shown = run.events
    .slice()
    .reverse()
    .filter((e) => (milestones ? MILESTONES.has(e.kind) : tools || e.kind !== 'tool') && (!focus || eventTouches(e, focus)))
  const focused = focus ? byKey.get(focus) : undefined
  return (
    <section className="kt-card kt-feed" data-testid="kt-feed" aria-label={tr('board.EventFeed.1')}>
      <header className="kt-card-head">
        <h2>{tr('board.EventFeed.1')}</h2>
        {focused && (
          <button type="button" className="kt-filter" onClick={() => onRole(focused.key)} aria-label={tr('board.EventFeed.2', { p0: focused.title })}>
            {tr('board.EventFeed.3')} <RoleIcon role={focused.icon || focused.key} size={14} /> {focused.title} ✕
          </button>
        )}
        <label className="kt-check">
          <input type="checkbox" checked={tools} onChange={(e) => setTools(e.target.checked)} />
          {tr('board.EventFeed.4')}
        </label>
      </header>
      <ol className="kt-feed-list">
        {shown.length === 0 && <li className="kt-dim kt-feed-empty">{focus ? tr('board.EventFeed.5') : tr('board.EventFeed.6')}</li>}
        {shown.map((e) => {
          const meta = EVENT_META[e.kind] ?? { icon: '•', label: e.kind, tone: 'idle' }
          return (
            <li key={e.seq} className={`kt-ev is-${e.kind} tone-${meta.tone}${fresh.has(e.seq) ? ' is-new' : ''}`} data-seq={e.seq}>
              <span className="kt-ev-icon" aria-hidden="true" title={meta.label}>
                {meta.icon}
              </span>
              <span className="kt-ev-text">{actors?.has(e.seq) && <ActorChip actor={actors.get(e.seq)!} />} {evText(e, run.roles)}</span>
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
      <button key={l.key} type="button" className="kt-ev-role" onClick={() => onRole(l.key)} title={tr('board.EventFeed.7', { p0: l.title })} aria-label={tr('board.EventFeed.7', { p0: l.title })}>
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
