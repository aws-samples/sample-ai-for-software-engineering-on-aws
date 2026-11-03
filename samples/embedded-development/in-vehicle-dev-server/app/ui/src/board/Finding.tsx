/**
 * 补登发现并交给角色 (TR §4.4): a run held for a person after the checks (交给人决定) carries on once the person registers
 * what a check found and the backlog does not have, and hands it to a role. The dialog is filled in from the held check:
 * the tool, file:line from its first reason, that file as the path the role may now write, and the ID it will get
 * (the next free one after the backlog and the triage). `POST /runs/{rid}/finding` checks the triage by the checks'
 * rules and answers what is wrong; 「接着运行」 off records it only, so a second can be registered first.
 */
import { useState } from 'react'
import type { RunDetail, TestCase } from '../types'
import { errorText } from './useBoard'

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
  const first = (message ?? '').split('；')[0]
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

/** The dialog's starting values for one held check (null: the run is not held after the checks). */
export function findingPreset(run: RunDetail, check?: string): FindingBody | null {
  const held = run.tests.held
  if (!held || !held.checks.length) return null
  const name = check && held.checks.includes(check) ? check : held.checks.find((c) => run.tests.cases.find((x) => x.id === c)?.status === 'fail') ?? held.checks[0]
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

/** The roles that write code: the ones a finding can be handed to. */
function implementers(run: RunDetail) {
  return run.roles.filter((l) => l.writable.length > 0 && l.status !== 'skipped' && !l.writable.every((g) => g.startsWith('docs/') || g.startsWith('tests/')))
}

const list = (s: string) => s.split(/[\s,，、]+/).map((x) => x.trim()).filter(Boolean)
/** Citations hold spaces (`[VSTATD-IF p.11 §8.4]`): one per bracket. */
const citesOf = (s: string) => s.match(/\[[^\]]+\]/g) ?? []

export function FindingDialog({ run, onConfirm, onCancel }: { run: RunDetail; onConfirm: (body: FindingBody) => Promise<void>; onCancel: () => void }) {
  const [f, setF] = useState<FindingBody>(() => findingPreset(run)!)
  const [extra, setExtra] = useState('')
  const [facts, setFacts] = useState('')
  const [cites, setCites] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const set = (x: Partial<FindingBody>) => setF((o) => ({ ...o, ...x }))
  const held = run.tests.held!
  const roles = implementers(run)
  const confirm = async () => {
    if (!f.by.trim()) return setErr('写下你的名字（谁补登的）')
    if (!f.location.trim() || !f.tool.trim()) return setErr('写明发现它的工具和位置')
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
      <strong id="kt-finding-title">补登发现 {nextFindingId(run)} 并交给角色</strong>
      <span>按 TR §4.4 把检查发现、待办里没有的问题记进批准的分诊（{held.why}）。交给的角色从此可以改下面的路径，提交说明要写这个编号。</span>
      <div className="kt-start-row">
        <label className="kt-start-field is-narrow"><span>检查</span>
          <select aria-label="检查" value={f.check} onChange={(e) => setF({ ...findingPreset(run, e.target.value)!, by: f.by, note: f.note, continue: f.continue })}>
            {held.checks.map((c) => <option key={c}>{c}</option>)}
          </select>
        </label>
        <label className="kt-start-field is-narrow"><span>工具</span><input aria-label="工具" value={f.tool} maxLength={80} onChange={(e) => set({ tool: e.target.value })} /></label>
        <label className="kt-start-field"><span>位置</span><input aria-label="位置" value={f.location} maxLength={200} onChange={(e) => set({ location: e.target.value })} placeholder="文件:行" /></label>
      </div>
      <div className="kt-start-row">
        <label className="kt-start-field is-narrow"><span>决定</span>
          <select aria-label="决定" value={f.decision} onChange={(e) => set({ decision: e.target.value as FindingBody['decision'] })}>
            <option value="fix">修复（fix）</option><option value="justify">说明（justify）</option><option value="defer">延后（defer）</option>
          </select>
        </label>
        {f.decision === 'fix' && (
          <label className="kt-start-field is-narrow"><span>证据</span>
            <select aria-label="证据" value={f.evidence ?? 'build'} onChange={(e) => set({ evidence: e.target.value as FindingBody['evidence'] })}>
              <option value="unit-test">unit-test</option><option value="static-analysis">static-analysis</option><option value="build">build</option>
            </select>
          </label>
        )}
        {f.decision === 'fix' && (
          <label className="kt-start-field is-narrow"><span>涉及行为</span>
            <select aria-label="涉及行为" value={f.behaviour ? 'true' : 'false'} onChange={(e) => set({ behaviour: e.target.value === 'true' })}>
              <option value="false">否</option><option value="true">是（要写事实条目）</option>
            </select>
          </label>
        )}
        <label className="kt-start-field is-narrow"><span>交给</span>
          <select aria-label="交给" value={f.role} onChange={(e) => set({ role: e.target.value })}>
            {roles.map((l) => <option key={l.key} value={l.key}>{l.title}</option>)}
          </select>
        </label>
      </div>
      <div className="kt-start-row">
        <label className="kt-start-field"><span>引用（cites）</span><input aria-label="引用" value={cites} onChange={(e) => setCites(e.target.value)} placeholder="[VSTATD-IF p.11 §8.4]、[CC1-PN §7.2]" /></label>
        <label className="kt-start-field is-narrow"><span>事实条目（facts）</span><input aria-label="事实条目" value={facts} onChange={(e) => setFacts(e.target.value)} placeholder="RES-THREADS" /></label>
      </div>
      {f.decision === 'defer' && (
        <div className="kt-start-row">
          <label className="kt-start-field"><span>为什么延后</span><input aria-label="为什么延后" value={f.reason} onChange={(e) => set({ reason: e.target.value })} /></label>
          <label className="kt-start-field"><span>什么时候再处理</span><input aria-label="什么时候再处理" value={f.pick_up_when} onChange={(e) => set({ pick_up_when: e.target.value })} /></label>
        </div>
      )}
      <div className="kt-start-row">
        <label className="kt-start-field"><span>可写路径</span><input aria-label="可写路径" value={f.paths.join(' ')} onChange={(e) => set({ paths: list(e.target.value) })} /></label>
        <label className="kt-start-field"><span>再加路径</span><input aria-label="再加路径" value={extra} onChange={(e) => setExtra(e.target.value)} placeholder="例如 tests/test_signal_table.cpp" /></label>
        <label className="kt-start-field is-narrow"><span>补登人</span><input aria-label="补登人" value={f.by} maxLength={60} onChange={(e) => set({ by: e.target.value })} /></label>
      </div>
      <textarea className="kt-gate-note" rows={2} value={f.note} onChange={(e) => set({ note: e.target.value })} aria-label="备注" placeholder="例如：工具链文件要设 CMAKE_SYSROOT（CC1-PN §7.2）" />
      <span className="kt-confirm-actions">
        <label><input type="checkbox" checked={f.continue} onChange={(e) => set({ continue: e.target.checked })} /> 接着运行</label>
        <button type="button" className="kt-btn is-solid is-primary" onClick={confirm} disabled={busy}>{busy ? '正在提交…' : f.continue ? '补登并接着运行' : '补登'}</button>
        <button type="button" className="kt-btn" onClick={onCancel}>取消</button>
      </span>
      {err && <p className="kt-error" role="alert">{err}</p>}
    </div>
  )
}
