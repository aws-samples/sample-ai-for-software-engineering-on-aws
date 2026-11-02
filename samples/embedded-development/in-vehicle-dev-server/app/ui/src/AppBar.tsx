/**
 * The app bar the views share: the app's name, the views as tabs — 团队看板 (how the run went), 评分卡 (the measured
 * figures over the runs) — and 投影. It stays where it is when the view changes, and 投影 belongs to the
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
.kt-appbar .kt-btn { padding: 5px 12px; margin: 4px 0 6px; }
.kt-app.is-projection { position: fixed; inset: 0; z-index: 2147483000; height: 100vh; background: var(--bg); }
.kt-app.is-projection > .kt-appbar { flex: none; padding: 8px 26px 0; }
.kt-app.is-projection > .kt-root.is-projection { position: relative; inset: auto; z-index: auto; flex: 1 1 auto; min-height: 0; height: auto; }
`

const TABS: [ViewKind, string, string][] = [
  ['board', '团队看板', '多 agent 团队怎么交付：角色、关卡、检查、签字'],
  ['score', '评分卡', '量出来的数：分诊、检查、台架、独立重跑，按次和合计'],
]

export function AppBar({ view, projection, onView, onProjection }: { view: ViewKind; projection: boolean; onView: (v: ViewKind) => void; onProjection: () => void }) {
  return (
    <header className="kt-appbar" data-testid="kt-appbar">
      <h1>AIDLC-Embedded团队</h1>
      <div className="kt-tabs" role="tablist" aria-label="视图">
        {TABS.map(([k, name, hint]) => (
          <button type="button" role="tab" key={k} aria-selected={view === k} title={hint} onClick={() => view !== k && onView(k)}>
            {name}
          </button>
        ))}
      </div>
      <span className="kt-appbar-grow" />
      <button type="button" className={`kt-btn${projection ? ' is-on' : ''}`} onClick={onProjection} title={projection ? '退出投影（Esc）' : '全屏、大字；切换视图时保持投影'}>
        {projection ? '退出投影' : '投影'}
      </button>
    </header>
  )
}
