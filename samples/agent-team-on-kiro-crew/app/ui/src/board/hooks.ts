/**
 * Small hooks the board shares: the latest value in a ref, reduced motion, one shared 1 Hz clock
 * (paused while the page is hidden), a number that counts up to its new value, and a typewriter for an
 * agent's live text that types only what is new.
 */
import { createContext, useContext, useEffect, useRef, useState, useSyncExternalStore } from 'react'

export function useLatest<T>(value: T) {
  const ref = useRef(value)
  ref.current = value
  return ref
}

const REDUCE = '(prefers-reduced-motion: reduce)'

export function prefersReducedMotion(): boolean {
  try {
    return typeof window !== 'undefined' && typeof window.matchMedia === 'function' && !!window.matchMedia(REDUCE)?.matches
  } catch {
    return false
  }
}

export function useReducedMotion(): boolean {
  const [rm, setRm] = useState(prefersReducedMotion)
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return
    const m = window.matchMedia(REDUCE)
    if (!m) return
    const on = () => setRm(!!m.matches)
    m.addEventListener?.('change', on)
    return () => m.removeEventListener?.('change', on)
  }, [])
  return rm
}

// ---------------------------------------------------------------------------------------------
// one clock for every "3 分钟前" and every ticking timer
// ---------------------------------------------------------------------------------------------

const subscribers = new Set<() => void>()
let tickTimer: ReturnType<typeof setInterval> | null = null
let nowMs = Date.now()

function subscribe(cb: () => void): () => void {
  subscribers.add(cb)
  if (!tickTimer) {
    nowMs = Date.now()
    tickTimer = setInterval(() => {
      if (typeof document !== 'undefined' && document.hidden) return
      nowMs = Date.now()
      for (const s of subscribers) s()
    }, 1000)
  }
  return () => {
    subscribers.delete(cb)
    if (!subscribers.size && tickTimer) {
      clearInterval(tickTimer)
      tickTimer = null
    }
  }
}

/** Date.now(), re-rendering once a second (never while the page is hidden). */
export function useNowMs(): number {
  return useSyncExternalStore(
    subscribe,
    () => nowMs,
    () => nowMs,
  )
}

/** The snapshot's time and when it arrived here: the server's "now" without trusting the local clock. */
export interface SnapshotClock {
  at: number
  receivedAt: number
}

export const ClockContext = createContext<SnapshotClock>({ at: Date.now() / 1000, receivedAt: Date.now() })

/** The server's now (epoch seconds), ticking once a second. */
export function useServerNow(): number {
  const { at, receivedAt } = useContext(ClockContext)
  const now = useNowMs()
  return at + Math.max(0, now - receivedAt) / 1000
}

/** Seconds since the snapshot was taken (a live timer adds this to the snapshot's value). */
export function useSinceSnapshot(): number {
  const { at } = useContext(ClockContext)
  return Math.max(0, useServerNow() - at)
}

// ---------------------------------------------------------------------------------------------
// a number that counts to its new value
// ---------------------------------------------------------------------------------------------

/** The displayed value of *target*: equal at first, then easing to each new value over *ms*. */
export function useTween(target: number, ms = 900, disabled = false): number {
  const [shown, setShown] = useState(target)
  const from = useRef(target)
  const shownRef = useLatest(shown)
  useEffect(() => {
    if (disabled || typeof requestAnimationFrame !== 'function') {
      setShown(target)
      return
    }
    from.current = shownRef.current
    if (from.current === target) return
    const t0 = performance.now()
    let id = 0
    const step = () => {
      const p = Math.min(1, (performance.now() - t0) / ms)
      const e = 1 - Math.pow(1 - p, 3)
      setShown(from.current + (target - from.current) * e)
      if (p < 1) id = requestAnimationFrame(step)
    }
    id = requestAnimationFrame(step)
    return () => cancelAnimationFrame(id)
  }, [target, ms, disabled, shownRef])
  return shown
}

/**
 * 0 until *value* changes after the first render, then +1 per change: a key that replays a one-shot
 * CSS animation for a real change, and never on the first render.
 */
export function useChangeCount(value: unknown): number {
  const ref = useRef({ v: value, n: 0 })
  if (!Object.is(ref.current.v, value)) ref.current = { v: value, n: ref.current.n + 1 }
  return ref.current.n
}

// ---------------------------------------------------------------------------------------------
// the typewriter
// ---------------------------------------------------------------------------------------------

/**
 * How *next* continues *prev* (a sliding tail of the same output): `[kept, added]` with
 * kept + added === next, or null when they do not overlap (a new text altogether).
 */
export function continuation(prev: string, next: string): [string, string] | null {
  if (!prev || !next) return null
  if (next === prev) return [next, '']
  if (next.startsWith(prev)) return [prev, next.slice(prev.length)]
  // the window slid: the longest end of prev that next starts with
  for (let k = Math.min(prev.length, next.length) - 1; k >= 12; k--) {
    if (next.startsWith(prev.slice(prev.length - k))) return [next.slice(0, k), next.slice(k)]
  }
  return null
}

/** The text to show: what was there stays, only the new part types out (or fades in if unrelated). */
export function useTypewriter(text: string | null, disabled = false): { shown: string; typing: boolean; fresh: boolean } {
  const [state, setState] = useState<{ base: string; added: string; n: number; fresh: boolean }>({ base: text ?? '', added: '', n: 0, fresh: false })
  const prev = useRef(text ?? '')
  useEffect(() => {
    const next = text ?? ''
    const old = prev.current
    prev.current = next
    if (next === old) return
    const cont = continuation(old, next)
    if (disabled || !cont || typeof window === 'undefined') {
      setState({ base: next, added: '', n: 0, fresh: !disabled && !!next && !cont })
      return
    }
    const [base, added] = cont
    setState({ base, added, n: 0, fresh: false })
    if (!added) return
    const step = Math.max(1, Math.ceil(added.length / 45))
    const id = window.setInterval(() => {
      setState((s) => {
        const n = Math.min(s.added.length, s.n + step)
        if (n >= s.added.length) window.clearInterval(id)
        return { ...s, n }
      })
    }, 28)
    return () => window.clearInterval(id)
  }, [text, disabled])
  const typing = state.n < state.added.length
  return { shown: state.base + state.added.slice(0, state.n), typing, fresh: state.fresh }
}
