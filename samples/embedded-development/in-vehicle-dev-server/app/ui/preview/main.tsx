/**
 * Standalone preview of the board for screenshots without KiroCrew: the real page (src/main.tsx)
 * against the stubbed SDK (src/test/stubs, the same ones vitest uses) and the fixtures of
 * src/test/fixtures.ts. Built by `npm run preview:build` into preview-dist/index.html (one file).
 *
 *   ?fixture=vstatd|vstatd-triage|vstatd-release                     the vstatd team: at the bench (the default), at its triage gate, at sign-off
 *   ?fixture=empty                                                   no runs: the work item, the flow, 准备情况 (GET /readiness), 知识库 (GET /knowledge), 需求清单 (GET /backlog) and 组队预览 (GET /team)
 *   ?fixture=running|finished|started|trouble|failed|multi           the snapshot the stub serves (the web team of the tests)
 *   ?view=score        the 评分卡, from the run of vstatd-release
 *   ?view=item&run=<id>  交付详情 (GET /runs/<id>/flow) of the run of vstatd-release
 *   (every run's 审计记录 is GET /runs/<id>/audit of that run; the home page's bench actions GET /audit/bench)
 *   ?simulate=1        play scenario() forward, one snapshot every 3.2 s (?stepMs=…); ?step=n freezes it
 *   ?mode=light        the kiro-light theme (default kiro-dark)
 *   ?fixture=gate      a real run rebuilt at a moment: the IM run r1012307c at its 安全 gate (&t=<秒> for another moment)
 *
 * Every snapshot's times are moved so that its `at` is now: relative times read as in a live run.
 */
import { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import App from '../src/main'
import { apiError, setApiRoutes } from '../src/test/stubs/app-sdk'
import { FIXTURES, asRun, auditOf, benchAuditOf, backlogOf, clone, knowledgeOf, knowledgeTextOf, multiRunBoard, readinessOf, scenario, scorecardOf, shiftTimes, startedBoard, flowOf, teamOf, vstatdBoard, type FixtureName } from '../src/test/fixtures'
import type { Board, RunDetail, TeamEvent } from '../src/types'
import realRun from '../src/test/fixtures/replay-im.json'
import { replayAt, replaySpan } from '../src/board/timeline'

const q = new URLSearchParams(location.search)
const gate = q.get('fixture') === 'gate'
const fixture = (q.get('fixture') && q.get('fixture')! in FIXTURES ? q.get('fixture') : 'vstatd') as FixtureName

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

setApiRoutes({
  'GET /api/apps/vstatd-team/board*': (_body, path) => snapshot(new URL(path, location.origin).searchParams.get('run')),
  'GET /api/apps/vstatd-team/scorecard': () => scorecardOf(vstatdBoard('release')),
  'GET /api/apps/vstatd-team/readiness': () => readinessOf(Date.now() / 1000),
  'POST /api/apps/vstatd-team/readiness/doctor': () => readinessOf(Date.now() / 1000),
  'GET /api/apps/vstatd-team/knowledge': () => knowledgeOf(),
  'GET /api/apps/vstatd-team/backlog': () => backlogOf(),
  'GET /api/apps/vstatd-team/team': () => teamOf(),
  'GET /api/apps/vstatd-team/runs/*': (_body, path) => {  // 交付详情 and 审计记录 only: the other run reads have no stub here
    const rid = path.split('/')[5]
    if (path.endsWith('/audit')) return { ...auditOf(), run: rid }
    if (!path.endsWith('/flow')) throw apiError(404, 'route_not_found', 'no stub route')
    return { ...flowOf(), run: rid }
  },
  'GET /api/apps/vstatd-team/audit/bench': () => benchAuditOf(Date.now() / 1000),
  'GET /api/apps/vstatd-team/knowledge/file*': (_body, path) => knowledgeTextOf(new URL(path, location.origin).searchParams.get('path') ?? ''),
  'POST /api/apps/vstatd-team/runs': (body) => {
    const requirement = (body as { requirement?: string } | null)?.requirement?.trim()
    const title = requirement ? requirement.split('\n')[0].slice(0, 24) : '活动报名小站'
    override = shiftTimes(asRun(startedBoard(), 'r1007b', title, 0), Date.now() / 1000 - startedBoard().at)
    return { id: 'r1007b' }
  },
  'POST /api/apps/vstatd-team/runs/*': (_body, path) => {
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
  'GET /api/apps/vstatd-team/probe': () => ({
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
