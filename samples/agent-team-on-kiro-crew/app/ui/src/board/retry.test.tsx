import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, test } from 'vitest'
import type { Board } from '../types'
import { apiCalls, apiError, setApiRoutes } from '../test/stubs/app-sdk'
import { clone, runningBoard } from '../test/fixtures'
import { TeamPage } from '../main'

const API = '/api/apps/aidlc-team'
const NEVER = 'never started: waiting for memory (macOS memory pressure did not ease in time); retry once it eases or a running agent finishes'

/** The fixture run, ended: the tester never got to start. */
function failedBoard(): Board {
  const b = runningBoard()
  b.run!.status = 'failed'
  b.runs[0].status = 'failed'
  const tester = b.run!.roles.find((l) => l.key === 'tester')!
  tester.status = 'failed'
  tester.agent = { ...tester.agent!, error: NEVER }
  return b
}

const laneOf = (key: string) => screen.getAllByTestId('kt-lane').find((l) => l.dataset.role === key)!
const posts = () => apiCalls.filter((c) => c.method === 'POST').map((c) => [c.path, c.body])

describe('重试', () => {
  test('a failed role can be retried from the top bar, its card and its node', async () => {
    const user = userEvent.setup()
    setApiRoutes({ [`GET ${API}/board*`]: () => clone(failedBoard()), [`POST ${API}/runs/r1006a/retry`]: () => ({ ok: true, run: 'r1006a', roles: ['tester'], status: 'running' }) })
    render(<TeamPage pollMs={60_000} />)
    await screen.findAllByTestId('kt-lane')
    expect(within(laneOf('tester')).getByText(NEVER, { exact: false })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '↻ 重试失败的 1 个角色' }))
    await user.click(within(laneOf('tester')).getByRole('button', { name: '↻ 重试' }))
    await user.click(screen.getByRole('button', { name: '重试测试' }))
    await waitFor(() =>
      expect(posts()).toEqual([
        [`${API}/runs/r1006a/retry`, {}],
        [`${API}/runs/r1006a/retry`, { roles: ['tester'] }],
        [`${API}/runs/r1006a/retry`, { roles: ['tester'] }],
      ]),
    )
    expect(within(laneOf('backend')).queryByRole('button', { name: '↻ 重试' })).toBeNull()
  })

  test('a refused retry says why', async () => {
    const user = userEvent.setup()
    setApiRoutes({
      [`GET ${API}/board*`]: () => clone(failedBoard()),
      [`POST ${API}/runs/r1006a/retry`]: () => {
        throw apiError(409, 'run_active', '已经有一个运行在跑（r1006b），一次只跑一个')
      },
    })
    render(<TeamPage pollMs={60_000} />)
    await screen.findAllByTestId('kt-lane')
    await user.click(screen.getByRole('button', { name: '↻ 重试失败的 1 个角色' }))
    expect(await screen.findByText(/重试没成：已经有一个运行在跑（r1006b），一次只跑一个/)).toBeInTheDocument()
  })

  test('nothing failed: no retry anywhere', async () => {
    setApiRoutes({ [`GET ${API}/board*`]: () => runningBoard() })
    render(<TeamPage pollMs={60_000} />)
    await screen.findAllByTestId('kt-lane')
    expect(screen.queryByRole('button', { name: /重试/ })).toBeNull()
  })
})
