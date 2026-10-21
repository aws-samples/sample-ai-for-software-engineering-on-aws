/**
 * aidlc-team page: the live mission control of the 8-role agent team.
 *
 * Polls GET /board every 2 s (board/useBoard.ts) and renders only that contract (types.ts): the
 * header with the live counters, the team graph (the hero, with the particle layer), the merge
 * conveyor, one lane per role, the test wall and the event feed. Each poll's snapshot is diffed
 * against the previous one (board/diff.ts): new events become particles and node flashes, changed
 * test cases flip, changed lanes and new merges get a one-time highlight. The first snapshot is
 * history and never animates.
 *
 * The default export is the app: one app bar (AppBar.tsx: the two views as tabs, and 投影 for both) over the CTO 视图
 * (cto/CtoView.tsx, the default) or this board; nav.ts says which the URL opens. A way into the board (BoardEntry) picks
 * its run and opens it at its gate, its replay, its 签字单 or 新需求.
 *
 * Click a role anywhere to look at that role only; 跟随 follows the most active lane; 投影 goes
 * fullscreen (the Fullscreen API, or a fixed overlay where it is not available) with bigger type and
 * no write actions (inside the app, 投影 is the app's: the page follows it). Reduced motion: nothing flies or pulses, states still change. 回放 (board/Replay.tsx) shows a
 * finished run again from its event log; while it plays the board's write actions are off and the polls do not animate.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useAppApi, useNavigate, type AppApi } from '@kirocrew/app-sdk'
import type { GateDecision, RunDetail, RoutePick } from './types'
import { Conveyor } from './board/Conveyor'
import type { BoardDiff } from './board/diff'
import type { Item } from './board/engine'
import { EventFeed } from './board/EventFeed'
import { LIVE, PHASES, POLL_MS, fmtClock, isRunActive, paths } from './board/format'
import { FolderPanel } from './board/Folder'
import { OutputsDrawer, type OutputsTarget } from './board/Outputs'
import { EmptyStart, ExpertStrip, GateDialog, Kpis, StartForm, StopConfirm, TopBar, type DeliveryPick, type GateAnswers, type PreviewFn } from './board/Header'
import { ClockContext, useReducedMotion, type SnapshotClock } from './board/hooks'
import { Lanes } from './board/Lanes'
import { layoutGraph, visibleGraph } from './board/layout'
import { BOARD_CSS } from './board/styles'
import { TeamGraph, phaseOfLane, type FlashMap } from './board/TeamGraph'
import { TestWall } from './board/TestWall'
import { errorText, useBoard } from './board/useBoard'
import { RoleIcon } from './board/RoleIcon'
import { KnowledgePanel } from './board/Knowledge'
import { SignOff } from './board/SignOff'
import { ReplayBar, useReplay } from './board/Replay'
import { CtoView } from './cto/CtoView'
import { ItemView } from './cto/ItemView'
import { AppBar, APP_CSS } from './AppBar'
import { KIT_CSS } from './kit'
import { filtersOf, parseView, searchOf, type BoardEntry, type CtoEntry, type CtoFilters, type ItemEntry, type View } from './nav'

interface Effects {
  run: string | null
  flips: Record<string, number>
  flashes: FlashMap
  bumps: Record<string, number>
  merges: ReadonlySet<string>
  fresh: ReadonlySet<number>
  announce: string
}

/** 填入预设意见: the note the team file suggests for a gate (by its label); the person can still write their own. */
const GATE_PRESETS: Record<string, string> = {
  方案: '批准。补充一条：库存少于 5 件时，列表和详情页的商品显示「仅剩 N 件」。',
}

const NO_EFFECTS: Effects = { run: null, flips: {}, flashes: {}, bumps: {}, merges: new Set(), fresh: new Set(), announce: '' }

/** Fold one poll's diff into the one-shot effects (each counter is a key that replays an animation). */
export function applyDiff(f: Effects, d: BoardDiff): Effects {
  if (d.first || f.run !== d.run) return { ...NO_EFFECTS, run: d.run }
  const flips = { ...f.flips }
  for (const x of d.flips) flips[x.id] = (flips[x.id] ?? 0) + 1
  const flashes = { ...f.flashes }
  for (const x of d.flashes) flashes[x.target] = { n: (flashes[x.target]?.n ?? 0) + 1, tone: x.tone }
  const bumps = { ...f.bumps }
  for (const x of d.lanes) bumps[x.key] = (bumps[x.key] ?? 0) + 1
  return { run: d.run, flips, flashes, bumps, merges: new Set(d.merges), fresh: new Set(d.fresh.map((e) => e.seq)), announce: d.announce ?? f.announce }
}

/** The lane follow mode looks at: the live one that did something last, else the newest event's role. */
export function mostActive(run: RunDetail): string | null {
  let best: string | null = null
  let bestAt = -Infinity
  for (const l of run.roles) {
    if (!LIVE.has(l.status) && l.status !== 'queued') continue
    const at = l.agent?.last_activity ?? l.agent?.started ?? l.started_at ?? 0
    if (at > bestAt) {
      bestAt = at
      best = l.key
    }
  }
  if (best) return best
  for (let i = run.events.length - 1; i >= 0; i--) {
    const r = run.events[i].role
    if (r && run.roles.some((l) => l.key === r)) return r
  }
  return null
}

/** Structure only: the graph is laid out again only when roles or edges change, never per poll. */
const structureKey = (run: RunDetail) => `${run.roles.map((l) => `${l.key}${l.status === 'skipped' ? '-' : ''}<${l.depends_on.join(',')}`).join(';')}|${run.edges.map((e) => e.join('>')).join(';')}|${(run.roster ?? []).map((p) => p.key).join(',')}`

type TeamPageProps = {
  pollMs?: number
  entry?: BoardEntry
  /** back to the CTO 视图 (with this run's delivery picked out) */
  onCto?: (e?: CtoEntry) => void
  /** this run's 交付详情 */
  onItem?: (e: ItemEntry) => void
  /** the run the board shows (the app's 交付详情 tab opens it) */
  onRun?: (rid: string) => void
  /** ← 返回: back to the view the board was opened from (its entry says from=…) */
  onBack?: () => void
  /** a run picked in the board's picker: the URL's entry says that run now */
  onPick?: (rid: string) => void
  /** opened again by back or forward: the app puts the page back where it was left, so it does not scroll here */
  returning?: boolean
  /** inside the app: 投影 is the app's (its bar has the button); the page follows it and asks it to end (Esc) */
  projection?: boolean
  onProjection?: (on: boolean) => void
}

export function TeamPage({ pollMs = POLL_MS, entry, onCto, onItem, onRun, onBack, onPick, returning = false, projection: appProjection, onProjection }: TeamPageProps = {}) {
  const api = useAppApi()
  const reducedMotion = useReducedMotion()
  const [selected, setSelected] = useState<string | null>(entry?.run ?? null)
  const [focus, setFocus] = useState<string | null>(entry?.gate ?? entry?.role ?? null)
  const [phase, setPhase] = useState<string | null>(entry?.phase ? phaseOfLane(entry.phase) : null)
  const [follow, setFollow] = useState(false)
  const [ownProjection, setProjection] = useState(false)
  const inApp = appProjection !== undefined
  const projection = inApp ? appProjection : ownProjection
  const [startOpen, setStartOpen] = useState(!!entry?.new)
  const [stopAsk, setStopAsk] = useState(false)
  const [gateAsk, setGateAsk] = useState<{ role: string; decision: GateDecision } | null>(null)
  const [outputs, setOutputs] = useState<OutputsTarget | null>(null)
  const [retryErr, setRetryErr] = useState('')
  const [folderOpen, setFolderOpen] = useState(false)
  const [fx, setFx] = useState<Effects>(NO_EFFECTS)
  const feed = useRef<((items: Item[]) => void) | null>(null)
  const rootRef = useRef<HTMLDivElement | null>(null)
  const native = useRef(false)

  const replaying = useRef(false)
  const animate = useCallback((d: BoardDiff) => {
    if (d.items.length) feed.current?.(d.items)
    setFx((f) => applyDiff(f, d))
  }, [])
  // while a replay plays, the animations are the replay's; the polls of the finished run change nothing anyway
  const onDiff = useCallback((d: BoardDiff) => void (replaying.current || animate(d)), [animate])
  const { board, error, missing, loading, receivedAt, reload } = useBoard(api, { run: selected, pollMs, onDiff })
  const rp = useReplay(api, board?.run ?? null, animate)
  replaying.current = !!rp.id
  const inReplay = !!rp.run
  const run = rp.run ?? board?.run ?? null
  useEffect(() => setFx(NO_EFFECTS), [rp.id])
  // the way in: once the board shows the run asked for, its replay starts (at a moment of a finished run: paused there),
  // or the page goes to its 签字单, its 测试墙, its counters, or the team graph (a gate, a role, a phase)
  const entered = useRef(false)
  const moment = useRef(false)
  useEffect(() => {
    if (entered.current || !entry?.run || board?.run?.id !== entry.run) return
    entered.current = true
    moment.current = !isRunActive(board.run.status) && (entry.at !== undefined || !!entry.phase)
    if (entry.replay || moment.current) rp.start()
    const where = entry.focus === 'signoff' ? '#kt-signoff' : entry.focus === 'tests' ? '[data-testid="kt-wall"]' : entry.focus === 'cost' ? '.kt-kpis' : entry.focus === 'lanes' ? '[data-testid="kt-lanes"]'
      : entry.gate || entry.role || entry.phase || moment.current ? '[data-testid="kt-graph"]' : ''
    if (where && !returning) setTimeout(() => rootRef.current?.querySelector(where)?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50)
  }, [board?.run?.id]) // eslint-disable-line react-hooks/exhaustive-deps
  const sped = useRef(false)
  useEffect(() => {  // once the replay's events are in (its span known)
    if (!rp.id || !rp.span || sped.current) return
    sped.current = true
    if (entry?.replay) rp.setSpeed(entry.replay)
    if (!moment.current || !board?.run || !rp.span) return
    const r = board.run, span = rp.span
    let t: number | null = entry?.at !== undefined ? r.started_at + entry.at : null
    if (t === null && phase) {  // a phase: where its first role was set to work
      const ts = r.roles.filter((l) => phaseOfLane(l.phase) === phase && l.started_at).map((l) => l.started_at as number)
      t = ts.length ? Math.min(...ts) : null
    }
    if (t !== null) {
      rp.seek(Math.max(span.start, Math.min(t, span.end)))
      if (!entry?.replay) rp.pause()
    }
    // the replay bar came in above the graph: look at the graph again once the board has its moment
    if (!returning) setTimeout(() => rootRef.current?.querySelector(entry?.focus === 'signoff' ? '#kt-signoff' : '[data-testid="kt-graph"]')?.scrollIntoView?.({ behavior: 'smooth', block: 'start' }), 200)
  }, [rp.id, rp.span]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (board?.run?.id) onRun?.(board.run.id)
  }, [board?.run?.id]) // eslint-disable-line react-hooks/exhaustive-deps
  // a picked run that the board no longer has (run: null although runs exist): back to the default
  useEffect(() => {
    if (board && !board.run && board.runs.length > 0 && selected) setSelected(null)
  }, [board, selected])

  const structure = run ? structureKey(run) : ''
  // laid out again only when the structure changes, not on every snapshot
  const lay = useMemo(() => {
    if (!run) return null
    const shown = visibleGraph(run.roles, run.edges) // a role sitting this run out is not in the flow
    return layoutGraph(shown.roles, shown.edges, run.roster)
  }, [structure])
  const liveClock: SnapshotClock = useMemo(() => ({ at: board?.at ?? Date.now() / 1000, receivedAt: receivedAt || Date.now() }), [board?.at, receivedAt])
  const clock = rp.clock ?? liveClock

  const onRole = useCallback((key: string) => setFocus((f) => (f === key ? null : key)), [])
  const followKey = follow && run ? mostActive(run) : null

  const enterProjection = useCallback(async () => {
    if (inApp) return onProjection?.(true)
    setProjection(true)
    const el = rootRef.current
    if (el && typeof el.requestFullscreen === 'function' && !document.fullscreenElement) {
      try {
        await el.requestFullscreen()
        native.current = true
      } catch {
        native.current = false // the fixed overlay (CSS) stands in
      }
    }
  }, [inApp, onProjection])
  const exitProjection = useCallback(async () => {
    if (inApp) return onProjection?.(false)
    setProjection(false)
    const wasNative = native.current
    native.current = false
    if (wasNative && document.fullscreenElement && typeof document.exitFullscreen === 'function') {
      try {
        await document.exitFullscreen()
      } catch {
        /* already out */
      }
    }
  }, [inApp, onProjection])
  useEffect(() => {
    const onFs = () => {
      if (!document.fullscreenElement && native.current) {
        native.current = false
        setProjection(false)
      }
    }
    document.addEventListener('fullscreenchange', onFs)
    return () => document.removeEventListener('fullscreenchange', onFs)
  }, [])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      if (outputs) setOutputs(null)
      else if (projection) void exitProjection()
      else {
        setFocus(null)
        setPhase(null)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [projection, exitProjection, outputs])

  const start = useCallback(
    async (requirement: string, opts?: { source?: string; team?: string }) => {
      const body: Record<string, string> = {}
      if (requirement) body.requirement = requirement
      if (opts?.source) body.source = opts.source
      if (opts?.team) body.team = opts.team
      const res = await api.post<{ run?: string } | null>(paths.runs(), body)
      const id = typeof res?.run === 'string' ? res.run : null
      setStartOpen(false)
      setFocus(null)
      // the new run, or (no id in the answer) the backend's default: the newest active run
      setSelected(id)
      reload()
    },
    [api, reload],
  )
  const stop = useCallback(async () => {
    if (!run) return
    await api.post(paths.stop(run.id), {})
    setStopAsk(false)
    reload()
  }, [api, run, reload])

  const pickRun = useCallback((id: string) => {
    setSelected(id)
    setFocus(null)
    setPhase(null)
    setStopAsk(false)
    setOutputs(null)
    onPick?.(id)
  }, [onPick])
  const openOutputs = useCallback((role: string, path?: string | null) => setOutputs({ role, path: path ?? null }), [])
  const retry = useCallback(
    async (role?: string) => {
      if (!run) return
      setRetryErr('')
      try {
        await api.post(paths.retry(run.id), role ? { roles: [role] } : {})
      } catch (e) {
        setRetryErr(errorText(e))
      }
      reload()
    },
    [api, run, reload],
  )

  const gate = useCallback(
    async (note: string, delivery?: DeliveryPick, answers?: GateAnswers) => {
      if (!run || !gateAsk) return
      await api.post(paths.gate(run.id), { role: gateAsk.role, decision: gateAsk.decision, note, ...(delivery ? { delivery } : {}), ...(answers ? { answers } : {}) })
      setGateAsk(null)
      reload()
    },
    [api, run, gateAsk, reload],
  )
  const gateLane = gateAsk && run ? run.roles.find((l) => l.key === gateAsk.role) : undefined
  // at a writing role's gate, the documents of its stage (the 启动 gate: architecture, interfaces, design, acceptance)
  const gateDocs = gateLane && run && gateLane.writable.length > 0
    ? run.roles.filter((l) => l.phase === gateLane.phase && l.writable.length > 0 && (l.status === 'merged' || l.key === gateLane.key))
      .map((l) => ({ key: l.key, title: l.title, icon: l.icon, onOpen: () => openOutputs(l.key) }))
    : []
  const sign = useCallback(
    async (by: string, note: string) => {
      if (!run) return
      await api.post(paths.signoff(run.id), { by, note })
      reload()
    },
    [api, run, reload],
  )
  const preview = useCallback<PreviewFn>((requirement) => api.post<RoutePick>(paths.route(), { requirement }), [api])
  const hide = useCallback(
    async (id: string) => {
      await api.post(paths.hide(id), {})
      setSelected(null)
      reload()
    },
    [api, reload],
  )
  const [cleanupMsg, setCleanupMsg] = useState('')
  const cleanup = useCallback(async () => {
    setCleanupMsg('正在清理…')
    try {
      const r = await api.post<{ sessions: number; folders: number }>(paths.cleanup(), {})
      setCleanupMsg(`清理了 ${r.sessions} 个已结束的会话，收起了 ${r.folders} 个空文件夹`)
    } catch (e) {
      setCleanupMsg(errorText(e))
    }
  }, [api])

  return (
    <div
      ref={rootRef}
      className={`kt-root${projection ? ' is-projection' : ''}${follow ? ' is-following' : ''}${run && isRunActive(run.status) ? ' is-live' : ''}`}
      data-testid="kt-root"
      data-projection={projection ? 'true' : undefined}
      data-motion={reducedMotion ? 'reduce' : undefined}
    >
      <style>{BOARD_CSS}</style>
      <style>{KIT_CSS}</style>
      <ClockContext.Provider value={clock}>
        {!projection && run && entry?.from && run.id === entry.run && (
          <WhereBar run={run} entry={entry} phase={phase} focus={focus} replayAt={rp.id && rp.span ? rp.t - rp.span.start : null} playing={rp.playing}
            onCto={onCto ? () => onCto({ hl: run.id }) : undefined} onItem={onItem ? () => onItem({ run: run.id }) : undefined} onBack={onBack} />
        )}
        <TopBar
          board={board}
          run={run}
          projection={projection}
          follow={follow}
          startOpen={startOpen}
          onSelect={pickRun}
          onProjection={inApp ? undefined : () => void (projection ? exitProjection() : enterProjection())}
          onFollow={() => setFollow((v) => !v)}
          onStart={() => setStartOpen((v) => !v)}
          onStop={() => setStopAsk(true)}
          onOutputs={(t) => setOutputs(t)}
          onRetry={() => void retry()}
          onFolder={() => setFolderOpen((v) => !v)}
          onCleanup={() => void cleanup()}
          onHide={(id) => void hide(id)}
          onReplay={rp.start}
          inApp={inApp}
          onItem={onItem}
          replaying={!!rp.id}
          folderOpen={folderOpen}
        />
        {rp.id && <ReplayBar rp={rp} projection={projection} />}
        {!projection && cleanupMsg && (
          <p className="kt-dim kt-cleanup-msg" role="status" onClick={() => setCleanupMsg('')}>
            {cleanupMsg}
          </p>
        )}
        {!projection && folderOpen && run && <FolderPanel api={api} run={run.id} folder={run.folder} onClose={() => setFolderOpen(false)} />}
        {retryErr && (
          <div className="kt-banner is-error" role="alert">
            重试没成：{retryErr}
          </div>
        )}
        {error && (
          <div className="kt-banner" role="status">
            {missing ? '后端还没有看板接口（GET /board 回 404）' : `看板刷新失败：${error}`}
            {board ? '，显示的是上一次拿到的数据' : ''}
          </div>
        )}
        {!board && loading && <p className="kt-loading">正在连接看板…</p>}
        {!projection && !inReplay && startOpen && run && <StartForm onStart={start} preview={preview} onCancel={() => setStartOpen(false)} />}
        {!projection && !inReplay && stopAsk && run && <StopConfirm run={run} onConfirm={stop} onCancel={() => setStopAsk(false)} />}
        {gateAsk && run && <GateDialog key={`${gateAsk.role}-${gateAsk.decision}-${gateLane?.talk.length ?? 0}`} label={gateLane?.gate_label || gateLane?.title || gateAsk.role} who={gateLane?.title} questions={gateLane?.questions} talk={gateLane?.talk} outputs={gateDocs.length > 1 ? gateDocs : []} decision={gateAsk.decision} preset={gateAsk.decision === 'discuss' ? undefined : (gateAsk.decision === 'revise' ? gateLane?.gate_revise_preset : gateLane?.gate_preset) || GATE_PRESETS[gateLane?.gate_label || '']} split={gateLane && gateLane.writable.length === 0 ? undefined : run.roles.filter((l) => l.key !== gateAsk.role && l.status !== 'skipped' && !(l.key in run.plan_skip)).map((l) => ({ key: l.key, title: l.title, icon: l.icon, assignment: l.assignment }))} skips={gateLane && gateLane.writable.length > 0 ? Object.entries(run.plan_skip).map(([k, why]) => ({ key: k, title: run.roles.find((l) => l.key === k)?.title ?? k, why })) : undefined} overrule={gateLane?.overrule} delivery={gateLane?.delivery_gate && gateAsk.decision === 'approve' ? run.delivery : undefined} report={gateLane && gateLane.writable.length === 0 ? gateLane.summary || '' : undefined} onReport={gateLane && gateLane.writable.length === 0 ? () => openOutputs(gateLane.key) : undefined} onConfirm={gate} onCancel={() => setGateAsk(null)} />}
        {board && !run && board.runs.length === 0 && <EmptyStart onStart={start} preview={preview} />}
        {run && lay && (
          <>
            <Kpis key={`${run.id}${inReplay ? ':replay' : ''}`} run={run} reducedMotion={reducedMotion} onRole={onRole} />
            {run.roles.some((l) => l.phase) && <ExpertStrip run={run} />}
            <KnowledgePanel run={run} onRole={onRole} />
            {!isRunActive(run.status) && run.tests.total > 0 && <SignOff run={run} onSign={sign} onCto={onCto ? () => onCto({ hl: run.id }) : undefined} onItem={onItem ? () => onItem({ run: run.id }) : undefined} />}
            <div className="kt-body">
              <div className="kt-col">
                <TeamGraph key={`${run.id}${inReplay ? ':replay' : ''}`} run={run} lay={lay} focus={focus} onRole={onRole} flashes={fx.flashes} reducedMotion={reducedMotion} feed={feed} onRetry={projection || inReplay || run.imported ? undefined : (k) => void retry(k)} onGate={inReplay ? undefined : (k, d) => setGateAsk({ role: k, decision: d })} quiet={projection} onOutputs={(k) => openOutputs(k)} phase={phase} onPhase={(p) => { setFocus(null); setPhase((x) => (x === p ? null : p)) }} />
                {focus && <FocusBar run={run} focus={focus} onClear={() => setFocus(null)} onItem={onItem ? () => onItem({ run: run.id, at: momentAt(run, rp, { role: focus }) }) : undefined} />}
                {!focus && phase && <PhaseBar run={run} phase={phase} onClear={() => setPhase(null)} onItem={onItem ? () => onItem({ run: run.id, at: momentAt(run, rp, { phase }) }) : undefined} />}
                {/* on a projector the rail of the graph carries the merges; the space goes to the lanes */}
                {!projection && <Conveyor run={run} fresh={fx.merges} focus={focus} onRole={onRole} />}
                <Lanes run={run} focus={focus} phase={phase} follow={followKey} bumps={fx.bumps} onRole={onRole} reducedMotion={reducedMotion} projection={projection} onOutputs={openOutputs} onRetry={projection || inReplay || run.imported ? undefined : (k) => void retry(k)} />
              </div>
              <aside className="kt-side" aria-label="测试和事件">
                <TestWall tests={run.tests} roles={run.roles} focus={focus} onRole={onRole} flips={fx.flips} />
                <EventFeed run={run} focus={focus} onRole={onRole} fresh={fx.fresh} milestones={projection} />
              </aside>
            </div>
          </>
        )}
        {run && outputs && <OutputsDrawer api={api} run={run} target={outputs} onTarget={setOutputs} onClose={() => setOutputs(null)} />}
        <div className="kt-sr" aria-live="polite" data-testid="kt-announce">
          {fx.announce}
        </div>
      </ClockContext.Provider>
    </div>
  )
}

/** The moment the board is looking at, in seconds from the run's start: the replay's, else where the phase or role began. */
function momentAt(run: RunDetail, rp: { id: string | null; t: number }, at: { phase?: string; role?: string }): number | undefined {
  if (rp.id) return Math.max(0, Math.round(rp.t - run.started_at))
  const lanes = run.roles.filter((l) => l.started_at && (at.role ? l.key === at.role : phaseOfLane(l.phase) === at.phase))
  return lanes.length ? Math.max(0, Math.round(Math.min(...lanes.map((l) => l.started_at as number)) - run.started_at)) : undefined
}

const FOCUS_NAME: Record<string, string> = { signoff: '签字单', tests: '测试墙', cost: '指标', lanes: '各成员泳道' }

/** Where the board is when another view opened it: CTO 视图 › the delivery › 团队看板 · its phase or gate · the replay's
 * moment; why this run when the newest 实测 stood in; and ← 返回 to the view it came from. */
function WhereBar({ run, entry, phase, focus, replayAt, playing, onCto, onItem, onBack }: {
  run: RunDetail; entry: BoardEntry; phase: string | null; focus: string | null; replayAt: number | null; playing: boolean
  onCto?: () => void; onItem?: () => void; onBack?: () => void
}) {
  const lane = focus ? run.roles.find((l) => l.key === focus) : undefined
  const ph = phase ? PHASES.find((x) => x.key === phase) : undefined
  const parts = [
    ph ? `${ph.title}阶段` : '',
    lane ? (lane.gate_label ? `${lane.gate_label}关卡` : lane.title) : '',
    entry.focus ? FOCUS_NAME[entry.focus] : '',
    replayAt !== null ? `回放 ${fmtClock(replayAt)}${playing ? '' : '（暂停）'}` : '',
  ].filter(Boolean)
  const why = entry.pick !== 'latest' ? ''
    : entry.phase ? `此刻没有运行在「${ph?.title ?? entry.phase}」这一列，这里打开的是最近一次实测。`
      : entry.gate ? '此刻没有运行停在人的关卡上，这里打开的是最近一次实测的第一个关卡。'
        : '此刻没有 agent 在做的运行，这里回放的是最近一次实测。'
  return (
    <nav className="kit-crumb kt-where" aria-label="位置" data-testid="kt-where">
      {onCto ? <button type="button" onClick={onCto}>CTO 视图</button> : <span>CTO 视图</span>}
      <span aria-hidden="true">›</span>
      {onItem ? <button type="button" onClick={onItem} title="这次交付的交付详情">{run.delivery?.name || run.title}</button> : <span>{run.delivery?.name || run.title}</span>}
      <span aria-hidden="true">›</span>
      <b>团队看板{parts.length ? ` · ${parts.join(' · ')}` : ''}</b>
      {why && <span className="kt-where-why">{why}</span>}
      <span className="kt-grow" />
      {onBack && <button type="button" className="kt-btn" onClick={onBack}>← 返回{entry.from === 'item' ? '交付详情' : ' CTO 视图'}</button>}
    </nav>
  )
}

/** A phase picked out on the board: which, how many roles, and its segment of the 价值流 on the 交付详情. */
function PhaseBar({ run, phase, onClear, onItem }: { run: RunDetail; phase: string; onClear: () => void; onItem?: () => void }) {
  const p = PHASES.find((x) => x.key === phase)
  const n = run.roles.filter((l) => l.status !== 'skipped' && phaseOfLane(l.phase) === phase).length
  return (
    <div className="kt-focuschip" role="status" data-testid="kt-phasebar">
      {p ? `${p.n} ${p.title}` : phase} · {n} 个角色
      {onItem && <button type="button" className="kt-chip-link" onClick={onItem}>这次交付的价值流 ↗</button>}
      <button type="button" onClick={onClear} aria-label="看全部" title="看全部（Esc）">
        ✕
      </button>
    </div>
  )
}

function FocusBar({ run, focus, onClear, onItem }: { run: RunDetail; focus: string; onClear: () => void; onItem?: () => void }) {
  const lane = run.roles.find((l) => l.key === focus)
  if (!lane) return null
  return (
    <div className="kt-focuschip" role="status" data-testid="kt-focusbar">
      <RoleIcon role={lane.icon || lane.key} size={14} /> {lane.title}
      {onItem && <button type="button" className="kt-chip-link" onClick={onItem}>这次交付的价值流 ↗</button>}
      <button type="button" onClick={onClear} aria-label="看全部" title="看全部（Esc）">
        ✕
      </button>
    </div>
  )
}

/** The app: its bar, then the CTO 视图 (the default), a 交付详情 or the board, as the URL says (nav.ts). A move to another
 * view is a history entry made through the host's router (useNavigate), so Kiro Crew's ← → (and ⌘←), like the browser's
 * back and forward, step between views, and every entry can be linked to; a change inside a view (a CTO filter, the run picked on the board) rewrites the current entry. Leaving the
 * CTO view first writes the delivery left from into its entry (`hl`), so coming back picks it out again with its filters.
 * Each entry also keeps how far the page was scrolled (`ktScroll` in its state): back or forward puts the page there again
 * once the view has its content (unless the reader scrolls first).
 * The delivery in hand (the last 交付详情, or the board's run) is what the 交付详情 tab opens. 投影 is the app's: full
 * screen (the Fullscreen API on the app, a fixed overlay where it is refused) stays on across views. */
export default function AidlcTeamApp({ pollMs }: { pollMs?: number } = {}) {
  const [view, setView] = useState<View & { n: number; returning?: boolean }>(() => ({ ...parseView(window.location.search), n: 0 }))
  const [ctx, setCtx] = useState<ItemEntry>(() => ctxOf(parseView(window.location.search), {}))
  const [projection, setProjection] = useState(false)
  const navigate = useNavigate()
  const rootRef = useRef<HTMLDivElement | null>(null)
  const current = useRef<View>(parseView(window.location.search)) // what the current history entry says
  const restore = useRef<number | null>(null) // back or forward: the scroll to put the page back at
  const ctoFilters = useRef<CtoFilters>(current.current.kind === 'cto' ? filtersOf(current.current) : {})
  const remember = useCallback((v: View) => {
    current.current = v
    if (v.kind === 'cto') ctoFilters.current = filtersOf(v)
    setCtx((c) => ctxOf(v, c))
  }, [])
  const href = (v: View) => `${window.location.pathname}${searchOf(v)}`
  const depth = () => Number((window.history.state as { ktDepth?: number } | null)?.ktDepth ?? 0)
  // what scrolls the page: the app in 投影, else the host's scroll box around it
  const scroller = useCallback((): Element | null => {
    const root = rootRef.current
    if (!root) return null
    const own = root.querySelector(':scope > .kt-root')
    if (own && own.scrollHeight > own.clientHeight && /auto|scroll/.test(getComputedStyle(own).overflowY)) return own
    for (let e = root.parentElement; e; e = e.parentElement) {
      if (e.scrollHeight > e.clientHeight && /auto|scroll/.test(getComputedStyle(e).overflowY)) return e
    }
    return document.scrollingElement
  }, [])
  const keepScroll = useCallback(() => {
    try {
      window.history.replaceState({ ...(window.history.state ?? {}), ktScroll: Math.round(scroller()?.scrollTop ?? 0) }, '', window.location.href)
    } catch {
      /* too many rewrites in a short time (Safari): the last one stands */
    }
  }, [scroller])
  // a change inside the view: the same history entry, rewritten; the view is not opened again
  const replace = useCallback((v: View) => {
    remember(v)
    window.history.replaceState({ ...(window.history.state ?? {}), ktDepth: depth() }, '', href(v))
  }, [remember])
  // a move to another view: a new history entry, made by the host's router (so its ← → know about it); the entry then
  // says how many moves deep into the app it is (the router may make it a moment later)
  const go = useCallback((v: View) => {
    const from = current.current
    if (from.kind === 'cto' && v.kind !== 'cto') {
      const key = v.kind === 'item' ? v.run ?? v.issue : v.run
      if (key) replace({ ...from, hl: key, at: undefined })
    }
    keepScroll()
    const d = depth() + 1, to = href(v)
    remember(v)
    setView((cur) => ({ ...v, n: cur.n + 1 }))
    navigate(to)
    const mark = () => {
      const st = window.history.state as { ktDepth?: number } | null
      if (`${window.location.pathname}${window.location.search}` === to && st?.ktDepth === undefined) window.history.replaceState({ ...(st ?? {}), ktDepth: d }, '', to)
    }
    mark()
    setTimeout(mark, 0)
    setTimeout(mark, 60)
  }, [remember, replace, keepScroll, navigate])
  // back and forward: the view the entry says, scrolled where it was left
  useEffect(() => {
    const onPop = () => {
      const v = parseView(window.location.search)
      const top = (window.history.state as { ktScroll?: number } | null)?.ktScroll
      restore.current = typeof top === 'number' && top > 0 ? top : null
      remember(v)
      setView((cur) => ({ ...v, n: cur.n + 1, returning: restore.current !== null }))
    }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [remember])
  // the entry keeps its scroll as the reader leaves it scrolled (once the scrolling stops: rewrites are rate-limited)
  useEffect(() => {
    let t: ReturnType<typeof setTimeout> | undefined
    const onScroll = (e: Event) => {
      const el = scroller()
      if (e.target !== el && !(e.target === document && el === document.scrollingElement)) return
      clearTimeout(t)
      t = setTimeout(keepScroll, 300)
    }
    window.addEventListener('scroll', onScroll, { capture: true, passive: true })
    return () => {
      clearTimeout(t)
      window.removeEventListener('scroll', onScroll, { capture: true })
    }
  }, [scroller, keepScroll])
  useEffect(() => {  // the view that just opened starts at its top (the host page scrolls, not this app) …
    if (!view.n) return
    document.querySelector(projection ? '[data-testid="kt-app"] > .kt-root' : '[data-testid="kt-app"]')?.scrollIntoView?.({ block: 'start' })
    const top = restore.current
    restore.current = null
    const el = scroller()
    if (top === null || !el) return
    // … or, back or forward, where it was left: once the content is long enough (its data comes in), and held there while
    // the layout still settles (a replay coming in above shifts it), until it has been still for 0.6 s — within 4 s
    let tries = 0, still = 0
    const timer = setInterval(() => {
      const reach = el.scrollHeight - el.clientHeight >= top
      if (reach && Math.abs(el.scrollTop - top) > 2) {
        el.scrollTop = top
        still = 0
      } else if (reach) still += 1
      if (still >= 6) stop()
      else if (++tries >= 40) {
        el.scrollTop = top
        stop()
      }
    }, 100)
    const stop = () => {
      clearInterval(timer)
      for (const k of ['wheel', 'touchstart', 'keydown'] as const) window.removeEventListener(k, stop)
    }
    for (const k of ['wheel', 'touchstart', 'keydown'] as const) window.addEventListener(k, stop, { passive: true })
    return stop
  }, [view.n]) // eslint-disable-line react-hooks/exhaustive-deps
  const project = useCallback(async (on: boolean) => {
    setProjection(on)
    const el = rootRef.current
    try {
      if (on && el && typeof el.requestFullscreen === 'function' && !document.fullscreenElement) await el.requestFullscreen()
      if (!on && document.fullscreenElement && typeof document.exitFullscreen === 'function') await document.exitFullscreen()
    } catch {
      /* the fixed overlay (APP_CSS) stands in */
    }
  }, [])
  useEffect(() => {
    const onFs = () => !document.fullscreenElement && setProjection(false)
    document.addEventListener('fullscreenchange', onFs)
    return () => document.removeEventListener('fullscreenchange', onFs)
  }, [])
  const onProjection = useCallback((on: boolean) => void project(on), [project])
  // coming back to the CTO view brings back its filters
  const toCto = useCallback((e: CtoEntry = {}) => go({ kind: 'cto', ...ctoFilters.current, ...e }), [go])
  // 交付详情 says which view it was opened from too (another 交付详情 is not a way back: the CTO view is)
  const toItem = useCallback((e: ItemEntry) => {
    const from = current.current.kind
    go({ kind: 'item', ...e, ...(!e.from && from !== 'item' ? { from } : {}) })
  }, [go])
  // the board says which view it was opened from (and how to go back there)
  const toBoard = useCallback((e: BoardEntry) => {
    const from = current.current.kind
    go({ kind: 'board', ...e, ...(e.run && !e.from && from !== 'board' ? { from } : {}) })
  }, [go])
  // ← 返回 (the board, 交付详情): the entry before, when this app made it; else the view it came from
  const back = useCallback((fallback: View) => (depth() > 0 ? window.history.back() : go(fallback)), [go])
  // the run the board shows is the delivery in hand; a run picked in its picker is what its entry says (without what a
  // link opened the board at)
  const onRun = useCallback((rid: string) => setCtx((c) => (c.run === rid ? c : { run: rid })), [])
  const onPick = useCallback((rid: string) => replace({ kind: 'board', run: rid }), [replace])
  const onCtoState = useCallback((f: CtoFilters & { hl?: string }) => replace({ kind: 'cto', ...f }), [replace])
  let body
  if (view.kind === 'board') {
    const { kind: _k, n, returning, ...entry } = view
    body = <TeamPage key={n} pollMs={pollMs} entry={entry} returning={returning} onCto={(e) => toCto(e)} onItem={toItem} onRun={onRun} onPick={onPick} projection={projection} onProjection={onProjection}
      onBack={entry.from ? () => back(entry.from === 'item' ? { kind: 'item', run: entry.run } : { kind: 'cto', ...ctoFilters.current, hl: entry.run }) : undefined} />
  } else if (view.kind === 'item') {
    const { kind: _k, n, returning, ...entry } = view
    body = <ItemView key={n} entry={entry} returning={returning} onCto={toCto}
      onBack={entry.from ? () => back(entry.from === 'board' ? { kind: 'board', run: entry.run } : { kind: 'cto', ...ctoFilters.current, hl: entry.run ?? entry.issue }) : undefined} onItem={toItem} onBoard={toBoard} projection={projection} pollMs={pollMs} />
  } else {
    const { kind: _k, n, returning, ...entry } = view
    body = <CtoView key={n} entry={entry} returning={returning} onOpen={toBoard} onItem={toItem} onState={onCtoState} projection={projection} onProjection={onProjection} />
  }
  return (
    <div ref={rootRef} className={`kt-app${projection ? ' is-projection' : ''}`} data-testid="kt-app">
      <style>{APP_CSS}</style>
      <AppBar view={view.kind} projection={projection} item={ctx.run ?? ctx.issue}
        onView={(k) => (k === 'item' ? toItem({ run: ctx.run, issue: ctx.issue }) : k === 'board' ? toBoard(ctx.run ? { run: ctx.run } : {}) : toCto(ctx.run || ctx.issue ? { hl: ctx.run ?? ctx.issue } : {}))}
        onProjection={() => onProjection(!projection)} />
      {body}
    </div>
  )
}

/** The delivery in hand after a move to *v*: the 交付详情 it is, or the board's run; else the one before. */
function ctxOf(v: View, before: ItemEntry): ItemEntry {
  if (v.kind === 'item') return v.run === before.run && v.issue === before.issue ? before : { run: v.run, issue: v.issue }
  if (v.kind === 'board' && v.run) return before.run === v.run ? before : { run: v.run }
  return before
}
