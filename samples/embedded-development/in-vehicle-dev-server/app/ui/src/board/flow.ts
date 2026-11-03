/**
 * The vstatd team's flow from the backlog to sign-off (team/team-vstatd.json, docs/kiro-crew-app.md D3–D10): the
 * steps, who acts at each (an agent role, a person, the app itself, the bench with its operator console), and, for a
 * run, where it is and who must do what next. Pure: no React. flow.test.ts keeps the role keys and check names in step
 * with the team file.
 */
import type { Lane, RunDetail } from '../types'
import { FINISHED, LIVE } from './format'

export type Who = 'agent' | 'person' | 'app' | 'bench'
export const WHO_LABEL: Record<Who, string> = { agent: 'agent 角色', person: '人', app: 'app 自动', bench: '台架+操作台' }

export type FlowKey = 'triage' | 'gate-triage' | 'architect' | 'gate-start' | 'tests-first' | 'dev' | 'before' | 'review' | 'bench' | 'after' | 'rerun' | 'signoff'

export interface FlowStepDef {
  key: FlowKey
  n: string // its number; '' for a gate between two steps
  title: string
  who: Who[]
  does: string
  roles?: string[] // the team file's roles that act here (a gate: the role whose gate it is)
  checks?: string[] // the team file's checks the app runs here
}

export const FLOW: FlowStepDef[] = [
  { key: 'triage', n: '1', title: '分诊', who: ['agent'], roles: ['triage'], does: '给本批每个发现定修、说明或延后，引用规范的页和节；把重构加成一条' },
  { key: 'gate-triage', n: '', title: '关卡：分诊', who: ['person'], roles: ['triage'], does: '你逐题决定说明、延后和新加的条目，修复照分诊页批准' },
  { key: 'architect', n: '2', title: '架构', who: ['agent'], roles: ['architect'], does: '拆分 Service::run() 的重构方案，按源文件给两个开发分工' },
  { key: 'gate-start', n: '', title: '关卡：开工', who: ['person'], roles: ['architect'], does: '你批准方案和分工，开发才开工' },
  { key: 'tests-first', n: '3', title: '测试先行', who: ['agent', 'app'], roles: ['tester'], does: '测试给要测的修复写测试；app 在基线提交上跑，每个都必须失败' },
  { key: 'dev', n: '4', title: '开发 ×2 并行', who: ['agent'], roles: ['dev-fix', 'dev-refactor'], does: '修复和重构同时做，各改分给自己的文件' },
  { key: 'before', n: '5', title: '上台架前检查', who: ['app'], checks: ['build', 'static', 'unit', 'size', 'trace'], does: '失败按文件退回负责的开发，轮数有上限；BLOCKED 交给人' },
  { key: 'review', n: '6', title: '评审', who: ['agent'], roles: ['reviewer'], does: '只读：最仔细看说明和重构保住的行为，要改就打回' },
  { key: 'bench', n: '7', title: '台架：部署、回放', who: ['bench'], does: '每个动作在 bench/console.py 按构建摘要批准' },
  { key: 'after', n: '8', title: '台架后检查', who: ['app'], checks: ['logdiff', 'runtime-limits'], does: '回放的日志对比基线，目标上的资源限额' },
  { key: 'rerun', n: '9', title: '独立重跑', who: ['app'], checks: ['release'], does: '新目录里从头重跑全部检查，再跑 release.sh，生成证据页' },
  { key: 'signoff', n: '10', title: '签字放行', who: ['person'], does: '发布负责人看证据页签字' },
]

export type StepState = 'todo' | 'current' | 'done' | 'failed' | 'held'

export interface Flow {
  steps: { def: FlowStepDef; state: StepState }[]
  current: FlowKey | null // null: signed off, every step done
  now: string // 现在：who must do what next
}

const BENCH_ACTION: Record<string, string> = { deploy: '部署', replay: '回放' }

/** Where *run* is in the flow, which steps are done, failed or held for a person, and what comes next. */
export function flowOf(run: RunDetail): Flow {
  const lane = (k: string): Lane | undefined => run.roles.find((l) => l.key === k)
  const busy = (l?: Lane) => !!l && (LIVE.has(l.status) || l.status === 'queued')
  const finished = (l?: Lane) => !l || l.status === 'skipped' || (FINISHED.has(l.status) && !busy(l))
  const gateOpen = (l?: Lane) => l?.gate === 'pending' || l?.gate === 'discussing'
  const lastKind = (l?: Lane) => (l && l.kinds.length ? l.kinds[l.kinds.length - 1] : '')
  const triage = lane('triage'), architect = lane('architect'), tester = lane('tester'), reviewer = lane('reviewer')
  const devs = ['dev-fix', 'dev-refactor'].map(lane).filter((l): l is Lane => !!l)
  const t = run.tests, bench = run.bench, rel = run.release
  const step = bench?.step ?? null

  const done: Record<FlowKey, boolean> = {
    triage: !busy(triage) && (finished(triage) || gateOpen(triage) || triage?.gate === 'approved'),
    'gate-triage': !triage || triage.gate === 'approved',
    architect: !busy(architect) && (finished(architect) || gateOpen(architect) || architect?.gate === 'approved'),
    'gate-start': !architect || architect.gate === 'approved',
    'tests-first': finished(tester) && (tester?.tests_first === 'passed' || (tester?.tests_first == null && devs.some((l) => l.status !== 'waiting'))),
    dev: devs.every(finished),
    before: t.total > 0 && t.failed === 0 && !t.held && !t.running,
    review: finished(reviewer),
    bench: step === 'after' || step === 'rerun' || step === 'done',
    after: step === 'rerun' || step === 'done',
    rerun: step === 'done' && (!rel || rel.release.verdict === 'PASS'),
    signoff: !!run.signoff,
  }
  const at = FLOW.findIndex((s) => !done[s.key])
  if (at < 0) return { steps: FLOW.map((def) => ({ def, state: 'done' })), current: null, now: `${run.signoff?.by ?? '发布负责人'}已签字放行` }
  const cur = FLOW[at].key
  const marks: Partial<Record<FlowKey, StepState>> = {}
  let state: StepState = 'current'
  let now = ''

  const held = (cur === 'before' && t.held) || (['bench', 'after', 'rerun', 'signoff'].includes(cur) && bench?.held) || (run.status === 'failed' && (t.held || bench?.held)) || null
  const failedLane = run.roles.find((l) => l.status === 'failed')
  const asking = run.roles.find((l) => l.status === 'awaiting_approval')
  const titles = (ls: Lane[]) => ls.map((l) => l.title).join('、')
  if (held) {
    state = 'held'
    now = `交给人决定：${held.why}`
  } else if (run.status === 'stopped') {
    state = 'failed'
    now = '运行已停止'
  } else if (failedLane) {
    state = 'failed'
    now = `${failedLane.title}失败了：看它的泳道，处理好以后点重试`
  } else if (asking) {
    now = `${asking.title}的一个工具调用在等你在 Kiro Crew 里批准`
  } else if (cur === 'triage') {
    now = busy(triage) ? '分诊在给每个发现定修、说明或延后' : '分诊马上开工'
  } else if (cur === 'gate-triage') {
    now = triage?.gate === 'discussing' ? '分诊在回答你在关卡上的讨论' : '等你在分诊关卡逐题决定'
  } else if (cur === 'architect') {
    now = '架构师在写重构方案和分工'
  } else if (cur === 'gate-start') {
    now = architect?.gate === 'discussing' ? '架构师在回答你在关卡上的讨论' : '等你在开工关卡批准重构方案和分工'
  } else if (cur === 'tests-first') {
    if (busy(tester) && tester?.tests_first === 'sent_back') now = '测试先行没过：有测试在基线提交上通过了，测试在重写'
    else now = busy(tester) || !finished(tester) ? '测试在写先失败的测试' : 'app 在基线提交上跑新测试：每个都必须失败'
  } else if (cur === 'dev') {
    const working = devs.filter(busy)
    const fixing = working.filter((l) => lastKind(l) === 'fix')
    const reviewed = working.filter((l) => lastKind(l) === 'review')
    if (fixing.length) {
      marks[step === 'after' && !bench?.running ? 'after' : 'before'] = 'failed'
      now = `检查没过，退回${titles(fixing)}修（第 ${Math.max(1, t.round || 0)} 轮检查）`
    } else if (reviewed.length) {
      marks.review = 'failed'
      now = `评审要改，退回${titles(reviewed)}`
    } else now = working.length ? `${titles(working)}在干活` : '等开发的分支合进运行分支'
  } else if (cur === 'before') {
    now = t.running || t.at === null ? `检查运行中（第 ${Math.max(1, t.round || 0)} 轮）` : '检查没过，正在退回负责的开发'
  } else if (cur === 'review') {
    now = '评审在只读审查'
  } else if (cur === 'bench') {
    const action = step ? BENCH_ACTION[step] : undefined
    const req = action ? bench?.state.pending.find((r) => r.action === step && !r.expired) : undefined
    if (req) {
      const d = req.digest.slice(0, 6)
      now = `等你批准${action}（摘要 ${d}…）：在右边台架面板输入摘要前 6 位，或在操作台上批`
    } else if (action) now = `app 在请求${action}：操作台上会出现请求`
    else now = step === 'doctor' ? 'app 在跑 bench/doctor.sh' : '马上上台架：先跑 bench/doctor.sh'
  } else if (cur === 'after') {
    now = '台架后检查运行中（logdiff、runtime-limits）'
  } else if (cur === 'rerun') {
    now = '独立重跑全部检查和 release.sh'
  } else {
    now = run.sign_block ? `还不能签字：${run.sign_block}` : '可以签字：在签字单上看证据页，签字放行'
  }

  return {
    steps: FLOW.map((def, i) => ({ def, state: i < at ? marks[def.key] ?? 'done' : i === at ? state : marks[def.key] ?? 'todo' })),
    current: cur,
    now,
  }
}
