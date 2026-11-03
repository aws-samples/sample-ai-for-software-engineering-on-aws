/**
 * The particle layer of the team graph. One
 * `aria-hidden` SVG group on top of the static graph whose shapes one requestAnimationFrame loop moves
 * by setting attributes directly, never through React, with a small pool of reused `<g>`. Here a
 * travelling particle is a comet (a head, a soft halo and a tapered streak) that follows the graph's
 * own routes (layout.ts: the edge, the merge lane, the rail), and a blip is a ring, a cross or a tick
 * that grows once and fades: one beat per record, never a loop.
 *
 * The loop only runs while the engine has something queued or flying. Every drawn shape carries
 * `data-src`, the event it stands for (`<run>#<seq>`): the event feed is the way to the same record.
 */
import type { Engine, Frame, Particle } from './engine'
import { measure, pointAt, type Path, type PathInfo, type Pt } from './layout'

/** Centre, size and corner radius of an anchor on the graph. */
export interface Box extends Pt {
  w: number
  h: number
  rx: number
}

const SVG = 'http://www.w3.org/2000/svg'
/** Points of a comet's tail, and how long it is at most (px). */
const TAIL_POINTS = 9
const TAIL_PX = 96

export interface OverlayOptions {
  /** The route from one anchor to another now; null: it does not travel. */
  path: (from: string, to: string) => Path | null
  /** The box an anchor takes up now (a blip pulses around it); null: not drawn. */
  box: (a: string) => Box | null
  /** The engine's clock (ms). */
  now: () => number
  perf?: () => number
  raf?: (cb: FrameRequestCallback) => number
  caf?: (id: number) => void
  onFrame?: (f: Frame) => void
}

const defaultRaf = (cb: FrameRequestCallback): number =>
  typeof requestAnimationFrame === 'function' ? requestAnimationFrame(cb) : (setTimeout(() => cb(performance.now()), 16) as unknown as number)
const defaultCaf = (id: number): void => (typeof cancelAnimationFrame === 'function' ? cancelAnimationFrame(id) : clearTimeout(id))

const easeInOut = (p: number) => (p < 0.5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2)
const easeOut = (p: number) => 1 - Math.pow(1 - p, 3)
const f1 = (v: number) => v.toFixed(1)

export class Overlay {
  private readonly group: SVGGElement
  private readonly engine: Engine
  private readonly opts: OverlayOptions
  private readonly pool: SVGGElement[] = []
  private readonly routes = new Map<number, PathInfo | null>()
  private handle: number | null = null
  private stopped = false

  constructor(group: SVGGElement, engine: Engine, opts: OverlayOptions) {
    this.group = group
    this.engine = engine
    this.opts = opts
  }

  get running(): boolean {
    return this.handle !== null
  }

  /** Ask for frames if there is anything to play (call after each ingest). */
  wake(): void {
    if (this.stopped || this.handle !== null || !this.engine.busy) return
    this.handle = (this.opts.raf ?? defaultRaf)(this.tick)
  }

  dispose(): void {
    this.stopped = true
    if (this.handle !== null) (this.opts.caf ?? defaultCaf)(this.handle)
    this.handle = null
    for (const el of this.pool) el.remove()
    this.pool.length = 0
    this.routes.clear()
  }

  /** One frame; public so tests can step it without a browser. */
  readonly tick = (): void => {
    this.handle = null
    const perf = this.opts.perf ?? (() => performance.now())
    const t0 = perf()
    const frame = this.engine.frame(this.opts.now())
    this.draw(frame.particles)
    this.engine.report(perf() - t0)
    this.opts.onFrame?.(frame)
    if (this.engine.busy && !this.stopped) this.handle = (this.opts.raf ?? defaultRaf)(this.tick)
    else this.hideFrom(0)
  }

  private shape(i: number): SVGGElement {
    const have = this.pool[i]
    if (have) return have
    const g = document.createElementNS(SVG, 'g') as SVGGElement
    const circle = (cls: string) => {
      const c = document.createElementNS(SVG, 'circle')
      c.setAttribute('class', cls)
      return c
    }
    const path = (cls: string, d: string) => {
      const p = document.createElementNS(SVG, 'path')
      p.setAttribute('class', cls)
      p.setAttribute('d', d)
      return p
    }
    const tail = (cls: string) => {
      const l = document.createElementNS(SVG, 'polyline')
      l.setAttribute('class', cls)
      return l
    }
    const ring = document.createElementNS(SVG, 'rect')
    ring.setAttribute('class', 'kt-p-ring')
    const label = document.createElementNS(SVG, 'text')
    label.setAttribute('class', 'kt-p-label')
    label.setAttribute('text-anchor', 'middle')
    // [tail glow, tail core, halo, head, ring, cross, check, label]
    g.append(tail('kt-p-tail-glow'), tail('kt-p-tail'), circle('kt-p-halo'), circle('kt-p-head'), ring, path('kt-p-cross', 'M-6,-6 L6,6 M6,-6 L-6,6'), path('kt-p-check', 'M-6,0 L-2,4.5 L6.5,-5'), label)
    this.group.appendChild(g)
    this.pool[i] = g
    return g
  }

  private route(p: Particle): PathInfo | null {
    if (this.routes.has(p.id)) return this.routes.get(p.id) ?? null
    const path = this.opts.path(p.from, p.to)
    const info = path && path.length ? measure(path) : null
    this.routes.set(p.id, info)
    return info
  }

  private draw(list: Array<Particle & { p: number }>): void {
    const live = new Set<number>()
    let i = 0
    for (const pt of list) {
      live.add(pt.id)
      if (pt.travel) {
        const info = this.route(pt)
        if (!info) continue
        const g = this.shape(i++)
        this.mark(g, pt)
        const size = Math.min(1.8, 1 + 0.25 * (pt.count - 1)) * (pt.prio >= 3 ? 1.15 : 1)
        const at = easeInOut(pt.p)
        const head = pointAt(info, at)
        const kids = g.children
        // a tapered streak behind the head: the last TAIL_PX of the route it has travelled
        const lag = Math.min(at, TAIL_PX / Math.max(1, info.total))
        const pts: string[] = []
        for (let k = 0; k <= TAIL_POINTS; k++) {
          const q = pointAt(info, at - lag + (lag * k) / TAIL_POINTS)
          pts.push(`${f1(q.x)},${f1(q.y)}`)
        }
        const trail = pts.join(' ')
        for (const k of [0, 1]) {
          kids[k].setAttribute('points', trail)
          kids[k].setAttribute('stroke-width', f1((k === 0 ? 9 : 3.2) * size))
          kids[k].setAttribute('display', 'inline')
        }
        place(kids[2] as SVGCircleElement, head, 12 * size)
        place(kids[3] as SVGCircleElement, head, 5.4 * size)
        for (let k = 4; k < 7; k++) kids[k].setAttribute('display', 'none')
        const label = kids[7] as SVGTextElement
        if (pt.label) {
          if (label.textContent !== pt.label) label.textContent = pt.label
          label.setAttribute('x', f1(head.x))
          label.setAttribute('y', f1(head.y - 15 * size))
          label.setAttribute('display', 'inline')
        } else label.setAttribute('display', 'none')
        g.setAttribute('opacity', f1(Math.min(1, pt.p / 0.06, (1 - pt.p) / 0.08 + 0.35)))
        continue
      }
      const box = this.opts.box(pt.to)
      if (!box) continue
      const g = this.shape(i++)
      this.mark(g, pt)
      const kids = g.children
      for (const k of [0, 1, 2, 3, 7]) kids[k].setAttribute('display', 'none')
      const grow = easeOut(pt.p)
      // a tool call is a small tick of the border; the rest a pulse that grows out of the anchor
      const reach = (pt.shape === 'spark' ? 7 : 26) * Math.min(1.6, 1 + 0.2 * (pt.count - 1)) * grow
      const ring = kids[4] as SVGRectElement
      ring.setAttribute('x', f1(box.x - box.w / 2 - reach))
      ring.setAttribute('y', f1(box.y - box.h / 2 - reach))
      ring.setAttribute('width', f1(box.w + 2 * reach))
      ring.setAttribute('height', f1(box.h + 2 * reach))
      ring.setAttribute('rx', f1(box.rx + reach / 2))
      ring.setAttribute('stroke-width', f1(pt.shape === 'spark' ? 2 : 4 - 2.5 * grow))
      ring.setAttribute('display', 'inline')
      const glyph = pt.shape === 'cross' ? kids[5] : pt.shape === 'check' ? kids[6] : null
      for (const k of [5, 6]) if (kids[k] !== glyph) kids[k].setAttribute('display', 'none')
      if (glyph) {
        glyph.setAttribute('display', 'inline')
        glyph.setAttribute('transform', `translate(${f1(box.x + box.w / 2 - 4)},${f1(box.y - box.h / 2 - 6 - 10 * grow)}) scale(${(1.7 - 0.5 * grow).toFixed(2)})`)
      }
      g.setAttribute('opacity', f1(1 - pt.p * pt.p))
    }
    for (const id of [...this.routes.keys()]) if (!live.has(id)) this.routes.delete(id)
    this.hideFrom(i)
  }

  private mark(g: SVGGElement, pt: Particle): void {
    g.setAttribute('class', `kt-p is-${pt.tone}${pt.travel ? ' is-travel' : ' is-blip'}`)
    g.setAttribute('data-src', pt.key)
    g.setAttribute('data-kind', pt.kind)
    g.removeAttribute('display')
  }

  private hideFrom(i: number): void {
    for (let j = i; j < this.pool.length; j++) {
      const g = this.pool[j]
      if (g.getAttribute('display') !== 'none') {
        g.setAttribute('display', 'none')
        g.removeAttribute('data-src')
      }
    }
  }
}

function place(c: SVGCircleElement, at: Pt, r: number): void {
  c.setAttribute('cx', f1(at.x))
  c.setAttribute('cy', f1(at.y))
  c.setAttribute('r', f1(r))
  c.setAttribute('display', 'inline')
}
