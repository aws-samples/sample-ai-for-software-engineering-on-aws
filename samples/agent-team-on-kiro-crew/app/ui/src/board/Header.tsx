/**
 * The top of the board: the run's title and status, the run picker, the actions (开一个新运行, 停止
 * after a confirmation, 跟随, 投影), and the live counters: tests passed/total, the wall clock against
 * the serial estimate (what one agent doing everything would take) with the saving, roles done,
 * KiroCrew's sub-agent lanes, credits. Also the start form (here and in the empty state) and the
 * empty state itself: an introduction to the 8-role team.
 */
import { useEffect, useState, type CSSProperties, type FormEvent } from 'react'
import type { Board, Delivery, GateDecision, GateQuestion, RoutePick, RunDetail, TalkLine, TestWall } from '../types'
import { AIDLC_AGENTS, FINISHED, expertsOf, officialOf, LIVE, PHASES, WORKING, aidlcUse, fmtAgo, fmtClock, fmtCredits, fmtSpan, isRunActive, laneMeta, runMeta, saving } from './format'
import { useChangeCount, useServerNow, useSinceSnapshot, useTween } from './hooks'
import { groupByAc } from './TestWall'
import { errorText } from './useBoard'
import { RoleIcon } from './RoleIcon'
import { MarkdownRenderer } from '@kirocrew/app-sdk/ui'

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
  /** 产出 / 打开网站: the drawer with each role's deliverables, or the finished product. */
  onOutputs?: (target: { role: string; tab?: 'site' | null }) => void
  /** 清理会话: delete the Kiro Crew sessions earlier runs opened (none while a run is going). */
  onHide?: (run: string) => void
  onCleanup?: () => void
  /** 回放: play a finished run again from its record; while it plays the write actions are hidden. */
  onReplay?: () => void
  replaying?: boolean
  /** inside the app: the app bar carries its name and 投影 */
  inApp?: boolean
  /** this run's 交付详情 (its name and Issue open it) */
  onItem?: (e: { run: string }) => void
}

/** What the PR says on the board: 待合并 until a person signs the run off, then merged into main here (or signed only, imported). */
export const PR_STATE: Record<string, string> = { open: '待合并', merged: '已合并', signed: '已签字放行' }

export function TopBar({ board, run, projection, follow, startOpen, onSelect, onProjection, onFollow, onStart, onStop, onOutputs, onRetry, onFolder, onCleanup, onHide, onReplay, inApp = false, onItem, replaying = false, folderOpen = false }: TopBarProps) {
  const failed = run ? run.roles.filter((l) => l.status === 'failed') : []
  const meta = run ? runMeta(run.status) : null
  const runs = board?.runs ?? []
  return (
    <header className="kt-top">
      <div className="kt-title">
        {!inApp && <h1>AI-DLC 多 Agent 团队</h1>}
        {run && meta && (
          <>
            {onItem ? (
              <button type="button" className="kt-run-title kt-run-link" onClick={() => onItem({ run: run.id })} title={`交付详情：周期、时间花在哪、成本、质量、价值流（${run.requirement || run.title}）`}>
                {run.delivery?.name || run.title}
              </button>
            ) : (
              <span className="kt-run-title" title={run.requirement || run.title}>{run.delivery?.name || run.title}</span>
            )}
            {run.issue && (onItem ? (
              <button type="button" className="kt-pill tone-info kt-mono kt-pill-btn" data-testid="kt-issue" onClick={() => onItem({ run: run.id })} title={`Issue ${run.issue.id} · ${run.issue.kind} · ${run.issue.reporter}提出 · 交付详情`}>
                {run.issue.id}
              </button>
            ) : (
              <span className="kt-pill tone-info kt-mono" data-testid="kt-issue" title={`Issue ${run.issue.id} · ${run.issue.kind} · ${run.issue.reporter}提出`}>
                {run.issue.id}
              </span>
            ))}
            <span className={`kt-pill tone-${meta.tone}${meta.active ? ' is-live' : ''}`} data-testid="kt-run-status">
              <i aria-hidden="true">{meta.active ? '●' : run.status === 'done' ? '✔' : run.status === 'failed' ? '✕' : '■'}</i>
              {meta.label}
            </span>
            {run.imported && (
              <span className="kt-pill tone-info" title={`这次运行是在「${run.imported.from}」上跑的，导入到这里来看和回放；代码和会话留在那台 Mac 上`}>
                导入 · {run.imported.from}
              </span>
            )}
            {!projection && run.pr ? (
              <span className="kt-run-meta kt-mono" data-testid="kt-pr" title={`${run.pr.files} 个文件 · +${run.pr.added} −${run.pr.removed} · 检查 ${run.pr.checks}${run.pr.review ? ` · ${run.pr.review}` : ''}`}>
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
          <select className="kt-select" aria-label="选择运行" value={run.id} onChange={(e) => onSelect(e.target.value)}>
            {runs.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name || r.title}{r.issue ? `（${r.issue}）` : ''} · {r.imported ? '导入 · ' : ''}{runMeta(r.status).label} · 测试 {r.tests.passed}/{r.tests.total}
              </option>
            ))}
          </select>
        )}
        {!projection && !replaying && run && onHide && !isRunActive(run.status) && (
          <button type="button" className="kt-btn kt-btn-icon" onClick={() => onHide(run.id)} title="把这次运行从列表里删掉（记录和代码留在这台 Mac 上）" aria-label="从列表里删除这次运行">
            🗑
          </button>
        )}
        {run && onReplay && !replaying && !isRunActive(run.status) && run.events.length > 0 && (
          <button type="button" className="kt-btn" onClick={onReplay} title="按这次运行的记录从头重放：谁在什么时候干了什么、哪里被打回、测试怎么由红变绿。不调用 agent，不花 credits">
            ▶ 回放
          </button>
        )}
        {!projection && !replaying && board && (board.runs.length > 0 || run) && (
          <button type="button" className="kt-btn is-primary" aria-expanded={startOpen} onClick={onStart}>
            新需求
          </button>
        )}
        {!projection && !replaying && run && isRunActive(run.status) && (
          <button type="button" className="kt-btn is-danger" onClick={onStop}>
            停止
          </button>
        )}
        {!projection && !replaying && onCleanup && board && board.runs.length > 0 && !board.runs.some((r) => isRunActive(r.status)) && (
          <button type="button" className="kt-btn" onClick={onCleanup} title="删掉已结束的运行在 Kiro Crew 侧栏里开的会话（签过字的运行保留，回放时还能打开）；运行记录和代码都保留">
            清理已结束的会话
          </button>
        )}
        {!projection && !replaying && !run?.imported && onRetry && failed.length > 0 && (
          <button type="button" className="kt-btn is-danger is-solid" onClick={onRetry} title={`再给失败的角色一轮：${failed.map((l) => l.title).join('、')}`}>
            ↻ 重试失败的 {failed.length} 个角色
          </button>
        )}
        {!projection && run && !run.imported && onFolder && (
          <button type="button" className="kt-btn" aria-expanded={folderOpen} onClick={onFolder} title="项目在这台 Mac 上的哪个文件夹：在 Finder 或 Kiro 里打开">
            📁 文件夹
          </button>
        )}
        {run && onOutputs && run.roles.length > 0 && (
          <button type="button" className="kt-btn" onClick={() => onOutputs({ role: run.roles[0].key })} title="一步一步看每个角色交了什么：文档、代码、回复、做了什么">
            产出
          </button>
        )}
        {run && onOutputs && !run.imported && !isRunActive(run.status) && run.base && run.tests.total > 0 && (
          <button type="button" className="kt-btn" onClick={() => onOutputs({ role: 'run', tab: 'site' })} title="把团队做出来的网站在本机跑起来，直接在这里看">
            打开网站
          </button>
        )}
        {run && (
          <button type="button" className="kt-btn" aria-pressed={follow} onClick={onFollow} title="自动滚到并放大最活跃的泳道">
            跟随
          </button>
        )}
        {run && onProjection && (
          <button type="button" className={`kt-btn${projection ? ' is-on' : ''}`} onClick={onProjection} title={projection ? '退出投影（Esc）' : '全屏、大字、隐藏操作'}>
            {projection ? '退出投影' : '投影'}
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
    <div className="kt-kpis" role="group" aria-label="指标">
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
      <div className="kt-kpi-label">测试通过</div>
      <div className="kt-kpi-value" data-testid="kt-tests-counter" aria-label={`测试通过 ${tests.passed}/${tests.total}`}>
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
        {tests.total ? (green ? <b className="tone-ok">全绿</b> : <b className="tone-bad">{tests.failed} 个红</b>) : '还没有测试'}
        {tests.at ? ` · ${fmtAgo(now - tests.at)}测过` : ''}
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
      <div className="kt-kpi-label">关卡记录 · 在约束下改了几轮</div>
      <div className="kt-kpi-value" data-testid="kt-gates">
        {first ? (
          <span className="kt-gates-score">
            <span className="kt-kpi-mid">{first.passed}/{first.passed + first.failed}</span>
            <span className="kt-gates-arrow">→</span>
            <span className="kt-kpi-big">{run.tests.passed}</span>
            <span className="kt-kpi-of">/{run.tests.total}</span>
          </span>
        ) : (
          <span className="kt-kpi-mid">检查还没跑</span>
        )}
      </div>
      <div className="kt-gates-rows">
        <span className={testBacks ? 'is-hit' : ''}>检查打回 <b>{testBacks}</b> 次</span>
        <span className={reviewBacks ? 'is-hit' : ''}>审查打回 <b>{reviewBacks}</b> 轮</span>
        <span className={people ? 'is-hit' : ''}>人拍板 <b>{people}</b> 次</span>
      </div>
    </div>
  )
}

/** The three layers this run stands on: Kiro Crew runs it, AI-DLC lends the experts, the company brings its rules. */
function UsedKpi({ run }: { run: RunDetail }) {
  const used = new Set(
    run.roles.filter((l) => l.status !== 'skipped').flatMap((l) => l.aidlc_agent.split(',').map((s) => s.trim()).filter(Boolean)),
  ) // the team's: the graph's roster shows which of them are already called
  const company = run.tests.cases.filter((c) => c.file.startsWith('tests/enterprise/')).length
  const written = run.tests.cases.length - company
  const agents = run.roles.filter((l) => l.attempt > 0 && l.status !== 'waiting' && l.status !== 'skipped').length
  return (
    <div className="kt-kpi kt-kpi-used">
      <div className="kt-kpi-label">这次用到了什么</div>
      <div className="kt-used-row">
        <b>Kiro Crew</b> 底座 · 会话 ×{agents} · 审批 · 审计
      </div>
      <div className="kt-used-row">
        <b>AI-DLC</b> 专家 {AIDLC_AGENTS.filter((a) => used.has(a.key)).length}/14
        {used.size > AIDLC_AGENTS.filter((a) => used.has(a.key)).length ? ` + 自定义 ${used.size - AIDLC_AGENTS.filter((a) => used.has(a.key)).length}` : ''}
        <span className="kt-used-dots" aria-hidden="true">
          {AIDLC_AGENTS.map((a) => (
            <i key={a.key} className={used.has(a.key) ? 'is-on' : ''} title={`${a.name}${used.has(a.key) ? '：本次用到' : '：本次没用'}`} />
          ))}
        </span>
      </div>
      <div className="kt-used-row">
        <b>企业规范</b> {run.standards.length ? `适用 ${run.standards.filter((s) => s.kind === 'standard').length} 份 · ` : ''}公司检查 {company} 项 · 团队写的 {written} 项
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
      <div className="kt-kpi-label">并行省时 · 墙钟对比一个 agent 从头做到尾</div>
      <div className="kt-kpi-value" data-testid="kt-saving">
        {saved_s >= 60 ? (
          <span className="kt-saving">
            并行省了 <span className="kt-kpi-big">{minutes}</span> 分钟
          </span>
        ) : (
          <span className="kt-kpi-mid">还没省下时间</span>
        )}
        {speedup !== null && speedup > 1.05 && <span className="kt-speedup" title="串行估算 ÷ 墙钟">×{speedup.toFixed(1)}</span>}
      </div>
      <div className="kt-bars">
        <div className="kt-bar-row">
          <span className="kt-bar-name">墙钟</span>
          <span className="kt-bar" title={`实际用时 ${fmtClock(wall)}`}>
            <i className="kt-bar-wall" style={{ width: `${(wall / max) * 100}%` }} />
          </span>
          <span className="kt-bar-val kt-mono">{fmtClock(wall)}</span>
        </div>
        <div className="kt-bar-row">
          <span className="kt-bar-name">串行估算</span>
          <span className="kt-bar is-segs" title={`每个角色自己干活的时间加起来 ${fmtClock(run.serial_s)}（${fmtSpan(run.serial_s)}）`}>
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
      <div className="kt-kpi-label">角色完成</div>
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
            title={`${l.title}：${laneMeta(l).label}（点一下只看它）`}
            aria-label={`${l.title}：${laneMeta(l).label}`}
            onClick={() => onRole?.(l.key)}
          >
            <RoleIcon role={l.icon || l.key} size={16} />
          </button>
        ))}
      </div>
      <div className="kt-kpi-note">
        {working ? <b className="tone-run">同时在跑 {working}</b> : '没有在跑的'}
        {stuck ? <b className="tone-warn"> · {stuck} 个卡住或等你</b> : null}
        {unmerged ? ` · ${unmerged} 个待合并` : ''}
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
      <div className="kt-kpi-note">{credits === null ? 'KiroCrew 还没报' : '整个运行合计'}</div>
    </div>
  )
}

// ---------------------------------------------------------------------------------------------
// start and stop
// ---------------------------------------------------------------------------------------------

export interface StartOptions {
  source?: string
  team?: string
}
export type StartFn = (requirement: string, opts?: StartOptions) => Promise<void>

/** A one-sentence requirement for tests and the preview page. */
export const DEMO_REQUIREMENT = '给山野咖啡做一个网上小店的 MVP：顾客能按分类逛商品、看详情、加购物车并下单。'
export type PreviewFn = (requirement: string) => Promise<RoutePick>

/** Ready-made requirements at the example company 桃源科技 (fictitious): one fills the requirement box. */
export const SCENARIOS: ReadonlyArray<{ label: string; hint: string; text: string }> = [
  { label: '双十一 · 家电大促', hint: '桃源科技官方商城，从活动模板开工，上线要人批', text: '双十一官方商城大促：挑 20 款家电打折加满减，活动页显示倒计时、划线价和到手价，运营在后台配好就能一键上线。' },
]

const TEAM_CHOICES: ReadonlyArray<{ value: string; label: string }> = [
  { value: 'auto', label: '按需求自动组队（推荐）' },
  { value: 'team-taoyuan-promo.json', label: '桃源科技 · 双十一家电大促' },
  { value: 'team-aidlc.json', label: 'AI-DLC 专家团队（13 个角色，任意新需求）' },
  { value: 'team-bugfix.json', label: '修 bug · 两人小队（要填项目目录）' },
]

/** 组队预览: the team the orchestrator picks for the requirement, the official AI-DLC scope it follows, and which of
 * the 14 official experts it calls (the others greyed). */
export function TeamPick({ pick }: { pick: RoutePick | null }) {
  if (!pick?.team) {
    return (
      <p className="kt-pick is-empty" data-testid="kt-pick">
        编排器按需求里的关键词组队……
      </p>
    )
  }
  const t = pick.team
  const used = new Set(t.agents.flatMap((a) => a.split(',').map((x) => x.trim())))
  const experts = expertsOf(t.roles)
  const absent = t.roles.filter((r) => r.on_crew === false)
  const kb = pick.knowledge
  const phases = PHASES.map((ph) => ({ ...ph, roles: t.roles.filter((r) => r.phase === ph.key) })).filter((ph) => ph.roles.length)
  return (
    <section className="kt-pick" aria-label="组队预览" data-testid="kt-pick">
      <p className="kt-pick-team" title={pick.matched.length ? `依据需求里的「${pick.matched.join('、')}」` : '没有特别的线索，用默认流程'}>
        <b>{t.name}</b> · {t.people?.length ? `${t.people.length} 人里挑了 ${t.roles.length} 位` : `${t.roles.length} 位成员`} · {pick.why}
      </p>
      <ol className="kt-pick-phases" aria-label="按 AI-DLC 阶段">
        {phases.map((ph) => (
          <li key={ph.key}>
            <span className="kt-pick-phase">
              {ph.n} {ph.title}
            </span>
            {ph.roles.map((r) => (
              <span key={r.key} className={`kt-pick-role${r.on_crew === false ? ' is-absent' : ''}`} title={`${r.stage}${r.member ? ` · Crew 成员 ${r.member}` : ''}`}>
                <RoleIcon role={r.icon || r.key} size={16} />
                <span>
                  {r.title} agent
                  {r.gate ? <em> · 人批准</em> : null}
                  {r.assignment && <small>{r.assignment}</small>}
                </span>
              </span>
            ))}
          </li>
        ))}
      </ol>
      {t.official_stages ? (
        <p className="kt-dim">
          覆盖 AI-DLC {t.scope} 流程的 {t.stages.length} 个阶段：{t.stages.join('、')}
          {t.extra_stages.length > 0 && `；另加 ${t.extra_stages.join('、')}（${t.extra_note}）`}
        </p>
      ) : null}
      <div className="kt-pick-roster" aria-label="AI-DLC 官方的 14 个专家和公司自定义的">
        {experts.map((a) => (
          <span key={a.key} className={`kt-pick-agent${used.has(a.key) ? ' is-used' : ''}${a.custom ? ' is-custom' : ''}`} title={used.has(a.key) ? '这次会调用' : '这次不调用'}>
            {a.name}
          </span>
        ))}
      </div>
      {absent.some((r) => r.optional) && (
        <p className="kt-warn" data-testid="kt-pick-unhired">
          <span title="可选岗位：交给团队时 Crew「代理」里没有这位成员，就不进这次的团队，它负责的部分保持模板原样">
            {absent.filter((r) => r.optional).map((r) => r.title).join('、')}还没入职，这次不参与（在 Crew「代理」里加上 {absent.filter((r) => r.optional).map((r) => r.member).join('、')}，再交给团队就会带上它）
          </span>
        </p>
      )}
      {absent.some((r) => !r.optional) && (
        <p className="kt-warn">
          <span title="没加的话，轮到它时会停下等，加上就自动开工">{absent.filter((r) => !r.optional).map((r) => r.title).join('、')}还没加入团队（在 Crew「代理」里加上 {absent.filter((r) => !r.optional).map((r) => r.member).join('、')}；没加的话轮到它时会停下等）</span>
        </p>
      )}
      {pick.standards && pick.standards.length > 0 && (
        <div className="kt-pick-std" aria-label="适用的公司规范">
          <b>适用规范：</b>
          {pick.standards.map((s) => (
            <span key={s.id} className={`kt-pick-agent is-used is-${s.kind}`} title={`${s.owner ? `${s.owner} · ` : ''}${s.why}`}>
              {s.kind === 'data' ? '数据' : ''}《{s.title}》
            </span>
          ))}
        </div>
      )}
      {kb && (
        <p className={kb.present === false ? 'kt-warn' : 'kt-dim'}>
          知识库「{kb.name}」：{kb.present === false ? `还没挂上，在 Crew 侧栏「知识库 → 来源」里加 ${kb.path || '~/workplace/taoyuan/knowledge'}` : kb.present === null ? '读取中' : `${kb.items ?? 0} 份文档${kb.status === 'synced' ? ' · 已同步' : ' · 正在索引'}`}
        </p>
      )}
      {t.source && <p className="kt-dim">代码仓库：{t.source}</p>}
      {t.needs_source && !t.source && <p className="kt-warn">这支团队要在一个已有项目上做：在下面填项目的代码目录。</p>}
    </section>
  )
}

/** How often the open form asks again who the team would be: a member added in Crew meanwhile (the service reads Crew's
 * members every 5 s) shows up in the preview without retyping the requirement. */
export const PREVIEW_REFRESH_MS = 5000

export function StartForm({ onStart, onCancel, preview, refreshMs = PREVIEW_REFRESH_MS }: { onStart: StartFn; onCancel?: () => void; preview?: PreviewFn; refreshMs?: number }) {
  const [text, setText] = useState(SCENARIOS[0].text)
  const [source, setSource] = useState('')
  const [team, setTeam] = useState('auto')
  const [pick, setPick] = useState<RoutePick | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [tick, setTick] = useState(0)
  useEffect(() => {
    if (!preview || team !== 'auto') return
    const t = setInterval(() => setTick((n) => n + 1), refreshMs)
    return () => clearInterval(t)
  }, [preview, team, refreshMs])
  useEffect(() => {
    if (!preview || team !== 'auto') return
    let alive = true
    const t = setTimeout(() => {
      preview(text)
        .then((p) => alive && setPick(p))
        .catch(() => alive && setPick(null))
    }, 250)
    return () => {
      alive = false
      clearTimeout(t)
    }
  }, [preview, team, text, tick])
  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (busy) return
    setBusy(true)
    setErr('')
    try {
      const src = source.trim()
      const t = team === 'team.json' ? undefined : team // the app's default team file needs no name
      await onStart(text.trim(), { ...(src ? { source: src } : {}), ...(t ? { team: t } : {}) })
    } catch (x) {
      setErr(errorText(x))
    } finally {
      setBusy(false)
    }
  }
  return (
    <form className="kt-start" onSubmit={submit} aria-label="给 agent 团队派需求">
      <div className="kt-scenarios" role="group" aria-label="需求示例">
        {SCENARIOS.map((s) => (
          <button key={s.label} type="button" className={`kt-scenario${text === s.text ? ' is-on' : ''}`} onClick={() => setText(s.text)} title={s.hint}>
            <b>{s.label}</b>
            <small>{s.hint}</small>
          </button>
        ))}
      </div>
      <label htmlFor="kt-req">交给 agent 团队的需求</label>
      <p className="kt-dim kt-req-hint">写一句话就行：编排器按需求组队，团队先把它整理成范围、验收标准和分工，你在关卡上批准后才往下做。</p>
      <textarea id="kt-req" value={text} rows={3} onChange={(e) => setText(e.target.value)} placeholder={SCENARIOS[0].text} />
      {preview && team === 'auto' && <TeamPick pick={pick} />}
      <details className="kt-start-more" open={team !== 'auto' || !!source}>
      <summary>高级选项</summary>
      <div className="kt-start-row">
        <label className="kt-start-field">
          <span>已有项目的代码目录（修 bug、接手已有产品时填；新项目不用填）</span>
          <input type="text" value={source} onChange={(e) => setSource(e.target.value)} placeholder="目录的绝对路径，例如 /Users/you/workplace/aidlc-team/runs/r1009abcd/wt/_run" />
        </label>
        <label className="kt-start-field is-narrow">
          <span>团队</span>
          <select value={team} onChange={(e) => setTeam(e.target.value)}>
            {TEAM_CHOICES.filter((c) => preview || c.value !== 'auto').map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </select>
        </label>
      </div>
      </details>
      <div className="kt-start-actions">
        <button type="submit" className="kt-btn is-primary" disabled={busy}>
          {busy ? '正在派给团队…' : '交给团队'}
        </button>
        {onCancel && (
          <button type="button" className="kt-btn" onClick={onCancel}>
            取消
          </button>
        )}
        <span className="kt-dim">按 AI-DLC 的阶段推进：需求和分工由你批准，交付前过公司检查和独立审查</span>
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
      <strong id="kt-stop-title">停止「{run.title}」？</strong>
      <span id="kt-stop-desc">{live ? `在跑和排队的 ${live} 个 agent 会被停掉，还没开工的角色不再派出去。` : '还没开工的角色不再派出去。'}</span>
      <span className="kt-confirm-actions">
        <button type="button" className="kt-btn is-danger is-solid" onClick={confirm} disabled={busy}>
          {busy ? '正在停止…' : '确认停止'}
        </button>
        <button type="button" className="kt-btn" onClick={onCancel} autoFocus>
          取消
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

/** 交付标签 as the person confirms them at the gate of the role that proposed them (they count on the CTO view). */
export type DeliveryPick = Pick<Delivery, 'name' | 'kind' | 'size' | 'line'>
const DELIVERY_KINDS: Delivery['kind'][] = ['新应用', '新功能', '修复']
const DELIVERY_SIZES: Delivery['size'][] = ['小', '中', '大']
const DELIVERY_LINES: Delivery['line'][] = ['电商', '移动应用', '客户关系管理', '供应链', '内部系统']

/** A person at a gate, inside the page (the desktop app has no window.prompt): approve with an optional note for
 * everyone after it, or send it back with what to change. *skips*: the optional members the proposal leaves out (they
 * sit the run out once approved). *overrule*: a review that still says 要改 with its rounds used up: approving it is
 * overruling the review (a reason is required), sending it back is one more round as the review says. */
/** The person's choice for each question of a gate, by question id (sent with 批准). */
export type GateAnswers = Record<string, { choice: string; text: string }>
/** 拦下的风险 sent with 退回: what the send-back keeps from going live, the amount in yuan (or none). */
export type GateRisk = { what: string; amount: number | null }

/** A gate: 批准 (with an answer for each question the role put to the person), 讨论 (it answers; the gate stays open),
 * or 退回. What was said in a 讨论 so far is shown in all three; at a writing role's gate, the stage's documents too. */
export function GateDialog({ label, who = '', decision, preset, presetRisk, split, skips, report, onReport, overrule = false, delivery, questions = [], talk = [], outputs = [], onConfirm, onCancel }: {
  label: string; who?: string; decision: GateDecision; preset?: string; presetRisk?: GateRisk | null; split?: { key: string; title: string; icon: string; assignment: string }[]
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
    return back && (what || wan > 0) ? { what, amount: wan > 0 ? Math.round(wan * 1e4) : null } : undefined
  }
  const answer = (id: string, a: Partial<{ choice: string; text: string }>) => setAnswers((x) => ({ ...x, [id]: { ...x[id], ...a } }))
  const confirm = async () => {
    if (overrule && approve && !note.trim()) {
      setErr('审查还说要改：推翻它放行要写理由')
      return
    }
    if (discuss && !note.trim()) {
      setErr('写下你想问的或想商量的')
      return
    }
    if (!approve && !discuss && !overrule && !note.trim()) {
      setErr('退回要写明改什么')
      return
    }
    const blank = asking ? questions.find((q) => answers[q.id]?.choice === 'other' && !answers[q.id].text.trim()) : undefined
    if (blank) {
      setErr(`决定 ${blank.id} 选了「其他」：写下你的决定`)
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
  const title = discuss ? `讨论${label}` : overrule ? (approve ? `仍然批准${label}` : `退回${label}，再改一轮`) : approve ? `批准${label}` : `退回${label}`
  const lead = discuss
    ? `写下你想问的或想商量的。${who || '它'}会回答，需要的话改自己的文档；关卡一直开着，讨论完再批准或退回。`
    : overrule ? (approve ? '审查还说要改，打回的轮数用完了。批准就是你推翻审查结论放行：写明理由，记在签字单上，然后部署。' : '按审查意见再改一轮：没写打回给谁时，打回审查点名的成员；你写的意见一起交给它们，和审查冲突时以你为准。改完审查再看一遍，然后回到这里。')
      : report !== undefined ? (approve ? '批准后部署。你的意见会记在签字单上。' : '写明打回给谁、改什么（「打回：前端开发 #2」），改完审查会再看一遍，然后回到这里。')
        : approve ? (asking ? '批准后，编排器按这份分工派下一阶段开工。下面每件事选一个答案（默认是它的建议），你的决定和意见会交给后面的每个 agent。' : '批准后，编排器按这份分工派下一阶段开工。有意见可以写在这里，会交给后面的每个 agent（可以不写）。')
          : '写下要改什么，它会按你的意见重写，再交给你批准。'
  return (
    <div className={`kt-confirm kt-gate-dialog${approve ? ' is-approve' : ''}${discuss ? ' is-discuss' : ''}`} role="dialog" aria-labelledby="kt-gate-title" data-testid="kt-gate-dialog">
      <strong id="kt-gate-title">{title}</strong>
      <span>{lead}</span>
      {outputs.length > 0 && (
        <p className="kt-gate-docs" data-testid="kt-gate-docs">
          <span className="kt-dim">这一阶段的产出：</span>
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
              <fieldset key={q.id} className="kt-gate-q" aria-label={`决定 ${q.id}`}>
                <legend>
                  <b>决定 {q.id}</b> {q.q}
                </legend>
                {q.options.map((o) => (
                  <label key={o.key} className={a.choice === o.key ? 'is-picked' : undefined}>
                    <input type="radio" name={`q-${q.id}`} checked={a.choice === o.key} onChange={() => answer(q.id, { choice: o.key })} />
                    <span>
                      {o.key}. {o.text}
                      {o.key === q.recommend && <em className="kt-gate-rec">建议</em>}
                    </span>
                  </label>
                ))}
                <label className={a.choice === 'other' ? 'is-picked' : undefined}>
                  <input type="radio" name={`q-${q.id}`} checked={a.choice === 'other'} onChange={() => answer(q.id, { choice: 'other' })} />
                  <span>其他</span>
                  {a.choice === 'other' && <input className="kt-gate-other" aria-label={`决定 ${q.id} 的其他答案`} value={a.text} maxLength={300} onChange={(e) => answer(q.id, { text: e.target.value })} placeholder="写下你的决定" />}
                </label>
                {(q.why || differs) && (
                  <span className="kt-dim">
                    {q.why && `建议理由：${q.why}`}
                    {differs && <b className="kt-gate-differs">{q.why ? '；' : ''}与建议（{q.recommend}）不同</b>}
                  </span>
                )}
              </fieldset>
            )
          })}
        </div>
      )}
      {talk.length > 0 && (
        <ol className="kt-gate-talk" aria-label="讨论记录" data-testid="kt-gate-talk">
          {talk.map((t, i) => (
            <li key={i} className={t.who === 'person' ? 'is-person' : 'is-agent'}>
              <b>{t.who === 'person' ? '你' : who || '它'}</b>
              <div className="kt-gate-talk-text">{t.who === 'agent' ? <MarkdownRenderer content={t.text} /> : t.text}{t.changed ? <em className="kt-dim">（改了文档）</em> : null}</div>
            </li>
          ))}
        </ol>
      )}
      {report !== undefined && !discuss && (
        <div className="kt-gate-report">
          <b>{overrule ? '审查还说要改：' : '审查结论：'}</b>
          {report || '（没有结论）'}
          {onReport && (
            <button type="button" className="kt-btn" onClick={onReport}>
              看完整审查报告
            </button>
          )}
        </div>
      )}
      {split && split.length > 0 && !discuss && (
        <ul className="kt-gate-split" aria-label="分工提案">
          {split.map((m) => (
            <li key={m.key}>
              <RoleIcon role={m.icon || m.key} size={14} /> <b>{m.title}</b> {m.assignment}
            </li>
          ))}
        </ul>
      )}
      {skips && skips.length > 0 && !discuss && (
        <ul className="kt-gate-split is-out" aria-label="这次不要的成员" data-testid="kt-gate-skips">
          {skips.map((m) => (
            <li key={m.key}>
              <RoleIcon role={m.key} size={14} /> <b>{m.title}</b> 这次不要：{m.why}
            </li>
          ))}
          <li className="kt-dim">批准后它们这次不参与，归它们的检查这次不跑；要它们就退回，写明要谁。</li>
        </ul>
      )}
      {approve && pick && delivery && (
        <fieldset className="kt-gate-delivery" data-testid="kt-gate-delivery">
          <legend title="签字放行后按这些标签计入 CTO 视图">交付标签{delivery.why ? `（提议：${delivery.why}）` : ''}</legend>
          <input aria-label="交付名称" value={pick.name} maxLength={20} onChange={(e) => setPick({ ...pick, name: e.target.value })} />
          <select aria-label="类型" value={pick.kind} onChange={(e) => setPick({ ...pick, kind: e.target.value as Delivery['kind'] })}>
            {DELIVERY_KINDS.map((k) => <option key={k}>{k}</option>)}
          </select>
          <select aria-label="规模" value={pick.size} onChange={(e) => setPick({ ...pick, size: e.target.value as Delivery['size'] })}>
            {DELIVERY_SIZES.map((k) => <option key={k}>{k}</option>)}
          </select>
          <select aria-label="业务线" value={pick.line} onChange={(e) => setPick({ ...pick, line: e.target.value as Delivery['line'] })}>
            {DELIVERY_LINES.map((k) => <option key={k}>{k}</option>)}
          </select>
        </fieldset>
      )}
      {back && (
        <fieldset className="kt-gate-delivery kt-gate-risk" data-testid="kt-gate-risk">
          <legend title="计入 CTO 视图的「更稳」和签字单">拦下的风险（可选）</legend>
          <input aria-label="拦下的风险" className="kt-gate-what" value={risk.what} maxLength={60} onChange={(e) => setRisk({ ...risk, what: e.target.value })} placeholder="例如：价保退差超过审批线" />
          <label>
            金额 <input aria-label="金额（万元）" className="kt-gate-amount" type="number" min={0} step={0.1} value={risk.wan} onChange={(e) => setRisk({ ...risk, wan: e.target.value })} placeholder="可不填" /> 万元
          </label>
        </fieldset>
      )}
      <textarea className="kt-gate-note" rows={3} value={note} onChange={(e) => setNote(e.target.value)} placeholder={discuss ? '例如：第 2 题为什么建议 B？改成 A 会有什么影响？' : overrule && approve ? '例如：风险我担，价保退差按 28 万预留，活动结束后财务复核' : approve ? '例如：补充一条业务规则' : '例如：漏了一条验收标准'} autoFocus aria-label={discuss ? '讨论' : '意见'} />
      <span className="kt-confirm-actions">
        {preset && note !== preset && !discuss && (
          <button type="button" className="kt-btn" onClick={() => { setNote(preset); if (back && presetRisk) setRisk({ what: presetRisk.what, wan: presetRisk.amount != null ? String(presetRisk.amount / 1e4) : '' }) }} title={preset}>
            填入预设意见
          </button>
        )}
        <button type="button" className={`kt-btn is-solid${approve || discuss ? ' is-primary' : ' is-danger'}`} onClick={confirm} disabled={busy}>
          {busy ? '正在提交…' : discuss ? '发出' : overrule && approve ? '确认推翻并批准' : approve ? '确认批准' : '确认退回'}
        </button>
        <button type="button" className="kt-btn" onClick={onCancel}>
          取消
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

// ---------------------------------------------------------------------------------------------
// the empty state
// ---------------------------------------------------------------------------------------------

/** The AI-DLC 专家团队 (team/team-aidlc.json): AI-DLC 官方领域专家，按依赖从左到右；同一列的并行。 */
const TEAM_INTRO: Array<{ phase: string; title: string; roles: Array<Array<{ key: string; title: string; does: string }>> }> = [
  {
    phase: '1 构思 Ideation',
    title: '一句话需求 → 范围清单',
    roles: [
      [
        { key: 'intent', title: '意图', does: '为谁、为什么、怎样算成功' },
        { key: 'feasibility', title: '约束', does: '对照企业规范和上架要求' },
      ],
      [{ key: 'scope', title: '范围', does: '交给人批准' }],
    ],
  },
  {
    phase: '2 启动 Inception',
    title: '读懂系统、定接口、分工，交给人批准',
    roles: [
      [{ key: 'architect', title: '架构师', does: '逆向工程、接口、谁改哪里' }],
      [{ key: 'designer', title: '界面', does: '沿用现有风格' }],
      [{ key: 'pm', title: '需求', does: '可验收的标准，汇总交给人批准' }],
    ],
  },
  {
    phase: '3 构建 Construction',
    title: '先写检查，再写代码',
    roles: [
      [
        { key: 'compliance', title: '合规与安全', does: '规范 → 检查，先红' },
        { key: 'tester', title: '测试', does: '护栏：不许改坏' },
      ],
      [
        { key: 'backend', title: '后端', does: '' },
        { key: 'frontend', title: '网页', does: '' },
        { key: 'mobile', title: '安卓', does: '' },
        { key: 'ops', title: '运维', does: '' },
      ],
    ],
  },
  { phase: '✓ 评审关卡', title: '独立、只读，要改就打回', roles: [[{ key: 'reviewer', title: '评审', does: '最多打回两轮，然后交给人' }]] },
]

export function EmptyStart({ onStart, preview }: { onStart: StartFn; preview?: PreviewFn }) {
  return (
    <section className="kt-empty" data-testid="kt-empty" aria-label="还没有运行">
      <div className="kt-empty-hero">
        <h2>做出来越来越便宜，好产品依然稀缺</h2>
        <p>
          AI 让一个好想法几天就能变成能演示的东西；但要交给整个公司用、要上架、要守住企业自己的规范，这一段才是难点。这支 agent 团队从一句话需求开始，按 AWS AI-DLC 的流程走：构思、启动、构建、评审关卡。编排器先按需求里的关键词组队（和 AI-DLC 选 scope 的规则一样），每个角色都是 AI-DLC 定义的领域专家，在 Kiro Crew 上以独立的会话或子 agent 运行，只带自己需要的上下文；编排器是确定性的程序，按团队配置排程、派活、合入、跑检查、打回，不靠模型自觉。范围由人批准，检查由机器判定，交付由独立评审放行。
        </p>
        <p className="kt-empty-punch">好产品不是一次生成出来的，是一道道关卡验收出来的。</p>
      </div>
      <ol className="kt-team-intro is-phased" aria-label="团队，按 AI-DLC 阶段从左到右">
        {TEAM_INTRO.map((ph) => (
          <li key={ph.phase} className="kt-intro-phase">
            <div className="kt-intro-phase-head">
              <b>{ph.phase}</b>
              <span>{ph.title}</span>
            </div>
            <div className="kt-intro-phase-body">
              {ph.roles.map((stage, i) => (
                <div key={i} className="kt-intro-stage">
                  {stage.length > 1 && <span className="kt-intro-par">并行 ×{stage.length}</span>}
                  {stage.map((r) => (
                    <div key={r.key} className="kt-intro-role">
                      <RoleIcon role={r.key} size={26} className="kt-intro-emoji" />
                      <span className="kt-intro-name">
                        <b>{r.title}</b>
                        <small className="kt-intro-agent">agent</small>
                      </span>
                      <span className="kt-intro-does">{r.does}</span>
                    </div>
                  ))}
                </div>
              ))}
            </div>
          </li>
        ))}
      </ol>
      <StartForm onStart={onStart} preview={preview} />
    </section>
  )
}

// ---------------------------------------------------------------------------------------------
// AI-DLC's 14 official experts
// ---------------------------------------------------------------------------------------------

const EXPERT_STATE = {
  busy: { label: '干活中', hint: '它的 agent 正在干活' },
  used: { label: '已调用', hint: '编排器已经派它干过活' },
  team: { label: '待命', hint: '这支团队有它的任务，还没轮到' },
  none: { label: '不参与', hint: '这支团队没有它的任务，这次不会被激活' },
  absent: { label: '未入职', hint: '这支团队要它，但 Crew 的「代理」里还没有这位成员：在代理页从模板加上（没加时用同名模板顶上）' },
} as const

/** All 14 experts AWS AI-DLC defines, in four states: at work, called, on the team but not its turn yet, or not on
 * this team at all (greyed, shown anyway: the orchestrator picked a team without it). */
export function ExpertStrip({ run }: { run: RunDetail }) {
  const { team, used, busy } = aidlcUse(run.roles)
  const experts = expertsOf(run.roles)
  const custom = experts.filter((a) => a.custom).length
  const members = run.crew_members ? new Set(run.crew_members) : null
  const of = (key: string) => run.roles.filter((l) => l.status !== 'skipped' && l.aidlc_agent.split(',').map((x) => x.trim()).includes(key))
  // a member added to the team's 「代理」 page that no role here calls on: shown too, as on the team with nothing to do
  // (a company's own copy of an official expert, like luming-architect-agent, is that expert: not an extra)
  const extra = (run.crew_members ?? []).filter((m) => !experts.some((a) => a.key === m) && !officialOf(m) && !run.roles.some((l) => l.member === m))
  return (
    <section className="kt-experts" aria-label="AI-DLC 官方 14 位专家" data-testid="kt-experts">
      <span className="kt-experts-title">
        AI-DLC 官方 14 位专家{custom + extra.length ? ` + 自定义 ${custom + extra.length} 位` : ''} · 这次用 {team.size} 位
      </span>
      <ul className="kt-experts-list">
        {experts.map((a) => {
          const lanes = of(a.key)
          // a role whose Crew member is not on the 「代理」 page (not added yet): its session boots the template instead
          const absent = members !== null && lanes.some((l) => l.member && !members.has(l.member))
          const state = busy.has(a.key) ? 'busy' : used.has(a.key) ? 'used' : team.has(a.key) ? (absent ? 'absent' : 'team') : 'none'
          const n = lanes.length
          const who = lanes.map((l) => l.title).join('、')
          return (
            <li key={a.key} className={`kt-expert is-${state}${a.custom ? ' is-custom' : ''}`} data-state={state} title={`${a.name}（${a.key}）：${EXPERT_STATE[state].hint}${who ? `；这次是 ${who}` : ''}`}>
              <b>
                {a.name}
                {n > 1 ? ` ×${n}` : ''}
              </b>
              <small>{a.custom && state === 'none' ? '自定义' : EXPERT_STATE[state].label}</small>
            </li>
          )
        })}
        {extra.map((m) => (
          <li key={m} className="kt-expert is-none is-custom is-joined" data-state="joined" title={`${m}：已加入团队（Crew「代理」里有），这次的需求没有它的任务`}>
            <b>{m.replace(/-agent$/, '')}</b>
            <small>已入职</small>
          </li>
        ))}
      </ul>
    </section>
  )
}
