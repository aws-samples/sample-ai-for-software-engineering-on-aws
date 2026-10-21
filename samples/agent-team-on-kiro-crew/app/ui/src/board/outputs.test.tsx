import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, test } from 'vitest'
import type { FileView, OutputAttempt, RoleOutput, SiteStatus } from '../types'
import { apiCalls, setApiRoutes } from '../test/stubs/app-sdk'
import { clone, runningBoard } from '../test/fixtures'
import { TeamPage } from '../main'
import { lineKind, sortFiles, tabsFor } from './Outputs'

const API = '/api/apps/aidlc-team'
const BOARD = `GET ${API}/board*`

const attempt = (over: Partial<OutputAttempt> = {}): OutputAttempt => ({
  n: 1, kind: 'work', label: '', agent: 'f84496b48dc1536a', started: 1000, ended: 1041, credits: 2.6, error: null,
  summary: '写好了 21 条验收标准', reply: 'DONE: 写好了 21 条验收标准\n\n- AC-1 首页列出活动', task: '[aidlc-team run=r1006a role=pm]\n\n把 README 里的需求写成验收标准',
  calls: [{ at: 1003, tool: 'Reading', kind: 'read', detail: 'README.md' }, { at: 1020, tool: 'Creating', kind: 'edit', detail: 'acceptance.md' }],
  live: false, ...over,
})

const output = (role: string, over: Partial<RoleOutput> = {}): RoleOutput => ({
  run: 'r1006a', role, title: role, emoji: '', status: 'merged', branch: `team/r1006a/${role}`, folder: `/w/runs/r1006a/wt/${role}`, base: '5e1f0aa', head: 'd5d735a',
  writable: ['docs/product/**'], ended: false, attempts: [attempt()],
  files: [
    { path: 'docs/product/notes.md', added: 3, removed: 0, status: 'A', output: false, owner: role },
    { path: 'docs/product/acceptance.md', added: 42, removed: 0, status: 'A', output: true, owner: role },
  ],
  ...over,
})

const fileView = (path: string, view: 'content' | 'diff'): FileView => ({
  path, view, lang: view === 'diff' ? 'diff' : path.endsWith('.md') ? 'markdown' : 'javascript', binary: false, size: 40, truncated: false,
  text: view === 'diff' ? `diff --git a/${path} b/${path}\n@@ -0,0 +1,2 @@\n+# 验收标准\n+AC-1 首页列出活动\n` : path.endsWith('.md') ? '# 验收标准\nAC-1 首页列出活动\n' : 'export const x = 1\nexport const y = 2\n',
})

function routes(extra: Record<string, (body: unknown, path: string) => unknown> = {}, board = runningBoard()) {
  setApiRoutes({
    [BOARD]: () => clone(board),
    [`GET ${API}/runs/r1006a/roles/pm`]: () => output('pm', { title: '产品经理' }),
    [`GET ${API}/runs/r1006a/roles/architect`]: () => output('architect', { title: '架构师', files: [] }),
    [`GET ${API}/runs/r1006a/roles/pm/file*`]: (_b, path) => {
      const q = new URLSearchParams(path.split('?')[1])
      return fileView(q.get('path')!, q.get('view') as 'content' | 'diff')
    },
    ...extra,
  })
}

const laneOf = (key: string) => screen.getAllByTestId('kt-lane').find((l) => l.dataset.role === key)!

describe('每一步的产出', () => {
  test('a role card opens its deliverables: the promised file first, rendered; its diff on demand', async () => {
    const user = userEvent.setup()
    routes()
    render(<TeamPage pollMs={60_000} />)
    await screen.findAllByTestId('kt-lane')
    await user.click(within(laneOf('pm')).getByRole('button', { name: /看产出/ }))
    const drawer = await screen.findByRole('dialog', { name: '产品经理的产出' })
    const list = await within(drawer).findByText('约定它交的')
    expect(list.nextElementSibling).toHaveTextContent('docs/product/acceptance.md')
    expect(await within(drawer).findByTestId('markdown')).toHaveTextContent('# 验收标准 AC-1 首页列出活动')
    await user.click(within(drawer).getByRole('button', { name: '改动' }))
    await waitFor(() => expect(apiCalls.some((c) => c.path.endsWith('/roles/pm/file?path=docs%2Fproduct%2Facceptance.md&view=diff'))).toBe(true))
    const added = await within(drawer).findByText('+AC-1 首页列出活动')
    expect(added.closest('li')).toHaveClass('is-add')
    await user.click(within(drawer).getByRole('button', { name: /docs\/product\/notes\.md/ }))
    expect(await within(drawer).findByTestId('kt-file-view')).toHaveTextContent('docs/product/notes.md')

    await user.click(within(drawer).getByRole('button', { name: /架构师/ }))
    expect(await screen.findByRole('dialog', { name: '架构师的产出' })).toBeInTheDocument()
    expect(await screen.findByText('它还没有提交任何文件。')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '上一步' }))
    expect(await screen.findByRole('dialog', { name: '产品经理的产出' })).toBeInTheDocument()
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  test('its reply, its task and every tool call, per round', async () => {
    const user = userEvent.setup()
    routes({
      [`GET ${API}/runs/r1006a/roles/pm`]: () =>
        output('pm', {
          title: '产品经理',
          attempts: [attempt(), attempt({ n: 2, kind: 'fix', label: '修 AC-19', reply: 'DONE: 改了 AC-19', calls: [{ at: 2001, tool: 'Running', kind: 'execute', detail: 'node --test tests/ops-project.test.js' }], started: 2000, ended: 2030 })],
        }),
    })
    render(<TeamPage pollMs={60_000} />)
    await screen.findAllByTestId('kt-lane')
    await user.click(within(laneOf('pm')).getByRole('button', { name: /看产出/ }))
    const drawer = await screen.findByRole('dialog', { name: '产品经理的产出' })
    await user.click(await within(drawer).findByRole('tab', { name: '它的回复' }))
    expect(within(drawer).getByTestId('kt-reply')).toHaveTextContent('DONE: 改了 AC-19')  // the latest round first
    await user.click(within(drawer).getByRole('button', { name: '第 1 轮 · 开工' }))
    expect(within(drawer).getByTestId('kt-reply')).toHaveTextContent('AC-1 首页列出活动')
    await user.click(within(drawer).getByRole('tab', { name: '接到的任务' }))
    expect(within(drawer).getByText(/把 README 里的需求写成验收标准/)).toBeInTheDocument()
    await user.click(within(drawer).getByRole('tab', { name: '做了什么' }))
    const calls = within(drawer).getByRole('list', { name: '它做了什么' })
    expect(within(calls).getAllByRole('listitem').map((li) => li.textContent)).toEqual(['0:03📖Reading README.md', '0:20✏️Creating acceptance.md'])
  })

  test('a file on the card opens the drawer at that file', async () => {
    const user = userEvent.setup()
    routes()
    render(<TeamPage pollMs={60_000} />)
    await screen.findAllByTestId('kt-lane')
    await user.click(within(laneOf('pm')).getByRole('button', { name: 'docs/product/acceptance.md' }))
    const drawer = await screen.findByRole('dialog', { name: '产品经理的产出' })
    expect(await within(drawer).findByTestId('kt-file-view')).toHaveTextContent('docs/product/acceptance.md')
  })

  test('打开网站: once the run has ended the product runs on a local port, shown in place', async () => {
    const user = userEvent.setup()
    const board = runningBoard()
    board.run!.status = 'done'
    board.runs[0].status = 'done'
    expect(board.run!.tests.total).toBeGreaterThan(0) // 打开网站 shows once there is something to run
    let state: SiteStatus = { run: 'r1006a', state: 'off', url: null, port: null, entry: null, started_at: null, expires_at: null, error: null, log: [] }
    routes(
      {
        [`GET ${API}/runs/r1006a/roles/run`]: () => output('run', { title: '整个产品', attempts: [], ended: true }),
        [`GET ${API}/runs/r1006a/site`]: () => state,
        [`POST ${API}/runs/r1006a/site`]: () => (state = { ...state, state: 'running', url: 'http://127.0.0.1:54321/', port: 54321, entry: 'backend/server.js', started_at: 1, expires_at: 1801, log: ['listening on 54321'] }),
        [`POST ${API}/runs/r1006a/site/stop`]: () => (state = { ...state, state: 'off', url: null, port: null }),
      },
      board,
    )
    render(<TeamPage pollMs={60_000} />)
    await screen.findAllByTestId('kt-lane')
    await user.click(screen.getByRole('button', { name: '打开网站' }))
    const drawer = await screen.findByRole('dialog', { name: '整个产品的产出' })
    await user.click(await within(drawer).findByRole('button', { name: '启动网站' }))
    const frame = await within(drawer).findByTitle('团队做出来的网站')
    expect(frame).toHaveAttribute('src', 'http://127.0.0.1:54321/')
    expect(within(drawer).getByRole('link', { name: /127\.0\.0\.1:54321/ })).toHaveAttribute('target', '_blank')
    await user.click(within(drawer).getByRole('button', { name: '停止' }))
    expect(await within(drawer).findByRole('button', { name: '启动网站' })).toBeInTheDocument()
    expect(apiCalls.filter((c) => c.method === 'POST').map((c) => c.path)).toEqual([`${API}/runs/r1006a/site`, `${API}/runs/r1006a/site/stop`])
  })

  test('while the run is active the site waits, and there is no 打开网站 button', async () => {
    const user = userEvent.setup()
    routes({ [`GET ${API}/runs/r1006a/roles/run`]: () => output('run', { title: '整个产品', attempts: [] }) })
    render(<TeamPage pollMs={60_000} />)
    await screen.findAllByTestId('kt-lane')
    expect(screen.queryByRole('button', { name: '打开网站' })).toBeNull()
    await user.click(screen.getByRole('button', { name: '产出' }))
    await screen.findByRole('dialog', { name: '产品经理的产出' })
    await user.click(screen.getByRole('button', { name: '整个产品' }))
    const drawer = await screen.findByRole('dialog', { name: '整个产品的产出' })
    expect(within(drawer).getByRole('tab', { name: /产出文件/ })).toHaveAttribute('aria-selected', 'true')
    await user.click(within(drawer).getByRole('tab', { name: '网站' }))
    expect(within(drawer).getByText(/运行结束以后才能打开网站/)).toBeInTheDocument()
    await act(async () => {})
  })
})

describe('helpers', () => {
  test('promised outputs come first; diff lines are classified', () => {
    expect(sortFiles(output('pm').files).map((f) => f.path)).toEqual(['docs/product/acceptance.md', 'docs/product/notes.md'])
    expect(['@@ -1 +1 @@', '+++ b/x', '+a', '-b', ' c'].map(lineKind)).toEqual(['is-hunk', 'is-meta', 'is-add', 'is-del', ''])
    expect(tabsFor('reviewer', false)).toEqual(['reply', 'task', 'calls'])
    expect(tabsFor('run', true)).toEqual(['site', 'files'])
  })
})

describe('the session runner', () => {
  test('在 Crew 里打开会话 opens the role session in the dashboard (no message sent)', async () => {
    const { chatLaunches } = await import('../test/stubs/app-sdk')
    const board = runningBoard()
    board.run!.roles.find((l) => l.key === 'pm')!.session = 'aidlc-team-r1006a-1-ab12'
    routes({}, board)
    render(<TeamPage />)
    const user = userEvent.setup()
    await screen.findAllByTestId('kt-lane')
    await user.click(screen.getByRole('button', { name: '产出' }))
    const drawer = await screen.findByTestId('kt-outputs')
    await user.click(await within(drawer).findByRole('button', { name: '在 Crew 里打开会话' }))
    expect(chatLaunches).toEqual([{ slotKey: 'aidlc-team-r1006a-1-ab12', autoSend: false }])
  })
})
