/**
 * 产出: what each step of the team actually produced. Step through the roles in team order and open any one:
 * its files (markdown rendered, code with line numbers, or exactly what it changed as a diff), its whole last
 * reply, the task the app gave it and every tool call it made, per round. 整个产品 is the run branch as a
 * whole.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useChatLauncher, type AppApi } from '@kirocrew/app-sdk'
import { MarkdownRenderer } from '@kirocrew/app-sdk/ui'
import type { FileView, OutputAttempt, OutputFile, RoleOutput, RunDetail } from '../types'
import { fmtClock, laneMeta, paths, runMeta, toolIcon } from './format'
import { FolderActions } from './Folder'
import { errorText } from './useBoard'
import { RoleIcon } from './RoleIcon'
import { t as tr } from '../i18n'

export const PRODUCT = 'run'
export type OutputsTab = 'files' | 'reply' | 'task' | 'calls'
export interface OutputsTarget {
  role: string
  path?: string | null
  tab?: OutputsTab | null
}

const TAB_LABEL: Record<OutputsTab, string> = { files: tr('board.Outputs.1'), reply: tr('board.Outputs.2'), task: tr('board.Outputs.3'), calls: tr('board.Outputs.4') }

export function tabsFor(role: string, writable: boolean): OutputsTab[] {
  if (role === PRODUCT) return ['files']
  return writable ? ['files', 'reply', 'task', 'calls'] : ['reply', 'task', 'calls']
}

export function OutputsDrawer({ api, run, target, onTarget, onClose }: { api: AppApi; run: RunDetail; target: OutputsTarget; onTarget: (t: OutputsTarget) => void; onClose: () => void }) {
  const closeRef = useRef<HTMLButtonElement | null>(null)
  useEffect(() => closeRef.current?.focus(), [])
  const index = run.roles.findIndex((l) => l.key === target.role)
  const order = [...run.roles.map((l) => l.key), PRODUCT]
  const at = order.indexOf(target.role)
  const step = (d: number) => {
    const next = order[at + d]
    if (next) onTarget({ role: next })
  }
  const title = target.role === PRODUCT ? tr('board.Outputs.5') : (run.roles[index]?.title ?? target.role)
  return (
    <div className="kt-drawer-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <aside className="kt-drawer" role="dialog" aria-modal="true" aria-label={tr('board.Outputs.6', { p0: title })} data-testid="kt-outputs">
        <div className="kt-drawer-top">
          <h2>{tr('board.Outputs.7')}</h2>
          <span className="kt-dim">{run.title}</span>
          <span className="kt-grow" />
          <button type="button" className="kt-btn" onClick={() => step(-1)} disabled={at <= 0} aria-label={tr('board.Outputs.8')}>
            {tr('board.Outputs.9')}
          </button>
          <button type="button" className="kt-btn" onClick={() => step(1)} disabled={at < 0 || at >= order.length - 1} aria-label={tr('board.Outputs.10')}>
            {tr('board.Outputs.11')}
          </button>
          <button ref={closeRef} type="button" className="kt-btn" onClick={onClose} aria-label={tr('board.Outputs.12')}>
            ✕
          </button>
        </div>
        <nav className="kt-steps" aria-label={tr('board.Outputs.13')}>
          {run.roles.map((l, i) => (
            <button key={l.key} type="button" className={`kt-step tone-${laneMeta(l).tone}${l.key === target.role ? ' is-on' : ''}`} aria-current={l.key === target.role ? 'step' : undefined} onClick={() => onTarget({ role: l.key })} title={laneMeta(l).label}>
              <span className="kt-step-n">{i + 1}</span>
              <RoleIcon role={l.icon || l.key} size={16} />
              <span>{l.title}</span>
            </button>
          ))}
          <button type="button" className={`kt-step is-product${target.role === PRODUCT ? ' is-on' : ''}`} aria-current={target.role === PRODUCT ? 'step' : undefined} onClick={() => onTarget({ role: PRODUCT })}>
            <span aria-hidden="true">📦</span>
            <span>{tr('board.Outputs.5')}</span>
          </button>
        </nav>
        {run.imported && (
          <p className="kt-banner" role="note">
            {tr('board.Outputs.14')}{run.imported.from}{tr('board.Outputs.15')}
          </p>
        )}
        <RolePane key={target.role} api={api} run={run} target={target} />
      </aside>
    </div>
  )
}

/** 在 Crew 里打开会话: the role's agent is a Kiro Crew chat session (the session runner): open it in the dashboard to
 * read every step it took, or type into it. */
export function OpenSession({ slot, title }: { slot: string; title: string }) {
  const { openChat } = useChatLauncher()
  return (
    <button type="button" className="kt-btn is-primary" onClick={() => openChat({ slotKey: slot, autoSend: false })} title={tr('board.Outputs.16', { p0: title })}>
      {tr('board.Outputs.17')}
    </button>
  )
}

/** One role (or the product): loaded when shown, again when its lane moves on. */
function RolePane({ api, run, target }: { api: AppApi; run: RunDetail; target: OutputsTarget }) {
  const role = target.role
  const lane = run.roles.find((l) => l.key === role) ?? null
  const product = role === PRODUCT
  const tabs = tabsFor(role, product || !!lane?.writable.length)
  const [tab, setTab] = useState<OutputsTab>(target.tab && tabs.includes(target.tab) ? target.tab : tabs[0])
  const [data, setData] = useState<RoleOutput | null>(null)
  const [err, setErr] = useState('')
  const version = product ? `${run.status}|${run.merges.length}` : lane ? `${lane.status}|${lane.attempt}|${lane.commits.length}|${lane.done_at ?? ''}` : ''
  const live = !!data?.attempts.some((a) => a.live)
  const [tick, setTick] = useState(0)
  useEffect(() => {
    if (!live) return
    const t = setInterval(() => setTick((n) => n + 1), 4000) // a working agent: its tool calls keep coming
    return () => clearInterval(t)
  }, [live])
  useEffect(() => {
    let alive = true
    setErr('')
    api
      .get<RoleOutput>(paths.role(run.id, role))
      .then((d) => alive && setData(d))
      .catch((e) => alive && setErr(errorText(e)))
    return () => {
      alive = false
    }
  }, [api, run.id, role, version, tick])

  const meta = lane ? laneMeta(lane) : runMeta(run.status)
  return (
    <section className="kt-pane" aria-label={data?.title ?? role}>
      <header className="kt-pane-head">
        <div className="kt-pane-who">
          <span className="kt-pane-emoji" aria-hidden="true">
            <RoleIcon role={product ? 'product' : lane?.icon || lane?.key} size={26} />
          </span>
          <h3>{product ? tr('board.Outputs.5') : tr('board.Outputs.6', { p0: lane?.title ?? role })}</h3>
          <span className={`kt-pill tone-${meta.tone}`}>{meta.label}</span>
          {data?.branch && (
            <code className="kt-dim" title={data.base ? tr('board.Outputs.18', { p0: data.base }) : undefined}>
              {data.branch}
              {data.head ? ` @ ${data.head}` : ''}
            </code>
          )}
        </div>
        {lane && <p className="kt-dim kt-pane-scope">{lane.writable.length ? tr('board.Outputs.19', { p0: lane.writable.join(tr('common.sep')) }) : tr('board.Outputs.20')}</p>}
        {(data?.folder || lane?.session) && (
          <div className="kt-pane-folder">
            {lane?.session && <OpenSession slot={lane.session} title={lane.title} />}
            {data?.folder && <FolderActions api={api} run={run.id} role={product ? null : role} path={data.folder} />}
          </div>
        )}
        <div className="kt-tabs" role="tablist" aria-label={tr('board.Outputs.21')}>
          {tabs.map((t) => (
            <button key={t} type="button" role="tab" className="kt-tab" aria-selected={tab === t} onClick={() => setTab(t)}>
              {t === 'reply' && !lane?.writable.length ? tr('board.Outputs.22') : TAB_LABEL[t]}
              {t === 'files' && data ? <sub>{data.files.length}</sub> : null}
            </button>
          ))}
        </div>
      </header>
      <div className="kt-pane-body" role="tabpanel">
        {err && (
          <p className="kt-error" role="alert">
            {tr('board.Outputs.23')}{err}
          </p>
        )}
        {!data && !err && <p className="kt-dim">{tr('board.Outputs.24')}</p>}
        {data && tab === 'files' && <FilesTab api={api} run={run} data={data} initial={target.path ?? null} />}
        {data && (tab === 'reply' || tab === 'task' || tab === 'calls') && <AttemptTab data={data} tab={tab} />}
      </div>
    </section>
  )
}


// ---------------------------------------------------------------------------------------------
// files: the list, and one file's content or diff
// ---------------------------------------------------------------------------------------------

export function sortFiles(files: OutputFile[]): OutputFile[] {
  return files.slice().sort((a, b) => Number(b.output) - Number(a.output) || a.path.localeCompare(b.path))
}

function FilesTab({ api, run, data, initial }: { api: AppApi; run: RunDetail; data: RoleOutput; initial: string | null }) {
  const files = useMemo(() => sortFiles(data.files), [data.files])
  const [sel, setSel] = useState<string | null>(() => (initial && files.some((f) => f.path === initial) ? initial : (files[0]?.path ?? null)))
  useEffect(() => {
    if (!sel && files[0]) setSel(files[0].path)
  }, [files, sel])
  const owners = useMemo(() => new Map(run.roles.map((l) => [l.key, l])), [run.roles])
  if (!files.length) return <p className="kt-dim">{data.role === PRODUCT ? tr('board.Outputs.25') : tr('board.Outputs.26')}</p>
  const outputs = files.filter((f) => f.output)
  const others = files.filter((f) => !f.output)
  const row = (f: OutputFile) => {
    const owner = data.role === PRODUCT && f.owner ? owners.get(f.owner) : null
    const slash = f.path.lastIndexOf('/')
    return (
      <li key={f.path}>
        <button type="button" className={`kt-frow${sel === f.path ? ' is-on' : ''}`} aria-current={sel === f.path ? 'true' : undefined} aria-label={f.path} onClick={() => setSel(f.path)} title={`${f.path}  +${f.added} −${f.removed}`}>
          <span className={`kt-file-st is-${f.status}`}>{f.status}</span>
          <span className="kt-frow-path kt-mono">
            {slash >= 0 && <span className="kt-dim">{f.path.slice(0, slash + 1)}</span>}
            {f.path.slice(slash + 1)}
          </span>
          <span className="kt-frow-num kt-mono">
            {owner && <span title={owner.title}><RoleIcon role={owner.icon || owner.key} size={13} /> </span>}
            <span className="kt-add">+{f.added}</span>
          </span>
        </button>
      </li>
    )
  }
  return (
    <div className="kt-files-pane">
      <div className="kt-flist">
        {outputs.length > 0 && (
          <>
            <p className="kt-flist-h">{data.role === PRODUCT ? tr('board.Outputs.27') : tr('board.Outputs.28')}</p>
            <ul>{outputs.map(row)}</ul>
          </>
        )}
        {others.length > 0 && (
          <>
            <p className="kt-flist-h">{outputs.length ? tr('board.Outputs.29') : tr('board.Outputs.30')}</p>
            <ul>{others.map(row)}</ul>
          </>
        )}
      </div>
      {sel && <FileViewer key={sel} api={api} run={run} role={data.role} path={sel} head={data.head} file={files.find((f) => f.path === sel) ?? null} />}
    </div>
  )
}

function FileViewer({ api, run, role, path, head, file }: { api: AppApi; run: RunDetail; role: string; path: string; head: string | null; file: OutputFile | null }) {
  const [view, setView] = useState<'content' | 'diff'>(file?.status === 'D' ? 'diff' : 'content')
  const [md, setMd] = useState<'rendered' | 'source'>('rendered')
  const [got, setGot] = useState<FileView | null>(null)
  const [err, setErr] = useState('')
  useEffect(() => {
    let alive = true
    setGot(null)
    setErr('')
    api
      .get<FileView>(paths.file(run.id, role, path, view))
      .then((d) => alive && setGot(d))
      .catch((e) => alive && setErr(errorText(e)))
    return () => {
      alive = false
    }
  }, [api, run.id, role, path, view, head])
  const markdown = got?.lang === 'markdown' && view === 'content'
  return (
    <div className="kt-fview" data-testid="kt-file-view">
      <div className="kt-fview-bar">
        <code className="kt-fview-path">{path}</code>
        {file && (
          <span className="kt-mono kt-dim">
            <span className="kt-add">+{file.added}</span> <span className="kt-del">−{file.removed}</span>
          </span>
        )}
        <span className="kt-grow" />
        {markdown && (
          <button type="button" className="kt-btn is-small" aria-pressed={md === 'source'} onClick={() => setMd((m) => (m === 'rendered' ? 'source' : 'rendered'))}>
            {tr('board.Outputs.31')}
          </button>
        )}
        <div className="kt-seg" role="group" aria-label={tr('board.Outputs.32')}>
          <button type="button" className="kt-btn is-small" aria-pressed={view === 'content'} onClick={() => setView('content')} disabled={file?.status === 'D'}>
            {tr('board.Outputs.33')}
          </button>
          <button type="button" className="kt-btn is-small" aria-pressed={view === 'diff'} onClick={() => setView('diff')}>
            {tr('board.Outputs.34')}
          </button>
        </div>
      </div>
      <div className="kt-fview-body">
        {err && (
          <p className="kt-error kt-pad" role="alert">
            {err}
          </p>
        )}
        {!got && !err && <p className="kt-dim kt-pad">{tr('board.Outputs.24')}</p>}
        {got && got.binary && <p className="kt-dim kt-pad">{tr('board.Outputs.35')}</p>}
        {got && !got.binary && !got.text && <p className="kt-dim kt-pad">{view === 'diff' ? tr('board.Outputs.36') : tr('board.Outputs.37')}</p>}
        {got && !got.binary && got.text && (markdown && md === 'rendered' ? (
          <div className="kt-md msg-content">
            <MarkdownRenderer content={got.text} />
          </div>
        ) : (
          <CodeLines text={got.text} diff={view === 'diff'} />
        ))}
        {got?.truncated && <p className="kt-dim kt-pad">{tr('board.Outputs.38')}</p>}
      </div>
    </div>
  )
}

export function lineKind(line: string): string {
  if (line.startsWith('@@')) return 'is-hunk'
  if (/^(diff --git|index |--- |\+\+\+ |new file mode|deleted file mode|similarity |rename )/.test(line)) return 'is-meta'
  if (line.startsWith('+')) return 'is-add'
  if (line.startsWith('-')) return 'is-del'
  return ''
}

function CodeLines({ text, diff }: { text: string; diff: boolean }) {
  const lines = text.endsWith('\n') ? text.slice(0, -1).split('\n') : text.split('\n')
  return (
    <ol className={`kt-code${diff ? ' is-diff' : ''}`}>
      {lines.map((ln, i) => (
        <li key={i} className={diff ? lineKind(ln) : undefined}>
          <code>{ln || ' '}</code>
        </li>
      ))}
    </ol>
  )
}

// ---------------------------------------------------------------------------------------------
// reply / task / calls, per round
// ---------------------------------------------------------------------------------------------

function AttemptTab({ data, tab }: { data: RoleOutput; tab: 'reply' | 'task' | 'calls' }) {
  const [n, setN] = useState<number | null>(null)
  const atts = data.attempts
  if (!atts.length) return <p className="kt-dim">{tr('board.Outputs.39')}</p>
  const att = atts.find((a) => a.n === n) ?? atts[atts.length - 1]
  return (
    <div className="kt-attempt">
      {atts.length > 1 && (
        <div className="kt-rounds" role="group" aria-label={tr('board.Outputs.40')}>
          {atts.map((a) => (
            <button key={a.n} type="button" className="kt-btn is-small" aria-pressed={a.n === att.n} onClick={() => setN(a.n)}>
              {tr('board.Outputs.41')} {a.n} {tr('board.Outputs.42')}{a.label ? ` · ${a.label}` : a.kind === 'work' ? tr('board.Outputs.43') : ''}
            </button>
          ))}
        </div>
      )}
      <AttemptMeta att={att} />
      {tab === 'reply' && <Reply att={att} />}
      {tab === 'task' && <pre className="kt-task kt-mono">{att.task}</pre>}
      {tab === 'calls' && <Calls att={att} />}
    </div>
  )
}

function AttemptMeta({ att }: { att: OutputAttempt }) {
  const took = att.started && att.ended ? fmtClock(att.ended - att.started) : null
  return (
    <p className="kt-dim kt-attempt-meta">
      {att.live ? tr('board.Outputs.44') : took ? tr('board.Outputs.45', { p0: took }) : tr('board.Outputs.46')}
      {att.calls.length > 0 && tr('board.Outputs.47', { p0: att.calls.length })}
      {att.credits !== null && ` · ${att.credits.toFixed(1)} credits`}
      {att.agent && <span className="kt-mono"> {tr('board.Outputs.48')} {att.agent}</span>}
    </p>
  )
}

function Reply({ att }: { att: OutputAttempt }) {
  if (att.error && !att.reply) return <p className="kt-error">{tr('board.Outputs.49')}{att.error}</p>
  if (!att.reply) return <p className="kt-dim">{att.live ? tr('board.Outputs.50') : tr('board.Outputs.51')}</p>
  return (
    <>
      {att.error && <p className="kt-error">{tr('board.Outputs.49')}{att.error}</p>}
      <div className="kt-md kt-reply msg-content" data-testid="kt-reply">
        <MarkdownRenderer content={att.reply} />
      </div>
    </>
  )
}

function Calls({ att }: { att: OutputAttempt }) {
  if (!att.calls.length) return <p className="kt-dim">{att.live ? tr('board.Outputs.52') : tr('board.Outputs.53')}</p>
  const t0 = att.started ?? att.calls[0].at
  return (
    <ol className="kt-calls" aria-label={tr('board.Outputs.54')}>
      {att.calls.map((c, i) => (
        <li key={`${c.at}-${i}`}>
          <time className="kt-mono kt-dim">{fmtClock(Math.max(0, c.at - t0))}</time>
          <span aria-hidden="true">{toolIcon(c.kind, c.tool)}</span>
          <span className="kt-mono">
            <b>{c.tool}</b> {c.detail}
          </span>
        </li>
      ))}
    </ol>
  )
}
