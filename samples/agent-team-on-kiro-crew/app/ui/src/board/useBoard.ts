/**
 * Polls GET /board every 2 s. Never two requests at
 * once, nothing while the page is in the background, at once when it comes back. There is no cursor
 * here (the contract returns the whole snapshot), so the hook keeps the previous snapshot of the
 * selected run and hands every new one to the differ (diff.ts) together with it; `onDiff` gets the
 * result (the page turns it into particles, flips and highlights).
 *
 * The first snapshot of a run, and the first one after the page was hidden, are history: the differ
 * says so (`first`), and nothing animates.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import type { AppApi } from '@kirocrew/app-sdk'
import type { Board, RunDetail } from '../types'
import { diffRuns, type BoardDiff } from './diff'
import { POLL_MS, paths } from './format'
import { useLatest } from './hooks'

export interface BoardState {
  board: Board | null
  error: string
  /** the backend has no /board route (404) */
  missing: boolean
  loading: boolean
  /** Date.now() when the current snapshot arrived */
  receivedAt: number
}

export interface BoardHandle extends BoardState {
  /** Poll now (after a start or a stop). */
  reload: () => void
}

/** The API error's text in Chinese (the SDK rejects with `API <status>: <body>`). */
export function errorText(e: unknown): string {
  const raw = e instanceof Error ? e.message : String(e)
  const m = /^API (\d{3}): ([\s\S]*)$/.exec(raw)
  if (!m) return raw
  const [, status, body] = m
  try {
    const data = JSON.parse(body) as { error?: unknown }
    if (data && typeof data.error === 'string' && data.error) return `${data.error}（${status}）`
  } catch {
    /* not JSON */
  }
  if (status === '401') return '需要登录 KiroCrew dashboard（401）'
  if (status === '403') return '没有权限：只接受 dashboard 主人本人的请求（403）'
  if (status === '404') return '后端还没有这个接口（404）'
  return `请求失败（${status}）${body.trim() ? `：${body.trim().slice(0, 200)}` : ''}`
}

export function errorStatus(e: unknown): number {
  const m = /^API (\d{3}):/.exec(e instanceof Error ? e.message : String(e))
  return m ? Number(m[1]) : 0
}

export function useBoard(api: AppApi, opts: { run: string | null; pollMs?: number; onDiff?: (d: BoardDiff, b: Board) => void }): BoardHandle {
  const pollMs = opts.pollMs ?? POLL_MS
  const [state, setState] = useState<BoardState>({ board: null, error: '', missing: false, loading: true, receivedAt: 0 })
  const apiRef = useLatest(api)
  const runRef = useLatest(opts.run)
  const onDiffRef = useLatest(opts.onDiff)
  const inFlight = useRef(false)
  const prev = useRef<RunDetail | null>(null)
  const hiddenGap = useRef(false)
  const generation = useRef(0)
  const kick = useRef<() => void>(() => {})

  const load = useCallback(async () => {
    if (inFlight.current) return
    inFlight.current = true
    const gen = generation.current
    try {
      const got = await apiRef.current.get<Board>(paths.board(runRef.current))
      if (gen !== generation.current) return // the selection changed while this was on its way
      const next = got?.run ?? null
      const visible = typeof document === 'undefined' || !document.hidden
      let diff: BoardDiff | null = null
      if (next) diff = diffRuns(prev.current, next, { at: got.at, resync: hiddenGap.current })
      prev.current = next
      if (visible) hiddenGap.current = false
      setState({ board: got, error: '', missing: false, loading: false, receivedAt: Date.now() })
      if (diff) onDiffRef.current?.(diff, got)
    } catch (e) {
      if (gen !== generation.current) return
      setState((s) => ({ ...s, error: errorText(e), missing: errorStatus(e) === 404, loading: false }))
    } finally {
      inFlight.current = false
      if (gen !== generation.current) kick.current()
    }
  }, [apiRef, runRef, onDiffRef])

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined
    let alive = true
    let chain = 0
    const schedule = (ms: number) => {
      clearTimeout(timer)
      const mine = ++chain
      timer = setTimeout(() => void run(mine), ms)
    }
    const run = async (mine: number) => {
      if (!alive || mine !== chain) return
      if (document.hidden) {
        hiddenGap.current = true // the visibility listener starts a new chain
        return
      }
      await load()
      if (alive && mine === chain) schedule(pollMs)
    }
    const onVisibility = () => {
      if (document.hidden) {
        hiddenGap.current = true
        clearTimeout(timer)
        chain++
        return
      }
      schedule(0)
    }
    kick.current = () => schedule(0)
    schedule(0)
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      alive = false
      clearTimeout(timer)
      kick.current = () => {}
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [load, pollMs])

  // another run picked: its first snapshot is history again
  const firstRun = useRef(true)
  useEffect(() => {
    if (firstRun.current) {
      firstRun.current = false
      return
    }
    generation.current++
    prev.current = null
    kick.current()
  }, [opts.run])

  const reload = useCallback(() => kick.current(), [])
  return { ...state, reload }
}
