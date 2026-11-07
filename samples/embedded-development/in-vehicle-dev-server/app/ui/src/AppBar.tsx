import { lang, presentation, setLang, setPresentation, t as tr, type Lang } from './i18n'
/**
 * The app bar the views share: the app's name, the views as tabs — 团队看板 (how the run went), 评分卡 (the measured
 * figures over the runs) — 下一步需要你 (how many gates and bench requests wait for the person on the board) and 投影. It stays where it is when the view changes, and 投影 belongs to the
 * app, not to a view: full screen goes on, the person moves between views, it stays on. Each view's own controls
 * (the run, 回放, 新需求 … on the board) sit in the row below.
 */

export type ViewKind = 'board' | 'score'

export const APP_CSS = `
.kt-app { display: flex; flex-direction: column; min-height: 100%; color: var(--text); font-family: var(--font-body, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif); }
.kt-appbar { display: flex; align-items: center; gap: 6px 18px; flex-wrap: wrap; padding: 10px 20px 0; border-bottom: 1px solid var(--border); font-size: 14px; }
.kt-appbar h1 { margin: 0; font-size: 14px; font-weight: 700; color: var(--muted); letter-spacing: .04em; white-space: nowrap; }
.kt-tabs { display: flex; gap: 4px; align-self: stretch; }
.kt-tabs button { appearance: none; border: 0; border-bottom: 2px solid transparent; background: transparent; color: var(--text); font: inherit; font-weight: 650;
  padding: 8px 12px 9px; margin-bottom: -1px; cursor: pointer; white-space: nowrap; }
.kt-tabs button:hover { color: var(--text-strong); }
.kt-tabs button[aria-selected="true"] { border-bottom-color: var(--accent); color: var(--text-strong); }
.kt-tabs button:focus-visible, .kt-appbar .kt-btn:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.kt-appbar-grow { flex: 1; }
.kt-needs { display: inline-flex; align-items: center; gap: 6px; padding: 3px 10px; border-radius: 999px; font-weight: 750; color: var(--kt-approve, var(--accent)); border: 1px solid currentColor; }
.kt-needs b { min-width: 1.4em; text-align: center; border-radius: 999px; color: var(--kt-on, #fff); background: var(--kt-approve, var(--accent)); }
.kt-appbar .kt-btn { padding: 5px 12px; margin: 4px 0 6px; }
.kt-lang { display: inline-flex; border: 1px solid var(--border); border-radius: 999px; overflow: hidden; margin: 4px 0 6px; }
.kt-lang button { appearance: none; border: 0; background: transparent; color: var(--muted); font: inherit; font-size: 12px; font-weight: 650; padding: 4px 10px; cursor: pointer; }
.kt-lang button[aria-pressed="true"] { background: var(--accent); color: var(--kt-on, #fff); }
.kt-lang button:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
.kt-app.is-projection { position: fixed; inset: 0; z-index: 2147483000; height: 100vh; background: var(--bg); }
.kt-app.is-projection > .kt-appbar { flex: none; padding: 8px 26px 0; }
.kt-app.is-projection > .kt-root.is-projection { position: relative; inset: auto; z-index: auto; flex: 1 1 auto; min-height: 0; height: auto; }
`

const TABS: [ViewKind, string, string][] = [
  ['board', tr('AppBar.1'), tr('AppBar.2')],
  ['score', tr('AppBar.3'), tr('AppBar.4')],
]

export function AppBar({ view, projection, onView, onProjection, needs = 0 }: { view: ViewKind | 'item'; projection: boolean; onView: (v: ViewKind) => void; onProjection: () => void; needs?: number }) {
  return (
    <header className="kt-appbar" data-testid="kt-appbar">
      <h1>{tr('AppBar.5')}</h1>
      <div className="kt-tabs" role="tablist" aria-label={tr('AppBar.6')}>
        {TABS.map(([k, name, hint]) => (
          <button type="button" role="tab" key={k} aria-selected={view === k} title={hint} onClick={() => view !== k && onView(k)}>
            {name}
          </button>
        ))}
      </div>
      <span className="kt-appbar-grow" />
      {needs > 0 && (
        <span className="kt-needs" role="status" data-testid="kt-needs" title={tr('AppBar.7')}>
          {tr('AppBar.8')} <b>{needs}</b>
        </span>
      )}
      <LangSwitch />
      <PresentSwitch />
      <button type="button" className={`kt-btn${projection ? ' is-on' : ''}`} onClick={onProjection} title={projection ? tr('AppBar.9') : tr('AppBar.10')}>
        {projection ? tr('AppBar.11') : tr('AppBar.12')}
      </button>
    </header>
  )
}

const LANGS: Lang[] = ['zh', 'en']

/** 中文 / English, each named in its own language: the board's language, kept in this browser (switching reloads the
 * page, so what is built once at load is in the new language too). Chinese until the person picks English. */
export function LangSwitch() {
  const now = lang()
  return (
    <span className="kt-lang" role="group" aria-label={tr('AppBar.lang')} data-testid="kt-lang">
      {LANGS.map((l) => (
        <button type="button" key={l} lang={l === 'zh' ? 'zh-CN' : 'en'} aria-pressed={now === l} onClick={() => now !== l && setLang(l)}>
          {tr(`AppBar.lang.${l}`)}
        </button>
      ))}
    </span>
  )
}

/** 演示模式 / Presentation mode: the people shown as their role (负责人 / Release owner) for a recording; this
 * Mac's home folder is always shown as ~. Kept in this browser, off by default; switching reloads the page. */
export function PresentSwitch() {
  const on = presentation()
  return (
    <button type="button" className={`kt-btn${on ? ' is-on' : ''}`} aria-pressed={on} data-testid="kt-present"
      title={tr('AppBar.present.hint')} onClick={() => setPresentation(!on)}>
      {tr('AppBar.present')}
    </button>
  )
}

