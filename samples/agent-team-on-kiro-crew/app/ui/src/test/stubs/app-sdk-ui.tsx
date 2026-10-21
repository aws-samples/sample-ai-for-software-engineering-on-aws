/**
 * Test stand-in for `@kirocrew/app-sdk/ui`.
 *
 * Each component renders the smallest real DOM that keeps a query meaningful and mirrors the host's
 * markup where it matters: Btn is a real <button>; PageHeader renders the title in a plain div (as the
 * host does, which is why the page passes its own h1); EmptyState's title is a div too;
 * MarkdownRenderer emits the raw text in <pre data-testid="markdown"> so a test can assert what would
 * be rendered without a markdown pipeline the host owns.
 */
import type { ComponentPropsWithoutRef, ReactNode } from 'react'

export const Card = (p: ComponentPropsWithoutRef<'div'>) => <div {...p} />
export const CardTitle = (p: ComponentPropsWithoutRef<'h3'>) => <h3 {...p} />
export const Btn = ({ primary, danger, ...p }: ComponentPropsWithoutRef<'button'> & { primary?: boolean; danger?: boolean }) => (
  <button data-primary={primary ? 'true' : undefined} data-danger={danger ? 'true' : undefined} {...p} />
)
export const SendBtn = Btn
export const Input = (p: ComponentPropsWithoutRef<'input'>) => <input {...p} />
export const SearchInput = (p: ComponentPropsWithoutRef<'input'>) => <input type="search" {...p} />
export const Badge = ({ variant, children, ...p }: ComponentPropsWithoutRef<'span'> & { variant: string; children: ReactNode }) => (
  <span data-variant={variant} {...p}>
    {children}
  </span>
)
export const StatCard = ({
  label,
  value,
  title,
  onClick,
  active,
  ...rest
}: ComponentPropsWithoutRef<'div'> & { label: string; value?: string | number | null; title?: string; onClick?: () => void; active?: boolean; accent?: boolean; delay?: number }) => {
  const { accent: _a, delay: _d, ...div } = rest as Record<string, unknown>
  return (
    <div data-testid="stat-card" title={title} data-active={active ? 'true' : undefined} {...(div as ComponentPropsWithoutRef<'div'>)}>
      {onClick ? (
        <button type="button" onClick={onClick}>
          {label}
        </button>
      ) : (
        <span>{label}</span>
      )}
      <span>{value ?? ''}</span>
    </div>
  )
}
export const Skeleton = (p: ComponentPropsWithoutRef<'div'>) => <div data-testid="skeleton" {...p} />
export const ContentSkeleton = ({ rows = 5 }: { rows?: number }) => <div data-testid="content-skeleton">{rows}</div>
export const EmptyState = ({ icon, title, subtitle, action }: { icon: ReactNode; title: string; subtitle?: string; action?: ReactNode }) => (
  <div data-testid="empty-state">
    {icon}
    <div data-testid="empty-state-title">{title}</div>
    {subtitle ? <div data-testid="empty-state-subtitle">{subtitle}</div> : null}
    {action ? <div data-testid="empty-state-action">{action}</div> : null}
  </div>
)
export const PageHeader = ({ title, subtitle, actions }: { title: ReactNode; subtitle?: string; actions?: ReactNode }) => (
  <div data-testid="page-header">
    <div data-testid="page-header-title">{title}</div>
    {subtitle ? <div>{subtitle}</div> : null}
    {actions}
  </div>
)
export const Toggle = ({ checked, onChange, disabled, label }: { checked: boolean; onChange: (v: boolean) => void; disabled?: boolean; label?: string }) => (
  <button role="switch" aria-checked={checked} aria-label={label} disabled={disabled} onClick={() => onChange(!checked)} />
)
export const InfoTip = ({ text }: { text: string }) => <span data-testid="info-tip" title={text} />
export function SegmentedControl<T extends string>({
  segments,
  value,
  onChange,
}: {
  segments: { key: T; label: string; count?: number; disabled?: boolean }[]
  value: T
  onChange: (v: T) => void
}) {
  return (
    <div role="group" data-testid="segmented">
      {segments.map((s) => (
        <button key={s.key} aria-pressed={s.key === value} disabled={s.disabled} onClick={() => onChange(s.key)}>
          {s.label}
        </button>
      ))}
    </div>
  )
}
export const MarkdownRenderer = ({ content }: { content: string }) => <pre data-testid="markdown">{content}</pre>
export const AimBadge = undefined
