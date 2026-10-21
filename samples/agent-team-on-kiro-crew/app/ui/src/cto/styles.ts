/**
 * The CTO view's stylesheet. Its root also carries `kt-root`, so the host's theme variables (--bg, --card, --text …),
 * the board's status colours (--kt-approve: waiting for a person, --kt-ok …) and its buttons (kt-btn) are the board's.
 * Its own classes start with `cto-`. Chart colours (validated with the dataviz palette checks on the host's card in
 * both modes): 新应用 blue, 新功能 orange, 修复 grey; 以前 grey, 现在 a data violet; the 价值流 of 交付详情: agent violet,
 * 等人批准 magenta, 返工 yellow (dark #9085e9 · #d55181 · #c98500, light #6250d6 · #e87ba4 · #eda100: all pairs pass; in light
 * mode magenta and yellow are under 3:1 on white, so every segment is labelled and there is a table view).
 * Printing (PDF) keeps this view only, in the light theme, without the controls.
 */

const LIGHT_HOST = `--bg: #fff; --bg-hover: #f0f0f0; --card: #fff; --text: #4a464f; --text-strong: #19161d; --muted: #5e5966;
  --border: #e4e4e7; --border-strong: #d4d4d8; --kt-approve: #b8237a; --kt-ok: #0a7d45;`
const LIGHT_DATA = `--s1: #2a78d6; --s2: #eb6834; --s3: #b9b6bf; --s4: #6250d6; --deemph: #b9b6bf; --cto-cell: #f7f7f8; --vs-person: #e87ba4; --vs-rework: #eda100;`

export const CTO_CSS = `
.cto-root { --s1: #3987e5; --s2: #d95926; --s3: #6b6673; --s4: #9085e9; --deemph: #6b6673; --cto-cell: var(--bg, #19161d);
  --vs-agent: var(--s4); --vs-person: #d55181; --vs-rework: #c98500;
  --cto-wash: color-mix(in srgb, var(--accent) 10%, transparent); --cto-fresh: color-mix(in srgb, var(--accent) 16%, transparent);
  --cto-glass: color-mix(in srgb, var(--text) 4%, transparent); gap: 16px; }
:root[data-mode="light"] .cto-root { ${LIGHT_DATA} }
.cto-root.is-printing { ${LIGHT_HOST} ${LIGHT_DATA} background: #fff; color: #4a464f; }
.cto-root [hidden] { display: none !important; }
.cto-root .kt-btn.is-small { padding: 3px 10px; font-size: 13px; border-radius: 8px; }
.cto-tag { display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: 12px; border: 1px solid var(--border); color: var(--text); }
.cto-tag.is-real { border-color: var(--accent); color: var(--text-strong); background: var(--cto-fresh); }
.cto-dim { color: var(--muted); }

.cto-top { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.cto-top h1 { margin: 0; font-size: 15px; font-weight: 700; color: var(--text); }
.cto-top .cto-org { color: var(--text); font-size: 14px; }
.cto-grow { flex: 1; }
.cto-dl { position: relative; }
.cto-dl summary { list-style: none; }
.cto-dl summary::-webkit-details-marker { display: none; }
.cto-menu { position: absolute; right: 0; top: calc(100% + 6px); z-index: 20; min-width: 280px; padding: 6px; border-radius: 12px; border: 1px solid var(--border-strong); background: var(--card); box-shadow: 0 12px 30px rgba(0,0,0,.3); display: grid; }
.cto-menu button { text-align: left; border: 0; background: transparent; padding: 8px 10px; border-radius: 8px; cursor: pointer; font: inherit; color: var(--text); }
.cto-menu button:hover { background: var(--bg-hover); }

.cto-hero h2 { margin: 6px 0 0; font-size: 32px; line-height: 1.3; font-weight: 700; color: var(--text-strong); }
.cto-hero p { margin: 6px 0 0; color: var(--text); }
.cto-lines { display: flex; flex-wrap: wrap; gap: 8px; }
.cto-lines button { display: inline-flex; align-items: baseline; gap: 8px; padding: 6px 14px; border-radius: 999px; border: 1px solid var(--border); background: var(--card); cursor: pointer; font: inherit; color: var(--text); }
.cto-lines button b { color: var(--text-strong); }
.cto-lines button span { color: var(--muted); font-size: 13px; }
.cto-lines button[aria-pressed="true"] { border-color: var(--accent); background: var(--cto-fresh); }

.cto-card { position: relative; } /* frame, padding, glass: kit.ts */
.cto-cards { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; }
.cto-value { margin: 6px 0 2px; } /* type: kit.ts */
.cto-desc { color: var(--text); }
.cto-mini { position: relative; margin-top: 14px; }
.cto-mini svg { display: block; width: 100%; overflow: visible; }
.cto-mini text, .cto-plot text { font-size: 12px; fill: var(--muted); font-variant-numeric: tabular-nums; }
.cto-mini text.is-strong { fill: var(--text-strong); font-weight: 600; font-size: 13px; }
.cto-plot .cto-mark { fill: var(--text); }
.cto-hit { fill: transparent; outline: none; cursor: default; }
.cto-hit:hover, .cto-hit:focus { fill: var(--cto-wash); }
.cto-legend { display: flex; flex-wrap: wrap; gap: 4px 12px; margin-top: 8px; font-size: 13px; color: var(--text); }
.cto-legend > span, .cto-legend > button { display: inline-flex; align-items: center; gap: 6px; }
.cto-legend > button { border: 0; background: transparent; padding: 2px 6px; margin-left: -6px; border-radius: 6px; cursor: pointer; color: inherit; font: inherit; }
.cto-legend > button b { color: var(--text-strong); font-weight: 600; font-variant-numeric: tabular-nums; }
.cto-legend > button:hover, .cto-legend > button[aria-pressed="true"] { background: var(--cto-fresh); }
.cto-sw { width: 10px; height: 10px; border-radius: 2px; display: inline-block; flex: none; }
.cto-dot { width: 9px; height: 9px; border-radius: 50%; display: inline-block; flex: none; }
.cto-foot { margin-top: 8px; font-size: 13px; color: var(--text); display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.cto-link { border: 0; background: transparent; color: var(--accent); cursor: pointer; padding: 0; font: inherit; }
.cto-calc { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-top: 6px; font-size: 13px; color: var(--text); }
.cto-calc input { width: 96px; padding: 3px 8px; border-radius: 8px; border: 1px solid var(--border); background: var(--cto-cell); color: var(--text-strong); font: inherit; }
.cto-calc b { color: var(--text-strong); }
.cto-flash { animation: cto-flash 1.6s ease-out; }
@keyframes cto-flash { 0% { background: var(--cto-fresh); } 100% { background: transparent; } }
.cto-tip { position: absolute; z-index: 10; pointer-events: none; background: var(--card); border: 1px solid var(--border-strong); border-radius: 10px; padding: 8px 10px; font-size: 13px; box-shadow: 0 8px 24px rgba(0,0,0,.25); min-width: 200px; }
.cto-tip .cto-when { color: var(--muted); margin-bottom: 4px; white-space: nowrap; }
.cto-tip .cto-row { display: flex; align-items: center; gap: 8px; }
.cto-tip .cto-row b { min-width: 40px; text-align: right; font-variant-numeric: tabular-nums; color: var(--text-strong); }
.cto-tip .cto-key { width: 12px; height: 2px; border-radius: 1px; }
.cto-tip .cto-row span { color: var(--text); }

.cto-chart-head { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }
.cto-plot { position: relative; height: 270px; }
.cto-plot svg { display: block; width: 100%; height: 100%; }
.cto-seg { display: inline-flex; border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
.cto-seg button { border: 0; background: transparent; padding: 5px 12px; cursor: pointer; font: inherit; color: var(--text); }
.cto-seg button[aria-pressed="true"] { background: var(--cto-fresh); font-weight: 600; color: var(--text-strong); }
.cto-table { width: 100%; border-collapse: collapse; font-size: 14px; }
.cto-table th { text-align: left; font-weight: 600; color: var(--text); padding: 8px 10px; border-bottom: 1px solid var(--border); white-space: nowrap; }
.cto-table td { padding: 9px 10px; border-bottom: 1px solid var(--border); vertical-align: top; color: var(--text-strong); }
.cto-table .is-num { text-align: right; font-variant-numeric: tabular-nums; }
.cto-weeks { max-height: 270px; overflow: auto; }

.cto-flow-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.cto-live { width: 8px; height: 8px; border-radius: 50%; background: var(--kt-ok); flex: none; animation: cto-pulse 1.6s infinite; }
@keyframes cto-pulse { 50% { opacity: .35; } }
.cto-stats { font-size: 18px; font-weight: 650; margin-top: 10px; color: var(--text-strong); }
.cto-stats span { color: var(--muted); font-weight: 400; margin: 0 6px; }
.cto-kanban { display: grid; grid-template-columns: 88px repeat(6, minmax(0, 1fr)); gap: 6px; margin-top: 12px; }
.cto-kb-h { padding: 4px 8px; }
.cto-kb-h b { font-size: 14px; color: var(--text-strong); }
.cto-kb-h .cto-n { color: var(--muted); margin-left: 6px; font-variant-numeric: tabular-nums; }
.cto-kb-h .cto-st { color: var(--muted); font-size: 12px; }
.cto-lane { white-space: nowrap; display: flex; align-items: center; justify-content: center; text-align: center; font-size: 13px; font-weight: 600; color: var(--text); border-radius: 10px; background: var(--cto-cell); padding: 6px; }
.cto-lane.is-wait { color: var(--text-strong); background: color-mix(in srgb, var(--kt-approve) 16%, var(--cto-cell)); }
.cto-cell { background: var(--cto-cell); border-radius: 10px; padding: 6px; display: grid; gap: 6px; align-content: start; min-height: 60px; }
.cto-cell.is-wait { background: color-mix(in srgb, var(--kt-approve) 6%, var(--cto-cell)); }
.cto-cell.is-span { grid-row: span 2; }
.cto-kcard { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 6px 8px; font-size: 12.5px; display: grid; gap: 2px; min-width: 0; text-align: left; color: var(--text); font-family: inherit; }
.cto-kcard .cto-ktop { display: flex; justify-content: space-between; gap: 6px; color: var(--muted); font-size: 12px; white-space: nowrap; }
.cto-kcard .cto-gate { color: var(--kt-approve); font-weight: 600; }
.cto-kcard .cto-ktitle { font-size: 13px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: var(--text-strong); }
.cto-kcard .cto-kfocus { color: var(--text); }
.cto-kcard .cto-kmeta { color: var(--muted); font-size: 12px; }
.cto-kcard .kt-btn { justify-self: start; margin-top: 4px; }
.cto-kcard.is-live { cursor: pointer; } /* its border says its state: kit.ts */
.cto-kcard.is-real { cursor: pointer; } /* 实测 is its tag, not its border */
.cto-kcard.is-new { animation: cto-flash 2.4s ease-out; }
.cto-kmore, .cto-kempty { color: var(--muted); font-size: 12px; padding: 0 4px; }
.cto-pop { position: absolute; z-index: 15; width: 440px; padding: 14px 16px; border-radius: 14px; border: 1px solid var(--accent); background: var(--card); box-shadow: 0 16px 40px rgba(0,0,0,.35); display: grid; gap: 8px; }
.cto-pop-head { display: flex; align-items: center; gap: 8px; }
.cto-pop-head b { font-size: 15px; color: var(--text-strong); }
.cto-pop-head .cto-x { margin-left: auto; border: 0; background: transparent; color: var(--muted); font-size: 18px; cursor: pointer; line-height: 1; }
.cto-pop-facts { color: var(--text); font-size: 13px; }
.cto-decisions { margin: 0; padding: 0; list-style: none; display: grid; gap: 6px; font-size: 14px; color: var(--text-strong); }
.cto-decisions li { display: grid; grid-template-columns: 72px 1fr; gap: 8px; }
.cto-decisions li b { font-weight: 600; white-space: nowrap; }
.cto-pop-act { display: flex; gap: 8px; margin-top: 2px; }

.cto-ledger-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 6px; }
.cto-kind { display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; }
.cto-was { color: var(--muted); font-size: 12px; }
.cto-defect { color: var(--kt-warn); font-size: 12px; }
.cto-ids { white-space: nowrap; font-size: 13px; }
.cto-ids .cto-was { font-family: var(--font-body, sans-serif); }
.cto-ids .cto-was.kt-mono { font-family: var(--mono, ui-monospace, monospace); }
.cto-table tr.is-real td { background: color-mix(in srgb, var(--accent) 6%, transparent); }
.cto-table tr.is-new td { animation: cto-flash 2.4s ease-out; }
.cto-src { display: flex; gap: 6px; align-items: center; white-space: nowrap; }
.cto-notes { color: var(--muted); font-size: 13px; }
.cto-notes summary { cursor: pointer; color: var(--text); }
.cto-notes ul { margin: 8px 0 0; padding-left: 18px; display: grid; gap: 4px; }
.cto-toast { position: fixed; left: 50%; bottom: 24px; transform: translateX(-50%); z-index: 30; padding: 10px 16px; border-radius: 12px; background: var(--bg-hover); border: 1px solid var(--border); font-size: 14px; color: var(--text-strong); max-width: 640px; }

/* 交付详情: built from the CTO view's cards and charts and the board's pills, chips and icons */
.cto-item-head { display: flex; align-items: center; gap: 8px 12px; flex-wrap: wrap; }
.cto-item-head .kt-run-title { margin: 0; }
.cto-item-head .cto-org { color: var(--text); font-size: 14px; }
.cto-item-now { margin: -6px 0 0; color: var(--text-strong); font-size: 14px; }
.cto-item-act { display: flex; gap: 8px; flex-wrap: wrap; }
.cto-item-cards { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.cto-value .cto-of { font-size: .5em; margin-left: 6px; } /* half the number: as big as the board's 「/38」 */
.cto-chips { display: flex; gap: 4px; flex-wrap: wrap; margin-top: 14px; }
.cto-chip { width: 26px; height: 26px; display: inline-grid; place-items: center; flex: none; border-radius: 8px; border: 2px solid var(--kt-ok-solid); background: var(--kt-ok-solid); color: #fff; }
.cto-chip.is-small { width: 22px; height: 22px; border-radius: 7px; }
.cto-chip.is-idle { border-style: dashed; border-color: var(--border-strong); background: transparent; color: var(--muted); opacity: .7; }
.cto-chip.is-back { border-color: var(--vs-rework); background: color-mix(in srgb, var(--vs-rework) 18%, transparent); color: var(--text-strong); }
.cto-chip.is-wait { border-color: var(--vs-person); background: color-mix(in srgb, var(--vs-person) 18%, transparent); color: var(--text-strong); }
.cto-chip.is-plain { border-color: var(--border-strong); background: transparent; color: var(--text-strong); }
.cto-segs { border: 0; background: transparent; padding: 0; margin-top: 14px; width: 100%; cursor: pointer; }
.cto-segs i { height: 10px; }
.cto-legend > button:disabled { cursor: default; color: var(--muted); }
.cto-legend > button .kt-role-icon { color: var(--vs-rework); }
.cto-gatecell { display: inline-flex; align-items: center; gap: 8px; white-space: nowrap; font-weight: 600; }
.cto-item-chain { display: flex; gap: 18px; align-items: center; flex-wrap: wrap; margin-top: 10px; }
.cto-chainpart { display: flex; gap: 10px; align-items: flex-start; }
.cto-chainpart b, .cto-chainpart .cto-link { font-size: 15px; color: var(--text-strong); }
.cto-chainpart .cto-link { color: var(--accent); }
.cto-item-arrow { font-size: 22px; color: var(--muted); }
.cto-item-twinrow { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin-top: 12px; padding: 12px 14px; border-radius: 12px; border: 1px solid var(--border); background: var(--cto-glass); }
.cto-item-twinrow > div { flex: 1 1 320px; }
.cto-vs-plot { margin-top: 10px; }
.cto-vs-plot text { font-size: 12px; fill: var(--muted); font-variant-numeric: tabular-nums; }
.cto-vs-plot text.is-strong { fill: var(--text-strong); font-weight: 600; font-size: 13px; }
.cto-vs-plot .cto-vs-lane { fill: var(--muted); }
.cto-vs-chip rect { fill: var(--kt-ok-solid); }
.cto-vs-chip .kt-role-icon { color: #fff; }
.cto-vs-chip.is-wait rect { fill: color-mix(in srgb, var(--vs-person) 22%, var(--card)); stroke: var(--vs-person); stroke-width: 1.5; }
.cto-vs-chip.is-wait .kt-role-icon { color: var(--text-strong); }
.cto-vs-tick { stroke: var(--border-strong); stroke-dasharray: 2 3; }
.cto-vs-moment circle { fill: var(--card); stroke: var(--border-strong); stroke-width: 1.5; }
.cto-vs-moment .kt-role-icon { color: var(--text-strong); }
.cto-vs-moment.is-wait circle { stroke: var(--vs-person); }
.cto-vs-moment.is-ok circle { stroke: var(--kt-ok); }
.cto-vs-moment.is-back circle { stroke: var(--vs-rework); }
.cto-vs-seg path { transition: filter .15s; }
.cto-vs-seg:hover path { filter: brightness(1.12); }
.cto-vs-seg.is-hl path { stroke: var(--text-strong); stroke-width: 2; }
.cto-vs-seg.is-hl text.is-strong { fill: var(--accent); }

/* the other two views: rows, cards and headings that open the next layer */
.cto-link-value { border: 0; background: transparent; padding: 0; font-family: inherit; color: var(--text-strong); cursor: pointer; text-align: left; display: block; }
.cto-link-value:hover { color: var(--accent); }
.cto-row-pick { cursor: pointer; }
.cto-row-pick:hover td { background: var(--cto-glass); }
.cto-row-pick:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
.cto-link-value:hover { text-decoration: underline; text-decoration-thickness: 2px; text-underline-offset: 6px; }
.cto-table tr.is-hl td { animation: cto-flash 2.4s ease-out 2; background: var(--cto-fresh); }
.cto-kcard.is-hl { outline: 2px solid var(--accent); outline-offset: 2px; }
.cto-pick { cursor: pointer; }
.cto-kb-h button, .cto-lane button { border: 0; background: transparent; padding: 0; font: inherit; color: inherit; cursor: pointer; text-align: left; display: inline-flex; align-items: center; gap: 6px; }
.cto-kb-h button { display: block; }
.cto-kb-h button:hover b, .cto-lane button:hover { color: var(--accent); }
.cto-lane .kt-role-icon { color: var(--kt-approve); }
.cto-gate { display: inline-flex; align-items: center; gap: 4px; }
.cto-filter { display: inline-flex; align-items: center; gap: 6px; border: 1px solid var(--accent); border-radius: 999px; padding: 1px 4px 1px 10px; font-size: 13px; color: var(--text-strong); background: var(--cto-fresh); }
.cto-filter button { border: 0; background: transparent; cursor: pointer; color: var(--muted); font: inherit; }
.cto-hit.is-pick { cursor: pointer; }
@media (max-width: 960px) { .cto-item-cards { grid-template-columns: 1fr 1fr; } }

.cto-root.is-projection { position: fixed; inset: 0; z-index: 2147483000; overflow: auto; background: var(--bg); font-size: 18px; padding: 24px 48px 60px; }
.cto-root.is-projection .cto-hero h2 { font-size: 46px; }
.cto-root.is-projection .cto-value { font-size: 56px; }
.cto-root.is-projection .cto-mini text { font-size: 15px; }
.cto-root.is-projection .cto-mini text.is-strong { font-size: 16px; }
.cto-root.is-projection .cto-noproj { display: none !important; }

.cto-print-only { display: none; }
@media print {
  @page { size: A4 landscape; margin: 10mm; }
  body * { visibility: hidden; }
  .cto-root, .cto-root * { visibility: visible; }
  .cto-root { position: absolute; left: 0; top: 0; width: 100%; padding: 0; font-size: 11px; }
  .cto-root .cto-noprint, .cto-root .cto-tip, .cto-root .cto-pop, .cto-root .cto-toast, .cto-root .cto-calc, .cto-root .cto-link { display: none !important; }
  .cto-lines button:not([aria-pressed="true"]) { display: none; }
  .cto-print-only { display: block; color: var(--muted); margin: 4px 0 8px; }
  .cto-card, .cto-cell, .cto-kcard, .cto-table tr { break-inside: avoid; }
  .cto-flow { break-before: page; }
  .cto-hero h2 { font-size: 24px; } .cto-value { font-size: 28px; }
  .cto-plot { height: 220px; }
}
@media (max-width: 960px) { .cto-cards { grid-template-columns: 1fr; } .cto-kanban { grid-template-columns: 1fr; } .cto-cell.is-span { grid-row: auto; } .cto-pop { width: auto; left: 12px !important; right: 12px !important; } }
`
