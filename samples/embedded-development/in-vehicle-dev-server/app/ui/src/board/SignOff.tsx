/**
 * 签字单: the right shift on the board, at the end of a run. Everything a person needs to sign for the release on one
 * card: the requirement, what people decided at the gates, what the machine checks said (with a release check: the
 * independent rerun's release.sh verdict, the checks whose verdict changed on it, and the evidence page, shown as plain
 * text: it quotes what agents wrote), what the independent review concluded, and what the agents did. Then the one
 * step no agent takes: a person signs (签字放行), and the board keeps who, when and what the checks said then. The
 * button stays off while the run cannot be signed (release.sh has not passed on the rerun). The signature merges the
 * run's PR (its run branch) into main.
 */
import { evText, signBlock } from '../i18n/events'
import { useState, type FormEvent } from 'react'
import type { ReleaseView, RunDetail } from '../types'
import { CASE_GROUPS, caseGroup, fmtCredits, fmtSpan } from './format'
import { RoleIcon } from './RoleIcon'
import { locale, lang, t as tr } from '../i18n'

const SIGNER_KEY = 'vstatd-team:signer'
/** An amount in yuan: ¥20.6 万 · ¥8,000 · '' (none). */
const money = (n: number | null | undefined) => (n == null ? '' : n >= 1e4 ? tr('board.SignOff.1', { p0: (n / 1e4).toFixed(1), p1: Math.round(n / 1e3).toLocaleString(locale()) }) : `¥${Math.round(n).toLocaleString(locale())}`)

/** Where the run's PR stands, in the 签字单's words. */
export function prState(run: RunDetail): string {
  const pr = run.pr
  if (!pr) return ''
  if (pr.state === 'open') return tr('board.SignOff.2')
  if (pr.state === 'merged') return tr('board.SignOff.3', { p0: pr.sha })
  return run.imported ? tr('board.SignOff.4') : tr('board.SignOff.5')
}

export function SignOff({ run, onSign }: { run: RunDetail; onSign?: (by: string, note: string) => Promise<void> }) {
  const [by, setBy] = useState(() => (typeof localStorage !== 'undefined' && localStorage.getItem(SIGNER_KEY)) || '')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const t = run.tests
  const groups = CASE_GROUPS.map((g, i) => {
    const cases = t.cases.filter((c) => caseGroup(c.ac) === i)
    return { ...g, total: cases.length, passed: cases.filter((c) => c.status === 'pass').length }
  }).filter((g) => g.total > 0)
  const over = run.overruled // a person approved over a review that still said 要改
  const gates = run.roles.filter((l) => l.gate_label && run.gate_notes[l.key] && l.key !== over?.role)
  const sentBack = run.events.filter((e) => e.kind === 'bounce' && e.from === 'person')
  // in the order they were made: an approval sits where its 「人批准了…」 event is
  const approvedAt = (key: string) => Math.max(-1, ...run.events.filter((e) => e.kind === 'approved' && e.role === key).map((e) => e.seq))
  const decisions = [
    ...sentBack.map((e) => ({ seq: e.seq, key: `b${e.seq}`, back: true, text: e.code && lang() === 'en' ? evText(e, run.roles) : e.text.replace(/^人/, '') })), // i18n-keep: the Chinese text starts with 人 (the person)
    ...gates.map((l) => ({ seq: approvedAt(l.key), key: l.key, back: false, text: tr('board.SignOff.6', { p0: l.gate_label, p1: run.gate_notes[l.key] }) })),
  ].sort((a, b) => (a.seq < 0 ? Infinity : a.seq) - (b.seq < 0 ? Infinity : b.seq))
  const review = run.roles.find((l) => l.writable.length === 0)
  const commits = run.roles.reduce((n, l) => n + l.commits.length, 0)
  const members = run.roles.filter((l) => l.status !== 'skipped')
  const green = t.total > 0 && t.failed === 0
  const rel = run.release
  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!onSign || !by.trim() || busy || run.sign_block) return
    setBusy(true)
    setErr('')
    try {
      localStorage.setItem(SIGNER_KEY, by.trim())
      await onSign(by.trim(), note.trim())
    } catch (x) {
      setErr(x instanceof Error ? x.message : String(x))
    } finally {
      setBusy(false)
    }
  }
  return (
    <section id="kt-signoff" className={`kt-sign${run.signoff ? ' is-signed' : ''}`} aria-label={tr('board.SignOff.7')} data-testid="kt-sign">
      <header className="kt-sign-head">
        <h2>{tr('board.SignOff.7')}</h2>
        <p className="kt-dim">{tr('board.SignOff.8')}</p>
      </header>
      <dl className="kt-sign-grid">
        <div>
          <dt>{tr('board.SignOff.9')}</dt>
          <dd>{run.requirement || run.title}</dd>
        </div>
        {run.issue && (
          <div>
            <dt>Issue · PR</dt>
            <dd data-testid="kt-sign-pr">
              Issue {run.issue.id}{tr('board.SignOff.10')}{run.issue.kind} · {run.issue.reporter}{tr('board.SignOff.11')}
              {run.pr ? tr('board.SignOff.12', { p0: run.pr.number, p1: run.pr.head, p2: run.pr.base, p3: prState(run) }) : ''}
            </dd>
          </div>
        )}
        <div>
          <dt>{tr('board.SignOff.13')}</dt>
          <dd>
            {gates.length || sentBack.length || over ? (
              <ul>
                {decisions.map((d) => (
                  <li key={d.key} className={d.back ? 'kt-sign-back' : undefined}>
                    {d.text}
                  </li>
                ))}
                {over && (
                  <li className="kt-sign-back" data-testid="kt-sign-overruled">
                    {tr('board.SignOff.14')}{run.roles.find((l) => l.key === over.role)?.gate_label || over.role}{tr('board.SignOff.15')}{over.note}
                  </li>
                )}
              </ul>
            ) : (
              tr('board.SignOff.16')
            )}
          </dd>
        </div>
        {(run.risks ?? []).length > 0 && (
          <div>
            <dt>{tr('board.SignOff.17')}</dt>
            <dd data-testid="kt-sign-risks">
              <ul>
                {(run.risks ?? []).map((r, i) => (
                  <li key={i} className="kt-sign-back">
                    {r.what}{r.amount != null ? ` ${money(r.amount)}` : ''}{tr('board.SignOff.10')}{r.gate}{tr('board.SignOff.18')}
                  </li>
                ))}
              </ul>
            </dd>
          </div>
        )}
        <div>
          <dt>{tr('board.SignOff.19')}</dt>
          <dd>
            {rel ? <Release rel={rel} /> : (
              <>
                <b className={green ? 'kt-ok' : 'kt-bad'}>
                  {t.passed}/{t.total} {tr('board.SignOff.20')}
                </b>
                <ul className="kt-sign-groups">
                  {groups.map((g) => (
                    <li key={g.prefix} className={g.passed === g.total ? 'is-ok' : 'is-bad'}>
                      {g.label} {g.passed}/{g.total}
                    </li>
                  ))}
                </ul>
              </>
            )}
          </dd>
        </div>
        <div>
          <dt>{tr('board.SignOff.21')}</dt>
          <dd>{review ? tr('board.SignOff.22', { p0: review.title, p1: review.summary || tr('board.SignOff.noVerdict'), p2: over?.role === review.key ? tr('board.SignOff.overruled') : '' }) : tr('board.SignOff.23')}</dd>
        </div>
        <div>
          <dt>{tr('board.SignOff.24')}</dt>
          <dd>
            {tr('board.SignOff.work', { members: members.length, commits, time: fmtSpan(run.wall_s), credits: fmtCredits(run.credits) })}
          </dd>
        </div>
      </dl>
      {rel && (
        <details className="kt-sign-evidence" open={!run.signoff} data-testid="kt-sign-evidence">
          <summary>{tr('board.SignOff.27')}</summary>
          {rel.evidence ? <pre className="kt-evidence">{rel.evidence}</pre> : <p className="kt-dim">{tr('board.SignOff.noEvidence', { results: rel.results })}</p>}
        </details>
      )}
      {run.signoff ? (
        <p className="kt-sign-done" role="status">
          <RoleIcon role="sign" size={16} /> <b>{run.signoff.by}</b> {tr('board.SignOff.signed', { at: new Date(run.signoff.at * 1000).toLocaleString(locale(), { hour12: false }),
            note: run.signoff.note ? tr('board.SignOff.32', { p0: run.signoff.note }) : '', tests: run.signoff.tests })}
        </p>
      ) : run.sign_block && !rel ? (
        <p className="kt-sign-blocked" role="status" data-testid="kt-sign-blocked">
          {signBlock(run)}
        </p>
      ) : onSign ? (
        <>
          {run.sign_block && (
            <p className="kt-sign-blocked" role="status" data-testid="kt-sign-blocked">
              {signBlock(run)}
            </p>
          )}
          <form className="kt-sign-form" onSubmit={submit}>
            <input aria-label={tr('board.SignOff.34')} placeholder={tr('board.SignOff.34')} value={by} onChange={(e) => setBy(e.target.value)} />
            <input aria-label={tr('board.SignOff.35')} placeholder={tr('board.SignOff.36')} value={note} onChange={(e) => setNote(e.target.value)} />
            <button type="submit" className="kt-btn is-primary" disabled={busy || !by.trim() || !!run.sign_block}>
              {busy ? tr('board.SignOff.37') : green || run.sign_block ? tr('board.SignOff.31') : tr('board.SignOff.38', { p0: t.failed })}
            </button>
            {err && <span className="kt-error">{err}</span>}
          </form>
        </>
      ) : null}
    </section>
  )
}

const VERDICT_TONE: Record<string, string> = { PASS: 'kt-ok', FAIL: 'kt-bad', BLOCKED: 'kt-warn', USAGE: 'kt-warn' }

/** The independent rerun (D9): release.sh's verdict and reasons, each check's verdict and evidence tier, what changed. */
function Release({ rel }: { rel: ReleaseView }) {
  return (
    <div data-testid="kt-sign-release">
      <p>
        {tr('board.SignOff.39')}{rel.head.slice(0, 7)}{tr('board.SignOff.40')} <b className={VERDICT_TONE[rel.release.verdict] ?? ''}>{rel.release.verdict}</b>
        {rel.release.summary ? ` · ${rel.release.summary}` : ''}
      </p>
      {rel.release.reasons.length > 0 && (
        <ul>
          {rel.release.reasons.map((r, i) => <li key={i} className="kt-sign-back">{r}</li>)}
        </ul>
      )}
      <ul className="kt-sign-groups">
        {rel.checks.map((c) => (
          <li key={c.name} className={c.verdict === 'PASS' ? 'is-ok' : 'is-bad'} title={c.reasons.join(tr('board.SignOff.41')) || c.summary}>
            {c.name} {c.verdict}{c.tier && c.tier !== 'n/a' ? ` · ${c.tier}` : ''}
          </li>
        ))}
      </ul>
      <p data-testid="kt-sign-differs">
        {rel.differs.length
          ? tr('board.SignOff.42', { p0: rel.differs.map((d) => tr('board.SignOff.differ', { p0: d.name, p1: d.was ?? tr('board.SignOff.notRun'), p2: d.now ?? tr('board.SignOff.notRun') })).join(tr('common.sep')) })
          : tr('board.SignOff.43')}
      </p>
    </div>
  )
}
