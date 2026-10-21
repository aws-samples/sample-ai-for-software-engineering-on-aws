/**
 * Standalone preview of the board for screenshots without KiroCrew: the real page (src/main.tsx)
 * against the stubbed SDK (src/test/stubs, the same ones vitest uses) and the fixtures of
 * src/test/fixtures.ts. Built by `npm run preview:build` into preview-dist/index.html (one file).
 *
 *   ?fixture=running|finished|started|trouble|failed|empty|multi   the snapshot the stub serves
 *   ?simulate=1        play scenario() forward, one snapshot every 3.2 s (?stepMs=…); ?step=n freezes it
 *   ?mode=light        the kiro-light theme (default kiro-dark)
 *   ?fixture=gate      a real run rebuilt at a moment: the IM run r1012307c at its 安全 gate (&t=<秒> for another moment)
 *   (no ?view)         the CTO 视图: the shipped history (cto/history.json) with two measured runs and a live card;
 *                      ?view=board for the board (its links in the CTO view go there)
 *
 * Every snapshot's times are moved so that its `at` is now: relative times read as in a live run.
 */
import { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import App from '../src/main'
import history from '../../cto/history.json'
import { ctoData, ctoFlow } from '../src/cto/testdata'
import type { CtoData } from '../src/cto/types'
import { setApiRoutes } from '../src/test/stubs/app-sdk'
import { FIXTURES, asRun, clone, multiRunBoard, scenario, shiftTimes, startedBoard, type FixtureName } from '../src/test/fixtures'
import type { Board, RunDetail, TeamEvent } from '../src/types'
import realRun from '../src/test/fixtures/replay-im.json'
import { replayAt, replaySpan } from '../src/board/timeline'

const q = new URLSearchParams(location.search)
const gate = q.get('fixture') === 'gate'
const fixture = (q.get('fixture') && q.get('fixture')! in FIXTURES ? q.get('fixture') : 'running') as FixtureName

/** The real IM run at the moment its 安全 gate waited for the person. */
function gateBoard(): Board {
  const src = realRun
  const { run, events } = clone(src) as unknown as { run: RunDetail; events: TeamEvent[] }
  const t = replaySpan(run, events).start + Number(q.get('t') ?? 262)
  const r = replayAt(run, events, t)
  return { at: t, runs: [{ id: r.id, title: r.title, status: r.status, started_at: r.started_at, ended_at: null, roles_done: r.roles.filter((l) => l.status === 'merged').length, roles_total: r.roles.length, tests: { passed: r.tests.passed, failed: r.tests.failed, total: r.tests.total } }], run: r } as unknown as Board
}
const simulate = q.get('simulate') === '1'
const mode = q.get('mode') === 'light' ? 'light' : 'dark'
const STEP_MS = Math.max(500, Number(q.get('stepMs') ?? 3200))
const frozen = q.get('step')
document.documentElement.dataset.mode = mode
document.documentElement.dataset.theme = `kiro-${mode}`

const steps = scenario()
const t0 = performance.now()
/** What 开一个新运行 / 停止 turned the preview's world into. */
let override: Board | null = null

function stepIndex(): number {
  if (frozen !== null) return Math.min(steps.length - 1, Math.max(0, Number(frozen) || 0))
  return Math.min(steps.length - 1, Math.floor((performance.now() - t0) / STEP_MS))
}

function snapshot(run: string | null): Board {
  let b: Board
  if (override) b = clone(override)
  else if (gate) b = gateBoard()
  else if (simulate) b = clone(steps[stepIndex()])
  else if (fixture === 'multi') b = multiRunBoard(run)
  else b = FIXTURES[fixture]()
  return shiftTimes(b, Date.now() / 1000 - b.at)
}

/** The CTO view's answer: the shipped history, and from the tests' data two measured runs and a run waiting at its gate. */
function cto(): CtoData {
  const t = ctoData()
  const h = history as unknown as CtoData
  return { meta: { ...h.meta, realAvgMins: 21 }, items: [...t.items.filter((i) => i.real).map((i) => ({ ...i, ship: h.meta.today })), ...h.items], wip: [t.wip[0], ...h.wip] }
}

setApiRoutes({
  'GET /api/apps/aidlc-team/cto': () => cto(),
  'GET /api/apps/aidlc-team/cto/offline': () => ({ name: 'CTO视图-离线版-预览.html', html: '<p>预览：离线版由后端生成</p>' }),
  'GET /api/apps/aidlc-team/cto/flow*': (_body, path) => ({ ...ctoFlow(), run: new URL(path, location.origin).searchParams.get('run') ?? 'r1013f04d' }),
  'GET /api/apps/aidlc-team/board*': (_body, path) => snapshot(new URL(path, location.origin).searchParams.get('run')),
  'POST /api/apps/aidlc-team/runs': (body) => {
    const requirement = (body as { requirement?: string } | null)?.requirement?.trim()
    const title = requirement ? requirement.split('\n')[0].slice(0, 24) : '活动报名小站'
    override = shiftTimes(asRun(startedBoard(), 'r1007b', title, 0), Date.now() / 1000 - startedBoard().at)
    return { id: 'r1007b' }
  },
  'POST /api/apps/aidlc-team/runs/*': (_body, path) => {
    if (path.endsWith('/stop')) {
      const b = snapshot(null)
      const r = b.run
      if (r) {
        r.status = 'stopped'
        r.ended_at = b.at
        for (const l of r.roles) {
          if (['running', 'fixing', 'stalled', 'awaiting_approval', 'queued'].includes(l.status)) {
            l.status = 'failed'
            if (l.agent) l.agent.error = '运行被停止'
          }
        }
        b.runs = b.runs.map((c) => (c.id === r.id ? { ...c, status: 'stopped', ended_at: b.at } : c))
      }
      override = b
    }
    return { ok: true }
  },
  'GET /api/apps/aidlc-team/probe': () => ({
    kirocrew_version: 'preview',
    subagent_manager: 'SubagentManager（预览：假数据）',
    manager_methods: ['all_agents', 'spawn'],
    agents: [],
    elapsed_ms: 0.4,
  }),
})

function href(params: Record<string, string | null>): string {
  const u = new URLSearchParams(location.search)
  for (const [k, v] of Object.entries(params)) {
    if (v === null) u.delete(k)
    else u.set(k, v)
  }
  return `?${u.toString()}`
}

function Bar() {
  const [step, setStep] = useState(stepIndex())
  useEffect(() => {
    if (!simulate) return
    const id = setInterval(() => setStep(stepIndex()), 250)
    return () => clearInterval(id)
  }, [])
  return (
    <div className="pv-bar">
      <b>看板预览</b>
      {(Object.keys(FIXTURES) as FixtureName[]).map((f) => (
        <a key={f} href={href({ fixture: f, simulate: null, step: null })} aria-current={!simulate && f === fixture}>
          {f}
        </a>
      ))}
      <a href={href({ simulate: '1', step: null, fixture: null })} aria-current={simulate}>
        simulate ▶
      </a>
      {simulate && (
        <span className="pv-step">
          第 {step + 1}/{steps.length} 拍{frozen === null && step < steps.length - 1 ? ` · 每 ${(STEP_MS / 1000).toFixed(1)} 秒一拍` : ''}
        </span>
      )}
      {simulate && <a href={href({ simulate: '1', step: null })}>重新播放</a>}
      <a href={href({ mode: mode === 'dark' ? 'light' : 'dark' })}>{mode === 'dark' ? '换亮色' : '换暗色'}</a>
      <span>数据是 fixture，接口是 src/test/stubs 里的假实现</span>
    </div>
  )
}

createRoot(document.getElementById('root')!).render(
  <>
    <Bar />
    <App />
  </>,
)
