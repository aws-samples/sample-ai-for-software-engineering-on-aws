/**
 * 需求流动: the kanban of what is in progress now, one card an Issue. Columns are the AI-DLC phases (需求池 → 构思 → 启动 →
 * 构建 → 运维 → 已交付), lanes are 等人批准 (a person's gate, the board's word and magenta for it) and agent 在做; at most
 * two cards a cell. Every card opens its 交付详情. A column's heading opens that phase on the 团队看板 (the run going there,
 * else the newest 实测, its replay paused where the phase began); a lane's heading opens a gate or the agents at work.
 */
import { RoleIcon } from '../board/RoleIcon'
import type { BoardEntry, ItemEntry } from '../nav'
import { itemOf } from '../nav'
import { daysBefore, fmt, inLine, md, mean, waited } from './metrics'
import type { CtoData, CtoItem, CtoWip } from './types'

const COLS: [string, string][] = [['需求池', '已提交，待组队'], ['构思', '意图 · 约束 · 范围'], ['启动', '需求 · 设计 · 分工'], ['构建', '代码 · 测试 · 独立审查'], ['运维', '部署 · 上线 · 签字'], ['已交付', '近 7 天 · 点开看交付详情']]
const STAGES = ['构思', '启动', '构建', '运维'] as const
/** a kanban column's AI-DLC phase on the board */
export const COL_PHASE: Record<string, string> = { 构思: 'ideation', 启动: 'inception', 构建: 'construction', 运维: 'operation' }

/** a gate's icon on its card: the board's icon of the role that stops there */
const GATE_ICON: Record<string, string> = { 范围关卡: 'scope', 需求关卡: 'pm', 方案关卡: 'architect', 上线关卡: 'compliance', 安全关卡: 'security', 签字放行: 'sign' }

export type FlowHandlers = {
  onOpen: (e: BoardEntry) => void
  onItem: (e: ItemEntry) => void
  /** 等人批准 with no run of this app waiting: a 实测's first gate, at its moment */
  onGateOf: (run: string) => void
  onLedger: () => void
}

function Card({ w, lines, hl, h }: { w: CtoWip; lines: string[]; hl: string | null; h: FlowHandlers }) {
  const key = w.real ?? w.issue ?? ''
  const go: BoardEntry | null = w.live && w.real ? (w.state === 'wait' && w.role ? { run: w.real, gate: w.role } : { run: w.real }) : null
  const open = () => (w.real || w.issue) && h.onItem(itemOf(w))
  return (
    <div className={`cto-kcard cto-pick${go ? ` is-live is-${w.state}` : ''}${hl === key ? ' is-hl' : ''}`} data-key={key} data-testid={go ? 'cto-live-card' : undefined}
      role="button" tabIndex={0} title="交付详情" onClick={open} onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), open())}>
      <div className="cto-ktop">
        {w.state === 'wait' ? (
          <>
            <span className="cto-gate"><RoleIcon role={w.role || GATE_ICON[w.gate ?? ''] || 'wait'} size={13} />{w.gate}</span>
            <span>已等 {waited(w.hours ?? 0)}</span>
          </>
        ) : w.state === 'agent' ? (
          <span>{w.members} 位成员 · 已用 {w.mins} 分钟</span>
        ) : (
          <>
            <span>待组队</span>
            <span>{w.mins} 分钟前提交</span>
          </>
        )}
      </div>
      <div className="cto-ktitle" title={w.t}>{w.t}</div>
      {w.state === 'wait' && <div className="cto-kfocus">{w.focus}</div>}
      <div className="cto-kmeta" title={w.reporter ? `${w.issue ?? ''} · ${w.reporter}提出` : undefined}>
        {lines[w.line]}{w.issue ? ` · ${w.issue}` : ''}{w.pr ? ` · PR #${w.pr} 待合并` : ''}{w.state === 'wait' ? ` · 等 ${w.who}` : ''}
      </div>
      {go && (
        <button type="button" className="kt-btn is-small is-primary" onClick={(e) => { e.stopPropagation(); h.onOpen(go) }}>
          {w.state === 'wait' ? '去审批 ↗' : '打开 ↗'}
        </button>
      )}
    </div>
  )
}

function Cell({ list, lines, hl, h, wait, empty }: { list: CtoWip[]; lines: string[]; hl: string | null; h: FlowHandlers; wait?: boolean; empty?: string }) {
  return (
    <div className={`cto-cell${wait ? ' is-wait' : ''}`}>
      {list.length === 0 && empty && <div className="cto-kempty">{empty}</div>}
      {list.slice(0, 2).map((w, i) => <Card key={`${w.t}-${i}`} w={w} lines={lines} hl={hl} h={h} />)}
      {list.length > 2 && <div className="cto-kmore">+{list.length - 2} 项</div>}
    </div>
  )
}

export function Flow({ data, line, fresh, hl = null, ...h }: { data: CtoData; line: number; fresh: ReadonlySet<string>; hl?: string | null } & FlowHandlers) {
  const M = data.meta
  const W = data.wip.filter(inLine(line))
  const waits = W.filter((w) => w.state === 'wait'), agents = W.filter((w) => w.state === 'agent'), pool = W.filter((w) => w.state === 'pool')
  const live = (a: CtoWip, b: CtoWip) => (b.live ? 1 : 0) - (a.live ? 1 : 0)
  const d7 = daysBefore(M.today, 6)
  const done = data.items.filter((i) => i.period === 'agent' && i.ship >= d7 && inLine(line)(i))
  const pin = (i: CtoItem) => (i.real && fresh.has(i.real) ? 0 : i.real ? 1 : 2)
  const shown = [...done].sort((a, b) => pin(a) - pin(b) || (a.ship < b.ship ? 1 : -1)).slice(0, 4)
  const count = (col: string) => (col === '需求池' ? pool.length : col === '已交付' ? done.length : W.filter((w) => w.col === col && w.state !== 'pool').length)
  const latest = data.items.find((i) => i.real && inLine(line)(i)) ?? data.items.find((i) => i.real)
  // a column's heading: that phase on the board, in the run of this app that is there now, else the newest 实测
  const openCol = (col: string) => {
    if (col === '需求池') return h.onOpen({ new: 'promo' })
    if (col === '已交付') return h.onLedger()
    const here = W.find((w) => w.live && w.real && w.col === col)
    const run = here?.real ?? latest?.real
    if (run) h.onOpen({ run, phase: COL_PHASE[col], ...(here ? {} : { pick: 'latest' as const }) })
  }
  const openWaits = () => {
    const here = [...waits].filter((w) => w.live && w.real && w.role).sort((a, b) => (b.hours ?? 0) - (a.hours ?? 0))[0]
    if (here) h.onOpen({ run: here.real as string, gate: here.role })
    else if (latest?.real) h.onGateOf(latest.real)
  }
  const openAgents = () => {
    const here = agents.find((w) => w.live && w.real)
    if (here) h.onOpen({ run: here.real as string })
    else if (latest?.real) h.onOpen({ run: latest.real, replay: 30, pick: 'latest' })
  }
  const colTitle = (col: string) =>
    col === '需求池' ? '在团队看板上提一个新需求' : col === '已交付' ? '看下方交付清单' : `在团队看板上看「${col}」这个环节（${W.some((w) => w.live && w.col === col) ? '此刻在这里的运行' : '最近一次实测'}）`
  return (
    <section className="cto-card cto-flow" aria-label="需求流动" data-anchor="flow">
      <div className="cto-flow-head">
        <span className="cto-live" aria-hidden="true" />
        <h3>需求流动</h3>
        <span className="cto-dim">此刻 · 来自 Kiro Crew · 每 5 秒刷新 · 点卡片看交付详情，点列名到团队看板的这个环节</span>
        <span className="cto-grow" />
        <button type="button" className="kt-btn is-small cto-noprint cto-noproj" onClick={() => h.onOpen({ new: 'promo' })} title="在团队看板上提交一个新需求（双十一 · 家电大促 已填好）">新需求 ↗</button>
      </div>
      <div className="cto-stats" data-testid="cto-flow-stats">
        进行中 {fmt(waits.length + agents.length)} 项<span>·</span>agent 在做 {fmt(agents.length)} 项<span>·</span>等人批准 {fmt(waits.length)} 项<span>·</span>需求池 {fmt(pool.length)} 项
      </div>
      <div className="cto-dim">
        等人批准的平均已等 {waited(mean(waits.map((w) => w.hours ?? 0)))}；agent 完成一次运行，实测平均 {M.realAvgMins} 分钟。
      </div>
      <div className="cto-kanban" role="table" aria-label="需求流动看板">
        <div />
        {COLS.map(([name, sub]) => (
          <div className="cto-kb-h" key={name}>
            <button type="button" onClick={() => openCol(name)} title={colTitle(name)}>
              <div><b>{name}{name !== '已交付' ? ' ↗' : ''}</b><span className="cto-n">{fmt(count(name))}</span></div>
              <div className="cto-st">{sub}</div>
            </button>
          </div>
        ))}
        <div className="cto-lane is-wait"><button type="button" onClick={openWaits} title="到团队看板上等人批准的关卡"><RoleIcon role="wait" size={15} />等人批准 ↗</button></div>
        <div className="cto-cell is-span">
          {[...pool].sort((a, b) => (a.mins ?? 0) - (b.mins ?? 0)).slice(0, 2).map((w, i) => <Card key={i} w={w} lines={M.lines} hl={hl} h={h} />)}
          {pool.length > 2 && <div className="cto-kmore">+{pool.length - 2} 项</div>}
        </div>
        {STAGES.map((col) => (
          <Cell key={`w-${col}`} wait lines={M.lines} hl={hl} h={h} list={waits.filter((w) => w.col === col).sort((a, b) => live(a, b) || (b.hours ?? 0) - (a.hours ?? 0))}
            empty={col === '构建' ? '这一阶段没有人的关卡：检查不过自动退回给 agent' : '此刻没有'} />
        ))}
        <div className="cto-cell is-span">
          {shown.map((i) => {
            const key = i.real ?? i.issue ?? i.t
            return (
              <button type="button" key={`${key}-${i.ship}`} data-key={key} className={`cto-kcard${i.real ? ' is-real' : ''}${i.real && fresh.has(i.real) ? ' is-new' : ''}${hl === key ? ' is-hl' : ''}`}
                title="交付详情" onClick={() => h.onItem(itemOf(i))}>
                <span className="cto-ktop">
                  <span>{i.real && fresh.has(i.real) ? '刚刚' : md(i.ship)}</span>
                  {i.real ? <span className="cto-tag is-real">实测</span> : <span>模拟</span>}
                </span>
                <span className="cto-ktitle">{i.t}</span>
                <span className="cto-kmeta">{M.lines[i.line]} · {i.mins != null ? `${i.mins} 分钟` : `${Math.round(i.cyc * 10) / 10} 天`}</span>
              </button>
            )
          })}
          {done.length > shown.length && <button type="button" className="cto-kmore cto-link" onClick={h.onLedger}>+{fmt(done.length - shown.length)} 项（见下方交付清单）</button>}
        </div>
        <div className="cto-lane"><button type="button" onClick={openAgents} title="到团队看板上看 agent 在做什么">agent 在做 ↗</button></div>
        {STAGES.map((col) => (
          <Cell key={`a-${col}`} lines={M.lines} hl={hl} h={h} list={agents.filter((w) => w.col === col).sort((a, b) => live(a, b) || (b.mins ?? 0) - (a.mins ?? 0))} />
        ))}
      </div>
    </section>
  )
}
