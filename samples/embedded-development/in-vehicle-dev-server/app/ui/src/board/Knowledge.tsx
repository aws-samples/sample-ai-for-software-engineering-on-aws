/**
 * 知识库: the left shift on the board. The team's Kiro Crew knowledge source and its state, the documents the roles
 * cite (how often their replies cite each), and what the roles looked up there, live: their 查知识库 calls and their
 * reads of the knowledge files. Also the 知识库 section of the home page (GET /knowledge) and the read-only viewer
 * both open (GET /knowledge/file: plain text, never rendered).
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useAppApi } from '@kirocrew/app-sdk'
import type { KnowledgeChip, KnowledgeIndex, KnowledgeSource, KnowledgeText, Lane, RunDetail } from '../types'
import { BASE, fmtAgo } from './format'
import { useServerNow } from './hooks'
import { RoleIcon } from './RoleIcon'
import { errorText } from './useBoard'

function sourceText(s: KnowledgeSource | null): string {
  if (!s) return ''
  if (s.present === null) return '读取中…'
  if (!s.present) return `还没挂上：在 Crew 侧栏「知识库 → 来源」里加 ${s.path || '~/workplace/vstatd/knowledge'}`
  const sync = s.status === 'synced' ? '已同步' : s.files_total ? `正在索引 ${s.files_done ?? 0}/${s.files_total}` : s.status || '索引中'
  return `${s.items ?? 0} 份文档 · ${sync}`
}

/** One knowledge document as plain text (escaped by React in a <pre>, never rendered as HTML or Markdown). */
export function KnowledgeViewer({ path, onClose }: { path: string; onClose: () => void }) {
  const api = useAppApi()
  const [doc, setDoc] = useState<KnowledgeText | null>(null)
  const [err, setErr] = useState('')
  const closeRef = useRef<HTMLButtonElement | null>(null)
  useEffect(() => closeRef.current?.focus(), [])
  useEffect(() => {
    let live = true
    setDoc(null)
    setErr('')
    api.get<KnowledgeText>(`${BASE}/knowledge/file?path=${encodeURIComponent(path)}`).then(
      (d) => live && setDoc(d),
      (x) => live && setErr(errorText(x)),
    )
    return () => {
      live = false
    }
  }, [api, path])
  return (
    <div className="kt-drawer-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()} onKeyDown={(e) => e.key === 'Escape' && onClose()}>
      <aside className="kt-drawer kt-kb-view" role="dialog" aria-modal="true" aria-label={`知识库文档 ${path}`} data-testid="kt-kb-viewer">
        <div className="kt-drawer-top">
          <h2>{doc?.title ?? path}</h2>
          <span className="kt-dim kt-mono">{path}</span>
          <span className="kt-dim">只读</span>
          <span className="kt-grow" />
          <button ref={closeRef} type="button" className="kt-btn" onClick={onClose} aria-label="关闭文档">
            ✕
          </button>
        </div>
        <div className="kt-pane-body">
          {err && <p className="kt-error" role="alert">读不到：{err}</p>}
          {!doc && !err && <p className="kt-dim">正在读…</p>}
          {doc && <pre className="kt-task kt-mono" data-testid="kt-kb-text">{doc.text}</pre>}
        </div>
      </aside>
    </div>
  )
}

/** 知识库 on the home page: every document the team uses, its figures counted from the file, and the index state. */
export function KnowledgeHome() {
  const api = useAppApi()
  const [k, setK] = useState<KnowledgeIndex | null>(null)
  const [err, setErr] = useState('')
  const [open, setOpen] = useState<string | null>(null)
  const load = useCallback(async () => {
    try {
      setK(await api.get<KnowledgeIndex>(`${BASE}/knowledge`))
      setErr('')
    } catch (x) {
      setErr(errorText(x))
    }
  }, [api])
  useEffect(() => {
    void load()
  }, [load])
  return (
    <section className="kt-ready kt-lib" aria-label="知识库" data-testid="kt-kb-home">
      <header className="kt-ready-head">
        <h3><RoleIcon role="book" size={16} /> 知识库</h3>
        <span className="kt-dim">agent 分诊、修复和评审时查这些文档，引用写成 [VSTATD-IF p.7 §4.1]、[CC1-PN §6.3]、[TR §4.1]。</span>
        {k?.source && <span className={`kt-dim${k.source.present === false ? ' kt-warn' : ''}`} data-testid="kt-kb-index">Kiro Crew 来源「{k.source.name}」：{sourceText(k.source)}</span>}
      </header>
      {err && <p className="kt-error" role="alert">知识库读不到：{err}</p>}
      {k?.error && <p className="kt-warn" role="status">{k.error}</p>}
      {!k && !err && <p className="kt-dim">正在读…</p>}
      {k && k.docs.length > 0 && (
        <ul className="kt-lib-list">
          {k.docs.map((d) => (
            <li key={d.path} className={`kt-lib-doc${d.present ? '' : ' is-missing'}`} data-testid="kt-kb-doc" data-path={d.path}>
              {d.text && d.present ? (
                <button type="button" className="kt-file-open kt-lib-title" onClick={() => setOpen(d.path)} title={`打开 ${d.path}（只读）`}>{d.title}</button>
              ) : (
                <b className="kt-lib-title">{d.title}</b>
              )}
              {d.key && <span className="kt-lib-key kt-mono">{d.key}</span>}
              <span className="kt-lib-counts">
                {d.present ? d.counts.map((c) => `${c.label} ${c.n}`).join(' · ') || (d.rendered_from ? `${d.rendered_from} 的 PDF 版` : '') : '文件不在'}
              </span>
              <small className="kt-dim kt-mono">{d.path}</small>
              <span className="kt-lib-desc">{d.desc}</span>
            </li>
          ))}
        </ul>
      )}
      {open && <KnowledgeViewer path={open} onClose={() => setOpen(null)} />}
    </section>
  )
}

function Chip({ d, onOpen }: { d: KnowledgeChip; onOpen: () => void }) {
  return (
    <li className="kt-kb-chip" data-testid="kt-kb-chip" data-key={d.key}>
      <button type="button" className="kt-file-open" onClick={onOpen} title={`打开 ${d.path}（只读）；角色的回复里引用了 ${d.cites} 次`}>
        <b>{d.key}</b> {d.title}
      </button>
      <span className="kt-mono">引用 {d.cites}</span>
    </li>
  )
}

export function KnowledgePanel({ run, onRole }: { run: RunDetail; onRole?: (key: string) => void }) {
  const now = useServerNow()
  const [open, setOpen] = useState<string | null>(null)
  const src = run.knowledge.source
  const docs = run.knowledge.docs ?? [] // a replayed record from before the chips has none
  if (!src && docs.length === 0) return null
  const byKey = new Map<string, Lane>(run.roles.map((l) => [l.key, l]))
  const hits = [...run.knowledge.hits].reverse()
  const searches = run.knowledge.hits.filter((h) => h.kind === 'search').length
  const reads = run.knowledge.hits.length - searches
  return (
    <section className="kt-kb" aria-label="知识库" data-testid="kt-kb">
      <div className="kt-kb-col">
        <p className="kt-kb-head">
          <b><RoleIcon role="book" size={16} /> 知识库{src ? `「${src.name}」` : ''}</b>
          <span className={`kt-dim${src && src.present === false ? ' kt-warn' : ''}`}>{sourceText(src)}</span>
        </p>
        {docs.length > 0 && (
          <ul className="kt-kb-chips" aria-label="角色引用的文档">
            {docs.map((d) => (
              <Chip key={d.key} d={d} onOpen={() => setOpen(d.path)} />
            ))}
          </ul>
        )}
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
      {open && <KnowledgeViewer path={open} onClose={() => setOpen(null)} />}
    </section>
  )
}
