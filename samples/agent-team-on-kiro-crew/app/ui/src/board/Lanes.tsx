/**
 * One lane per role, in team order: who it is, what state it is in and since when, what its agent is
 * doing right now (the last tool call, the last few, the live text it is writing), what it changed
 * (files with +/− bars, commits), what went wrong (violations, conflicts) and its summary when done.
 *
 * Every lane ends in a time track on one shared axis (the run's start → now): its working spans, one
 * per attempt, with commits, merges, bounces and violations marked where they happened. Read down the
 * lanes and the parallel work lines up like a Gantt chart.
 */
import { useEffect, useRef } from 'react'
import type { Lane, RunDetail, TestCase } from '../types'
import { LIVE, WORKING, baseName, caseMeta, fmtAgo, fmtClock, fmtCredits, laneMeta, toolIcon, waitingFor, waitingText } from './format'
import { useServerNow, useSinceSnapshot, useTypewriter } from './hooks'
import { RoleIcon } from './RoleIcon'

export interface LanesProps {
  /** 重试 a failed role. */
  onRetry?: (role: string) => void
  run: RunDetail
  focus: string | null
  follow: string | null
  bumps: Record<string, number>
  onRole: (key: string) => void
  reducedMotion: boolean
  /** On a projector the lanes scroll on their own under the graph: the followed lane goes to the top. */
  projection?: boolean
  /** Open the 产出 drawer at this role (and file). */
  onOutputs?: (role: string, path?: string | null) => void
  /** an AI-DLC phase picked out: the lanes of the other phases dim */
  phase?: string | null
}

export function Lanes({ run, focus, follow, bumps, onRole, reducedMotion, projection = false, onOutputs, onRetry, phase = null }: LanesProps) {
  const out = run.roles.filter((l) => l.status === 'skipped') // sitting this run out: no lane of their own
  return (
    <section className="kt-lanes" aria-label="角色泳道" data-testid="kt-lanes">
      <LanesAxis run={run} />
      {run.roles.filter((l) => l.status !== 'skipped').map((lane) => (
        <LaneRow
          key={lane.key}
          lane={lane}
          run={run}
          focused={focus === lane.key}
          dim={focus ? focus !== lane.key : !!phase && (lane.phase === 'review' ? 'construction' : lane.phase) !== phase}
          followed={follow === lane.key}
          bump={bumps[lane.key] ?? 0}
          onRole={onRole}
          reducedMotion={reducedMotion}
          projection={projection}
          onOutputs={onOutputs}
          onRetry={onRetry}
        />
      ))}
      {out.length > 0 && (
        <p className="kt-dim kt-lanes-out" data-testid="kt-lanes-out">
          这次不参与：{out.map((l) => `${l.title}（${l.summary || '本项目用不到'}）`).join('、')}
        </p>
      )}
    </section>
  )
}

// ---------------------------------------------------------------------------------------------
// the shared time axis
// ---------------------------------------------------------------------------------------------

export interface Span {
  a: number
  b: number
  attempt: number
  live: boolean
}

/** The lane's working spans, one per attempt: from each `spawned` to the next done / failed / merged. */
export function laneSpans(lane: Lane, run: RunDetail, now: number): Span[] {
  const evs = run.events
    .filter((e) => e.role === lane.key && (e.kind === 'spawned' || e.kind === 'done' || e.kind === 'failed' || e.kind === 'merged'))
    .sort((x, y) => x.at - y.at || x.seq - y.seq)
  const out: Span[] = []
  let open: number | null = null
  let n = 0
  for (const e of evs) {
    if (e.kind === 'spawned') {
      if (open !== null) out.push({ a: open, b: e.at, attempt: n, live: false })
      open = e.at
      n++
      continue
    }
    // the start fell out of the event window (or was never recorded): it started at started_at
    if (open === null && !out.length && lane.started_at !== null) {
      open = lane.started_at
      n = Math.max(n, 1)
    }
    if (open !== null) {
      out.push({ a: open, b: e.at, attempt: n, live: false })
      open = null
    }
  }
  const live = LIVE.has(lane.status) || lane.status === 'queued'
  if (open !== null) out.push({ a: open, b: live ? now : (lane.done_at ?? now), attempt: n, live })
  else if (live && lane.agent && !out.some((s) => s.b >= lane.agent!.started)) out.push({ a: lane.agent.started, b: now, attempt: lane.attempt, live: true })
  if (!out.length && lane.started_at !== null) out.push({ a: lane.started_at, b: lane.done_at ?? (live ? now : lane.started_at), attempt: 1, live })
  return out
}

function useAxis(run: RunDetail): { t0: number; t1: number; pct: (t: number) => number } {
  const now = useServerNow()
  const t0 = run.started_at
  const t1 = Math.max(t0 + 1, run.ended_at ?? now)
  return { t0, t1, pct: (t: number) => Math.min(100, Math.max(0, ((t - t0) / (t1 - t0)) * 100)) }
}

function LanesAxis({ run }: { run: RunDetail }) {
  const { t0, t1 } = useAxis(run)
  const dur = t1 - t0
  return (
    <div className="kt-lane kt-lane-axis" aria-hidden="true">
      <div className="kt-axis-title">时间线（从运行开始）</div>
      <div className="kt-axis">
        {[0, 0.25, 0.5, 0.75, 1].map((f) => (
          <span key={f} className="kt-axis-tick" style={{ left: `${f * 100}%` }}>
            {fmtClock(f * dur)}
          </span>
        ))}
      </div>
    </div>
  )
}

function LaneTrack({ lane, run }: { lane: Lane; run: RunDetail }) {
  const now = useServerNow()
  const { pct } = useAxis(run)
  const spans = laneSpans(lane, run, now)
  const marks = [
    ...lane.commits.map((c) => ({ at: c.at, kind: 'commit', title: `提交 ${c.sha}：${c.subject}` })),
    ...run.merges.filter((m) => m.role === lane.key).map((m) => ({ at: m.at, kind: m.status === 'conflict' ? 'conflict' : 'merged', title: m.status === 'conflict' ? `合入冲突：${m.note ?? ''}` : `合入运行分支 ${m.sha}` })),
    ...run.events.filter((e) => (e.kind === 'bounce' && (e.to === lane.key || e.role === lane.key)) || (e.kind === 'violation' && e.role === lane.key)).map((e) => ({ at: e.at, kind: e.kind, title: e.text })),
  ]
  return (
    <div className="kt-track" role="img" aria-label={`${lane.title}的时间线：${spans.length ? spans.map((s) => `第 ${s.attempt} 轮 ${fmtClock(s.a - run.started_at)}–${s.live ? '现在' : fmtClock(s.b - run.started_at)}`).join('，') : '还没开工'}`}>
      <div className="kt-track-line" />
      {spans.map((s, i) => (
        <span
          key={i}
          className={`kt-track-span${s.live ? ' is-live' : ''}${s.attempt > 1 ? ' is-fix' : ''}`}
          style={{ left: `${pct(s.a)}%`, width: `${Math.max(0.6, pct(s.b) - pct(s.a))}%` }}
          title={`第 ${s.attempt} 轮：${fmtClock(s.a - run.started_at)}–${s.live ? '现在' : fmtClock(s.b - run.started_at)}`}
        />
      ))}
      {marks.map((m, i) => (
        <span key={`m${i}`} className={`kt-track-mark is-${m.kind}`} style={{ left: `${pct(m.at)}%` }} title={m.title} />
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------------------------
// one lane
// ---------------------------------------------------------------------------------------------

function LaneRow({
  lane,
  run,
  focused,
  dim,
  followed,
  bump,
  onRole,
  reducedMotion,
  projection,
  onOutputs,
  onRetry,
}: {
  lane: Lane
  run: RunDetail
  focused: boolean
  dim: boolean
  followed: boolean
  bump: number
  onRole: (k: string) => void
  reducedMotion: boolean
  projection: boolean
  onOutputs?: (role: string, path?: string | null) => void
  onRetry?: (role: string) => void
}) {
  const ref = useRef<HTMLElement | null>(null)
  useEffect(() => {
    if (followed) ref.current?.scrollIntoView?.({ block: projection ? 'start' : 'nearest', behavior: reducedMotion ? 'auto' : 'smooth' })
  }, [followed, reducedMotion, projection])
  const meta = laneMeta(lane)
  const waiting = lane.status === 'waiting'
  return (
    <article
      ref={ref}
      className={`kt-lane is-${lane.status} tone-${meta.tone}${focused ? ' is-focus' : ''}${dim ? ' is-dim' : ''}${followed ? ' is-followed' : ''}${waiting ? ' is-compact' : ''}`}
      data-testid="kt-lane"
      data-role={lane.key}
      data-status={lane.status}
      aria-label={`${lane.title}：${meta.label}`}
    >
      {bump > 0 && <span key={bump} className="kt-lane-bump" aria-hidden="true" />}
      <LaneId lane={lane} focused={focused} onRole={onRole} onOutputs={onOutputs} />
      <div className="kt-lane-live">
        <LaneSituation lane={lane} run={run} onRole={onRole} onRetry={onRetry} />
        {!waiting && <LiveWork lane={lane} reducedMotion={reducedMotion} />}
      </div>
      <div className="kt-lane-work">{!waiting && <Changes lane={lane} run={run} followed={followed} onOutputs={onOutputs} />}</div>
      <LaneTrack lane={lane} run={run} />
    </article>
  )
}

function LaneId({ lane, focused, onRole, onOutputs }: { lane: Lane; focused: boolean; onRole: (k: string) => void; onOutputs?: (role: string) => void }) {
  const meta = laneMeta(lane)
  const a = lane.agent
  const live = LIVE.has(lane.status) || lane.status === 'queued'
  const credits = lane.credits ?? a?.credits ?? null
  return (
    <div className="kt-lane-id">
      <button type="button" className="kt-avatar" onClick={() => onRole(lane.key)} aria-pressed={focused} aria-label={focused ? `不再只看${lane.title}` : `只看${lane.title}`} title={focused ? '再点一次看全部' : '只看这个角色'}>
        <RoleIcon role={lane.icon || lane.key} size={20} />
      </button>
      <div className="kt-lane-who">
        <div className="kt-lane-name">
          <span>{lane.title}</span>
          {lane.attempt > 1 && <span className="kt-badge tone-fix">第 {lane.attempt} 轮</span>}
        </div>
        {lane.doing && <div className={`kt-lane-doing${lane.doing !== lane.assignment ? ' is-sent-back' : ''}`}>{lane.doing}</div>}
        <div className="kt-lane-tag">
          <span className={`kt-pill tone-${meta.tone}`} title={meta.hint}>
            <i aria-hidden="true">{meta.icon}</i>
            {meta.label}
          </span>
          <span className="kt-lane-model kt-mono" title={`模型 ${lane.model}`}>
            {lane.model}
          </span>
        </div>
      </div>
      {lane.status !== 'waiting' && (
        <p className="kt-lane-stats">
          <span title={live ? '这一轮已经跑了多久' : '它自己干活的时间'}>
            ⏱ <b>{live && a ? <LiveClock base={a.elapsed_s} /> : fmtClock(lane.active_s)}</b>
            {live && a ? (lane.active_s > a.elapsed_s + 1 ? ` 本轮 · 合计 ${fmtClock(lane.active_s)}` : ' 本轮') : ' 用时'}
          </span>
          {a && (
            <span>
              <b>{a.turns}</b> 回合 · <b>{a.tool_count}</b> 次工具
            </span>
          )}
          {(credits !== null || live) && (
            <span>
              <b>{fmtCredits(credits)}</b> credits{live ? (credits !== null ? ' + 本轮未结' : '（本轮未结）') : ''}
            </span>
          )}
        </p>
      )}
      {lane.status !== 'waiting' && onOutputs && (
        <button type="button" className="kt-out-btn" onClick={() => onOutputs(lane.key)} title={`${lane.title}交了什么：文件、回复、任务、每一次工具调用`}>
          {lane.writable.length ? '看产出' : '看评审报告'} ›
        </button>
      )}
    </div>
  )
}

function LiveClock({ base }: { base: number }) {
  const since = useSinceSnapshot()
  return <>{fmtClock(base + since)}</>
}

function Quiet({ at }: { at: number | null }) {
  const now = useServerNow()
  if (!at) return null
  return <>{fmtAgo(now - at).replace('前', '没动静')}</>
}

function Ago({ at }: { at: number | null }) {
  const now = useServerNow()
  if (!at) return null
  return <time>{fmtAgo(now - at)}</time>
}

/** What the lane is waiting for, or what is wrong with it: one loud line. */
function LaneSituation({ lane, run, onRole, onRetry }: { lane: Lane; run: RunDetail; onRole: (k: string) => void; onRetry?: (k: string) => void }) {
  const a = lane.agent
  switch (lane.status) {
    case 'waiting': {
      if (lane.awaiting_member) {
        return (
          <div className="kt-situation tone-warn">
            <strong>⏸ 没开工：Kiro Crew「代理」里还没有成员 {lane.awaiting_member}</strong>
            <span className="kt-deps">在「代理」→「添加团队成员」加上它（模板选同名），加上就自动开工</span>
          </div>
        )
      }
      const ups = waitingFor(lane, run.roles)
      return (
        <div className="kt-situation tone-idle">
          <strong>{waitingText(lane, run.roles)}</strong>
          {ups.length > 0 && (
            <span className="kt-deps">
              {ups.map((u) => (
                <button key={u.key} type="button" className={`kt-chip-role tone-${laneMeta(u).tone}`} onClick={() => onRole(u.key)} title={`只看${u.title}`}>
                  <RoleIcon role={u.icon || u.key} size={13} /> {u.title} · {laneMeta(u).label}
                </button>
              ))}
            </span>
          )}
        </div>
      )
    }
    case 'queued':
      return (
        <div className="kt-situation tone-queue">
          <strong>⏸ 排队：</strong>
          {a?.queued_reason ?? 'KiroCrew 还没让它开始'}
        </div>
      )
    case 'stalled':
      return (
        <div className="kt-situation tone-warn">
          <strong>⚠ 卡住：</strong>
          KiroCrew 标记它卡住了{a?.last_activity ? <>，<Quiet at={a.last_activity} /></> : null}
          {a?.last_tool ? `；最后在 ${a.last_tool}` : ''}
        </div>
      )
    case 'awaiting_approval':
      return (
        <div className="kt-situation tone-approve">
          <strong>✋ 等你批准：</strong>
          {a?.last_tool ?? '一个工具调用'}（去 KiroCrew 的审批里处理）
        </div>
      )
    case 'failed':
      return (
        <div className="kt-situation tone-bad">
          <strong>✕ 失败：</strong>
          {a?.error ?? '没有说明'}
          {onRetry && (
            <button type="button" className="kt-btn is-small is-danger kt-retry-btn" onClick={() => onRetry(lane.key)} title="再给它一轮：没合进去的从头做，合进去以后失败的接着修">
              ↻ 重试
            </button>
          )}
        </div>
      )
    case 'done':
      if (!lane.writable.length)
        return (
          <div className="kt-situation tone-ok">
            <strong>✔ 完成</strong>
            <span className="kt-summary">{lane.summary ?? '只读角色，不改文件'}</span>
          </div>
        )
      return (
        <div className="kt-situation tone-done">
          <strong>✓ 完成，等合并进运行分支</strong>
          {lane.summary ? <span className="kt-summary">{lane.summary}</span> : null}
        </div>
      )
    case 'merged':
      return (
        <div className="kt-situation tone-ok">
          <strong>✔ 交付</strong>
          <span className="kt-summary">{lane.summary ?? '分支已合进运行分支'}</span>
        </div>
      )
    default:
      return null
  }
}

function LiveWork({ lane, reducedMotion }: { lane: Lane; reducedMotion: boolean }) {
  const a = lane.agent
  const live = LIVE.has(lane.status)
  const working = WORKING.has(lane.status)
  const tail = useTypewriter(live ? (a?.text_tail ?? null) : null, reducedMotion)
  return (
    <>
      {lane.violations.map((v) => (
        <div key={v} className="kt-violation" role="alert">
          🚫 改了不属于它的 <code>{v}</code>
        </div>
      ))}
      {live && a?.last_tool && (
        <div className={`kt-ticker${working ? ' is-working' : ''}`} title="最近一次工具调用">
          <span className="kt-ticker-arrow" aria-hidden="true">
            ▸
          </span>
          <span className="kt-ticker-text kt-mono" key={a.last_tool}>
            {a.last_tool}
          </span>
          {working && <span className="kt-caret" aria-hidden="true" />}
        </div>
      )}
      {live && tail.shown && (
        <p className={`kt-tail${tail.fresh ? ' is-fresh' : ''}`} title="agent 正在写的内容（最后约 300 字）">
          <span>
            {tail.shown}
            {tail.typing && <span className="kt-caret" aria-hidden="true" />}
          </span>
        </p>
      )}
      {live && a && a.recent_tools.length > 0 && (
        <ol className="kt-tools" aria-label="最近的工具调用">
          {a.recent_tools.map((t, i) => (
            <li key={`${t.at}-${i}`} className={i === a.recent_tools.length - 1 ? 'is-last' : ''} title={`${t.tool}${t.detail ? `：${t.detail}` : ''}`}>
              <span aria-hidden="true">{toolIcon(t.kind, t.tool)}</span>
              <span className="kt-mono">{!t.detail ? t.tool : /\s/.test(t.detail) ? t.detail : baseName(t.detail)}</span>
              <Ago at={t.at} />
            </li>
          ))}
        </ol>
      )}
      {!live && lane.status !== 'merged' && lane.status !== 'done' && lane.summary && <p className="kt-summary">{lane.summary}</p>}
    </>
  )
}

/** One chip per acceptance criterion: red if any of its cases fails, the number of cases beside it. */
export function groupCases(cases: TestCase[]): { key: string; status: TestCase['status']; count: number; titles: string[] }[] {
  const groups = new Map<string, { key: string; status: TestCase['status']; count: number; titles: string[] }>()
  for (const c of cases) {
    const key = c.ac ?? c.name
    const g = groups.get(key) ?? { key, status: 'pass' as TestCase['status'], count: 0, titles: [] }
    g.count += 1
    g.titles.push(`${c.status === 'fail' ? '✗' : c.status === 'skip' ? '–' : '✓'} ${c.name}${c.message ? `：${c.message}` : ''}`)
    if (c.status === 'fail' || (c.status === 'skip' && g.status === 'pass')) g.status = c.status
    groups.set(key, g)
  }
  return [...groups.values()]
}

function Changes({ lane, run, followed, onOutputs }: { lane: Lane; run: RunDetail; followed: boolean; onOutputs?: (role: string, path?: string | null) => void }) {
  const files = lane.files.slice().sort((a, b) => b.added + b.removed - (a.added + a.removed))
  const scale = Math.max(1, ...files.map((f) => f.added + f.removed))
  const show = followed ? files : files.slice(0, 5)
  const violated = new Set(lane.violations)
  const cases = new Map(run.tests.cases.map((c) => [c.id, c]))
  const owned = groupCases(lane.owns_tests.map((id) => cases.get(id)).filter((c): c is NonNullable<typeof c> => !!c))
  const commits = lane.commits.slice().reverse()
  if (!lane.files.length && !commits.length && !owned.length) return <p className="kt-dim kt-nothing">还没有改动</p>
  return (
    <>
      {lane.files.length > 0 && (
        <div className="kt-files-head">
          <span>改动</span>
          <span className="kt-add">+{lane.lines.added}</span>
          <span className="kt-del">−{lane.lines.removed}</span>
          <span className="kt-dim">{lane.files.length} 个文件</span>
        </div>
      )}
      <ul className="kt-files">
        {show.map((f) => (
          <li key={f.path} className={violated.has(f.path) ? 'is-violation' : ''} title={`${f.path}  +${f.added} −${f.removed}${violated.has(f.path) ? '（越界：不在它能写的目录里）' : ''}`}>
            <span className={`kt-file-st is-${f.status}`}>{f.status}</span>
            {onOutputs && f.status !== 'D' ? (
              <button type="button" className="kt-file-path kt-file-open kt-mono" onClick={() => onOutputs(lane.key, f.path)} title={`打开 ${f.path}`}>
                {f.path}
              </button>
            ) : (
              <span className="kt-file-path kt-mono">{f.path}</span>
            )}
            <span className="kt-file-bar" aria-hidden="true">
              <i className="kt-bar-add" style={{ width: `${(f.added / scale) * 100}%` }} />
              <i className="kt-bar-del" style={{ width: `${(f.removed / scale) * 100}%` }} />
            </span>
            <span className="kt-file-num kt-mono">
              <span className="kt-add">+{f.added}</span>
              {f.removed > 0 && <span className="kt-del"> −{f.removed}</span>}
            </span>
          </li>
        ))}
        {lane.files.length > show.length && <li className="kt-more kt-dim">还有 {lane.files.length - show.length} 个文件</li>}
      </ul>
      {commits.length > 0 && (
        <ul className="kt-commits" aria-label="提交">
          {commits.slice(0, followed ? 8 : 2).map((c) => (
            <li key={c.sha}>
              <code>{c.sha}</code>
              <span>{c.subject}</span>
            </li>
          ))}
        </ul>
      )}
      {owned.length > 0 && (
        <div className="kt-owned" aria-label="它要负责变绿的测试">
          <span className="kt-dim">负责的测试</span>
          {owned.map((g) => (
            <span key={g.key} className={`kt-owned-case is-${g.status}`} title={g.titles.join('\n')}>
              {g.key} {caseMeta(g.status).glyph}
              {g.count > 1 && <sub>×{g.count}</sub>}
            </span>
          ))}
        </div>
      )}
    </>
  )
}
