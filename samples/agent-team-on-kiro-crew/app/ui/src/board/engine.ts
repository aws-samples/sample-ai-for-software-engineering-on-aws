/**
 * The animation engine of the team graph. (lines
 * 1–276, the `Pipeline` class): the same dedupe, admission limits, frame budget with degradation
 * levels, reduced motion and hidden-page pause; the scheduling is simpler (a poll's batch plays
 * spread over the next ~1.6 s in its real order and spacing) and a particle that arrives leaves a
 * ring on its target. Pure: the clock is passed in, so the page and the tests run the same code.
 *
 * Every particle is one real event (`key` = `<run>#<seq>`); nothing moves without one.
 *
 *  1. in — items are deduplicated by key (the last 2048 remembered); `history()` remembers without
 *     playing (the first snapshot);
 *  2. spread — a batch plays from when it arrived, each item offset by its time after the batch's
 *     first, squeezed to fit SPREAD_MS when the batch spans longer;
 *  3. merge — one particle per channel (kind, from, to) per 250 ms; merged items make it bigger;
 *  4. admit — POOL particles at most, PER_EDGE per edge; when full the least important goes first,
 *     priority 3 (merged, tests, bounce, conflict, violation, failed) never;
 *  5. frame budget — at most 2 ms of the page's own work per frame: over it one level down (L0 all,
 *     L1 half below priority 3, L2 priority 2 and up, L3 nothing flies); 5 s calm, one level up;
 *  6. hidden — nothing plays; what was due meanwhile is dropped on return, never played late;
 *  7. reduced motion — L3 for good: states change, nothing flies.
 */

export type Prio = 0 | 1 | 2 | 3
export type Shape = 'comet' | 'ring' | 'cross' | 'check' | 'spark'
export type PTone = 'handoff' | 'merge' | 'pass' | 'fail' | 'bounce' | 'danger' | 'run' | 'ok' | 'tool' | 'info'

export interface Item {
  key: string
  /** When it happened, epoch seconds. */
  t: number
  kind: string
  from: string
  to: string
  prio: Prio
  shape: Shape
  tone: PTone
  /** What it carries, drawn next to a travelling head: 验收标准, 9/12, AC-11 … (from the event itself). */
  label?: string | null
}

export interface Particle extends Item {
  id: number
  /** ms on the engine's clock */
  start: number
  dur: number
  /** how many items it stands for */
  count: number
  travel: boolean
}

export interface Frame {
  particles: Array<Particle & { p: number }>
  level: number
}

export const DEDUPE = 2048
export const POOL = 32
export const PER_EDGE = 4
export const MERGE_MS = 250
export const LATE_MS = 5000
export const BUDGET_MS = 2
export const CALM_MS = 1.5
export const CALM_FOR_MS = 5000
export const TRAVEL_MS = 1500
export const BLIP_MS = 900
export const ARRIVE_MS = 850
export const SPREAD_MS = 1600

/** What a travelling particle leaves on its target when it gets there. */
export function arrivalShape(tone: PTone): Shape {
  if (tone === 'bounce' || tone === 'fail') return 'cross'
  if (tone === 'pass' || tone === 'merge') return 'check'
  return 'ring'
}

export interface EngineOptions {
  /** The clock, ms (performance.now() live; a fake one in tests). */
  now: () => number
  reducedMotion?: boolean
  spreadMs?: number
}

export class Engine {
  private readonly now: () => number
  private readonly spreadMs: number
  private readonly base: number
  private seen = new Set<string>()
  private order: string[] = []
  private queue: Array<Item & { playAt: number }> = []
  private active: Particle[] = []
  private nextId = 1
  private skipToggle = false
  private calmSince: number | null = null
  private hiddenAt: number | null = null
  level: number
  /** What did not fly and why (tests and the debug readout read it). */
  readonly dropped = { duplicate: 0, merged: 0, admission: 0, level: 0, expired: 0 }

  constructor(opts: EngineOptions) {
    this.now = opts.now
    this.spreadMs = opts.spreadMs ?? SPREAD_MS
    this.base = opts.reducedMotion ? 3 : 0
    this.level = this.base
  }

  get reducedMotion(): boolean {
    return this.base === 3
  }

  /** Something is queued or flying: the overlay keeps asking for frames only then. */
  get busy(): boolean {
    return this.hiddenAt === null && (this.queue.length > 0 || this.active.length > 0)
  }

  /** Records the page already had (the first snapshot): remembered, never played. */
  history(items: Item[]): void {
    for (const it of items) if (!this.seen.has(it.key)) this.remember(it.key)
  }

  /** One poll's new items; returns those that were not seen before. */
  ingest(items: Item[], receivedAt: number = this.now()): Item[] {
    const fresh: Item[] = []
    for (const it of items) {
      if (this.seen.has(it.key)) {
        this.dropped.duplicate++
        continue
      }
      this.remember(it.key)
      fresh.push(it)
    }
    if (!fresh.length) return fresh
    const first = Math.min(...fresh.map((i) => i.t))
    const span = (Math.max(...fresh.map((i) => i.t)) - first) * 1000
    const squeeze = span > this.spreadMs ? this.spreadMs / span : 1
    for (const it of fresh) this.queue.push({ ...it, playAt: receivedAt + (it.t - first) * 1000 * squeeze })
    this.queue.sort((a, b) => a.playAt - b.playAt)
    return fresh
  }

  /** The particles to draw now, with their progress 0…1. */
  frame(at: number = this.now()): Frame {
    if (this.hiddenAt !== null) return { particles: [], level: this.level }
    while (this.queue.length && this.queue[0].playAt <= at) {
      const it = this.queue.shift()!
      this.spawn(it, Math.max(it.playAt, at - 100))
    }
    const keep: Particle[] = []
    for (const p of this.active) {
      if (at - p.start < p.dur) {
        keep.push(p)
        continue
      }
      // a particle that got there leaves one ring on its target (the same record, not a new one)
      if (p.travel) keep.push({ ...p, id: this.nextId++, from: p.to, travel: false, shape: arrivalShape(p.tone), start: p.start + p.dur, dur: ARRIVE_MS })
    }
    this.active = keep.filter((p) => at - p.start < p.dur)
    return { particles: this.active.map((p) => ({ ...p, p: Math.min(1, Math.max(0, (at - p.start) / p.dur)) })), level: this.level }
  }

  /** How long the page's own work took in the frame that just ran (ms): the level follows it. */
  report(workMs: number, at: number = this.now()): void {
    if (this.base === 3) return
    if (workMs > BUDGET_MS) {
      this.level = Math.min(3, this.level + 1)
      this.calmSince = null
      return
    }
    if (workMs < CALM_MS) {
      if (this.calmSince === null) this.calmSince = at
      else if (at - this.calmSince >= CALM_FOR_MS && this.level > this.base) {
        this.level -= 1
        this.calmSince = at
      }
    } else {
      this.calmSince = null
    }
  }

  /** The page went to the background (true) or came back (false). */
  setHidden(hidden: boolean, at: number = this.now()): void {
    if (hidden) {
      if (this.hiddenAt === null) this.hiddenAt = at
      return
    }
    if (this.hiddenAt === null) return
    this.hiddenAt = null
    // what should have played meanwhile is not played late
    const stale = this.queue.filter((q) => at - q.playAt > LATE_MS)
    this.dropped.expired += stale.length
    this.queue = this.queue.filter((q) => at - q.playAt <= LATE_MS)
    this.active = this.active.filter((p) => at - p.start < p.dur)
  }

  private remember(key: string): void {
    this.seen.add(key)
    this.order.push(key)
    if (this.order.length > DEDUPE) this.seen.delete(this.order.shift()!)
  }

  private spawn(it: Item, at: number): void {
    if (this.level >= 3 || (this.level >= 2 && it.prio < 2)) {
      this.dropped.level++
      return
    }
    if (this.level === 1 && it.prio < 3) {
      this.skipToggle = !this.skipToggle
      if (this.skipToggle) {
        this.dropped.level++
        return
      }
    }
    const channel = `${it.kind}|${it.from}|${it.to}`
    const same = this.active.find((p) => `${p.kind}|${p.from}|${p.to}` === channel && Math.abs(at - p.start) < MERGE_MS)
    if (same) {
      same.count++
      same.prio = Math.max(same.prio, it.prio) as Prio
      this.dropped.merged++
      return
    }
    const edge = `${it.from}>${it.to}`
    const onEdge = this.active.filter((p) => `${p.from}>${p.to}` === edge)
    if (onEdge.length >= PER_EDGE && !this.evict(onEdge, it.prio)) {
      this.dropped.admission++
      return
    }
    if (this.active.length >= POOL && !this.evict(this.active, it.prio)) {
      this.dropped.admission++
      return
    }
    const travel = it.from !== it.to
    this.active.push({ ...it, id: this.nextId++, start: at, dur: travel ? TRAVEL_MS : BLIP_MS, count: 1, travel })
  }

  /** Make room among *among* for an item of priority *prio*: drop the least important one below it
   * (oldest first). Priority 3 is never dropped and always gets in (the pool stretches for it). */
  private evict(among: Particle[], prio: Prio): boolean {
    const victims = among.filter((p) => p.prio < 3 && p.prio < prio).sort((a, b) => a.prio - b.prio || a.start - b.start)
    const v = victims[0]
    if (v) {
      this.active = this.active.filter((p) => p !== v)
      this.dropped.admission++
      return true
    }
    return prio === 3
  }
}
