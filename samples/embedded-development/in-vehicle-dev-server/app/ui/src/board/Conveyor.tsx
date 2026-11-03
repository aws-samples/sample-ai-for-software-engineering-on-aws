/**
 * The merge conveyor: every merge into the run branch in order (oldest first, the newest next to the
 * branch's head), a conflict red with the paths that clashed, and the roles that are done but not
 * merged yet waiting at the end of the belt. A merge that is new since the previous poll slides in.
 */
import { useEffect, useRef, useState } from 'react'
import type { RunDetail } from '../types'
import { mergeKey } from './diff'
import { fmtAgo } from './format'
import { useServerNow } from './hooks'
import { RoleIcon } from './RoleIcon'

export interface ConveyorProps {
  run: RunDetail
  fresh: ReadonlySet<string>
  focus: string | null
  onRole: (key: string) => void
}

export function Conveyor({ run, fresh, focus, onRole }: ConveyorProps) {
  const now = useServerNow()
  const byKey = new Map(run.roles.map((l) => [l.key, l]))
  const pending = run.roles.filter((l) => l.status === 'done' && l.writable.length > 0)
  const conflicts = run.merges.filter((m) => m.status === 'conflict').length
  const belt = useRef<HTMLOListElement | null>(null)
  const [older, setOlder] = useState(false)
  // the newest merges sit next to the head: keep that end in view when the belt is wider than the card
  useEffect(() => {
    const el = belt.current
    if (!el) return
    el.scrollLeft = el.scrollWidth
    setOlder(el.scrollLeft > 4)
  }, [run.merges.length, pending.length])
  return (
    <section className="kt-card kt-conveyor" data-testid="kt-conveyor" aria-label="合并传送带">
      <header className="kt-card-head">
        <h2>合并传送带</h2>
        <span className="kt-dim">
          {run.merges.filter((m) => m.status === 'merged').length} 次合入{conflicts ? ` · ` : ''}
          {conflicts ? <span className="tone-bad">{conflicts} 次冲突</span> : null}
        </span>
      </header>
      <ol className={`kt-belt${older ? ' has-older' : ''}`} ref={belt} onScroll={(e) => setOlder(e.currentTarget.scrollLeft > 4)}>
        <li className="kt-belt-end is-base" title="每个角色都从这个提交开分支">
          基线 <code>{run.base}</code>
        </li>
        {run.merges.map((m) => {
          const lane = byKey.get(m.role)
          const key = mergeKey(m)
          return (
            <li key={key} className={`kt-belt-chip is-${m.status}${fresh.has(key) ? ' is-new' : ''}${focus && focus !== m.role ? ' is-dim' : ''}`}>
              <button type="button" className="kt-belt-role" onClick={() => onRole(m.role)} title={`只看${lane?.title ?? m.role}`}>
                {lane && <RoleIcon role={lane.icon || lane.key} size={14} />} {lane?.title ?? m.role}
              </button>
              <span className="kt-belt-meta">
                <code>{m.sha}</code> · {m.files} 文件 · {fmtAgo(now - m.at)}
              </span>
              {m.status === 'conflict' && (
                <span className="kt-belt-note">
                  ⚡ 冲突：<code>{m.note ?? '没有给出路径'}</code>
                </span>
              )}
            </li>
          )
        })}
        {pending.map((l) => (
          <li key={`pending-${l.key}`} className={`kt-belt-chip is-pending${focus && focus !== l.key ? ' is-dim' : ''}`}>
            <button type="button" className="kt-belt-role" onClick={() => onRole(l.key)}>
              <RoleIcon role={l.icon || l.key} size={14} /> {l.title}
            </button>
            <span className="kt-belt-meta">完成 · 待合并</span>
          </li>
        ))}
        <li className="kt-belt-end is-head" title="运行分支：各角色的分支依次合进来，app 在这里跑测试">
          <code>{run.branch}</code>
        </li>
      </ol>
    </section>
  )
}
