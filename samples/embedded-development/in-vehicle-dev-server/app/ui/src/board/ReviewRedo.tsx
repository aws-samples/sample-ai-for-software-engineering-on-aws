/**
 * 按评审意见再改一轮: the run ended on a 要改 review after its review rounds (运行结束：评审打回 … 仍要改，交给人决定). The person
 * sends the last review back once more with their decision (POST /runs/{rid}/retry {note, by}); the roles it names get
 * the review and the decision, the decision winning where they differ. The decision is prefilled for a justification
 * the review names: a new empty commit that cites it and the triage's citations, so that no merged history is rewritten.
 */
import { useState } from 'react'
import type { RunDetail } from '../types'
import { errorText } from './useBoard'
import { t as tr } from '../i18n'

const SIGNER_KEY = 'vstatd-team:signer'

/** The decision proposed for the findings the review names: each justification gets an empty commit citing its pages. */
export function redoNote(run: RunDetail): string {
  const said = run.review_redo?.summary ?? ''
  const ids = [...new Set(said.match(/F-\d{3}/g) ?? [])]
  const rows = (run.backlog?.triage?.findings ?? []).filter((f) => ids.includes(f.id) && f.decision === 'justify' && f.cites.length > 0)
  if (!rows.length) return ''
  return [tr('board.ReviewRedo.1'),
    ...rows.map((f) => tr('board.ReviewRedo.2', { p0: f.id, p1: f.id, p2: f.cites.join(' ') }))].join('\n')
}

export function ReviewRedoBox({ run, onConfirm }: { run: RunDetail; onConfirm: (body: { note: string; by: string }) => Promise<void> }) {
  const redo = run.review_redo!
  const [note, setNote] = useState(() => redoNote(run))
  const [by, setBy] = useState(() => (typeof localStorage !== 'undefined' && localStorage.getItem(SIGNER_KEY)) || '')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const title = (k: string) => run.roles.find((l) => l.key === k)?.title ?? k
  const confirm = async () => {
    if (!by.trim()) return setErr(tr('board.ReviewRedo.3'))
    setBusy(true)
    setErr('')
    try {
      localStorage.setItem(SIGNER_KEY, by.trim())
      await onConfirm({ note: note.trim(), by: by.trim() })
    } catch (x) {
      setErr(errorText(x))
      setBusy(false)
    }
  }
  return (
    <div className="kt-ready-pending" role="status" data-testid="kt-review-redo">
      <b>{tr('board.ReviewRedo.4')}</b>
      <span>{title(redo.role)}{tr('board.ReviewRedo.5')}{redo.summary}</span>
      <span className="kt-dim">{tr('board.ReviewRedo.6')} {redo.targets.map(title).join(tr('board.ReviewRedo.7'))}{tr('board.ReviewRedo.8')}</span>
      <textarea className="kt-gate-note" rows={3} value={note} onChange={(e) => setNote(e.target.value)} aria-label={tr('board.ReviewRedo.9')} placeholder={tr('board.ReviewRedo.10')} />
      <span className="kt-start-actions">
        <label className="kt-start-field is-narrow"><span>{tr('board.ReviewRedo.11')}</span><input aria-label={tr('board.ReviewRedo.11')} value={by} maxLength={60} onChange={(e) => setBy(e.target.value)} /></label>
        <button type="button" className="kt-btn is-solid is-primary" onClick={confirm} disabled={busy}>{busy ? tr('board.ReviewRedo.12') : tr('board.ReviewRedo.13')}</button>
      </span>
      {err && <p className="kt-error" role="alert">{err}</p>}
    </div>
  )
}
