/**
 * CTO 视图: what AI-DLC delivered, for a CTO — one sentence and three numbers (更多、更快、更省), the weekly releases,
 * 需求流动 (what is in progress now) and the 交付清单. Everything is computed from `GET /cto` (metrics.ts), every 5 s:
 * a run of this app shows up on the kanban as it goes and in the numbers once a person signs it off. Its buttons open
 * the 团队看板 at the right place (onOpen, marked ↗); 下载 saves a PDF (the browser's print), the ledger as CSV, or an
 * offline page. 投影 is the app's (AppBar.tsx): this view takes bigger type while it is on. Each delivery carries its
 * Issue and PR; a defect raised after something shipped links the two. The method notes are at the foot of the page (口径).
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useAppApi } from '@kirocrew/app-sdk'
import { BOARD_CSS } from '../board/styles'
import { paths } from '../board/format'
import { errorText } from '../board/useBoard'
import { itemOf, type BoardEntry, type CtoEntry, type CtoFilters, type ItemEntry } from '../nav'
import { boardAt } from './stream'
import { MiniCheap, MiniFast, MiniMore, WeeklyChart, MiniSteady } from './charts'
import { Flow } from './Flow'
import { KIND, KINDS, KIND_VAR, SIZE, baseCycles, day1, fmt, ledger, ledgerCsv, md, metrics, ratioOf, wan, weekly, money } from './metrics'
import { CTO_CSS } from './styles'
import { KIT_CSS } from '../kit'
import type { CtoData, CtoFlow, CtoItem, Kind, Size } from './types'

export const CTO_POLL_MS = 5000

function save(text: string, name: string, type: string): boolean {
  if (typeof URL.createObjectURL !== 'function') return false
  const a = document.createElement('a')
  a.href = URL.createObjectURL(new Blob([text], { type }))
  a.download = name
  document.body.append(a)
  a.click()
  setTimeout(() => {
    URL.revokeObjectURL(a.href)
    a.remove()
  }, 0)
  return true
}

type Props = {
  onOpen: (e: BoardEntry) => void
  /** a delivery's 交付详情 */
  onItem?: (e: ItemEntry) => void
  /** the way in: its filters, a delivery to pick out, a part to scroll to */
  entry?: CtoEntry
  /** the filters changed (or the delivery picked out faded): the app rewrites the URL's entry */
  onState?: (f: CtoFilters) => void
  /** opened again by back or forward: the app puts the page back where it was left, so it does not scroll here */
  returning?: boolean
  pollMs?: number
  projection?: boolean
  onProjection?: (on: boolean) => void
}

export function CtoView({ onOpen, onItem = () => {}, onState, returning = false, entry, pollMs = CTO_POLL_MS, projection = false, onProjection }: Props) {
  const api = useAppApi()
  const [data, setData] = useState<CtoData | null>(null)
  const [error, setError] = useState('')
  const [line, setLine] = useState(entry?.line ?? -1)
  const [kind, setKind] = useState<Kind | 'all'>(entry?.type ?? 'all')
  const [realOnly, setRealOnly] = useState(!!entry?.real)
  const [size, setSize] = useState<Size | null>(entry?.size ?? null)
  const [week, setWeek] = useState<string | null>(entry?.week ?? null)
  const [defects, setDefects] = useState<boolean>(entry?.defects ?? false)
  const [hl, setHl] = useState<string | null>(null)
  const [limit, setLimit] = useState(12)
  const [perDay, setPerDay] = useState('')
  const [calcOpen, setCalcOpen] = useState(false)
  const [printing, setPrinting] = useState(false)
  const [toast, setToast] = useState('')
  const [fresh, setFresh] = useState<ReadonlySet<string>>(new Set())
  const seen = useRef<Set<string> | null>(null)
  const dlRef = useRef<HTMLDetailsElement>(null)
  const ledgerRef = useRef<HTMLElement>(null)

  // GET /cto now and every pollMs; a run signed off since the last poll is 「刚刚」
  useEffect(() => {
    let alive = true
    let timer: ReturnType<typeof setTimeout> | undefined
    const pull = async () => {
      try {
        const d = await api.get<CtoData>(paths.cto())
        if (!alive) return
        const reals = new Set(d.items.flatMap((i) => (i.real ? [i.real] : [])))
        if (seen.current) {
          const added = [...reals].filter((r) => !seen.current?.has(r))
          if (added.length) setFresh((f) => new Set([...f, ...added]))
        }
        seen.current = reals
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

  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(''), 3600)
    return () => clearTimeout(t)
  }, [toast])

  // 投影 is the app's; Esc here ends it (full screen ends on its own)
  useEffect(() => {
    if (!projection) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onProjection?.(false)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [projection, onProjection])

  // PDF: the browser's print of this view only, light, without the controls
  useEffect(() => {
    const before = () => setPrinting(true)
    const after = () => setPrinting(false)
    window.addEventListener('beforeprint', before)
    window.addEventListener('afterprint', after)
    return () => {
      window.removeEventListener('beforeprint', before)
      window.removeEventListener('afterprint', after)
    }
  }, [])

  const base = useMemo(() => (data ? baseCycles(data.items) : { S: 0, M: 0, L: 0 }), [data])
  const m = useMemo(() => (data ? metrics(data, line, base) : null), [data, line, base])
  const weeks = useMemo(() => (data ? weekly(data.items, data.meta, line) : []), [data, line])
  const rows = useMemo(() => (data ? ledger(data.items, line, kind, realOnly, fresh, { size, week, defects }) : []), [data, line, kind, realOnly, fresh, size, week, defects])
  // the filters in the URL: a change rewrites the view's history entry (and drops the delivery picked out)
  const filters = (): CtoFilters => ({ ...(line >= 0 ? { line } : {}), ...(kind !== 'all' ? { type: kind } : {}), ...(size ? { size } : {}), ...(week ? { week } : {}), ...(realOnly ? { real: true } : {}), ...(defects ? { defects: true } : {}) })
  const now = useRef(filters)
  now.current = filters
  const first = useRef(true)
  useEffect(() => {
    if (first.current) {
      first.current = false
      return
    }
    onState?.(filters())
  }, [line, kind, realOnly, size, week, defects]) // eslint-disable-line react-hooks/exhaustive-deps
  // the way in: once the data is here, the delivery asked for is picked out — its ledger row under the filters it was left
  // with (they are relaxed, and the page says so, only when it is not under them), else its kanban card — or a part
  const entered = useRef(false)
  useEffect(() => {
    if (!data || entered.current || !entry) return
    entered.current = true
    const go = (sel: string, block: ScrollLogicalPosition = 'start') => void (returning || setTimeout(() => document.querySelector(sel)?.scrollIntoView?.({ behavior: 'smooth', block }), 80))
    if (entry.at) go(`[data-anchor="${entry.at}"]`)
    const key = entry.hl
    if (!key) return
    const is = (i: CtoItem) => i.real === key || i.issue === key
    setHl(key)
    setTimeout(() => {
      setHl(null)
      onState?.(now.current())  // the URL no longer picks it out: a reload does not jump to it again
    }, 6000)
    const under = ledger(data.items, line, kind, realOnly, fresh, { size, week, defects }).findIndex(is)
    if (under >= 0) {
      setLimit((n) => Math.max(n, under + 1))
      go(`[data-key="${key}"]`, 'center')
      return
    }
    const all = ledger(data.items, -1, 'all', false, fresh).findIndex(is)
    const before = all < 0 ? data.items.find(is) : undefined
    if (all >= 0 || before) {
      if (Object.keys(filters()).length) setToast('这一项不在刚才的筛选里，已改为显示全部业务线和类型')
      setLine(-1)
      setKind('all')
      setRealOnly(false)
      setSize(null)
      setDefects(false)
      setWeek(before ? (data.meta.weeks.filter((w) => w <= before.ship).pop() ?? null) : null)
      setLimit(Math.max(12, before ? 30 : all + 1))
      go(`[data-key="${key}"]`, 'center')
    } else if (data.wip.some((w) => w.real === key || w.issue === key)) {
      go(`[data-key="${key}"]`, 'center')
    }
  }, [data]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!data || !m) {
    return (
      <div className="kt-root cto-root" data-testid="cto-root">
        <style>{BOARD_CSS}</style>
        <style>{CTO_CSS}</style>
        <style>{KIT_CSS}</style>
        <p className="cto-dim">{error ? `CTO 视图的数据拿不到：${error}` : '正在读取交付数据…'}</p>
      </div>
    )
  }
  const M = data.meta
  const scopeName = line < 0 ? '全部业务线' : M.lines[line]
  const scope = line < 0 ? `研发中心 ${m.seats} 人 · ${M.lines.length} 条业务线` : `${M.lines[line]} · ${m.seats} 人`
  const st = m.steady
  const value = Number(perDay) > 0 ? `¥${wan(m.built.length * m.adv * Number(perDay))}` : '—'
  const pickKind = (k: Kind | 'all') => {
    setKind(k)
    setLimit(12)
  }
  const toLedger = () => ledgerRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'start' })
  const latest = data.items.find((i) => i.real && (line < 0 || i.line === line)) ?? data.items.find((i) => i.real)
  // 等人批准 with no run of this app at a gate: the newest 实测's first gate, at its moment
  const gateOf = async (run: string) => {
    try {
      const f = await api.get<CtoFlow>(paths.ctoFlow(run))
      const s = f.segments.find((x) => x.who === 'person' && x.gate !== 'signoff')
      onOpen({ ...(s ? boardAt(run, s) : { run }), pick: 'latest' })
    } catch {
      onOpen({ run, pick: 'latest' })
    }
  }
  const item = (i: CtoItem) => onItem(itemOf(i))
  const stop = (f: () => void) => (e: { stopPropagation: () => void }) => {
    e.stopPropagation()
    f()
  }
  const download = async (what: 'pdf' | 'csv' | 'html') => {
    if (dlRef.current) dlRef.current.open = false
    if (what === 'pdf') {
      setPrinting(true)
      setTimeout(() => window.print(), 60)
    } else if (what === 'csv') {
      const all = ledger(data.items, line, kind, realOnly, fresh)
      if (save(ledgerCsv(all, M, base), `CTO视图-交付清单-${scopeName}-${M.today}.csv`, 'text/csv;charset=utf-8'))
        setToast(`已导出 ${fmt(all.length)} 行（${scopeName}${kind === 'all' ? '' : ` · ${KIND[kind]}`}${realOnly ? ' · 只看实测' : ''}）`)
    } else {
      try {
        const got = await api.get<{ name: string; html: string }>(paths.ctoOffline())
        if (save(got.html, got.name, 'text/html;charset=utf-8')) setToast('已下载离线版：数据为此刻的快照，不连 Kiro Crew 也能打开')
      } catch (e) {
        setToast(`离线版没下载成：${errorText(e)}`)
      }
    }
  }
  return (
    <div className={`kt-root cto-root${projection ? ' is-projection' : ''}${printing ? ' is-printing' : ''}`} data-testid="cto-root">
      <style>{BOARD_CSS}</style>
      <style>{CTO_CSS}</style>
      <style>{KIT_CSS}</style>
      <header className="cto-top">
        <span className="cto-tag" title="桃源科技是虚构的公司，历史交付是示例数据；标「实测」的是真实运行并签字的交付（含从其他电脑导入的运行）">模拟企业 · 含实测</span>
        <span className="cto-org">桃源科技 · {scope} · 引入 AI-DLC 第 12 周</span>
        <span className="cto-grow" />
        <details className="cto-dl cto-noprint cto-noproj" ref={dlRef}>
          <summary className="kt-btn">下载 ▾</summary>
          <div className="cto-menu">
            <button type="button" onClick={() => void download('pdf')}>PDF（打印版，A4 横向）</button>
            <button type="button" onClick={() => void download('csv')}>交付清单（CSV，按当前筛选）</button>
            <button type="button" onClick={() => void download('html')}>离线版（HTML，不连 Crew 也能打开）</button>
          </div>
        </details>
      </header>
      {error && <div className="kt-banner" role="status">CTO 视图刷新失败：{error}，显示的是上一次拿到的数据</div>}

      <section className="cto-hero">
        <h2>同样的研发团队，交付更多、上线更快、成本更低、质量更稳。</h2>
        <p>近 12 周对比引入 AI-DLC 之前的 12 周 · 只计签字放行的交付{m.real ? <> · <button type="button" className="cto-link" onClick={() => { setRealOnly(true); setLimit(12); toLedger() }} title="在交付清单里只看实测">其中 {m.real} 项为真实运行（实测）</button></> : ''}</p>
        <div className="cto-print-only">桃源科技 · {scopeName} · 导出于 {new Date().toLocaleString('zh-CN', { hour12: false })} · 口径见末尾</div>
      </section>

      <nav className="cto-lines" aria-label="业务线">
        {[-1, ...M.lines.map((_, i) => i)].map((li) => (
          <button type="button" key={li} aria-pressed={line === li} onClick={() => { setLine(li); setLimit(12) }}>
            <b>{li < 0 ? '全部' : M.lines[li]}</b>
            <span>交付量 {ratioOf(data.items, li).toFixed(1)} 倍</span>
          </button>
        ))}
      </nav>

      <section className="cto-cards">
        <article className={`cto-card${fresh.size ? ' cto-flash' : ''}`} key={`more-${fresh.size}`} aria-label="更多" data-anchor="more">
          <div className="cto-eyebrow">更多</div>
          <button type="button" className="cto-value cto-link-value" data-testid="cto-more" onClick={toLedger} title="看交付清单">{m.ratio.toFixed(1)} 倍</button>
          <div className="cto-desc">交付量 · 同样 {m.seats} 人</div>
          <MiniMore m={m} />
          <div className="cto-legend">
            {KINDS.map((k) => (
              <button type="button" key={k} aria-pressed={kind === k} title={`前 12 周 ${m.count(m.before, k)} 项；点击筛选下方交付清单`}
                onClick={() => { pickKind(kind === k ? 'all' : k); ledgerRef.current?.scrollIntoView({ behavior: 'smooth' }) }}>
                <i className="cto-sw" style={{ background: KIND_VAR[k] }} />{KIND[k]}<b>{fmt(m.count(m.agent, k))}</b>
              </button>
            ))}
          </div>
        </article>
        <article className="cto-card" aria-label="更快" data-anchor="fast">
          <div className="cto-eyebrow">更快</div>
          <button type="button" className="cto-value cto-link-value" data-testid="cto-fast" onClick={() => { setSize('L'); setLimit(12); toLedger() }} title="看大型需求的交付">{day1(base.L)} 天 → {m.cycle('L') ? `${day1(m.cycle('L'))} 天` : '—'}</button>
          <div className="cto-desc">大型需求的交付周期 · 点一行看这一规模的交付</div>
          <MiniFast m={m} base={base} onPick={(s) => { setSize(s); setLimit(12); toLedger() }} />
          <div className="cto-legend">
            <span><i className="cto-dot" style={{ background: 'var(--deemph)' }} />以前</span>
            <span><i className="cto-dot" style={{ background: 'var(--s4)' }} />现在</span>
          </div>
          <div className="cto-foot">
            <span>新应用和新功能平均每项提前 {day1(m.adv)} 天上线</span>
            <button type="button" className="cto-link" onClick={() => setCalcOpen((v) => !v)}>{calcOpen ? '收起 ▾' : '估算价值 ▸'}</button>
          </div>
          {calcOpen && (
            <label className="cto-calc">
              每项每天带来毛利 ¥<input type="number" min={0} step={100} value={perDay} onChange={(e) => setPerDay(e.target.value)} placeholder="填入金额" autoFocus />，约多带来 <b data-testid="cto-value">{value}</b>
            </label>
          )}
        </article>
        <article className="cto-card" aria-label="更省" data-anchor="cheap">
          <div className="cto-eyebrow">更省</div>
          <div className="cto-value" data-testid="cto-cheap">−{Math.round((1 - m.unit / M.dayRate) * 100)}%</div>
          <div className="cto-desc">每人日工作量的成本</div>
          <MiniCheap m={m} meta={M} />
          <div className="cto-foot">
            <span>近 12 周相当于节省研发投入 ¥{wan(m.save)}</span>
            {latest?.real && <button type="button" className="cto-link" onClick={() => item(latest)} title={`${latest.t}：agent 用量、人的时间和决定`}>看一次实测的消耗 ↗</button>}
          </div>
        </article>
        <article className="cto-card" aria-label="更稳" data-anchor="steady">
          <div className="cto-eyebrow">更稳</div>
          <button type="button" className="cto-value cto-link-value" data-testid="cto-steady" onClick={() => { setDefects(true); setLimit(12); toLedger() }} title="看上线后报出缺陷的交付">{st.before.toFixed(1)} → {st.now.toFixed(1)}</button>
          <div className="cto-desc">每 100 项新应用和新功能的上线后缺陷</div>
          <MiniSteady m={m} />
          <div className="cto-foot cto-foot-steady">
            <span data-testid="cto-caught">{st.reals ? `${st.reals} 项实测交付上线前拦下 ${fmt(st.caughtAll)} 个问题：检查 ${st.caught.checks} · 审查 ${st.caught.review} · 人 ${st.caught.person}` : '上线前拦下的问题：实测交付才有'}</span>
            {st.risks[0] && (
              <button type="button" className="cto-link" data-testid="cto-risk" onClick={() => onItem({ ...itemOf(st.risks[0].item), at: Math.round(st.risks[0].at) })} title={`${st.risks[0].item.t}：负责人在${st.risks[0].gate}关卡退回时记下`}>
                拦下的风险：{st.risks[0].what}{st.risks[0].amount != null ? ` ${money(st.risks[0].amount)}` : ''} ↗
              </button>
            )}
          </div>
        </article>
      </section>

      <WeeklyChart weeks={weeks} today={M.today} onWeek={(w) => { setWeek(w); setLimit(12); toLedger() }} />

      <Flow data={data} line={line} fresh={fresh} hl={hl} onOpen={onOpen} onItem={onItem} onGateOf={(r) => void gateOf(r)} onLedger={toLedger} />

      <section className="cto-card" ref={ledgerRef} aria-label="交付清单" data-anchor="ledger">
        <div className="cto-ledger-head">
          <h3>交付清单</h3>
          <div className="cto-seg cto-noprint" role="group" aria-label="类型">
            {(['all', ...KINDS] as (Kind | 'all')[]).map((k) => (
              <button type="button" key={k} aria-pressed={kind === k} onClick={() => pickKind(k)}>{k === 'all' ? '全部' : KIND[k]}</button>
            ))}
          </div>
          <button type="button" className={`kt-btn is-small cto-noprint${realOnly ? ' is-on' : ''}`} aria-pressed={realOnly} onClick={() => { setRealOnly((v) => !v); setLimit(12) }}>只看实测</button>
          {size && <span className="cto-filter">{SIZE[size]}型<button type="button" aria-label="不按规模筛选" onClick={() => setSize(null)}>✕</button></span>}
          {week && <span className="cto-filter">{md(week)} 起的一周<button type="button" aria-label="不按周筛选" onClick={() => setWeek(null)}>✕</button></span>}
          {defects && <span className="cto-filter">有上线后缺陷<button type="button" aria-label="不按上线后缺陷筛选" onClick={() => setDefects(false)}>✕</button></span>}
          <span className="cto-dim" data-testid="cto-ledger-count">共 {fmt(rows.length)} 项{realOnly ? '' : '，实测置顶'} · 点一行看交付详情</span>
        </div>
        <table className="cto-table">
          <thead>
            <tr><th>交付</th><th>业务线</th><th>类型</th><th>规模</th><th>上线</th><th>周期</th><th>签字</th><th>Issue · PR</th><th>来源</th></tr>
          </thead>
          <tbody>
            {rows.slice(0, limit).map((i) => {
              const isFresh = !!i.real && fresh.has(i.real)
              return (
                <tr key={`${i.real ?? i.t}-${i.ship}`} data-key={i.real ?? i.issue} className={`cto-row-pick${i.real ? ' is-real' : ''}${isFresh ? ' is-new' : ''}${hl && hl === (i.real ?? i.issue) ? ' is-hl' : ''}`}
                  onClick={() => item(i)} title="交付详情" tabIndex={0} onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && e.target === e.currentTarget && (e.preventDefault(), item(i))}>
                  <td>
                    <div>{i.t}</div>
                    {i.tests && (i.real ? <button type="button" className="cto-was cto-link" onClick={stop(() => onOpen({ run: i.real as string, focus: 'tests' }))} title="团队看板上的测试墙">检查 {i.tests} 通过 ↗</button> : <div className="cto-was">检查 {i.tests} 通过</div>)}
                    {i.defects?.length ? (
                      <div className="cto-defect" title={`上线后报出的缺陷：${i.defects.join('、')}`}>
                        上线后缺陷 {i.defects.length} · 修复见{' '}
                        {i.defects.map((d) => <button type="button" key={d} className="cto-link" onClick={stop(() => onItem({ issue: d }))}>{d}</button>)}
                      </div>
                    ) : null}
                    {i.origin && <button type="button" className="cto-was cto-link" onClick={stop(() => onItem({ issue: i.origin }))}>修复 {i.origin} 上线后的缺陷</button>}
                  </td>
                  <td>{M.lines[i.line]}</td>
                  <td><span className="cto-kind"><i className="cto-sw" style={{ background: KIND_VAR[i.kind] }} />{KIND[i.kind]}</span></td>
                  <td>{SIZE[i.size]}</td>
                  <td className="is-num">{isFresh ? '刚刚' : md(i.ship)}</td>
                  <td><div>{i.mins != null ? `${i.mins} 分钟` : `${day1(i.cyc)} 天`}</div><div className="cto-was">以前约 {day1(base[i.size])} 天</div></td>
                  <td>{i.real ? <button type="button" className="cto-link" onClick={stop(() => onOpen({ run: i.real as string, focus: 'signoff' }))} title="团队看板上的签字单">{i.signer} ↗</button> : i.signer}</td>
                  <td className="cto-ids">{i.issue ? <><div title={i.reporter ? `${i.reporter}提出${i.created ? `，${md(i.created)} 创建` : ''}` : undefined}><span className="kt-mono">{i.issue}</span>{i.reporter && <span className="cto-was"> {i.reporter}</span>}</div>{i.pr ? <div className="cto-was kt-mono">PR #{i.pr}</div> : null}</> : '—'}</td>
                  <td>
                    <div className="cto-src">
                      {i.real ? (
                        <>
                          <span className="cto-tag is-real">实测</span>
                          <button type="button" className="kt-btn is-small cto-noprint" onClick={stop(() => onOpen({ run: i.real as string, replay: 30 }))}>▶ 回放 ↗</button>
                        </>
                      ) : (
                        <span className="cto-tag">模拟</span>
                      )}
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
        {rows.length > limit && (
          <button type="button" className="kt-btn is-small cto-noprint" style={{ marginTop: 10 }} onClick={() => setLimit((n) => n + 30)}>显示更多（还有 {fmt(rows.length - limit)} 项）</button>
        )}
      </section>

      <details className="cto-notes" open={printing || undefined}>
        <summary>口径</summary>
        <ul>
          <li>数据：模拟的桃源科技研发中心（{M.lines.length} 条业务线，每条 {M.peoplePerLine} 人）近 12 周与引入 AI-DLC 之前 12 周的交付记录{m.real ? `；另有 ${m.real} 项来自真实运行并签字的交付（含从其他电脑导入的运行），标为「实测」` : ''}。只计签字放行的交付。</li>
          <li>更多：近 12 周上线项数 ÷ 前 12 周上线项数，同一组织、人数不变。</li>
          <li>更快：交付周期 = 上线日 − Issue 创建日；「以前」为引入前 12 周同规模交付的平均周期。模拟历史里的周期是示例值，不代表实测的效率提升。</li>
          <li>更省：每人日工作量的成本 =（实际人工人日 × ¥{fmt(M.dayRate)} + agent 订阅）÷ 完成的等价工作量。等价工作量按规模：小 {M.eq.S}、中 {M.eq.M}、大 {M.eq.L} 人日；agent 协作下的人工投入：小 {M.human.S}、中 {M.human.M}、大 {M.human.L} 人日；订阅按每人 Kiro Pro+ 每月 {M.seatUsdMonth} 美元、汇率 {M.fx}（示例值，见 cto/history.json 的 meta）。</li>
          <li>更稳：每 100 项新应用和新功能在上线后报出的缺陷（上线后报出的缺陷记为修复类交付，并链接回原交付）；实测交付还没有上线后的观察期，不计入这个比例。上线前拦下的问题 = 实测交付中检查、独立审查和人在关卡上的退回次数；拦下的风险由负责人在关卡退回时填写内容和金额。</li>
          <li>价值：本页不推算收入。填入每项每天带来的毛利后，按「新应用和新功能的项数 × 平均提前天数 × 每天毛利」估算。</li>
          <li>交付标签（类型、规模、业务线）由第一个关卡上的角色提议，负责人在关卡上确认。</li>
          <li>Issue 与 PR：每项交付对应一个 Issue（提出方、创建日）和一个合入 main 的 PR；实测运行的 PR 是它的运行分支，负责人签字放行时合入。上线后报出的缺陷记为修复类交付，与原交付互相链接。</li>
        </ul>
      </details>
      {toast && <div className="cto-toast" role="status">{toast}</div>}
    </div>
  )
}
