/**
 * 签字单: the right shift on the board, at the end of a run. Everything a person needs to sign for the release on one
 * card: the requirement, what people decided at the gates, what the machine checks said (with a release check: the
 * independent rerun's release.sh verdict, the checks whose verdict changed on it, and the evidence page, shown as plain
 * text: it quotes what agents wrote), what the independent review concluded, and what the agents did. Then the one
 * step no agent takes: a person signs (签字放行), and the board keeps who, when and what the checks said then. The
 * button stays off while the run cannot be signed (release.sh has not passed on the rerun). The signature merges the
 * run's PR (its run branch) into main.
 */
import { useState, type FormEvent } from 'react'
import type { ReleaseView, RunDetail } from '../types'
import { CASE_GROUPS, caseGroup, fmtCredits, fmtSpan } from './format'
import { RoleIcon } from './RoleIcon'

const SIGNER_KEY = 'vstatd-team:signer'
/** An amount in yuan: ¥20.6 万 · ¥8,000 · '' (none). */
const money = (n: number | null | undefined) => (n == null ? '' : n >= 1e4 ? `¥${(n / 1e4).toFixed(1)} 万` : `¥${Math.round(n).toLocaleString('zh-CN')}`)

/** Where the run's PR stands, in the 签字单's words. */
export function prState(run: RunDetail): string {
  const pr = run.pr
  if (!pr) return ''
  if (pr.state === 'open') return '待合并：签字放行时合入 main'
  if (pr.state === 'merged') return `已合入 main（${pr.sha}）`
  return run.imported ? '已签字放行；运行从其他电脑导入，代码仓库不在这里，没有在这里合并' : '已签字放行；main 在运行期间有新提交，没能直接合入'
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
    ...sentBack.map((e) => ({ seq: e.seq, key: `b${e.seq}`, back: true, text: e.text.replace(/^人/, '') })),
    ...gates.map((l) => ({ seq: approvedAt(l.key), key: l.key, back: false, text: `批准${l.gate_label}：${run.gate_notes[l.key]}` })),
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
            {rel ? <Release rel={rel} /> : (
              <>
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
              </>
            )}
          </dd>
        </div>
        <div>
          <dt>独立审查</dt>
          <dd>{review ? `${review.title}（另开的会话，只读改动）：${review.summary || '没有结论'}${over?.role === review.key ? '（人推翻了这个结论）' : ''}` : '这支团队没有独立审查'}</dd>
        </div>
        <div>
          <dt>agent 做了什么</dt>
          <dd>
            {members.length} 位成员 · {commits} 次提交 · 用时 {fmtSpan(run.wall_s)} · {fmtCredits(run.credits)} credits
          </dd>
        </div>
      </dl>
      {rel && (
        <details className="kt-sign-evidence" open={!run.signoff} data-testid="kt-sign-evidence">
          <summary>证据页（evidence-page.sh 生成的 evidence.md）</summary>
          {rel.evidence ? <pre className="kt-evidence">{rel.evidence}</pre> : <p className="kt-dim">没有证据页：evidence-page.sh 没有写出 evidence.md（看 {rel.results}）</p>}
        </details>
      )}
      {run.signoff ? (
        <p className="kt-sign-done" role="status">
          <RoleIcon role="sign" size={16} /> <b>{run.signoff.by}</b> 于 {new Date(run.signoff.at * 1000).toLocaleString('zh-CN', { hour12: false })} 签字放行
          {run.signoff.note ? `：${run.signoff.note}` : ''}（签字时检查 {run.signoff.tests}）
        </p>
      ) : run.sign_block && !rel ? (
        <p className="kt-sign-blocked" role="status" data-testid="kt-sign-blocked">
          {run.sign_block}
        </p>
      ) : onSign ? (
        <>
          {run.sign_block && (
            <p className="kt-sign-blocked" role="status" data-testid="kt-sign-blocked">
              {run.sign_block}
            </p>
          )}
          <form className="kt-sign-form" onSubmit={submit}>
            <input aria-label="签字人" placeholder="签字人" value={by} onChange={(e) => setBy(e.target.value)} />
            <input aria-label="备注" placeholder="备注（选填），比如：已在操作台核对过动作记录" value={note} onChange={(e) => setNote(e.target.value)} />
            <button type="submit" className="kt-btn is-primary" disabled={busy || !by.trim() || !!run.sign_block}>
              {busy ? '正在签…' : green || run.sign_block ? '签字放行' : `还有 ${t.failed} 项没过，仍然签字`}
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
        独立重跑（{rel.head.slice(0, 7)}）：release.sh <b className={VERDICT_TONE[rel.release.verdict] ?? ''}>{rel.release.verdict}</b>
        {rel.release.summary ? ` · ${rel.release.summary}` : ''}
      </p>
      {rel.release.reasons.length > 0 && (
        <ul>
          {rel.release.reasons.map((r, i) => <li key={i} className="kt-sign-back">{r}</li>)}
        </ul>
      )}
      <ul className="kt-sign-groups">
        {rel.checks.map((c) => (
          <li key={c.name} className={c.verdict === 'PASS' ? 'is-ok' : 'is-bad'} title={c.reasons.join('；') || c.summary}>
            {c.name} {c.verdict}{c.tier && c.tier !== 'n/a' ? ` · ${c.tier}` : ''}
          </li>
        ))}
      </ul>
      <p data-testid="kt-sign-differs">
        {rel.differs.length
          ? `和运行最后一轮结论不同的检查：${rel.differs.map((d) => `${d.name}（${d.was ?? '没跑'} → ${d.now ?? '没跑'}）`).join('、')}`
          : '重跑的结论和运行最后一轮都一样'}
      </p>
    </div>
  )
}
