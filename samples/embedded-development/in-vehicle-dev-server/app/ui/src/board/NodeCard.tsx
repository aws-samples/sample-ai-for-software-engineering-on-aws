/**
 * The card a team member's node shows when the pointer rests on it: who it is and what it was given this run, what it
 * did (its own summary, its changes, the checks it answers for, its knowledge lookups) or is doing now, and the two
 * ways to look closer: 看产出 (the outputs drawer) and 在 Crew 里打开会话 (its Kiro Crew session).
 */
import { assignmentText, doingText } from '../i18n/events'
import type { Lane, RunDetail } from '../types'
import { LIVE, fmtClock, fmtCredits, laneMeta } from './format'
import { OpenSession } from './Outputs'
import { RoleIcon } from './RoleIcon'
import { t as tr } from '../i18n'

export function NodeCard({ run, lane, onOutputs }: { run: RunDetail; lane: Lane; onOutputs?: (role: string) => void }) {
  const meta = laneMeta(lane)
  const live = LIVE.has(lane.status)
  const mine = run.tests.cases.filter((c) => c.owner === lane.key)
  const passed = mine.filter((c) => c.status === 'pass').length
  const lookups = run.knowledge.hits.filter((h) => h.role === lane.key).length
  const files = lane.files.length
  const sentBack = lane.doing && lane.doing !== lane.assignment
  const did = live
    ? lane.agent?.last_tool
      ? tr('board.NodeCard.1', { p0: lane.agent.last_tool })
      : tr('board.NodeCard.2')
    : lane.summary || (lane.status === 'waiting' ? (lane.awaiting_member ? '' : tr('board.NodeCard.3')) : lane.status === 'skipped' ? tr('board.NodeCard.4') : '')
  const missing = lane.status === 'waiting' ? lane.awaiting_member : null
  return (
    <div className="kt-ncard-body">
      <p className="kt-ncard-head">
        <RoleIcon role={lane.icon || lane.key} size={16} /> <b>{lane.title}</b>
        <span className={`kt-pill tone-${meta.tone}`}>{meta.label}</span>
      </p>
      {lane.assignment && (
        <p className="kt-ncard-task">
          <span className="kt-dim">{tr('board.NodeCard.5')}</span> {assignmentText(lane)}
        </p>
      )}
      {missing && (
        <p className="kt-ncard-back">
          {tr('board.NodeCard.6')} {missing}{tr('board.NodeCard.7')} {missing}{tr('board.NodeCard.8')}
        </p>
      )}
      {sentBack && <p className="kt-ncard-back">{tr('board.NodeCard.9')}{doingText(lane)}</p>}
      {did && <p className="kt-ncard-did">{did}</p>}
      <ul className="kt-ncard-facts">
        {(lane.active_s > 0 || live) && <li>{tr('board.NodeCard.10')} {fmtClock(live && lane.agent ? lane.agent.elapsed_s : lane.active_s)}</li>}
        {lane.writable.length > 0 && files > 0 && (
          <li>
            {tr('board.NodeCard.11')} {files} {tr('board.NodeCard.12')} <span className="kt-ok">+{lane.lines.added}</span> <span className="kt-bad">−{lane.lines.removed}</span> · {lane.commits.length} {tr('board.NodeCard.13')}
          </li>
        )}
        {lane.writable.length === 0 && lane.status !== 'waiting' && <li>{tr('board.NodeCard.14')}</li>}
        {mine.length > 0 && (
          <li>
            {tr('board.NodeCard.15')} {passed}/{mine.length} {tr('board.NodeCard.16')}
          </li>
        )}
        {lookups > 0 && <li>{tr('board.NodeCard.17')} {lookups} {tr('board.NodeCard.18')}</li>}
        {lane.credits !== null && <li>{fmtCredits(lane.credits)} credits</li>}
      </ul>
      <div className="kt-ncard-actions">
        {onOutputs && lane.status !== 'waiting' && (
          <button type="button" className="kt-btn" onClick={() => onOutputs(lane.key)}>
            {tr('board.NodeCard.19')}
          </button>
        )}
        {lane.session && <OpenSession slot={lane.session} title={lane.title} />}
      </div>
    </div>
  )
}
