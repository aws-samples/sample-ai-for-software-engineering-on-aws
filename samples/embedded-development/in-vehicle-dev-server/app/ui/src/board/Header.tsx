/**
 * The top of the board: the run's title and status, the run picker, the actions (开一个新运行, 停止
 * after a confirmation, 跟随, 投影), and the live counters: tests passed/total, the wall clock against
 * the serial estimate (what one agent doing everything would take) with the saving, roles done,
 * KiroCrew's sub-agent lanes, credits. Also the start form (here and in the empty state) and the
 * empty state itself: the start form first, what this Mac still needs (FlowStrip.tsx), the flow from the backlog to
 * sign-off, the knowledge documents (Knowledge.tsx) and the requirement list (Backlog.tsx), and the bench actions of no run.
 */
import { optionText, questionText } from '../i18n/events'
import { useEffect, useState, type CSSProperties, type FormEvent, type ReactNode } from 'react'
import { useAppApi } from '../api'
import type { Board, Delivery, GateDecision, GateQuestion, RunDetail, TalkLine, TeamPreview, TestWall } from '../types'
import { AIDLC_AGENTS, BASE, FINISHED, PHASES, expertsOf, LIVE, WORKING, aidlcUse, fmtAgo, fmtClock, fmtCredits, fmtSpan, isRunActive, laneMeta, runMeta, saving } from './format'
import { useChangeCount, useServerNow, useSinceSnapshot, useTween } from './hooks'
import { groupByAc } from './TestWall'
import { errorText } from './useBoard'
import { RoleIcon } from './RoleIcon'
import { MarkdownRenderer } from '@kirocrew/app-sdk/ui'
import { FlowSteps } from './DivisionGrid'
import { ReadinessPanel, ReadinessSummary, useReadiness } from './FlowStrip'
import { BenchAudit } from './Audit'
import { KnowledgeHome } from './Knowledge'
import { BacklogHome } from './Backlog'
import { t as tr } from '../i18n'

// ---------------------------------------------------------------------------------------------
// the top bar
// ---------------------------------------------------------------------------------------------

export interface TopBarProps {
  board: Board | null
  run: RunDetail | null
  projection: boolean
  follow: boolean
  startOpen: boolean
  onSelect: (id: string) => void
  /** 投影 (the page's own; inside the app the app bar has it) */
  onProjection?: () => void
  onFollow: () => void
  onStart: () => void
  onStop: () => void
  /** 重试 every failed role of the run. */
  onRetry?: () => void
  /** 文件夹: where the run's code is on this Mac. */
  onFolder?: () => void
  folderOpen?: boolean
  /** 产出: the drawer with each role's deliverables. */
  onOutputs?: (target: { role: string }) => void
  /** 清理会话: delete the Kiro Crew sessions earlier runs opened (none while a run is going). */
  onHide?: (run: string) => void
  onCleanup?: () => void
  /** 回放: play a finished run again from its record; while it plays the write actions are hidden. */
  onReplay?: () => void
  /** 交付详情 of the run shown (its value stream) */
  onDetail?: (rid: string) => void
  replaying?: boolean
  /** inside the app: the app bar carries its name and 投影 */
  inApp?: boolean
}

/** What the PR says on the board: 待合并 until a person signs the run off, then merged into main here (or signed only, imported). */
export const PR_STATE: Record<string, string> = { open: tr('board.Header.1'), merged: tr('board.Header.2'), signed: tr('board.Header.3') }

export function TopBar({ board, run, projection, follow, startOpen, onSelect, onProjection, onFollow, onStart, onStop, onOutputs, onRetry, onFolder, onCleanup, onHide, onReplay, onDetail, inApp = false, replaying = false, folderOpen = false }: TopBarProps) {
  const failed = run ? run.roles.filter((l) => l.status === 'failed') : []
  const meta = run ? runMeta(run.status) : null
  const runs = board?.runs ?? []
  return (
    <header className="kt-top">
      <div className="kt-title">
        {!inApp && <h1>{tr('board.Header.4')}</h1>}
        {run && meta && (
          <>
            <span className="kt-run-title" title={run.requirement || run.title}>{run.delivery?.name || run.title}</span>
            {run.issue && (
              <span className="kt-pill tone-info kt-mono" data-testid="kt-issue" title={tr('board.Header.5', { p0: run.issue.id, p1: run.issue.kind, p2: run.issue.reporter })}>
                {run.issue.id}
              </span>
            )}
            <span className={`kt-pill tone-${meta.tone}${meta.active ? ' is-live' : ''}`} data-testid="kt-run-status">
              <i aria-hidden="true">{meta.active ? '●' : run.status === 'done' ? '✔' : run.status === 'failed' ? '✕' : '■'}</i>
              {meta.label}
            </span>
            {run.imported && (
              <span className="kt-pill tone-info" title={tr('board.Header.6', { p0: run.imported.from })}>
                {tr('board.Header.7')} {run.imported.from}
              </span>
            )}
            {!projection && run.pr ? (
              <span className="kt-run-meta kt-mono" data-testid="kt-pr" title={tr('board.Header.8', { p0: run.pr.files, p1: run.pr.added, p2: run.pr.removed, p3: run.pr.checks, p4: run.pr.review ? ` · ${run.pr.review}` : '' })}>
                PR #{run.pr.number} · {run.pr.head} → {run.pr.base} · {PR_STATE[run.pr.state]}
              </span>
            ) : (
              !projection && !run.imported && (
                <span className="kt-run-meta kt-mono" title={run.repo}>
                  {run.branch} ← {run.base}
                </span>
              )
            )}
          </>
        )}
      </div>
      <div className="kt-actions">
        {!projection && runs.length > 1 && run && (
          <select className="kt-select" aria-label={tr('board.Header.9')} value={run.id} onChange={(e) => onSelect(e.target.value)}>
            {runs.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name || r.title}{r.issue ? tr('board.Header.10', { p0: r.issue }) : ''} · {r.imported ? tr('board.Header.11') : ''}{runMeta(r.status).label} {tr('board.Header.12')} {r.tests.passed}/{r.tests.total}
              </option>
            ))}
          </select>
        )}
        {!projection && !replaying && run && onHide && !isRunActive(run.status) && (
          <button type="button" className="kt-btn kt-btn-icon" onClick={() => onHide(run.id)} title={tr('board.Header.13')} aria-label={tr('board.Header.14')}>
            🗑
          </button>
        )}
        {!projection && !replaying && run && onDetail && (
          <button type="button" className="kt-btn" onClick={() => onDetail(run.id)} title={tr('board.Header.15')}>
            {tr('board.Header.16')}
          </button>
        )}
        {run && onReplay && !replaying && !isRunActive(run.status) && run.events.length > 0 && (
          <button type="button" className="kt-btn" onClick={onReplay} title={tr('board.Header.17')}>
            {tr('board.Header.18')}
          </button>
        )}
        {!projection && !replaying && board && (board.runs.length > 0 || run) && (
          <button type="button" className="kt-btn is-primary" aria-expanded={startOpen} onClick={onStart}>
            {tr('board.Header.19')}
          </button>
        )}
        {!projection && !replaying && run && isRunActive(run.status) && (
          <button type="button" className="kt-btn is-danger" onClick={onStop}>
            {tr('board.Header.20')}
          </button>
        )}
        {!projection && !replaying && onCleanup && board && board.runs.length > 0 && !board.runs.some((r) => isRunActive(r.status)) && (
          <button type="button" className="kt-btn" onClick={onCleanup} title={tr('board.Header.21')}>
            {tr('board.Header.22')}
          </button>
        )}
        {!projection && !replaying && !run?.imported && onRetry && failed.length > 0 && (
          <button type="button" className="kt-btn is-danger is-solid" onClick={onRetry} title={tr('board.Header.23', { p0: failed.map((l) => l.title).join(tr('common.sep')) })}>
            {tr('board.Header.24')} {failed.length} {tr('board.Header.25')}
          </button>
        )}
        {!projection && run && !run.imported && onFolder && (
          <button type="button" className="kt-btn" aria-expanded={folderOpen} onClick={onFolder} title={tr('board.Header.26')}>
            {tr('board.Header.27')}
          </button>
        )}
        {run && onOutputs && run.roles.length > 0 && (
          <button type="button" className="kt-btn" onClick={() => onOutputs({ role: run.roles[0].key })} title={tr('board.Header.28')}>
            {tr('board.Header.29')}
          </button>
        )}
        {run && (
          <button type="button" className="kt-btn" aria-pressed={follow} onClick={onFollow} title={tr('board.Header.30')}>
            {tr('board.Header.31')}
          </button>
        )}
        {run && onProjection && (
          <button type="button" className={`kt-btn${projection ? ' is-on' : ''}`} onClick={onProjection} title={projection ? tr('board.Header.32') : tr('board.Header.33')}>
            {projection ? tr('board.Header.34') : tr('board.Header.35')}
          </button>
        )}
      </div>
    </header>
  )
}

// ---------------------------------------------------------------------------------------------
// the counters
// ---------------------------------------------------------------------------------------------

const hue = (i: number) => (i * 47 + 200) % 360

export function Kpis({ run, reducedMotion, onRole }: { run: RunDetail; reducedMotion: boolean; onRole?: (key: string) => void }) {
  return (
    <div className="kt-kpis" role="group" aria-label={tr('board.Header.36')}>
      <TestsKpi tests={run.tests} reducedMotion={reducedMotion} />
      {phased(run) ? <GatesKpi run={run} /> : <ParallelKpi run={run} reducedMotion={reducedMotion} />}
      <RolesKpi run={run} onRole={onRole} />
      <UsedKpi run={run} />
      <CreditsKpi credits={run.credits} reducedMotion={reducedMotion} />
    </div>
  )
}

function TestsKpi({ tests, reducedMotion }: { tests: TestWall; reducedMotion: boolean }) {
  const shown = Math.round(useTween(tests.passed, 900, reducedMotion))
  const pop = useChangeCount(tests.passed)
  const now = useServerNow()
  const green = tests.total > 0 && tests.failed === 0
  const cells = groupByAc(tests.cases).flatMap((g) => g.cases)
  return (
    <div className={`kt-kpi kt-kpi-tests${green ? ' is-green' : ''}`}>
      <div className="kt-kpi-label">{tr('board.Header.37')}</div>
      <div className="kt-kpi-value" data-testid="kt-tests-counter" aria-label={tr('board.Header.38', { p0: tests.passed, p1: tests.total })}>
        <span className={`kt-kpi-big${pop ? ' is-pop' : ''}`} key={pop}>
          {shown}
        </span>
        <span className="kt-kpi-of">/{tests.total}</span>
      </div>
      <div className="kt-segs" aria-hidden="true">
        {cells.map((c) => (
          <i key={c.id} className={`is-${c.status}`} title={c.name} />
        ))}
      </div>
      <div className="kt-kpi-note">
        {tests.total ? (green ? <b className="tone-ok">{tr('board.Header.39')}</b> : <b className="tone-bad">{tests.failed} {tr('board.Header.40')}</b>) : tr('board.Header.41')}
        {tests.at ? tr('board.Header.42', { p0: fmtAgo(now - tests.at) }) : ''}
      </div>
    </div>
  )
}

/** A team laid out by AI-DLC phase (team-aidlc.json): the board leads with the gates, not the time saved. */
const phased = (run: RunDetail) => run.roles.length > 0 && run.roles.every((l) => !!l.phase)


/** What this run's gates caught: the same checks first and now, and every round a gate sent work back. */
function GatesKpi({ run }: { run: RunDetail }) {
  const first = run.tests.history[0]
  const kinds = run.roles.flatMap((l) => l.kinds)
  const testBacks = kinds.filter((k) => k === 'fix').length
  const reviewBacks = run.review_rounds
  // a person's decisions at gates: each approval, and each time a person sent work back
  const people = run.roles.filter((l) => l.gate === 'approved').length + run.events.filter((e) => e.kind === 'bounce' && e.from === 'person').length
  return (
    <div className="kt-kpi kt-kpi-gates">
      <div className="kt-kpi-label">{tr('board.Header.43')}</div>
      <div className="kt-kpi-value" data-testid="kt-gates">
        {first ? (
          <span className="kt-gates-score">
            <span className="kt-kpi-mid">{first.passed}/{first.passed + first.failed}</span>
            <span className="kt-gates-arrow">→</span>
            <span className="kt-kpi-big">{run.tests.passed}</span>
            <span className="kt-kpi-of">/{run.tests.total}</span>
          </span>
        ) : (
          <span className="kt-kpi-mid">{tr('board.Header.44')}</span>
        )}
      </div>
      <div className="kt-gates-rows">
        <span className={testBacks ? 'is-hit' : ''}>{tr('board.Header.45')} <b>{testBacks}</b> {tr('board.Header.46')}</span>
        <span className={reviewBacks ? 'is-hit' : ''}>{tr('board.Header.47')} <b>{reviewBacks}</b> {tr('board.Header.48')}</span>
        <span className={people ? 'is-hit' : ''}>{tr('board.Header.49')} <b>{people}</b> {tr('board.Header.46')}</span>
      </div>
    </div>
  )
}

/** The three layers this run stands on: Kiro Crew runs it, AI-DLC lends the experts, the checks judge the work. */
function UsedKpi({ run }: { run: RunDetail }) {
  const used = new Set(
    run.roles.filter((l) => l.status !== 'skipped').flatMap((l) => l.aidlc_agent.split(',').map((s) => s.trim()).filter(Boolean)),
  ) // the team's: the graph's roster shows which of them are already called
  const company = run.tests.cases.filter((c) => c.file.startsWith('tests/enterprise/')).length
  const written = run.tests.cases.length - company
  const checks = new Set(run.tests.cases.filter((c) => c.verdict).map((c) => c.ac ?? c.name)).size
  const agents = run.roles.filter((l) => l.attempt > 0 && l.status !== 'waiting' && l.status !== 'skipped').length
  return (
    <div className="kt-kpi kt-kpi-used">
      <div className="kt-kpi-label">{tr('board.Header.50')}</div>
      <div className="kt-used-row">
        <b>Kiro Crew</b> {tr('board.Header.51')}{agents} {tr('board.Header.52')}
      </div>
      <div className="kt-used-row">
        <b>AI-DLC</b> {tr('board.Header.53')} {AIDLC_AGENTS.filter((a) => used.has(a.key)).length}/14
        {used.size > AIDLC_AGENTS.filter((a) => used.has(a.key)).length ? tr('board.Header.54', { p0: used.size - AIDLC_AGENTS.filter((a) => used.has(a.key)).length }) : ''}
        <span className="kt-used-dots" aria-hidden="true">
          {AIDLC_AGENTS.map((a) => (
            <i key={a.key} className={used.has(a.key) ? 'is-on' : ''} title={`${a.name}${used.has(a.key) ? tr('board.Header.55') : tr('board.Header.56')}`} />
          ))}
        </span>
      </div>
      <div className="kt-used-row">
        <b>{tr('board.Header.57')}</b> {checks ? tr('board.Header.58', { p0: checks }) : tr('board.Header.59', { p0: company, p1: written })}
      </div>
    </div>
  )
}

function ParallelKpi({ run, reducedMotion }: { run: RunDetail; reducedMotion: boolean }) {
  const since = useSinceSnapshot()
  const wall = run.wall_s + (isRunActive(run.status) ? since : 0)
  const { saved_s, speedup } = saving({ wall_s: wall, serial_s: run.serial_s })
  const minutes = Math.round(useTween(saved_s / 60, 900, reducedMotion))
  const max = Math.max(wall, run.serial_s, 1)
  const segs = run.roles.filter((l) => l.active_s > 0)
  const segTotal = segs.reduce((a, l) => a + l.active_s, 0) || 1
  return (
    <div className="kt-kpi kt-kpi-par">
      <div className="kt-kpi-label">{tr('board.Header.60')}</div>
      <div className="kt-kpi-value" data-testid="kt-saving">
        {saved_s >= 60 ? (
          <span className="kt-saving">
            {tr('board.Header.61')} <span className="kt-kpi-big">{minutes}</span> {tr('board.Header.62')}
          </span>
        ) : (
          <span className="kt-kpi-mid">{tr('board.Header.63')}</span>
        )}
        {speedup !== null && speedup > 1.05 && <span className="kt-speedup" title={tr('board.Header.64')}>×{speedup.toFixed(1)}</span>}
      </div>
      <div className="kt-bars">
        <div className="kt-bar-row">
          <span className="kt-bar-name">{tr('board.Header.65')}</span>
          <span className="kt-bar" title={tr('board.Header.66', { p0: fmtClock(wall) })}>
            <i className="kt-bar-wall" style={{ width: `${(wall / max) * 100}%` }} />
          </span>
          <span className="kt-bar-val kt-mono">{fmtClock(wall)}</span>
        </div>
        <div className="kt-bar-row">
          <span className="kt-bar-name">{tr('board.Header.67')}</span>
          <span className="kt-bar is-segs" title={tr('board.Header.68', { p0: fmtClock(run.serial_s), p1: fmtSpan(run.serial_s) })}>
            {segs.map((l, i) => (
              <i key={l.key} className="kt-bar-seg" style={{ width: `${(l.active_s / segTotal) * (run.serial_s / max) * 100}%`, '--h': hue(i) } as CSSProperties} title={`${l.title} ${fmtClock(l.active_s)}`} />
            ))}
          </span>
          <span className="kt-bar-val kt-mono">{fmtClock(run.serial_s)}</span>
        </div>
      </div>
    </div>
  )
}

function RolesKpi({ run, onRole }: { run: RunDetail; onRole?: (key: string) => void }) {
  const done = run.roles.filter((l) => FINISHED.has(l.status)).length
  const working = run.roles.filter((l) => WORKING.has(l.status)).length
  const stuck = run.roles.filter((l) => LIVE.has(l.status) && !WORKING.has(l.status)).length
  const unmerged = run.roles.filter((l) => l.status === 'done' && l.writable.length > 0).length
  return (
    <div className="kt-kpi kt-kpi-roles">
      <div className="kt-kpi-label">{tr('board.Header.69')}</div>
      <div className="kt-kpi-value" data-testid="kt-roles-counter">
        <span className="kt-kpi-big">{done}</span>
        <span className="kt-kpi-of">/{run.roles.length}</span>
      </div>
      <div className="kt-role-dots">
        {run.roles.map((l) => (
          <button
            key={l.key}
            type="button"
            className={`kt-role-dot tone-${laneMeta(l).tone}${WORKING.has(l.status) ? ' is-working' : ''}`}
            title={tr('board.Header.70', { p0: l.title, p1: laneMeta(l).label })}
            aria-label={tr('board.Header.71', { p0: l.title, p1: laneMeta(l).label })}
            onClick={() => onRole?.(l.key)}
          >
            <RoleIcon role={l.icon || l.key} size={16} />
          </button>
        ))}
      </div>
      <div className="kt-kpi-note">
        {working ? <b className="tone-run">{tr('board.Header.72')} {working}</b> : tr('board.Header.73')}
        {stuck ? <b className="tone-warn"> · {stuck} {tr('board.Header.74')}</b> : null}
        {unmerged ? tr('board.Header.75', { p0: unmerged }) : ''}
      </div>
    </div>
  )
}


function CreditsKpi({ credits, reducedMotion }: { credits: number | null; reducedMotion: boolean }) {
  const shown = useTween(credits ?? 0, 900, reducedMotion)
  return (
    <div className="kt-kpi kt-kpi-credits">
      <div className="kt-kpi-label">credits</div>
      <div className="kt-kpi-value">
        <span className="kt-kpi-big">{credits === null ? '—' : fmtCredits(shown)}</span>
      </div>
      <div className="kt-kpi-note">{credits === null ? tr('board.Header.76') : tr('board.Header.77')}</div>
    </div>
  )
}

// ---------------------------------------------------------------------------------------------
// start and stop
// ---------------------------------------------------------------------------------------------

export interface StartOptions {
  source?: string
}
export type StartFn = (requirement: string, opts?: StartOptions) => Promise<void>

/** The scenario's work item (README.md, "The scenario"): it fills the requirement box. */
export const WORK_ITEM = '修复 vstatd 静态分析待办里标为 fix 的发现，并把信号表的处理从 750 行的 Service::run() 里拆出去。行为不变：在录制的行驶数据上，信号、值、超时和错误都和原来一样；目标上的内存不超过限额。'  // i18n-keep: the request the agents work on, in their working language (team.json work_item)

const CHECK_WHEN: ReadonlyArray<[string, string]> = [['before_bench', tr('board.Header.79')], ['after_bench', tr('board.Header.80')], ['release', tr('board.Header.81')]]

/** 组队预览 (GET /team): the one team's roles by AI-DLC phase, the templates they run, its checks and the knowledge source. */
export function TeamPreviewPanel() {
  const api = useAppApi()
  const [t, setT] = useState<TeamPreview | null>(null)
  const [err, setErr] = useState('')
  useEffect(() => {
    let live = true
    api.get<TeamPreview>(`${BASE}/team`).then(
      (d) => live && setT(d),
      (x) => live && setErr(errorText(x)),
    )
    return () => {
      live = false
    }
  }, [api])
  if (err) return <p className="kt-pick is-empty" data-testid="kt-pick">{tr('board.Header.82')}{err}</p>
  if (!t) return <p className="kt-pick is-empty" data-testid="kt-pick">{tr('board.Header.83')}</p>
  if (t.error) return <p className="kt-pick is-empty kt-warn" data-testid="kt-pick">{t.error}</p>
  const missing = new Set(t.templates.filter((x) => !x.present).map((x) => x.name))
  const phases = PHASES.map((ph) => ({ ...ph, roles: t.roles.filter((r) => r.phase === ph.key) })).filter((ph) => ph.roles.length)
  const byKey = new Map(t.roles.map((r) => [r.key, r.title]))
  const kb = t.knowledge
  return (
    <section className="kt-pick" aria-label={tr('board.Header.84')} data-testid="kt-pick">
      <p className="kt-pick-team"><b>{t.name}</b> · {t.roles.length} {tr('board.Header.85')}</p>
      <ol className="kt-pick-phases" aria-label={tr('board.Header.86')}>
        {phases.map((ph) => (
          <li key={ph.key}>
            <span className="kt-pick-phase">{ph.n} {ph.title}</span>
            {ph.roles.map((r) => (
              <span key={r.key} className={`kt-pick-role${missing.has(r.template) ? ' is-absent' : ''}`} data-testid="kt-pick-role" data-key={r.key}
                title={tr('board.Header.87', { p0: r.aidlc_agent || '—', p1: r.writable })}>
                <RoleIcon role={r.icon || r.key} size={16} />
                <span>
                  {r.title}
                  {r.gate ? <em> {tr('board.Header.88')}{r.gate}{tr('board.Header.89')}</em> : null}
                  <small className="kt-mono">{r.template}{missing.has(r.template) && <span className="kt-pick-miss"> {tr('board.Header.90')}</span>}</small>
                </span>
              </span>
            ))}
          </li>
        ))}
      </ol>
      {missing.size > 0 && (
        <p className="kt-warn" data-testid="kt-pick-missing">
          {tr('board.Header.91')} {[...missing].join(tr('board.Header.92'))} {tr('board.Header.93')} <code className="kt-mono">bash setup.sh</code>
        </p>
      )}
      <div className="kt-pick-checks" aria-label={tr('board.Header.57')}>
        {CHECK_WHEN.map(([when, label]) => {
          const cs = t.checks.filter((c) => c.when === when)
          if (!cs.length) return null
          return (
            <p key={when} data-testid="kt-pick-checks" data-when={when}>
              <span className="kt-pick-phase">{label}</span>
              {cs.map((c) => (
                <span key={c.name} className="kt-pick-agent is-used kt-mono" title={c.owner ? tr('board.Header.94', { p0: byKey.get(c.owner) ?? c.owner, p1: c.max_rounds }) : tr('board.Header.95')}>
                  {c.name}
                </span>
              ))}
            </p>
          )
        })}
      </div>
      {kb && (
        <p className={kb.present === false ? 'kt-warn' : 'kt-dim'} data-testid="kt-pick-kb">
          {tr('board.Header.96')}{kb.name}{tr('board.Header.97')}{kb.present === false ? tr('board.Header.98', { p0: kb.path || '~/workplace/vstatd/knowledge' }) : kb.present === null ? tr('board.Header.99') : tr('board.Header.100', { p0: kb.items ?? 0, p1: kb.status === 'synced' ? tr('board.Header.kbSynced') : tr('board.Header.kbIndexing') })}
        </p>
      )}
    </section>
  )
}

export function StartForm({ onStart, onCancel, note }: { onStart: StartFn; onCancel?: () => void; note?: ReactNode }) {
  const [text, setText] = useState(WORK_ITEM)
  const [source, setSource] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (busy) return
    setBusy(true)
    setErr('')
    try {
      const src = source.trim()
      await onStart(text.trim(), src ? { source: src } : {})
    } catch (x) {
      setErr(errorText(x))
    } finally {
      setBusy(false)
    }
  }
  return (
    <form className="kt-start" onSubmit={submit} aria-label={tr('board.Header.101')}>
      <label htmlFor="kt-req">{tr('board.Header.102')}</label>
      <p className="kt-dim kt-req-hint">{tr('board.Header.103')}</p>
      <textarea id="kt-req" value={text} rows={3} onChange={(e) => setText(e.target.value)} placeholder={WORK_ITEM} />
      <details className="kt-start-more">
        <summary>{tr('board.Header.104')}</summary>
        <TeamPreviewPanel />
      </details>
      <details className="kt-start-more" open={!!source}>
      <summary>{tr('board.Header.105')}</summary>
      <div className="kt-start-row">
        <label className="kt-start-field">
          <span>{tr('board.Header.106')}</span>
          <input type="text" value={source} onChange={(e) => setSource(e.target.value)} placeholder={tr('board.Header.107')} />
        </label>
      </div>
      </details>
      <div className="kt-start-actions">
        <button type="submit" className="kt-btn is-primary" disabled={busy}>
          {busy ? tr('board.Header.108') : tr('board.Header.109')}
        </button>
        {onCancel && (
          <button type="button" className="kt-btn" onClick={onCancel}>
            {tr('board.Header.110')}
          </button>
        )}
        <span className="kt-dim">{tr('board.Header.111')}</span>
        {note}
      </div>
      {err && (
        <p className="kt-error" role="alert">
          {err}
        </p>
      )}
    </form>
  )
}

export function StopConfirm({ run, onConfirm, onCancel }: { run: RunDetail; onConfirm: () => Promise<void>; onCancel: () => void }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const live = run.roles.filter((l) => LIVE.has(l.status) || l.status === 'queued').length
  const confirm = async () => {
    setBusy(true)
    setErr('')
    try {
      await onConfirm()
    } catch (x) {
      setErr(errorText(x))
      setBusy(false)
    }
  }
  return (
    <div className="kt-confirm" role="alertdialog" aria-labelledby="kt-stop-title" aria-describedby="kt-stop-desc">
      <strong id="kt-stop-title">{tr('board.Header.112')}{run.title}{tr('board.Header.113')}</strong>
      <span id="kt-stop-desc">{live ? tr('board.Header.114', { p0: live }) : tr('board.Header.115')}</span>
      <span className="kt-confirm-actions">
        <button type="button" className="kt-btn is-danger is-solid" onClick={confirm} disabled={busy}>
          {busy ? tr('board.Header.116') : tr('board.Header.117')}
        </button>
        <button type="button" className="kt-btn" onClick={onCancel} autoFocus>
          {tr('board.Header.110')}
        </button>
      </span>
      {err && (
        <p className="kt-error" role="alert">
          {err}
        </p>
      )}
    </div>
  )
}

/** 交付标签 as the person confirms them at the gate of a role that proposes them (the vstatd team has none). */
export type DeliveryPick = Pick<Delivery, 'name' | 'kind' | 'size' | 'line'>
const DELIVERY_KINDS: Delivery['kind'][] = ['新应用', '新功能', '修复']  // i18n-keep: values the backend stores
const DELIVERY_SIZES: Delivery['size'][] = ['小', '中', '大']  // i18n-keep: values the backend stores
const DELIVERY_LINES: Delivery['line'][] = ['电商', '移动应用', '客户关系管理', '供应链', '内部系统']  // i18n-keep: values the backend stores
/** A stored delivery value shown in the board's language (the value sent back stays the stored one). */
const deliveryLabel = (group: 'kind' | 'size' | 'line', values: readonly string[], v: string) => tr(`board.Header.delivery.${group}.${values.indexOf(v)}`)

/** A person at a gate, inside the page (the desktop app has no window.prompt): approve with an optional note for
 * everyone after it, or send it back with what to change. *skips*: the optional members the proposal leaves out (they
 * sit the run out once approved). *overrule*: a review that still says 要改 with its rounds used up: approving it is
 * overruling the review (a reason is required), sending it back is one more round as the review says. */
/** The person's choice for each question of a gate, by question id (sent with 批准). */
export type GateAnswers = Record<string, { choice: string; text: string }>
/** 拦下的风险 sent with 退回 at a gate whose team file asks for it (gate_revise_risk): what it keeps from going live, the amount in yuan (or none). */
export type GateRisk = { what: string; amount: number | null }

/** A gate: 批准 (with an answer for each question the role put to the person), 讨论 (it answers; the gate stays open),
 * or 退回. What was said in a 讨论 so far is shown in all three; at a writing role's gate, the stage's documents too. */
export function GateDialog({ label, who = '', decision, preset, presetRisk, askRisk = false, split, skips, report, onReport, overrule = false, delivery, questions = [], talk = [], outputs = [], replay = false, onConfirm, onCancel }: {
  label: string; who?: string; decision: GateDecision; preset?: string; presetRisk?: GateRisk | null; askRisk?: boolean; split?: { key: string; title: string; icon: string; assignment: string }[]
  /** A replay: the gate's questions as they were asked, nothing answered or sent. */
  replay?: boolean
  skips?: { key: string; title: string; why: string }[]; report?: string; onReport?: () => void; overrule?: boolean; delivery?: Delivery
  questions?: GateQuestion[]; talk?: TalkLine[]; outputs?: { key: string; title: string; icon: string; onOpen: () => void }[]
  onConfirm: (note: string, delivery?: DeliveryPick, answers?: GateAnswers, risk?: GateRisk) => Promise<void>; onCancel: () => void
}) {
  const [note, setNote] = useState('')
  const [risk, setRisk] = useState({ what: '', wan: '' }) // 退回: what it keeps from going live, the amount in 万元
  const [pick, setPick] = useState<DeliveryPick | null>(delivery ? { name: delivery.name, kind: delivery.kind, size: delivery.size, line: delivery.line } : null)
  const [answers, setAnswers] = useState<GateAnswers>(() => Object.fromEntries(questions.map((q) => [q.id, { choice: q.recommend || q.options[0]?.key || '', text: '' }])))
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const approve = decision === 'approve'
  const discuss = decision === 'discuss'
  const asking = approve && questions.length > 0
  const back = !approve && !discuss
  const riskOut = (): GateRisk | undefined => {
    const what = risk.what.trim(), wan = Number(risk.wan)
    return back && askRisk && (what || wan > 0) ? { what, amount: wan > 0 ? Math.round(wan * 1e4) : null } : undefined
  }
  const answer = (id: string, a: Partial<{ choice: string; text: string }>) => setAnswers((x) => ({ ...x, [id]: { ...x[id], ...a } }))
  const confirm = async () => {
    if (overrule && approve && !note.trim()) {
      setErr(tr('board.Header.129'))
      return
    }
    if (discuss && !note.trim()) {
      setErr(tr('board.Header.130'))
      return
    }
    if (!approve && !discuss && !overrule && !note.trim()) {
      setErr(tr('board.Header.131'))
      return
    }
    const blank = asking ? questions.find((q) => answers[q.id]?.choice === 'other' && !answers[q.id].text.trim()) : undefined
    if (blank) {
      setErr(tr('board.Header.132', { p0: blank.id }))
      return
    }
    setBusy(true)
    setErr('')
    try {
      const r = riskOut()
      await (asking ? onConfirm(note.trim(), pick ?? undefined, answers) : approve && pick ? onConfirm(note.trim(), pick) : r ? onConfirm(note.trim(), undefined, undefined, r) : onConfirm(note.trim()))
    } catch (x) {
      setErr(errorText(x))
      setBusy(false)
    }
  }
  const title = replay ? tr('board.Header.replayTitle', { p0: label }) : discuss ? tr('board.Header.133', { p0: label }) : overrule ? (approve ? tr('board.Header.134', { p0: label }) : tr('board.Header.135', { p0: label })) : approve ? tr('board.Header.136', { p0: label }) : tr('board.Header.137', { p0: label })
  const lead = replay
    ? tr('board.Header.replayLead')
    : discuss
    ? tr('board.Header.138', { p0: who || tr('common.it') })
    : overrule ? (approve ? tr('board.Header.139') : tr('board.Header.140'))
      : report !== undefined ? (approve ? tr('board.Header.141') : tr('board.Header.reviseHint'))
        : approve ? (asking ? tr('board.Header.143') : tr('board.Header.144'))
          : tr('board.Header.145')
  return (
    <div className={`kt-confirm kt-gate-dialog${approve ? ' is-approve' : ''}${discuss ? ' is-discuss' : ''}`} role="dialog" aria-labelledby="kt-gate-title" data-testid="kt-gate-dialog">
      <strong id="kt-gate-title">{title}</strong>
      <span>{lead}</span>
      {outputs.length > 0 && (
        <p className="kt-gate-docs" data-testid="kt-gate-docs">
          <span className="kt-dim">{tr('board.Header.146')}</span>
          {outputs.map((o) => (
            <button key={o.key} type="button" className="kt-chip-link" onClick={o.onOpen}>
              <RoleIcon role={o.icon || o.key} size={13} /> {o.title} ↗
            </button>
          ))}
        </p>
      )}
      {asking && (
        <div className="kt-gate-questions" data-testid="kt-gate-questions">
          {questions.map((q) => {
            const a = answers[q.id] ?? { choice: '', text: '' }
            const differs = !!q.recommend && a.choice !== q.recommend
            return (
              <fieldset key={q.id} className="kt-gate-q" aria-label={tr('board.Header.147', { p0: q.id })}>
                <legend>
                  <b>{tr('board.Header.148')} {q.id}</b> {questionText(q)}
                </legend>
                {q.cites && q.cites.length > 0 && (
                  <span className="kt-gate-cites" data-testid="kt-gate-cites">
                    {tr('board.Header.149')}{q.cites.map((c) => <code key={c}>{c}</code>)}
                  </span>
                )}
                {q.options.map((o) => (
                  <label key={o.key} className={a.choice === o.key ? 'is-picked' : undefined}>
                    <input type="radio" name={`q-${q.id}`} checked={a.choice === o.key} disabled={replay} onChange={() => answer(q.id, { choice: o.key })} />
                    <span>
                      {o.key}. {optionText(o)}
                      {o.key === q.recommend && <em className="kt-gate-rec">{tr('board.Header.150')}</em>}
                    </span>
                  </label>
                ))}
                {!replay && (
                  <label className={a.choice === 'other' ? 'is-picked' : undefined}>
                    <input type="radio" name={`q-${q.id}`} checked={a.choice === 'other'} onChange={() => answer(q.id, { choice: 'other' })} />
                    <span>{tr('board.Header.151')}</span>
                    {a.choice === 'other' && <input className="kt-gate-other" aria-label={tr('board.Header.152', { p0: q.id })} value={a.text} maxLength={300} onChange={(e) => answer(q.id, { text: e.target.value })} placeholder={tr('board.Header.153')} />}
                  </label>
                )}
                {(q.why || (differs && !replay)) && (
                  <span className="kt-dim">
                    {q.why && tr('board.Header.154', { p0: q.why })}
                    {differs && <b className="kt-gate-differs">{q.why ? tr('board.Header.155') : ''}{tr('board.Header.156')}{q.recommend}{tr('board.Header.157')}</b>}
                  </span>
                )}
              </fieldset>
            )
          })}
        </div>
      )}
      {talk.length > 0 && (
        <ol className="kt-gate-talk" aria-label={tr('board.Header.158')} data-testid="kt-gate-talk">
          {talk.map((t, i) => (
            <li key={i} className={t.who === 'person' ? 'is-person' : 'is-agent'}>
              <b>{t.who === 'person' ? tr('board.Header.159') : who || tr('board.Header.160')}</b>
              <div className="kt-gate-talk-text">{t.who === 'agent' ? <MarkdownRenderer content={t.text} /> : t.text}{t.changed ? <em className="kt-dim">{tr('board.Header.161')}</em> : null}</div>
            </li>
          ))}
        </ol>
      )}
      {report !== undefined && !discuss && (
        <div className="kt-gate-report">
          <b>{overrule ? tr('board.Header.162') : tr('board.Header.163')}</b>
          {report || tr('board.Header.164')}
          {onReport && (
            <button type="button" className="kt-btn" onClick={onReport}>
              {tr('board.Header.165')}
            </button>
          )}
        </div>
      )}
      {split && split.length > 0 && !discuss && (
        <ul className="kt-gate-split" aria-label={tr('board.Header.166')}>
          {split.map((m) => (
            <li key={m.key}>
              <RoleIcon role={m.icon || m.key} size={14} /> <b>{m.title}</b> {m.assignment}
            </li>
          ))}
        </ul>
      )}
      {skips && skips.length > 0 && !discuss && (
        <ul className="kt-gate-split is-out" aria-label={tr('board.Header.167')} data-testid="kt-gate-skips">
          {skips.map((m) => (
            <li key={m.key}>
              <RoleIcon role={m.key} size={14} /> <b>{m.title}</b> {tr('board.Header.168')}{m.why}
            </li>
          ))}
          <li className="kt-dim">{tr('board.Header.169')}</li>
        </ul>
      )}
      {approve && pick && delivery && (
        <fieldset className="kt-gate-delivery" data-testid="kt-gate-delivery">
          <legend title={tr('board.Header.170')}>{tr('board.Header.171')}{delivery.why ? tr('board.Header.172', { p0: delivery.why }) : ''}</legend>
          <input aria-label={tr('board.Header.173')} value={pick.name} maxLength={20} onChange={(e) => setPick({ ...pick, name: e.target.value })} />
          <select aria-label={tr('board.Header.174')} value={pick.kind} onChange={(e) => setPick({ ...pick, kind: e.target.value as Delivery['kind'] })}>
            {DELIVERY_KINDS.map((k) => <option key={k} value={k}>{deliveryLabel('kind', DELIVERY_KINDS, k)}</option>)}
          </select>
          <select aria-label={tr('board.Header.175')} value={pick.size} onChange={(e) => setPick({ ...pick, size: e.target.value as Delivery['size'] })}>
            {DELIVERY_SIZES.map((k) => <option key={k} value={k}>{deliveryLabel('size', DELIVERY_SIZES, k)}</option>)}
          </select>
          <select aria-label={tr('board.Header.176')} value={pick.line} onChange={(e) => setPick({ ...pick, line: e.target.value as Delivery['line'] })}>
            {DELIVERY_LINES.map((k) => <option key={k} value={k}>{deliveryLabel('line', DELIVERY_LINES, k)}</option>)}
          </select>
        </fieldset>
      )}
      {back && askRisk && (
        <fieldset className="kt-gate-delivery kt-gate-risk" data-testid="kt-gate-risk">
          <legend title={tr('board.Header.177')}>{tr('board.Header.178')}</legend>
          <input aria-label={tr('board.Header.179')} className="kt-gate-what" value={risk.what} maxLength={60} onChange={(e) => setRisk({ ...risk, what: e.target.value })} placeholder={tr('board.Header.180')} />
          <label>
            {tr('board.Header.181')} <input aria-label={tr('board.Header.182')} className="kt-gate-amount" type="number" min={0} step={0.1} value={risk.wan} onChange={(e) => setRisk({ ...risk, wan: e.target.value })} placeholder={tr('board.Header.183')} /> {tr('board.Header.184')}
          </label>
        </fieldset>
      )}
      {replay ? (
        <span className="kt-confirm-actions">
          <button type="button" className="kt-btn" onClick={onCancel} autoFocus>
            {tr('board.Header.close')}
          </button>
        </span>
      ) : (<>
      <textarea className="kt-gate-note" rows={3} value={note} onChange={(e) => setNote(e.target.value)} placeholder={discuss ? tr('board.Header.185') : overrule && approve ? tr('board.Header.186') : approve ? tr('board.Header.187') : tr('board.Header.188')} autoFocus aria-label={discuss ? tr('board.Header.189') : tr('board.Header.190')} />
      <span className="kt-confirm-actions">
        {preset && note !== preset && !discuss && (
          <button type="button" className="kt-btn" onClick={() => { setNote(preset); if (back && presetRisk) setRisk({ what: presetRisk.what, wan: presetRisk.amount != null ? String(presetRisk.amount / 1e4) : '' }) }} title={preset}>
            {tr('board.Header.191')}
          </button>
        )}
        <button type="button" className={`kt-btn is-solid${approve || discuss ? ' is-primary' : ' is-danger'}`} onClick={confirm} disabled={busy}>
          {busy ? tr('board.Header.192') : discuss ? tr('board.Header.193') : overrule && approve ? tr('board.Header.194') : approve ? tr('board.Header.195') : tr('board.Header.196')}
        </button>
        <button type="button" className="kt-btn" onClick={onCancel}>
          {tr('board.Header.110')}
        </button>
      </span>
      </>)}
      {err && (
        <p className="kt-error" role="alert">
          {err}
        </p>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------------------------
// the empty state
// ---------------------------------------------------------------------------------------------

export function EmptyStart({ onStart }: { onStart: StartFn }) {
  const ready = useReadiness()
  return (
    <section className="kt-empty" data-testid="kt-empty" aria-label={tr('board.Header.197')}>
      <div className="kt-empty-hero">
        <h2>{tr('board.Header.198')}</h2>
        <p>
          {tr('board.Header.199')}
        </p>
      </div>
      <StartForm onStart={onStart} note={<ReadinessSummary r={ready.r} />} />
      <ReadinessPanel state={ready} />
      <FlowSteps />
      <KnowledgeHome />
      <BacklogHome />
      <BenchAudit />
    </section>
  )
}

// ---------------------------------------------------------------------------------------------
// AI-DLC's 14 official experts
// ---------------------------------------------------------------------------------------------

const EXPERT_STATE = {
  busy: { label: tr('board.Header.200'), hint: tr('board.Header.201') },
  used: { label: tr('board.Header.202'), hint: tr('board.Header.203') },
  team: { label: tr('board.Header.204'), hint: tr('board.Header.205') },
  none: { label: tr('board.Header.206'), hint: tr('board.Header.207') },
} as const

/** All 14 experts AWS AI-DLC defines, in four states: at work, called, on the team but not its turn yet, or not on
 * this team at all (greyed, shown anyway: the orchestrator picked a team without it). */
export function ExpertStrip({ run }: { run: RunDetail }) {
  const { team, used, busy } = aidlcUse(run.roles)
  const experts = expertsOf(run.roles)
  const custom = experts.filter((a) => a.custom).length
  const of = (key: string) => run.roles.filter((l) => l.status !== 'skipped' && l.aidlc_agent.split(',').map((x) => x.trim()).includes(key))
  return (
    <section className="kt-experts" aria-label={tr('board.Header.208')} data-testid="kt-experts">
      <span className="kt-experts-title">
        {tr('board.Header.208')}{custom ? tr('board.Header.209', { p0: custom }) : ''} {tr('board.Header.210')} {team.size} {tr('board.Header.211')}
      </span>
      <ul className="kt-experts-list">
        {experts.map((a) => {
          const lanes = of(a.key)
          const state = busy.has(a.key) ? 'busy' : used.has(a.key) ? 'used' : team.has(a.key) ? 'team' : 'none'
          const n = lanes.length
          const who = lanes.map((l) => l.title).join(tr('board.Header.92'))
          return (
            <li key={a.key} className={`kt-expert is-${state}${a.custom ? ' is-custom' : ''}`} data-state={state} title={tr('board.Header.212', { p0: a.name, p1: a.key, p2: EXPERT_STATE[state].hint, p3: who ? tr('board.Header.thisTime', { p0: who }) : '' })}>
              <b>
                {a.name}
                {n > 1 ? ` ×${n}` : ''}
              </b>
              <small>{a.custom && state === 'none' ? tr('board.Header.213') : EXPERT_STATE[state].label}</small>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
