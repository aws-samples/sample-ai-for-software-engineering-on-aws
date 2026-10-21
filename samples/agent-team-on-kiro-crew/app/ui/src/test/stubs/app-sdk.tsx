/**
 * Test stand-in for `@kirocrew/app-sdk` (vitest.config.ts aliases the specifier here).
 *
 * The real module is provided by the dashboard at runtime through its import map; there is no npm
 * package. The stub is behavioural, not a spy soup: useAppApi dispatches to a route table a test
 * installs with setApiRoutes, so component tests run the real request paths and the real error
 * decoding (errorText) instead of asserting that a mock was called. It has api.raw / api.request (the host has both; setApiRaw(false) plays an older host without raw).
 */
import { createContext, useContext, type ReactNode } from 'react'

export interface AppApi {
  get<T = unknown>(path: string, init?: RequestInit): Promise<T>
  post<T = unknown>(path: string, body?: unknown, init?: RequestInit): Promise<T>
  put<T = unknown>(path: string, body?: unknown, init?: RequestInit): Promise<T>
  patch<T = unknown>(path: string, body?: unknown, init?: RequestInit): Promise<T>
  del<T = unknown>(path: string, init?: RequestInit): Promise<T>
  raw?(path: string, init?: RequestInit): Promise<Response>
  request?<T = unknown>(path: string, init?: RequestInit): Promise<T>
}

type Method = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
/** A route's answer; throw a StubApiError (or anything) to fail the request. */
export type RouteHandler = (body: unknown, path: string, init?: RequestInit) => unknown | Promise<unknown>

const routes = new Map<string, RouteHandler>()
export const apiCalls: { method: Method; path: string; body: unknown }[] = []
export const navigations: string[] = []
export const badges: number[] = []
export const notifications: { message: string; type?: string }[] = []
export const chatLaunches: { agent?: string; message?: string; slotKey?: string; autoSend?: boolean }[] = []
let rawSupported = true
let chatListFails = false

/** Install handlers keyed `"GET /api/apps/aidlc-team/board"`. A `*` at the end matches a prefix (query strings included). */
export function setApiRoutes(table: Record<string, RouteHandler>): void {
  routes.clear()
  apiCalls.length = 0
  for (const [key, handler] of Object.entries(table)) routes.set(key, handler)
}

/** false: useAppApi() has no raw / request, like an older host. */
export function setApiRaw(supported: boolean): void {
  rawSupported = supported
}

/** true: ChatMessageList throws when rendered (for the fallback path). */
export function setChatMessageListFails(fails: boolean): void {
  chatListFails = fails
}

/** Back to an empty table and empty records (setup.ts calls it before every test). */
export function resetStubs(): void {
  routes.clear()
  apiCalls.length = 0
  navigations.length = 0
  badges.length = 0
  notifications.length = 0
  chatLaunches.length = 0
  rawSupported = true
  chatListFails = false
}

export class StubApiError extends Error {
  constructor(
    readonly status: number,
    readonly body: unknown,
  ) {
    super(`API ${status}: ${typeof body === 'string' ? body : JSON.stringify(body)}`)
  }
}

/** A backend error answer, `{"error": message, "code": code}` with `status`. */
export function apiError(status: number, code: string, message: string): StubApiError {
  return new StubApiError(status, { error: message, code })
}

async function dispatch(method: Method, path: string, body?: unknown, init?: RequestInit): Promise<unknown> {
  apiCalls.push({ method, path, body })
  const exact = routes.get(`${method} ${path}`)
  if (exact) return exact(body, path, init)
  let best: [number, RouteHandler] | null = null
  for (const [key, handler] of routes) {
    const [m, pattern] = key.split(' ')
    if (m !== method || !pattern?.endsWith('*')) continue
    const prefix = pattern.slice(0, -1)
    if (path.startsWith(prefix) && (!best || prefix.length > best[0])) best = [prefix.length, handler]
  }
  if (best) return best[1](body, path, init)
  throw new StubApiError(404, { error: 'no stub route', code: 'route_not_found', details: { path } })
}

const methodOf = (init?: RequestInit): Method => ((init?.method || 'GET').toUpperCase() as Method)

const api: AppApi = {
  get: (path, init) => dispatch('GET', path, undefined, init) as Promise<never>,
  post: (path, body, init) => dispatch('POST', path, body, init) as Promise<never>,
  put: (path, body, init) => dispatch('PUT', path, body, init) as Promise<never>,
  patch: (path, body, init) => dispatch('PATCH', path, body, init) as Promise<never>,
  del: (path, init) => dispatch('DELETE', path, undefined, init) as Promise<never>,
}

const withRaw: AppApi = {
  ...api,
  raw: async (path, init) => {
    const data = await dispatch(methodOf(init), path, init?.body, init)
    return new Response(data === undefined ? null : JSON.stringify(data), { status: 200, headers: { 'Content-Type': 'application/json' } })
  },
  request: (path, init) => dispatch(methodOf(init), path, init?.body, init) as Promise<never>,
}

export function useAppApi(): AppApi {
  return rawSupported ? withRaw : api
}

export function useNavigate(): (path: string) => void {
  return (path) => {
    navigations.push(path)
    window.history.pushState(null, '', path)
  }
}

export function useNavBadge(): (count: number) => void {
  return (count) => void badges.push(count)
}

export function useNotify() {
  return (message: string, opts?: { type?: 'info' | 'success' | 'error' }) => void notifications.push({ message, type: opts?.type })
}

export function useAppInfo() {
  return { name: 'aidlc-team', version: '0.1.0', permissions: { api: ['/api/apps/aidlc-team'], events: [] } }
}

export function useTheme() {
  const mode = document.documentElement.dataset.mode === 'dark' ? ('dark' as const) : ('light' as const)
  return { mode, accent: '#5a8fd4', colorTheme: 'default' }
}

export function useAppEvents(_event: string, _cb: (data: unknown) => void): void {
  // The real host never dispatches these; a stub that fired would let a test pass on a path that
  // cannot work in production.
}

export function useChatLauncher() {
  return { openChat: (opts?: { agent?: string; message?: string; slotKey?: string; autoSend?: boolean }) => void chatLaunches.push(opts ?? {}) }
}

export function useChatSession() {
  return {
    status: 'no-session' as const,
    slotKey: null,
    slotInfo: null,
    creating: false,
    error: null,
    openChat: () => {},
    createSession: async () => {},
    resetSession: () => {},
  }
}

const AppApiContext = createContext<AppApi | null>(null)
export function AppApiProvider({ children }: { children: ReactNode }) {
  return <AppApiContext.Provider value={api}>{children}</AppApiContext.Provider>
}

export const ChatEmbed = ({ slotKey }: { slotKey: string }) => <div data-testid="chat-embed">{slotKey}</div>
export const ChatPanel = ChatEmbed
export interface StubChatMessage {
  role: string
  content: string
}
export const ChatMessageList = ({ messages, running }: { messages: StubChatMessage[]; running: boolean }) => {
  if (chatListFails) throw new Error('ChatMessageList failed')
  return (
    <div data-testid="chat-messages" data-running={running ? 'true' : undefined}>
      {messages.map((m, i) => (
        <div key={i} data-role={m.role}>
          {m.content}
        </div>
      ))}
    </div>
  )
}
export const defaultMessageRenderers: readonly unknown[] = []
export const GROUPED_ROLES: readonly string[] = ['thinking', 'permission']
export const ToolCallPill = () => null
export function mergeRenderers(extra: readonly unknown[]) {
  return extra
}
export function resolveRenderer() {
  return undefined
}
export function parseOptions(content: string) {
  return { text: content, options: [] as string[], multi: false, isPlan: false }
}
export function deriveFollowUpOptions() {
  return { followUpOptions: [] as string[], followUpIsPlan: false }
}
export function extractSteeringAcks(content: string) {
  return { cleaned: content, acks: [] as string[] }
}
export function stripPartialOptionMarker(text: string) {
  return text
}
export function checkSubscribeAllowed() {
  return { level: 'ok' as const }
}

// Keep the context reachable for tests that render a component outside the page.
export function useAppApiContext(): AppApi | null {
  return useContext(AppApiContext)
}
