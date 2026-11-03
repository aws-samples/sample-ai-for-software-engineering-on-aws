/**
 * 评分卡 (D8): the rehearsal scorecard of the scenario page, from `GET /scorecard` every 10 s. Only measured figures,
 * each from the runs' records (backend/team/scorecard.py); a figure no run is behind is shown empty (—), never 0. The
 * cards are the sums over the runs, the table each run, the notes at the foot say how each figure is taken and which
 * figures of the scenario page are left out. The cards and blocks are the kit's (kit.ts), as the CTO view's were.
 */
import { useEffect, useState } from 'react'
import { useAppApi } from '@kirocrew/app-sdk'
import { BOARD_CSS } from '../board/styles'
import { fmtSpan, paths, runMeta } from '../board/format'
import { errorText } from '../board/useBoard'
import { KIT_CSS } from '../kit'
import type { ScoreRun, Scorecard } from '../types'

export const SCORE_POLL_MS = 10000

const SC_CSS = `
.sc-root .cto-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(210px, 1fr)); }
.sc-root .cto-card { margin: 0; }
.sc-head h2 { margin: 0 0 4px; font-size: 1.4em; color: var(--text-strong); }
.sc-head p { margin: 0; color: var(--muted); }
.sc-root .cto-value.is-empty { color: var(--muted); }
.sc-table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
.sc-table th, .sc-table td { text-align: left; padding: 6px 10px 6px 0; border-bottom: 1px solid var(--border); vertical-align: top; }
.sc-table th { color: var(--muted); font-weight: 650; font-size: .93em; }
.sc-wide { overflow-x: auto; }
.sc-detail { margin-top: 4px; font-size: 12px; padding: 3px 10px; }
.sc-root section.cto-card > h3 { margin: 0 0 10px; font-size: 1.1em; color: var(--text-strong); }
.sc-notes { color: var(--muted); font-size: 13px; }
.sc-notes summary { cursor: pointer; color: var(--text); }
.sc-notes ul { margin: 8px 0 0; padding-left: 18px; display: grid; gap: 4px; }
.kt-app.is-projection > .sc-root { flex: 1 1 auto; min-height: 0; overflow: auto; font-size: 18px; }
`

const EMPTY = '—'
const n = (x: number | null | undefined) => (x === null || x === undefined ? EMPTY : String(x))
const span = (x: number | null) => (x === null ? EMPTY : fmtSpan(x))
const isEmpty = (x: unknown) => x === null || x === undefined

function Card({ label, value, of, empty }: { label: string; value: string; of?: string; empty: boolean }) {
  return (
    <div className="cto-card" data-testid="sc-card">
      <div className="cto-eyebrow">{label}</div>
      <div className={`cto-value${empty ? ' is-empty' : ''}`} title={empty ? '还没有运行做到这一步' : undefined}>
        {value}
        {of && !empty && <span className="cto-of"> {of}</span>}
      </div>
    </div>
  )
}

function caughtText(c: Record<string, number> | null): string {
  if (!c) return EMPTY
  const failed = Object.entries(c).filter(([, v]) => v > 0)
  return failed.length ? failed.map(([k, v]) => `${k} ${v}`).join('、') : '0'
}

function RunRow({ r, onDetail }: { r: ScoreRun; onDetail?: (rid: string) => void }) {
  return (
    <tr data-testid="sc-run" data-run={r.id}>
      <td>
        <b>{r.title || r.id}</b>
        <div className="kt-dim">{r.id} · {runMeta(r.status).label}{r.signed ? ' · 已签字' : ''}</div>
        {onDetail && <button type="button" className="kt-btn sc-detail" onClick={() => onDetail(r.id)} aria-label={`交付详情：${r.title || r.id}`}>交付详情</button>}
      </td>
      <td>{r.findings ? `${r.findings.fixed} / ${r.findings.justified} / ${r.findings.deferred}` : EMPTY}</td>
      <td title={r.overturned ? `人：${r.overturned.by_person.join('、') || '无'}；评审：${r.overturned.by_reviewer.join('、') || '无'}` : undefined}>
        {r.overturned ? (r.overturned.ids.length ? `${r.overturned.ids.length}（${r.overturned.ids.join('、')}）` : '0') : EMPTY}
      </td>
      <td>{span(r.times.triage_s)}</td>
      <td>{span(r.times.first_pass_s)}</td>
      <td>{span(r.times.signoff_s)}</td>
      <td>{n(r.build_rounds)}</td>
      <td>{caughtText(r.caught)}</td>
      <td>{r.logdiff ? `${r.logdiff.differences}（未解释 ${r.logdiff.unexplained}）` : EMPTY}</td>
      <td>{r.bench ? `${r.bench.approved} / ${r.bench.refused} / ${r.bench.reconciled}` : EMPTY}</td>
      <td>{r.rerun_differs ? (r.rerun_differs.length ? r.rerun_differs.join('、') : '0') : EMPTY}</td>
    </tr>
  )
}

export function ScorecardView({ pollMs = SCORE_POLL_MS, onDetail }: { pollMs?: number; onDetail?: (rid: string) => void }) {
  const api = useAppApi()
  const [data, setData] = useState<Scorecard | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let alive = true
    let timer: ReturnType<typeof setTimeout> | undefined
    const pull = async () => {
      try {
        const d = await api.get<Scorecard>(paths.scorecard())
        if (!alive) return
        setData(d)
        setError('')
      } catch (e) {
        if (alive) setError(errorText(e))
      }
      if (alive) timer = setTimeout(() => void pull(), pollMs)
    }
    void pull()
    return () => {
      alive = false
      clearTimeout(timer)
    }
  }, [api, pollMs])

  const t = data?.total
  const checks = t?.caught ? Object.entries(t.caught) : []
  return (
    <div className="kt-root cto-root sc-root" data-testid="sc-root">
      <style>{BOARD_CSS}</style>
      <style>{SC_CSS}</style>
      <style>{KIT_CSS}</style>
      <header className="sc-head">
        <h2>评分卡</h2>
        <p>只放量出来的数：都取自运行记录、检查结果和台架的动作记录。没有运行做到那一步的数空着（{EMPTY}），不写 0。{t ? `共 ${t.runs} 次运行。` : ''}</p>
      </header>
      {error && <div className="kt-banner" role="status">评分卡刷新失败：{error}{data ? '，显示的是上一次拿到的数据' : ''}</div>}
      {!data && !error && <p className="kt-loading">正在读评分卡…</p>}
      {t && (
        <>
          <div className="cto-cards">
            <Card label="发现：修复 / 说明 / 延后" value={t.findings ? `${t.findings.fixed} / ${t.findings.justified} / ${t.findings.deferred}` : EMPTY} empty={isEmpty(t.findings)} />
            <Card label="被推翻的说明" value={n(t.overturned)} empty={isEmpty(t.overturned)} />
            <Card label="构建修复轮数" value={n(t.build_rounds)} empty={isEmpty(t.build_rounds)} />
            <Card label="日志差异" value={n(t.logdiff?.differences)} of={t.logdiff ? `未解释 ${t.logdiff.unexplained}` : undefined} empty={isEmpty(t.logdiff)} />
            <Card label="台架动作：批准 / 拒绝 / 核对" value={t.bench ? `${t.bench.approved} / ${t.bench.refused} / ${t.bench.reconciled}` : EMPTY} empty={isEmpty(t.bench)} />
            <Card label="独立重跑结果不同的检查" value={n(t.rerun_differs)} empty={isEmpty(t.rerun_differs)} />
          </div>
          <section className="cto-card" data-testid="sc-caught">
            <h3>台架之前拦下的检查失败（按检查）</h3>
            {checks.length ? (
              <table className="sc-table">
                <thead><tr><th>检查</th><th>失败的轮数</th></tr></thead>
                <tbody>{checks.map(([k, v]) => <tr key={k}><td><code>{k}</code></td><td>{v}</td></tr>)}</tbody>
              </table>
            ) : <p className="kt-dim">{EMPTY} 还没有运行跑过台架之前的检查</p>}
          </section>
          <section className="cto-card" data-testid="sc-runs">
            <h3>每次运行</h3>
            {data.runs.length ? (
              <div className="sc-wide">
                <table className="sc-table">
                  <thead>
                    <tr>
                      <th>运行</th><th>修复 / 说明 / 延后</th><th>被推翻的说明</th><th>到分诊批准</th><th>到检查第一次全过</th><th>到签字</th>
                      <th>构建修复轮数</th><th>台架之前拦下</th><th>日志差异</th><th>台架：批准 / 拒绝 / 核对</th><th>重跑结果不同</th>
                    </tr>
                  </thead>
                  <tbody>{data.runs.map((r) => <RunRow key={r.id} r={r} onDetail={onDetail} />)}</tbody>
                </table>
              </div>
            ) : <p className="kt-dim">还没有运行。在团队看板上用「新需求」开始一次。</p>}
          </section>
        </>
      )}
      <details className="sc-notes">
        <summary>口径：每个数怎么来的</summary>
        <ul>
          <li>发现：批准的分诊（triage.json）里每个决定；分诊按 TR §4.4 新加的条目（本批的重构）不算。</li>
          <li>被推翻的说明：分诊建议说明的发现，人在分诊关卡没有选 A（退回时记下），或评审「要改」的回复点了名、而批准的分诊说明了它的。</li>
          <li>时间：从运行开始（给出需求）算的墙钟时间，到分诊批准、到台架之前的检查第一次全部通过、到签字；等关卡、停下再重试的时间都在内。时间只按次列，不加总。</li>
          <li>构建修复轮数：build 检查没过，app 打回修复的轮数。台架之前拦下：每个检查在台架之前的各轮里 FAIL 的轮数（BLOCKED 不算）。</li>
          <li>日志差异：每次台架回放后 logdiff 找到的差异，和其中批准的差异解释不了的；独立重跑判的是最后一次回放，不重复算。其中几处是真的行为变化，app 不记录人的这一判断，所以不列。</li>
          <li>台架动作：操作台对这次运行的请求做的决定（超时没人批准算拒绝），和这次运行最近一次请求之后的核对（reconcile），取自台架的动作记录 actions.jsonl。</li>
          <li>独立重跑结果不同的检查：签字前在新结果目录里从头重跑全部检查，结论和运行最后一轮不同的检查。</li>
          <li>按权限类别统计的工具调用来自 build 和 bench 两个 MCP 服务器的审计日志；这个 app 里 agent 不用它们，所以不列。</li>
        </ul>
      </details>
    </div>
  )
}
