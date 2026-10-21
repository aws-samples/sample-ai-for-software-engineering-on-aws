/**
 * Ambient typings for the modules the KiroCrew dashboard provides at RUNTIME through its import map.
 *
 * There is no published npm package for these; the host maps the bare specifiers to
 * `/vendor/*.mjs` stubs that re-export a fixed list of names from `window.__kirocrew_modules`
 * (verified against the running gateway bundle, see docs/research/03-kirocrew-frontend-host-contract.md §1.3).
 *
 * Importing a name that is NOT in the stub's export list is a browser link-time SyntaxError that
 * fails the whole app bundle, so these declarations deliberately list only the real exports.
 * `lucide-react` is the exception: use its DEFAULT export (a Proxy over every icon) rather than a
 * named import, because only ~40 icons are named exports.
 */

declare module '@kirocrew/app-sdk' {
  import type { ReactNode } from 'react'

  /**
   * Every method rejects with an AppApiError (`message` = "API <status>: <body>", plus `status` and
   * `body`) on a non-2xx answer. post/put/patch JSON-encode `body` (Content-Type application/json
   * unless `init.headers` says otherwise).
   */
  export interface AppApi {
    get<T = unknown>(path: string, init?: RequestInit): Promise<T>
    post<T = unknown>(path: string, body?: unknown, init?: RequestInit): Promise<T>
    put<T = unknown>(path: string, body?: unknown, init?: RequestInit): Promise<T>
    patch<T = unknown>(path: string, body?: unknown, init?: RequestInit): Promise<T>
    del<T = unknown>(path: string, init?: RequestInit): Promise<T>
    /**
     * The fetch Response itself, for a body that is not JSON (an upload: `{method: 'POST', body: file,
     * headers}`). Same path checks as the others. Missing on older hosts: check before use.
     */
    raw?(path: string, init?: RequestInit): Promise<Response>
    /** fetch with the given init, the answer parsed as JSON (undefined for an empty body). Older hosts lack it. */
    request?<T = unknown>(path: string, init?: RequestInit): Promise<T>
  }
  export interface AppPermissions { api: string[]; events: string[] }
  export interface AppInfo { name: string; version: string; permissions: AppPermissions }
  /**
   * `mode` reads `document.documentElement.dataset.theme`, which is only `dark`/`light` for the
   * default theme (other themes are `<slug>-dark`). Prefer the app's own `useHostMode()` which
   * reads `data-mode`. `colorTheme` is always `'default'` (the host never sets the attribute).
   */
  export interface AppTheme { mode: 'dark' | 'light'; accent: string; colorTheme: string }
  /** slotKey: open that existing session (the host navigates to /chat?sid=<slotKey>); autoSend false: do not send message. */
  export interface ChatLaunchOptions { agent?: string; message?: string; slotKey?: string; autoSend?: boolean }

  /** Permission-scoped fetch. Pass ABSOLUTE same-origin paths; cookie auth only. */
  export function useAppApi(): AppApi
  /**
   * Subscribes to `window` CustomEvent `mc:app:<event>`. The host does NOT forward its `app_event`
   * WebSocket frames to these, so nothing arrives unless the app dispatches them itself.
   */
  export function useAppEvents(event: string, callback: (data: unknown) => void): void
  export function useTheme(): AppTheme
  export function useAppInfo(): AppInfo
  /** Host router navigation, e.g. `/apps/aidlc-studio?view=actions` or `/chat?sid=<slot>`. */
  export function useNavigate(): (path: string) => void
  /** Dispatches `mc:notify`; no host listener exists today — render your own banner instead. */
  export function useNotify(): (message: string, opts?: { type?: 'info' | 'success' | 'error' }) => void
  /** Works: sets the sidebar badge count for this app (0/undefined clears). */
  export function useNavBadge(): (count: number) => void
  export function useChatLauncher(): { openChat(opts?: ChatLaunchOptions): void }

  export interface ChatMessage {
    role: string
    content: string
    cls: string
    ts?: string
    rawText?: string
    meta?: Record<string, unknown>
    kind?: string
  }
  export interface ParsedOptions { text: string; options: string[]; multi: boolean; isPlan: boolean }
  export interface FollowUpDerivation { followUpOptions: string[]; followUpIsPlan: boolean }
  export function parseOptions(content: string): ParsedOptions
  export function deriveFollowUpOptions(messages: ChatMessage[], isStreaming: boolean): FollowUpDerivation
  export function extractSteeringAcks(content: string): { cleaned: string; acks: string[] }
  export function stripPartialOptionMarker(text: string): string
  export function checkSubscribeAllowed(event: string, declared: string[]): { level: string; hint?: string }

  export interface ChatSessionOptions {
    workspacePath: string
    label: string
    agent?: string
    appName?: string
    seedTemplate?: (o: { label: string; path: string; isPackage: boolean }) => string
  }
  export interface ChatSessionState {
    status: 'loading' | 'ready' | 'no-session' | 'error'
    slotKey: string | null
    slotInfo: { key: string; title: string; messages: number; running: boolean } | null
    creating: boolean
    error: string | null
    openChat: () => void
    createSession: () => Promise<void>
    resetSession: () => void
  }
  /** Requires `/api/chat` in permissions.api. */
  export function useChatSession(opts: ChatSessionOptions): ChatSessionState
  export const ChatEmbed: (props: {
    slotKey: string
    agent?: string
    placeholder?: string
    frameless?: boolean
    startAtBottom?: boolean
    onSend?: (message: string) => Promise<unknown> | void
  }) => ReactNode
  export const ChatPanel: (props: { slotKey: string }) => ReactNode
  export interface MessageRenderContext {
    index: number
    messages: ChatMessage[]
    running: boolean
    key: string
    wrapper: (children: ReactNode, isUser?: boolean) => ReactNode
    row: (children: ReactNode, tight?: boolean) => ReactNode
    onFileOpen?: (path: string) => void
    autoDeniedIds?: string[]
    renderTool?: (m: ChatMessage) => ReactNode
  }
  export interface MessageRenderer {
    id: string
    roles: string[]
    match?: (m: ChatMessage) => boolean
    render: (m: ChatMessage, ctx: MessageRenderContext) => ReactNode
  }
  export const ChatMessageList: (props: {
    messages: ChatMessage[]
    running: boolean
    contentWidth?: string
    onApprove?: (approvalId: string, decision: string) => void
    onFileOpen?: (path: string) => void
    renderers?: readonly MessageRenderer[]
  }) => ReactNode
  export const defaultMessageRenderers: readonly MessageRenderer[]
  export function mergeRenderers(extra: readonly MessageRenderer[]): readonly MessageRenderer[]
  export function resolveRenderer(message: ChatMessage, renderers: readonly MessageRenderer[]): MessageRenderer | undefined
  export const ToolCallPill: (props: Record<string, unknown>) => ReactNode
  export const GROUPED_ROLES: readonly string[]
  export const AppApiProvider: (props: Record<string, unknown>) => ReactNode
}

declare module '@kirocrew/app-sdk/ui' {
  import type { ComponentPropsWithoutRef, ReactNode } from 'react'

  type DivProps = Omit<ComponentPropsWithoutRef<'div'>, 'dangerouslySetInnerHTML'>
  /** Note the built-in `mb-4`; override with className when you need a flush layout. */
  export const Card: (props: DivProps) => ReactNode
  export const CardTitle: (props: Omit<ComponentPropsWithoutRef<'h3'>, 'dangerouslySetInnerHTML'>) => ReactNode
  export const Btn: (props: ComponentPropsWithoutRef<'button'> & { danger?: boolean; primary?: boolean }) => ReactNode
  export const SendBtn: (props: ComponentPropsWithoutRef<'button'>) => ReactNode
  export const Input: (props: ComponentPropsWithoutRef<'input'>) => ReactNode
  /** `className` lands on the wrapper, not the input. */
  export const SearchInput: (props: ComponentPropsWithoutRef<'input'>) => ReactNode
  export const Badge: (props: ComponentPropsWithoutRef<'span'> & { variant: 'ok' | 'err' | 'warn' | 'aim' | 'muted'; children: ReactNode }) => ReactNode
  export const StatCard: (props: DivProps & {
    label: string
    value?: string | number | null
    accent?: boolean
    colorClass?: string
    delay?: number
    onClick?: () => void
    active?: boolean
    title?: string
  }) => ReactNode
  export const Skeleton: (props: DivProps) => ReactNode
  export const ContentSkeleton: (props: { rows?: number }) => ReactNode
  export const EmptyState: (props: { icon: ReactNode; title: string; subtitle?: string; action?: ReactNode; testId?: string }) => ReactNode
  export const PageHeader: (props: { title: ReactNode; subtitle?: string; actions?: ReactNode }) => ReactNode
  export const Toggle: (props: {
    checked: boolean
    onChange: (v: boolean) => void
    disabled?: boolean
    label?: string
    describedBy?: string
    tone?: 'accent' | 'muted'
  }) => ReactNode
  export const InfoTip: (props: { text: string; placement?: 'auto' | 'top' }) => ReactNode
  export interface Segment<T extends string> {
    key: T
    label: string
    icon?: ReactNode
    count?: number
    tooltip?: string
    disabled?: boolean
  }
  /** Auto-collapses by measuring the PARENT width; pass `collapse={false}` inside shrink-0/inline-flex parents. */
  export const SegmentedControl: <T extends string>(props: {
    segments: Segment<T>[]
    value: T
    onChange: (v: T) => void
    layoutId?: string
    collapse?: boolean
  }) => ReactNode
  /**
   * Allowlist-sanitising markdown renderer (raw HTML escaped, no scripts, mermaid in strict mode).
   * Wrap it in an element with class `msg-content` to inherit the host's prose styles.
   */
  export const MarkdownRenderer: (props: {
    content: string
    streaming?: boolean
    onFileOpen?: (path: string, opts?: { line?: number; endLine?: number }) => void
    onFolderOpen?: (path: string) => void
    onArtifactOpen?: (slug: string) => void
    rawMode?: boolean
    sourcePos?: boolean
    messageTs?: string
    slotKey?: string
    glow?: boolean
    smooth?: boolean
    softBreaks?: boolean
    compactImages?: boolean
    linkPreviews?: boolean
  }) => ReactNode
  /** Present in the vendor stub but resolves to `undefined` on the host — never render it. */
  export const AimBadge: undefined
}

/**
 * `lucide-react` — icons, via the DEFAULT export only.
 *
 * The host's vendor stub names ~40 icons and re-exports the whole set behind a Proxy on `default`
 * (`03 §1.3`). A named import of any other icon compiles and then throws
 * `does not provide an export named 'X'` at link time in the browser, taking the entire app module
 * with it. So the named exports are deliberately NOT declared here: the only importable shape is the
 * default Proxy, indexed by name, which is what `ui/src/shell/Icon.tsx` does.
 */
declare module 'lucide-react' {
  import type { ComponentType, SVGProps } from 'react'

  export type LucideProps = SVGProps<SVGSVGElement> & {
    size?: number | string
    strokeWidth?: number | string
    absoluteStrokeWidth?: boolean
  }
  export type LucideIcon = ComponentType<LucideProps>

  /** A Proxy over every icon in the set; an unknown name yields `undefined`, never a throw. */
  const icons: Record<string, LucideIcon | undefined>
  export default icons
}
