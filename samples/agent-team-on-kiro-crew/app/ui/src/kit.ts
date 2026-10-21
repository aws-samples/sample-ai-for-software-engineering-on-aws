/**
 * The one card kit of the app's three views (CTO 视图, 交付详情, 团队看板). Their components keep their own class names
 * and inner layout; how a card is framed is defined here only, so the views cannot drift apart again:
 *
 * - 指标卡 (the board's counters, the CTO view's and 交付详情's cards): radius 16, a 1 px border, the glass highlight at
 *   the top right, padding 16/18; the cards of a row are as tall as each other.
 * - 区块卡 (team graph, lanes, 专家条, 知识库, 测试墙, 事件, 传送带, 签字单, 每周上线, 需求流动, 交付清单, 价值流 …):
 *   radius 16, a 1 px border, no highlight, padding 16/20, one heading style.
 * - Inside a card: cells radius 10, role chips 8, pills round.
 * - Spacing: 12 between the cards of a row, 16 between blocks.
 * - A border says a state and nothing else, always 1 px: green 全绿 / 已签字 / 已合入, magenta 等人批准, blue 在跑,
 *   red 失败. Only a run in progress glows (the root carries `is-live`).
 * - Label 0.93em/650 muted; big number 2.85em/800, tight, tabular; its "of" 1.43em muted. A number is coloured only when
 *   it is itself a state (38/38 全绿, 4/25 failing).
 *
 * Sizes are in em, so 投影 (a larger root font size) scales every card the same way. Included last in each view.
 */

const KPI = '.kt-kpi, .cto-cards > .cto-card'
const BLOCK = '.kt-card, .kt-experts, .kt-kb, .kt-sign, .kt-start, .cto-root > section.cto-card'
const FRAMED = `${KPI}, ${BLOCK}, .kt-graph, .kt-lane`
const HEAD = '.kt-card-head h2, .kt-experts-title, .kt-kb-head b, .kt-sign-head h2, .cto-chart-head h3, .cto-flow-head h3, .cto-ledger-head h3'

export const KIT_CSS = `
.kt-root { --kit-r: 16px; --kit-r-cell: 10px; --kit-pad-kpi: 16px 18px; --kit-pad-block: 16px 20px; --kit-gap-row: 12px; --kit-gap-block: 16px;
  --kit-ok: color-mix(in srgb, var(--kt-ok) 55%, var(--border)); --kit-wait: color-mix(in srgb, var(--kt-approve) 55%, var(--border));
  --kit-run: color-mix(in srgb, var(--kt-run) 55%, var(--border)); --kit-bad: color-mix(in srgb, var(--kt-bad) 55%, var(--border)); gap: var(--kit-gap-block); }
${FRAMED} { border-radius: var(--kit-r); border: 1px solid var(--border); }
${KPI}, ${BLOCK} { background-color: var(--card); }
${KPI} { position: relative; overflow: hidden; padding: var(--kit-pad-kpi); }
.kt-kpi::after, .cto-cards > .cto-card::after { content: ''; position: absolute; inset: 0; pointer-events: none; border-radius: inherit;
  background: radial-gradient(90% 70% at 100% 0%, color-mix(in srgb, var(--text) 4%, transparent), transparent 70%); }
${BLOCK} { padding: var(--kit-pad-block); margin: 0; }
.kt-kpis, .cto-cards { gap: var(--kit-gap-row); align-items: stretch; }
.cto-kcard, .kt-kb-chip, .cto-cell, .cto-lane { border-radius: var(--kit-r-cell); }

.kt-kpi-label, .cto-eyebrow { font-size: .93em; font-weight: 650; color: var(--muted); letter-spacing: .04em; }
.kt-kpi-big, .cto-value { font-size: 2.85em; font-weight: 800; letter-spacing: -.03em; line-height: 1.1; font-variant-numeric: tabular-nums; color: var(--text-strong); text-shadow: none; }
.kt-kpi-of, .cto-of { font-weight: 700; letter-spacing: 0; color: var(--muted); }
.kt-kpi-of { font-size: 1.43em; } /* beside the number; the CTO view's 「credits」「/37」 sit inside it at .5em: the same 20 px */
${HEAD} { margin: 0; font-size: 1.1em; font-weight: 700; color: var(--text-strong); letter-spacing: 0; }
.kt-kb-head b { display: inline-flex; align-items: center; gap: 6px; }
.kt-kb-head b .kt-role-icon { color: var(--kt-info); }
.kt-sign-done > .kt-role-icon { vertical-align: -3px; color: var(--kt-ok); }

/* the crumb of a view opened from another: where it is, the way back */
.kit-crumb { display: flex; align-items: center; gap: 6px 8px; flex-wrap: wrap; font-size: .93em; color: var(--muted); }
.kit-crumb button:not(.kt-btn) { border: 0; background: transparent; padding: 0; font: inherit; color: var(--accent); cursor: pointer; }
.kit-crumb button:not(.kt-btn):hover { text-decoration: underline; text-underline-offset: 3px; }
.kit-crumb b { color: var(--text-strong); font-weight: 600; }
.kit-crumb .kt-grow { flex: 1; }
.kt-where-why { padding: 2px 10px; border-radius: 999px; background: color-mix(in srgb, var(--text) 7%, transparent); color: var(--text); } /* a note, not a state: no border */

/* a border says a state */
/* (under .kt-root: a state outranks the frame rules above, \`.cto-root > section.cto-card\` among them) */
.kt-root .kt-kpi-tests.is-green, .kt-root .kt-wall.is-green, .kt-root .kt-sign.is-signed, .kt-root .cto-card.is-ok { border-color: var(--kit-ok); }
.kt-root .kt-sign:not(.is-signed), .kt-root .cto-card.is-wait { border-color: var(--kit-wait); }
.kt-root .cto-card.is-bad { border-color: var(--kit-bad); }
.kt-kpi-tests.is-green .kt-kpi-big, .kt-kpi-gates .kt-kpi-big, .cto-card.is-ok .cto-value { color: var(--kt-ok); }
.cto-card.is-bad .cto-value { color: var(--kt-bad); }
.cto-kcard { border-color: var(--border); box-shadow: none; }
.cto-kcard.is-live.is-wait { border-color: var(--kit-wait); }
.cto-kcard.is-live.is-agent { border-color: var(--kit-run); }
/* only a run in progress glows */
.kt-root.is-live .kt-kpi-tests.is-green, .kt-root.is-live .kt-wall.is-green { box-shadow: 0 0 34px -12px var(--kt-ok); }
.cto-kcard.is-live { box-shadow: 0 0 0 2px color-mix(in srgb, var(--kt-approve) 18%, transparent); }
.cto-kcard.is-live.is-agent { box-shadow: 0 0 0 2px color-mix(in srgb, var(--kt-run) 18%, transparent); }
`
