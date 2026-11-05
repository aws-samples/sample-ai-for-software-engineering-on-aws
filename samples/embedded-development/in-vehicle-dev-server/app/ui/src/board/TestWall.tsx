/**
 * The test wall: one cell per test case, grouped by acceptance criterion (AC-1 …), red / green / skip,
 * with the role that must make it pass. A cell whose status changed since the previous poll flips
 * (diff.ts); hovering or focusing a cell shows its name, file, owner and the first line of the failure
 * in the inspector line under the wall. The sparkline is the run's history: passed over time, one point
 * per test run of the run branch.
 *
 * A team file's checks (D7, D11) make it the check wall instead: one row per check and owner, with the check's own
 * verdict (PASS, FAIL, BLOCKED, or USAGE for a misconfigured one), the tier its evidence came from, whom it goes back to
 * (BLOCKED: a person) and its reasons.
 */
import { useState } from 'react'
import type { Lane, TestCase, TestWall as Wall } from '../types'
import { acNumber, caseGroup, caseMeta, CASE_GROUPS, fmtAgo } from './format'
import { useServerNow } from './hooks'
import { RoleIcon } from './RoleIcon'
import { t as tr } from '../i18n'

export interface TestWallProps {
  tests: Wall
  roles: Lane[]
  focus: string | null
  onRole: (key: string) => void
  flips: Record<string, number>
  /** 补登发现并交给角色, on a run held for a person after the checks (absent: not offered, e.g. in a replay) */
  onFinding?: () => void
}

export interface AcGroup {
  ac: string
  cases: TestCase[]
}

/** The group of the cases without an AC (其他), in the board's language. */
const OTHER = tr('board.TestWall.1')

/** Cases grouped by AC, in AC order; cases without one go last under 其他. */
export function groupByAc(cases: TestCase[]): AcGroup[] {
  const groups = new Map<string, TestCase[]>()
  for (const c of cases) {
    const k = c.ac ?? OTHER
    const list = groups.get(k)
    if (list) list.push(c)
    else groups.set(k, [c])
  }
  return [...groups.entries()]
    .sort(([a], [b]) => acNumber(a === OTHER ? null : a) - acNumber(b === OTHER ? null : b) || a.localeCompare(b))
    .map(([ac, list]) => ({ ac, cases: list.slice().sort((x, y) => x.name.localeCompare(y.name)) }))
}

/** The heading shown on the first group of each kind (功能 / 安全 / 合规 / 上架), when the wall has more than one kind. */
export function groupLabel(g: AcGroup, prev: AcGroup | undefined, multi: boolean): string | null {
  const k = caseGroup(g.ac === OTHER ? null : g.ac)
  if (!multi || k >= CASE_GROUPS.length) return null  // a wall of only AC cases looks as before
  if (prev && caseGroup(prev.ac === OTHER ? null : prev.ac) === k) return null
  return CASE_GROUPS[k].label
}

export function TestWall({ tests, roles, focus, onRole, flips, onFinding }: TestWallProps) {
  const [inspect, setInspect] = useState<string | null>(null)
  const byRole = new Map(roles.map((l) => [l.key, l]))
  const groups = groupByAc(tests.cases)
  const multi = new Set(groups.map((x) => caseGroup(x.ac === OTHER ? null : x.ac))).size > 1
  const current = tests.cases.find((c) => c.id === inspect) ?? null
  const failing = tests.cases.filter((c) => c.status === 'fail')
  const byOwner = new Map<string, number>()
  for (const c of failing) byOwner.set(c.owner ?? '', (byOwner.get(c.owner ?? '') ?? 0) + 1)
  const green = tests.total > 0 && tests.failed === 0
  const checked = tests.cases.some((c) => c.verdict)
  return (
    <section className={`kt-card kt-wall${green ? ' is-green' : ''}`} data-testid="kt-wall" aria-label={checked ? tr('board.TestWall.2') : tr('board.TestWall.3')}>
      <header className="kt-card-head">
        <h2>{checked ? tr('board.TestWall.2') : tr('board.TestWall.3')}</h2>
        <span className={`kt-wall-score${green ? ' tone-ok' : tests.failed ? ' tone-bad' : ''}`}>
          {tests.passed}/{tests.total}
        </span>
        {checked ? (
          <span className="kt-wall-src" title={tr('board.TestWall.4', { p0: tests.command })}>{tr('board.TestWall.5')}</span>
        ) : (
          <span className="kt-wall-src" title={tr('board.TestWall.6', { p0: tests.command })}>
            {tr('board.TestWall.7')} {tests.cases.filter((c) => c.file.startsWith('tests/enterprise/')).length} {tr('board.TestWall.8')} {tests.cases.filter((c) => !c.file.startsWith('tests/enterprise/')).length}
          </span>
        )}
        <TestedAt at={tests.at} />
      </header>
      {tests.history.length > 0 && (
        <div className="kt-spark-row">
          <span title={tr('board.TestWall.9')}>{tr('board.TestWall.10')}</span>
          <Sparkline history={tests.history} total={tests.total} />
        </div>
      )}
      {tests.held && (
        <div className="kt-bench-held" role="status" data-testid="kt-wall-held">
          <b>{tr('board.TestWall.11')}</b>{tests.held.why}
          {onFinding && (
            <span><button type="button" className="kt-btn" onClick={onFinding}>{tr('board.TestWall.12')}</button></span>
          )}
        </div>
      )}
      {checked ? (
        <ol className="kt-checks" data-testid="kt-checks">
          {tests.cases.map((c) => {
            const owner = c.owner ? byRole.get(c.owner) : undefined
            return (
              <li key={`${c.id}-${flips[c.id] ?? 0}`} className={`kt-check is-${c.status}${flips[c.id] ? ' is-flip' : ''}${focus ? (c.owner === focus ? ' is-hot' : ' is-dim') : ''}`}
                data-testid="kt-check" data-case={c.id} data-status={c.status}>
                <span className={`kt-check-verdict is-${c.status}`}>{c.verdict}</span>
                <b className="kt-mono">{c.ac ?? c.name}</b>
                {c.tier && c.tier !== 'n/a' && <span className="kt-dim">{tr('board.TestWall.13')}{c.tier}</span>}
                {owner ? (
                  <button type="button" className="kt-check-owner" onClick={() => onRole(owner.key)}>
                    <RoleIcon role={owner.icon || owner.key} size={13} /> {tr('board.TestWall.14')}{owner.title}
                  </button>
                ) : c.status !== 'pass' ? <span className="kt-warn">{tr('board.TestWall.15')}</span> : null}
                {c.ms !== null && <span className="kt-dim">{Math.round(c.ms / 1000)} {tr('board.TestWall.16')}</span>}
                {c.message && <p className="kt-check-why kt-mono">{c.message}</p>}
              </li>
            )
          })}
        </ol>
      ) : tests.cases.length === 0 ? (
        <p className="kt-dim kt-wall-empty">{tests.at ? tr('board.TestWall.17') : tr('board.TestWall.18')}</p>
      ) : (
        <div className="kt-wall-grid">
          {groups.map((g, gi) => (
            <div key={g.ac} className={`kt-ac${g.cases.length > 1 ? ' is-multi' : ''}`} role="group" aria-label={g.ac}>
              {groupLabel(g, groups[gi - 1], multi) && <div className="kt-group-label">{groupLabel(g, groups[gi - 1], multi)}</div>}
              {g.cases.length > 1 && <div className="kt-ac-label">{g.ac}</div>}
              <div className="kt-ac-cells">
                {g.cases.map((c, i) => {
                  const owner = c.owner ? byRole.get(c.owner) : undefined
                  const flip = flips[c.id] ?? 0
                  const meta = caseMeta(c.status)
                  const label = tr('board.TestWall.19', { p0: c.name, p1: meta.label, p2: c.message ? tr('board.TestWall.message', { p0: c.message }) : '', p3: owner ? tr('board.TestWall.ownedBy', { p0: owner.title }) : '' })
                  return (
                    <button
                      key={c.id}
                      type="button"
                      className={`kt-cell is-${c.status}${focus ? (c.owner === focus ? ' is-hot' : ' is-dim') : ''}`}
                      data-testid="kt-cell"
                      data-case={c.id}
                      data-status={c.status}
                      aria-label={label}
                      onMouseEnter={() => setInspect(c.id)}
                      onMouseLeave={() => setInspect((x) => (x === c.id ? null : x))}
                      onFocus={() => setInspect(c.id)}
                      onBlur={() => setInspect((x) => (x === c.id ? null : x))}
                      onClick={() => c.owner && onRole(c.owner)}
                    >
                      <span key={flip} className={`kt-cell-face${flip ? ' is-flip' : ''}`}>
                        <span className="kt-cell-ac">{g.cases.length > 1 ? `${g.ac.replace(/^[A-Z]+-/, '')}·${i + 1}` : (c.ac ?? c.name).replace(/^([A-Z]+)-/, '$1 ')}</span>
                        <span className="kt-cell-glyph" aria-hidden="true">
                          {meta.glyph}
                        </span>
                        {owner && (
                          <span className="kt-cell-owner" aria-hidden="true">
                            <RoleIcon role={owner.icon || owner.key} size={12} />
                          </span>
                        )}
                      </span>
                    </button>
                  )
                })}
              </div>
            </div>
          ))}
        </div>
      )}
      {tests.cases.length > 0 && !checked && (
      <div className={`kt-wall-inspect${current ? ` is-${current.status}` : ''}`} data-testid="kt-inspect">
        {current ? (
          <>
            <strong>
              {caseMeta(current.status).glyph} {current.name}
            </strong>
            <span className="kt-mono kt-dim">{current.file}</span>
            {current.owner && byRole.get(current.owner) && (
              <span>
                <RoleIcon role={byRole.get(current.owner)?.icon || current.owner} size={13} /> {tr('board.TestWall.14')}{byRole.get(current.owner)!.title}
              </span>
            )}
            {current.verdict && <span className="kt-dim">{current.verdict}{current.tier && current.tier !== 'n/a' ? tr('board.TestWall.20', { p0: current.tier }) : ''}</span>}
            {current.ms !== null && <span className="kt-dim">{current.ms} ms</span>}
            {current.message && <span className="kt-fail-msg kt-mono">{current.message}</span>}
          </>
        ) : failing.length ? (
          <span>
            <strong className="tone-bad">{failing.length} {tr('board.TestWall.21')}</strong>
            {[...byOwner.entries()].map(([k, n]) => {
              const l = byRole.get(k)
              return (
                <span key={k || 'none'} className="kt-inspect-owner">
                  {l ? <><RoleIcon role={l.icon || l.key} size={13} /> {l.title}</> : tr('board.TestWall.22')} {n}
                </span>
              )
            })}
            <span className="kt-dim"> {tr('board.TestWall.23')}</span>
          </span>
        ) : (
          <strong className="tone-ok">{tr('board.TestWall.24')}</strong>
        )}
      </div>
      )}
    </section>
  )
}

function TestedAt({ at }: { at: number | null }) {
  const now = useServerNow()
  return <span className="kt-dim kt-wall-at">{at ? tr('board.TestWall.25', { p0: fmtAgo(now - at) }) : tr('board.TestWall.26')}</span>
}

export function Sparkline({ history, total }: { history: Wall['history']; total: number }) {
  if (!history.length) return null
  const W = 300
  const H = 40
  const t0 = history[0].at
  const t1 = history[history.length - 1].at
  const max = Math.max(1, total, ...history.map((h) => h.passed + h.failed))
  const x = (at: number) => (t1 > t0 ? 5 + ((at - t0) / (t1 - t0)) * (W - 10) : W / 2)
  const y = (v: number) => H - 5 - (v / max) * (H - 10)
  // a step line: the count holds until the next test run
  let d = `M${x(history[0].at).toFixed(1)},${y(history[0].passed).toFixed(1)}`
  for (let i = 1; i < history.length; i++) d += ` H${x(history[i].at).toFixed(1)} V${y(history[i].passed).toFixed(1)}`
  const last = history[history.length - 1]
  const area = `${d} V${H - 5} H${x(history[0].at).toFixed(1)} Z`
  return (
    <svg className="kt-spark" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={tr('board.TestWall.27', { p0: history.map((h) => h.passed).join(' → ') })}>
      <line className="kt-spark-total" x1={0} x2={W} y1={y(max)} y2={y(max)} />
      <path className="kt-spark-area" d={area} />
      <path className="kt-spark-line" d={d} />
      {history.map((h, i) => (
        <circle key={i} className={h.failed ? 'kt-spark-pt is-fail' : 'kt-spark-pt is-pass'} cx={x(h.at)} cy={y(h.passed)} r={i === history.length - 1 ? 3.4 : 2.2}>
          <title>{`${h.passed}/${h.passed + h.failed}`}</title>
        </circle>
      ))}
      <text className="kt-spark-label" x={Math.min(W - 2, x(last.at))} y={Math.max(9, y(last.passed) - 6)} textAnchor="end">
        {last.passed}
      </text>
    </svg>
  )
}
