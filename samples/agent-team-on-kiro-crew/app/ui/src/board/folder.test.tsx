import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, test } from 'vitest'
import { apiCalls, apiError, setApiRoutes } from '../test/stubs/app-sdk'
import { runningBoard } from '../test/fixtures'
import { TeamPage } from '../main'

const API = '/api/apps/aidlc-team'

describe('打开文件夹', () => {
  test('the top bar shows where the project is and opens it in Finder or Kiro', async () => {
    const user = userEvent.setup()
    setApiRoutes({
      [`GET ${API}/board*`]: () => runningBoard(),
      [`POST ${API}/runs/r1006a/open`]: (body) => {
        if ((body as { app: string }).app === 'kiro') throw apiError(502, 'open_failed', '打不开：没装 Kiro')
        return { ok: true, path: '/x', app: 'finder' }
      },
    })
    render(<TeamPage pollMs={60_000} />)
    await screen.findAllByTestId('kt-lane')
    await user.click(screen.getByRole('button', { name: '📁 文件夹' }))
    const panel = screen.getByRole('region', { name: '项目文件夹' })
    expect(within(panel).getByText('/Users/you/workplace/aidlc-team/runs/r1006a/wt/_run')).toBeInTheDocument()
    await user.click(within(panel).getByRole('button', { name: '📁 在 Finder 打开' }))
    expect(await within(panel).findByRole('status')).toHaveTextContent('已经在 Finder 里打开')
    await user.click(within(panel).getByRole('button', { name: '用 Kiro 打开' }))
    expect(await within(panel).findByText(/^打不开：没装 Kiro/)).toBeInTheDocument()
    expect(apiCalls.filter((c) => c.method === 'POST').map((c) => c.body)).toEqual([{ role: null, app: 'finder' }, { role: null, app: 'kiro' }])
    await user.click(within(panel).getByRole('button', { name: '收起项目文件夹' }))
    expect(screen.queryByRole('region', { name: '项目文件夹' })).toBeNull()
  })
})
