/**
 * 知识库和公司规范: the left shift on the board. Which company standards (and which knowledge-base data) the
 * requirement touched, matched by keywords like 组队 (deterministic, with why); the team's Kiro Crew knowledge source
 * and its state; and what the roles looked up there, live: their 查知识库 calls and their reads of the data files.
 */
import type { Lane, RunDetail, Standard } from '../types'
import { fmtAgo } from './format'
import { useServerNow } from './hooks'
import { RoleIcon } from './RoleIcon'

function sourceText(run: RunDetail): string {
  const s = run.knowledge.source
  if (!s) return ''
  if (s.present === null) return '读取中…'
  if (!s.present) return `还没挂上：在 Crew 侧栏「知识库 → 来源」里加 ${s.path || '~/workplace/taoyuan/knowledge'}`
  const sync = s.status === 'synced' ? '已同步' : s.files_total ? `正在索引 ${s.files_done ?? 0}/${s.files_total}` : s.status || '索引中'
  return `${s.items ?? 0} 份文档 · ${sync}`
}

function Chip({ s }: { s: Standard }) {
  const rules = s.rules.length ? `${s.rules[0]}${s.rules.length > 1 ? `～${s.rules[s.rules.length - 1].split('-')[1]}` : ''}` : ''
  return (
    <li className={`kt-kb-chip is-${s.kind}`} title={`${s.owner ? `${s.owner}定的` : ''}${s.doc ? ` · 知识库里的 ${s.doc}` : ''}；${s.why}`}>
      <b>{s.kind === 'data' ? '数据' : '规范'}《{s.title}》</b>
      {rules && <span className="kt-mono">{rules}</span>}
    </li>
  )
}

export function KnowledgePanel({ run, onRole }: { run: RunDetail; onRole?: (key: string) => void }) {
  const now = useServerNow()
  const src = run.knowledge.source
  if (!src && run.standards.length === 0) return null
  const byKey = new Map<string, Lane>(run.roles.map((l) => [l.key, l]))
  const hits = [...run.knowledge.hits].reverse()
  const searches = run.knowledge.hits.filter((h) => h.kind === 'search').length
  const reads = run.knowledge.hits.length - searches
  return (
    <section className="kt-kb" aria-label="知识库和公司规范" data-testid="kt-kb">
      <div className="kt-kb-col">
        <p className="kt-kb-head">
          <b><RoleIcon role="book" size={16} /> 知识库{src ? `「${src.name}」` : ''}</b>
          <span className={`kt-dim${src && src.present === false ? ' kt-warn' : ''}`}>{sourceText(run)}</span>
        </p>
        <ul className="kt-kb-chips" aria-label="适用的公司规范和数据">
          {run.standards.map((s) => (
            <Chip key={s.id} s={s} />
          ))}
        </ul>
      </div>
      <div className="kt-kb-col is-hits">
        <p className="kt-kb-head">
          <b>agent 查了什么</b>
          <span className="kt-dim">
            查知识库 {searches} 次 · 读数据 {reads} 次
          </span>
        </p>
        {hits.length === 0 ? (
          <p className="kt-dim kt-kb-empty">还没有查询</p>
        ) : (
          <ol className="kt-kb-hits">
            {hits.slice(0, 8).map((h, i) => {
              const lane = byKey.get(h.role)
              return (
                <li key={`${h.at}-${i}`} className={`is-${h.kind}`}>
                  <button type="button" className="kt-kb-who" onClick={() => onRole?.(h.role)}>
                    <RoleIcon role={lane?.icon || h.role} size={13} /> {lane?.title ?? h.role}
                  </button>
                  <span className="kt-kb-what">{h.kind === 'search' ? `查知识库「${h.text}」` : `读数据 ${h.text}`}</span>
                  <small className="kt-dim">{fmtAgo(now - h.at)}</small>
                </li>
              )
            })}
          </ol>
        )}
      </div>
    </section>
  )
}
