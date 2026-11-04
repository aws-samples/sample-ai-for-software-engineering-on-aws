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
 * - readinessOf: GET /readiness on a Mac with the build image but no bench yet;
 * - knowledgeOf, knowledgeTextOf: GET /knowledge and /knowledge/file; backlogOf: GET /backlog; teamOf: GET /team;
 *   flowOf: GET /runs/<id>/flow (交付详情) of the vstatd run that ended with the release check;
 * - auditOf: GET /runs/<id>/audit of that run; benchAuditOf: GET /audit/bench (a baseline replay approved on the board).
 */
import raw from './fixtures/board-running.json'
import type { AuditActor, AuditEntry, AuditTrail, BacklogIndex, BacklogRow, BacklogView, Board, EventData, FileChange, KnowledgeDoc, KnowledgeIndex, KnowledgeText, Lane, Readiness, RunDetail, ScoreRun, Scorecard, TeamEvent, TeamPreview, RunFlow, FlowResult, FlowSegment, Msg, MsgParams, TeamEventKind, TestCase, TriageRow } from '../types'

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
  r.events.push({ seq, at: e.at ?? b.at, kind: e.kind, role: e.role ?? null, text: e.text ?? e.kind, code: e.code ?? null, params: e.params ?? null, from: e.from ?? null, to: e.to ?? null, data: e.data ?? null })
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

/** The backlog (findings-backlog.md) as GET /backlog and the board carry it. */
const BACKLOG: BacklogRow[] = ([
  ["F-001", "cppcheck", "nullPointerRedundantCheck", "src/gateway_client.cpp › GatewayClient::read_records", "Either the condition 'buf==nullptr' is redundant or there is possible null pointer dereference: buf.", "fix"],
  ["F-002", "clang-tidy", "bugprone-unused-return-value", "src/gateway_client.cpp › GatewayClient::connect", "the value returned by this function should not be disregarded; neglecting it may lead to errors (`fcntl`)", "fix"],
  ["F-003", "cppcheck", "resourceLeak", "src/gateway_client.cpp › GatewayClient::connect", "Resource leak: fd", "fix"],
  ["F-004", "clang-tidy", "bugprone-narrowing-conversions", "src/frame_decoder.cpp › parse_record", "narrowing conversion from 'unsigned long' to signed type 'int' is implementation-defined", "fix"],
  ["F-005", "cppcheck", "uninitMemberVar", "src/frame_decoder.cpp › FrameDecoder::FrameDecoder", "Member variable 'FrameDecoder::last_error_' is not initialized in the constructor.", "fix"],
  ["F-006", "clang-tidy", "bugprone-signed-char-misuse", "src/frame_decoder.cpp › hex_nibble", "'signed char' to 'int' conversion; consider casting to 'unsigned char' first.", "fix"],
  ["F-007", "clang-tidy", "bugprone-implicit-widening-of-multiplication-result", "src/frame_decoder.cpp › scale_unsigned", "performing an implicit widening conversion to type 'std::uint64_t' (aka 'unsigned long') of a multiplication performed in type 'std::uint32_t' (aka 'unsigned int')", "fix"],
  ["F-008", "cppcheck", "knownConditionTrueFalse", "src/supervisor.cpp › Supervisor::check", "Condition 'entry.supervised' is always true", "fix"],
  ["F-009", "cppcheck", "variableScope", "src/supervisor.cpp › Supervisor::check", "The scope of the variable 'now' can be reduced.", "later"],
  ["F-010", "clang-tidy", "cppcoreguidelines-init-variables", "src/signal_table.cpp › SignalTable::update", "variable 'status' is not initialized", "fix"],
  ["F-011", "cppcheck", "arrayIndexOutOfBoundsCond", "src/signal_table.cpp › SignalTable::find", "Either the condition 'i>24' is redundant or the array 'entries_[24]' is accessed at index 24, which is out of bounds.", "fix"],
  ["F-012", "clang-tidy", "performance-unnecessary-value-param", "src/signal_table.cpp › SignalTable::update", "the parameter 'path' is copied for each invocation but only used as a const reference; consider making it a const reference", "fix"],
  ["F-013", "cppcheck", "passedByValue", "src/ipc_server.cpp › IpcServer::broadcast", "Function parameter 'line' should be passed by const reference.", "fix"],
  ["F-014", "cppcheck", "resourceLeak", "src/ipc_server.cpp › IpcServer::open_listener", "Resource leak: listen_fd", "fix"],
  ["F-015", "clang-tidy", "bugprone-unused-return-value", "src/ipc_server.cpp › IpcServer::accept_client", "the value returned by this function should not be disregarded; neglecting it may lead to errors (`fcntl`)", "fix"],
  ["F-016", "clang-tidy", "bugprone-unchecked-optional-access", "src/client_session.cpp › ClientSession::handle_sub", "unchecked access to optional value", "fix"],
  ["F-017", "cppcheck", "containerOutOfBounds", "src/client_session.cpp › ClientSession::parse_line", "Either the condition 'words.size()==1' is redundant or words size can be 1. Expression 'words[1]' cause access out of bounds.", "fix"],
  ["F-018", "clang-tidy", "cert-err34-c", "src/client_session.cpp › parse_interval", "'atoi' used to convert a string to an integer value, but function will not report conversion errors; consider using 'strtol' instead", "fix"],
  ["F-019", "cppcheck", "uselessCallsSubstr", "src/client_session.cpp › ClientSession::parse_line", "Ineffective call of function 'substr' because it returns a copy of the object. Use operator= instead.", "later"],
  ["F-020", "clang-tidy", "performance-inefficient-string-concatenation", "src/log_writer.cpp › LogWriter::format", "string concatenation results in allocation of unnecessary temporary strings; consider using 'operator+=' or 'string::append()' instead", "later"],
  ["F-021", "clang-tidy", "cppcoreguidelines-pro-type-member-init", "src/client_session.h › ClientSession::ClientSession", "constructor does not initialize these fields: lines_", "fix"],
  ["F-022", "cppcheck", "shadowVariable", "src/service.cpp › Service::run", "Local variable 'status' shadows outer variable", "later"],
  ["F-023", "clang-tidy", "bugprone-branch-clone", "src/service.cpp › Service::run", "repeated branch body in conditional chain", "fix"],
  ["F-024", "cppcheck", "duplicateCondition", "src/service.cpp › Service::run", "The if condition is the same as the previous if condition", "later"],
  ["F-025", "clang-tidy", "bugprone-empty-catch", "src/service.cpp › Service::run", "empty catch statements hide issues; to handle exceptions appropriately, consider re-throwing, handling, or avoiding catch altogether", "fix"],
  ["F-026", "cppcheck", "unreadVariable", "src/service.cpp › Service::run", "Variable 'loops' is assigned a value that is never used.", "later"],
  ["F-027", "clang-tidy", "cppcoreguidelines-pro-type-member-init", "src/config.cpp › Config::Config", "constructor does not initialize these fields: grace_ms_", "fix"],
  ["F-028", "clang-tidy", "bugprone-unused-return-value", "src/main.cpp › main", "the value returned by this function should not be disregarded; neglecting it may lead to errors (`sd_notify`)", "fix"],
  ["F-029", "cppcheck", "missingOverride", "src/log_writer.h › JournalSink::write", "The function 'write' overrides a function in a base class but is not marked with a 'override' specifier.", "later"],
  ["F-030", "clang-tidy", "bugprone-easily-swappable-parameters", "src/supervisor.cpp › Supervisor::Supervisor", "2 adjacent parameters of 'Supervisor' of similar type ('std::chrono::milliseconds') are easily swapped by mistake", "later"],
] as const).map(([id, tool, check, location, message, label]) => ({ id, tool, check, location, message, label }))

const WORK_ITEM = '修复 vstatd 静态分析待办里标为 fix 的发现，并把信号表的处理从 750 行的 Service::run() 里拆出去。行为不变：在录制的行驶数据上，信号、值、超时和错误都和原来一样；目标上的内存不超过限额。'

/** GET /backlog: the work item and the backlog. */
export function backlogOf(): BacklogIndex {
  return { work_item: WORK_ITEM, rows: clone(BACKLOG), next_id: 'F-031', error: '' }
}

/** The board's 需求清单: the triage proposed at its gate (*approved* false), or approved with the latest static and trace results. */
function backlogView(approved: boolean): BacklogView {
  const special: Record<string, Partial<TriageRow>> = {
    'F-008': { decision: 'justify', cites: ['[VSTATD-IF p.7 §4.2]'], evidence: null, behaviour: null },
    'F-021': { decision: 'defer', evidence: null, behaviour: null },
    'F-018': { evidence: 'unit-test', behaviour: true, cites: ['[VSTATD-IF p.8 §5.2]'], facts: ['IPC-REQUESTS'] },
    'F-016': { evidence: 'unit-test' },
  }
  const answers: Record<string, string> = { 'F-008': 'A 同意说明（评审还会复核引用）', 'F-021': 'A 同意延后', 'F-031': 'A 同意加入本批' }
  const fix = BACKLOG.filter((r) => r.label === 'fix').map((r) => r.id)
  const findings: TriageRow[] = [...fix, 'F-031'].map((id, i) => {
    const f: TriageRow = { id, decision: 'fix', added: id === 'F-031', cites: [], facts: [], evidence: id === 'F-031' ? 'build' : 'static-analysis', behaviour: false,
      answer: null, static: null, trace: null, ...special[id] }
    if (!approved) return f
    const traced = f.decision === 'fix' || f.decision === 'justify'
    return { ...f, answer: answers[id] ?? null,
      static: f.added ? 'added under TR §4.4 (found by 工作项：拆分 Service::run())' : f.decision === 'fix' ? 'gone' : 'reported',
      trace: traced && f.decision === 'fix' ? [`${(0x3a1f00 + i * 7919).toString(16)}c0de${i % 10}`.slice(0, 12)] : [] }
  })
  return { rows: clone(BACKLOG), next_id: 'F-031', triage: { state: approved ? 'approved' : 'proposed', approved: approved ? { by: '李工', at: '2026-11-02T09:12:00Z' } : null, findings } }
}

/** The vstatd run's event log up to *stage*: triage to its gate, then the build and checks, then the bench and the release check. */
function vstatdEvents(id: string, title: string, t: number, stage: 'triage' | 'bench' | 'release'): TeamEvent[] {
  // each with the code and params the backend gives it (messages.py), so that the English board says it too
  type Row = [number, TeamEventKind, string | null, string, string | null, string | null, EventData | null, Msg | null]
  const ev = (dt: number, kind: TeamEventKind, role: string | null, text: string, from: string | null = null, to: string | null = null, data: EventData | null = null, msg: Msg | null = null): Row =>
    [dt, kind, role, text, from, to, data, msg]
  const m = (code: string, params: MsgParams | null = null): Msg => ({ code, params })
  const triage: Row[] = [
    ev(0, 'run', null, `运行开始：${title}`, null, null, null, m('run.start', { title })),
    ev(20, 'spawned', 'triage', '分诊开工：读 findings-backlog.md 和接口规范', null, null, null, m('spawned.dispatch', { r_role: 'triage', task: '读 findings-backlog.md 和接口规范' })),
    ev(1480, 'committed', 'triage', '分诊提交 4b7e1d2：F-001..F-030 定了修、说明或延后，按 TR §4.4 加 F-031', null, null, null, m('committed', { r_role: 'triage', subject: '4b7e1d2 triage: F-001..F-030 decided, F-031 added under TR §4.4' })),
    ev(1490, 'done', 'triage', '分诊完成：22 个 fix、3 个 justify、5 个 defer，加 F-031 重构', null, null, null, m('plan.triage', { r_role: 'triage', n: 2, listed: 28 })),
    ev(1510, 'gate', 'triage', '分诊交给人：F-008 说明、F-021 延后要你决定', 'triage', 'person', null, m('gate.wait', { g_gate: 'triage' })),
  ]
  const build: Row[] = [
    ev(1800, 'approved', 'triage', '人批准了分诊（李工）', 'person', 'triage', null, m('approved', { g_gate: 'triage' })),
    ev(1805, 'handoff', 'architect', '分诊交给架构师', 'triage', 'architect', { carry: '分诊' }, m('handoff', { r_from: 'triage', outs: ['triage.json', 'triage.md'], r_role: 'architect' })),
    ev(2600, 'done', 'architect', '架构师完成：Service::run() 拆成 4 个函数，两个开发按源文件分工', null, null, null, m('done', { r_role: 'architect', summary: 'Service::run() → 4 functions; two developers split by source file' })),
    ev(2610, 'gate', 'architect', '开工方案交给人', 'architect', 'person', null, m('gate.wait', { g_gate: 'architect' })),
    ev(2700, 'approved', 'architect', '人批准了开工', 'person', 'architect', null, m('approved', { g_gate: 'architect' })),
    ev(2705, 'handoff', 'tester', '重构方案交给测试', 'architect', 'tester', { carry: '重构方案' }, m('handoff', { r_from: 'architect', outs: ['refactor-plan.md'], r_role: 'tester' })),
    ev(3000, 'tests', null, '测试先行：3 个新测试在基线提交上都失败（应当如此）', null, null, { passed: 0, total: 3 }, m('tests.first_ok', { r_role: 'tester' })),
    ev(3305, 'handoff', 'dev-fix', '测试交给开发 · 修复', 'tester', 'dev-fix', { carry: '测试' }, m('handoff', { r_from: 'tester', outs: ['tests.md'], r_role: 'dev-fix' })),
    ev(3305, 'handoff', 'dev-refactor', '测试交给开发 · 重构', 'tester', 'dev-refactor', { carry: '测试' }, m('handoff', { r_from: 'tester', outs: ['tests.md'], r_role: 'dev-refactor' })),
    ev(3620, 'committed', 'dev-fix', '开发 · 修复提交 3c9a1f0：F-003: close fd on connect failure', null, null, null, m('committed', { r_role: 'dev-fix', subject: '3c9a1f0 F-003: close fd on connect failure' })),
    ev(4100, 'committed', 'dev-refactor', '开发 · 重构提交 5f6b2e9：F-031: move signal table handling out of Service::run()', null, null, null, m('committed', { r_role: 'dev-refactor', subject: '5f6b2e9 F-031: move signal table handling out of Service::run()' })),
    ev(4200, 'tests', null, '检查第 2 轮 3/5：static、unit FAIL', null, null, { passed: 3, total: 5, phase: 'before_bench' }, m('tests.score', { passed: 3, total: 5 })),
    ev(4201, 'bounce', 'dev-fix', '检查第 2 轮 static FAIL（F-018 还在报）、unit FAIL，退回开发 · 修复', 'tests', 'dev-fix', { cases: ['static', 'unit'] }, m('bounce.checks', { cases: ['static', 'unit'], r_role: 'dev-fix' })),
    ev(4210, 'spawned', 'dev-fix', '开发 · 修复第 2 轮：修 static、unit', null, null, null, m('spawned.round', { r_role: 'dev-fix', n: 2, label: 'static, unit' })),
    ev(5120, 'committed', 'dev-fix', '开发 · 修复提交 d8e3a71：F-018: strtol with a range check in parse_interval', null, null, null, m('committed', { r_role: 'dev-fix', subject: 'd8e3a71 F-018: strtol with a range check in parse_interval' })),
    ev(5400, 'tests', null, '检查第 3 轮 5/5：build、static、unit、size、trace 都 PASS', null, null, { passed: 5, total: 5, phase: 'before_bench' }, m('tests.score', { passed: 5, total: 5, green: true })),
    ev(5410, 'handoff', 'reviewer', '改动交给评审', 'dev-fix', 'reviewer', { carry: '改动' }, m('handoff', { r_from: 'dev-fix', outs: [], r_role: 'reviewer' })),
    ev(5800, 'done', 'reviewer', '评审：可以交付', null, null, null, m('done', { r_role: 'reviewer', summary: 'ready to deliver' })),
    ev(5460, 'bench', null, '台架自检 doctor.sh 通过', null, null, null, m('bench.go', { n: 1 })),
    ev(5890, 'bench', null, '向操作台请求部署：vstatd 133240 bytes，摘要 bc93723c5a1f', null, null, null, m('bench.deploy', { artifact: 'vstatd' })),
  ]
  const release: Row[] = [
    ev(5960, 'bench', null, '看板批准部署（李工）'),
    ev(5990, 'bench', null, '部署结果 ok：installed', null, null, null, m('bench.replay')),
    ev(6160, 'bench', null, '操作台批准回放，回放 drive-01', null, null, null, m('bench.replayed', { run_dir: 'bench/run-1' })),
    ev(6800, 'tests', null, '台架之后的检查 2/2：logdiff、runtime-limits PASS', null, null, { passed: 2, total: 2, phase: 'after_bench' }, m('tests.after', { passed: 2, total: 2 })),
    ev(7300, 'tests', null, '独立重跑 7/7：release.sh PASS，可以签字', null, null, { passed: 7, total: 7, phase: 'rerun' }, m('tests.rerun', { verdict: 'PASS' })),
  ]
  const rows = [...triage, ...(stage === 'triage' ? [] : build), ...(stage === 'release' ? release : [])].sort((a, b) => a[0] - b[0])
  return rows.map(([dt, kind, role, text, from, to, data, msg], i) => ({ seq: i + 1, at: t + dt, kind, role, text, code: msg?.code ?? null, params: msg?.params ?? null, from, to, data }))
}

const CHECK = (name: string, verdict: 'PASS' | 'FAIL' | 'BLOCKED', tier: string, owner: string | null, message: string | null, ms: number): TestCase => ({
  id: name, ac: name, name: `${name}.sh`, file: '', status: verdict === 'PASS' ? 'pass' : verdict === 'FAIL' ? 'fail' : 'blocked', verdict, tier, owner, ms, message,
})

/** title_en, stage_en, gate_label_en of the vstatd team's roles (team-vstatd.json). */
const VSTATD_EN: Record<string, [string, string, string]> = {
  triage: ['Triage', 'Triage · fix, explain or defer', 'Triage'], architect: ['Architect', 'Refactor plan · division of work', 'Start'],
  tester: ['Tester', 'Tests first', ''], 'dev-fix': ['Developer · fix', 'Fix', ''], 'dev-refactor': ['Developer · refactor', 'Refactor', ''], reviewer: ['Reviewer', 'Review', ''],
}

/** The vstatd team (team-vstatd.json): at its triage gate, held at the bench, or ended with the release check. */
export function vstatdBoard(stage: 'triage' | 'bench' | 'release' = 'bench'): Board {
  const b = runningBoard()
  const run = b.run!
  const t = run.started_at
  const tpl = run.roles.find((r) => r.key === 'backend')!
  const at = (stage === 'triage' ? 0 : stage === 'bench' ? 1 : 2)
  const mk = (key: string, title: string, icon: string, phase: string, stage_: string, deps: string[], status: Lane['status'], member: string, extra: Partial<Lane> = {}): Lane => ({
    ...clone(tpl), key, title, title_en: VSTATD_EN[key]?.[0] ?? '', icon, phase, stage: stage_, stage_en: VSTATD_EN[key]?.[1] ?? '', depends_on: deps, status, gate: null, gate_label: '',
    gate_label_en: VSTATD_EN[key]?.[2] ?? '', kinds: ['work'], attempt: 1,
    aidlc_agent: member, member, writable: [`src/${key}.*`], violations: [], mission: '', summary: null, agent: null, owns_tests: [], questions: [], answers: [], ...extra,
  })
  const after = (s: Lane['status']): Lane['status'] => (at ? s : 'waiting')
  const questions = [
    { id: 'F-008', q: 'F-008 分诊建议说明为误报或无害、不修（待办标的是 fix）：src/supervisor.cpp › Supervisor::check', options: [{ key: 'A', text: '同意说明（评审还会复核引用）' }, { key: 'B', text: '不同意：本批修复（退回分诊补齐证据和行为）' }],
      recommend: 'A', why: '条件实现宽限期，分析器看不到回调里设的标志', cites: ['[VSTATD-IF p.7 §4.2]'], decision: 'justify' },
    { id: 'F-021', q: 'F-021 分诊建议延后（待办标的是 fix）：src/ipc_server.cpp › IpcServer::accept', options: [{ key: 'A', text: '同意延后' }, { key: 'B', text: '不同意：本批修复（退回分诊补齐证据和行为）' }],
      recommend: 'A', why: '改法要动 IPC 的行为；什么时候再处理：下一批', cites: [], decision: 'defer' },
  ]
  // what each role changed in reference-project, and its commits citing the findings (TR: every fix commit cites its ID)
  const wt = (key: string): Partial<Lane> => ({ worktree: `${run.repo.replace(/\/repo$/, '')}/wt/${key}`, branch: `team/${run.id}/${key}`, session: `vstatd-team-${run.id}-${key}` })
  const F = (path: string, added: number, removed: number, status: FileChange['status'] = 'M'): FileChange => ({ path, added, removed, status })
  const C = (sha: string, subject: string, dt: number) => ({ sha, subject, at: t + dt })
  const work = (files: FileChange[], commits: ReturnType<typeof C>[], done: number): Partial<Lane> =>
    ({ files, commits, lines: { added: files.reduce((n, f) => n + f.added, 0), removed: files.reduce((n, f) => n + f.removed, 0) }, done_at: t + done })
  const WORK: Record<string, Partial<Lane>> = {
    triage: work([F('docs/aidlc/triage.json', 412, 0, 'A'), F('docs/aidlc/triage.md', 186, 0, 'A')],
      [C('4b7e1d2', 'triage: F-001..F-030 decided, F-031 added under TR §4.4', 1480)], 1490),
    architect: work([F('docs/aidlc/refactor-plan.md', 138, 0, 'A')], [C('9d02c6e', 'F-031: plan the Service::run() split and who edits which file', 2590)], 2600),
    tester: work([F('tests/test_gateway_client.cpp', 96, 0, 'A'), F('tests/test_client_session.cpp', 54, 3), F('tests/test_signal_table.cpp', 71, 0), F('tests/CMakeLists.txt', 4, 1)],
      [C('c41a8f3', 'F-003 F-018: tests that fail on the baseline', 3180), C('e5f9b20', 'F-031: characterization test for the signal table', 3290)], 3300),
    'dev-fix': work([F('src/gateway_client.cpp', 18, 6), F('src/frame_decoder.cpp', 22, 9), F('src/client_session.cpp', 31, 12), F('src/ipc_server.cpp', 9, 3)],
      [C('3c9a1f0', 'F-003: close fd on connect failure', 3620), C('7a1e44b', 'F-004 F-005: no narrowing in parse_record, init last_error_', 3900),
        C('b20d9c5', 'F-016: check the optional before handle_sub reads it', 4180), C('d8e3a71', 'F-018: strtol with a range check in parse_interval', 5120)], 5200),
    'dev-refactor': work([F('src/service.cpp', 38, 412), F('src/signal_table.cpp', 164, 12), F('src/signal_table.h', 21, 2)],
      [C('5f6b2e9', 'F-031: move signal table handling out of Service::run()', 4100), C('a93c07d', 'F-010 F-012: init status, path by const ref in SignalTable::update', 4420)], 4500),
    reviewer: { files: [], commits: [], lines: { added: 0, removed: 0 }, done_at: t + 5800 },
  }
  const did = (key: string): Partial<Lane> => ({ ...wt(key), ...(key === 'triage' || at ? WORK[key] : { files: [], commits: [], lines: { added: 0, removed: 0 }, done_at: null }) })
  run.roles = [
    mk('triage', '分诊', 'scope', 'inception', '分诊 · 修、说明或延后', [], 'merged', 'aidlc-developer-agent',
      { gate: at ? 'approved' : 'pending', gate_label: '分诊', writable: ['docs/aidlc/triage.json', 'docs/aidlc/triage.md'], questions: at ? [] : questions, ...did('triage') }),
    mk('architect', '架构师', 'architect', 'inception', '重构方案 · 分工', ['triage'], after('merged'), 'aidlc-architect-agent',
      { gate: at ? 'approved' : null, gate_label: '开工', writable: ['docs/aidlc/refactor-plan.md'], ...did('architect') }),
    mk('tester', '测试', 'tester', 'construction', '测试先行', ['architect'], after('merged'), 'aidlc-quality-agent', { writable: ['tests/**'], tests_first: at ? 'passed' : null, ...did('tester') }),
    mk('dev-fix', '开发 · 修复', 'backend', 'construction', '修复', ['tester'], after('merged'), 'aidlc-developer-agent',
      { attempt: at ? 2 : 1, kinds: at ? ['work', 'fix'] : ['work'], writable: ['src/gateway_client.*', 'src/frame_decoder.*', 'src/client_session.*', 'src/ipc_server.*', 'src/supervisor.*', 'src/config.*', 'src/main.cpp'], ...did('dev-fix') }),
    mk('dev-refactor', '开发 · 重构', 'frontend', 'construction', '重构', ['tester'], after('merged'), 'aidlc-developer-agent',
      { writable: ['src/service.*', 'src/signal_table.*'], ...did('dev-refactor') }),
    mk('reviewer', '评审', 'reviewer', 'review', '评审', ['dev-fix', 'dev-refactor'], at ? 'done' : 'waiting', 'aidlc-architecture-reviewer-agent', { writable: [], summary: at ? '可以交付' : null, ...did('reviewer') }),
  ]
  run.ownership = { roles: Object.fromEntries(run.roles.filter((l) => l.writable.length).map((l) => [l.key, l.writable])), test_areas: {} }
  run.delivery = { name: '', kind: '修复', size: '中', line: '内部系统', why: '', confirmed: false }
  run.issue = { id: 'VSTATD-112', kind: '缺陷', reporter: '车载平台组', created_at: t }
  run.edges = run.roles.flatMap((r) => r.depends_on.map((d) => [d, r.key] as [string, string]))
  run.team = { name: 'AIDLC-Embedded团队', orchestrator: 'vstatd-team' }
  run.title = '修复 vstatd 静态分析待办里标为 fix 的发现'
  run.requirement = '修复 vstatd 静态分析待办里标为 fix 的发现，并把信号表的处理从 750 行的 Service::run() 里拆出去。行为不变：在录制的行驶数据上，信号、值、超时和错误都和原来一样；目标上的内存不超过限额。'
  run.knowledge = { source: { name: 'vstatd', present: true, items: 14, status: 'synced', files_total: 14, files_done: 14, path: '~/workplace/vstatd/knowledge' }, hits: [],
    docs: [{ key: 'VSTATD-IF', title: 'vstatd 接口规范', path: 'vstatd-interface.md', cites: at ? 9 : 3 }, { key: 'CC1-PN', title: 'CC-1 平台说明', path: 'cc1-platform-notes.md', cites: at ? 2 : 0 },
      { key: 'TR', title: '团队规则', path: 'team-rules.md', cites: at ? 6 : 4 }] }
  run.merges = []
  run.backlog = backlogView(at > 0)
  run.events = vstatdEvents(run.id, run.title, t, stage)
  b.at = t + (stage === 'triage' ? 1520 : stage === 'bench' ? 5900 : 7400) // the snapshot is taken after its last event
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
  run.wall_s = (run.ended_at ?? b.at) - t
  run.serial_s = run.wall_s + (at ? 990 : 0) // the two developers worked side by side for 990 s
  b.runs = [{ ...b.runs[0], title: run.title, status: run.status, roles_total: run.roles.length, roles_done: run.roles.filter((l) => l.status === 'merged' || l.status === 'done').length,
    tests: { passed: run.tests.passed, failed: run.tests.failed, total: run.tests.total } }]
  return b
}

const SAMPLE = '/Users/you/sample-ai-for-software-engineering-on-aws/samples/embedded-development/in-vehicle-dev-server'

/** GET /readiness at *at*: the knowledge indexed and the build image there, doctor.sh failing, the target off, no baseline. */
export function readinessOf(at: number = raw.at): Readiness {
  return {
    at, team: 'AIDLC-Embedded团队', error: '',
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
    pending: [
      { id: '20261103T094307-deploy-ac78', action: 'deploy', digest: 'bc93723c0cb02e054acc5f25705b61a4443435c168351ec5914d0729bdce4d98',
        requested_by: 'bench tools', left_s: 168,
        approve: `python3 ${SAMPLE}/bench/console.py approve 20261103T094307-deploy-ac78 --digest bc93723c0cb0`,
        refuse: `python3 ${SAMPLE}/bench/console.py refuse 20261103T094307-deploy-ac78 --reason <原因>` },
    ],
  }
}

const KB_DOC = (path: string, title: string, key: string | null, desc: string, counts: [string, number][], text = true): KnowledgeDoc => ({
  path, title, key, desc, counts: counts.map(([label, n]) => ({ label, n })), present: true, text, rendered_from: text ? null : 'vstatd-interface.md',
})

/** GET /knowledge: the scenario's documents (figures as the backend counts them from the files) and the source indexed. */
export function knowledgeOf(): KnowledgeIndex {
  return {
    error: '', source: { name: 'vstatd', present: true, items: 14, status: 'synced', files_total: 14, files_done: 14, path: '~/workplace/vstatd/knowledge' },
    docs: [
      KB_DOC('vstatd-interface.md', 'vstatd 接口规范', 'VSTATD-IF', '网关报文、信号、解码、监督、IPC、错误、运行日志和启动；引用要写页码', [['节', 41], ['页', 11]]),
      KB_DOC('vstatd-interface.pdf', 'vstatd 接口规范（PDF）', null, '上面那份规范的排版版本，分页相同；这里只看 Markdown 版', [], false),
      KB_DOC('cc1-platform-notes.md', 'CC-1 平台说明', 'CC1-PN', '目标、仿真的 CC-1、资源限额、启动顺序、日志格式、工具链和台架', [['节', 23]]),
      KB_DOC('team-rules.md', '团队规则', 'TR', 'C++ 规则、构建选项、分析器设置、分诊规则、修复轮数和完成的定义', [['节', 22]]),
      KB_DOC('findings-backlog.md', '静态分析待办', null, '当前版本的静态分析发现，标 fix 的进本批，标 later 的留在待办', [['发现', 30], ['fix', 22], ['later', 8]]),
      KB_DOC('cc1-gateway.dbc', 'CAN 数据库（DBC）', null, '报文、信号、周期和 SNA 值；规范 §3.1 的表从这里来', [['报文', 9], ['信号', 24]]),
      KB_DOC('vss-mapping.yaml', 'VSS 信号映射', null, '每个发布的信号路径（COVESA VSS v6.1 名字）对应哪个 CAN 信号', [['信号路径', 24]]),
      KB_DOC('facts/signals.yaml', '事实条目 · 信号', null, '从规范里摘出的每个信号，带页和节', [['条目', 24]]),
      KB_DOC('facts/messages.yaml', '事实条目 · 报文', null, '从规范里摘出的每个报文，带页和节', [['条目', 9]]),
      KB_DOC('facts/rules.yaml', '事实条目 · 规则', null, '从规范里摘出的每条规则，带页和节', [['条目', 39]]),
    ],
  }
}

/** GET /knowledge/file for *path*: a short stand-in text (with markup that must show as text). */
export function knowledgeTextOf(path: string): KnowledgeText {
  const doc = knowledgeOf().docs.find((d) => d.path === path)
  const text = `# ${doc?.title ?? path}\n\n> 预览里的替身文字；app 里是 ${path} 的全文。\n\n<b>不渲染</b> **也不渲染 Markdown**\n`
  return { path, title: doc?.title ?? path, text, size: text.length }
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

/** GET /team: the vstatd team as team-vstatd.json has it; *missing* templates have no file in ~/.kiro/agents. */
export function teamOf(missing: string[] = []): TeamPreview {
  const role = (key: string, title: string, icon: string, template: string, aidlc_agent: string, phase: string, writable: string, gate = '') =>
    ({ key, title, icon, template, aidlc_agent, phase, writable, gate })
  const roles = [
    role('triage', '分诊', 'scope', 'embedded-developer-agent', 'aidlc-developer-agent', 'inception', 'docs/aidlc/triage.json、docs/aidlc/triage.md', '分诊'),
    role('architect', '架构师', 'architect', 'embedded-architect-agent', 'aidlc-architect-agent', 'inception', 'docs/aidlc/refactor-plan.md、docs/aidlc/work-split.json、docs/aidlc/plan.json', '开工'),
    role('tester', '测试', 'tester', 'embedded-quality-agent', 'aidlc-quality-agent', 'construction', 'tests/**、docs/aidlc/tests.md'),
    role('dev-fix', '开发 · 修复', 'backend', 'embedded-developer-agent', 'aidlc-developer-agent', 'construction', '按架构师的分工'),
    role('dev-refactor', '开发 · 重构', 'frontend', 'embedded-developer-agent', 'aidlc-developer-agent', 'construction', '按架构师的分工'),
    role('reviewer', '评审', 'reviewer', 'embedded-architecture-reviewer-agent', 'aidlc-architecture-reviewer-agent', 'review', '只读'),
  ]
  const check = (name: string, when: string, owner: string | null, max_rounds = 2) => ({ name, when, owner, max_rounds })
  return {
    name: 'AIDLC-Embedded团队', roles, error: '',
    checks: [check('build', 'before_bench', 'dev-fix', 3), check('static', 'before_bench', 'dev-fix'), check('unit', 'before_bench', 'dev-fix'),
      check('size', 'before_bench', 'dev-refactor'), check('trace', 'before_bench', 'dev-fix'), check('runtime-limits', 'after_bench', 'dev-fix'),
      check('logdiff', 'after_bench', 'dev-fix'), check('release', 'release', null)],
    templates: [...new Set(roles.map((r) => r.template))].sort().map((name) => ({ name, present: !missing.includes(name) })),
    knowledge: { name: 'vstatd', present: true, items: 14, status: 'synced', files_total: 14, files_done: 14, path: '~/workplace/vstatd/knowledge' },
  }
}

/** GET /runs/<id>/flow: the vstatd run (vstatdBoard('release')) from its requirement to the sign-off it waits for. */
export function flowOf(b: Board = vstatdBoard('release')): RunFlow {
  const r = b.run!
  const RESULT: Record<string, FlowResult> = { 批准: 'approved', 不过: 'fail', 通过: 'pass', 不同: 'differs' }
  const said = (label: string, role: string | null): Pick<FlowSegment, 'code' | 'params'> => {
    if (label.startsWith('等人批准')) return { code: 'flow.gate', params: { g_gate: role } }
    if (label.startsWith('操作台')) return { code: 'flow.console', params: { action: label.split(' · ')[1] } }
    if (label.startsWith('检查 第')) return { code: 'flow.checks', params: { n: Number(/\d+/.exec(label)![0]) } }
    if (label === '台架之后的检查') return { code: 'flow.after_bench', params: null }
    if (label === '独立重跑全部检查') return { code: 'flow.rerun', params: null }
    const round = /^.+ · 第 (\d+) 轮$/.exec(label)
    if (round) return { code: 'flow.agent.round', params: { r_role: role, n: Number(round[1]) } }
    return { code: 'flow.agent', params: { r_role: role, label: label.split(' · ').pop() } }
  }
  const seg = (kind: FlowSegment['kind'], from: number, to: number, label: string, role: string | null = null, result: string | null = null, open = false): FlowSegment =>
    ({ kind, from, to, role, label, ...said(label, role), result, result_code: result ? RESULT[result] : null, open })
  const segments = [
    seg('agent', 20, 1500, '分诊 · 第 1 轮', 'triage'), seg('gate', 1510, 1800, '等人批准 · 分诊', 'triage', '批准'),
    seg('agent', 1810, 2600, '架构师 · 第 1 轮', 'architect'), seg('gate', 2610, 2700, '等人批准 · 开工', 'architect', '批准'),
    seg('agent', 2710, 3300, '测试 · 第 1 轮', 'tester'), seg('agent', 3310, 4300, '开发 · 修复 · 第 1 轮', 'dev-fix'),
    seg('agent', 3315, 4500, '开发 · 重构 · 第 1 轮', 'dev-refactor'), seg('checks', 4520, 4900, '检查 第 1 轮', null, '不过'),
    seg('agent', 4910, 5200, '开发 · 修复 · 修复 build', 'dev-fix'), seg('checks', 5210, 5400, '检查 第 2 轮', null, '通过'),
    seg('agent', 5410, 5800, '评审 · 第 1 轮', 'reviewer'), seg('console', 5900, 5960, '操作台 · deploy', null, '批准'),
    seg('console', 6100, 6160, '操作台 · replay', null, '批准'), seg('checks', 6600, 6800, '台架之后的检查', null, '通过'),
    seg('rerun', 6810, 7300, '独立重跑全部检查', null, '不同'),
  ]
  return {
    run: r.id, title: r.title, status: r.status, started_at: r.started_at, end: 7300, live: false, signed: !!r.signoff,
    segments,
    marks: [{ at: 1800, kind: 'approved', role: 'triage', label: '人批准了分诊', code: 'approved', params: { g_gate: 'triage' } },
      { at: 2700, kind: 'approved', role: 'architect', label: '人批准了开工', code: 'approved', params: { g_gate: 'architect' } },
      { at: 4900, kind: 'check_fail', role: null, label: '检查不过：build', code: 'flow.check_fail', params: { checks: ['build'] } },
      { at: 4901, kind: 'bounce', role: 'dev-fix', label: 'build 失败，打回开发 · 修复', code: 'bounce.tests', params: { cases: ['build'], r_role: 'dev-fix' } }],
    roles: r.roles.map((l) => ({ key: l.key, title: l.title, title_en: l.title_en, gate_label: l.gate_label, gate_label_en: l.gate_label_en, icon: l.icon })),
    totals: { elapsed_s: 7300, agent_s: 4705, person_s: 510, gate_s: 390, console_s: 120, check_s: 1260, credits: 18.4, check_rounds: 3, send_backs: 1 },
  }
}

const BOARD_BY = 'Kiro Crew 看板（you，vstatd-team）'
const audit = (t0: number, rows: [number, AuditActor, string, string, string, string?][]): AuditEntry[] =>
  rows.map(([dt, actor, who, step, what, evidence = '']) => ({ at: t0 + dt, iso: new Date((t0 + dt) * 1000).toISOString().slice(0, 19) + 'Z', seq: null, actor, who, step, what, evidence }))

/** GET /runs/<id>/audit: the vstatd run (vstatdBoard('release')), every decision and action as audit.py records them. */
export function auditOf(b: Board = vstatdBoard('release')): AuditTrail {
  const r = b.run!
  return {
    run: r.id, title: r.title, requirement: r.requirement, team: r.team.name, base: r.base, status: r.status,
    entries: audit(r.started_at, [
      [0, 'person', '负责人', '', `运行开始：${r.title}`],
      [20, 'agent', '分诊', 'triage', '分诊开工'],
      [1490, 'agent', '分诊', 'triage', '分诊完成：22 个 fix、3 个 justify、5 个 defer，加 F-031 重构', 'F-031 VSTATD-IF-4.2'],
      [1500, 'agent', '分诊', 'triage', '分诊的分诊：5 件要人决定，25 条照分诊做（见分诊文档）'],
      [1510, 'app', 'app', 'gate-triage', '关卡打开，等人批准：分诊'],
      [1800, 'person', '王经理', 'gate-triage', '分诊批准（王经理），记在 triage.json（sha256 6f1e0c2a9b3d）', 'sha256 6f1e0c2a9b3d Q1=A；Q2=A；Q3=A；Q4=A；Q5=A'],
      [2600, 'agent', '架构师', 'architect', '架构师完成：Service::run() 拆成 4 个函数，两个开发按源文件分工'],
      [2610, 'app', 'app', 'gate-start', '关卡打开，等人批准：开工'],
      [2700, 'person', '负责人', 'gate-start', '人批准了开工', 'Q1=B（与建议不同）'],
      [3300, 'app', 'app', 'tests-first', '测试的新测试在需求提交上都失败了，开发开工', 'T-F003 T-F012'],
      [4300, 'app', 'app', 'dev', '开发 · 修复的分支合入运行分支', 'commit 3c9a1f07b2e4'],
      [4900, 'app', 'app', 'before', '测试 4/5', 'build=FAIL static=PASS unit=PASS size=PASS trace=PASS'],
      [4901, 'app', 'app', 'before', 'build 失败，打回开发 · 修复'],
      [5400, 'app', 'app', 'before', '测试 5/5：全绿', 'build=PASS static=PASS unit=PASS size=PASS trace=PASS'],
      [5800, 'agent', '评审', 'review', '审查：可以交付'],
      [5890, 'app', 'app', 'bench', '向操作台请求部署：vstatd, 133240 bytes', '请求 20261103T094046-deploy-2570 摘要 bc93723c0cb0'],
      [5960, 'person', BOARD_BY, 'bench', '看板批准部署', '请求 20261103T094046-deploy-2570 摘要 bc93723c0cb0'],
      [5990, 'bench', '台架', 'bench', '部署结果 ok：installed', '请求 20261103T094046-deploy-2570 摘要 bc93723c0cb0'],
      [6160, 'person', 'you@mac (/dev/ttys003)', 'bench', '操作台批准回放', '请求 20261103T101353-replay-0f40 摘要 bc93723c0cb0'],
      [6800, 'app', 'app', 'after', '台架之后的检查 2/2', 'logdiff=PASS runtime-limits=PASS'],
      [7300, 'app', 'app', 'rerun', '独立重跑：release.sh PASS，和上一轮结果不同的检查：size', 'build=PASS static=PASS size=FAIL'],
    ]),
  }
}

/** GET /audit/bench: the baseline replay, requested at the console and approved on the board. */
export function benchAuditOf(at: number = raw.at): AuditTrail {
  return {
    run: '', title: '台架动作（不属于任何运行）', requirement: '', team: '', base: '', status: '',
    entries: audit(at - 3600, [
      [0, 'bench', 'bench tools', 'bench', '向操作台请求回放', '请求 20261103T101353-replay-0f40 摘要 bc93723c0cb0'],
      [76, 'person', BOARD_BY, 'bench', '看板批准回放', '请求 20261103T101353-replay-0f40 摘要 bc93723c0cb0'],
      [88, 'bench', '台架', 'bench', '回放结果 ok：replay drive-01 to ~/workplace/vstatd-team/baseline', '请求 20261103T101353-replay-0f40 摘要 bc93723c0cb0'],
    ]),
  }
}
