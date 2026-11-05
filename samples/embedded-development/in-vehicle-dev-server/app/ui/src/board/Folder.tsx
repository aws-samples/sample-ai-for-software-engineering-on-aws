/**
 * 打开文件夹: where a run's code is on this Mac, and a way there. The run branch's worktree holds the whole project as
 * merged so far; every writing role also has its own worktree. The backend opens only those (Finder or the Kiro IDE).
 */
import { useState } from 'react'
import type { AppApi } from '@kirocrew/app-sdk'
import { paths } from './format'
import { errorText } from './useBoard'
import { t as tr } from '../i18n'

export function FolderActions({ api, run, role, path }: { api: AppApi; run: string; role: string | null; path: string | null }) {
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const open = (app: 'finder' | 'kiro') => {
    setMsg(null)
    api
      .post<{ ok: boolean; path: string; app: string }>(paths.open(run), { role, app })
      .then((r) => setMsg({ ok: true, text: app === 'kiro' ? tr('board.Folder.1') : tr('board.Folder.2') }))
      .catch((e) => setMsg({ ok: false, text: errorText(e) }))
  }
  const copy = () => {
    if (!path) return
    const done = () => setMsg({ ok: true, text: tr('board.Folder.3') })
    const fail = () => setMsg({ ok: false, text: tr('board.Folder.4') })
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
          {tr('board.Folder.5')}
        </button>
        <button type="button" className="kt-btn is-small" onClick={() => open('kiro')}>
          {tr('board.Folder.6')}
        </button>
        {path && (
          <button type="button" className="kt-btn is-small" onClick={copy}>
            {tr('board.Folder.7')}
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
    <section className="kt-folder-panel" aria-label={tr('board.Folder.8')}>
      <div className="kt-folder-panel-head">
        <strong>{tr('board.Folder.8')}</strong>
        <span className="kt-dim">{tr('board.Folder.9')}</span>
        <span className="kt-grow" />
        <button type="button" className="kt-btn is-small" onClick={onClose} aria-label={tr('board.Folder.10')}>
          ✕
        </button>
      </div>
      <FolderActions api={api} run={run} role={null} path={folder} />
    </section>
  )
}
