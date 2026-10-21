/**
 * 打开文件夹: where a run's code is on this Mac, and a way there. The run branch's worktree holds the whole project as
 * merged so far; every writing role also has its own worktree. The backend opens only those (Finder or the Kiro IDE).
 */
import { useState } from 'react'
import type { AppApi } from '@kirocrew/app-sdk'
import { paths } from './format'
import { errorText } from './useBoard'

export function FolderActions({ api, run, role, path }: { api: AppApi; run: string; role: string | null; path: string | null }) {
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const open = (app: 'finder' | 'kiro') => {
    setMsg(null)
    api
      .post<{ ok: boolean; path: string; app: string }>(paths.open(run), { role, app })
      .then((r) => setMsg({ ok: true, text: app === 'kiro' ? '已经用 Kiro 打开' : '已经在 Finder 里打开' }))
      .catch((e) => setMsg({ ok: false, text: errorText(e) }))
  }
  const copy = () => {
    if (!path) return
    const done = () => setMsg({ ok: true, text: '路径已复制' })
    const fail = () => setMsg({ ok: false, text: '复制不了，手动选中上面的路径' })
    if (navigator.clipboard?.writeText) navigator.clipboard.writeText(path).then(done, fail)
    else fail()
  }
  return (
    <div className="kt-folder" data-testid="kt-folder">
      {path && (
        <code className="kt-folder-path" title={path}>
          {path}
        </code>
      )}
      <span className="kt-folder-acts">
        <button type="button" className="kt-btn is-small" onClick={() => open('finder')}>
          📁 在 Finder 打开
        </button>
        <button type="button" className="kt-btn is-small" onClick={() => open('kiro')}>
          用 Kiro 打开
        </button>
        {path && (
          <button type="button" className="kt-btn is-small" onClick={copy}>
            复制路径
          </button>
        )}
        {msg && (
          <span role="status" className={msg.ok ? 'kt-dim' : 'kt-error'}>
            {msg.text}
          </span>
        )}
      </span>
    </div>
  )
}

/** Under the top bar: the run's own folder. */
export function FolderPanel({ api, run, folder, onClose }: { api: AppApi; run: string; folder: string; onClose: () => void }) {
  return (
    <section className="kt-folder-panel" aria-label="项目文件夹">
      <div className="kt-folder-panel-head">
        <strong>项目文件夹</strong>
        <span className="kt-dim">运行分支检出在这里：团队合并进来的全部代码。每个角色自己的工作目录在「产出」里打开。</span>
        <span className="kt-grow" />
        <button type="button" className="kt-btn is-small" onClick={onClose} aria-label="收起项目文件夹">
          ✕
        </button>
      </div>
      <FolderActions api={api} run={run} role={null} path={folder} />
    </section>
  )
}
