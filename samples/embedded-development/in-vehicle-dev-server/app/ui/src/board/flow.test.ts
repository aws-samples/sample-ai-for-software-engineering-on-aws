import { describe, expect, test } from 'vitest'
import team from '../../../team/team-vstatd.json'
import { vstatdBoard } from '../test/fixtures'
import type { Lane, RunDetail } from '../types'
import { FLOW, flowOf, type FlowKey, type StepState } from './flow'

const at = (stage: 'triage' | 'bench' | 'release' = 'triage'): RunDetail => vstatdBoard(stage).run!
const lane = (r: RunDetail, k: string): Lane => r.roles.find((l) => l.key === k)!
const set = (r: RunDetail, k: string, over: Partial<Lane>) => Object.assign(lane(r, k), over)
const states = (r: RunDetail): Record<FlowKey, StepState> => Object.fromEntries(flowOf(r).steps.map((s) => [s.def.key, s.state])) as Record<FlowKey, StepState>
/** A run after both gates, with every later role still waiting. */
function started(): RunDetail {
  const r = at('bench')
  for (const k of ['tester', 'dev-fix', 'dev-refactor', 'reviewer']) set(r, k, { status: 'waiting', kinds: [], tests_first: null })
  Object.assign(r.tests, { at: null, cases: [], passed: 0, failed: 0, total: 0, history: [], round: 0 })
  Object.assign(r.bench!, { step: null, running: null })
  r.bench!.state.pending = []
  return r
}

describe('the flow matches the team file', () => {
  test('every role is in exactly one agent step, each gate follows its role, and the checks are the team file\'s', () => {
    const agentRoles = FLOW.filter((s) => s.n && s.who.includes('agent')).flatMap((s) => s.roles ?? [])
    expect(agentRoles).toEqual(team.roles.map((r) => r.key))
    const gated = team.roles.filter((r) => r.gate === 'human')
    const gates = FLOW.filter((s) => !s.n)
    expect(gates.map((s) => s.roles)).toEqual(gated.map((r) => [r.key]))
    expect(gates.map((s) => s.title)).toEqual(gated.map((r) => `关卡：${r.gate_label}`))
    for (const g of gates) expect(FLOW[FLOW.indexOf(g) - 1].roles).toEqual(g.roles)
    const checks = (when: string) => team.checks.filter((c) => c.when === when).map((c) => c.name).sort()
    const step = (k: FlowKey) => [...(FLOW.find((s) => s.key === k)!.checks ?? [])].sort()
    expect(step('before')).toEqual(checks('before_bench'))
    expect(step('after')).toEqual(checks('after_bench'))
    expect(step('rerun')).toEqual(checks('release'))
    expect(FLOW.filter((s) => s.n).map((s) => s.n)).toEqual(['1', '2', '3', '4', '5', '6', '7', '8', '9', '10'])
  })
})

describe('where a run is, and who acts next', () => {
  test('1 分诊 at work, then its gate waits for the person (and answers a 讨论)', () => {
    const r = at('triage')
    set(r, 'triage', { status: 'running', gate: null })
    expect(flowOf(r)).toMatchObject({ current: 'triage', now: '分诊在给每个发现定修、说明或延后' })
    expect(states(r)).toMatchObject({ triage: 'current', 'gate-triage': 'todo', signoff: 'todo' })
    set(r, 'triage', { status: 'merged', gate: 'pending' })
    expect(flowOf(r)).toMatchObject({ current: 'gate-triage', now: '等你在分诊关卡逐题决定' })
    expect(states(r)).toMatchObject({ triage: 'done', 'gate-triage': 'current' })
    set(r, 'triage', { gate: 'discussing' })
    expect(flowOf(r).now).toBe('分诊在回答你在关卡上的讨论')
  })

  test('2 架构, then the 开工 gate', () => {
    const r = at('triage')
    set(r, 'triage', { gate: 'approved' })
    set(r, 'architect', { status: 'running' })
    expect(flowOf(r)).toMatchObject({ current: 'architect', now: '架构师在写重构方案和分工' })
    expect(states(r)).toMatchObject({ triage: 'done', 'gate-triage': 'done', architect: 'current' })
    set(r, 'architect', { status: 'merged', gate: 'pending' })
    expect(flowOf(r)).toMatchObject({ current: 'gate-start', now: '等你在开工关卡批准重构方案和分工' })
  })

  test('3 测试先行: the tester writes, the app runs them on the base, a test that passed there sends it back', () => {
    const r = started()
    set(r, 'tester', { status: 'running', kinds: ['work'] })
    expect(flowOf(r)).toMatchObject({ current: 'tests-first', now: '测试在写先失败的测试' })
    set(r, 'tester', { status: 'merged', tests_first: 'pending' })
    expect(flowOf(r)).toMatchObject({ current: 'tests-first', now: 'app 在基线提交上跑新测试：每个都必须失败' })
    set(r, 'tester', { status: 'running', kinds: ['work', 'revise'], tests_first: 'sent_back' })
    expect(flowOf(r).now).toBe('测试先行没过：有测试在基线提交上通过了，测试在重写')
    expect(states(r)['tests-first']).toBe('current')
  })

  test('4 开发 ×2, and a failing check sends it back', () => {
    const r = started()
    set(r, 'tester', { status: 'merged', tests_first: 'passed' })
    set(r, 'dev-fix', { status: 'running', kinds: ['work'] })
    set(r, 'dev-refactor', { status: 'running', kinds: ['work'] })
    expect(flowOf(r)).toMatchObject({ current: 'dev', now: '开发 · 修复、开发 · 重构在干活' })
    expect(states(r)).toMatchObject({ 'tests-first': 'done', dev: 'current', before: 'todo' })
    set(r, 'dev-refactor', { status: 'merged' })
    set(r, 'dev-fix', { status: 'fixing', kinds: ['work', 'fix'] })
    Object.assign(r.tests, { at: r.started_at + 60, total: 5, passed: 4, failed: 1, round: 2 })
    expect(flowOf(r)).toMatchObject({ current: 'dev', now: '检查没过，退回开发 · 修复修（第 2 轮检查）' })
    expect(states(r)).toMatchObject({ dev: 'current', before: 'failed' })
  })

  test('5 上台架前检查: running, then held for a person', () => {
    const r = started()
    set(r, 'tester', { status: 'merged', tests_first: 'passed' })
    set(r, 'dev-fix', { status: 'merged' })
    set(r, 'dev-refactor', { status: 'merged' })
    Object.assign(r.tests, { running: true, round: 2 })
    expect(flowOf(r)).toMatchObject({ current: 'before', now: '检查运行中（第 2 轮）' })
    Object.assign(r.tests, { running: false, at: r.started_at + 60, total: 5, passed: 4, failed: 1, held: { checks: ['build'], why: 'build 修了 3 轮仍不过：src/main.cpp:12:10' } })
    expect(flowOf(r)).toMatchObject({ current: 'before', now: '交给人决定：build 修了 3 轮仍不过：src/main.cpp:12:10' })
    expect(states(r).before).toBe('held')
  })

  test('6 评审, and its 要改 sends the work back', () => {
    const r = started()
    for (const k of ['tester', 'dev-fix', 'dev-refactor']) set(r, k, { status: 'merged', tests_first: k === 'tester' ? 'passed' : null })
    Object.assign(r.tests, { at: r.started_at + 60, total: 5, passed: 5, failed: 0 })
    set(r, 'reviewer', { status: 'running', kinds: ['work'] })
    expect(flowOf(r)).toMatchObject({ current: 'review', now: '评审在只读审查' })
    expect(states(r)).toMatchObject({ before: 'done', review: 'current' })
    set(r, 'reviewer', { status: 'waiting' })
    set(r, 'dev-refactor', { status: 'running', kinds: ['work', 'review'] })
    expect(flowOf(r)).toMatchObject({ current: 'dev', now: '评审要改，退回开发 · 重构' })
    expect(states(r).review).toBe('failed')
  })

  test('7 台架: the deploy waits at the operator console, with the command and the digest', () => {
    const r = at('bench')
    const req = r.bench!.state.pending[0]
    expect(flowOf(r)).toMatchObject({ current: 'bench', now: `等你在操作台批准部署：${r.bench!.console} approve ${req.id} --digest bc9372` })
    expect(states(r)).toMatchObject({ review: 'done', bench: 'current', after: 'todo' })
    r.bench!.console = null
    expect(flowOf(r).now).toBe(`等你在操作台批准部署（请求 ${req.id}，摘要 bc9372）`)
    r.bench!.state.pending = []
    expect(flowOf(r).now).toBe('app 在请求部署：操作台上会出现请求')
    Object.assign(r.bench!, { step: 'doctor' })
    expect(flowOf(r).now).toBe('app 在跑 bench/doctor.sh')
    Object.assign(r.bench!, { step: 'deploy', held: { step: 'deploy', why: '部署没做成（refused）：not this build', commands: [], at: 0 } })
    expect(flowOf(r)).toMatchObject({ current: 'bench', now: '交给人决定：部署没做成（refused）：not this build' })
    expect(states(r).bench).toBe('held')
  })

  test('8 台架后检查, its failure back to the developer, and 9 the independent rerun', () => {
    const r = at('bench')
    r.bench!.state.pending = []
    Object.assign(r.bench!, { step: 'after', running: 'after' })
    expect(flowOf(r)).toMatchObject({ current: 'after', now: '台架后检查运行中（logdiff、runtime-limits）' })
    expect(states(r)).toMatchObject({ bench: 'done', after: 'current' })
    Object.assign(r.bench!, { running: null })
    set(r, 'dev-fix', { status: 'fixing', kinds: ['work', 'fix', 'fix'] })
    set(r, 'reviewer', { status: 'waiting' })
    expect(flowOf(r).current).toBe('dev')
    expect(states(r)).toMatchObject({ dev: 'current', before: 'todo', after: 'failed' })
    set(r, 'dev-fix', { status: 'merged' })
    set(r, 'reviewer', { status: 'done' })
    Object.assign(r.bench!, { step: 'rerun', running: 'rerun' })
    expect(flowOf(r)).toMatchObject({ current: 'rerun', now: '独立重跑全部检查和 release.sh' })
  })

  test('10 签字: signable once release.sh passed; signed, every step is done', () => {
    const r = at('release')
    expect(flowOf(r)).toMatchObject({ current: 'signoff', now: '可以签字：在签字单上看证据页，签字放行' })
    expect(states(r)).toMatchObject({ rerun: 'done', signoff: 'current' })
    r.signoff = { by: '王工', note: '', at: r.ended_at!, tests: '5/5' }
    expect(flowOf(r)).toMatchObject({ current: null, now: '王工已签字放行' })
    expect(Object.values(states(r)).every((s) => s === 'done')).toBe(true)
  })

  test('a run that stopped, or a role that failed, marks where it ended', () => {
    const r = started()
    set(r, 'tester', { status: 'failed' })
    r.status = 'failed'
    expect(flowOf(r)).toMatchObject({ current: 'tests-first', now: '测试失败了：看它的泳道，处理好以后点重试' })
    expect(states(r)['tests-first']).toBe('failed')
    set(r, 'tester', { status: 'running' })
    r.status = 'stopped'
    expect(flowOf(r)).toMatchObject({ current: 'tests-first', now: '运行已停止' })
    expect(states(r)['tests-first']).toBe('failed')
  })

  test('a tool call waiting for approval in Kiro Crew is what comes next', () => {
    const r = started()
    set(r, 'tester', { status: 'awaiting_approval' })
    expect(flowOf(r).now).toBe('测试的一个工具调用在等你在 Kiro Crew 里批准')
  })
})
