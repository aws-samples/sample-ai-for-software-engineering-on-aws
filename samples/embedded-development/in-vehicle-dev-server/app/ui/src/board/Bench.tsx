/**
 * 台架: the bench of a team that has one (D3, D10), read only. Where the app is on the bench (doctor, deploy, replay,
 * the checks after it, the rerun), what holds it for a person with the commands they run, doctor.sh's result, the
 * emulated target and the simulated supply, each request waiting at the operator console with the digest to approve
 * and the console command for it, and the end of the action record. A person approves or refuses a request here or at
 * the console; either way the bench's own decide() decides (D3).
 */
import { useState } from 'react'
import { useAppApi } from '@kirocrew/app-sdk'
import type { BenchView } from '../types'
import { BASE } from './format'
import { errorText } from './useBoard'

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
      setDone(verdict === 'approve' ? '已批准' : '已拒绝')
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
          <input aria-label="拒绝的原因" value={reason} maxLength={200} onChange={(e) => setReason(e.target.value)} placeholder="拒绝的原因" autoFocus />
          <button type="button" className="kt-btn is-solid is-danger" disabled={busy || !reason.trim()} onClick={() => void send('refuse')}>确认拒绝</button>
          <button type="button" className="kt-btn" disabled={busy} onClick={() => setRefusing(false)}>取消</button>
        </>
      ) : (
        <>
          <input aria-label="构建摘要的前 6 位" className="kt-mono" value={prefix} maxLength={64} onChange={(e) => setPrefix(e.target.value)}
            placeholder="核对后输入摘要前 6 位" title={`这次的摘要：${digest}`} />
          <button type="button" className="kt-btn is-solid is-primary" disabled={busy || !okPrefix} onClick={() => void send('approve')}
            title="由台架自己的审批逻辑判定：摘要要对得上，没超时，只批一次">批准</button>
          <button type="button" className="kt-btn" disabled={busy} onClick={() => setRefusing(true)}>拒绝…</button>
        </>
      )}
      {err && <span className="kt-error" role="alert">{err}</span>}
    </span>
  )
}

const STEP: Record<string, string> = {
  doctor: '检查台架（doctor.sh）',
  deploy: '部署：等操作台批准',
  replay: '回放录制的行驶数据：等操作台批准',
  after: '台架之后的检查',
  rerun: '独立重跑全部检查和 release.sh',
  done: '台架上的事做完了',
}
const TARGET: Record<string, string> = { known: '状态已知', off: '没开机', busy: '有动作在做', unknown: '状态未知：要在操作台核对' }
const ACTION_SHOWN = 8

const str = (x: unknown) => (x === null || x === undefined ? '' : String(x))

/** One line of the action record (bench/lib/benchstate.py: event and its fields). */
export function actionLine(a: Record<string, unknown>): string {
  const ev = str(a.event)
  const who = a.by ? `（${str(a.by)}）` : ''
  switch (ev) {
    case 'request':
      return `请求 ${str(a.action)} ${str(a.digest).slice(0, 12)}，${str(a.requested_by)}`
    case 'decision':
      return `${a.verdict === 'approved' ? '批准' : '拒绝'} ${str(a.action)} ${str(a.digest).slice(0, 12)}${who}${a.reason ? `：${str(a.reason)}` : ''}`
    case 'action':
      return `动作 ${str(a.action)} ${a.result === 'ok' ? '完成' : '失败'}${a.detail ? `：${str(a.detail)}` : ''}`
    case 'gate':
      return `物理门 ${str(a.action)} ${a.passed ? '通过' : '不通过'}${a.why ? `：${str(a.why)}` : ''}`
    case 'supply':
      return `电源 ${str(a.voltage_v)} V，KL15 ${str(a.kl15)}${who}`
    case 'target':
      return `目标 ${str(a.state)}${a.why ? `：${str(a.why)}` : ''}`
    case 'reconcile':
      return `核对目标状态${who}`
    default:
      return ev || JSON.stringify(a)
  }
}

export function BenchPanel({ bench }: { bench: BenchView }) {
  const st = bench.state
  const target = str(st.target.state)
  const supply = st.supply
  const recent = st.actions.slice(-ACTION_SHOWN).reverse()
  const doc = bench.doctor
  return (
    <section className="kt-card kt-bench" aria-label="台架" data-testid="kt-bench">
      <header className="kt-card-head">
        <h2>台架</h2>
        <span className="kt-dim" data-testid="kt-bench-step">
          {bench.step ? `${STEP[bench.step] ?? bench.step}${bench.running ? ' · 进行中' : ''}` : '台架之前的检查都过了、评审放行以后才上台架'}
        </span>
      </header>
      {bench.held && (
        <div className="kt-bench-held" role="status" data-testid="kt-bench-held">
          <b>要人处理：</b>{bench.held.why}
          {bench.held.commands.length > 0 && (
            <ul>
              {bench.held.commands.map((c) => <li key={c}><code>{c}</code></li>)}
            </ul>
          )}
          <span className="kt-dim">处理好以后在看板上点「重试」，从「{STEP[bench.held.step] ?? bench.held.step}」接着做。</span>
        </div>
      )}
      <dl className="kt-bench-grid">
        <div>
          <dt>CC-1（模拟目标）</dt>
          <dd className={target === 'known' ? 'kt-ok' : target === 'unknown' ? 'kt-bad' : ''}>
            {TARGET[target] ?? target}{st.target.why ? <span className="kt-dim"> · {str(st.target.why)}</span> : null}
          </dd>
        </div>
        <div>
          <dt>电源（模拟）</dt>
          <dd>{supply ? `${str(supply.voltage_v) || '—'} V · KL15 ${str(supply.kl15) || '—'}` : <span className="kt-warn">还没设：在操作台上设（v 13.5、k on），否则物理动作都会被拒</span>}</dd>
        </div>
        <div>
          <dt>doctor.sh</dt>
          <dd data-testid="kt-bench-doctor">
            {doc ? (
              <>
                <b className={doc.ok ? 'kt-ok' : 'kt-bad'}>{doc.ok ? '通过' : '没通过'}</b>
                {doc.summary ? ` · ${doc.summary}` : ''}
                {doc.fails.length + doc.warns.length > 0 && (
                  <ul>
                    {doc.fails.map((f) => <li key={`f${f}`} className="kt-bad">{f}</li>)}
                    {doc.warns.map((w) => <li key={`w${w}`} className="kt-warn">{w}</li>)}
                  </ul>
                )}
              </>
            ) : '还没跑'}
          </dd>
        </div>
      </dl>
      <div className="kt-bench-pending" data-testid="kt-bench-pending">
        <b>等操作台批准的请求</b>
        {st.pending.length === 0 ? (
          <p className="kt-dim">没有</p>
        ) : (
          <ul>
            {st.pending.map((r) => (
              <li key={r.id}>
                <span><b>{r.action}</b> · {r.requested_by}{r.expired ? <span className="kt-bad"> · 已超时</span> : null}</span>
                <span>构建摘要 <code className="kt-bench-digest">{r.digest}</code></span>
                {r.detail && <span className="kt-dim">{r.detail}</span>}
                {!r.expired && <DecideRequest id={r.id} digest={r.digest} />}
                {bench.console && (
                  <span className="kt-dim">
                    或在操作台：<code>{`${bench.console} approve ${r.id} --digest ${r.digest.slice(0, 12)}`}</code>；拒绝：<code>{`${bench.console} refuse ${r.id} --reason <原因>`}</code>
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
        {bench.console && <p className="kt-dim">在这里批准，或在另一个终端里的操作台：<code>{bench.console}</code>（a 批准、r 拒绝、c 核对）。两边都走台架自己的审批逻辑，电源、点火、超时照样拦。</p>}
      </div>
      <div className="kt-bench-record">
        <b>动作记录（最近 {Math.min(ACTION_SHOWN, st.actions.length)} 条）</b>
        {recent.length === 0 ? <p className="kt-dim">动作记录是空的（{st.dir}/actions.jsonl）</p> : (
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
