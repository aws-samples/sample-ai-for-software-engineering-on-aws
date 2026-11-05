/**
 * 知识库: the left shift on the board. The team's Kiro Crew knowledge source and its state, the documents the roles
 * cite (how often their replies cite each), and what the roles looked up there, live: their 查知识库 calls and their
 * reads of the knowledge files. Also the 知识库 section of the home page (GET /knowledge) and the read-only viewer
 * both open (GET /knowledge/file: plain text, never rendered).
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useAppApi } from '@kirocrew/app-sdk'
import type { KnowledgeChip, KnowledgeDoc, KnowledgeIndex, KnowledgeSource, KnowledgeText, Lane, RunDetail } from '../types'
import { BASE, fmtAgo } from './format'
import { useServerNow } from './hooks'
import { RoleIcon } from './RoleIcon'
import { errorText } from './useBoard'
import { t as tr } from '../i18n'

function sourceText(s: KnowledgeSource | null): string {
  if (!s) return ''
  if (s.present === null) return tr('board.Knowledge.1')
  if (!s.present) return tr('board.Knowledge.2', { p0: s.path || '~/workplace/vstatd/knowledge' })
  const sync = s.status === 'synced' ? tr('board.Knowledge.3') : s.files_total ? tr('board.Knowledge.4', { p0: s.files_done ?? 0, p1: s.files_total }) : s.status || tr('board.Knowledge.5')
  return tr('board.Knowledge.6', { p0: s.items ?? 0, p1: sync })
}

/** The index state in a few words, for the folded 知识库's summary. */
function indexText(s: KnowledgeSource | null): string {
  if (!s) return ''
  if (s.present === null) return tr('board.Knowledge.7')
  if (!s.present) return tr('board.Knowledge.8')
  return s.status === 'synced' ? tr('board.Knowledge.9') : s.files_total ? tr('board.Knowledge.4', { p0: s.files_done ?? 0, p1: s.files_total }) : tr('board.Knowledge.5')
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
      <aside className="kt-drawer kt-kb-view" role="dialog" aria-modal="true" aria-label={tr('board.Knowledge.10', { p0: path })} data-testid="kt-kb-viewer">
        <div className="kt-drawer-top">
          <h2>{doc?.title ?? path}</h2>
          <span className="kt-dim kt-mono">{path}</span>
          <span className="kt-dim">{tr('board.Knowledge.11')}</span>
          <span className="kt-grow" />
          <button ref={closeRef} type="button" className="kt-btn" onClick={onClose} aria-label={tr('board.Knowledge.12')}>
            ✕
          </button>
        </div>
        <div className="kt-pane-body">
          {err && <p className="kt-error" role="alert">{tr('board.Knowledge.13')}{err}</p>}
          {!doc && !err && <p className="kt-dim">{tr('board.Knowledge.14')}</p>}
          {doc && <pre className="kt-task kt-mono" data-testid="kt-kb-text">{doc.text}</pre>}
        </div>
      </aside>
    </div>
  )
}

/** The home page's card groups: which documents go together (the facts files share one card, the PDF is a note on the spec). */
const GROUPS: { title: string; paths: string[] }[] = [
  { title: tr('board.Knowledge.15'), paths: ['vstatd-interface.md', 'cc1-platform-notes.md', 'team-rules.md'] },
  { title: tr('board.Knowledge.16'), paths: ['findings-backlog.md', 'cc1-gateway.dbc', 'vss-mapping.yaml'] },
  { title: tr('board.Knowledge.17'), paths: ['facts/'] },
]
const FACTS = 'facts/'

function Figures({ d }: { d: KnowledgeDoc }) {
  if (!d.present) return <span className="kt-lib-chip is-missing">{tr('board.Knowledge.18')}</span>
  return <>{d.counts.map((c) => <span key={c.label} className="kt-lib-chip">{c.label} {c.n}</span>)}</>
}

function Open({ d, onOpen }: { d: KnowledgeDoc; onOpen: (path: string) => void }) {
  if (!d.text || !d.present) return null
  return (
    <button type="button" className="kt-btn kt-lib-open" onClick={() => onOpen(d.path)} aria-label={tr('board.Knowledge.19', { p0: d.title })} title={tr('board.Knowledge.20', { p0: d.path })}>
      {tr('board.Knowledge.21')}
    </button>
  )
}

function DocCard({ d, pdf, onOpen }: { d: KnowledgeDoc; pdf?: KnowledgeDoc; onOpen: (path: string) => void }) {
  return (
    <li className={`kt-lib-card${d.present ? '' : ' is-missing'}`} data-testid="kt-kb-doc" data-path={d.path}>
      <div className="kt-lib-top">
        <b className="kt-lib-title">{d.title}</b>
        {d.key && <span className="kt-lib-key kt-mono">{d.key}</span>}
        {pdf?.present && <span className="kt-lib-pdf" title={tr('board.Knowledge.22', { p0: pdf.path, p1: pdf.desc })} data-testid="kt-kb-pdf">{tr('board.Knowledge.23')}</span>}
      </div>
      <div className="kt-lib-counts"><Figures d={d} /></div>
      <p className="kt-lib-desc" title={d.desc}>{d.desc}</p>
      <div className="kt-lib-foot">
        <small className="kt-dim kt-mono">{d.path}</small>
        <Open d={d} onOpen={onOpen} />
      </div>
    </li>
  )
}

/** The three facts files on one card: a figure and a 查看 per file. */
function FactsCard({ docs, onOpen }: { docs: KnowledgeDoc[]; onOpen: (path: string) => void }) {
  const kind = (d: KnowledgeDoc) => d.title.split(' · ').pop() ?? d.title
  return (
    <li className="kt-lib-card" data-testid="kt-kb-doc" data-path={FACTS}>
      <div className="kt-lib-top"><b className="kt-lib-title">{tr('board.Knowledge.17')}</b></div>
      <div className="kt-lib-counts">
        {docs.map((d) => <span key={d.path} className={`kt-lib-chip${d.present ? '' : ' is-missing'}`}>{kind(d)} {d.present ? d.counts[0]?.n ?? '—' : tr('board.Knowledge.18')}</span>)}
      </div>
      <p className="kt-lib-desc">{tr('board.Knowledge.24')}</p>
      {docs.map((d) => (
        <div key={d.path} className="kt-lib-foot">
          <small className="kt-dim kt-mono">{d.path}</small>
          <Open d={d} onOpen={onOpen} />
        </div>
      ))}
    </li>
  )
}

/** 知识库 on the home page: every document the team uses as cards by kind, its figures counted from the file, and the index state. */
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
  const docs = k?.docs ?? []
  const byPath = new Map(docs.map((d) => [d.path, d]))
  const pdfOf = (d: KnowledgeDoc) => docs.find((x) => x.rendered_from === d.path)
  const placed = new Set(GROUPS.flatMap((g) => g.paths))
  const isFact = (d: KnowledgeDoc) => d.path.startsWith(FACTS)
  // a document no group names (and that is not a PDF note) still shows, last
  const rest = docs.filter((d) => !placed.has(d.path) && !isFact(d) && !d.rendered_from)
  return (
    <details className="kt-ready kt-lib kt-fold" aria-label={tr('board.Knowledge.25')} data-testid="kt-kb-home">
      <summary data-testid="kt-kb-sum">
        <h3><RoleIcon role="book" size={16} /> {tr('board.Knowledge.25')}</h3>
        {k && !k.error && <span className="kt-dim">{[tr('board.Knowledge.26', { p0: docs.length }), indexText(k.source)].filter(Boolean).join(' · ')}</span>}
      </summary>
      <div className="kt-fold-body">
      <header className="kt-lib-head">
        <p className="kt-dim">{tr('board.Knowledge.27')}</p>
        {k?.source && <p className={`kt-dim${k.source.present === false ? ' kt-warn' : ''}`} data-testid="kt-kb-index">{tr('board.Knowledge.28')}{k.source.name}{tr('board.Knowledge.29')}{sourceText(k.source)}</p>}
      </header>
      {err && <p className="kt-error" role="alert">{tr('board.Knowledge.30')}{err}</p>}
      {k?.error && <p className="kt-warn" role="status">{k.error}</p>}
      {!k && !err && <p className="kt-dim">{tr('board.Knowledge.14')}</p>}
      {docs.length > 0 &&
        [...GROUPS, { title: tr('board.Knowledge.31'), paths: rest.map((d) => d.path) }].map((g) => {
          const facts = g.paths.includes(FACTS) ? docs.filter(isFact) : []
          const cards = g.paths.map((p) => byPath.get(p)).filter((d): d is KnowledgeDoc => !!d)
          if (cards.length === 0 && facts.length === 0) return null
          return (
            <div key={g.title} className="kt-lib-group" data-testid="kt-kb-group" data-group={g.title}>
              <h4>{g.title}</h4>
              <ul className="kt-lib-grid">
                {cards.map((d) => <DocCard key={d.path} d={d} pdf={pdfOf(d)} onOpen={setOpen} />)}
                {facts.length > 0 && <FactsCard docs={facts} onOpen={setOpen} />}
              </ul>
            </div>
          )
        })}
      </div>
      {open && <KnowledgeViewer path={open} onClose={() => setOpen(null)} />}
    </details>
  )
}

function Chip({ d, onOpen }: { d: KnowledgeChip; onOpen: () => void }) {
  return (
    <li className="kt-kb-chip" data-testid="kt-kb-chip" data-key={d.key}>
      <button type="button" className="kt-file-open" onClick={onOpen} title={tr('board.Knowledge.32', { p0: d.path, p1: d.cites })}>
        <b>{d.key}</b> {d.title}
      </button>
      <span className="kt-mono">{tr('board.Knowledge.33')} {d.cites}</span>
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
    <details className="kt-kb kt-fold" aria-label={tr('board.Knowledge.25')} data-testid="kt-kb">
      <summary className="kt-kb-head" data-testid="kt-kb-fold">
        <b><RoleIcon role="book" size={16} /> {tr('board.Knowledge.25')}{src ? tr('board.Knowledge.34', { p0: src.name }) : ''}</b>
        <span className="kt-dim">{[indexText(src), tr('board.Knowledge.35', { p0: docs.length }), tr('board.Knowledge.36', { p0: searches, p1: reads })].filter(Boolean).join(' · ')}</span>
      </summary>
      <div className="kt-kb-grid">
      <div className="kt-kb-col">
        <p className="kt-kb-head">
          <b>{tr('board.Knowledge.37')}</b>
          <span className={`kt-dim${src && src.present === false ? ' kt-warn' : ''}`}>{src ? tr('board.Knowledge.38', { p0: src.name, p1: sourceText(src) }) : ''}</span>
        </p>
        {docs.length > 0 && (
          <ul className="kt-kb-chips" aria-label={tr('board.Knowledge.37')}>
            {docs.map((d) => (
              <Chip key={d.key} d={d} onOpen={() => setOpen(d.path)} />
            ))}
          </ul>
        )}
      </div>
      <div className="kt-kb-col is-hits">
        <p className="kt-kb-head">
          <b>{tr('board.Knowledge.39')}</b>
          <span className="kt-dim">
            {tr('board.Knowledge.40')} {searches} {tr('board.Knowledge.41')} {reads} {tr('board.Knowledge.42')}
          </span>
        </p>
        {hits.length === 0 ? (
          <p className="kt-dim kt-kb-empty">{tr('board.Knowledge.43')}</p>
        ) : (
          <ol className="kt-kb-hits">
            {hits.slice(0, 8).map((h, i) => {
              const lane = byKey.get(h.role)
              return (
                <li key={`${h.at}-${i}`} className={`is-${h.kind}`}>
                  <button type="button" className="kt-kb-who" onClick={() => onRole?.(h.role)}>
                    <RoleIcon role={lane?.icon || h.role} size={13} /> {lane?.title ?? h.role}
                  </button>
                  <span className="kt-kb-what">{h.kind === 'search' ? tr('board.Knowledge.44', { p0: h.text }) : tr('board.Knowledge.45', { p0: h.text })}</span>
                  <small className="kt-dim">{fmtAgo(now - h.at)}</small>
                </li>
              )
            })}
          </ol>
        )}
      </div>
      </div>
      {open && <KnowledgeViewer path={open} onClose={() => setOpen(null)} />}
    </details>
  )
}
