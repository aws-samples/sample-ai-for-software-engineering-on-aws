/**
 * 交付详情: one delivery, between the CTO 视图 (every delivery) and the 团队看板 (how a run went). It answers what a CTO
 * asks of one delivery — how long it took against before, where the time went (agent or waiting for a person), what it
 * cost, whether quality held (checks, send-backs, defects after release), what people decided, and its Issue → PR —
 * and every one of them opens the board where it happened: a segment of the 价值流 at that phase and moment of the
 * run's replay, a decision at its gate, the checks on the 测试墙, the PR on the 签字单.
 *
 * One look with the other two views: the board's title row (the delivery's name, its Issue and status pills), the CTO
 * view's cards (eyebrow, big number, a mini chart, the links at the foot), charts (stream.tsx, in the 每周上线 style, with
 * a table view) and tables, and the board's line icons for the roles and the moments.
 *
 * A run of this app (实测, or still going) has its 价值流 from `GET /cto/flow`; a delivery of the simulated history has
 * no run: the page says so and offers the 同类实测 (the same business line and type, else the same type).
 */
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useAppApi } from '@kirocrew/app-sdk'
import { BOARD_CSS } from '../board/styles'
import { fmtClock, paths } from '../board/format'
import { RoleIcon } from '../board/RoleIcon'
import { errorText } from '../board/useBoard'
import type { BoardEntry, CtoEntry, ItemEntry } from '../nav'
import { MiniCycle, MiniSplit, fmtSec } from './charts'
import { KIND, SIZE, baseCycles, day1, md, waited } from './metrics'
import { StreamChart, VS_COLOR, VS_NAME, boardAt, markAt, segAt, segKind } from './stream'
import { CTO_CSS } from './styles'
import { KIT_CSS } from '../kit'
import type { CtoData, CtoFlow, CtoItem, CtoWip } from './types'

export { boardAt } from './stream'
export const ITEM_POLL_MS = 5000

/** The delivery the page is about, whether it was delivered (交付清单) or is in progress (需求流动). */
export type Subject = { item?: CtoItem; wip?: CtoWip }

export function findSubject(data: CtoData, e: ItemEntry): Subject {
  if (e.run) return { item: data.items.find((i) => i.real === e.run), wip: data.wip.find((w) => w.real === e.run) }
  return { item: data.items.find((i) => i.issue === e.issue), wip: data.wip.find((w) => w.issue === e.issue) }
}

/** 同类实测: a measured run like this delivery (same line and type, else same type, else same line, else the newest). */
export function similarReal(items: CtoItem[], x: { line: number; kind: string }): CtoItem | undefined {
  const reals = items.filter((i) => i.real)
  return reals.find((i) => i.line === x.line && i.kind === x.kind) ?? reals.find((i) => i.kind === x.kind) ?? reals.find((i) => i.line === x.line) ?? reals[0]
}

const BACK_KINDS = new Set(['bounce', 'check', 'review'])
const PR_STATE: Record<string, string> = { open: '待合并', merged: '已合入 main', signed: '已签字放行' }
const localDay = (t: number) => {
  const d = new Date(t * 1000)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

type Props = {
  entry: ItemEntry
  onCto: (e: CtoEntry) => void
  onItem: (e: ItemEntry) => void
  onBoard: (e: BoardEntry) => void
  /** ← 返回: back to the view it was opened from (its entry says from=…) */
  onBack?: () => void
  /** opened again by back or forward: the app puts the page back where it was left, so it does not scroll here */
  returning?: boolean
  projection?: boolean
  pollMs?: number
}

export function ItemView({ entry, onCto, onItem, onBoard, onBack, returning = false, projection = false, pollMs = ITEM_POLL_MS }: Props) {
  const api = useAppApi()
  const [data, setData] = useState<CtoData | null>(null)
  const [flow, setFlow] = useState<CtoFlow | null>(null)
  const [error, setError] = useState('')
  const [asTable, setAsTable] = useState(false)
  useEffect(() => {
    let alive = true
    let timer: ReturnType<typeof setTimeout> | undefined
    const pull = async () => {
      try {
        const [d, f] = await Promise.all([api.get<CtoData>(paths.cto()), entry.run ? api.get<CtoFlow>(paths.ctoFlow(entry.run)) : Promise.resolve(null)])
        if (!alive) return
        setData(d)
        setFlow(f)
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
  }, [api, entry.run, entry.issue, pollMs])
  const base = useMemo(() => (data ? baseCycles(data.items) : null), [data])
  // back from the board at a moment: the 价值流 is where to look
  const looked = useRef(false)
  useEffect(() => {
    if (!flow || looked.current || entry.at === undefined || returning) return
    looked.current = true
    setTimeout(() => document.querySelector('[data-testid="item-root"] section[aria-label="价值流"]')?.scrollIntoView?.({ behavior: 'smooth', block: 'start' }), 80)
  }, [flow]) // eslint-disable-line react-hooks/exhaustive-deps
  // the tab with no delivery in hand: the newest 实测
  useEffect(() => {
    const newest = !entry.run && !entry.issue ? data?.items.find((i) => i.real) : undefined
    if (newest?.real) onItem({ run: newest.real })
  }, [data]) // eslint-disable-line react-hooks/exhaustive-deps

  const backBtn = onBack && <button type="button" className="kt-btn" onClick={onBack}>← 返回{entry.from === 'board' ? '团队看板' : ' CTO 视图'}</button>
  const shell = (body: ReactNode) => (
    <div className={`kt-root cto-root cto-item${projection ? ' is-projection' : ''}`} data-testid="item-root">
      <style>{BOARD_CSS}</style>
      <style>{CTO_CSS}</style>
      <style>{KIT_CSS}</style>
      {body}
    </div>
  )
  if (!data || !base) return shell(<p className="cto-dim">{error ? `交付详情的数据拿不到：${error}` : '正在读取交付…'}</p>)
  const { item, wip } = findSubject(data, entry)
  const x = item ?? wip
  if (!x) {
    return shell(
      <>
        <div className="cto-top"><Crumb name="没有这项交付" onCto={() => onCto({})} /><span className="cto-grow" />{backBtn}</div>
        <p className="cto-dim">CTO 视图里没有这项交付（{entry.run ?? entry.issue}）：它可能已从列表中删除。</p>
      </>,
    )
  }
  const M = data.meta
  const key = entry.run ?? entry.issue ?? ''
  const run = entry.run
  const real = !!item?.real
  const going = !item && !!wip?.live
  const twin = run ? undefined : similarReal(data.items, x)
  const cycle = item ? (item.mins != null ? `${item.mins} 分钟` : `${day1(item.cyc)} 天`) : flow ? fmtSec(flow.end) : '—'
  const cycleDays = item ? (item.mins != null ? item.mins / 1440 : item.cyc) : flow ? flow.end / 86400 : 0
  const created = item?.created ?? (flow ? localDay(flow.issue.created_at) : undefined)
  const fix = (issue: string) => data.items.find((i) => i.issue === issue)
  const sizeName = `${SIZE[x.size]}型`

  // where the time went: agent (less its rework), rework, waiting for a person
  const split = flow
    ? (['agent', 'rework', 'person'] as const).map((k) => ({ k, s: flow.segments.filter((g) => segKind(g) === k).reduce((a, g) => a + g.to - g.from, 0) }))
    : []
  const firstWait = flow?.segments.find((s) => s.who === 'person' && s.gate !== 'signoff')
  const firstBack = flow?.marks.find((m) => BACK_KINDS.has(m.kind))
  const sentBack = flow ? flow.sent_back.person + flow.sent_back.review + flow.sent_back.checks : 0
  const members = flow?.team.filter((m) => !m.skipped) ?? []
  const atSeg = flow?.segments[segAt(flow.segments, entry.at)]
  const toPart = (k: 'agent' | 'rework' | 'person') => (k === 'person' && firstWait ? onBoard(boardAt(run as string, firstWait)) : onBoard({ run, replay: 30 }))

  return shell(
    <>
      <div className="cto-top">
        <Crumb name={x.t} onCto={() => onCto({ hl: key })} />
        <span className="cto-grow" />
        <div className="cto-item-act cto-noprint">
          {going && wip?.state === 'wait' && wip.role && <button type="button" className="kt-btn is-primary" onClick={() => onBoard({ run, gate: wip.role })}>去审批 ↗</button>}
          {run && <button type="button" className="kt-btn" onClick={() => onBoard({ run })}>在团队看板中查看 ↗</button>}
          {real && <button type="button" className="kt-btn" onClick={() => onBoard({ run, replay: 30 })}>▶ 回放 ↗</button>}
          {backBtn}
        </div>
      </div>
      <header className="cto-item-head">
        <h2 className="kt-run-title">{x.t}</h2>
        {x.issue && (
          <button type="button" className="kt-pill tone-info kt-mono kt-pill-btn" onClick={() => onCto({ hl: key })} title="在 CTO 视图的交付清单中找到这一项">{x.issue}</button>
        )}
        <span className={`kt-pill ${real ? 'tone-ok' : going ? 'tone-run is-live' : 'tone-idle'}`}>
          <i aria-hidden="true">{real ? '✔' : going ? '●' : '○'}</i>
          {real ? '实测' : going ? '进行中' : item ? '模拟' : '模拟 · 进行中'}
        </span>
        <span className="cto-org">{x.reporter ? `${x.reporter}提出 · ` : ''}{M.lines[x.line]} · {KIND[x.kind]} · {sizeName}</span>
      </header>
      {wip && (
        <p className="cto-item-now" data-testid="item-now">
          {wip.state === 'wait' ? `此刻：${wip.gate}，已等 ${waited(wip.hours ?? 0)}，${wip.focus ?? ''}` : wip.state === 'agent' ? `此刻：agent 在做 · ${wip.col} · ${wip.members} 位成员` : `此刻：在需求池，${wip.mins} 分钟前提交，待组队`}
        </p>
      )}

      <section className="cto-cards cto-item-cards" aria-label="这项交付的四个数">
        <article className="cto-card" aria-label="周期">
          <div className="cto-eyebrow">周期</div>
          <div className="cto-value" data-testid="item-cycle">{cycle}</div>
          <div className="cto-desc">{created ? `Issue ${md(created)} 创建` : 'Issue 创建'}{item ? ` → ${md(item.ship)} 签字放行` : ' → 进行中'}</div>
          <MiniCycle size={sizeName} before={base[x.size]} days={cycleDays} now={cycle} />
          <div className="cto-legend">
            <span><i className="cto-dot" style={{ background: 'var(--deemph)' }} />以前同规模</span>
            <span><i className="cto-dot" style={{ background: 'var(--s4)' }} />这次</span>
          </div>
          <div className="cto-foot"><button type="button" className="cto-link" onClick={() => onCto({ at: 'fast' })}>CTO 视图「更快」↗</button></div>
        </article>

        {flow ? (
          <article className="cto-card" aria-label="时间花在哪">
            <div className="cto-eyebrow">时间花在哪</div>
            <div className="cto-value">{fmtSec(flow.agent_s)}</div>
            <div className="cto-desc">agent 在做 · 等人批准 {fmtSec(flow.person_s)}（{flow.gates} 次关卡）</div>
            <MiniSplit total={fmtSec(flow.end)} parts={split.map(({ k, s }) => ({ label: VS_NAME[k], s, color: VS_COLOR[k], onPick: () => toPart(k) }))} />
            <div className="cto-legend">
              {split.filter((p) => p.s > 0).map(({ k, s }) => (
                <button type="button" key={k} onClick={() => toPart(k)} title={k === 'person' ? '到看板上的第一个关卡' : '在看板上回放'}>
                  <i className="cto-sw" style={{ background: VS_COLOR[k] }} />{VS_NAME[k]}<b>{fmtSec(s)}</b>
                </button>
              ))}
            </div>
          </article>
        ) : (
          <article className="cto-card" aria-label="签字">
            <div className="cto-eyebrow">签字放行</div>
            <div className="cto-value">{item ? md(item.ship) : '—'}</div>
            <div className="cto-desc">{item?.signer ? `${item.signer} 签字` : '还没有交付'}</div>
          </article>
        )}

        {flow ? (
          <article className="cto-card" aria-label="成本">
            <div className="cto-eyebrow">成本</div>
            <div className="cto-value">{flow.credits ?? '—'}<span className="cto-of">credits</span></div>
            <div className="cto-desc">{members.length} 位 agent 成员 · 人做了 {flow.decisions.length} 个决定{item ? '、1 次签字' : ''}</div>
            <div className="cto-chips" aria-label="成员">
              {flow.team.map((m) => (
                <span key={m.key} className={`cto-chip${m.skipped ? ' is-idle' : ''}`} title={m.skipped ? `${m.title}：这次不参与` : `${m.title}：${m.credits} credits`}>
                  <RoleIcon role={m.icon} size={16} />
                </span>
              ))}
            </div>
            <div className="cto-foot"><button type="button" className="cto-link" onClick={() => onBoard({ run, focus: 'lanes' })}>看每位成员的用量 ↗</button></div>
          </article>
        ) : (
          <article className="cto-card" aria-label="Issue 与 PR">
            <div className="cto-eyebrow">Issue → PR</div>
            <div className="cto-value kt-mono">{x.issue ?? '—'}</div>
            <div className="cto-desc">{x.pr ? `PR #${x.pr} 合入 main` : '还没有 PR'}</div>
          </article>
        )}

        <article className={`cto-card${flow && flow.tests.total ? (flow.tests.passed === flow.tests.total ? ' is-ok' : ' is-bad') : ''}`} aria-label="质量">
          <div className="cto-eyebrow">质量</div>
          {flow ? (
            <>
              <div className="cto-value">{flow.tests.passed}<span className="cto-of">/{flow.tests.total}</span></div>
              <div className="cto-desc">检查 {flow.tests.passed}/{flow.tests.total} 通过 · 企业统一下发 {flow.tests.enterprise} 项，agent 改不了</div>
              <button type="button" className="kt-segs cto-segs" aria-label="在团队看板的测试墙上看每一项" onClick={() => onBoard({ run, focus: 'tests' })}>
                {Array.from({ length: flow.tests.total }, (_, i) => <i key={i} className={i < flow.tests.passed ? 'is-pass' : 'is-fail'} />)}
              </button>
              <div className="cto-legend">
                <button type="button" disabled={!firstBack} onClick={() => firstBack && onBoard(markAt(run as string, firstBack))} title={firstBack ? '看板回放到第一次退回' : undefined}>
                  <RoleIcon role="bounce" size={14} />退回 {sentBack} 次：人 {flow.sent_back.person} · 审查 {flow.sent_back.review} · 检查 {flow.sent_back.checks}{firstBack ? ' ↗' : ''}
                </button>
              </div>
            </>
          ) : (
            <div className="cto-value">{item?.origin ? '缺陷修复' : `${item?.defects?.length ?? 0}`}{!item?.origin && <span className="cto-of">项上线后缺陷</span>}</div>
          )}
          <Defects x={x} fix={fix} onItem={onItem} />
        </article>
      </section>

      <section className="cto-card" aria-label="价值流">
        <div className="cto-chart-head">
          <h3>价值流</h3>
          <span className="cto-dim">{flow ? `从 Issue 创建到${flow.marks.some((m) => m.kind === 'signoff') ? '签字放行' : '此刻'}，共 ${fmtSec(flow.end)} · 点任一段或任一时刻，到团队看板的那个环节` : '模拟交付，没有运行记录：环节明细只有真实运行才有。'}</span>
          <span className="cto-grow" />
          {flow && (
            <div className="cto-seg cto-noprint" role="group" aria-label="图或表格">
              <button type="button" aria-pressed={!asTable} onClick={() => setAsTable(false)}>图</button>
              <button type="button" aria-pressed={asTable} onClick={() => setAsTable(true)}>表格</button>
            </div>
          )}
        </div>
        {flow && run ? (
          <>
            <div className="cto-legend">
              {(['agent', 'rework', 'person'] as const).map((k) => <span key={k}><i className="cto-sw" style={{ background: VS_COLOR[k] }} />{VS_NAME[k]}</span>)}
              <span className="cto-dim">· 色块上方是参与的角色，下方是关键时刻</span>
              {atSeg && entry.at !== undefined && <span className="kt-where-why" data-testid="item-at">团队看板上的 {fmtClock(entry.at)} 在「{atSeg.label}」这一段，已框出</span>}
            </div>
            {asTable ? (
              <table className="cto-table">
                <thead><tr><th>时间</th><th>环节</th><th>谁</th><th className="is-num">用时</th><th>结论</th><th /></tr></thead>
                <tbody>
                  {flow.segments.map((s, i) => (
                    <tr key={`${s.from}-${s.label}`} className={i === segAt(flow.segments, entry.at) ? 'is-hl' : undefined}>
                      <td className="kt-mono">{fmtClock(s.from)}–{fmtClock(s.to)}</td>
                      <td><span className="cto-kind"><i className="cto-sw" style={{ background: VS_COLOR[segKind(s)] }} />{s.label}</span></td>
                      <td>{s.who === 'person' ? '负责人' : s.roles.map((k) => flow.titles[k] ?? k).join('、')}</td>
                      <td className="is-num">{fmtSec(s.to - s.from)}</td>
                      <td>{s.decision ?? ''}</td>
                      <td><button type="button" className="cto-link" onClick={() => onBoard(boardAt(run, s))}>看板 ↗</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <StreamChart flow={flow} run={run} onBoard={onBoard} hlAt={entry.at} />
            )}
          </>
        ) : (
          twin?.real && (
            <div className="cto-item-twinrow" data-testid="item-twin">
              <div>
                <div className="cto-eyebrow">同类实测</div>
                <b>{twin.t}</b>
                <div className="cto-dim">{M.lines[twin.line]} · {KIND[twin.kind]} · {twin.mins} 分钟 · 检查 {twin.tests} 通过</div>
              </div>
              <button type="button" className="kt-btn is-primary" onClick={() => onItem({ run: twin.real as string })}>看它的价值流 ↗</button>
              <button type="button" className="kt-btn" onClick={() => onBoard({ run: twin.real as string, replay: 30 })}>在团队看板中回放 ↗</button>
            </div>
          )
        )}
      </section>

      {flow && run && flow.decisions.length > 0 && (
        <section className="cto-card" aria-label="负责人的决定">
          <div className="cto-chart-head">
            <h3>负责人的决定</h3>
            <span className="cto-dim">{flow.decisions.length} 个 · 每一个都能在团队看板上回放到那一刻</span>
          </div>
          <table className="cto-table">
            <thead><tr><th>时间</th><th>决定</th><th>意见</th><th /></tr></thead>
            <tbody>
              {flow.decisions.map((d) => {
                const ok = d.gate.startsWith('批准')
                return (
                  <tr key={`${d.at}-${d.gate}`}>
                    <td className="kt-mono cto-dim">{fmtClock(d.at)}</td>
                    <td><span className="cto-gatecell"><span className={`cto-chip is-small${ok ? '' : ' is-back'}`}><RoleIcon role={ok ? 'approved' : 'bounce'} size={14} /></span>{d.gate}</span></td>
                    <td>{d.note}</td>
                    <td><button type="button" className="cto-link" onClick={() => onBoard({ run, gate: d.role, at: Math.round(d.at) })}>看板 · 回放到这一刻 ↗</button></td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </section>
      )}

      {flow && (
        <section className={`cto-card${flow.pr?.state === 'merged' ? ' is-ok' : ''}`} aria-label="Issue 与 PR">
          <div className="cto-chart-head">
            <h3>Issue → PR</h3>
            <span className="cto-dim">需求从哪里来，代码怎样合入 main</span>
          </div>
          <div className="cto-item-chain">
            <div className="cto-chainpart">
              <span className="cto-chip is-plain"><RoleIcon role="issue" size={16} /></span>
              <div>
                <b className="kt-mono">{x.issue ?? '—'}</b>
                <div className="cto-dim">{flow.issue.kind}{x.reporter ? ` · ${x.reporter}提出` : ''}{created ? ` · ${md(created)} 创建` : ''}</div>
              </div>
            </div>
            <span className="cto-item-arrow" aria-hidden="true">→</span>
            <div className="cto-chainpart">
              <span className={`cto-chip${flow.pr?.state === 'open' ? ' is-wait' : ''}`}><RoleIcon role={flow.pr?.state === 'merged' ? 'merge' : 'pr'} size={16} /></span>
              <div>
                {flow.pr ? (
                  <button type="button" className="cto-link kt-mono" onClick={() => onBoard({ run, focus: 'signoff' })}>PR #{flow.pr.number} ↗</button>
                ) : (
                  <b className="kt-mono">还没有</b>
                )}
                <div className="cto-dim">
                  {flow.pr ? `${flow.pr.head} → main · ${flow.pr.files} 个文件 +${flow.pr.added} −${flow.pr.removed} · ${PR_STATE[flow.pr.state]}` : '交付后开出，签字放行时合入 main'}
                </div>
              </div>
            </div>
          </div>
        </section>
      )}
      {error && <div className="kt-banner" role="status">交付详情刷新失败：{error}，显示的是上一次拿到的数据</div>}
    </>,
  )
}

function Crumb({ name, onCto }: { name: string; onCto: () => void }) {
  return (
    <nav className="kit-crumb" aria-label="位置">
      <button type="button" onClick={onCto}>CTO 视图</button>
      <span aria-hidden="true">›</span>
      <b>{name}</b>
    </nav>
  )
}

function Defects({ x, fix, onItem }: { x: CtoItem | CtoWip; fix: (issue: string) => CtoItem | undefined; onItem: (e: ItemEntry) => void }) {
  const item = 'ship' in x ? x : null
  if (!item) return null
  if (item.origin) {
    return (
      <div className="cto-foot"><button type="button" className="cto-link" onClick={() => onItem({ issue: item.origin })}>修复 {item.origin} 上线后的缺陷 ↗</button></div>
    )
  }
  const ds = item.defects ?? []
  if (!ds.length) return <div className="cto-foot">上线后缺陷 0</div>
  return (
    <div className="cto-foot cto-defect">
      上线后缺陷 {ds.length}：
      {ds.map((d) => {
        const f = fix(d)
        return (
          <button type="button" key={d} className="cto-link" onClick={() => onItem(f?.real ? { run: f.real } : { issue: d })}>{d} ↗</button>
        )
      })}
    </div>
  )
}
