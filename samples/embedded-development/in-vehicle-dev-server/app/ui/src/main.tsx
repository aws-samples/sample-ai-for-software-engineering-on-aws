/**
 * vstatd-team page: the live mission control of the vstatd team (team/team-vstatd.json).
 *
 * Polls GET /board every 2 s (board/useBoard.ts) and renders only that contract (types.ts): the
 * header with the live counters, the flow strip (board/FlowStrip.tsx) and 人机分工 under it (board/DivisionGrid.tsx), the team
 * graph (the hero, with the particle layer) beside the test wall and the bench, the merge conveyor once there is a merge,
 * one lane per role, 需求清单 and 知识库 (folded), the event feed and the 审计记录 (board/Audit.tsx). Each poll's snapshot is diffed
 * against the previous one (board/diff.ts): new events become particles and node flashes, changed
 * test cases flip, changed lanes and new merges get a one-time highlight. The first snapshot is
 * history and never animates.
 *
 * The default export is the app: one app bar (AppBar.tsx: the views as tabs, and 投影) over this board; nav.ts says
 * what the URL opens. A way into the board (BoardEntry) picks its run and opens it at its gate, its replay, its 签字单
 * or 新需求.
 *
 * Click a role anywhere to look at that role only; 跟随 follows the most active lane; 投影 goes
 * fullscreen (the Fullscreen API, or a fixed overlay where it is not available) with bigger type and
 * no write actions (inside the app, 投影 is the app's: the page follows it). Reduced motion: nothing flies or pulses, states still change. 回放 (board/Replay.tsx) shows a
 * finished run again from its event log; while it plays the board's write actions are off and the polls do not animate.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useAppApi, useNavigate, type AppApi } from '@kirocrew/app-sdk'
import type { GateDecision, RunDetail } from './types'
import { Conveyor } from './board/Conveyor'
import type { BoardDiff } from './board/diff'
import type { Item } from './board/engine'
import { EventFeed } from './board/EventFeed'
import { BASE, LIVE, PHASES, POLL_MS, isRunActive, paths } from './board/format'
import { FolderPanel } from './board/Folder'
import { OutputsDrawer, type OutputsTarget } from './board/Outputs'
import { EmptyStart, ExpertStrip, GateDialog, Kpis, StartForm, StopConfirm, TopBar, type DeliveryPick, type GateAnswers, type GateRisk } from './board/Header'
import { ClockContext, useReducedMotion, type SnapshotClock } from './board/hooks'
import { Lanes } from './board/Lanes'
import { layoutGraph, visibleGraph } from './board/layout'
import { BOARD_CSS } from './board/styles'
import { TeamGraph, phaseOfLane, type FlashMap } from './board/TeamGraph'
import { TestWall } from './board/TestWall'
import { errorText, useBoard } from './board/useBoard'
import { RoleIcon } from './board/RoleIcon'
import { KnowledgePanel } from './board/Knowledge'
import { BacklogPanel } from './board/Backlog'
import { SignOff } from './board/SignOff'
import { BenchPanel } from './board/Bench'
import { FlowStrip } from './board/FlowStrip'
import { FindingDialog, type ExtendBody, type FindingBody } from './board/Finding'
import { AuditPanel, useAudit, type AuditPick } from './board/Audit'
import { DivisionView } from './board/DivisionGrid'
import { flowOf } from './board/flow'
import { ReplayBar, useReplay } from './board/Replay'
import { AppBar, APP_CSS } from './AppBar'
import { KIT_CSS } from './kit'
import { parseView, searchOf, type BoardEntry, type View } from './nav'
import { ScorecardView } from './scorecard/ScorecardView'
import { ItemView } from './item/ItemView'
import { t as tr } from './i18n'

interface Effects {
  run: string | null
  flips: Record<string, number>
  flashes: FlashMap
  bumps: Record<string, number>
  merges: ReadonlySet<string>
  fresh: ReadonlySet<number>
  announce: string
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
const structureKey = (run: RunDetail) => `${run.roles.map((l) => `${l.key}${l.status === 'skipped' ? '-' : ''}<${l.depends_on.join(',')}`).join(';')}|${run.edges.map((e) => e.join('>')).join(';')}`

type TeamPageProps = {
  pollMs?: number
  /** how many gates and bench requests of the run wait for the person (the app bar's 下一步需要你) */
  onNeeds?: (n: number) => void
  entry?: BoardEntry
  /** a run picked in the board's picker: the URL's entry says that run now */
  onPick?: (rid: string) => void
  /** 交付详情 of a run (the app's item view) */
  onDetail?: (rid: string) => void
  /** opened again by back or forward: the app puts the page back where it was left, so it does not scroll here */
  returning?: boolean
  /** inside the app: 投影 is the app's (its bar has the button); the page follows it and asks it to end (Esc) */
  projection?: boolean
  onProjection?: (on: boolean) => void
}

export function TeamPage({ pollMs = POLL_MS, entry, onPick, onDetail, returning = false, projection: appProjection, onProjection, onNeeds }: TeamPageProps = {}) {
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
  const [findingAsk, setFindingAsk] = useState(false)
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
  const live = board?.run ?? null // the audit trail is the whole record, read for the run itself, not a replay's moment
  const audit = useAudit(live ? `${BASE}/runs/${live.id}/audit` : null, `${live?.id}:${live?.events[live.events.length - 1]?.seq ?? 0}`)
  const [auditPick, setAuditPick] = useState<AuditPick | null>(null)
  const actors = useMemo(() => new Map((audit.trail?.entries ?? []).filter((x) => x.seq !== null).map((x) => [x.seq!, x.actor])), [audit.trail])
  const needs = live ? live.roles.filter((l) => l.gate === 'pending').length + (live.bench?.state.pending.filter((r) => !r.expired).length ?? 0) : 0
  useEffect(() => onNeeds?.(needs), [needs, onNeeds])
  useEffect(() => () => onNeeds?.(0), [onNeeds])
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
  // a picked run that the board no longer has (run: null although runs exist): back to the default
  useEffect(() => {
    if (board && !board.run && board.runs.length > 0 && selected) setSelected(null)
  }, [board, selected])

  const structure = run ? structureKey(run) : ''
  // laid out again only when the structure changes, not on every snapshot
  const lay = useMemo(() => {
    if (!run) return null
    const shown = visibleGraph(run.roles, run.edges) // a role sitting this run out is not in the flow
    return layoutGraph(shown.roles, shown.edges)
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
    async (requirement: string, opts?: { source?: string }) => {
      const body: Record<string, string> = {}
      if (requirement) body.requirement = requirement
      if (opts?.source) body.source = opts.source
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
    async (note: string, delivery?: DeliveryPick, answers?: GateAnswers, risk?: GateRisk) => {
      if (!run || !gateAsk) return
      await api.post(paths.gate(run.id), { role: gateAsk.role, decision: gateAsk.decision, note, ...(delivery ? { delivery } : {}), ...(answers ? { answers } : {}), ...(risk ? { risk } : {}) })
      setGateAsk(null)
      reload()
    },
    [api, run, gateAsk, reload],
  )
  const finding = useCallback(
    async (body: FindingBody | ExtendBody) => {
      if (!run) return
      await api.post(paths.finding(run.id), body)
      setFindingAsk(false)
      reload()
    },
    [api, run, reload],
  )
  const benchRetry = useCallback(async () => {  // a held bench step: the person carries on from it, named in the audit
    if (!run) return
    setRetryErr('')
    try {
      await api.post(paths.retry(run.id), { by: localStorage.getItem('vstatd-team:signer') || '' })
    } catch (e) {
      setRetryErr(errorText(e))
    }
    reload()
  }, [api, run, reload])
  const redo = useCallback(
    async (body: { note: string; by: string }) => {
      if (!run) return
      await api.post(paths.retry(run.id), body)
      reload()
    },
    [api, run, reload],
  )
  const onFinding = run && run.tests.held && !projection && !inReplay && !run.imported ? () => setFindingAsk(true) : undefined
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
  const hide = useCallback(
    async (id: string) => {
      await api.post(paths.hide(id), {})
      setSelected(null)
      reload()
    },
    [api, reload],
  )
  // the lanes and the feed sit in the body on a projector, under it otherwise
  const laneList = run && <Lanes run={run} focus={focus} phase={phase} follow={followKey} bumps={fx.bumps} onRole={onRole} reducedMotion={reducedMotion} projection={projection} onOutputs={openOutputs} onRetry={projection || inReplay || run.imported ? undefined : (k) => void retry(k)} />
  const eventFeed = run && <EventFeed run={run} focus={focus} onRole={onRole} fresh={fx.fresh} milestones={projection} actors={actors} />
  const [cleanupMsg, setCleanupMsg] = useState('')
  const cleanup = useCallback(async () => {
    setCleanupMsg(tr('main.1'))
    try {
      const r = await api.post<{ sessions: number; folders: number }>(paths.cleanup(), {})
      setCleanupMsg(tr('main.2', { p0: r.sessions, p1: r.folders }))
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
          onDetail={onDetail}
          inApp={inApp}
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
            {tr('main.3')}{retryErr}
          </div>
        )}
        {error && (
          <div className="kt-banner" role="status">
            {missing ? tr('main.4') : tr('main.5', { p0: error })}
            {board ? tr('main.6') : ''}
          </div>
        )}
        {!board && loading && <p className="kt-loading">{tr('main.7')}</p>}
        {!projection && !inReplay && startOpen && run && <StartForm onStart={start} onCancel={() => setStartOpen(false)} />}
        {!projection && !inReplay && stopAsk && run && <StopConfirm run={run} onConfirm={stop} onCancel={() => setStopAsk(false)} />}
        {gateAsk && run && <GateDialog key={`${gateAsk.role}-${gateAsk.decision}-${gateLane?.talk.length ?? 0}`} label={gateLane?.gate_label || gateLane?.title || gateAsk.role} who={gateLane?.title} questions={gateLane?.questions} talk={gateLane?.talk} outputs={gateDocs.length > 1 ? gateDocs : []} decision={gateAsk.decision} preset={gateAsk.decision === 'discuss' ? undefined : gateAsk.decision === 'revise' ? gateLane?.gate_revise_preset : gateLane?.gate_preset} presetRisk={gateAsk.decision === 'revise' ? gateLane?.gate_revise_risk : undefined} askRisk={!!gateLane?.gate_revise_risk} split={gateLane && gateLane.writable.length === 0 ? undefined : run.roles.filter((l) => l.key !== gateAsk.role && l.status !== 'skipped' && !(l.key in run.plan_skip)).map((l) => ({ key: l.key, title: l.title, icon: l.icon, assignment: l.assignment }))} skips={gateLane && gateLane.writable.length > 0 ? Object.entries(run.plan_skip).map(([k, why]) => ({ key: k, title: run.roles.find((l) => l.key === k)?.title ?? k, why })) : undefined} overrule={gateLane?.overrule} delivery={gateLane?.delivery_gate && gateAsk.decision === 'approve' ? run.delivery : undefined} report={gateLane && gateLane.writable.length === 0 ? gateLane.summary || '' : undefined} onReport={gateLane && gateLane.writable.length === 0 ? () => openOutputs(gateLane.key) : undefined} onConfirm={gate} onCancel={() => setGateAsk(null)} />}
        {findingAsk && run?.tests.held && <FindingDialog key={run.id} run={run} onConfirm={finding} onCancel={() => setFindingAsk(false)} />}
        {board && !run && board.runs.length === 0 && <EmptyStart onStart={start} />}
        {run && lay && (
          <>
            <Kpis key={`${run.id}${inReplay ? ':replay' : ''}`} run={run} reducedMotion={reducedMotion} onRole={onRole} />
            {run.bench && <FlowStrip run={run} onFinding={onFinding} onAgree={onFinding ? finding : undefined} onRedo={!projection && !inReplay && !run.imported ? redo : undefined} />}
            {!projection && live && <DivisionView trail={audit.trail} current={run.bench ? flowOf(run).current : null} onPick={setAuditPick} />}
            {run.roles.some((l) => l.phase) && <ExpertStrip run={run} />}
            {projection && <KnowledgePanel run={run} onRole={onRole} />}
            {projection && <BacklogPanel run={run} />}
            {!isRunActive(run.status) && run.tests.total > 0 && <SignOff run={run} onSign={sign} />}
            <div className="kt-body">
              <div className="kt-col">
                <TeamGraph key={`${run.id}${inReplay ? ':replay' : ''}`} run={run} lay={lay} focus={focus} onRole={onRole} flashes={fx.flashes} reducedMotion={reducedMotion} feed={feed} onRetry={projection || inReplay || run.imported ? undefined : (k) => void retry(k)} onGate={inReplay ? undefined : (k, d) => setGateAsk({ role: k, decision: d })} quiet={projection} onOutputs={(k) => openOutputs(k)} phase={phase} onPhase={(p) => { setFocus(null); setPhase((x) => (x === p ? null : p)) }} />
                {focus && <FocusBar run={run} focus={focus} onClear={() => setFocus(null)} />}
                {!focus && phase && <PhaseBar run={run} phase={phase} onClear={() => setPhase(null)} />}
                {/* on a projector the rail of the graph carries the merges; the space goes to the lanes */}
                {!projection && run.merges.length > 0 && <Conveyor run={run} fresh={fx.merges} focus={focus} onRole={onRole} />}
                {projection && laneList}
              </div>
              <aside className="kt-side" aria-label={projection ? tr('main.8') : tr('main.9')}>
                <TestWall tests={run.tests} roles={run.roles} focus={focus} onRole={onRole} flips={fx.flips} onFinding={onFinding} />
                {run.bench && <BenchPanel bench={run.bench} onRetry={!projection && !inReplay && !run.imported && run.bench.held ? benchRetry : undefined} />}
                {projection && eventFeed}
              </aside>
            </div>
            {/* off the projector the live state comes first: lanes, then the lists, then the feed */}
            {!projection && (
              <>
                {laneList}
                <BacklogPanel run={run} />
                <KnowledgePanel run={run} onRole={onRole} />
                {eventFeed}
              </>
            )}
            {!projection && live && <AuditPanel runId={live.id} ended={!isRunActive(live.status)} trail={audit.trail} err={audit.err} pick={auditPick} />}
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

/** A phase picked out on the board: which, and how many roles. */
function PhaseBar({ run, phase, onClear }: { run: RunDetail; phase: string; onClear: () => void }) {
  const p = PHASES.find((x) => x.key === phase)
  const n = run.roles.filter((l) => l.status !== 'skipped' && phaseOfLane(l.phase) === phase).length
  return (
    <div className="kt-focuschip" role="status" data-testid="kt-phasebar">
      {p ? `${p.n} ${p.title}` : phase} · {n} {tr('main.10')}
      <button type="button" onClick={onClear} aria-label={tr('main.11')} title={tr('main.12')}>
        ✕
      </button>
    </div>
  )
}

function FocusBar({ run, focus, onClear }: { run: RunDetail; focus: string; onClear: () => void }) {
  const lane = run.roles.find((l) => l.key === focus)
  if (!lane) return null
  return (
    <div className="kt-focuschip" role="status" data-testid="kt-focusbar">
      <RoleIcon role={lane.icon || lane.key} size={14} /> {lane.title}
      <button type="button" onClick={onClear} aria-label={tr('main.11')} title={tr('main.12')}>
        ✕
      </button>
    </div>
  )
}

function entryOf(v: View & { n: number; returning?: boolean }): BoardEntry {
  if (v.kind !== 'board') return {}
  const { kind: _k, n: _n, returning: _r, ...entry } = v
  return entry
}

/** The app: its bar, then the board or the 评分卡, as the URL says (nav.ts). A move to another view is a history entry made through
 * the host's router (useNavigate), so Kiro Crew's ← → (and ⌘←), like the browser's back and forward, step between
 * views, and every entry can be linked to; a change inside a view (the run picked on the board) rewrites the current
 * entry. Each entry also keeps how far the page was scrolled (`ktScroll` in its state): back or forward puts the page
 * there again once the view has its content (unless the reader scrolls first). 投影 is the app's: full screen (the
 * Fullscreen API on the app, a fixed overlay where it is refused) stays on across views. */
export default function VstatdTeamApp({ pollMs }: { pollMs?: number } = {}) {
  const [view, setView] = useState<View & { n: number; returning?: boolean }>(() => ({ ...parseView(window.location.search), n: 0 }))
  const [projection, setProjection] = useState(false)
  const [needs, setNeeds] = useState(0)
  const navigate = useNavigate()
  const rootRef = useRef<HTMLDivElement | null>(null)
  const restore = useRef<number | null>(null) // back or forward: the scroll to put the page back at
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
    window.history.replaceState({ ...(window.history.state ?? {}), ktDepth: depth() }, '', href(v))
  }, [])
  // a move to another view: a new history entry, made by the host's router (so its ← → know about it); the entry then
  // says how many moves deep into the app it is (the router may make it a moment later)
  const go = useCallback((v: View) => {
    keepScroll()
    const d = depth() + 1, to = href(v)
    setView((cur) => ({ ...v, n: cur.n + 1 }))
    navigate(to)
    const mark = () => {
      const st = window.history.state as { ktDepth?: number } | null
      if (`${window.location.pathname}${window.location.search}` === to && st?.ktDepth === undefined) window.history.replaceState({ ...(st ?? {}), ktDepth: d }, '', to)
    }
    mark()
    setTimeout(mark, 0)
    setTimeout(mark, 60)
  }, [keepScroll, navigate])
  // back and forward: the view the entry says, scrolled where it was left
  useEffect(() => {
    const onPop = () => {
      const v = parseView(window.location.search)
      const top = (window.history.state as { ktScroll?: number } | null)?.ktScroll
      restore.current = typeof top === 'number' && top > 0 ? top : null
      setView((cur) => ({ ...v, n: cur.n + 1, returning: restore.current !== null }))
    }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])
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
  const onPick = useCallback((rid: string) => replace({ kind: 'board', run: rid }), [replace])
  const onDetail = useCallback((rid: string) => go({ kind: 'item', run: rid }), [go])
  const { n, returning } = view
  return (
    <div ref={rootRef} className={`kt-app${projection ? ' is-projection' : ''}`} data-testid="kt-app">
      <style>{APP_CSS}</style>
      <AppBar view={view.kind} projection={projection} onView={(k) => go({ kind: k })} onProjection={() => onProjection(!projection)} needs={view.kind === 'board' ? needs : 0} />
      {view.kind === 'score' ? <ScorecardView key={n} onDetail={onDetail} />
        : view.kind === 'item' ? <ItemView key={n} run={view.run} onBoard={(e) => go({ kind: 'board', ...e })} />
        : <TeamPage key={n} pollMs={pollMs} entry={entryOf(view)} returning={returning} onPick={onPick} onDetail={onDetail} projection={projection} onProjection={onProjection} onNeeds={setNeeds} />}
    </div>
  )
}
