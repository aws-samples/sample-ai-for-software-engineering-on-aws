/**
 * 补登发现并交给角色 (TR §4.4): a run held for a person after the checks (交给人决定) carries on once the person registers
 * what a check found and the backlog does not have, and hands it to a role. The dialog is filled in from the held check:
 * the tool, file:line from its first reason, that file as the path the role may now write, and the ID it will get
 * (the next free one after the backlog and the triage). `POST /runs/{rid}/finding` checks the triage by the checks'
 * rules and answers what is wrong; 「接着运行」 off records it only, so a second can be registered first.
 */
import { useState } from 'react'
import type { RunDetail, TestCase, TriageRow } from '../types'
import { errorText } from './useBoard'
import { t as tr } from '../i18n'

const SIGNER_KEY = 'vstatd-team:signer' // the sign-off's: the same person signs and registers

export type FindingBody = {
  check: string; tool: string; location: string; decision: 'fix' | 'justify' | 'defer'
  evidence: 'unit-test' | 'static-analysis' | 'build' | null; behaviour: boolean; facts: string[]; cites: string[]
  reason: string; pick_up_when: string; role: string; paths: string[]; note: string; by: string; continue: boolean
}

/** The next free finding ID: after every ID of the backlog and of the triage. */
export function nextFindingId(run: RunDetail): string {
  const ids = [...(run.backlog?.rows ?? []).map((r) => r.id), ...(run.backlog?.triage?.findings ?? []).map((f) => f.id)]
  const n = Math.max(0, ...ids.map((i) => (/^F-(\d{3})$/.exec(i) ? Number(i.slice(2)) : 0)))
  return `F-${String(n + 1).padStart(3, '0')}`
}

/** file:line of a check's first reason, without the results/…/work/<check>/tree/ prefix of the checks' own copy. */
export function locationOf(message: string | null): string {
  const first = (message ?? '').split('；')[0] // i18n-keep: the checks join their reasons with ；
  const m = /([\w./-]+\.[A-Za-z0-9]+):(\d+)/.exec(first)
  return m ? `${m[1].replace(/^.*\/work\/[^/]+\/tree\//, '')}:${m[2]}` : ''
}

export function toolOf(check: string, message: string | null): string {
  const text = message ?? ''
  if (check === 'build') return 'gcc'
  if (check === 'unit') return /ThreadSanitizer|AddressSanitizer|UndefinedBehavior/.exec(text)?.[0] ?? 'gtest'
  if (check === 'static') return /clang/.test(text) ? 'clang-tidy' : 'cppcheck'
  return check
}

const EVIDENCE: Record<string, FindingBody['evidence']> = { build: 'build', unit: 'unit-test', static: 'static-analysis' }

/** The IDs already added under TR §4.4 for *check* at *location*: registering it again hands the same failure back. */
export function registeredAs(run: RunDetail, check: string, location: string): string[] {
  return (run.backlog?.triage?.findings ?? [])
    .filter((f) => f.added && f.found_by === `checks/${check}.sh` && !!location && f.location === location).map((f) => f.id)
}

/** The dialog's starting values for one held check (null: the run is not held after the checks). Without *check*: the
 * first failing held check not registered yet at its location, else the first failing one. */
export function findingPreset(run: RunDetail, check?: string): FindingBody | null {
  const held = run.tests.held
  if (!held || !held.checks.length) return null
  const at = (c: string) => locationOf(run.tests.cases.find((x) => x.id === c)?.message ?? null)
  const failing = held.checks.filter((c) => run.tests.cases.find((x) => x.id === c)?.status === 'fail')
  const name = check && held.checks.includes(check) ? check
    : failing.find((c) => !registeredAs(run, c, at(c)).length) ?? failing[0] ?? held.checks[0]
  const c: TestCase | undefined = run.tests.cases.find((x) => x.id === name)
  const location = locationOf(c?.message ?? null)
  const file = location.replace(/:\d+$/, '') || c?.file || ''
  const roles = implementers(run)
  return {
    check: name, tool: toolOf(name, c?.message ?? null), location, decision: 'fix', evidence: EVIDENCE[name] ?? 'build',
    behaviour: false, facts: [], cites: [], reason: '', pick_up_when: '', role: c?.owner && roles.some((l) => l.key === c.owner) ? c.owner : roles[0]?.key ?? '',
    paths: file ? [file] : [], note: '', by: (typeof localStorage !== 'undefined' && localStorage.getItem(SIGNER_KEY)) || '', continue: true,
  }
}

/** 给已补登的发现加路径: no new ID, the role gets the files where the cause is and one more round of that check. */
export type ExtendBody = { extend: string; role: string; paths: string[]; note: string; by: string; continue: boolean }

const CHECK_OF = /^checks\/([\w-]+)\.sh$/
/** The findings a check added already: the ones that can get more paths. */
export function extendable(run: RunDetail): TriageRow[] {
  return (run.backlog?.triage?.findings ?? []).filter((f) => f.added && CHECK_OF.test(f.found_by ?? ''))
}

/** Adding paths comes first when every held check whose reason names a file:line has it registered already: one more
 * new finding there hands the role the same failure and the same files. */
export function startsExtending(run: RunDetail): boolean {
  const held = run.tests.held
  if (!held || !extendable(run).length) return false
  return held.checks.every((c) => {
    const at = locationOf(run.tests.cases.find((x) => x.id === c)?.message ?? null)
    return !at || registeredAs(run, c, at).length > 0
  })
}

/** The roles that write code: the ones a finding can be handed to. */
function implementers(run: RunDetail) {
  return run.roles.filter((l) => l.writable.length > 0 && l.status !== 'skipped' && !l.writable.every((g) => g.startsWith('docs/') || g.startsWith('tests/')))
}

const list = (s: string) => s.split(/[\s,，、]+/).map((x) => x.trim()).filter(Boolean) // i18n-keep: what a person types, in either language
/** Citations hold spaces (`[VSTATD-IF p.11 §8.4]`): one per bracket. */
const citesOf = (s: string) => s.match(/\[[^\]]+\]/g) ?? []

export type Confirm = (body: FindingBody | ExtendBody) => Promise<void>

/** The app's proposal on a held run (GET /board tests.held.suggest): which files to give to which finding's role. The
 * person agrees with one click; each is sent as 给已补登的发现加路径, the last one with 接着运行. */
export function SuggestAgree({ run, onConfirm }: { run: RunDetail; onConfirm: Confirm }) {
  const items = run.tests.held?.suggest ?? []
  const [by, setBy] = useState(() => (typeof localStorage !== 'undefined' && localStorage.getItem(SIGNER_KEY)) || '')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  if (!items.length) return null
  const title = (k: string) => run.roles.find((l) => l.key === k)?.title ?? k
  const agree = async () => {
    if (!by.trim()) return setErr(tr('board.Finding.1'))
    setBusy(true)
    setErr('')
    localStorage.setItem(SIGNER_KEY, by.trim())
    try {
      for (const [i, s] of items.entries()) {
        await onConfirm({ extend: s.extend, role: s.role, paths: s.paths, note: tr('board.Finding.2', { p0: s.note }), by: by.trim(), continue: i === items.length - 1 })
      }
    } catch (x) {
      setErr(errorText(x))
      setBusy(false)
    }
  }
  return (
    <div className="kt-ready-pending" data-testid="kt-suggest">
      <b>{tr('board.Finding.3')}</b>
      <ul>
        {items.map((s) => (
          <li key={s.extend}>{s.extend}{tr('board.Finding.4')}{s.check}{tr('board.Finding.5')}{title(s.role)}{tr('board.Finding.6')} <code className="kt-mono">{s.paths.join(' ')}</code>{tr('board.Finding.7')}<span className="kt-dim">{s.note}</span></li>
        ))}
      </ul>
      <span className="kt-start-actions">
        <label className="kt-start-field is-narrow"><span>{tr('board.Finding.8')}</span><input aria-label={tr('board.Finding.8')} value={by} maxLength={60} onChange={(e) => setBy(e.target.value)} /></label>
        <button type="button" className="kt-btn is-solid is-primary" onClick={agree} disabled={busy}>{busy ? tr('board.Finding.9') : tr('board.Finding.10')}</button>
      </span>
      {err && <p className="kt-error" role="alert">{err}</p>}
    </div>
  )
}

/** 要做什么: a new finding, or more paths for one added already. */
function ModePick({ extending, onPick }: { extending: boolean; onPick: (extending: boolean) => void }) {
  return (
    <label className="kt-start-field is-narrow"><span>{tr('board.Finding.11')}</span>
      <select aria-label={tr('board.Finding.11')} value={extending ? 'extend' : 'new'} onChange={(e) => onPick(e.target.value === 'extend')}>
        <option value="new">{tr('board.Finding.12')}</option><option value="extend">{tr('board.Finding.13')}</option>
      </select>
    </label>
  )
}

export function FindingDialog({ run, onConfirm, onCancel }: { run: RunDetail; onConfirm: Confirm; onCancel: () => void }) {
  const [extending, setExtending] = useState(() => startsExtending(run))
  return extending
    ? <ExtendForm run={run} onConfirm={onConfirm} onCancel={onCancel} onMode={setExtending} />
    : <NewFinding run={run} onConfirm={onConfirm} onCancel={onCancel} onMode={setExtending} />
}

function ExtendForm({ run, onConfirm, onCancel, onMode }: { run: RunDetail; onConfirm: Confirm; onCancel: () => void; onMode: (x: boolean) => void }) {
  const held = run.tests.held!
  const roles = implementers(run)
  const ids = extendable(run)
  const first = held.checks.map((c) => ids.find((f) => CHECK_OF.exec(f.found_by ?? '')?.[1] === c)).find(Boolean) ?? ids[0]
  const proposed = (id: string) => held.suggest?.find((s) => s.extend === id)
  const [b, setB] = useState<ExtendBody>(() => ({ extend: first?.id ?? '', role: proposed(first?.id ?? '')?.role ?? roles[0]?.key ?? '', paths: [],
    note: proposed(first?.id ?? '')?.note ?? '', by: (typeof localStorage !== 'undefined' && localStorage.getItem(SIGNER_KEY)) || '', continue: true }))
  const [paths, setPaths] = useState(() => proposed(first?.id ?? '')?.paths.join(' ') ?? '')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const set = (x: Partial<ExtendBody>) => setB((o) => ({ ...o, ...x }))
  const pick = ids.find((f) => f.id === b.extend)
  const confirm = async () => {
    if (!b.by.trim()) return setErr(tr('board.Finding.14'))
    if (!list(paths).length) return setErr(tr('board.Finding.15'))
    setBusy(true)
    setErr('')
    try {
      localStorage.setItem(SIGNER_KEY, b.by.trim())
      await onConfirm({ ...b, by: b.by.trim(), paths: list(paths) })
    } catch (x) {
      setErr(errorText(x))
      setBusy(false)
    }
  }
  return (
    <div className="kt-confirm kt-gate-dialog" role="dialog" aria-labelledby="kt-finding-title" data-testid="kt-finding-dialog">
      <strong id="kt-finding-title">{tr('board.Finding.16')}</strong>
      <span>{tr('board.Finding.17')}{held.why}{tr('board.Finding.18')}</span>
      <div className="kt-start-row">
        <ModePick extending onPick={onMode} />
        <label className="kt-start-field"><span>{tr('board.Finding.19')}</span>
          <select aria-label={tr('board.Finding.19')} value={b.extend} onChange={(e) => {
            const s = proposed(e.target.value)
            set({ extend: e.target.value, note: s?.note ?? '', ...(s ? { role: s.role } : {}) })
            setPaths(s?.paths.join(' ') ?? '')
          }}>
            {ids.map((f) => <option key={f.id} value={f.id}>{f.id} · {CHECK_OF.exec(f.found_by ?? '')?.[1]} · {f.location}</option>)}
          </select>
        </label>
        <label className="kt-start-field is-narrow"><span>{tr('board.Finding.20')}</span>
          <select aria-label={tr('board.Finding.20')} value={b.role} onChange={(e) => set({ role: e.target.value })}>
            {roles.map((l) => <option key={l.key} value={l.key}>{l.title}</option>)}
          </select>
        </label>
      </div>
      {pick && <p className="kt-dim">{pick.id} {tr('board.Finding.21')} {pick.found_by} {tr('board.Finding.22')} {pick.location} {tr('board.Finding.23')}{roles.find((l) => l.key === b.role)?.writable.join(' ') || '—'}</p>}
      <div className="kt-start-row">
        <label className="kt-start-field"><span>{tr('board.Finding.24')}</span><input aria-label={tr('board.Finding.24')} value={paths} onChange={(e) => setPaths(e.target.value)} placeholder={tr('board.Finding.25')} /></label>
        <label className="kt-start-field is-narrow"><span>{tr('board.Finding.26')}</span><input aria-label={tr('board.Finding.26')} value={b.by} maxLength={60} onChange={(e) => set({ by: e.target.value })} /></label>
      </div>
      <textarea className="kt-gate-note" rows={2} value={b.note} onChange={(e) => set({ note: e.target.value })} aria-label={tr('board.Finding.27')} placeholder={tr('board.Finding.28')} />
      <span className="kt-confirm-actions">
        <label><input type="checkbox" checked={b.continue} onChange={(e) => set({ continue: e.target.checked })} /> {tr('board.Finding.29')}</label>
        <button type="button" className="kt-btn is-solid is-primary" onClick={confirm} disabled={busy}>{busy ? tr('board.Finding.9') : b.continue ? tr('board.Finding.30') : tr('board.Finding.31')}</button>
        <button type="button" className="kt-btn" onClick={onCancel}>{tr('board.Finding.32')}</button>
      </span>
      {err && <p className="kt-error" role="alert">{err}</p>}
    </div>
  )
}

function NewFinding({ run, onConfirm, onCancel, onMode }: { run: RunDetail; onConfirm: Confirm; onCancel: () => void; onMode: (x: boolean) => void }) {
  const [f, setF] = useState<FindingBody>(() => findingPreset(run)!)
  const [extra, setExtra] = useState('')
  const [facts, setFacts] = useState('')
  const [cites, setCites] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const set = (x: Partial<FindingBody>) => setF((o) => ({ ...o, ...x }))
  const held = run.tests.held!
  const roles = implementers(run)
  const dup = registeredAs(run, f.check, f.location.trim())
  const confirm = async () => {
    if (!f.by.trim()) return setErr(tr('board.Finding.14'))
    if (!f.location.trim() || !f.tool.trim()) return setErr(tr('board.Finding.33'))
    setBusy(true)
    setErr('')
    try {
      localStorage.setItem(SIGNER_KEY, f.by.trim())
      const fix = f.decision === 'fix'
      await onConfirm({ ...f, by: f.by.trim(), evidence: fix ? f.evidence : null, behaviour: fix && f.behaviour, facts: list(facts), cites: citesOf(cites),
        paths: [...new Set([...f.paths, ...list(extra)])] })
    } catch (x) {
      setErr(errorText(x))
      setBusy(false)
    }
  }
  return (
    <div className="kt-confirm kt-gate-dialog" role="dialog" aria-labelledby="kt-finding-title" data-testid="kt-finding-dialog">
      <strong id="kt-finding-title">{tr('board.Finding.34')} {nextFindingId(run)} {tr('board.Finding.35')}</strong>
      <span>{tr('board.Finding.36')}{held.why}{tr('board.Finding.37')}</span>
      <div className="kt-start-row">
        {extendable(run).length > 0 && <ModePick extending={false} onPick={onMode} />}
        <label className="kt-start-field is-narrow"><span>{tr('board.Finding.38')}</span>
          <select aria-label={tr('board.Finding.38')} value={f.check} onChange={(e) => setF({ ...findingPreset(run, e.target.value)!, by: f.by, note: f.note, continue: f.continue })}>
            {held.checks.map((c) => <option key={c}>{c}</option>)}
          </select>
        </label>
        <label className="kt-start-field is-narrow"><span>{tr('board.Finding.39')}</span><input aria-label={tr('board.Finding.39')} value={f.tool} maxLength={80} onChange={(e) => set({ tool: e.target.value })} /></label>
        <label className="kt-start-field"><span>{tr('board.Finding.40')}</span><input aria-label={tr('board.Finding.40')} value={f.location} maxLength={200} onChange={(e) => set({ location: e.target.value })} placeholder={tr('board.Finding.41')} /></label>
      </div>
      {dup.length > 0 && (
        <p className="kt-warn" role="status" data-testid="kt-finding-dup">
          {f.check} {tr('board.Finding.22')} {f.location.trim()} {tr('board.Finding.42')}{dup.join(tr('board.Finding.43'))}{tr('board.Finding.44')}
        </p>
      )}
      <div className="kt-start-row">
        <label className="kt-start-field is-narrow"><span>{tr('board.Finding.45')}</span>
          <select aria-label={tr('board.Finding.45')} value={f.decision} onChange={(e) => set({ decision: e.target.value as FindingBody['decision'] })}>
            <option value="fix">{tr('board.Finding.46')}</option><option value="justify">{tr('board.Finding.47')}</option><option value="defer">{tr('board.Finding.48')}</option>
          </select>
        </label>
        {f.decision === 'fix' && (
          <label className="kt-start-field is-narrow"><span>{tr('board.Finding.49')}</span>
            <select aria-label={tr('board.Finding.49')} value={f.evidence ?? 'build'} onChange={(e) => set({ evidence: e.target.value as FindingBody['evidence'] })}>
              <option value="unit-test">unit-test</option><option value="static-analysis">static-analysis</option><option value="build">build</option>
            </select>
          </label>
        )}
        {f.decision === 'fix' && (
          <label className="kt-start-field is-narrow"><span>{tr('board.Finding.50')}</span>
            <select aria-label={tr('board.Finding.50')} value={f.behaviour ? 'true' : 'false'} onChange={(e) => set({ behaviour: e.target.value === 'true' })}>
              <option value="false">{tr('board.Finding.51')}</option><option value="true">{tr('board.Finding.52')}</option>
            </select>
          </label>
        )}
        <label className="kt-start-field is-narrow"><span>{tr('board.Finding.20')}</span>
          <select aria-label={tr('board.Finding.20')} value={f.role} onChange={(e) => set({ role: e.target.value })}>
            {roles.map((l) => <option key={l.key} value={l.key}>{l.title}</option>)}
          </select>
        </label>
      </div>
      <div className="kt-start-row">
        <label className="kt-start-field"><span>{tr('board.Finding.53')}</span><input aria-label={tr('board.Finding.54')} value={cites} onChange={(e) => setCites(e.target.value)} placeholder={tr('board.Finding.55')} /></label>
        <label className="kt-start-field is-narrow"><span>{tr('board.Finding.56')}</span><input aria-label={tr('board.Finding.57')} value={facts} onChange={(e) => setFacts(e.target.value)} placeholder="RES-THREADS" /></label>
      </div>
      {f.decision === 'defer' && (
        <div className="kt-start-row">
          <label className="kt-start-field"><span>{tr('board.Finding.58')}</span><input aria-label={tr('board.Finding.58')} value={f.reason} onChange={(e) => set({ reason: e.target.value })} /></label>
          <label className="kt-start-field"><span>{tr('board.Finding.59')}</span><input aria-label={tr('board.Finding.59')} value={f.pick_up_when} onChange={(e) => set({ pick_up_when: e.target.value })} /></label>
        </div>
      )}
      <div className="kt-start-row">
        <label className="kt-start-field"><span>{tr('board.Finding.60')}</span><input aria-label={tr('board.Finding.60')} value={f.paths.join(' ')} onChange={(e) => set({ paths: list(e.target.value) })} /></label>
        <label className="kt-start-field"><span>{tr('board.Finding.61')}</span><input aria-label={tr('board.Finding.61')} value={extra} onChange={(e) => setExtra(e.target.value)} placeholder={tr('board.Finding.62')} /></label>
        <label className="kt-start-field is-narrow"><span>{tr('board.Finding.26')}</span><input aria-label={tr('board.Finding.26')} value={f.by} maxLength={60} onChange={(e) => set({ by: e.target.value })} /></label>
      </div>
      <textarea className="kt-gate-note" rows={2} value={f.note} onChange={(e) => set({ note: e.target.value })} aria-label={tr('board.Finding.27')} placeholder={tr('board.Finding.63')} />
      <span className="kt-confirm-actions">
        <label><input type="checkbox" checked={f.continue} onChange={(e) => set({ continue: e.target.checked })} /> {tr('board.Finding.29')}</label>
        <button type="button" className="kt-btn is-solid is-primary" onClick={confirm} disabled={busy}>{busy ? tr('board.Finding.9') : f.continue ? tr('board.Finding.64') : tr('board.Finding.65')}</button>
        <button type="button" className="kt-btn" onClick={onCancel}>{tr('board.Finding.32')}</button>
      </span>
      {err && <p className="kt-error" role="alert">{err}</p>}
    </div>
  )
}
