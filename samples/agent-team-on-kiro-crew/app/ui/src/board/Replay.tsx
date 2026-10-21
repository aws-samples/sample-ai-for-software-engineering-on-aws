/**
 * 回放 on the board: a finished run played again from its event log, at 10× to 120×, with a scrubber. The board shows
 * replayAt(run, events, t) (timeline.ts) instead of the run's final record, and every tick goes through the same differ as
 * a live poll, so particles, flips and red flashes come in the order they happened. Nothing is written while it plays:
 * the page turns its gates, retries and sign-off off. Costs no credits; the run is not touched.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { AppApi } from '@kirocrew/app-sdk'
import type { RunDetail, TeamEvent } from '../types'
import { diffRuns, type BoardDiff } from './diff'
import { fmtClock, paths } from './format'
import type { SnapshotClock } from './hooks'
import { replayAt, replaySpan, type ReplaySpan } from './timeline'
import { errorText } from './useBoard'

export const SPEEDS = [10, 30, 60, 120] as const
export const TICK_MS = 250

/** The slowest speed that plays a run of *seconds* in about a minute and a half (a long run gets the fastest). */
export function pickSpeed(seconds: number): number {
  return SPEEDS.find((s) => seconds / s <= 90) ?? SPEEDS[SPEEDS.length - 1]
}

export interface ReplayHandle {
  /** the run being replayed, or null */
  id: string | null
  loading: boolean
  error: string
  /** the board at the replay's moment (null when not replaying) */
  run: RunDetail | null
  clock: SnapshotClock | null
  span: ReplaySpan | null
  t: number
  speed: number
  playing: boolean
  start: () => void
  exit: () => void
  toggle: () => void
  /** stop where it is (a way in at a moment: the person starts it) */
  pause: () => void
  seek: (t: number) => void
  setSpeed: (s: number) => void
}

interface State {
  id: string | null
  events: TeamEvent[] | null
  t: number
  speed: number
  playing: boolean
  loading: boolean
  error: string
}

const OFF: State = { id: null, events: null, t: 0, speed: SPEEDS[1], playing: false, loading: false, error: '' }

export function useReplay(api: AppApi, run: RunDetail | null, onDiff: (d: BoardDiff) => void): ReplayHandle {
  const [st, setSt] = useState<State>(OFF)
  const prev = useRef<RunDetail | null>(null)
  const quiet = useRef(false)
  const on = !!(run && st.id === run.id && st.events)
  const span = useMemo(() => (on && run && st.events ? replaySpan(run, st.events) : null), [on, run, st.events])

  // another run picked: the replay stops
  useEffect(() => {
    if (st.id && run && run.id !== st.id) setSt(OFF)
  }, [run, st.id])

  const start = useCallback(() => {
    if (!run) return
    const id = run.id
    setSt({ ...OFF, id, loading: true })
    api
      .get<{ events?: TeamEvent[] }>(paths.events(id))
      .then((r) => {
        const events = Array.isArray(r?.events) ? r.events : []
        const sp = replaySpan(run, events)
        prev.current = null
        setSt({ ...OFF, id, events, t: sp.start, speed: pickSpeed(sp.end - sp.start), playing: true })
      })
      .catch((e) => setSt({ ...OFF, error: `回放没打开：${errorText(e)}` }))
  }, [api, run])
  const exit = useCallback(() => {
    prev.current = null
    setSt(OFF)
  }, [])
  const toggle = useCallback(() => {
    setSt((s) => {
      if (!span) return s
      if (s.t >= span.end) {
        quiet.current = true
        prev.current = null
        return { ...s, t: span.start, playing: true } // from the start again
      }
      return { ...s, playing: !s.playing }
    })
  }, [span])
  const seek = useCallback((t: number) => {
    quiet.current = true // a jump is not a change: nothing flies
    setSt((s) => ({ ...s, t }))
  }, [])
  const setSpeed = useCallback((speed: number) => setSt((s) => ({ ...s, speed })), [])
  const pause = useCallback(() => setSt((s) => ({ ...s, playing: false })), [])

  useEffect(() => {
    if (!on || !st.playing || !span) return
    const timer = setInterval(() => {
      setSt((s) => {
        const t = Math.min(span.end, s.t + (s.speed * TICK_MS) / 1000)
        return { ...s, t, playing: t < span.end }
      })
    }, TICK_MS)
    return () => clearInterval(timer)
  }, [on, st.playing, span])

  const shown = useMemo(() => (on && run && st.events ? replayAt(run, st.events, st.t) : null), [on, run, st.events, st.t])
  useEffect(() => {
    if (!shown) return
    // events up to two ticks old still fly: at 120× a tick is half a minute of the run
    const d = diffRuns(prev.current, shown, { at: st.t, resync: quiet.current, lateS: Math.max(30, (st.speed * TICK_MS * 2) / 1000) })
    quiet.current = false
    prev.current = shown
    onDiff(d)
  }, [shown]) // eslint-disable-line react-hooks/exhaustive-deps

  // the replay's own time; between two ticks (and while paused) it stands still: the board's 1 Hz clock adds nothing
  const clock = useMemo(() => (shown ? { at: Math.min(st.t, span?.end ?? st.t), receivedAt: Number.POSITIVE_INFINITY } : null), [shown, st.t, span])
  return { id: st.id, loading: st.loading, error: st.error, run: shown, clock, span, t: st.t, speed: st.speed, playing: st.playing, start, exit, toggle, pause, seek, setSpeed }
}

/** The replay's controls, under the top bar: what is playing, how far, how fast. */
export function ReplayBar({ rp, projection }: { rp: ReplayHandle; projection: boolean }) {
  if (rp.loading) return <div className="kt-replay" role="status">正在读这次运行的记录…</div>
  if (rp.error) return <div className="kt-banner is-error" role="alert">{rp.error}</div>
  if (!rp.run || !rp.span) return null
  const { start, end } = rp.span
  const ended = rp.t >= end
  return (
    <div className="kt-replay" role="group" aria-label="回放">
      <span className="kt-pill tone-info">回放</span>
      <button type="button" className="kt-btn kt-btn-icon" onClick={rp.toggle} aria-label={rp.playing ? '暂停' : ended ? '从头再放' : '播放'} title={rp.playing ? '暂停' : ended ? '从头再放' : '播放'}>
        {rp.playing ? '⏸' : ended ? '↺' : '▶'}
      </button>
      <input
        type="range"
        className="kt-replay-scrub"
        aria-label="回放进度"
        min={start}
        max={end}
        step={1}
        value={Math.min(end, rp.t)}
        onChange={(e) => rp.seek(Number(e.target.value))}
      />
      <span className="kt-mono kt-replay-time">
        {fmtClock(Math.round(rp.t - start))} / {fmtClock(Math.round(end - start))}
      </span>
      {!projection && (
        <span className="kt-replay-speeds" role="radiogroup" aria-label="倍速">
          {SPEEDS.map((s) => (
            <button key={s} type="button" role="radio" aria-checked={rp.speed === s} className={`kt-btn${rp.speed === s ? ' is-on' : ''}`} onClick={() => rp.setSpeed(s)}>
              {s}×
            </button>
          ))}
        </span>
      )}
      <span className="kt-dim kt-replay-note">{ended ? '放完了：下面是这次运行最后的样子' : '按这次运行的记录重放，不调用 agent'}</span>
      <button type="button" className="kt-btn" onClick={rp.exit}>
        退出回放
      </button>
    </div>
  )
}
