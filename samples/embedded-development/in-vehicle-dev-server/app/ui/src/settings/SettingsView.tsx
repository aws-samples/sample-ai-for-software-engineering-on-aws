/**
 * 设置: the app's own settings (`GET /settings`, `POST /settings`; backend/team/settings.py), the dashboard owner's
 * to edit, as every route of this app is. Each field starts from the shipped team file's value, so an install that
 * never opens this page runs as before, and 恢复默认 puts a field back to it.
 *
 * The two MCP servers' configuration files belong to the servers: this page holds their paths and nothing of their
 * content. The block at the foot reads the build server's `[paths]` for the three `bench_*` entries its release
 * check needs and gives the lines to paste there; a person pastes them, in the server's own file (D17).
 *
 * The cards and blocks are the kit's (kit.ts), as the board's and the 评分卡's are.
 */
import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { useAppApi } from '../api'
import { BOARD_CSS } from '../board/styles'
import { paths } from '../board/format'
import { errorText } from '../board/useBoard'
import { KIT_CSS } from '../kit'
import type { Settings, SettingsPage } from '../types'
import { t as tr } from '../i18n'

const SET_CSS = `
.st-head h2 { margin: 0 0 4px; font-size: 1.4em; color: var(--text-strong); }
.st-head p { margin: 0; color: var(--muted); }
.st-root section.kt-card > h3 { margin: 0 0 4px; font-size: 1.1em; color: var(--text-strong); }
.st-root section.kt-card > p.st-why { margin: 0 0 12px; color: var(--muted); font-size: .9em; }
.st-field { display: grid; gap: 4px; margin-bottom: 14px; }
.st-field:last-child { margin-bottom: 0; }
.st-field > label { font-weight: 650; color: var(--text-strong); }
.st-field > small { color: var(--muted); }
.st-field input[type="text"], .st-field select { font: inherit; font-size: .95em; padding: 6px 9px; border-radius: 8px;
  border: 1px solid var(--border); background: var(--bg-elevated, var(--card)); color: var(--text); min-width: 0; }
.st-field input[type="text"] { font-family: var(--font-mono, ui-monospace, SFMono-Regular, Menlo, monospace); }
.st-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.st-row input[type="text"] { flex: 1 1 22em; }
.st-check { display: flex; align-items: baseline; gap: 8px; }
.st-check input { margin: 0; }
.st-guard { font-size: .76em; font-weight: 800; padding: 0 7px; border-radius: 999px; color: var(--kt-warn);
  border: 1px solid currentColor; }
.st-actions { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.st-lines { font-size: .86em; margin: 8px 0 0; padding: 8px 10px; border-radius: 8px; background: var(--kt-glass);
  white-space: pre; overflow-x: auto; }
.st-off { color: var(--muted); }
.kt-app.is-projection > .st-root { flex: 1 1 auto; min-height: 0; overflow: auto; font-size: 18px; }
`

/**
 * One text field: its label, a line of help under it, and 恢复默认 when it differs from the team file's value.
 * `id` is the field's own, written out here (as `st-board-decides` is) and the same in every language: a label's
 * text is for a person to read, not an HTML id — the translations hold spaces and an apostrophe.
 */
function PathField({ id, label, help, value, dflt, onChange }:
  { id: string; label: string; help: string; value: string; dflt: string; onChange: (v: string) => void }) {
  return (
    <div className="st-field">
      <label htmlFor={id}>{label}</label>
      <div className="st-row">
        <input id={id} type="text" value={value} spellCheck={false}
          onChange={(e) => onChange(e.target.value)} />
        {value !== dflt && (
          <button type="button" className="kt-btn" onClick={() => onChange(dflt)}>{tr('settings.reset')}</button>
        )}
      </div>
      <small>{help}</small>
    </div>
  )
}

export function SettingsView() {
  const api = useAppApi()
  const [page, setPage] = useState<SettingsPage | null>(null)
  const [draft, setDraft] = useState<Settings | null>(null)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)
  const [saving, setSaving] = useState(false)

  const take = useCallback((p: SettingsPage) => {
    setPage(p)
    setDraft(p.settings)
  }, [])

  useEffect(() => {
    let alive = true
    void (async () => {
      try {
        const p = await api.get<SettingsPage>(paths.settings())
        if (alive) take(p)
      } catch (e) {
        if (alive) setError(errorText(e))
      }
    })()
    return () => {
      alive = false
    }
  }, [api, take])

  const save = async () => {
    if (!draft) return
    setSaving(true)
    setError('')
    try {
      // what does not hold up comes back 400 with every problem in the message, and nothing is written
      take(await api.post<SettingsPage>(paths.settings(), { settings: draft }))
      setSaved(true)
    } catch (e) {
      setError(errorText(e))
    }
    setSaving(false)
  }

  const frame = (inner: ReactNode) => <div className="kt-root st-root" data-testid="st-root">{inner}</div>
  if (error && !draft) return frame(<p className="kt-error" role="alert">{error}</p>)
  if (!page || !draft) return frame(<p className="kt-loading">{tr('settings.loading')}</p>)

  const d = page.defaults
  const set = (patch: Partial<Settings>) => {
    setDraft({ ...draft, ...patch })
    setSaved(false)
  }
  const servers = draft.mode === 'servers'
  const release = page.release
  const changed = JSON.stringify(draft) !== JSON.stringify(page.settings)
  return (
    <div className="kt-root st-root" data-testid="st-root">
      <style>{BOARD_CSS}</style>
      <style>{SET_CSS}</style>
      <style>{KIT_CSS}</style>
      <header className="st-head">
        <h2>{tr('settings.title')}</h2>
        <p>{tr('settings.lead')}</p>
      </header>
      {error && <div className="kt-banner is-error" role="alert" data-testid="st-error">{error}</div>}
      {saved && !changed && (
        <div className="kt-banner" role="status" data-testid="st-saved">{tr('settings.saved')}</div>
      )}

      <section className="kt-card" data-testid="st-mode">
        <h3>{tr('settings.mode')}</h3>
        <p className="st-why">{tr('settings.mode.why')}</p>
        <div className="st-field">
          <label htmlFor="st-mode-pick">{tr('settings.mode.label')}</label>
          <select id="st-mode-pick" value={draft.mode}
            onChange={(e) => set({ mode: e.target.value as Settings['mode'] })}>
            <option value="direct">{tr('settings.mode.direct')}</option>
            <option value="servers">{tr('settings.mode.servers')}</option>
          </select>
          <small>{tr('settings.mode.hint', { p0: d.mode })}</small>
        </div>
      </section>

      <section className="kt-card" data-testid="st-servers">
        <h3>{tr('settings.servers')}</h3>
        <p className="st-why">{tr('settings.servers.why')}</p>
        <PathField id="st-build-config" label={tr('settings.servers.build')} help={tr('settings.servers.build.hint')}
          value={draft.server_configs.build} dflt={d.server_configs.build}
          onChange={(v) => set({ server_configs: { ...draft.server_configs, build: v } })} />
        <PathField id="st-bench-config" label={tr('settings.servers.bench')} help={tr('settings.servers.bench.hint')}
          value={draft.server_configs.bench} dflt={d.server_configs.bench}
          onChange={(v) => set({ server_configs: { ...draft.server_configs, bench: v } })} />
      </section>

      <section className="kt-card" data-testid="st-direct">
        <h3>{tr('settings.direct')}</h3>
        <p className="st-why">{servers ? tr('settings.direct.off') : tr('settings.direct.why')}</p>
        <PathField id="st-baseline" label={tr('settings.direct.baseline')} help={tr('settings.direct.baseline.hint')}
          value={draft.baseline} dflt={d.baseline} onChange={(v) => set({ baseline: v })} />
        <PathField id="st-docker-runner" label={tr('settings.direct.runner')} help={tr('settings.direct.runner.hint')}
          value={draft.docker.runner} dflt={d.docker.runner}
          onChange={(v) => set({ docker: { ...draft.docker, runner: v } })} />
        <PathField id="st-docker-host" label={tr('settings.direct.host')} help={tr('settings.direct.host.hint')}
          value={draft.docker.host} dflt={d.docker.host}
          onChange={(v) => set({ docker: { ...draft.docker, host: v } })} />
      </section>

      <section className="kt-card" data-testid="st-approve">
        <h3>{tr('settings.approve')} <span className="st-guard">{tr('settings.approve.guard')}</span></h3>
        <p className="st-why">{tr('settings.approve.why')}</p>
        <div className="st-field st-check">
          <input id="st-board-decides" type="checkbox" checked={draft.board_decides}
            onChange={(e) => set({ board_decides: e.target.checked })} />
          <label htmlFor="st-board-decides">{tr('settings.approve.label')}</label>
        </div>
        <small className="st-off">{tr('settings.approve.hint')}</small>
      </section>

      {release && (
        <section className="kt-card" data-testid="st-release">
          <h3>{tr('settings.release')}</h3>
          <p className="st-why">{tr('settings.release.why')}</p>
          <p data-testid="st-release-state">
            <b>{release.ok === true ? tr('settings.release.ok')
              : release.ok === false ? tr('settings.release.missing') : tr('settings.release.unknown')}</b>
            {' · '}{release.detail}
          </p>
          {release.config && <small className="st-off">{release.config}</small>}
          {release.paste_lines.length > 0 && (
            <pre className="st-lines" data-testid="st-release-lines">{release.paste_lines.join('\n')}</pre>
          )}
        </section>
      )}

      <div className="st-actions">
        <button type="button" className="kt-btn is-on" onClick={() => void save()} disabled={saving || !changed}
          data-testid="st-save">
          {saving ? tr('settings.saving') : tr('settings.save')}
        </button>
        {changed && (
          <button type="button" className="kt-btn" onClick={() => take(page)}>{tr('settings.cancel')}</button>
        )}
        <span className="kt-dim">{tr('settings.restart')}</span>
      </div>
    </div>
  )
}
