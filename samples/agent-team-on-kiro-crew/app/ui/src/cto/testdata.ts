/** A small CTO view answer for tests: four deliveries before AI-DLC, five with it (two measured runs), four cards. */
import type { CtoData, CtoFlow } from './types'

const addDays = (iso: string, n: number) => {
  const [y, m, d] = iso.split('-').map(Number)
  const t = new Date(y, m - 1, d + n)
  return `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, '0')}-${String(t.getDate()).padStart(2, '0')}`
}

export function ctoData(): CtoData {
  const base = { signer: '', real: null, period: 'base' as const }
  const agent = { signer: 'Zhang Min', real: null, period: 'agent' as const }
  return {
    meta: {
      today: '2026-10-20', agentStart: '2026-07-29', weeks: Array.from({ length: 24 }, (_, i) => addDays('2026-05-06', 7 * i)),
      lines: ['电商', '移动应用', '客户关系管理', '供应链', '内部系统'], peoplePerLine: 12,
      eq: { S: 1, M: 5, L: 30 }, human: { S: 0.25, M: 1, L: 7 }, dayRate: 2000, seatUsdMonth: 40, fx: 7.1, months: 3, realAvgMins: 21,
    },
    items: [
      { ...agent, t: '双十一家电大促活动页', line: 0, kind: 'feat', size: 'M', ship: '2026-10-19', cyc: 0.012, mins: 17, signer: '研发负责人', real: 'r1013f04d', tests: '37/37', members: 8,
        issue: 'TY-4127', reporter: '运营部', created: '2026-10-19', pr: 5123, defects: [],
        decisions: [['批准需求', '补充规则：每人每款限购 2 台'], ['退回上线', '价保退差 48.6 万元，超过 30 万需 CFO 审批'], ['批准上线', '价保退差按 28 万元预留']],
        caught: { person: 1, review: 0, checks: 2 }, risks: [{ what: '价保退差超过 30 万审批线', amount: 206000, gate: '上线', role: 'compliance', at: 731 }] },
      { ...agent, t: '商品参数对比（冰箱）', line: 0, kind: 'feat', size: 'M', ship: '2026-10-19', cyc: 2.5, issue: 'TY-2790', reporter: '商品部', created: '2026-10-17', pr: 2990, defects: ['TY-2801'] },
      { ...agent, t: '带,逗号的交付', line: 0, kind: 'feat', size: 'M', ship: '2026-10-18', cyc: 0.02, mins: 25, signer: 'Wu Hao', real: 'r1020live', tests: '20/20', members: 5, decisions: [['批准范围', '无补充意见']] },
      { ...agent, t: '库存预警阈值配置（华东仓）', line: 4, kind: 'fix', size: 'S', ship: '2026-10-18', cyc: 0.8 },
      { ...agent, t: '供应商对账平台', line: 3, kind: 'app', size: 'L', ship: '2026-10-01', cyc: 7 },
      { ...base, t: '优惠券叠加规则（空调）', line: 0, kind: 'feat', size: 'M', ship: '2026-06-01', cyc: 10 },
      { ...base, t: '到手价计算（电视）', line: 0, kind: 'feat', size: 'M', ship: '2026-06-02', cyc: 10 },
      { ...base, t: '门店库存同步服务', line: 3, kind: 'app', size: 'L', ship: '2026-06-10', cyc: 30 },
      { ...base, t: '通讯录部门排序（行政部）', line: 4, kind: 'fix', size: 'S', ship: '2026-06-12', cyc: 2 },
    ],
    wip: [
      { t: '双十一官方商城大促', line: 0, kind: 'feat', size: 'M', state: 'wait', col: '运维', gate: '上线关卡', role: 'compliance', who: '负责人', hours: 0.2, focus: '独立审查已出结论，待负责人决定', live: true, real: 'r1020gate', issue: 'TY-4130', reporter: '运营部' },
      { t: '会员手机号脱敏位数修正', line: 2, kind: 'fix', size: 'S', state: 'wait', col: '构思', gate: '范围关卡', who: 'Wang Lei', hours: 2.1, focus: '3 个口径待答复' },
      { t: '库存同步延迟（华南仓）', line: 3, kind: 'fix', size: 'S', state: 'agent', col: '构建', members: 4, mins: 12 },
      { t: '加班申请审批（法务部）', line: 4, kind: 'feat', size: 'M', state: 'pool', col: '需求池', mins: 4 },
    ],
  }
}

/** The 价值流 of the 双十一 实测 (r1013f04d), as GET /cto/flow answers it (rounded). */
export function ctoFlow(): CtoFlow {
  const seg = (from: number, to: number, who: 'agent' | 'person', col: string, phase: string, label: string, roles: string[], gate: string | null = null, decision: '批准' | '退回' | null = null) =>
    ({ from, to, who, col, phase, label, roles, gate, decision })
  return {
    run: 'r1013f04d', status: 'done', started_at: 1791840066, end: 1022,
    segments: [
      seg(0, 52, 'agent', '启动', 'inception', '启动', ['product']),
      seg(52, 259, 'person', '启动', 'inception', '等人批准 · 需求关卡', ['product'], 'product', '批准'),
      seg(260, 536, 'agent', '构建', 'construction', '构建', ['backend1', 'tester']),
      seg(536, 731, 'person', '运维', 'construction', '等人批准 · 上线关卡', ['compliance'], 'compliance', '退回'),
      seg(731, 837, 'agent', '构建', 'construction', '返工', ['backend1', 'compliance']),
      seg(837, 951, 'person', '运维', 'construction', '等人批准 · 上线关卡', ['compliance'], 'compliance', '批准'),
      seg(952, 1022, 'agent', '运维', 'operation', '运维', ['deploy']),
    ],
    marks: [
      { at: 52, kind: 'gate', role: 'product', label: '需求关卡：等人批准' }, { at: 259, kind: 'approved', role: 'product', label: '批准需求' },
      { at: 536, kind: 'gate', role: 'compliance', label: '上线关卡：等人批准' }, { at: 731, kind: 'bounce', role: 'compliance', label: '退回上线' },
      { at: 1019, kind: 'deployed', role: 'deploy', label: '部署到本机' }, { at: 1022, kind: 'signoff', role: null, label: '研发负责人 签字放行' },
    ],
    decisions: [
      { at: 259, role: 'product', gate: '批准需求', note: '补充规则：每人每款限购 2 台' },
      { at: 731, role: 'compliance', gate: '退回上线', note: '价保退差 48.6 万元，超过 30 万需 CFO 审批' },
      { at: 951, role: 'compliance', gate: '批准上线', note: '价保退差按 28 万元预留' },
    ],
    agent_s: 504, person_s: 516, gates: 3, credits: 34.2, members: 8, tests: { passed: 37, total: 37, enterprise: 28 },
    sent_back: { person: 1, review: 0, checks: 0 }, risks: [{ what: '价保退差超过 30 万审批线', amount: 206000, gate: '上线', role: 'compliance', at: 731 }], rework: 1, review: '审查说可以交付', deployed: true,
    issue: { id: 'TY-4127', kind: '需求', reporter: '运营部', created_at: 1791840066 },
    pr: { number: 5123, head: 'team/r1013f04d/run', base: 'main', state: 'signed', opened_at: 1791841088, merged_at: 1791841088, merged_by: '研发负责人', sha: '', files: 17, added: 1523, removed: 40, checks: '37/37', review: '审查说可以交付' },
    titles: { product: '产品经理', backend1: '后端开发 #1', tester: '测试工程师', compliance: '合规审查', deploy: '部署工程师' },
    team: [
      { key: 'product', title: '产品经理', icon: 'pm', skipped: false, credits: 2.3 }, { key: 'backend1', title: '后端开发 #1', icon: 'backend', skipped: false, credits: 9.1 },
      { key: 'tester', title: '测试工程师', icon: 'tester', skipped: false, credits: 4.2 }, { key: 'compliance', title: '合规审查', icon: 'compliance', skipped: false, credits: 6.0 },
      { key: 'deploy', title: '部署工程师', icon: 'deploy', skipped: false, credits: 3.1 }, { key: 'mobile', title: '安卓开发', icon: 'mobile', skipped: true, credits: 0 },
    ],
  }
}
