/**
 * The card a team member's node shows when the pointer rests on it: who it is and what it was given this run, what it
 * did (its own summary, its changes, the checks it answers for, its knowledge lookups) or is doing now, and the two
 * ways to look closer: 看产出 (the outputs drawer) and 在 Crew 里打开会话 (its Kiro Crew session).
 */
import type { Lane, RunDetail } from '../types'
import { LIVE, fmtClock, fmtCredits, laneMeta } from './format'
import { OpenSession } from './Outputs'
import { RoleIcon } from './RoleIcon'

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
      ? `正在：${lane.agent.last_tool}`
      : '刚开工'
    : lane.summary || (lane.status === 'waiting' ? (lane.awaiting_member ? '' : '还没轮到') : lane.status === 'skipped' ? '这次不参与' : '')
  const missing = lane.status === 'waiting' ? lane.awaiting_member : null
  return (
    <div className="kt-ncard-body">
      <p className="kt-ncard-head">
        <RoleIcon role={lane.icon || lane.key} size={16} /> <b>{lane.title}</b>
        <span className={`kt-pill tone-${meta.tone}`}>{meta.label}</span>
      </p>
      {lane.assignment && (
        <p className="kt-ncard-task">
          <span className="kt-dim">任务</span> {lane.assignment}
        </p>
      )}
      {missing && (
        <p className="kt-ncard-back">
          ⏸ 没开工：「代理」里还没有成员 {missing}。在 Kiro Crew「代理」→「添加团队成员」加上它（名称和模板都填 {missing}），加上就自动开工。
        </p>
      )}
      {sentBack && <p className="kt-ncard-back">这一轮：{lane.doing}</p>}
      {did && <p className="kt-ncard-did">{did}</p>}
      <ul className="kt-ncard-facts">
        {(lane.active_s > 0 || live) && <li>用时 {fmtClock(live && lane.agent ? lane.agent.elapsed_s : lane.active_s)}</li>}
        {lane.writable.length > 0 && files > 0 && (
          <li>
            改了 {files} 个文件 <span className="kt-ok">+{lane.lines.added}</span> <span className="kt-bad">−{lane.lines.removed}</span> · {lane.commits.length} 次提交
          </li>
        )}
        {lane.writable.length === 0 && lane.status !== 'waiting' && <li>只读：不改代码，只看实际改动</li>}
        {mine.length > 0 && (
          <li>
            负责的检查 {passed}/{mine.length} 通过
          </li>
        )}
        {lookups > 0 && <li>查知识库、读数据 {lookups} 次</li>}
        {lane.credits !== null && <li>{fmtCredits(lane.credits)} credits</li>}
      </ul>
      <div className="kt-ncard-actions">
        {onOutputs && lane.status !== 'waiting' && (
          <button type="button" className="kt-btn" onClick={() => onOutputs(lane.key)}>
            看产出
          </button>
        )}
        {lane.session && <OpenSession slot={lane.session} title={lane.title} />}
      </div>
    </div>
  )
}
