/**
 * 签字单: the right shift on the board, at the end of a run. Everything a person needs to sign for the release on one
 * card: the requirement, what people decided at the gates, what the machine checks said (by the company standard
 * they enforce), what the independent review concluded, where it is deployed, and what the agents did. Then the one
 * step no agent takes: a person signs (签字放行), and the board keeps who, when and what the checks said then. The
 * signature merges the run's PR (its run branch) into main.
 */
import { useState, type FormEvent } from 'react'
import type { RunDetail } from '../types'
import { CASE_GROUPS, caseGroup, fmtCredits, fmtSpan } from './format'
import { RoleIcon } from './RoleIcon'
import { money } from '../cto/metrics'

const SIGNER_KEY = 'aidlc-team:signer'

/** Where the run's PR stands, in the 签字单's words. */
export function prState(run: RunDetail): string {
  const pr = run.pr
  if (!pr) return ''
  if (pr.state === 'open') return '待合并：签字放行时合入 main'
  if (pr.state === 'merged') return `已合入 main（${pr.sha}）`
  return run.imported ? '已签字放行；运行从其他电脑导入，代码仓库不在这里，没有在这里合并' : '已签字放行；main 在运行期间有新提交，没能直接合入'
}

export function SignOff({ run, onSign, onCto, onItem }: { run: RunDetail; onSign?: (by: string, note: string) => Promise<void>; onCto?: () => void; onItem?: () => void }) {
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
    ...sentBack.map((e) => ({ seq: e.seq, key: `b${e.seq}`, back: true, text: e.text.replace(/^人/, '') })),
    ...gates.map((l) => ({ seq: approvedAt(l.key), key: l.key, back: false, text: `批准${l.gate_label}：${run.gate_notes[l.key]}` })),
  ].sort((a, b) => (a.seq < 0 ? Infinity : a.seq) - (b.seq < 0 ? Infinity : b.seq))
  const review = run.roles.find((l) => l.writable.length === 0)
  const deployed = run.roles.find((l) => l.deployed)?.deployed ?? null
  const commits = run.roles.reduce((n, l) => n + l.commits.length, 0)
  const members = run.roles.filter((l) => l.status !== 'skipped')
  const green = t.total > 0 && t.failed === 0
  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!onSign || !by.trim() || busy) return
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
    <section id="kt-signoff" className={`kt-sign${run.signoff ? ' is-signed' : ''}`} aria-label="签字单" data-testid="kt-sign">
      <header className="kt-sign-head">
        <h2>签字单</h2>
        <p className="kt-dim">发布前由负责人确认</p>
      </header>
      <dl className="kt-sign-grid">
        <div>
          <dt>需求</dt>
          <dd>{run.requirement || run.title}</dd>
        </div>
        {run.issue && (
          <div>
            <dt>Issue · PR</dt>
            <dd data-testid="kt-sign-pr">
              Issue {run.issue.id}（{run.issue.kind} · {run.issue.reporter}提出）
              {run.pr ? ` → PR #${run.pr.number}：${run.pr.head} → ${run.pr.base} · ${prState(run)}` : ''}
            </dd>
          </div>
        )}
        <div>
          <dt>人做的决定</dt>
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
                    推翻审查结论，批准{run.roles.find((l) => l.key === over.role)?.gate_label || over.role}：{over.note}
                  </li>
                )}
              </ul>
            ) : (
              '（关卡上没有留意见）'
            )}
          </dd>
        </div>
        {(run.risks ?? []).length > 0 && (
          <div>
            <dt>拦下的风险</dt>
            <dd data-testid="kt-sign-risks">
              <ul>
                {(run.risks ?? []).map((r, i) => (
                  <li key={i} className="kt-sign-back">
                    {r.what}{r.amount != null ? ` ${money(r.amount)}` : ''}（{r.gate}关卡退回时记下）
                  </li>
                ))}
              </ul>
            </dd>
          </div>
        )}
        <div>
          <dt>机器检查</dt>
          <dd>
            <b className={green ? 'kt-ok' : 'kt-bad'}>
              {t.passed}/{t.total} 通过
            </b>
            <ul className="kt-sign-groups">
              {groups.map((g) => (
                <li key={g.prefix} className={g.passed === g.total ? 'is-ok' : 'is-bad'}>
                  {g.label} {g.passed}/{g.total}
                </li>
              ))}
            </ul>
          </dd>
        </div>
        <div>
          <dt>独立审查</dt>
          <dd>{review ? `${review.title}（另开的会话，只读改动）：${review.summary || '没有结论'}${over?.role === review.key ? '（人推翻了这个结论）' : ''}` : '这支团队没有独立审查'}</dd>
        </div>
        <div>
          <dt>部署</dt>
          <dd>
            {deployed ? (
              <a href={deployed.url} target="_blank" rel="noreferrer">
                {deployed.url}
              </a>
            ) : (
              '没有部署'
            )}
          </dd>
        </div>
        <div>
          <dt>agent 做了什么</dt>
          <dd>
            {members.length} 位成员 · {commits} 次提交 · 用时 {fmtSpan(run.wall_s)} · {fmtCredits(run.credits)} credits
          </dd>
        </div>
      </dl>
      {run.signoff ? (
        <p className="kt-sign-done" role="status">
          <RoleIcon role="sign" size={16} /> <b>{run.signoff.by}</b> 于 {new Date(run.signoff.at * 1000).toLocaleString('zh-CN', { hour12: false })} 签字放行
          {run.signoff.note ? `：${run.signoff.note}` : ''}（签字时检查 {run.signoff.tests}）
          {onCto && (
            <button type="button" className="kt-btn is-primary kt-sign-cto" onClick={onCto} title="签字放行的交付计入 CTO 视图：交付清单、三张卡片和每周上线">
              已计入 CTO 视图 ↗
            </button>
          )}
          {onItem && (
            <button type="button" className="kt-btn kt-sign-cto" onClick={onItem} title="这次交付的周期、时间花在哪、成本、质量和价值流">
              交付详情 ↗
            </button>
          )}
        </p>
      ) : run.sign_block ? (
        <p className="kt-sign-blocked" role="status" data-testid="kt-sign-blocked">
          {run.sign_block}
        </p>
      ) : onSign ? (
        <form className="kt-sign-form" onSubmit={submit}>
          <input aria-label="签字人" placeholder="签字人" value={by} onChange={(e) => setBy(e.target.value)} />
          <input aria-label="备注" placeholder="备注（选填），比如：已在预发环境看过" value={note} onChange={(e) => setNote(e.target.value)} />
          <button type="submit" className="kt-btn is-primary" disabled={busy || !by.trim()}>
            {busy ? '正在签…' : green ? '签字放行' : `还有 ${t.failed} 项没过，仍然签字`}
          </button>
          {err && <span className="kt-error">{err}</span>}
        </form>
      ) : null}
    </section>
  )
}
