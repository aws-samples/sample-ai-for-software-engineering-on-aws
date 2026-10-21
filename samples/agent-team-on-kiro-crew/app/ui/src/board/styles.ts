/**
 * The board's stylesheet (one <style> tag; no CSS files). Only the host's theme variables (--text,
 * --text-strong, --bg, --bg-elevated, --card, --border, --border-strong, --muted, --accent, --mono)
 * plus the status colours derived here, one set per host mode. They were picked against the default
 * themes (kiro-dark: card #211d25; kiro-light: card #fff) for at least 4.5:1 as text on the card and
 * on their own 10–16 % tints; the solid fills (merged, failed, passed cells) carry white text at ≥ 5:1.
 *
 * Motion is state or a real event, never decoration: working roles pulse on one shared beat, queued
 * ones march, awaiting-approval blinks; everything else plays once per change (flash, flip, slide,
 * pop). Reduced motion (the media query, or data-motion="reduce" set from it) turns all of it off.
 */

const TONES = ['run', 'fix', 'ok', 'done', 'queue', 'warn', 'approve', 'bad', 'idle', 'handoff', 'info'] as const

const toneVars = TONES.map((t) => `.kt-root .tone-${t} { --kt-tone: var(--kt-${t}); }`).join('\n')

const LANE_TONE: Record<string, string> = {
  waiting: 'idle',
  queued: 'queue',
  running: 'run',
  stalled: 'warn',
  awaiting_approval: 'approve',
  done: 'done',
  merged: 'ok',
  fixing: 'fix',
  failed: 'bad',
}

const legendSwatches = Object.entries(LANE_TONE)
  .map(([s, t]) => `.kt-legend-item.is-${s} i { border-color: var(--kt-${t}); background: color-mix(in srgb, var(--kt-${t}) 16%, transparent); }`)
  .join('\n')

export const BOARD_CSS = `
.kt-root {
  --kt-run: #3cc4ff; --kt-fix: #ff9f43; --kt-ok: #3ee08f; --kt-ok-solid: #0b7a4b; --kt-done: #7fe3b8;
  --kt-queue: #9ba6ff; --kt-warn: #ffc53d; --kt-approve: #ff6ec7; --kt-bad: #ff5d6c; --kt-bad-solid: #c4253a;
  --kt-handoff: #b48cff; --kt-info: #8fb8ff; --kt-idle: var(--muted, #938f9b);
  --kt-on: #16121b; --kt-seg-l: .74; --kt-seg-c: .12; --kt-glass: color-mix(in srgb, var(--text, #dcdadf) 4%, transparent);
  color: var(--text); font-family: var(--font-body, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif); font-size: 14px; line-height: 1.45;
  display: flex; flex-direction: column; gap: 14px; padding: 16px 20px 28px; min-height: 100%; box-sizing: border-box;
}
:root[data-mode="light"] .kt-root {
  --kt-run: #0a6db5; --kt-fix: #c05200; --kt-ok: #0a7d45; --kt-ok-solid: #0a7d45; --kt-done: #0a7d45;
  --kt-queue: #4a4fd1; --kt-warn: #946200; --kt-approve: #b8237a; --kt-bad: #c8243b; --kt-bad-solid: #c8243b;
  --kt-handoff: #7b3fe4; --kt-info: #285092; --kt-on: #fff; --kt-seg-l: .62; --kt-seg-c: .13;
}
.kt-root *, .kt-root *::before, .kt-root *::after { box-sizing: border-box; }
${toneVars}
.kt-root :is(span, strong, b, em, time)[class*="tone-"] { color: var(--kt-tone); }
.kt-mono { font-family: var(--mono, ui-monospace, SFMono-Regular, Menlo, monospace); }
.kt-dim { color: var(--muted); }
.kt-sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); clip-path: inset(50%); white-space: nowrap; }
.kt-root :is(button, select, textarea, summary, input):focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.kt-root code { font-family: var(--mono, ui-monospace, monospace); font-size: .92em; }
.kt-loading { color: var(--muted); margin: 24px 0; }

/* ---------- buttons, pills, banners ---------- */
.kt-btn { appearance: none; font: inherit; font-size: .93em; font-weight: 650; padding: 7px 14px; border-radius: 10px; cursor: pointer;
  border: 1px solid var(--border-strong, var(--border)); background: var(--card); color: var(--text); transition: border-color .15s, background .15s; white-space: nowrap; }
.kt-btn:hover { border-color: var(--accent); }
.kt-btn:disabled { opacity: .6; cursor: progress; }
.kt-btn.is-primary { background: var(--accent); border-color: var(--accent); color: var(--accent-fg, #fff); }
.kt-btn.is-primary:hover { filter: brightness(1.08); }
.kt-btn.is-danger { color: var(--kt-bad); border-color: color-mix(in srgb, var(--kt-bad) 55%, var(--border)); }
.kt-btn.is-danger.is-solid { background: var(--kt-bad-solid); border-color: var(--kt-bad-solid); color: #fff; }
.kt-btn[aria-pressed="true"], .kt-btn.is-on { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 18%, var(--card)); color: var(--text-strong); }
.kt-select { font: inherit; font-size: .93em; padding: 7px 10px; border-radius: 10px; border: 1px solid var(--border-strong, var(--border)); background: var(--card); color: var(--text); max-width: 360px; }
.kt-pill { display: inline-flex; align-items: center; gap: 5px; padding: 2px 10px; border-radius: 999px; font-size: .86em; font-weight: 750; white-space: nowrap;
  color: var(--kt-tone); background: color-mix(in srgb, var(--kt-tone) 14%, transparent); border: 1px solid color-mix(in srgb, var(--kt-tone) 42%, transparent); }
.kt-pill i { font-style: normal; font-size: .9em; }
.kt-pill.is-live i { animation: kt-blink 1.6s ease-in-out infinite; }
.kt-root span.kt-badge { display: inline-flex; align-items: center; padding: 1px 8px; border-radius: 999px; font-size: .74em; font-weight: 800; background: var(--kt-tone); color: var(--kt-on); white-space: nowrap; }
.kt-banner { padding: 8px 12px; border-radius: 10px; border: 1px solid color-mix(in srgb, var(--kt-warn) 55%, var(--border)); background: color-mix(in srgb, var(--kt-warn) 10%, var(--card)); }
.kt-banner.is-error { border-color: color-mix(in srgb, var(--kt-bad) 60%, var(--border)); background: color-mix(in srgb, var(--kt-bad) 10%, var(--card)); }
.kt-replay { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; padding: 8px 12px; border-radius: 12px;
  border: 1px solid color-mix(in srgb, var(--kt-info, #60a5fa) 45%, var(--border)); background: color-mix(in srgb, var(--kt-info, #60a5fa) 8%, var(--card)); }
.kt-replay-scrub { flex: 1 1 240px; min-width: 160px; accent-color: var(--kt-info, #60a5fa); }
.kt-replay-time { font-size: .93em; min-width: 9ch; }
.kt-replay-speeds { display: inline-flex; gap: 4px; }
.kt-replay-speeds .kt-btn { padding: 4px 9px; font-size: .85em; }
.kt-replay-note { font-size: .86em; }
.kt-error { margin: 0; color: var(--kt-bad); font-weight: 650; }
.kt-focusbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 6px 8px 6px 14px; border-radius: 12px;
  border: 1px solid var(--accent); background: color-mix(in srgb, var(--accent) 10%, var(--card)); }

/* ---------- top bar ---------- */
.kt-top { display: flex; align-items: center; gap: 10px 16px; flex-wrap: wrap; }
.kt-title { display: flex; align-items: center; gap: 8px 12px; flex-wrap: wrap; min-width: 0; flex: 1 1 480px; } /* a laptop-wide window: the buttons go to the next line, not the title into a column */
.kt-title h1 { margin: 0; font-size: 1em; font-weight: 700; color: var(--muted); letter-spacing: .04em; }
.kt-run-title { font-size: 1.65em; font-weight: 800; color: var(--text-strong); letter-spacing: -.01em; }
.kt-run-meta { font-size: .82em; color: var(--muted); }
.kt-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.kt-start { display: grid; gap: 8px; padding: 14px 16px; border: 1px solid var(--border); border-radius: 16px; background: var(--card); }
.kt-start label { font-weight: 750; color: var(--text-strong); }
.kt-start textarea { font: inherit; resize: vertical; min-height: 86px; padding: 10px 12px; border-radius: 12px; border: 1px solid var(--border-strong, var(--border)); background: var(--bg); color: var(--text); }
.kt-start-actions, .kt-confirm-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.kt-pick { display: grid; gap: 6px; padding: 10px 12px; border-radius: 12px; border: 1px dashed var(--border-strong, var(--border)); background: var(--bg); font-size: .92em; }
.kt-pick.is-empty { color: var(--muted); }
.kt-pick p { margin: 0; }
.kt-pick-why b, .kt-pick-team b { color: var(--text-strong); }
.kt-pick-phases { list-style: none; margin: 2px 0; padding: 0; display: grid; gap: 4px; }
.kt-pick-phases li { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.kt-pick-phase { min-width: 6.5em; font-weight: 700; color: var(--muted); }
.kt-pick-role { display: inline-flex; align-items: center; gap: 4px; padding: 2px 8px; border-radius: 999px; background: var(--card); border: 1px solid var(--border); }
.kt-pick-role em { font-style: normal; color: var(--kt-approve); font-weight: 700; }
.kt-pick-roster { display: flex; flex-wrap: wrap; gap: 4px; }
.kt-pick-agent { padding: 1px 7px; border-radius: 6px; font-size: .86em; color: var(--muted); opacity: .45; border: 1px solid var(--border); }
.kt-pick-agent.is-used { opacity: 1; color: var(--text-strong); border-color: var(--kt-ok, var(--border-strong)); font-weight: 700; }
.kt-warn { color: var(--kt-warn); font-weight: 700; }
.kt-cleanup-msg { margin: 0; cursor: pointer; }
.kt-pick-role > span { display: inline-flex; flex-direction: column; line-height: 1.25; }
.kt-pick-role small { font-size: .82em; color: var(--muted); font-weight: 500; }
.kt-pick-role.is-absent { border-style: dashed; border-color: var(--kt-warn); }
.kt-pick-agent.is-custom::after { content: ' ★'; color: var(--kt-approve); }
.kt-pick-std { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin: 6px 0; }
.kt-pick-agent.is-data { border-style: dashed; }
.kt-scenarios { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; }
.kt-scenario { display: flex; flex-direction: column; align-items: flex-start; gap: 2px; padding: 10px 14px; border-radius: 12px; border: 1px solid var(--border); background: var(--card); color: var(--text); cursor: pointer; text-align: left; font: inherit; }
.kt-scenario b { font-size: 1.02em; }
.kt-scenario small { color: var(--muted); font-size: .85em; }
.kt-scenario.is-on { border-color: var(--kt-on, var(--kt-run)); box-shadow: 0 0 0 2px color-mix(in srgb, var(--kt-run) 35%, transparent); }
.kt-kb { display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(0, 1fr); gap: 14px; } /* frame: kit.ts */
.kt-kb-col { min-width: 0; }
.kt-kb-head { display: flex; align-items: baseline; gap: 10px; margin: 0 0 6px; flex-wrap: wrap; }
.kt-kb-chips { display: flex; flex-wrap: wrap; gap: 6px; list-style: none; margin: 0; padding: 0; }
.kt-kb-chip { display: inline-flex; align-items: baseline; gap: 6px; padding: 4px 10px; border-radius: 10px; border: 1px solid color-mix(in srgb, var(--kt-info) 55%, var(--border)); background: color-mix(in srgb, var(--kt-info) 10%, transparent); }
.kt-kb-chip.is-data { border-style: dashed; border-color: color-mix(in srgb, var(--kt-handoff) 60%, var(--border)); background: color-mix(in srgb, var(--kt-handoff) 9%, transparent); }
.kt-kb-chip small { color: var(--muted); font-size: .8em; }
.kt-kb-chip .kt-mono { font-size: .82em; color: var(--muted); }
.kt-kb-hits { list-style: none; margin: 0; padding: 0; display: grid; gap: 3px; max-height: 132px; overflow: auto; }
.kt-kb-hits li { display: flex; align-items: baseline; gap: 8px; font-size: .92em; white-space: nowrap; }
.kt-kb-hits li.is-data .kt-kb-what { color: var(--kt-handoff); }
.kt-kb-what { overflow: hidden; text-overflow: ellipsis; min-width: 0; flex: 1; }
.kt-kb-who { all: unset; cursor: pointer; display: inline-flex; align-items: center; gap: 4px; font-weight: 700; color: var(--text-strong); }
.kt-kb-empty { margin: 4px 0; }
.kt-gate-delivery { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin: 6px 0 8px; padding: 8px 10px; border-radius: 10px; border: 1px solid var(--border); background: var(--kt-glass); }
.kt-gate-delivery legend { padding: 0 4px; font-size: .9em; color: var(--muted); }
.kt-gate-delivery input, .kt-gate-delivery select { font: inherit; font-size: .93em; padding: 4px 8px; border-radius: 8px; border: 1px solid var(--border-strong, var(--border)); background: var(--card); color: var(--text); }
.kt-gate-delivery input { width: 13em; }
.kt-sign-cto { margin-left: 10px; vertical-align: middle; }
.kt-gate-split { list-style: none; margin: 6px 0 8px; padding: 8px 10px; border-radius: 10px; background: color-mix(in srgb, var(--kt-handoff) 8%, transparent); display: grid; gap: 3px; font-size: .92em; }
.kt-gate-split b { margin-right: 6px; }
.kt-gate-split.is-out { background: color-mix(in srgb, var(--kt-warn) 10%, transparent); }
.kt-focuschip { position: sticky; top: 8px; z-index: 3; margin: -6px 0 6px auto; width: max-content; display: inline-flex; align-items: center; gap: 6px; padding: 4px 6px 4px 10px; border-radius: 999px; border: 1px solid var(--kt-on, var(--border)); background: var(--card); font-size: .9em; font-weight: 700; }
.kt-focuschip button { all: unset; cursor: pointer; padding: 0 6px; border-radius: 999px; color: var(--muted); }
.kt-focuschip button:hover { color: var(--text-strong); }
.kt-wall-src { font-size: .85em; color: var(--muted); }
.kt-req-hint { margin: 2px 0 6px; font-size: .88em; }
.kt-btn-icon { padding-left: 9px; padding-right: 9px; }
.kt-expert.is-joined { opacity: .75; border-style: dashed; }
.kt-start-more { margin: 8px 0; }
.kt-start-more > summary { cursor: pointer; color: var(--muted); font-size: .9em; }
.kt-ncard { position: absolute; z-index: 6; width: 300px; max-width: 34%; padding: 10px 12px; border-radius: 14px; border: 1px solid var(--border-strong, var(--border)); background: var(--card); box-shadow: 0 14px 40px rgba(0,0,0,.35); font-size: 13px; }
.kt-ncard-body p { margin: 0 0 6px; }
.kt-ncard-head { display: flex; align-items: center; gap: 6px; font-size: 14px; }
.kt-ncard-head .kt-pill { margin-left: auto; }
.kt-ncard-task .kt-dim { margin-right: 4px; }
.kt-ncard-back { color: var(--kt-fix); font-weight: 650; }
.kt-ncard-did { color: var(--text); line-height: 1.45; max-height: 6.2em; overflow: hidden; }
.kt-ncard-facts { list-style: none; margin: 0 0 8px; padding: 0; display: grid; gap: 2px; color: var(--muted); }
.kt-ncard-actions { display: flex; gap: 6px; flex-wrap: wrap; }
.kt-ncard-actions .kt-btn { font-size: 12px; padding: 4px 10px; }
.kt-gate-report { margin: 6px 0 8px; padding: 8px 10px; border-radius: 10px; background: color-mix(in srgb, var(--kt-info) 9%, transparent); display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; font-size: .94em; }
.kt-gate-report .kt-btn { margin-left: auto; font-size: 12px; padding: 3px 9px; }
.kt-sign-back { color: var(--kt-fix); display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
/* .kt-sign: framed by kit.ts (a border for its state: magenta waiting, green signed) */

.kt-sign-head { display: flex; align-items: baseline; gap: 14px; flex-wrap: wrap; }
.kt-sign-head h2 { margin: 0; font-size: 1.25em; }
.kt-sign-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px 18px; margin: 10px 0; }
.kt-sign-grid dt { font-size: .82em; color: var(--muted); font-weight: 700; }
.kt-sign-grid dd { margin: 2px 0 0; }
.kt-sign-grid ul { margin: 0; padding-left: 1.1em; }
.kt-sign-groups { display: flex; flex-wrap: wrap; gap: 4px 10px; list-style: none; padding: 0 !important; margin-top: 2px !important; font-size: .88em; }
.kt-sign-groups .is-ok { color: var(--kt-ok); }
.kt-sign-groups .is-bad { color: var(--kt-bad); }
.kt-sign-form { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.kt-sign-form input { padding: 7px 10px; border-radius: 8px; border: 1px solid var(--border); background: var(--card); color: var(--text); font: inherit; }
.kt-sign-form input:first-child { width: 10em; }
.kt-sign-form input:nth-child(2) { flex: 1; min-width: 16em; }
.kt-sign-done { margin: 4px 0 0; font-size: 1.05em; }
.kt-sign-blocked { margin: 10px 0 0; padding: 8px 12px; border-radius: 10px; border: 1px dashed color-mix(in srgb, var(--kt-warn) 55%, var(--border)); color: var(--muted); }
.kt-ok { color: var(--kt-ok); }
.kt-bad { color: var(--kt-bad); }
.kt-lane-doing, .kt-node-task { }
.kt-experts { display: flex; align-items: center; gap: 10px 14px; flex-wrap: wrap; } /* frame: kit.ts */
.kt-experts-title { font-weight: 800; color: var(--text-strong); white-space: nowrap; }
.kt-experts-list { display: flex; flex-wrap: wrap; gap: 6px; list-style: none; margin: 0; padding: 0; }
.kt-expert { display: inline-flex; align-items: baseline; gap: 6px; padding: 3px 10px; border-radius: 999px; border: 1px solid var(--border); font-size: .9em; }
.kt-expert small { font-size: .82em; font-weight: 700; }
.kt-expert.is-busy { border-color: var(--kt-run); background: color-mix(in srgb, var(--kt-run) 16%, transparent); box-shadow: 0 0 0 2px color-mix(in srgb, var(--kt-run) 25%, transparent); }
.kt-expert.is-busy small { color: var(--kt-run); }
.kt-expert.is-used { border-color: color-mix(in srgb, var(--kt-ok) 60%, transparent); background: color-mix(in srgb, var(--kt-ok) 12%, transparent); }
.kt-expert.is-used small { color: var(--kt-ok); }
.kt-expert.is-team { border-style: dashed; color: var(--muted); }
.kt-expert.is-none { color: var(--muted); opacity: .45; }
.kt-expert.is-absent { border-style: dashed; border-color: var(--kt-warn); color: var(--kt-warn); }
.kt-expert.is-custom b::after { content: ' ★'; font-size: .8em; color: var(--kt-approve); }
.kt-confirm { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 14px; padding: 12px 16px; border-radius: 14px;
  border: 1px solid var(--kt-bad); background: color-mix(in srgb, var(--kt-bad) 9%, var(--card)); }
.kt-confirm strong { color: var(--text-strong); }
.kt-gate-dialog { border-color: var(--kt-approve); background: color-mix(in srgb, var(--kt-approve) 9%, var(--card)); }
.kt-gate-docs, .kt-gate-talk, .kt-gate-questions, .kt-gate-split, .kt-gate-report { flex: 1 1 100%; }
.kt-gate-docs { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 10px; margin: 6px 0; font-size: .93em; }
.kt-gate-docs .kt-chip-link { display: inline-flex; align-items: center; gap: 4px; }
.kt-gate-talk { list-style: none; margin: 6px 0 8px; padding: 8px 10px; border-radius: 10px; background: var(--kt-glass); display: grid; gap: 6px; max-height: 260px; overflow: auto; font-size: .93em; }
.kt-gate-talk li { display: grid; grid-template-columns: 4.5em 1fr; gap: 8px; }
.kt-gate-talk li.is-person .kt-gate-talk-text { white-space: pre-wrap; }
.kt-gate-talk-text p { margin: 0 0 4px; }
.kt-gate-talk-text ul, .kt-gate-talk-text ol { margin: 0 0 4px; padding-left: 1.3em; }
.kt-gate-dialog.is-approve .kt-gate-talk { max-height: 180px; }
.kt-gate-talk li.is-person > b { color: var(--kt-approve); }
.kt-gate-questions { display: grid; gap: 8px; margin: 6px 0 8px; }
.kt-gate-q { margin: 0; padding: 8px 10px; border-radius: 10px; border: 1px solid var(--border); background: var(--kt-glass); display: grid; gap: 4px; }
.kt-gate-q legend { padding: 0 4px; font-size: .95em; }
.kt-gate-q label { display: flex; align-items: baseline; gap: 6px; flex-wrap: wrap; font-size: .93em; cursor: pointer; }
.kt-gate-q label.is-picked > span { font-weight: 650; color: var(--text-strong); }
.kt-gate-rec { margin-left: 6px; padding: 0 6px; border-radius: 999px; font-style: normal; font-size: .85em; color: var(--kt-ok); border: 1px solid color-mix(in srgb, var(--kt-ok) 55%, var(--border)); }
.kt-gate-other { flex: 1 1 16em; font: inherit; padding: 3px 8px; border-radius: 8px; border: 1px solid var(--border-strong, var(--border)); background: var(--card); color: var(--text); }
.kt-gate-differs { color: var(--kt-warn); font-weight: 650; }
.kt-gate-note { flex: 1 1 100%; min-height: 64px; padding: 8px 10px; border-radius: 10px; border: 1px solid var(--border-strong, var(--border)); background: var(--bg); color: var(--text); font: inherit; resize: vertical; }

/* ---------- the counters ---------- */
.kt-kpis { display: grid; grid-template-columns: minmax(190px, 1.05fr) minmax(300px, 1.75fr) minmax(190px, 1fr) minmax(170px, .85fr) minmax(120px, .65fr); gap: 12px; }
@media (max-width: 1240px) { .kt-kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); } .kt-kpi-par, .kt-kpi-gates { grid-column: span 2; order: -1; } }
.kt-kpi { display: flex; flex-direction: column; gap: 5px; min-width: 0; } /* frame, glass, label and number: kit.ts */

.kt-kpi-label { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; } /* type: kit.ts */
.kt-kpi-value { display: flex; align-items: baseline; flex-wrap: wrap; gap: 4px 8px; color: var(--text-strong); font-weight: 750; font-variant-numeric: tabular-nums; }
.kt-kpi-big { display: inline-block; } /* type: kit.ts */
.kt-kpi-big.is-pop { animation: kt-pop .7s cubic-bezier(.2,1.6,.4,1) 1; }

.kt-kpi-mid { font-size: 1.5em; font-weight: 800; color: var(--muted); }
.kt-kpi-note { font-size: .84em; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.kt-kpi-tests.is-green .kt-kpi-big { color: var(--kt-ok); }
.kt-segs { display: flex; gap: 3px; margin-top: 2px; }
.kt-segs i { flex: 1; height: 9px; border-radius: 3px; background: color-mix(in srgb, var(--muted) 30%, transparent); transition: background .4s; }
.kt-segs i.is-pass { background: var(--kt-ok); box-shadow: 0 0 8px color-mix(in srgb, var(--kt-ok) 55%, transparent); }
.kt-segs i.is-fail { background: var(--kt-bad); }
.kt-saving { display: inline-flex; align-items: baseline; gap: 6px; font-size: 1.15em; }

.kt-speedup { margin-left: auto; align-self: center; padding: 2px 10px; border-radius: 999px; font-size: 1em; font-weight: 800; color: var(--kt-handoff);
  background: color-mix(in srgb, var(--kt-handoff) 14%, transparent); border: 1px solid color-mix(in srgb, var(--kt-handoff) 42%, transparent); }
.kt-bars { display: grid; gap: 5px; margin-top: 2px; }
.kt-bar-row { display: grid; grid-template-columns: 4.6em minmax(0, 1fr) 4.4em; align-items: center; gap: 8px; font-size: .84em; }
.kt-bar-name { color: var(--muted); white-space: nowrap; }
.kt-bar-val { text-align: right; color: var(--text-strong); font-weight: 700; }
.kt-bar { display: flex; height: 11px; border-radius: 6px; background: color-mix(in srgb, var(--muted) 16%, transparent); overflow: hidden; }
.kt-bar.is-segs { gap: 2px; background: none; }
.kt-bar-wall { border-radius: 6px; background: linear-gradient(90deg, var(--kt-run), var(--kt-handoff)); box-shadow: 0 0 12px color-mix(in srgb, var(--kt-run) 45%, transparent); transition: width .9s; }
.kt-bar-seg { height: 100%; border-radius: 3px; background: oklch(var(--kt-seg-l) var(--kt-seg-c) var(--h)); transition: width .9s; }
.kt-role-dots { display: flex; gap: 4px; flex-wrap: wrap; }
.kt-role-dot { width: 26px; height: 26px; padding: 0; display: grid; place-items: center; border-radius: 8px; font: inherit; font-size: 14px; line-height: 1; cursor: pointer; border: 2px solid var(--kt-tone); background: color-mix(in srgb, var(--kt-tone) 14%, transparent); }
.kt-role-dot:hover { transform: translateY(-1px); }
.kt-role-dot.tone-idle { border-style: dashed; filter: grayscale(.9); opacity: .55; }
.kt-role-dot.tone-ok { background: var(--kt-ok-solid); border-color: var(--kt-ok-solid); }
.kt-role-dot.is-working { box-shadow: 0 0 0 3px color-mix(in srgb, var(--kt-tone) 22%, transparent), 0 0 14px color-mix(in srgb, var(--kt-tone) 60%, transparent); animation: kt-glow 2.4s ease-in-out infinite; }
.kt-slots { display: flex; gap: 5px; flex-wrap: wrap; }
.kt-slots i { width: 22px; height: 22px; border-radius: 6px; border: 2px dashed var(--border-strong, var(--border)); }
.kt-slots i.is-on { border: 2px solid var(--kt-run); background: color-mix(in srgb, var(--kt-run) 32%, transparent); box-shadow: 0 0 10px color-mix(in srgb, var(--kt-run) 50%, transparent); }
.kt-slots i.is-queued { border: 2px dashed var(--kt-queue); background: color-mix(in srgb, var(--kt-queue) 20%, transparent); }
.kt-kpi-cap.is-queued { border-color: color-mix(in srgb, var(--kt-queue) 55%, var(--border)); }

.kt-gates-score { display: inline-flex; align-items: baseline; gap: 10px; }
.kt-gates-score .kt-kpi-mid { color: var(--kt-bad); }
.kt-gates-arrow { color: var(--muted); font-size: 22px; font-weight: 700; }
.kt-gates-rows { display: flex; flex-wrap: wrap; gap: 6px 16px; margin-top: 8px; font-size: 13.5px; color: var(--muted); }
.kt-gates-rows b { color: var(--text-strong); font-size: 18px; margin: 0 2px; }
.kt-gates-rows .is-hit b { color: var(--kt-bad); }
.kt-used-row { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; margin-top: 6px; font-size: 13px; color: var(--muted); }
.kt-used-row b { color: var(--text-strong); font-weight: 800; }
.kt-used-dots { display: inline-flex; gap: 3px; margin-left: 4px; }
.kt-used-dots i { width: 9px; height: 9px; border-radius: 3px; background: color-mix(in srgb, var(--muted) 28%, transparent); }
.kt-used-dots i.is-on { background: var(--kt-ok); box-shadow: 0 0 6px color-mix(in srgb, var(--kt-ok) 55%, transparent); }

/* ---------- the team graph ---------- */
.kt-graph { position: relative; overflow: hidden; /* border, radius: kit.ts */
  background: radial-gradient(110% 80% at 50% -12%, color-mix(in srgb, var(--accent) 15%, transparent), transparent 62%),
    radial-gradient(60% 50% at 100% 100%, color-mix(in srgb, var(--kt-ok) 7%, transparent), transparent 70%), var(--card); }
.kt-graph-stage { position: relative; }
.kt-graph-svg { display: block; width: 100%; height: auto; user-select: none; overflow: visible; }
.kt-g-dot { fill: color-mix(in srgb, var(--muted) 30%, transparent); }
.kt-stage-band { fill: color-mix(in srgb, var(--text) 2.5%, transparent); stroke: color-mix(in srgb, var(--muted) 22%, transparent); stroke-dasharray: 2 6; transition: fill .6s, stroke .6s; }
.kt-stage.is-live .kt-stage-band { fill: color-mix(in srgb, var(--kt-run) 5%, transparent); stroke: color-mix(in srgb, var(--kt-run) 40%, transparent); stroke-dasharray: none; }
.kt-stage-title { fill: var(--muted); font-size: 15px; font-weight: 750; letter-spacing: .02em; }
.kt-stage.is-live .kt-stage-title { fill: var(--text-strong); }
.kt-phase-band { fill: color-mix(in srgb, var(--text) 2.5%, transparent); stroke: color-mix(in srgb, var(--muted) 26%, transparent); stroke-dasharray: 2 6; transition: fill .6s, stroke .6s; }
.kt-phase.is-live .kt-phase-band { fill: color-mix(in srgb, var(--kt-run) 5%, transparent); stroke: color-mix(in srgb, var(--kt-run) 45%, transparent); stroke-dasharray: none; }
.kt-phase.is-done .kt-phase-band { stroke: color-mix(in srgb, var(--kt-ok) 45%, transparent); stroke-dasharray: none; }
.kt-phase-title { fill: var(--muted); font-size: 16px; font-weight: 800; letter-spacing: .02em; }
.kt-phase-title.is-pick { cursor: pointer; }
.kt-phase-title.is-pick:hover { fill: var(--accent); text-decoration: underline; }
.kt-phase.is-focus .kt-phase-band { fill: color-mix(in srgb, var(--accent) 8%, transparent); stroke: var(--accent); stroke-width: 2; stroke-dasharray: none; }
.kt-phase.is-focus .kt-phase-title { fill: var(--accent); }
.kt-phase.is-off { opacity: .55; }
.kt-run-link { border: 0; background: transparent; padding: 0; font: inherit; cursor: pointer; text-align: left; }
.kt-run-link:hover { color: var(--accent); text-decoration: underline; text-underline-offset: 4px; }
.kt-pill-btn { cursor: pointer; font: inherit; }
.kt-focuschip .kt-chip-link { border: 0; background: transparent; color: var(--accent); cursor: pointer; font: inherit; padding: 0 4px; }
.kt-phase.is-live .kt-phase-title, .kt-phase.is-done .kt-phase-title { fill: var(--text-strong); }
.kt-phase-en { font-size: 12px; font-weight: 600; fill-opacity: .7; }
.kt-phase.is-unused .kt-phase-band { fill: none; stroke: color-mix(in srgb, var(--muted) 30%, transparent); stroke-dasharray: 4 6; }
.kt-phase.is-unused .kt-phase-title { fill: color-mix(in srgb, var(--muted) 70%, transparent); }
.kt-phase-note { fill: color-mix(in srgb, var(--muted) 75%, transparent); font-size: 13px; font-weight: 650; }
.kt-orch-body { fill: color-mix(in srgb, var(--kt-run) 10%, var(--card)); stroke: color-mix(in srgb, var(--kt-run) 55%, transparent); stroke-width: 2; }
.kt-orch.is-active .kt-orch-body { stroke: var(--kt-run); }
.kt-orch-title { fill: var(--text-strong); font-size: 15px; font-weight: 850; letter-spacing: .02em; }
.kt-orch-cn { fill: var(--text-strong); font-size: 14px; font-weight: 700; }
.kt-orch-sub { fill: var(--muted); font-size: 11px; font-weight: 600; }
.kt-phase-stages { fill: var(--muted); font-size: 11.5px; font-weight: 600; }
.kt-cmd { fill: none; stroke: var(--kt-run); stroke-width: 2.4; stroke-linecap: round; stroke-dasharray: 7 7; opacity: .9; animation: kt-cmd-flow 1.1s linear infinite; }
.kt-cmd.is-fixing { stroke: var(--kt-fix); }
.kt-cmd.is-queued { stroke: var(--kt-queue); opacity: .55; animation: none; }
.kt-cmd.is-awaiting_approval, .kt-cmd.is-stalled { stroke: var(--kt-approve); }
@keyframes kt-cmd-flow { to { stroke-dashoffset: -28; } }
@media (prefers-reduced-motion: reduce) { .kt-cmd { animation: none; } }
.kt-roster-title { fill: var(--muted); font-size: 11.5px; font-weight: 750; }
.kt-roster-group { fill: var(--muted); font-size: 10.5px; font-weight: 750; letter-spacing: .02em; }
.kt-roster-item.is-busy rect { stroke: var(--kt-run); fill: color-mix(in srgb, var(--kt-run) 16%, transparent); }
.kt-roster-item.is-busy circle { fill: var(--kt-run); }
.kt-roster-item rect { fill: color-mix(in srgb, var(--muted) 8%, transparent); stroke: color-mix(in srgb, var(--muted) 25%, transparent); }
.kt-roster-item circle { fill: color-mix(in srgb, var(--muted) 45%, transparent); }
.kt-roster-item text { fill: color-mix(in srgb, var(--muted) 75%, transparent); font-size: 11.5px; font-weight: 600; }
.kt-roster-item.is-team rect { stroke: color-mix(in srgb, var(--kt-ok) 45%, transparent); stroke-dasharray: 3 3; }
.kt-roster-item.is-team text { fill: var(--text); }
.kt-roster-item.is-team circle { fill: var(--kt-ok); }
.kt-roster-item.is-team rect { stroke: color-mix(in srgb, var(--kt-ok) 70%, transparent); }
.kt-roster-item.is-bench text { fill: var(--muted); }
.kt-roster-item:not(.is-team) { opacity: .38; }
.kt-roster-item:not(.is-team) rect { stroke-dasharray: none; fill: transparent; }
.kt-roster-state { font-size: 10px !important; font-weight: 700 !important; }
.kt-roster-item.is-team:not(.is-used) .kt-roster-state { fill: var(--muted) !important; }
.kt-roster-item.is-used .kt-roster-state { fill: var(--kt-ok) !important; }
.kt-roster-item.is-busy .kt-roster-state { fill: var(--kt-run) !important; }
.kt-roster-item.is-used rect { fill: color-mix(in srgb, var(--kt-ok) 14%, transparent); stroke: color-mix(in srgb, var(--kt-ok) 60%, transparent); stroke-dasharray: none; }
.kt-roster-item.is-used circle { fill: var(--kt-ok); }
.kt-roster-item.is-used text { fill: var(--text-strong); }
.kt-roster-item.is-busy rect { fill: color-mix(in srgb, var(--kt-run) 22%, transparent); stroke: var(--kt-run); }
.kt-roster-item.is-busy circle { fill: var(--kt-run); filter: drop-shadow(0 0 4px var(--kt-run)); }
.kt-node.is-skipped { opacity: .45; }
.kt-node.is-skipped .kt-node-body { fill: none; stroke: color-mix(in srgb, var(--muted) 55%, transparent); stroke-dasharray: 3 5; }
.kt-node.is-skipped .kt-node-emoji { filter: grayscale(1); opacity: .5; }
.kt-node.is-skipped .kt-node-title { fill: var(--muted); }
.kt-gate-chip { cursor: pointer; }
.kt-gate-chip.is-static { cursor: default; }
.kt-gate-chip rect { fill: var(--kt-approve); stroke: color-mix(in srgb, #fff 40%, transparent); stroke-width: 1; }
.kt-gate-chip.is-revise rect { fill: var(--card); stroke: var(--kt-approve); }
.kt-gate-chip text { fill: #fff; font-size: 12.5px; font-weight: 800; }
.kt-gate-chip.is-revise text { fill: var(--kt-approve); }
.kt-gate-chip.is-discuss rect { fill: var(--card); stroke: var(--kt-approve); stroke-dasharray: 3 2; }
.kt-gate-chip.is-discuss text { fill: var(--kt-approve); }
.kt-gate-chip.is-talking rect { fill: color-mix(in srgb, var(--kt-approve) 14%, var(--card)); stroke: var(--kt-approve); }
.kt-gate-chip.is-talking text { fill: var(--kt-approve); font-weight: 700; }
.kt-gate-chip:hover rect, .kt-gate-chip:focus-visible rect { filter: brightness(1.12); stroke-width: 2; }
.kt-par rect { fill: color-mix(in srgb, var(--kt-run) 16%, var(--card)); stroke: var(--kt-run); stroke-width: 1.3; }
.kt-par text { fill: var(--kt-run); font-size: 13px; font-weight: 800; }
.kt-par-dot { fill: var(--kt-run); animation: kt-blink 2.4s ease-in-out infinite; }
.kt-edge { fill: none; stroke-width: 2.2; stroke-linecap: round; transition: opacity .3s, stroke-width .3s; }
.kt-edge.is-pending { stroke: var(--muted); opacity: .38; stroke-dasharray: 5 6; }
.kt-graph.is-phased .kt-edge:not(.is-hot) { opacity: .2; }
.kt-edge.is-ready { stroke: var(--kt-handoff); opacity: .5; }
.kt-edge.is-used { stroke: var(--kt-handoff); opacity: .78; }
.kt-edge.is-dim { opacity: .08; }
.kt-edge.is-hot { opacity: 1; stroke-width: 3.2; }
.kt-arrow.is-pending { fill: var(--muted); }
.kt-arrow.is-ready, .kt-arrow.is-used { fill: var(--kt-handoff); }

.kt-node { cursor: pointer; outline: none; transition: opacity .3s; }
.kt-node.is-dim { opacity: .26; }
.kt-node-body { fill: var(--bg-elevated, var(--card)); stroke: var(--border-strong, var(--muted)); stroke-width: 2; transition: fill .5s, stroke .5s; }
.kt-node-avatar { fill: color-mix(in srgb, var(--text) 7%, var(--card)); stroke: color-mix(in srgb, var(--muted) 40%, transparent); stroke-width: 1.5; }
.kt-node-emoji { color: var(--text-strong); }
.kt-node-title { fill: var(--text-strong); font-size: 18.5px; font-weight: 800; }
.kt-node-agent { font-size: 12px; font-weight: 600; fill-opacity: 0.7; letter-spacing: 0.02em; }
.kt-node-title.is-long { font-size: 15.5px; }
.kt-node-title.is-long .kt-node-agent { font-size: 10.5px; }
.kt-node-sub { fill: var(--muted); font-size: 13.5px; font-weight: 650; font-variant-numeric: tabular-nums; }
.kt-node-task { fill: var(--text); fill-opacity: 0.78; font-size: 12px; font-weight: 600; }
.kt-node-task.is-sent-back { fill: var(--kt-fix); fill-opacity: 1; }
.kt-node.is-waiting .kt-node-task, .kt-node.is-skipped .kt-node-task { fill: var(--muted); }
.kt-node-ticker { fill: var(--kt-run); font-size: 12.5px; font-weight: 600; font-family: var(--mono, ui-monospace, monospace); }
.kt-node.is-fixing .kt-node-ticker { fill: var(--kt-fix); }
.kt-node.is-stalled .kt-node-ticker { fill: var(--kt-warn); }
.kt-node.is-awaiting_approval .kt-node-ticker { fill: var(--kt-approve); }
.kt-node-focus { fill: none; stroke: var(--accent); stroke-width: 3; opacity: 0; }
.kt-node:focus-visible .kt-node-focus, .kt-node.is-focus .kt-node-focus { opacity: 1; }
.kt-node-halo { fill: none; stroke-width: 12; opacity: .4; filter: blur(6px); transform-box: fill-box; transform-origin: center; animation: kt-halo 2.4s ease-in-out infinite; }
.kt-node-spin { fill: none; stroke-width: 3; stroke-linecap: round; stroke-dasharray: 30 130; transform-box: fill-box; transform-origin: center; animation: kt-spin 1.5s linear infinite; }
.kt-node.is-waiting .kt-node-body { fill: color-mix(in srgb, var(--card) 65%, transparent); stroke: color-mix(in srgb, var(--muted) 55%, transparent); stroke-dasharray: 6 5; }
.kt-node.is-waiting .kt-node-emoji { filter: grayscale(1); opacity: .5; }
.kt-graph.is-phased .kt-node.is-waiting { opacity: .5; }
.kt-node.is-waiting .kt-node-title { fill: var(--muted); }
.kt-node.is-running .kt-node-body { stroke: var(--kt-run); stroke-width: 3; fill: color-mix(in srgb, var(--kt-run) 11%, var(--card)); }
.kt-node.is-running .kt-node-sub { fill: var(--kt-run); }
.kt-node.is-running :is(.kt-node-halo, .kt-node-spin) { stroke: var(--kt-run); }
.kt-node.is-fixing .kt-node-body { stroke: var(--kt-fix); stroke-width: 3; fill: color-mix(in srgb, var(--kt-fix) 12%, var(--card)); }
.kt-node.is-fixing .kt-node-sub { fill: var(--kt-fix); }
.kt-node.is-fixing :is(.kt-node-halo, .kt-node-spin) { stroke: var(--kt-fix); }
.kt-node.is-queued .kt-node-body { stroke: color-mix(in srgb, var(--kt-queue) 50%, transparent); stroke-width: 1.5; fill: color-mix(in srgb, var(--kt-queue) 9%, var(--card)); }
.kt-node.is-queued .kt-node-sub { fill: var(--kt-queue); }
.kt-node-ants { fill: none; stroke: var(--kt-queue); stroke-width: 3; stroke-dasharray: 10 8; animation: kt-ants .9s linear infinite; }
.kt-node.is-stalled .kt-node-body { stroke: var(--kt-warn); stroke-width: 3.5; fill: color-mix(in srgb, var(--kt-warn) 10%, var(--card)); }
.kt-node.is-stalled .kt-node-sub { fill: var(--kt-warn); font-weight: 800; }
.kt-node-hatch { pointer-events: none; }
.kt-hatch-line { fill: color-mix(in srgb, var(--kt-warn) 15%, transparent); }
.kt-node.is-awaiting_approval .kt-node-body { stroke: var(--kt-approve); stroke-width: 3.5; fill: color-mix(in srgb, var(--kt-approve) 13%, var(--card)); }
.kt-node.is-awaiting_approval .kt-node-sub { fill: var(--kt-approve); font-weight: 800; }
.kt-node.is-awaiting_approval .kt-node-halo { stroke: var(--kt-approve); animation: kt-beacon 1.1s ease-in-out infinite; }
.kt-node.is-failed .kt-node-body { fill: var(--kt-bad-solid); stroke: var(--kt-bad); stroke-width: 3; }
.kt-node.is-failed :is(.kt-node-title, .kt-node-sub) { fill: #fff; }
.kt-node.is-failed .kt-node-avatar { fill: color-mix(in srgb, #fff 18%, transparent); stroke: none; }
.kt-node.is-done .kt-node-body { stroke: var(--kt-ok); stroke-width: 3; fill: color-mix(in srgb, var(--kt-ok) 9%, var(--card)); }
.kt-node.is-done .kt-node-sub { fill: var(--kt-ok); }
.kt-node:is(.is-merged, .is-final) .kt-node-body { fill: var(--kt-ok-solid); stroke: color-mix(in srgb, var(--kt-ok) 70%, #fff); stroke-width: 1.5; }
.kt-node:is(.is-merged, .is-final) .kt-node-title { fill: #fff; }
.kt-node:is(.is-merged, .is-final) .kt-node-sub { fill: #fff; opacity: .85; }
.kt-node:is(.is-merged, .is-final) .kt-node-avatar { fill: color-mix(in srgb, #fff 17%, transparent); stroke: color-mix(in srgb, #fff 30%, transparent); }
.kt-node-check circle { fill: #fff; }
.kt-node-check path { fill: none; stroke: var(--kt-ok-solid); stroke-width: 2.4; stroke-linecap: round; stroke-linejoin: round; }
.kt-node-retry { cursor: pointer; }
.kt-node-retry rect { fill: var(--kt-bad-solid); stroke: color-mix(in srgb, #fff 40%, transparent); stroke-width: 1; }
.kt-node-retry text { fill: #fff; font-size: 12.5px; font-weight: 800; }
.kt-node-retry:hover rect, .kt-node-retry:focus-visible rect { filter: brightness(1.15); stroke: #fff; stroke-width: 2; }
.kt-retry-btn { margin-left: 8px; }
.kt-node-badge rect { fill: var(--kt-badge, var(--muted)); }
.kt-node-badge text { fill: var(--kt-on); font-size: 12px; font-weight: 800; }
.kt-node-badge.is-fix { --kt-badge: var(--kt-fix); }
.kt-node-badge.is-bad { --kt-badge: var(--kt-bad); }
.kt-node-badge.is-queue { --kt-badge: var(--kt-queue); }
.kt-node-badge.is-warn { --kt-badge: var(--kt-warn); }
.kt-node-badge.is-approve { --kt-badge: var(--kt-approve); }
.kt-node-badge.is-gate { --kt-badge: var(--kt-approve); }
.kt-node-flash { stroke-width: 6; opacity: 0; transform-box: fill-box; transform-origin: center; pointer-events: none; animation: kt-flash 1.4s ease-out 1 forwards; }
.kt-node-flash.is-bad { stroke: var(--kt-bad); fill: color-mix(in srgb, var(--kt-bad) 30%, transparent); }
.kt-node-flash.is-ok { stroke: var(--kt-ok); fill: color-mix(in srgb, var(--kt-ok) 25%, transparent); }

.kt-rail-base { stroke: color-mix(in srgb, var(--muted) 45%, transparent); stroke-width: 6; stroke-linecap: round; stroke-dasharray: 1 9; }
.kt-rail-fill { stroke: var(--kt-ok); stroke-width: 6; stroke-linecap: round; filter: drop-shadow(0 0 5px color-mix(in srgb, var(--kt-ok) 60%, transparent)); transition: x2 .8s; }
.kt-rail-label { fill: var(--text-strong); font-size: 14.5px; font-weight: 800; }
.kt-rail-sub { fill: var(--muted); font-size: 13px; font-weight: 600; }
.kt-rail-label .kt-mono, .kt-rail-sub .kt-mono { font-weight: 500; fill: var(--muted); }
.kt-rail-dot circle { fill: var(--kt-ok-solid); stroke: var(--card); stroke-width: 2.5; }
.kt-rail-dot text { fill: #fff; font-size: 11px; font-weight: 800; }
.kt-rail-dot.is-conflict circle { fill: var(--kt-bad-solid); stroke: var(--kt-bad); }
.kt-rail-dot.is-dim { opacity: .3; }
.kt-rail-flash { fill: none; stroke-width: 4; transform-box: fill-box; transform-origin: center; animation: kt-flash 1.4s ease-out 1 forwards; }
.kt-rail-flash.is-bad { stroke: var(--kt-bad); }
.kt-rail-flash.is-ok { stroke: var(--kt-ok); }
.kt-station-bg { fill: var(--bg-elevated, var(--card)); stroke: var(--border-strong, var(--muted)); stroke-width: 2.5; transition: fill .5s, stroke .5s; }
.kt-station-track { fill: none; stroke: color-mix(in srgb, var(--muted) 28%, transparent); stroke-width: 6; }
.kt-station-pass { fill: none; stroke: var(--kt-ok); stroke-width: 6; transition: stroke-dasharray .8s; }
.kt-station-fail { fill: none; stroke: var(--kt-bad); stroke-width: 6; transition: stroke-dasharray .8s, stroke-dashoffset .8s; }
.kt-station-num { fill: var(--text-strong); font-size: 15px; font-weight: 850; font-variant-numeric: tabular-nums; }
.kt-station-label { fill: var(--text-strong); font-size: 13.5px; font-weight: 800; }
.kt-station.is-pass .kt-station-bg { fill: color-mix(in srgb, var(--kt-ok) 16%, var(--card)); stroke: var(--kt-ok); }
.kt-station.is-fail .kt-station-bg { stroke: color-mix(in srgb, var(--kt-bad) 70%, transparent); }
.kt-station-flash { fill: none; stroke-width: 6; transform-box: fill-box; transform-origin: center; animation: kt-flash 1.6s ease-out 1 forwards; }
.kt-station-flash.is-ok { stroke: var(--kt-ok); fill: color-mix(in srgb, var(--kt-ok) 22%, transparent); }
.kt-station-flash.is-bad { stroke: var(--kt-bad); }

.kt-particles { pointer-events: none; }
.kt-p { color: var(--kt-info); }
.kt-p.is-handoff { color: var(--kt-handoff); }
.kt-p:is(.is-merge, .is-pass, .is-ok) { color: var(--kt-ok); }
.kt-p:is(.is-fail, .is-bounce, .is-danger) { color: var(--kt-bad); }
.kt-p:is(.is-run, .is-tool) { color: var(--kt-run); }
.kt-p-halo { fill: currentColor; opacity: .22; }
.kt-p-tail-glow { fill: none; stroke: currentColor; stroke-linecap: round; stroke-linejoin: round; opacity: .16; }
.kt-p-tail { fill: none; stroke: currentColor; stroke-linecap: round; stroke-linejoin: round; opacity: .62; }
.kt-p-head { fill: color-mix(in srgb, currentColor 40%, #fff); stroke: currentColor; stroke-width: 2.2; }
.kt-p-ring { fill: none; stroke: currentColor; }
.kt-p.is-tool .kt-p-ring { opacity: .7; }
.kt-p-cross, .kt-p-check { fill: none; stroke: currentColor; stroke-width: 3.2; stroke-linecap: round; stroke-linejoin: round; }
.kt-p-label { fill: currentColor; font-size: 13px; font-weight: 800; paint-order: stroke; stroke: var(--card); stroke-width: 4px; stroke-linejoin: round; }

.kt-legend { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 14px; padding: 8px 16px 10px; font-size: 12px; color: var(--muted);
  border-top: 1px solid color-mix(in srgb, var(--border) 70%, transparent); background: color-mix(in srgb, var(--bg) 35%, transparent); }
.kt-legend-item { display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; }
.kt-legend-item i { width: 18px; height: 11px; border-radius: 4px; border: 2px solid var(--border-strong, var(--muted)); }
${legendSwatches}
.kt-legend-item.is-waiting i { border-style: dashed; background: none; }
.kt-legend-item.is-skipped i { border-style: dotted; background: none; opacity: .6; }
.kt-legend-item.is-queued i { border-style: dashed; }
.kt-legend-item.is-merged i, .kt-legend-item.is-failed i { background: var(--kt-ok-solid); }
.kt-legend-item.is-failed i { background: var(--kt-bad-solid); }
.kt-legend-item b { width: 9px; height: 9px; border-radius: 50%; background: var(--kt-info); box-shadow: 0 0 8px currentColor; }
.kt-legend-item.is-p-handoff b { background: var(--kt-handoff); color: var(--kt-handoff); }
.kt-legend-item:is(.is-p-merge, .is-p-pass) b { background: var(--kt-ok); color: var(--kt-ok); }
.kt-legend-item.is-p-fail b { background: var(--kt-bad); color: var(--kt-bad); }
.kt-legend-sep { width: 1px; height: 14px; background: var(--border); }
.kt-legend-note { margin-left: auto; font-style: italic; }

/* ---------- cards: conveyor, wall, feed ---------- */
.kt-card { min-width: 0; } /* frame: kit.ts */
.kt-card-head { display: flex; align-items: center; flex-wrap: wrap; gap: 6px 10px; margin-bottom: 10px; }

.kt-belt { list-style: none; margin: 0; padding: 4px 2px 6px; display: flex; align-items: center; gap: 10px; overflow-x: auto; position: relative; scrollbar-width: thin; scroll-behavior: smooth; }
.kt-belt::before { content: ''; position: absolute; left: 8px; right: 8px; top: 50%; height: 4px; margin-top: -2px; border-radius: 2px;
  background: repeating-linear-gradient(90deg, color-mix(in srgb, var(--muted) 38%, transparent) 0 10px, transparent 10px 17px); }
.kt-belt > li { position: relative; z-index: 1; flex: none; }
.kt-belt.has-older { -webkit-mask-image: linear-gradient(90deg, transparent 0, #000 56px); mask-image: linear-gradient(90deg, transparent 0, #000 56px); }
.kt-belt-end { display: flex; align-items: center; gap: 6px; padding: 7px 12px; border-radius: 10px; font-size: .86em; font-weight: 750; border: 1px solid var(--border-strong, var(--border)); background: var(--bg-elevated, var(--card)); color: var(--muted); }
.kt-belt-end.is-head { margin-left: auto; color: var(--kt-ok); border-color: var(--kt-ok); background: color-mix(in srgb, var(--kt-ok) 10%, var(--card)); box-shadow: 0 0 20px -6px var(--kt-ok); }
.kt-belt-chip { display: flex; flex-direction: column; gap: 1px; padding: 5px 11px 6px; border-radius: 12px; transition: opacity .3s;
  border: 1px solid color-mix(in srgb, var(--kt-ok) 50%, var(--border)); background: color-mix(in srgb, var(--kt-ok) 10%, var(--card)); }
.kt-belt-chip.is-conflict { border: 2px solid var(--kt-bad); background: color-mix(in srgb, var(--kt-bad) 14%, var(--card)); }
.kt-belt-chip.is-pending { border: 1px dashed var(--border-strong, var(--muted)); background: var(--card); }
.kt-belt-chip.is-new { animation: kt-slide-in 1s cubic-bezier(.2,.8,.2,1) 1; }
.kt-belt-chip.is-dim { opacity: .3; }
.kt-belt-role { appearance: none; border: 0; background: none; padding: 0; font: inherit; font-weight: 800; color: var(--text-strong); cursor: pointer; text-align: left; white-space: nowrap; }
.kt-belt-meta { font-size: .78em; color: var(--muted); white-space: nowrap; }
.kt-belt-meta code { color: var(--text); }
.kt-belt-note { font-size: .82em; font-weight: 800; color: var(--kt-bad); white-space: nowrap; }

.kt-body { display: grid; grid-template-columns: minmax(0, 1fr) minmax(360px, 400px); gap: 14px; align-items: start; }
.kt-col { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
.kt-side { position: sticky; top: 12px; display: flex; flex-direction: column; gap: 14px; min-width: 0; max-height: calc(100vh - 24px); overflow-y: auto; scrollbar-width: thin; }
.kt-side .kt-feed { display: flex; flex-direction: column; flex: 1 1 auto; min-height: 240px; }
.kt-side .kt-feed-list { flex: 1 1 auto; min-height: 0; max-height: none; }
@media (max-width: 1240px) { .kt-body { grid-template-columns: minmax(0, 1fr); } .kt-side { position: static; max-height: none; } .kt-side .kt-feed-list { max-height: 460px; } }

.kt-wall-score { font-size: 1.4em; font-weight: 850; font-variant-numeric: tabular-nums; color: var(--text-strong); }
.kt-wall-cmd { padding: 1px 7px; border-radius: 6px; font-size: .8em; color: var(--muted); background: color-mix(in srgb, var(--text) 6%, transparent); }
.kt-wall-at { font-size: .8em; }

.kt-wall-empty { margin: 4px 0; }
.kt-spark-row { display: grid; grid-template-columns: auto minmax(0, 1fr); align-items: center; gap: 10px; margin: -2px 0 10px; font-size: .78em; color: var(--muted); }
.kt-spark { display: block; width: 100%; height: 40px; overflow: visible; }
.kt-spark-total { stroke: var(--border-strong, var(--muted)); stroke-dasharray: 3 3; }
.kt-spark-area { fill: color-mix(in srgb, var(--kt-ok) 20%, transparent); }
.kt-spark-line { fill: none; stroke: var(--kt-ok); stroke-width: 2; stroke-linejoin: round; }
.kt-spark-pt.is-pass { fill: var(--kt-ok); } .kt-spark-pt.is-fail { fill: var(--kt-bad); }
.kt-spark-label { fill: var(--text-strong); font-size: 10px; font-weight: 800; }
.kt-wall-grid { display: flex; flex-wrap: wrap; gap: 6px; }
.kt-ac { display: flex; flex-direction: column; gap: 3px; }
.kt-ac-label { padding-left: 3px; font-size: .74em; font-weight: 800; color: var(--muted); }
.kt-group-label { padding-left: 3px; font-size: .82em; font-weight: 900; letter-spacing: .04em; color: var(--text-strong); }
.kt-ac-cells { display: flex; gap: 4px; }
.kt-ac.is-multi .kt-ac-cells { padding: 3px; border-radius: 13px; border: 1px dashed var(--border-strong, var(--border)); }
.kt-cell { position: relative; width: 54px; height: 54px; padding: 0; border: 0; border-radius: 12px; background: none; font: inherit; cursor: pointer; perspective: 320px; transition: opacity .3s; }
.kt-cell.is-pass { --kt-c: var(--kt-ok); } .kt-cell.is-fail { --kt-c: var(--kt-bad); } .kt-cell.is-skip { --kt-c: var(--muted); }
.kt-cell-face { position: absolute; inset: 0; display: grid; grid-template-rows: auto 1fr; padding: 4px 6px; border-radius: 12px; text-align: left;
  border: 2px solid var(--kt-c); background: color-mix(in srgb, var(--kt-c) 15%, var(--card)); color: var(--text-strong); transform-origin: 50% 50%; backface-visibility: hidden; }
.kt-cell.is-pass .kt-cell-face { background: var(--kt-ok-solid); border-color: color-mix(in srgb, var(--kt-ok) 75%, transparent); color: #fff; }
.kt-cell.is-skip .kt-cell-face { border-style: dashed; color: var(--muted); }
.kt-cell-ac { font-size: .72em; font-weight: 850; white-space: nowrap; }
.kt-cell-glyph { align-self: center; justify-self: center; margin-top: -4px; font-size: 1.4em; font-weight: 900; line-height: 1; }
.kt-cell.is-fail .kt-cell-glyph { color: var(--kt-bad); }
.kt-cell-owner { position: absolute; right: 3px; bottom: 1px; font-size: 13px; }
.kt-cell-face.is-flip { animation: kt-flip .85s cubic-bezier(.2,.8,.25,1) 1, kt-burst 1.3s ease-out 1; }
.kt-cell:hover .kt-cell-face, .kt-cell:focus-visible .kt-cell-face { box-shadow: 0 0 0 2px var(--accent); }
.kt-cell.is-dim { opacity: .28; }
.kt-cell.is-hot .kt-cell-face { box-shadow: 0 0 0 2px var(--accent); }
.kt-wall-inspect { display: flex; flex-wrap: wrap; align-items: baseline; gap: 3px 10px; min-height: 2.6em; margin-top: 10px; padding: 7px 10px; border-radius: 10px; font-size: .86em; background: color-mix(in srgb, var(--text) 4.5%, transparent); }
.kt-wall-inspect.is-fail { background: color-mix(in srgb, var(--kt-bad) 9%, transparent); }
.kt-wall-inspect strong { color: var(--text-strong); }
.kt-fail-msg { color: var(--kt-bad); font-weight: 750; }
.kt-inspect-owner { margin-left: 8px; }

.kt-feed-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 1px; max-height: 460px; overflow-y: auto; scrollbar-width: thin; }
.kt-ev { display: grid; grid-template-columns: 1.6em minmax(0, 1fr) auto auto; align-items: center; gap: 8px; padding: 5px 6px; border-radius: 8px; font-size: .88em; }
.kt-ev:hover { background: color-mix(in srgb, var(--text) 5%, transparent); }
.kt-ev-icon { text-align: center; }
.kt-ev-text { min-width: 0; overflow-wrap: anywhere; color: var(--text); }
.kt-ev.is-tool .kt-ev-text { color: var(--muted); }
.kt-ev.tone-bad .kt-ev-text { color: var(--kt-bad); font-weight: 750; }
.kt-ev.is-merged .kt-ev-text, .kt-ev.is-done .kt-ev-text { color: var(--kt-ok); }
.kt-ev.is-handoff .kt-ev-text { color: var(--kt-handoff); }
.kt-ev.is-new { animation: kt-ev-in 1.6s ease-out 1; }
.kt-ev-roles { display: inline-flex; align-items: center; gap: 2px; color: var(--muted); font-size: .9em; }
.kt-ev-role { appearance: none; padding: 0 4px; border-radius: 7px; border: 1px solid var(--border); background: var(--bg-elevated, var(--card)); font-size: 13px; line-height: 1.5; cursor: pointer; }
.kt-ev-role:hover { border-color: var(--accent); }
.kt-ev-time { color: var(--muted); font-size: .84em; white-space: nowrap; font-variant-numeric: tabular-nums; }
.kt-feed-empty { padding: 8px 6px; }
.kt-filter { appearance: none; font: inherit; font-size: .82em; font-weight: 700; padding: 2px 10px; border-radius: 999px; cursor: pointer; border: 1px solid var(--accent); background: color-mix(in srgb, var(--accent) 14%, transparent); color: var(--text-strong); }
.kt-check { margin-left: auto; display: inline-flex; align-items: center; gap: 4px; font-size: .82em; color: var(--muted); cursor: pointer; }

/* ---------- lanes ---------- */
.kt-lanes { display: flex; flex-direction: column; gap: 8px; min-width: 0; }
.kt-lane { position: relative; display: grid; grid-template-columns: 236px minmax(0, 1.2fr) minmax(0, 1fr); grid-template-areas: "id live work" "id track track";
  gap: 6px 16px; padding: 12px 14px 10px 18px; border-radius: 14px; border: 1px solid var(--border); background: var(--card); overflow: hidden;
  transition: opacity .3s, box-shadow .3s, border-color .3s; scroll-margin: 16px; }
.kt-lane::before { content: ''; position: absolute; left: 0; top: 0; bottom: 0; width: 4px; background: var(--kt-tone); }
.kt-lane.is-compact { grid-template-areas: "id live live" "id track track"; }
.kt-lane:is(.is-running, .is-fixing) { border-color: color-mix(in srgb, var(--kt-tone) 55%, var(--border));
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--kt-tone) 30%, transparent), 0 10px 30px -16px var(--kt-tone);
  background: linear-gradient(100deg, color-mix(in srgb, var(--kt-tone) 8%, var(--card)), var(--card) 45%); }
.kt-lane:is(.is-merged, .tone-ok) { background: linear-gradient(100deg, color-mix(in srgb, var(--kt-ok) 6%, var(--card)), var(--card) 40%); }
.kt-lane:is(.is-stalled, .is-awaiting_approval, .is-failed) { border-color: var(--kt-tone); box-shadow: 0 0 0 1px var(--kt-tone); }
.kt-lane.is-stalled { background-image: repeating-linear-gradient(135deg, color-mix(in srgb, var(--kt-warn) 7%, transparent) 0 10px, transparent 10px 20px); }
.kt-lane.is-waiting { background: color-mix(in srgb, var(--card) 70%, transparent); border-style: dashed; }
.kt-lane.is-dim { opacity: .42; }
.kt-lane.is-focus { border-color: var(--accent); box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 55%, transparent); }
.kt-lane.is-followed { font-size: 1.07em; border-color: var(--kt-tone); box-shadow: 0 0 0 2px var(--kt-tone), 0 16px 44px -16px var(--kt-tone); }
.kt-lane.is-followed::after { content: '跟随中'; position: absolute; top: 8px; right: 10px; padding: 1px 8px; border-radius: 999px; font-size: .72em; font-weight: 800; background: var(--kt-tone); color: var(--kt-on); }
.kt-lane-bump { position: absolute; inset: 0; border-radius: inherit; pointer-events: none; animation: kt-bump 1.8s ease-out 1 forwards; }
.kt-lane-axis { padding: 0 14px 0 18px; border: 0; background: none; box-shadow: none; }
.kt-lane-axis::before { display: none; }
.kt-axis-title { grid-area: id; align-self: end; font-size: .76em; color: var(--muted); white-space: nowrap; }
.kt-axis { grid-area: track; position: relative; height: 16px; }
.kt-axis-tick { position: absolute; top: 0; transform: translateX(-50%); font-size: .76em; color: var(--muted); font-variant-numeric: tabular-nums; }
.kt-axis-tick:first-child { transform: none; }
.kt-axis-tick:last-child { transform: translateX(-100%); }
.kt-lane-id { grid-area: id; display: grid; grid-template-columns: 52px minmax(0, 1fr); gap: 4px 10px; align-content: start; }
.kt-avatar { width: 52px; height: 52px; padding: 0; display: grid; place-items: center; border-radius: 16px; font-size: 27px; cursor: pointer;
  border: 2px solid var(--kt-tone); background: color-mix(in srgb, var(--kt-tone) 13%, var(--card)); transition: box-shadow .3s; }
.kt-lane.is-waiting .kt-avatar span { filter: grayscale(1); opacity: .55; }
.kt-lane:is(.is-merged, .tone-ok) .kt-avatar { background: var(--kt-ok-solid); border-color: var(--kt-ok-solid); }
.kt-lane:is(.is-running, .is-fixing) .kt-avatar { animation: kt-glow 2.4s ease-in-out infinite; }
.kt-lane-who { display: flex; flex-direction: column; justify-content: center; gap: 5px; min-width: 0; }
.kt-lane-name { display: flex; align-items: center; gap: 6px; font-size: 1.18em; line-height: 1.2; font-weight: 850; color: var(--text-strong); }
.kt-lane-doing { font-size: 12px; color: var(--muted); margin: 1px 0 3px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.kt-lane-doing.is-sent-back { color: var(--kt-fix); font-weight: 650; }
.kt-lane-tag { display: flex; align-items: center; gap: 6px; min-width: 0; }
.kt-lane-model { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: .74em; color: var(--muted); }
.kt-lane-stats { grid-column: 1 / -1; display: flex; flex-wrap: wrap; gap: 1px 10px; margin: 6px 0 0; font-size: .82em; color: var(--muted); font-variant-numeric: tabular-nums; }
.kt-lane-stats b { font-weight: 750; color: var(--text); }
.kt-lane-live { grid-area: live; display: flex; flex-direction: column; gap: 7px; min-width: 0; }
.kt-lane-work { grid-area: work; display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.kt-situation { display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 8px; padding: 6px 10px; border-radius: 10px; font-size: .93em;
  border: 1px solid color-mix(in srgb, var(--kt-tone) 42%, transparent); background: color-mix(in srgb, var(--kt-tone) 10%, transparent); color: var(--text); }
.kt-situation strong { color: var(--kt-tone); font-weight: 800; }
.kt-situation:is(.tone-ok, .tone-done) { padding: 0; border: 0; background: none; }
.kt-situation.tone-idle { background: none; border-style: dashed; }
.kt-situation.tone-idle strong { color: var(--text-strong); }
.kt-situation:is(.tone-warn, .tone-approve, .tone-bad) { font-weight: 600; }
.kt-summary { color: var(--text); overflow-wrap: anywhere; }
.kt-deps { display: flex; flex-wrap: wrap; gap: 6px; }
.kt-chip-role { appearance: none; font: inherit; font-size: .86em; font-weight: 650; padding: 1px 9px; border-radius: 999px; cursor: pointer;
  border: 1px solid color-mix(in srgb, var(--kt-tone) 48%, transparent); background: color-mix(in srgb, var(--kt-tone) 11%, transparent); color: var(--kt-tone); }
.kt-violation { padding: 6px 10px; border-radius: 10px; font-size: .93em; font-weight: 800; color: var(--kt-bad);
  border: 1px solid color-mix(in srgb, var(--kt-bad) 60%, transparent); background: color-mix(in srgb, var(--kt-bad) 13%, transparent); }
.kt-ticker { display: flex; align-items: center; gap: 6px; min-width: 0; font-weight: 700; color: var(--kt-tone); }
.kt-ticker-text { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; animation: kt-tick-in .45s ease-out 1; }
.kt-caret { display: inline-block; flex: none; width: .5em; height: 1.05em; margin-left: 2px; vertical-align: -.15em; background: currentColor; animation: kt-caret 1s steps(1) infinite; }
.kt-tail { margin: 0; display: flex; flex-direction: column; justify-content: flex-end; max-height: 4.9em; overflow: hidden; padding: 6px 10px; font-size: .92em; line-height: 1.55; color: var(--text);
  border-left: 3px solid color-mix(in srgb, var(--kt-tone) 65%, transparent); border-radius: 0 10px 10px 0; background: color-mix(in srgb, var(--text) 4%, transparent);
  -webkit-mask-image: linear-gradient(to bottom, transparent 0, #000 1.5em); mask-image: linear-gradient(to bottom, transparent 0, #000 1.5em); }
.kt-tail.is-fresh { animation: kt-fade-in .8s ease-out 1; }
.kt-lane.is-followed .kt-tail { max-height: 8em; }
.kt-tools { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: 5px; font-size: .8em; }
.kt-tools li { display: inline-flex; align-items: center; gap: 5px; max-width: 220px; padding: 2px 8px; border-radius: 8px; border: 1px solid var(--border); background: var(--kt-glass); color: var(--muted); }
.kt-tools li .kt-mono { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text); }
.kt-tools li time { font-size: .92em; white-space: nowrap; }
.kt-tools li.is-last { border-color: color-mix(in srgb, var(--kt-tone) 60%, transparent); background: color-mix(in srgb, var(--kt-tone) 12%, transparent); }
.kt-files-head { display: flex; align-items: baseline; gap: 8px; font-size: .84em; font-weight: 750; color: var(--text-strong); }
.kt-add { color: var(--kt-ok); font-weight: 750; } .kt-del { color: var(--kt-bad); font-weight: 750; }
.kt-files { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 3px; font-size: .8em; }
.kt-files li { display: grid; grid-template-columns: 1.3em minmax(0, 1fr) 64px 5.6em; align-items: center; gap: 6px; }
.kt-file-st { text-align: center; font-family: var(--mono, monospace); font-weight: 850; }
.kt-file-st.is-A { color: var(--kt-ok); } .kt-file-st.is-M { color: var(--kt-warn); } .kt-file-st.is-D { color: var(--kt-bad); }
.kt-file-path { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text); }
.kt-file-bar { display: flex; height: 7px; border-radius: 4px; overflow: hidden; background: color-mix(in srgb, var(--muted) 15%, transparent); }
.kt-bar-add { background: var(--kt-ok); } .kt-bar-del { background: var(--kt-bad); }
.kt-file-num { text-align: right; white-space: nowrap; }
.kt-files li.is-violation .kt-file-path { color: var(--kt-bad); font-weight: 800; text-decoration: underline wavy color-mix(in srgb, var(--kt-bad) 70%, transparent); text-underline-offset: 3px; }
.kt-files li.is-violation .kt-file-st { color: var(--kt-bad); }
.kt-files li.kt-more { display: block; font-size: .95em; }
.kt-commits { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 2px; font-size: .8em; }
.kt-commits li { display: flex; gap: 6px; min-width: 0; }
.kt-commits code { flex: none; color: var(--kt-handoff); }
.kt-commits span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.kt-owned { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; font-size: .78em; }
.kt-owned-case { padding: 1px 7px; border-radius: 6px; font-weight: 800; font-family: var(--mono, monospace); }
.kt-owned-case sub { font-size: .72em; margin-left: 2px; opacity: .75; vertical-align: baseline; }
.kt-owned-case.is-pass { color: var(--kt-ok); background: color-mix(in srgb, var(--kt-ok) 13%, transparent); }
.kt-owned-case.is-fail { color: var(--kt-bad); background: color-mix(in srgb, var(--kt-bad) 13%, transparent); }
.kt-owned-case.is-skip { color: var(--muted); background: var(--kt-glass); }
.kt-nothing { margin: 0; font-size: .84em; }
.kt-track { grid-area: track; position: relative; height: 14px; margin-top: 2px; }
.kt-track-line { position: absolute; left: 0; right: 0; top: 6px; height: 2px; border-radius: 1px; background: color-mix(in srgb, var(--muted) 22%, transparent); }
.kt-track-span { position: absolute; top: 3px; height: 8px; border-radius: 4px; background: color-mix(in srgb, var(--text) 34%, transparent); }
.kt-track-span.is-fix { background: color-mix(in srgb, var(--kt-fix) 65%, transparent); }
.kt-track-span.is-live { background: var(--kt-tone); box-shadow: 0 0 10px color-mix(in srgb, var(--kt-tone) 70%, transparent); }
.kt-track-span.is-live::after { content: ''; position: absolute; right: -3px; top: -3px; width: 14px; height: 14px; border-radius: 50%; background: var(--kt-tone); box-shadow: 0 0 10px var(--kt-tone); animation: kt-blink 1.4s ease-in-out infinite; }
.kt-track-mark { position: absolute; top: 0; width: 4px; height: 14px; margin-left: -2px; border-radius: 2px; background: var(--muted); }
.kt-track-mark.is-commit { top: 4px; width: 6px; height: 6px; margin-left: -3px; border-radius: 50%; background: var(--text-strong); box-shadow: 0 0 0 2px var(--card); }
.kt-track-mark.is-merged { background: var(--kt-ok); }
.kt-track-mark:is(.is-conflict, .is-bounce, .is-violation) { background: var(--kt-bad); }

/* ---------- the empty state and the probe ---------- */
.kt-empty { display: grid; gap: 22px; padding: 28px 30px; border-radius: 22px; border: 1px solid var(--border);
  background: radial-gradient(90% 90% at 0% 0%, color-mix(in srgb, var(--accent) 16%, transparent), transparent 60%), var(--card); }
.kt-empty-hero h2 { margin: 0 0 8px; font-size: 2.1em; font-weight: 850; color: var(--text-strong); letter-spacing: -.01em; }
.kt-empty-hero p { margin: 0; max-width: 62em; color: var(--text); font-size: 1.04em; line-height: 1.65; }
.kt-team-intro { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 22px; align-items: center; }
@media (max-width: 1000px) { .kt-team-intro { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
.kt-team-intro.is-phased { grid-template-columns: 1.15fr 1.15fr 1.6fr .8fr; align-items: stretch; gap: 14px; }
@media (max-width: 1000px) { .kt-team-intro.is-phased { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
.kt-intro-phase { display: flex; flex-direction: column; gap: 10px; padding: 12px; border-radius: 16px; border: 1px dashed color-mix(in srgb, var(--muted) 35%, transparent); }
.kt-intro-phase-head { display: flex; flex-direction: column; gap: 2px; }
.kt-intro-phase-head b { color: var(--text-strong); font-size: 1.02em; }
.kt-intro-phase-head span { color: var(--muted); font-size: .86em; }
.kt-intro-phase-body { display: flex; gap: 10px; align-items: center; flex: 1; }
.kt-intro-phase-body > .kt-intro-stage { flex: 1; min-width: 0; }
.kt-intro-stage { position: relative; display: flex; flex-direction: column; gap: 8px; }
.kt-intro-stage:not(:last-child)::after { content: '→'; position: absolute; right: -18px; top: 50%; transform: translateY(-50%); color: var(--kt-handoff); font-weight: 900; font-size: 1.2em; }
.kt-intro-role { display: grid; grid-template-columns: 36px minmax(0, 1fr); grid-template-rows: auto auto; column-gap: 8px; padding: 9px 11px; border-radius: 14px; border: 1px solid var(--border); background: var(--bg-elevated, var(--card)); }
.kt-empty-punch { margin-top: 10px; font-size: 1.12em; font-weight: 850; color: var(--text-strong); }
.kt-intro-emoji { grid-row: span 2; align-self: center; color: var(--text-strong); opacity: .85; }
.kt-role-icon { display: inline-block; vertical-align: -0.18em; flex: none; }
.kt-start-row { display: flex; gap: 12px; flex-wrap: wrap; margin-top: 10px; }
.kt-start-field { display: flex; flex-direction: column; gap: 4px; flex: 1 1 360px; font-size: .9em; }
.kt-start-field span { font-weight: 750; color: var(--text-strong); }
.kt-start-field.is-narrow { flex: 0 1 260px; }
.kt-start-field input, .kt-start-field select { font: inherit; padding: 8px 10px; border-radius: 10px; border: 1px solid var(--border-strong, var(--border)); background: var(--bg); color: var(--text); font-weight: 400; }
.kt-start-field input::placeholder, .kt-start textarea::placeholder { color: var(--muted); font-weight: 400; }
.kt-intro-role b { color: var(--text-strong); }
.kt-intro-does { font-size: .82em; color: var(--muted); }
.kt-intro-name { display: flex; align-items: baseline; gap: 4px; min-width: 0; }
.kt-intro-agent { font-size: 11px; font-weight: 600; color: var(--muted); }
.kt-intro-par { align-self: flex-start; padding: 1px 9px; border-radius: 999px; font-size: .74em; font-weight: 850; color: var(--kt-run); background: color-mix(in srgb, var(--kt-run) 13%, transparent); border: 1px solid color-mix(in srgb, var(--kt-run) 40%, transparent); }
.kt-debug summary { cursor: pointer; font-size: .84em; color: var(--muted); }
.kt-debug pre { max-height: 320px; overflow: auto; margin: 8px 0 0; padding: 10px 12px; border-radius: 10px; font-size: 12px; background: var(--bg-elevated, var(--card)); border: 1px solid var(--border); }

/* ---------- projection ---------- */
.kt-root.is-projection { position: fixed; inset: 0; z-index: 2147483000; height: 100vh; overflow: hidden; background: var(--bg); font-size: 16.5px; padding: 16px 26px 18px; gap: 12px; }
.kt-root.is-projection .kt-body { flex: 1 1 auto; min-height: 0; grid-template-columns: minmax(0, 1fr) minmax(400px, 470px); align-items: stretch; }
.kt-root.is-projection .kt-col { min-height: 0; overflow: hidden; }
.kt-root.is-projection .kt-col > :not(.kt-lanes) { flex: none; }
.kt-root.is-projection > :not(.kt-body) { flex: none; }
.kt-root.is-projection .kt-graph-svg { max-height: 44vh; }
.kt-root.is-projection .kt-graph.is-phased .kt-graph-svg { max-height: 62vh; }
.kt-root.is-projection .kt-body:has(.kt-graph.is-phased) { grid-template-columns: minmax(0, 1fr) minmax(300px, 340px); }
.kt-root.is-projection .kt-lanes { flex: 1 1 auto; min-height: 0; overflow-y: auto; scrollbar-width: thin; padding-right: 4px; }
.kt-root.is-projection .kt-lane { flex: none; }
.kt-root.is-projection .kt-side { position: static; max-height: none; min-height: 0; height: 100%; }
.kt-root.is-projection .kt-lane:is(.is-merged, .is-waiting):not(.is-followed):not(.is-focus) { grid-template-areas: "id live live" "id track track"; padding-top: 8px; padding-bottom: 6px; }
.kt-root.is-projection .kt-lane:is(.is-merged, .is-waiting):not(.is-followed):not(.is-focus) :is(.kt-lane-work, .kt-lane-stats, .kt-lane-model, .kt-deps) { display: none; }
.kt-root.is-projection .kt-lane:is(.is-merged, .is-waiting):not(.is-followed):not(.is-focus) .kt-avatar { width: 40px; height: 40px; font-size: 21px; border-radius: 12px; }
.kt-root.is-projection .kt-lane:is(.is-merged, .is-waiting):not(.is-followed):not(.is-focus) .kt-lane-id { grid-template-columns: 40px minmax(0, 1fr); }
.kt-root:fullscreen { background: var(--bg); }

/* ---------- 产出: each step's deliverables ---------- */
.kt-grow { flex: 1 1 auto; }
.kt-folder { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.kt-folder-path { padding: 4px 8px; border-radius: 8px; background: var(--kt-glass); border: 1px solid var(--border); overflow-wrap: anywhere; user-select: all; }
.kt-folder-acts { display: inline-flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.kt-folder-panel { display: grid; gap: 8px; padding: 10px 14px; border-radius: 12px; border: 1px solid var(--border); background: var(--card); }
.kt-folder-panel-head { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
.kt-pane-folder { margin-top: 2px; font-size: .9em; }
.kt-pad { padding: 12px 14px; margin: 0; }
.kt-btn.is-small { padding: 4px 10px; font-size: .84em; border-radius: 8px; }
.kt-seg { display: inline-flex; gap: 4px; }
.kt-out-btn { grid-column: 1 / -1; justify-self: start; appearance: none; border: 0; background: none; padding: 2px 0 0; font: inherit; font-size: .84em; font-weight: 750; color: var(--accent); cursor: pointer; }
.kt-out-btn:hover { text-decoration: underline; }
.kt-file-open { appearance: none; border: 0; background: none; padding: 0; font: inherit; text-align: left; cursor: pointer; }
.kt-file-open:hover { color: var(--accent); text-decoration: underline; }
.kt-drawer-backdrop { position: fixed; inset: 0; z-index: 80; display: flex; justify-content: flex-end; background: color-mix(in srgb, #05030a 46%, transparent); animation: kt-fade-in .16s ease-out; }
.kt-drawer { width: min(1240px, 96vw); height: 100%; display: flex; flex-direction: column; min-height: 0; background: var(--bg, var(--card)); color: var(--text);
  border-left: 1px solid var(--border-strong, var(--border)); box-shadow: -30px 0 80px rgba(0, 0, 0, .38); }
.kt-drawer-top { display: flex; align-items: center; gap: 10px; padding: 14px 20px 10px; }
.kt-drawer-top h2 { margin: 0; font-size: 1.12em; color: var(--text-strong); }
.kt-steps { display: flex; gap: 6px; padding: 4px 20px 12px; overflow-x: auto; border-bottom: 1px solid var(--border); }
.kt-step { appearance: none; display: inline-flex; align-items: center; gap: 6px; padding: 5px 12px 5px 6px; border-radius: 999px; cursor: pointer; white-space: nowrap; font: inherit; font-size: .9em; font-weight: 700;
  border: 1px solid color-mix(in srgb, var(--kt-tone, var(--border)) 45%, var(--border)); background: color-mix(in srgb, var(--kt-tone, var(--muted)) 8%, var(--card)); color: var(--text); }
.kt-step-n { display: inline-grid; place-items: center; width: 20px; height: 20px; border-radius: 50%; font-size: .78em; background: color-mix(in srgb, var(--kt-tone, var(--muted)) 30%, transparent); color: var(--text-strong); }
.kt-step.is-product { padding-left: 12px; }
.kt-step.is-on { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 22%, var(--card)); color: var(--text-strong); box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 35%, transparent); }
.kt-pane { flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column; }
.kt-pane-head { padding: 12px 20px 0; display: grid; gap: 6px; }
.kt-pane-who { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.kt-pane-who h3 { margin: 0; font-size: 1.2em; color: var(--text-strong); }
.kt-pane-emoji { color: var(--text-strong); }
.kt-pane-scope { margin: 0; font-size: .86em; }
.kt-tabs { display: flex; gap: 2px; border-bottom: 1px solid var(--border); margin-top: 4px; }
.kt-tab { appearance: none; border: 0; background: none; padding: 9px 14px; margin-bottom: -1px; font: inherit; font-weight: 750; color: var(--muted); cursor: pointer; border-bottom: 2px solid transparent; }
.kt-tab sub { font-size: .72em; margin-left: 3px; vertical-align: baseline; opacity: .8; }
.kt-tab[aria-selected="true"] { color: var(--text-strong); border-bottom-color: var(--accent); }
.kt-tab:hover { color: var(--text-strong); }
.kt-pane-body { flex: 1 1 auto; min-height: 0; overflow: auto; padding: 14px 20px 26px; }
.kt-files-pane { display: grid; grid-template-columns: minmax(220px, 310px) minmax(0, 1fr); gap: 14px; height: 100%; min-height: 420px; }
.kt-flist { overflow: auto; min-height: 0; }
.kt-flist ul { list-style: none; margin: 0 0 12px; padding: 0; display: grid; gap: 2px; }
.kt-flist-h { margin: 4px 0 6px; font-size: .78em; font-weight: 800; letter-spacing: .04em; color: var(--muted); }
.kt-frow { appearance: none; width: 100%; display: grid; grid-template-columns: 1.3em minmax(0, 1fr) auto; gap: 6px; align-items: center; padding: 5px 8px; border-radius: 8px; border: 1px solid transparent;
  background: none; font: inherit; font-size: .86em; color: var(--text); text-align: left; cursor: pointer; }
.kt-frow:hover { background: var(--kt-glass); }
.kt-frow.is-on { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 14%, transparent); }
.kt-frow-path { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.kt-frow-num { font-size: .92em; white-space: nowrap; }
.kt-fview { min-width: 0; min-height: 0; display: flex; flex-direction: column; border: 1px solid var(--border); border-radius: 12px; background: var(--card); overflow: hidden; }
.kt-fview-bar { display: flex; align-items: center; gap: 8px; padding: 8px 12px; border-bottom: 1px solid var(--border); flex-wrap: wrap; }
.kt-fview-path { font-weight: 750; color: var(--text-strong); overflow-wrap: anywhere; }
.kt-fview-body { flex: 1 1 auto; min-height: 0; overflow: auto; }
.kt-code { list-style: none; margin: 0; padding: 8px 0 12px; counter-reset: kt-ln; font-family: var(--mono, ui-monospace, monospace); font-size: 12.5px; line-height: 1.6; }
.kt-code li { counter-increment: kt-ln; display: grid; grid-template-columns: 4.4em minmax(0, 1fr); }
.kt-code li::before { content: counter(kt-ln); text-align: right; padding-right: 14px; color: var(--muted); opacity: .65; user-select: none; }
.kt-code code { white-space: pre-wrap; overflow-wrap: anywhere; font-size: 1em; padding-right: 12px; }
.kt-code.is-diff li.is-add { background: color-mix(in srgb, var(--kt-ok) 15%, transparent); }
.kt-code.is-diff li.is-add code { color: var(--text-strong); }
.kt-code.is-diff li.is-del { background: color-mix(in srgb, var(--kt-bad) 15%, transparent); }
.kt-code.is-diff li.is-hunk { color: var(--kt-info); background: color-mix(in srgb, var(--kt-info) 8%, transparent); }
.kt-code.is-diff li.is-meta { color: var(--muted); }
.kt-md { padding: 14px 18px; overflow-wrap: anywhere; }
.kt-reply { max-width: 920px; padding: 4px 2px; }
.kt-rounds { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 8px; }
.kt-attempt-meta { margin: 0 0 10px; font-size: .86em; }
.kt-task { margin: 0; padding: 12px 14px; border-radius: 12px; border: 1px solid var(--border); background: var(--card); white-space: pre-wrap; overflow-wrap: anywhere; font-size: 12.5px; line-height: 1.6; }
.kt-calls { list-style: none; margin: 0; padding: 0; display: grid; }
.kt-calls li { display: grid; grid-template-columns: 4.2em 1.7em minmax(0, 1fr); gap: 6px; align-items: baseline; padding: 5px 2px; border-bottom: 1px dashed var(--border); font-size: .86em; }
.kt-calls li span:last-child { overflow-wrap: anywhere; }
.kt-site { display: flex; flex-direction: column; gap: 10px; height: 100%; min-height: 520px; }
.kt-site-bar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.kt-site-bar a { color: var(--accent); font-weight: 750; }
.kt-site-frame { flex: 1 1 auto; width: 100%; min-height: 560px; border: 1px solid var(--border-strong, var(--border)); border-radius: 12px; background: #fff; }
.kt-site-log pre { margin: 6px 0 0; max-height: 220px; overflow: auto; padding: 10px 12px; border-radius: 10px; background: var(--card); border: 1px solid var(--border); font-size: 12px; white-space: pre-wrap; }
@media (max-width: 900px) { .kt-files-pane { grid-template-columns: minmax(0, 1fr); } }

/* ---------- motion ---------- */
@keyframes kt-halo { 0%, 100% { opacity: .1; transform: scale(.985); } 50% { opacity: .55; transform: scale(1.025); } }
@keyframes kt-spin { to { transform: rotate(360deg); } }
@keyframes kt-ants { to { stroke-dashoffset: -36; } }
@keyframes kt-beacon { 0%, 100% { opacity: .15; } 50% { opacity: .85; } }
@keyframes kt-blink { 0%, 100% { opacity: 1; } 50% { opacity: .3; } }
@keyframes kt-glow { 0%, 100% { box-shadow: 0 0 0 3px color-mix(in srgb, var(--kt-tone) 14%, transparent), 0 0 8px color-mix(in srgb, var(--kt-tone) 25%, transparent); }
  50% { box-shadow: 0 0 0 5px color-mix(in srgb, var(--kt-tone) 26%, transparent), 0 0 22px color-mix(in srgb, var(--kt-tone) 65%, transparent); } }
@keyframes kt-flash { 0% { opacity: 1; transform: scale(1); } 35% { opacity: .9; } 100% { opacity: 0; transform: scale(1.14); } }
@keyframes kt-flip { 0% { transform: rotateX(-92deg); filter: brightness(1.9); } 65% { transform: rotateX(14deg); } 100% { transform: rotateX(0); filter: none; } }
@keyframes kt-burst { 0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--kt-c) 80%, transparent); } 100% { box-shadow: 0 0 0 16px transparent; } }
@keyframes kt-slide-in { 0% { transform: translateX(-46px) scale(.88); opacity: 0; } 55% { opacity: 1; } 75% { transform: translateX(3px) scale(1.02); } 100% { transform: none; } }
@keyframes kt-ev-in { 0% { transform: translateY(-10px); opacity: 0; background: color-mix(in srgb, var(--accent) 28%, transparent); } 25% { transform: none; opacity: 1; } 100% { background: transparent; } }
@keyframes kt-bump { 0% { opacity: 1; box-shadow: inset 0 0 0 2px var(--kt-tone); background: color-mix(in srgb, var(--kt-tone) 16%, transparent); } 100% { opacity: 0; box-shadow: inset 0 0 0 2px var(--kt-tone); } }
@keyframes kt-pop { 0% { transform: scale(1); } 35% { transform: scale(1.22); color: var(--kt-ok); } 100% { transform: scale(1); } }
@keyframes kt-tick-in { 0% { opacity: 0; transform: translateY(5px); } 100% { opacity: 1; transform: none; } }
@keyframes kt-caret { 50% { opacity: 0; } }
@keyframes kt-fade-in { 0% { opacity: 0; } 100% { opacity: 1; } }
@media (prefers-reduced-motion: reduce) {
  .kt-root *, .kt-root *::before, .kt-root *::after { animation: none !important; transition: none !important; }
}
.kt-root[data-motion="reduce"] *, .kt-root[data-motion="reduce"] *::before, .kt-root[data-motion="reduce"] *::after { animation: none !important; transition: none !important; }
`
