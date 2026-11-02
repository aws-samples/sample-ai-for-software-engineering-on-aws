/**
 * Board fixtures for the tests and the standalone preview, all derived from the realistic mid-run
 * snapshot board-running.json:
 *
 * - runningBoard: the snapshot as is (architect/designer/tester merged, backend on fix round 2,
 *   frontend running with a violation and a merge conflict, ops done, reviewer waiting, tests 6/12);
 * - scenario(): the same run played forward, one snapshot per poll (tool calls, backend's fix merged
 *   and tests flipping green, frontend undoing its violation, ops merged, a bounce, frontend's second
 *   round, 12/12, the handoffs to the reviewer, the review, done); finishedBoard is its last step;
 * - startedBoard (just started), troubleBoard (stalled, awaiting approval, queued), failedBoard
 *   (frontend failed after two fix rounds), emptyBoard (no runs), multiRunBoard (three runs);
 * - vstatdBoard: the vstatd team (team-vstatd.json) at its triage gate (questions with citations), held at the bench
 *   (the check wall green, a deploy waiting at the operator console), or ended with the release check (the
 *   independent rerun, a check that differed, the evidence page);
 * - readinessOf: GET /readiness on a Mac with the build image but no bench yet.
 */
import raw from './fixtures/board-running.json'
import type { Board, FileChange, Lane, Readiness, RunDetail, ScoreRun, Scorecard, TeamEvent, TeamEventKind, TestCase } from '../types'

export const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T

export function runningBoard(): Board {
  return clone(raw) as unknown as Board
}

export function emptyBoard(at: number = raw.at): Board {
  return { at, runs: [], run: null }
}

const LIVE_STATUSES = new Set(['running', 'fixing', 'stalled', 'awaiting_approval'])

export function lane(b: Board, key: string): Lane {
  const l = b.run?.roles.find((r) => r.key === key)
  if (!l) throw new Error(`no lane ${key}`)
  return l
}

export function caseOf(b: Board, id: string): TestCase {
  const c = b.run?.tests.cases.find((x) => x.id === id || x.ac === id)
  if (!c) throw new Error(`no test case ${id}`)
  return c
}

/** Recount passed / failed / total from the cases. */
export function recount(b: Board): Board {
  const t = b.run!.tests
  t.passed = t.cases.filter((c) => c.status === 'pass').length
  t.failed = t.cases.filter((c) => c.status === 'fail').length
  t.total = t.cases.length
  return b
}

/** One case to *status* (an id like `api-signup.test.js#AC-6`, or just `AC-6`). */
export function setCase(b: Board, id: string, status: TestCase['status'], message: string | null = null): Board {
  const c = caseOf(b, id)
  c.status = status
  c.message = status === 'fail' ? (message ?? c.message ?? 'failed') : null
  return recount(b)
}

/** Append an event (next seq, at the snapshot's time unless given). */
export function withEvent(b: Board, e: Partial<TeamEvent> & { kind: TeamEventKind }): Board {
  const r = b.run!
  const seq = r.events.reduce((m, x) => Math.max(m, x.seq), 0) + 1
  r.events.push({ seq, at: e.at ?? b.at, kind: e.kind, role: e.role ?? null, text: e.text ?? e.kind, from: e.from ?? null, to: e.to ?? null, data: e.data ?? null })
  return b
}

/** Move every timestamp in the board by *dt* seconds. */
export function shiftTimes(b: Board, dt: number): Board {
  const s = (v: number | null) => (v === null ? null : v + dt)
  b.at += dt
  for (const c of b.runs) {
    c.started_at += dt
    c.ended_at = s(c.ended_at)
  }
  const r = b.run
  if (!r) return b
  r.started_at += dt
  r.ended_at = s(r.ended_at)
  for (const l of r.roles) {
    l.started_at = s(l.started_at)
    l.done_at = s(l.done_at)
    for (const c of l.commits) c.at += dt
    if (l.agent) {
      l.agent.started += dt
      l.agent.last_activity = s(l.agent.last_activity)
      for (const t of l.agent.recent_tools) t.at += dt
    }
  }
  r.tests.at = s(r.tests.at)
  for (const h of r.tests.history) h.at += dt
  for (const m of r.merges) m.at += dt
  for (const e of r.events) e.at += dt
  return b
}

/** The same board as another run (id, title and branch names), its times moved by *dt*. */
export function asRun(b: Board, id: string, title: string, dt: number): Board {
  const old = b.run!.id
  const swap = (s: string | null) => (s === null ? null : s.split(old).join(id))
  shiftTimes(b, dt)
  const r = b.run!
  r.id = id
  r.title = title
  r.delivery = { ...r.delivery, name: title } // the 交付名 the team's defaults give: the requirement's first line
  r.branch = swap(r.branch)!
  r.repo = swap(r.repo)!
  for (const l of r.roles) {
    l.branch = swap(l.branch)
    l.worktree = swap(l.worktree)
  }
  b.runs = b.runs.map((c) => (c.id === old ? { ...c, id, title, name: title } : c))
  r.events = r.events.map((e) => (e.kind === 'run' ? { ...e, text: e.text.replace('活动报名小站', title) } : e))
  return b
}

/** Keep the run's card (Board.runs) and the derived totals in step with the run. */
function sync(b: Board): Board {
  const r = b.run!
  recount(b)
  const credits = r.roles.reduce((a, l) => a + (l.credits ?? 0), 0)
  r.credits = credits ? Math.round(credits * 10) / 10 : null
  b.runs = b.runs.map((c) =>
    c.id === r.id
      ? {
          ...c,
          status: r.status,
          ended_at: r.ended_at,
          roles_done: r.roles.filter((l) => l.status === 'done' || l.status === 'merged').length,
          roles_total: r.roles.length,
          tests: { passed: r.tests.passed, failed: r.tests.failed, total: r.tests.total },
        }
      : c,
  )
  return b
}

// ---------------------------------------------------------------------------------------------
// the scripted run
// ---------------------------------------------------------------------------------------------

class Script {
  readonly b: Board
  constructor(base: Board) {
    this.b = clone(base)
  }
  private get run(): RunDetail {
    return this.b.run!
  }
  lane(k: string): Lane {
    return lane(this.b, k)
  }
  /** World time passes: the run, its live lanes and their agents get older. */
  tick(dt: number): this {
    const r = this.run
    this.b.at += dt
    if (!r.ended_at) r.wall_s += dt
    const live = r.roles.filter((l) => LIVE_STATUSES.has(l.status))
    for (const l of live) {
      l.active_s += dt
      if (l.agent) l.agent.elapsed_s += dt
    }
    r.serial_s += dt * live.length
    return this
  }
  event(kind: TeamEventKind, role: string | null, text: string, ago = 0, from: string | null = null, to: string | null = null): this {
    withEvent(this.b, { kind, role, text, from, to, at: this.b.at - ago })
    const r = this.run
    if (r.events.length > 200) r.events.splice(0, r.events.length - 200)
    return this
  }
  tool(role: string, tool: string, kind: string, detail: string, last: string, ago: number): this {
    const l = this.lane(role)
    const a = l.agent!
    const at = this.b.at - ago
    a.recent_tools = [...a.recent_tools, { at, tool, kind, detail }].slice(-8)
    a.last_tool = last
    a.last_activity = at
    a.turns += 1
    a.tool_count += 1
    return this.event('tool', role, `${l.title}：${last}`, ago)
  }
  say(role: string, text: string): this {
    const a = this.lane(role).agent!
    a.text_tail = `${a.text_tail ?? ''}${text}`.slice(-300)
    return this
  }
  commit(role: string, sha: string, subject: string, files: FileChange[], ago: number, drop: string[] = []): this {
    const l = this.lane(role)
    l.commits = [...l.commits, { sha, subject, at: this.b.at - ago }].slice(-8)
    const by = new Map(l.files.filter((f) => !drop.includes(f.path)).map((f) => [f.path, f]))
    for (const f of files) {
      const had = by.get(f.path)
      by.set(f.path, had ? { ...had, added: had.added + f.added, removed: had.removed + f.removed } : f)
    }
    l.files = [...by.values()].sort((x, y) => y.added + y.removed - (x.added + x.removed)).slice(0, 12)
    l.lines = { added: l.files.reduce((a, f) => a + f.added, 0), removed: l.files.reduce((a, f) => a + f.removed, 0) }
    l.violations = l.violations.filter((v) => !drop.includes(v))
    return this.event('committed', role, `${l.title}提交：${subject}`, ago)
  }
  done(role: string, summary: string, credits: number, ago: number): this {
    const l = this.lane(role)
    l.status = 'done'
    l.done_at = this.b.at - ago
    l.summary = summary
    if (l.agent) {
      l.agent.credits = credits
      l.agent.last_activity = this.b.at - ago
    }
    l.credits = Math.round(((l.credits ?? 0) + credits) * 10) / 10
    return this.event('done', role, `${l.title}完成：${summary}`, ago)
  }
  merge(role: string, sha: string, files: number, ago: number): this {
    const l = this.lane(role)
    this.run.merges.push({ role, sha, at: this.b.at - ago, status: 'merged', files, note: null })
    l.status = 'merged'
    return this.event('merged', role, `${l.title}的分支合入运行分支`, ago, role, 'run')
  }
  test(pass: string[], ago: number, text?: string): this {
    for (const id of pass) setCase(this.b, id, 'pass')
    const t = this.run.tests
    t.at = this.b.at - ago
    t.history.push({ at: t.at, passed: t.passed, failed: t.failed })
    return this.event('tests', null, text ?? `测试 ${t.passed}/${t.total}`, ago)
  }
  bounce(role: string, acs: string[], ago: number): this {
    const l = this.lane(role)
    return this.event('bounce', role, `${acs.join('、')} 失败，打回${l.title}`, ago, 'tests', role)
  }
  spawn(role: string, attempt: number, text: string, ago: number, first: { tool: string; kind: string; detail: string; last: string; tail: string }): this {
    const l = this.lane(role)
    const at = this.b.at - ago
    l.status = attempt > 1 ? 'fixing' : 'running'
    l.attempt = attempt
    l.started_at = l.started_at ?? at
    l.done_at = null
    l.agent = {
      id: `s-${role}${attempt}`,
      turns: 1,
      tool_count: 1,
      last_tool: first.last,
      last_activity: at,
      started: at,
      elapsed_s: ago,
      queued_reason: null,
      error: null,
      recent_tools: [{ at, tool: first.tool, kind: first.kind, detail: first.detail }],
      text_tail: first.tail,
      credits: null,
    }
    if (!l.worktree) {
      l.worktree = `${this.run.repo.replace(/\/repo$/, '')}/wt/${role}`
      l.branch = `team/${this.run.id}/${role}`
    }
    return this.event('spawned', role, text, ago)
  }
  status(s: RunDetail['status'], ago = 0): this {
    this.run.status = s
    if (s === 'done' || s === 'failed' || s === 'stopped') this.run.ended_at = this.b.at - ago
    return this
  }
  snap(): Board {
    return clone(sync(this.b))
  }
}

/** The running fixture played forward, one snapshot per poll; the first is the fixture itself. */
export function scenario(): Board[] {
  const s = new Script(runningBoard())
  const out: Board[] = [s.snap()]
  // 1: both implementers at work; frontend commits the error message
  s.tick(15)
    .tool('backend', 'fs_write', 'write', 'backend/validate.js', 'Editing backend/validate.js', 12)
    .say('backend', 'checkCapacity 改成 >=，checkDuplicate 放到写入之前。跑一下 api-signup 的测试。')
    .tool('backend', 'execute_bash', 'shell', 'node --test tests/api-signup.test.js', 'Running: node --test tests/api-signup.test.js', 4)
    .tool('frontend', 'fs_write', 'write', 'frontend/app.js', 'Editing frontend/app.js', 9)
    .say('frontend', '提交失败时在表单下面渲染 .error-msg，文字用接口回的 reason。')
    .commit('frontend', 'f6a1c3e', '[frontend] 报名失败时显示原因', [{ path: 'frontend/app.js', added: 24, removed: 3, status: 'A' }], 2)
  out.push(s.snap())
  // 2: backend's second round is merged, three cases flip green
  s.tick(20)
    .say('backend', 'AC-6、AC-7、AC-10 都过了，提交。')
    .commit(
      'backend',
      'e9c4d21',
      '[backend] 修：名额判断 >=，写入前查重复邮箱，名单按时间排序',
      [
        { path: 'backend/validate.js', added: 12, removed: 3, status: 'A' },
        { path: 'backend/store.js', added: 6, removed: 1, status: 'A' },
      ],
      17,
    )
    .done('backend', '名额判断改成 >=、写入前查重复邮箱、名单按报名时间排序', 4.8, 13)
    .merge('backend', 'e9c4d21', 2, 10)
    .test(['AC-6', 'AC-7', 'AC-10'], 3)
  out.push(s.snap())
  // 3: frontend gives backend/server.js back; ops is merged
  s.tick(20)
    .tool('frontend', 'execute_bash', 'shell', 'git checkout team/r1006a/run -- backend/server.js', 'Running: git checkout team/r1006a/run -- backend/server.js', 17)
    .say('frontend', 'backend/server.js 不归前端管，撤回我的改动；409 在前端自己处理。')
    .commit('frontend', 'f6d9e10', '[frontend] 撤回对 backend/server.js 的改动', [], 12, ['backend/server.js'])
    .merge('ops', '0a6d3e1', 3, 7)
    .test([], 2)
  out.push(s.snap())
  // 4: frontend is merged, two more green, AC-11 still red: bounced back for round 2
  s.tick(25)
    .done('frontend', '首页、详情、报名表单、名单页；报名失败显示原因', 14.2, 22)
    .merge('frontend', 'f6d9e10', 3, 18)
    .test(['AC-8', 'AC-12'], 12)
    .bounce('frontend', ['AC-11'], 8)
    .spawn('frontend', 2, '前端第 2 轮：修 AC-11', 4, {
      tool: 'fs_read',
      kind: 'read',
      detail: 'tests/web-render.test.js',
      last: 'Reading tests/web-render.test.js',
      tail: 'AC-11：手机宽度下表单可用。失败信息是 form wider than 375px，先看表单的宽度是谁定的……',
    })
  out.push(s.snap())
  // 5: frontend's second round at work
  s.tick(20)
    .tool('frontend', 'fs_read', 'read', 'frontend/styles/main.css', 'Reading frontend/styles/main.css', 15)
    .say('frontend', '找到了：表单外面那层写死了 min-width: 420px。改成 width: 100%，最多 420px。')
    .tool('frontend', 'fs_write', 'write', 'frontend/index.html', 'Editing frontend/index.html', 8)
    .tool('frontend', 'execute_bash', 'shell', 'node --test tests/web-render.test.js', 'Running: node --test tests/web-render.test.js', 3)
  out.push(s.snap())
  // 6: 12/12; the implementation is handed to the reviewer
  s.tick(25)
    .commit('frontend', 'f8b2a47', '[frontend] 修：手机上表单不再超宽', [{ path: 'frontend/index.html', added: 5, removed: 2, status: 'A' }], 22)
    .done('frontend', 'AC-11 修好：表单在 375px 下不再溢出', 3.9, 19)
    .merge('frontend', 'f8b2a47', 1, 16)
    .test(['AC-11'], 11, '测试 12/12：全绿')
    .event('handoff', 'reviewer', '后端的实现交给评审', 7, 'backend', 'reviewer')
    .event('handoff', 'reviewer', '前端的实现交给评审', 7, 'frontend', 'reviewer')
    .event('handoff', 'reviewer', '运维的脚本交给评审', 6, 'ops', 'reviewer')
    .spawn('reviewer', 1, '评审开工：只读核对合并后的改动', 3, {
      tool: 'fs_read',
      kind: 'read',
      detail: 'docs/product/acceptance.md',
      last: 'Reading docs/product/acceptance.md',
      tail: '先读验收标准，再看运行分支相对 5e1f0aa 的全部改动。',
    })
    .status('reviewing')
  out.push(s.snap())
  // 7: the review
  s.tick(20)
    .tool('reviewer', 'execute_bash', 'shell', 'git diff 5e1f0aa..team/r1006a/run --stat', 'Running: git diff 5e1f0aa..team/r1006a/run --stat', 14)
    .say('reviewer', '对照 12 条验收标准逐条核：接口和 contracts/api.md 一致；前端只通过 HTTP 拿数据；运维脚本带健康检查；没有越界改动……')
    .tool('reviewer', 'fs_read', 'read', 'backend/validate.js', 'Reading backend/validate.js', 4)
  out.push(s.snap())
  // 8: done
  s.tick(25)
    .say('reviewer', 'DONE: 可以交付。')
    .done('reviewer', 'DONE: 可以交付 · 12 条验收标准都有实现和测试', 7.6, 14)
    .event('review', 'reviewer', '评审：可以交付', 12)
    .event('run', null, '运行完成：12/12 全绿，评审说可以交付', 6)
    .status('done', 6)
  out.push(s.snap())
  return out
}

export function finishedBoard(): Board {
  const steps = scenario()
  return steps[steps.length - 1]
}

/** A run 42 s in: the product manager is reading the requirement, everyone else waits. */
export function startedBoard(): Board {
  const b = runningBoard()
  const r = b.run!
  const t0 = r.started_at
  b.at = t0 + 42
  Object.assign(r, { status: 'running', wall_s: 42, serial_s: 42, credits: null, ended_at: null })
  for (const l of r.roles) {
    Object.assign(l, {
      status: 'waiting',
      attempt: 1,
      agent: null,
      worktree: null,
      branch: null,
      files: [],
      lines: { added: 0, removed: 0 },
      commits: [],
      violations: [],
      owns_tests: [],
      started_at: null,
      done_at: null,
      active_s: 0,
      credits: null,
      summary: null,
    })
  }
  const pm = lane(b, 'pm')
  Object.assign(pm, {
    status: 'running',
    started_at: t0,
    active_s: 42,
    worktree: `${r.repo.replace(/\/repo$/, '')}/wt/pm`,
    branch: `team/${r.id}/pm`,
    agent: {
      id: 's-pm',
      turns: 3,
      tool_count: 4,
      last_tool: 'Reading README.md',
      last_activity: t0 + 40,
      started: t0,
      elapsed_s: 42,
      queued_reason: null,
      error: null,
      recent_tools: [
        { at: t0 + 6, tool: 'fs_read', kind: 'read', detail: 'README.md' },
        { at: t0 + 19, tool: 'execute_bash', kind: 'shell', detail: 'ls docs/' },
        { at: t0 + 40, tool: 'fs_read', kind: 'read', detail: 'README.md' },
      ],
      text_tail: '需求是一个活动报名小站：首页列出活动，点进去看详情，填姓名和邮箱报名；名额满了不能报，同一个邮箱不能报两次；主办方能看名单。先把页面和动作列出来，再写成可测的验收标准 AC-1、AC-2……',
      credits: null,
    },
  })
  r.tests = { at: null, command: 'node --test tests/', cases: [], passed: 0, failed: 0, total: 0, history: [], held: null, round: 0, running: false }
  r.merges = []
  r.events = r.events.slice(0, 2)
  withEvent(b, { kind: 'tool', role: 'pm', text: '产品经理：Reading README.md', at: t0 + 6 })
  return sync(b)
}

/** The loud states at once: backend stalled, frontend waiting for approval, ops queued. */
export function troubleBoard(): Board {
  const b = runningBoard()
  const r = b.run!
  const be = lane(b, 'backend')
  be.status = 'stalled'
  be.agent!.last_activity = b.at - 260
  be.agent!.last_tool = 'Running: node --test tests/api-signup.test.js'
  const fe = lane(b, 'frontend')
  fe.status = 'awaiting_approval'
  fe.agent!.last_tool = 'Running: rm -rf frontend/dist && node build.js'
  const ops = lane(b, 'ops')
  Object.assign(ops, {
    status: 'queued',
    files: [],
    lines: { added: 0, removed: 0 },
    commits: [],
    started_at: null,
    done_at: null,
    active_s: 0,
    credits: null,
    summary: null,
    agent: {
      id: 's-op',
      turns: 0,
      tool_count: 0,
      last_tool: '',
      last_activity: null,
      started: b.at - 35,
      elapsed_s: 35,
      queued_reason: 'KiroCrew 同时只放 2 个子 agent 跑，它排在第 1 位',
      error: null,
      recent_tools: [],
      text_tail: null,
      credits: null,
    },
  })
  r.events = r.events.filter((e) => !(e.role === 'ops' && e.kind === 'done'))
  withEvent(b, { kind: 'spawned', role: 'ops', text: '运维已派出：排队等 Kiro Crew 开始会话', at: b.at - 35 })
  sync(b)
  return b
}

/** Frontend's second round did not fix AC-11: the run stops there. */
export function failedBoard(): Board {
  const steps = scenario()
  const s = new Script(steps[5])
  s.tick(30)
    .commit('frontend', 'f8b2a47', '[frontend] 试图修手机宽度', [{ path: 'frontend/index.html', added: 5, removed: 2, status: 'A' }], 27)
    .done('frontend', '改了表单宽度', 3.9, 24)
    .merge('frontend', 'f8b2a47', 1, 20)
    .test([], 14, '测试 11/12')
    .event('failed', 'frontend', '前端两轮修复后 AC-11 仍然失败', 9)
    .event('run', null, '运行失败：前端用完了 2 轮修复', 6)
    .status('failed', 6)
  const b = s.snap()
  const fe = lane(b, 'frontend')
  fe.status = 'failed'
  fe.agent!.error = 'AC-11 两轮修复后仍然失败：form wider than 375px'
  return sync(b)
}

/** Three runs: the live one, yesterday's finished one, a failed one the day before. */
export function multiRunBoard(selected?: string | null): Board {
  const live = runningBoard()
  const done = asRun(finishedBoard(), 'r1005z', '读书会报名页', -86400)
  const failed = asRun(failedBoard(), 'r1004x', '社团招新页', -2 * 86400)
  const pick = selected === 'r1005z' ? done : selected === 'r1004x' ? failed : live
  return { at: live.at, runs: [live.runs[0], done.runs[0], failed.runs[0]], run: pick.run }
}

/** A v2 run (team-aidlc.json) in the middle of construction: phases, an approved scope gate, a fix round. */
export function aidlcBoard(gatePending = false): Board {
  const b = runningBoard()
  const run = b.run!
  const tpl = run.roles.find((r) => r.key === 'backend')!
  const mk = (key: string, title: string, phase: string, stage: string, deps: string[], status: Lane['status'], extra: Partial<Lane> = {}): Lane => ({
    ...clone(tpl), key, title, phase, stage, depends_on: deps, status, gate: null, gate_label: '', kinds: ['work'], attempt: 1, aidlc_agent: '',
    writable: [`${key}/**`], violations: [], mission: '', summary: null, ...extra,
  })
  const dev = 'aidlc-developer-agent'
  const later = (s: Lane['status']): Lane['status'] => (gatePending ? 'waiting' : s)
  run.roles = [
    mk('intent', '意图', 'ideation', '1.1 意图捕获', [], 'merged', { aidlc_agent: 'aidlc-product-agent' }),
    mk('feasibility', '约束', 'ideation', '1.3 可行性与约束', [], 'merged', { aidlc_agent: 'aidlc-compliance-agent,aidlc-devsecops-agent' }),
    mk('scope', '范围', 'ideation', '1.4 范围定义', ['intent', 'feasibility'], 'merged', { gate: gatePending ? 'pending' : 'approved', gate_label: '范围', aidlc_agent: 'aidlc-product-agent' }),
    mk('architect', '架构师', 'inception', '2.1 逆向工程 · 2.8 接口约定', ['scope'], later('merged'), { aidlc_agent: 'aidlc-architect-agent' }),
    mk('pm', '需求', 'inception', '2.3 需求分析', ['architect'], later('merged'), { aidlc_agent: 'aidlc-product-agent' }),
    mk('designer', '界面', 'inception', '2.5 界面细化', ['architect'], later('merged'), { aidlc_agent: 'aidlc-design-agent' }),
    mk('compliance', '合规与安全', 'construction', '3.2 非功能需求 → 检查', ['architect'], later('merged'), { aidlc_agent: 'aidlc-compliance-agent,aidlc-devsecops-agent' }),
    mk('tester', '测试', 'construction', '3.6 构建与测试 · 护栏', ['pm'], later('merged'), { aidlc_agent: 'aidlc-quality-agent' }),
    mk('backend', '后端', 'construction', '3.5 代码生成', ['architect', 'compliance'], later('fixing'), { aidlc_agent: dev, attempt: 2, kinds: ['work', 'fix'] }),
    mk('frontend', '网页', 'construction', '3.5 代码生成', ['architect', 'designer', 'compliance'], later('running'), { aidlc_agent: dev }),
    mk('mobile', '安卓', 'construction', '3.5 代码生成', ['architect', 'designer', 'compliance'], later('merged'), { aidlc_agent: dev }),
    mk('ops', '运维', 'construction', '3.5 代码生成', ['architect', 'compliance'], later('merged'), { aidlc_agent: 'aidlc-pipeline-deploy-agent' }),
    mk('reviewer', '评审', 'review', '评审关卡', ['backend', 'frontend', 'mobile', 'ops'], 'waiting', { writable: [], aidlc_agent: 'aidlc-architecture-reviewer-agent,aidlc-product-lead-agent' }),
  ]
  run.edges = run.roles.flatMap((r) => r.depends_on.map((d) => [d, r.key] as [string, string]))
  run.team = { name: 'AI-DLC 专家团队', orchestrator: 'kirocrew-team' }
  run.title = '下个月要把 Private IM 推给全公司用，并上架 Google Play。'
  run.status = gatePending ? 'gating' : 'fixing'
  run.tests = gatePending ? { ...run.tests, cases: [], passed: 0, failed: 0, total: 0, history: [] } : { ...run.tests, passed: 70, failed: 12, total: 82, history: [{ at: run.tests.at ?? b.at, passed: 40, failed: 42 }, ...run.tests.history] }
  return b
}

const CHECK = (name: string, verdict: 'PASS' | 'FAIL' | 'BLOCKED', tier: string, owner: string | null, message: string | null, ms: number): TestCase => ({
  id: name, ac: name, name: `${name}.sh`, file: '', status: verdict === 'PASS' ? 'pass' : verdict === 'FAIL' ? 'fail' : 'blocked', verdict, tier, owner, ms, message,
})

/** The vstatd team (team-vstatd.json): at its triage gate, held at the bench, or ended with the release check. */
export function vstatdBoard(stage: 'triage' | 'bench' | 'release' = 'bench'): Board {
  const b = runningBoard()
  const run = b.run!
  const t = run.started_at
  const tpl = run.roles.find((r) => r.key === 'backend')!
  const at = (stage === 'triage' ? 0 : stage === 'bench' ? 1 : 2)
  const mk = (key: string, title: string, icon: string, phase: string, stage_: string, deps: string[], status: Lane['status'], member: string, extra: Partial<Lane> = {}): Lane => ({
    ...clone(tpl), key, title, icon, phase, stage: stage_, depends_on: deps, status, gate: null, gate_label: '', kinds: ['work'], attempt: 1,
    aidlc_agent: member, member, writable: [`src/${key}.*`], violations: [], mission: '', summary: null, agent: null, owns_tests: [], questions: [], answers: [], ...extra,
  })
  const after = (s: Lane['status']): Lane['status'] => (at ? s : 'waiting')
  const questions = [
    { id: 'F-008', q: 'F-008 分诊建议说明为误报或无害、不修（待办标的是 fix）：src/supervisor.cpp › Supervisor::check', options: [{ key: 'A', text: '同意说明（评审还会复核引用）' }, { key: 'B', text: '不同意：本批修复（退回分诊补齐证据和行为）' }],
      recommend: 'A', why: '条件实现宽限期，分析器看不到回调里设的标志', cites: ['[VSTATD-IF p.7 §4.2]'], decision: 'justify' },
    { id: 'F-021', q: 'F-021 分诊建议延后（待办标的是 fix）：src/ipc_server.cpp › IpcServer::accept', options: [{ key: 'A', text: '同意延后' }, { key: 'B', text: '不同意：本批修复（退回分诊补齐证据和行为）' }],
      recommend: 'A', why: '改法要动 IPC 的行为；什么时候再处理：下一批', cites: [], decision: 'defer' },
  ]
  run.roles = [
    mk('triage', '分诊', 'scope', 'inception', '分诊 · 修、说明或延后', [], 'merged', 'aidlc-developer-agent',
      { gate: at ? 'approved' : 'pending', gate_label: '分诊', writable: ['docs/aidlc/triage.json', 'docs/aidlc/triage.md'], questions: at ? [] : questions }),
    mk('architect', '架构师', 'architect', 'inception', '重构方案 · 分工', ['triage'], after('merged'), 'aidlc-architect-agent', { gate: at ? 'approved' : null, gate_label: '开工' }),
    mk('tester', '测试', 'tester', 'construction', '测试先行', ['architect'], after('merged'), 'aidlc-quality-agent', { writable: ['tests/**'], tests_first: at ? 'passed' : null }),
    mk('dev-fix', '开发 · 修复', 'backend', 'construction', '修复', ['tester'], after('merged'), 'aidlc-developer-agent', { attempt: at ? 2 : 1, kinds: at ? ['work', 'fix'] : ['work'] }),
    mk('dev-refactor', '开发 · 重构', 'frontend', 'construction', '重构', ['tester'], after('merged'), 'aidlc-developer-agent'),
    mk('reviewer', '评审', 'reviewer', 'review', '评审', ['dev-fix', 'dev-refactor'], at ? 'done' : 'waiting', 'aidlc-architecture-reviewer-agent', { writable: [], summary: at ? '可以交付' : null }),
  ]
  run.edges = run.roles.flatMap((r) => r.depends_on.map((d) => [d, r.key] as [string, string]))
  run.team = { name: '车载平台服务 · AI-DLC 团队', orchestrator: 'vstatd-team' }
  run.title = '修复 vstatd 静态分析待办里标为 fix 的发现'
  run.requirement = '修复 vstatd 静态分析待办里标为 fix 的发现，并把信号表的处理从 750 行的 Service::run() 里拆出去。行为不变：在录制的行驶数据上，信号、值、超时和错误都和原来一样；目标上的内存不超过限额。'
  run.knowledge = { source: { name: 'vstatd', present: true, items: 14, status: 'synced', files_total: 14, files_done: 14, path: '~/workplace/vstatd/knowledge' }, hits: [] }
  run.merges = []
  run.tests = at ? {
    at: t + 5400, command: 'build static unit size trace', passed: 5, failed: 0, total: 5,
    history: [{ at: t + 3000, passed: 0, failed: 3 }, { at: t + 4200, passed: 3, failed: 2 }, { at: t + 5400, passed: 5, failed: 0 }],
    cases: [CHECK('build', 'PASS', 'n/a', 'dev-fix', null, 212_000), CHECK('static', 'PASS', 'n/a', 'dev-fix', null, 98_000),
      CHECK('unit', 'PASS', 'unit test', 'dev-fix', null, 301_000), CHECK('size', 'PASS', 'n/a', 'dev-refactor', null, 4_000), CHECK('trace', 'PASS', 'n/a', 'dev-fix', null, 2_000)],
    held: null, round: 3, running: false,
  } : { at: null, command: 'build static unit size trace', cases: [], passed: 0, failed: 0, total: 0, history: [], held: null, round: 0, running: false }
  const digest = 'bc93723c5a1f0e8d2b7c46e19a0d3f58c2e7b1a49d6f0c38e5b2a71d94c06e3f'
  const benchState = { dir: '~/.cc1-bench', target: { state: 'off', why: '台架状态目录里没有目标状态（CC-1 没开机）' }, supply: null, pending: [], actions: [] }
  run.bench = !at ? { step: null, running: null, held: null, doctor: null, artifact: null, run_dir: null, baseline: '~/workplace/vstatd-team/baseline', actions: [], state: benchState, console: null } : {
    step: stage === 'bench' ? 'deploy' : 'done', running: stage === 'bench' ? 'deploy' : null,
    held: null, doctor: { ok: true, rc: 0, at: t + 5460, fails: [], warns: ['memory: 4.3 GiB for Docker (6 GiB recommended)'], summary: 'doctor: ready' },
    artifact: `${run.repo.replace(/\/repo$/, '')}/results/7/artifacts/vstatd`, run_dir: `${run.repo.replace(/\/repo$/, '')}/bench/run-1`,
    baseline: '~/workplace/vstatd-team/baseline',
    actions: stage === 'bench' ? [] : [{ action: 'deploy', at: t + 5600, outcome: 'ok', why: '', rc: 0 }, { action: 'replay', at: t + 5800, outcome: 'ok', why: '', rc: 0 }],
    state: {
      dir: '~/.cc1-bench', target: { state: 'known', why: 'booted from the pristine image' }, supply: { voltage_v: 13.5, kl15: 'on', set_by: '李工' },
      pending: stage === 'bench' ? [{ id: '20261102T101500-deploy-3fa1', action: 'deploy', digest, detail: 'vstatd 133240 bytes', requested_at: '2026-11-02T10:15:00Z', requested_by: `vstatd-team ${run.id}`, expired: false }] : [],
      actions: [
        { at: '2026-11-02T10:12:03Z', event: 'supply', voltage_v: 13.5, kl15: 'on', by: '李工' },
        { at: '2026-11-02T10:14:40Z', event: 'target', state: 'known', why: 'booted from the pristine image' },
        { at: '2026-11-02T10:15:00Z', event: 'gate', action: 'deploy', digest, passed: true, why: '' },
        { at: '2026-11-02T10:15:00Z', event: 'request', id: '20261102T101500-deploy-3fa1', action: 'deploy', digest, requested_by: `vstatd-team ${run.id}` },
        ...(stage === 'release' ? [{ at: '2026-11-02T10:16:12Z', event: 'decision', id: '20261102T101500-deploy-3fa1', verdict: 'approved', action: 'deploy', digest, by: '李工', reason: '' },
          { at: '2026-11-02T10:17:40Z', event: 'action', id: '20261102T101500-deploy-3fa1', action: 'deploy', digest, result: 'ok', detail: 'installed' }] : []),
      ],
    },
    console: 'python3 /Users/you/sample-ai-for-software-engineering-on-aws/samples/embedded-development/in-vehicle-dev-server/bench/console.py',
  }
  run.release = stage === 'release' ? {
    at: t + 7200, head: '7c3e9a1f2b', results: `${run.repo.replace(/\/repo$/, '')}/results/rerun`,
    release: { verdict: 'PASS', summary: 'every check passed on 7c3e9a1', reasons: [] },
    checks: ['build', 'static', 'unit', 'size', 'trace', 'runtime-limits', 'logdiff'].map((name) => ({ name, verdict: 'PASS' as const, tier: ['runtime-limits', 'logdiff'].includes(name) ? 'emulation' : name === 'unit' ? 'unit test' : 'n/a', summary: '', reasons: [] })),
    differs: [{ name: 'unit', was: 'FAIL', now: 'PASS' }],
    evidence: '# Evidence page: vstatd 本批\n\n| Check | Verdict | Tier |\n| --- | --- | --- |\n| build | PASS | n/a |\n| logdiff | PASS | emulation |\n\nA commit message an agent wrote: <script>alert(1)</script>\n',
  } : null
  if (stage === 'release') {
    Object.assign(run, { status: 'done', ended_at: t + 7300, sign_block: '', signoff: null })
  } else {
    Object.assign(run, { status: at ? 'running' : 'gating', ended_at: null, sign_block: '运行结束以后才能签字' })
  }
  b.runs = [{ ...b.runs[0], title: run.title, status: run.status, roles_total: run.roles.length, roles_done: run.roles.filter((l) => l.status === 'merged' || l.status === 'done').length,
    tests: { passed: run.tests.passed, failed: run.tests.failed, total: run.tests.total } }]
  return b
}

const SAMPLE = '/Users/you/sample-ai-for-software-engineering-on-aws/samples/embedded-development/in-vehicle-dev-server'

/** GET /readiness at *at*: the knowledge indexed and the build image there, doctor.sh failing, the target off, no baseline. */
export function readinessOf(at: number = raw.at): Readiness {
  return {
    at, team: '车载平台服务 · AI-DLC 团队', error: '',
    items: [
      { key: 'knowledge', label: '知识库来源「vstatd」', ok: true, detail: '14 份文档 · 已索引', command: '', needed: 'start', age_s: null, running: false },
      { key: 'image', label: '构建容器镜像 vstatd-build:amd64', ok: true, detail: '在本机', command: '', needed: 'checks', age_s: 12, running: false },
      { key: 'doctor', label: '台架自检 bench/doctor.sh', ok: false, detail: '没通过：no target image in the volume cc1-images: run bench/build-target.sh（警告：the supply is not set: set it at the operator console (bench/console.py)）',
        command: `${SAMPLE}/bench/build-target.sh`, needed: 'bench', age_s: 340, running: false },
      { key: 'target', label: '台架上的目标 CC-1', ok: false, detail: 'off：台架状态目录里没有目标状态（CC-1 没开机）', command: `${SAMPLE}/bench/cc1.sh start`, needed: 'bench', age_s: null, running: false },
      { key: 'baseline', label: '基线（baseline-result.json）', ok: false, detail: '~/workplace/vstatd-team/baseline',
        command: `部署当前版本以后运行 ${SAMPLE}/bench/cc1.sh replay --kind baseline --out /Users/you/workplace/vstatd-team/baseline`, needed: 'bench', age_s: null, running: false },
      { key: 'console', label: '操作台', ok: null, detail: 'app 看不出操作台开着没有：部署和回放要人在操作台上批准，它要在自己的终端里开着',
        command: `python3 ${SAMPLE}/bench/console.py`, needed: 'bench', age_s: null, running: false },
    ],
  }
}

/** A scorecard (GET /scorecard) with *b*'s run, its figures as the backend would take them from such a run. */
export function scorecardOf(b: Board): Scorecard {
  const r = b.run!
  const row: ScoreRun = {
    id: r.id, title: r.title, status: r.status, started_at: r.started_at, signed: !!r.signoff,
    findings: { fixed: 17, justified: 2, deferred: 3 }, overturned: { ids: ['F-021'], by_person: ['F-021'], by_reviewer: [] },
    times: { triage_s: 1800, first_pass_s: 5400, signoff_s: r.signoff ? r.signoff.at - r.started_at : null },
    build_rounds: 1, caught: { build: 1, static: 1, unit: 1, size: 0, trace: 0 }, logdiff: { differences: 2, unexplained: 0 },
    bench: { approved: 2, refused: 0, reconciled: 0 }, rerun_differs: r.release ? r.release.differs.map((d) => d.name) : null,
  }
  return { runs: [row], total: { runs: 1, findings: row.findings, overturned: 1, build_rounds: 1, caught: row.caught, logdiff: row.logdiff,
    bench: row.bench, rerun_differs: row.rerun_differs?.length ?? null } }
}

export const FIXTURES = {
  running: runningBoard,
  aidlc: () => aidlcBoard(),
  'aidlc-gate': () => aidlcBoard(true),
  finished: finishedBoard,
  started: startedBoard,
  trouble: troubleBoard,
  failed: failedBoard,
  empty: () => emptyBoard(),
  multi: () => multiRunBoard(),
  vstatd: () => vstatdBoard('bench'),
  'vstatd-triage': () => vstatdBoard('triage'),
  'vstatd-release': () => vstatdBoard('release'),
} as const

export type FixtureName = keyof typeof FIXTURES
