/**
 * 产出: what each step of the team actually produced. Step through the roles in team order and open any one:
 * its files (markdown rendered, code with line numbers, or exactly what it changed as a diff), its whole last
 * reply, the task the app gave it and every tool call it made, per round. 整个产品 is the run branch as a
 * whole and, once the run has ended, the site itself: started on a local port and shown right here.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useChatLauncher, type AppApi } from '@kirocrew/app-sdk'
import { MarkdownRenderer } from '@kirocrew/app-sdk/ui'
import type { FileView, OutputAttempt, OutputFile, RoleOutput, RunDetail, SiteStatus } from '../types'
import { fmtClock, laneMeta, paths, runMeta, toolIcon } from './format'
import { FolderActions } from './Folder'
import { errorText } from './useBoard'
import { RoleIcon } from './RoleIcon'

export const PRODUCT = 'run'
export type OutputsTab = 'files' | 'reply' | 'task' | 'calls' | 'site'
export interface OutputsTarget {
  role: string
  path?: string | null
  tab?: OutputsTab | null
}

const TAB_LABEL: Record<OutputsTab, string> = { files: '产出文件', reply: '它的回复', task: '接到的任务', calls: '做了什么', site: '网站' }

export function tabsFor(role: string, writable: boolean): OutputsTab[] {
  if (role === PRODUCT) return ['site', 'files']
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
  const title = target.role === PRODUCT ? '整个产品' : (run.roles[index]?.title ?? target.role)
  return (
    <div className="kt-drawer-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <aside className="kt-drawer" role="dialog" aria-modal="true" aria-label={`${title}的产出`} data-testid="kt-outputs">
        <div className="kt-drawer-top">
          <h2>每一步的产出</h2>
          <span className="kt-dim">{run.title}</span>
          <span className="kt-grow" />
          <button type="button" className="kt-btn" onClick={() => step(-1)} disabled={at <= 0} aria-label="上一步">
            ‹ 上一步
          </button>
          <button type="button" className="kt-btn" onClick={() => step(1)} disabled={at < 0 || at >= order.length - 1} aria-label="下一步">
            下一步 ›
          </button>
          <button ref={closeRef} type="button" className="kt-btn" onClick={onClose} aria-label="关闭产出">
            ✕
          </button>
        </div>
        <nav className="kt-steps" aria-label="团队的每一步">
          {run.roles.map((l, i) => (
            <button key={l.key} type="button" className={`kt-step tone-${laneMeta(l).tone}${l.key === target.role ? ' is-on' : ''}`} aria-current={l.key === target.role ? 'step' : undefined} onClick={() => onTarget({ role: l.key })} title={laneMeta(l).label}>
              <span className="kt-step-n">{i + 1}</span>
              <RoleIcon role={l.icon || l.key} size={16} />
              <span>{l.title}</span>
            </button>
          ))}
          <button type="button" className={`kt-step is-product${target.role === PRODUCT ? ' is-on' : ''}`} aria-current={target.role === PRODUCT ? 'step' : undefined} onClick={() => onTarget({ role: PRODUCT })}>
            <span aria-hidden="true">📦</span>
            <span>整个产品</span>
          </button>
        </nav>
        {run.imported && (
          <p className="kt-banner" role="note">
            这次运行是从「{run.imported.from}」导入的，只带运行记录：每位成员的任务、回复和做了什么都在，改了哪些文件、文件内容要在原来那台 Mac 上看。
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
    <button type="button" className="kt-btn is-primary" onClick={() => openChat({ slotKey: slot, autoSend: false })} title={`「${title} agent」是 Kiro Crew 里的一个会话：每一步都能看，也能直接打字插话`}>
      在 Crew 里打开会话
    </button>
  )
}

/** One role (or the product): loaded when shown, again when its lane moves on. */
function RolePane({ api, run, target }: { api: AppApi; run: RunDetail; target: OutputsTarget }) {
  const role = target.role
  const lane = run.roles.find((l) => l.key === role) ?? null
  const product = role === PRODUCT
  const tabs = tabsFor(role, product || !!lane?.writable.length)
  const [tab, setTab] = useState<OutputsTab>(target.tab && tabs.includes(target.tab) ? target.tab : product && !isEnded(run) ? 'files' : tabs[0])
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
          <h3>{product ? '整个产品' : `${lane?.title ?? role}的产出`}</h3>
          <span className={`kt-pill tone-${meta.tone}`}>{meta.label}</span>
          {data?.branch && (
            <code className="kt-dim" title={data.base ? `和 ${data.base} 比` : undefined}>
              {data.branch}
              {data.head ? ` @ ${data.head}` : ''}
            </code>
          )}
        </div>
        {lane && <p className="kt-dim kt-pane-scope">{lane.writable.length ? `能写：${lane.writable.join('、')}` : '只读：不改任何文件'}</p>}
        {(data?.folder || lane?.session) && (
          <div className="kt-pane-folder">
            {lane?.session && <OpenSession slot={lane.session} title={lane.title} />}
            {data?.folder && <FolderActions api={api} run={run.id} role={product ? null : role} path={data.folder} />}
          </div>
        )}
        <div className="kt-tabs" role="tablist" aria-label="看什么">
          {tabs.map((t) => (
            <button key={t} type="button" role="tab" className="kt-tab" aria-selected={tab === t} onClick={() => setTab(t)}>
              {t === 'reply' && !lane?.writable.length ? '评审报告' : TAB_LABEL[t]}
              {t === 'files' && data ? <sub>{data.files.length}</sub> : null}
            </button>
          ))}
        </div>
      </header>
      <div className="kt-pane-body" role="tabpanel">
        {err && (
          <p className="kt-error" role="alert">
            读不了：{err}
          </p>
        )}
        {!data && !err && <p className="kt-dim">读取中…</p>}
        {data && tab === 'files' && <FilesTab api={api} run={run} data={data} initial={target.path ?? null} />}
        {data && (tab === 'reply' || tab === 'task' || tab === 'calls') && <AttemptTab data={data} tab={tab} />}
        {tab === 'site' && <SiteTab api={api} run={run} />}
      </div>
    </section>
  )
}

const isEnded = (run: RunDetail) => run.status === 'done' || run.status === 'failed' || run.status === 'stopped'

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
  if (!files.length) return <p className="kt-dim">{data.role === PRODUCT ? '还没有合进运行分支的改动。' : '它还没有提交任何文件。'}</p>
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
            <p className="kt-flist-h">{data.role === PRODUCT ? '约定的产出' : '约定它交的'}</p>
            <ul>{outputs.map(row)}</ul>
          </>
        )}
        {others.length > 0 && (
          <>
            <p className="kt-flist-h">{outputs.length ? '其他改动' : '改动的文件'}</p>
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
            源码
          </button>
        )}
        <div className="kt-seg" role="group" aria-label="看内容还是看改动">
          <button type="button" className="kt-btn is-small" aria-pressed={view === 'content'} onClick={() => setView('content')} disabled={file?.status === 'D'}>
            内容
          </button>
          <button type="button" className="kt-btn is-small" aria-pressed={view === 'diff'} onClick={() => setView('diff')}>
            改动
          </button>
        </div>
      </div>
      <div className="kt-fview-body">
        {err && (
          <p className="kt-error kt-pad" role="alert">
            {err}
          </p>
        )}
        {!got && !err && <p className="kt-dim kt-pad">读取中…</p>}
        {got && got.binary && <p className="kt-dim kt-pad">二进制文件，不显示内容</p>}
        {got && !got.binary && !got.text && <p className="kt-dim kt-pad">{view === 'diff' ? '没有改动' : '空文件'}</p>}
        {got && !got.binary && got.text && (markdown && md === 'rendered' ? (
          <div className="kt-md msg-content">
            <MarkdownRenderer content={got.text} />
          </div>
        ) : (
          <CodeLines text={got.text} diff={view === 'diff'} />
        ))}
        {got?.truncated && <p className="kt-dim kt-pad">只显示了前 300 KB</p>}
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
  if (!atts.length) return <p className="kt-dim">它还没开工。</p>
  const att = atts.find((a) => a.n === n) ?? atts[atts.length - 1]
  return (
    <div className="kt-attempt">
      {atts.length > 1 && (
        <div className="kt-rounds" role="group" aria-label="哪一轮">
          {atts.map((a) => (
            <button key={a.n} type="button" className="kt-btn is-small" aria-pressed={a.n === att.n} onClick={() => setN(a.n)}>
              第 {a.n} 轮{a.label ? ` · ${a.label}` : a.kind === 'work' ? ' · 开工' : ''}
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
      {att.live ? '还在做' : took ? `用时 ${took}` : '没跑起来'}
      {att.calls.length > 0 && ` · ${att.calls.length} 次工具调用`}
      {att.credits !== null && ` · ${att.credits.toFixed(1)} credits`}
      {att.agent && <span className="kt-mono"> · KiroCrew 子 agent {att.agent}</span>}
    </p>
  )
}

function Reply({ att }: { att: OutputAttempt }) {
  if (att.error && !att.reply) return <p className="kt-error">没做成：{att.error}</p>
  if (!att.reply) return <p className="kt-dim">{att.live ? '它还在做，回复还没出来。' : '没有留下回复。'}</p>
  return (
    <>
      {att.error && <p className="kt-error">没做成：{att.error}</p>}
      <div className="kt-md kt-reply msg-content" data-testid="kt-reply">
        <MarkdownRenderer content={att.reply} />
      </div>
    </>
  )
}

function Calls({ att }: { att: OutputAttempt }) {
  if (!att.calls.length) return <p className="kt-dim">{att.live ? '还没有工具调用。' : '没有记下工具调用。'}</p>
  const t0 = att.started ?? att.calls[0].at
  return (
    <ol className="kt-calls" aria-label="它做了什么">
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

// ---------------------------------------------------------------------------------------------
// the site
// ---------------------------------------------------------------------------------------------

function SiteTab({ api, run }: { api: AppApi; run: RunDetail }) {
  const ended = isEnded(run)
  const [st, setSt] = useState<SiteStatus | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [reload, setReload] = useState(0)
  const load = useCallback(() => {
    api
      .get<SiteStatus>(paths.site(run.id))
      .then(setSt)
      .catch((e) => setErr(errorText(e)))
  }, [api, run.id])
  useEffect(load, [load])
  useEffect(() => {
    if (st?.state !== 'running') return
    const t = setInterval(load, 5000) // the server's output, and whether it is still up
    return () => clearInterval(t)
  }, [st?.state, load])
  const act = (path: string) => {
    setBusy(true)
    setErr('')
    api
      .post<SiteStatus>(path, {})
      .then(setSt)
      .catch((e) => setErr(errorText(e)))
      .finally(() => setBusy(false))
  }
  if (!ended) return <p className="kt-dim">运行结束以后才能打开网站：运行中 app 要在运行分支的目录里合并和跑测试。</p>
  const up = st?.state === 'running' && st.url
  return (
    <div className="kt-site">
      <div className="kt-site-bar">
        {up ? (
          <>
            <span className="kt-pill tone-ok">● 在跑</span>
            <a className="kt-mono" href={st.url!} target="_blank" rel="noreferrer">
              {st.url} ↗
            </a>
            <span className="kt-dim">{st.entry}</span>
            <span className="kt-grow" />
            <button type="button" className="kt-btn is-small" onClick={() => setReload((n) => n + 1)}>
              刷新
            </button>
            <button type="button" className="kt-btn is-small is-danger" onClick={() => act(paths.siteStop(run.id))} disabled={busy}>
              停止
            </button>
          </>
        ) : (
          <>
            <button type="button" className="kt-btn is-primary" onClick={() => act(paths.site(run.id))} disabled={busy}>
              {busy ? '启动中…' : '启动网站'}
            </button>
            <span className="kt-dim">在本机一个空闲端口上运行团队写的服务（`npm start` 的入口），半小时后自己停。</span>
          </>
        )}
      </div>
      {err && (
        <p className="kt-error" role="alert">
          {err}
        </p>
      )}
      {st?.state === 'failed' && st.error && (
        <p className="kt-error" role="alert">
          {st.error}
        </p>
      )}
      {up && <iframe key={reload} src={st.url!} title="团队做出来的网站" className="kt-site-frame" />}
      {st && st.log.length > 0 && (
        <details className="kt-site-log" open={st.state === 'failed'}>
          <summary>服务的输出（{st.log.length} 行）</summary>
          <pre className="kt-mono">{st.log.join('\n')}</pre>
        </details>
      )}
    </div>
  )
}
