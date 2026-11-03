/**
 * 按评审意见再改一轮: the run ended on a 要改 review after its review rounds (运行结束：评审打回 … 仍要改，交给人决定). The person
 * sends the last review back once more with their decision (POST /runs/{rid}/retry {note, by}); the roles it names get
 * the review and the decision, the decision winning where they differ. The decision is prefilled for a justification
 * the review names: a new empty commit that cites it and the triage's citations, so that no merged history is rewritten.
 */
import { useState } from 'react'
import type { RunDetail } from '../types'
import { errorText } from './useBoard'

const SIGNER_KEY = 'vstatd-team:signer'

/** The decision proposed for the findings the review names: each justification gets an empty commit citing its pages. */
export function redoNote(run: RunDetail): string {
  const said = run.review_redo?.summary ?? ''
  const ids = [...new Set(said.match(/F-\d{3}/g) ?? [])]
  const rows = (run.backlog?.triage?.findings ?? []).filter((f) => ids.includes(f.id) && f.decision === 'justify' && f.cites.length > 0)
  if (!rows.length) return ''
  return ['不改写已经合入运行分支的提交（不 amend、不 rebase）。',
    ...rows.map((f) => `${f.id}：追加一个空提交（git commit --allow-empty），提交说明写 ${f.id} 和分诊里它的引用 ${f.cites.join(' ')}；代码和已有的 NOLINT 不用改。`)].join('\n')
}

export function ReviewRedoBox({ run, onConfirm }: { run: RunDetail; onConfirm: (body: { note: string; by: string }) => Promise<void> }) {
  const redo = run.review_redo!
  const [note, setNote] = useState(() => redoNote(run))
  const [by, setBy] = useState(() => (typeof localStorage !== 'undefined' && localStorage.getItem(SIGNER_KEY)) || '')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const title = (k: string) => run.roles.find((l) => l.key === k)?.title ?? k
  const confirm = async () => {
    if (!by.trim()) return setErr('写下你的名字（谁做的决定）')
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
      <b>✋ 评审还是要改，交给你决定</b>
      <span>{title(redo.role)}：{redo.summary}</span>
      <span className="kt-dim">按评审意见再改一轮，交给 {redo.targets.map(title).join('、')}；你写的决定和评审意见冲突时以你的为准。不同意评审就停止这次运行。</span>
      <textarea className="kt-gate-note" rows={3} value={note} onChange={(e) => setNote(e.target.value)} aria-label="你的决定" placeholder="评审留给人决定的事，你怎么定" />
      <span className="kt-start-actions">
        <label className="kt-start-field is-narrow"><span>决定人</span><input aria-label="决定人" value={by} maxLength={60} onChange={(e) => setBy(e.target.value)} /></label>
        <button type="button" className="kt-btn is-solid is-primary" onClick={confirm} disabled={busy}>{busy ? '正在提交…' : '同意，按评审意见再改一轮'}</button>
      </span>
      {err && <p className="kt-error" role="alert">{err}</p>}
    </div>
  )
}
