/**
 * Test stand-in for `lucide-react`.
 *
 * The real module is a large icon set the host provides. Tests only need every icon name to resolve to
 * something renderable and inert, so the default export is a Proxy that mints an empty element per
 * name, matching how the app consumes it (`import lucide from 'lucide-react'`, indexed by name): the
 * only form that works against the host's vendor stub. The element records the name, the size and
 * the colour (style.color), so a test can tell which icon was drawn in which colour.
 */
import type { CSSProperties, SVGProps } from 'react'

type IconProps = SVGProps<SVGSVGElement> & { size?: number | string }

function makeIcon(name: string) {
  const Icon = ({ size = 16, style, className }: IconProps) => (
    <span data-icon={name} data-size={String(size)} className={className} style={{ color: (style as CSSProperties | undefined)?.color }} aria-hidden="true" />
  )
  Icon.displayName = name
  return Icon
}

const cache = new Map<string, ReturnType<typeof makeIcon>>()
const handler: ProxyHandler<Record<string, unknown>> = {
  get: (_target, prop) => {
    if (typeof prop !== 'string') return undefined
    if (prop === '__esModule') return true
    if (!cache.has(prop)) cache.set(prop, makeIcon(prop))
    return cache.get(prop)
  },
}

const proxy = new Proxy({}, handler) as Record<string, ReturnType<typeof makeIcon>>
export default proxy
