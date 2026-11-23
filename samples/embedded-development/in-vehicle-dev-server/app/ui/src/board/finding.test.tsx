import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, test, vi } from 'vitest'
import type { Board } from '../types'
import { apiCalls, apiError, setApiRoutes } from '../test/stubs/app-sdk'
import { clone, vstatdBoard } from '../test/fixtures'
import { TeamPage } from '../main'
import { locationOf, toolOf } from './Finding'

const API = '/api/apps/vstatd-team'
const TREE = '/Users/you/workplace/vstatd-team/runs/r1006a/results/1/work/unit/tree/'
const TSAN = `tsan: SUMMARY: ThreadSanitizer: data race ${TREE}src/signal_table.cpp:90 in vstatd::SignalTable::get(unsigned long) const；tsan: WARNING: ThreadSanitizer: data race (pid=300)`
const BUILD = 'src/main.cpp:12:10: fatal error: systemd/sd-daemon.h: No such file or directory'

/** The vstatd run held for a person after the checks: build and unit failed, the developer cannot fix more. */
function heldBoard(): Board {
  const b = vstatdBoard('bench')
  const run = b.run!
  run.status = 'failed'
  b.runs[0].status = 'failed'
  run.bench = { ...run.bench!, step: null, running: null }
  run.tests.cases = run.tests.cases.map((c) =>
    c.id === 'build' ? { ...c, status: 'fail', verdict: 'FAIL', message: BUILD, file: 'src/main.cpp' }
      : c.id === 'unit' ? { ...c, status: 'fail', verdict: 'FAIL', message: TSAN, file: 'src/signal_table.cpp' } : c)
  run.tests.passed = 3
  run.tests.failed = 2
  run.tests.held = { checks: ['build', 'unit'], why: `build 没过，负责的角色没法再改：${BUILD}` }
  return b
}

const posts = () => apiCalls.filter((c) => c.method === 'POST').map((c) => [c.path, c.body])

describe('补登发现并交给角色', () => {
  test('location and tool come from the first reason', () => {
    expect(locationOf(TSAN)).toBe('src/signal_table.cpp:90')
    expect(locationOf(BUILD)).toBe('src/main.cpp:12')
    expect(toolOf('unit', TSAN)).toBe('ThreadSanitizer')
    expect(toolOf('unit', 'expected 1, got 2')).toBe('gtest')
    expect(toolOf('build', BUILD)).toBe('gcc')
  })

  test('the dialog is filled in from the held check and sends the finding', async () => {
    const user = userEvent.setup()
    localStorage.setItem('vstatd-team:signer', '王工')
    setApiRoutes({
      [`GET ${API}/board*`]: () => clone(heldBoard()),
      [`POST ${API}/runs/r1006a/finding`]: () => ({ id: 'F-032', triage_sha256: 'ab', held: true, status: 'failed' }),
    })
    render(<TeamPage pollMs={60_000} />)
    const box = await screen.findByTestId('kt-wall-held')
    expect(screen.getAllByRole('button', { name: '补登发现并交给角色' })).toHaveLength(2) // the check wall and the flow strip
    await user.click(within(box).getByRole('button', { name: '补登发现并交给角色' }))
    const d = await screen.findByTestId('kt-finding-dialog')
    const q = within(d)
    expect(q.getByText('补登发现 F-032 并交给角色')).toBeInTheDocument()
    expect(q.getByLabelText('检查')).toHaveValue('build')
    expect(q.getByLabelText('工具')).toHaveValue('gcc')
    expect(q.getByLabelText('位置')).toHaveValue('src/main.cpp:12')
    expect(q.getByLabelText('可写路径')).toHaveValue('src/main.cpp')
    expect(q.getByLabelText('证据')).toHaveValue('build')
    expect(q.getByLabelText('交给')).toHaveValue('dev-fix')
    expect(q.getByLabelText('补登人')).toHaveValue('王工')
    expect([...(q.getByLabelText('交给') as HTMLSelectElement).options].map((o) => o.value)).toEqual(['dev-fix', 'dev-refactor'])

    await user.selectOptions(q.getByLabelText('检查'), 'unit')
    expect(q.getByLabelText('工具')).toHaveValue('ThreadSanitizer')
    expect(q.getByLabelText('位置')).toHaveValue('src/signal_table.cpp:90')
    expect(q.getByLabelText('证据')).toHaveValue('unit-test')

    await user.selectOptions(q.getByLabelText('检查'), 'build')
    await user.clear(q.getByLabelText('位置'))
    await user.type(q.getByLabelText('位置'), 'cmake/cc1-aarch64.cmake:1')
    await user.clear(q.getByLabelText('可写路径'))
    await user.type(q.getByLabelText('可写路径'), 'cmake/cc1-aarch64.cmake')
    await user.type(q.getByLabelText('引用'), '[[CC1-PN §7.2]')
    await user.type(q.getByLabelText('备注'), '设 CMAKE_SYSROOT')
    await user.click(q.getByLabelText('接着运行'))
    await user.click(q.getByRole('button', { name: '补登' }))
    await waitFor(() => expect(posts()).toEqual([[`${API}/runs/r1006a/finding`, {
      check: 'build', tool: 'gcc', location: 'cmake/cc1-aarch64.cmake:1', decision: 'fix', evidence: 'build', behaviour: false,
      facts: [], cites: ['[CC1-PN §7.2]'], reason: '', pick_up_when: '', role: 'dev-fix', paths: ['cmake/cc1-aarch64.cmake'],
      note: '设 CMAKE_SYSROOT', by: '王工', continue: false,
    }]]))
    await waitFor(() => expect(screen.queryByTestId('kt-finding-dialog')).toBeNull())
  })

  test('past the build server\'s bound: the hold shows the reset command the person runs before 重试', async () => {
    const b = heldBoard()
    const cmd = '~/workplace/vstatd-team/server/venv/bin/python -I -m buildserver.admin reset-repair --config '
      + '~/workplace/vstatd-team/server/build.toml --reason "a person decided after 4 failed cross builds"'
    b.run!.tests.held = { checks: ['build'], why: 'build 没法判定：build 服务器的交叉构建已连续失败 4 次、上限 3', commands: [cmd] }
    setApiRoutes({ [`GET ${API}/board*`]: () => clone(b) })
    render(<TeamPage pollMs={60_000} />)
    const box = within(await screen.findByTestId('kt-flow-held-commands'))
    expect(box.getByText(cmd)).toBeInTheDocument()
    expect(box.getByText(/build 服务器到了修复上限/)).toBeInTheDocument()
  })

  test('the role named the root-cause file it cannot write: 再加路径 and 备注 are filled in, sent only on 补登', async () => {
    const user = userEvent.setup()
    localStorage.setItem('vstatd-team:signer', '王工')
    const b = heldBoard()
    const note = '开发 · 修复说：需要有人把 cmake/cc1-aarch64.cmake 加进我的可改范围，提交说明里写 F-032'
    b.run!.tests.held!.prefill = [{ check: 'build', role: 'dev-fix', paths: ['cmake/cc1-aarch64.cmake'], note }]
    setApiRoutes({
      [`GET ${API}/board*`]: () => clone(b),
      [`POST ${API}/runs/r1006a/finding`]: () => ({ id: 'F-032', triage_sha256: 'ab', held: false, status: 'running' }),
    })
    render(<TeamPage pollMs={60_000} />)
    await user.click(within(await screen.findByTestId('kt-wall-held')).getByRole('button', { name: '补登发现并交给角色' }))
    const q = within(await screen.findByTestId('kt-finding-dialog'))
    expect(q.getByLabelText('检查')).toHaveValue('build')
    expect(q.getByLabelText('可写路径')).toHaveValue('src/main.cpp')
    expect(q.getByLabelText('再加路径')).toHaveValue('cmake/cc1-aarch64.cmake')
    expect(q.getByLabelText('备注')).toHaveValue(note)
    expect(posts()).toEqual([]) // filled in, not sent
    await user.selectOptions(q.getByLabelText('检查'), 'unit') // the prefill is the build check's: it does not follow
    expect(q.getByLabelText('再加路径')).toHaveValue('')
    expect(q.getByLabelText('备注')).toHaveValue('')
    await user.selectOptions(q.getByLabelText('检查'), 'build')
    expect(q.getByLabelText('再加路径')).toHaveValue('cmake/cc1-aarch64.cmake')
    await user.click(q.getByRole('button', { name: '补登并接着运行' }))
    await waitFor(() => expect(posts()).toEqual([[`${API}/runs/r1006a/finding`, expect.objectContaining({
      check: 'build', role: 'dev-fix', paths: ['src/main.cpp', 'cmake/cc1-aarch64.cmake'], note, by: '王工',
      continue: true,
    })]]))
  })

  test('a check registered at the same place already: the dialog starts on the next one and says so for that one', async () => {
    const user = userEvent.setup()
    const b = heldBoard()
    b.run!.backlog!.triage!.findings.push({ id: 'F-032', decision: 'fix', added: true, found_by: 'checks/build.sh', location: 'src/main.cpp:12',
      cites: [], facts: [], evidence: 'build', behaviour: false, answer: null, static: null, trace: null })
    setApiRoutes({ [`GET ${API}/board*`]: () => clone(b) })
    render(<TeamPage pollMs={60_000} />)
    await user.click(within(await screen.findByTestId('kt-wall-held')).getByRole('button', { name: '补登发现并交给角色' }))
    const q = within(await screen.findByTestId('kt-finding-dialog'))
    expect(q.getByText('补登发现 F-033 并交给角色')).toBeInTheDocument()
    expect(q.getByLabelText('检查')).toHaveValue('unit')
    expect(q.queryByTestId('kt-finding-dup')).toBeNull()
    await user.selectOptions(q.getByLabelText('检查'), 'build')
    expect(q.getByTestId('kt-finding-dup')).toHaveTextContent('build 在 src/main.cpp:12 已经补登过：F-032')
    await user.clear(q.getByLabelText('位置'))
    await user.type(q.getByLabelText('位置'), 'cmake/cc1-aarch64.cmake:1')
    expect(q.queryByTestId('kt-finding-dup')).toBeNull()
  })

  test('every held failure registered at its place: the dialog starts on 给已补登的发现加路径 and sends only the paths', async () => {
    const user = userEvent.setup()
    localStorage.setItem('vstatd-team:signer', '王工')
    const b = heldBoard()
    const row = (id: string, check: string, location: string) => ({ id, decision: 'fix', added: true, found_by: `checks/${check}.sh`, location,
      cites: [], facts: [], evidence: 'build', behaviour: false, answer: null, static: null, trace: null })
    b.run!.backlog!.triage!.findings.push(row('F-032', 'build', 'src/main.cpp:12'), row('F-035', 'unit', 'src/signal_table.cpp:90'))
    setApiRoutes({
      [`GET ${API}/board*`]: () => clone(b),
      [`POST ${API}/runs/r1006a/finding`]: () => ({ id: 'F-032', triage_sha256: 'ab', held: true, status: 'failed' }),
    })
    render(<TeamPage pollMs={60_000} />)
    await user.click(within(await screen.findByTestId('kt-wall-held')).getByRole('button', { name: '补登发现并交给角色' }))
    const q = within(await screen.findByTestId('kt-finding-dialog'))
    expect(q.getByText('给已补登的发现加可写路径')).toBeInTheDocument()
    expect(q.getByLabelText('要做什么')).toHaveValue('extend')
    expect([...(q.getByLabelText('发现') as HTMLSelectElement).options].map((o) => o.value)).toEqual(['F-032', 'F-035'])
    expect(q.getByLabelText('发现')).toHaveValue('F-032')
    await user.click(q.getByRole('button', { name: '加路径并接着运行' }))
    expect(q.getByRole('alert')).toHaveTextContent('写明要加的可写路径')
    await user.type(q.getByLabelText('加可写路径'), 'cmake/cc1-aarch64.cmake')
    await user.type(q.getByLabelText('备注'), '设 CMAKE_SYSROOT')
    await user.click(q.getByLabelText('接着运行'))
    await user.click(q.getByRole('button', { name: '加路径' }))
    await waitFor(() => expect(posts()).toEqual([[`${API}/runs/r1006a/finding`, {
      extend: 'F-032', role: 'dev-fix', paths: ['cmake/cc1-aarch64.cmake'], note: '设 CMAKE_SYSROOT', by: '王工', continue: false,
    }]]))
  })

  test('the app proposes the paths: one 同意 sends each, the last one carries on', async () => {
    const user = userEvent.setup()
    localStorage.setItem('vstatd-team:signer', '王工')
    const b = heldBoard()
    b.run!.tests.held!.suggest = [
      { extend: 'F-032', check: 'build', role: 'dev-fix', paths: ['cmake/cc1-aarch64.cmake'], note: '开发 · 修复说根因在 cmake/cc1-aarch64.cmake' },
      { extend: 'F-035', check: 'unit', role: 'dev-fix', paths: ['tests/test_signal_table.cpp'], note: '还没有测试写 F-035' },
    ]
    setApiRoutes({
      [`GET ${API}/board*`]: () => clone(b),
      [`POST ${API}/runs/r1006a/finding`]: () => ({ id: 'F-032', triage_sha256: 'ab', held: true, status: 'failed' }),
    })
    render(<TeamPage pollMs={60_000} />)
    const box = await screen.findByTestId('kt-suggest')
    expect(box).toHaveTextContent('F-032（build）交给开发 · 修复，加可写 cmake/cc1-aarch64.cmake')
    expect(within(screen.getByTestId('kt-flow-held')).getByRole('button', { name: '自己填' })).toBeInTheDocument()
    await user.click(within(box).getByRole('button', { name: '同意建议并接着运行' }))
    await waitFor(() => expect(posts()).toEqual([
      [`${API}/runs/r1006a/finding`, { extend: 'F-032', role: 'dev-fix', paths: ['cmake/cc1-aarch64.cmake'], note: '同意 app 的建议：开发 · 修复说根因在 cmake/cc1-aarch64.cmake', by: '王工', continue: false }],
      [`${API}/runs/r1006a/finding`, { extend: 'F-035', role: 'dev-fix', paths: ['tests/test_signal_table.cpp'], note: '同意 app 的建议：还没有测试写 F-035', by: '王工', continue: true }],
    ]))
  })

  test('one finding proposed to the developer and the tester: both listed, the form follows 交给', async () => {
    const user = userEvent.setup()
    const errors = vi.spyOn(console, 'error').mockImplementation(() => {})
    const b = heldBoard()
    const row = (id: string, check: string, location: string) => ({
      id, decision: 'fix', added: true, found_by: `checks/${check}.sh`, location, cites: [], facts: [],
      evidence: 'unit-test', behaviour: false, answer: null, static: null, trace: null })
    b.run!.backlog!.triage!.findings.push(row('F-032', 'build', 'src/main.cpp:12'),
      row('F-035', 'unit', 'src/signal_table.cpp:90'))
    const test = 'tests/test_signal_table.cpp'
    b.run!.tests.held!.suggest = [
      { extend: 'F-035', check: 'unit', role: 'dev-fix', paths: ['src/signal_table.hpp'], note: '根因在 .hpp' },
      { extend: 'F-035', check: 'unit', role: 'tester', paths: [test], note: `在 ${test} 里加` },
    ]
    setApiRoutes({ [`GET ${API}/board*`]: () => clone(b) })
    try {
      render(<TeamPage pollMs={60_000} />)
      const box = await screen.findByTestId('kt-suggest')
      expect(within(box).getAllByRole('listitem')).toHaveLength(2)
      expect(box).toHaveTextContent('交给测试，加可写 tests/test_signal_table.cpp')
      expect(errors.mock.calls.filter((c) => String(c[0]).includes('same key'))).toEqual([])
      await user.click(within(screen.getByTestId('kt-flow-held')).getByRole('button', { name: '自己填' }))
      const q = within(await screen.findByTestId('kt-finding-dialog'))
      await user.selectOptions(q.getByLabelText('发现'), 'F-035')
      expect(q.getByLabelText('交给')).toHaveValue('dev-fix') // the first proposal for the finding
      expect(q.getByLabelText('加可写路径')).toHaveValue('src/signal_table.hpp')
      await user.selectOptions(q.getByLabelText('交给'), 'tester')
      expect(q.getByLabelText('加可写路径')).toHaveValue('tests/test_signal_table.cpp')
      expect(q.getByLabelText('备注')).toHaveValue('在 tests/test_signal_table.cpp 里加')
      await user.selectOptions(q.getByLabelText('交给'), 'dev-fix')
      expect(q.getByLabelText('加可写路径')).toHaveValue('src/signal_table.hpp')
    } finally {
      errors.mockRestore()
    }
  })

  test('a refused finding says why and the dialog stays', async () => {
    const user = userEvent.setup()
    setApiRoutes({
      [`GET ${API}/board*`]: () => clone(heldBoard()),
      [`POST ${API}/runs/r1006a/finding`]: () => {
        throw apiError(400, 'triage_problems', '补登以后分诊过不了检查：F-032：引用 \'[VSTATD-IF §8.4]\'：引 VSTATD-IF 要写页码')
      },
    })
    render(<TeamPage pollMs={60_000} />)
    await user.click(within(await screen.findByTestId('kt-wall-held')).getByRole('button', { name: '补登发现并交给角色' }))
    const q = within(await screen.findByTestId('kt-finding-dialog'))
    await user.type(q.getByLabelText('补登人'), '王工')
    await user.type(q.getByLabelText('再加路径'), 'tests/test_signal_table.cpp')
    await user.click(q.getByRole('button', { name: '补登并接着运行' }))
    expect(await q.findByRole('alert')).toHaveTextContent('引 VSTATD-IF 要写页码')
    expect((posts()[0][1] as { paths: string[] }).paths).toEqual(['src/main.cpp', 'tests/test_signal_table.cpp'])
  })
})
