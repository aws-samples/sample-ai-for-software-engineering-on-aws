import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, test } from 'vitest'
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
