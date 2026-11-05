/**
 * 台架: the bench of a team that has one (D3, D10), read only. Where the app is on the bench (doctor, deploy, replay,
 * the checks after it, the rerun), what holds it for a person with the commands they run, doctor.sh's result, the
 * emulated target and the simulated supply, each request waiting at the operator console with the digest to approve
 * and the console command for it, and the end of the action record. A person approves or refuses a request here or at
 * the console; either way the bench's own decide() decides (D3).
 */
import { evText } from '../i18n/events'
import { useState } from 'react'
import { useAppApi } from '@kirocrew/app-sdk'
import type { BenchView } from '../types'
import { auditChanged } from './Audit'
import { BASE } from './format'
import { errorText } from './useBoard'
import { t as tr } from '../i18n'

/** 批准 / 拒绝 one request waiting at the operator console (D3): the bench's own decide() decides. Approving needs the
 * first 6 characters of the digest typed by the person, as at the console; refusing needs a reason. */
export function DecideRequest({ id, digest, onDone }: { id: string; digest: string; onDone?: () => void }) {
  const api = useAppApi()
  const [prefix, setPrefix] = useState('')
  const [refusing, setRefusing] = useState(false)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [done, setDone] = useState('')
  const send = async (verdict: 'approve' | 'refuse') => {
    setBusy(true)
    setErr('')
    try {
      await api.post(`${BASE}/bench/decide`, { id, verdict, digest: prefix.trim(), reason: reason.trim() })
      setDone(verdict === 'approve' ? tr('board.Bench.1') : tr('board.Bench.2'))
      auditChanged()
      onDone?.()
    } catch (x) {
      setErr(errorText(x))
    } finally {
      setBusy(false)
    }
  }
  if (done) return <span className="kt-decide is-done" data-testid="kt-decide" role="status">✔ {done}</span>
  const okPrefix = /^[0-9a-fA-F]{6,}$/.test(prefix.trim())
  return (
    <span className="kt-decide" data-testid="kt-decide">
      {refusing ? (
        <>
          <input aria-label={tr('board.Bench.3')} value={reason} maxLength={200} onChange={(e) => setReason(e.target.value)} placeholder={tr('board.Bench.3')} autoFocus />
          <button type="button" className="kt-btn is-solid is-danger" disabled={busy || !reason.trim()} onClick={() => void send('refuse')}>{tr('board.Bench.4')}</button>
          <button type="button" className="kt-btn" disabled={busy} onClick={() => setRefusing(false)}>{tr('board.Bench.5')}</button>
        </>
      ) : (
        <>
          <input aria-label={tr('board.Bench.6')} className="kt-mono" value={prefix} maxLength={64} onChange={(e) => setPrefix(e.target.value)}
            placeholder={tr('board.Bench.7')} title={tr('board.Bench.8', { p0: digest })} />
          <button type="button" className="kt-btn is-solid is-primary" disabled={busy || !okPrefix} onClick={() => void send('approve')}
            title={tr('board.Bench.9')}>{tr('board.Bench.10')}</button>
          <button type="button" className="kt-btn" disabled={busy} onClick={() => setRefusing(true)}>{tr('board.Bench.11')}</button>
        </>
      )}
      {err && <span className="kt-error" role="alert">{err}</span>}
    </span>
  )
}

/** A command with the scenario folder's absolute path cut (bench/…, reference-project/…, checks/…); the full one is
 * what gets copied. */
export const shortCmd = (cmd: string) => cmd.replace(/(?:\/[^\s/]+)+\/((?:bench|reference-project|checks)\/)/g, '$1')

function useCopy(): [string, (text: string) => void] {
  const [msg, setMsg] = useState('')
  const copy = (text: string) => {
    const fail = () => setMsg(tr('board.Bench.12'))
    if (!navigator.clipboard) return fail()
    navigator.clipboard.writeText(text).then(() => setMsg(tr('board.Bench.13')), fail)
  }
  return [msg, copy]
}

/** One command, shortened, with 复制命令 (the full command). */
export function Cmd({ cmd }: { cmd: string }) {
  const [msg, copy] = useCopy()
  return (
    <span className="kt-cli" data-testid="kt-cli">
      <code className="kt-ready-cmd" title={cmd}>{shortCmd(cmd)}</code>
      <button type="button" className="kt-btn is-small" onClick={() => copy(cmd)}>{tr('board.Bench.14')}</button>
      {msg && <small className="kt-dim" role="status">{msg}</small>}
    </span>
  )
}

/** A build digest: its first 12 characters, the full one in the title and copied. */
export function Digest({ digest }: { digest: string }) {
  const [msg, copy] = useCopy()
  return (
    <span data-testid="kt-digest">
      <code className="kt-bench-digest" title={digest}>{digest.slice(0, 12)}</code>{' '}
      <button type="button" className="kt-btn is-small" onClick={() => copy(digest)} title={tr('board.Bench.15')}>{tr('board.Bench.16')}</button>
      {msg && <small className="kt-dim" role="status">{msg}</small>}
    </span>
  )
}

const STEP: Record<string, string> = {
  doctor: tr('board.Bench.17'),
  deploy: tr('board.Bench.18'),
  replay: tr('board.Bench.19'),
  after: tr('board.Bench.20'),
  rerun: tr('board.Bench.21'),
  done: tr('board.Bench.22'),
}
const TARGET: Record<string, string> = { known: tr('board.Bench.23'), off: tr('board.Bench.24'), busy: tr('board.Bench.25'), unknown: tr('board.Bench.26') }
const ACTION_SHOWN = 8

const str = (x: unknown) => (x === null || x === undefined ? '' : String(x))

/** One line of the action record (bench/lib/benchstate.py: event and its fields). */
export function actionLine(a: Record<string, unknown>): string {
  const ev = str(a.event)
  const who = a.by ? tr('board.Bench.27', { p0: str(a.by) }) : ''
  switch (ev) {
    case 'request':
      return tr('board.Bench.28', { p0: str(a.action), p1: str(a.digest).slice(0, 12), p2: str(a.requested_by) })
    case 'decision':
      return `${a.verdict === 'approved' ? tr('board.Bench.10') : tr('board.Bench.29')} ${str(a.action)} ${str(a.digest).slice(0, 12)}${who}${a.reason ? tr('board.Bench.30', { p0: str(a.reason) }) : ''}`
    case 'action':
      return tr('board.Bench.31', { p0: str(a.action), p1: a.result === 'ok' ? tr('board.Bench.ok') : tr('board.Bench.failed'), p2: a.detail ? tr('common.detail', { p0: str(a.detail) }) : '' })
    case 'gate':
      return tr('board.Bench.32', { p0: str(a.action), p1: a.passed ? tr('board.Bench.passed') : tr('board.Bench.notPassed'), p2: a.why ? tr('common.detail', { p0: str(a.why) }) : '' })
    case 'supply':
      return tr('board.Bench.33', { p0: str(a.voltage_v), p1: str(a.kl15), p2: who })
    case 'target':
      return tr('board.Bench.34', { p0: str(a.state), p1: a.why ? tr('common.detail', { p0: str(a.why) }) : '' })
    case 'reconcile':
      return tr('board.Bench.35', { p0: who })
    default:
      return ev || JSON.stringify(a)
  }
}

export function BenchPanel({ bench, onRetry }: { bench: BenchView; onRetry?: () => Promise<void> }) {
  const st = bench.state
  const target = str(st.target.state)
  const supply = st.supply
  const recent = st.actions.slice(-ACTION_SHOWN).reverse()
  const doc = bench.doctor
  return (
    <section className="kt-card kt-bench" aria-label={tr('board.Bench.36')} data-testid="kt-bench">
      <header className="kt-card-head">
        <h2>{tr('board.Bench.36')}</h2>
        <span className="kt-dim" data-testid="kt-bench-step">
          {bench.step ? `${STEP[bench.step] ?? bench.step}${bench.running ? tr('board.Bench.37') : ''}` : tr('board.Bench.38')}
        </span>
      </header>
      {bench.held && (
        <div className="kt-bench-held" role="status" data-testid="kt-bench-held">
          <b>{tr('board.Bench.39')}</b>{evText({ text: bench.held.why, code: bench.held.code, params: bench.held.params })}
          {bench.held.commands.length > 0 && (
            <ul>
              {bench.held.commands.map((c) => <li key={c}><code>{c}</code></li>)}
            </ul>
          )}
          <span className="kt-dim">{tr('board.Bench.40')}{STEP[bench.held.step] ?? bench.held.step}{tr('board.Bench.41')}</span>
          {onRetry && <span><button type="button" className="kt-btn is-solid is-primary" onClick={() => void onRetry()}>{tr('board.Bench.42')}{STEP[bench.held.step] ?? bench.held.step}{tr('board.Bench.43')}</button></span>}
        </div>
      )}
      <dl className="kt-bench-grid">
        <div>
          <dt>{tr('board.Bench.44')}</dt>
          <dd className={target === 'known' ? 'kt-ok' : target === 'unknown' ? 'kt-bad' : ''}>
            {TARGET[target] ?? target}{st.target.why ? <span className="kt-dim"> · {str(st.target.why)}</span> : null}
          </dd>
        </div>
        <div>
          <dt>{tr('board.Bench.45')}</dt>
          <dd>{supply ? `${str(supply.voltage_v) || '—'} V · KL15 ${str(supply.kl15) || '—'}` : <span className="kt-warn">{tr('board.Bench.46')}</span>}</dd>
        </div>
        <div>
          <dt>doctor.sh</dt>
          <dd data-testid="kt-bench-doctor">
            {doc ? (
              <>
                <b className={doc.ok ? 'kt-ok' : 'kt-bad'}>{doc.ok ? tr('board.Bench.47') : tr('board.Bench.48')}</b>
                {doc.summary ? ` · ${doc.summary}` : ''}
                {doc.fails.length + doc.warns.length > 0 && (
                  <ul>
                    {doc.fails.map((f) => <li key={`f${f}`} className="kt-bad">{f}</li>)}
                    {doc.warns.map((w) => <li key={`w${w}`} className="kt-warn">{w}</li>)}
                  </ul>
                )}
              </>
            ) : tr('board.Bench.49')}
          </dd>
        </div>
      </dl>
      <div className="kt-bench-pending" data-testid="kt-bench-pending">
        <b>{tr('board.Bench.50')}</b>
        {st.pending.length === 0 ? (
          <p className="kt-dim">{tr('board.Bench.51')}</p>
        ) : (
          <ul>
            {st.pending.map((r) => (
              <li key={r.id}>
                <span><b>{r.action}</b> · {r.requested_by}{r.expired ? <span className="kt-bad"> {tr('board.Bench.52')}</span> : null}</span>
                <span>{tr('board.Bench.53')} <Digest digest={r.digest} /></span>
                {r.detail && <span className="kt-dim">{r.detail}</span>}
                {!r.expired && <DecideRequest id={r.id} digest={r.digest} />}
              </li>
            ))}
          </ul>
        )}
        {bench.console && (
          <details className="kt-ready-cli">
            <summary>{tr('board.Bench.54')}</summary>
            <span className="kt-dim">{tr('board.Bench.55')}</span>
            <Cmd cmd={bench.console} />
            {st.pending.filter((r) => !r.expired).map((r) => (
              <div key={r.id}>
                <Cmd cmd={`${bench.console} approve ${r.id} --digest ${r.digest.slice(0, 12)}`} />
                <Cmd cmd={tr('board.Bench.56', { p0: bench.console, p1: r.id })} />
              </div>
            ))}
          </details>
        )}
      </div>
      <div className="kt-bench-record">
        <b>{tr('board.Bench.recent', { n: Math.min(ACTION_SHOWN, st.actions.length) })}</b>
        {recent.length === 0 ? <p className="kt-dim">{tr('board.Bench.emptyRecord', { dir: st.dir })}</p> : (
          <ol data-testid="kt-bench-record">
            {recent.map((a, i) => (
              <li key={`${str(a.at)}-${i}`}>
                <span className="kt-dim kt-mono">{str(a.at).replace('T', ' ').replace(/(\.\d+)?Z$/, '')}</span> {actionLine(a)}
              </li>
            ))}
          </ol>
        )}
      </div>
    </section>
  )
}
