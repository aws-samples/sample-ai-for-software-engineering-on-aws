import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, test } from 'vitest'
import type { Board } from '../types'
import { apiCalls, setApiRoutes } from '../test/stubs/app-sdk'
import { clone, vstatdBoard } from '../test/fixtures'
import { TeamPage } from '../main'

const API = '/api/apps/vstatd-team'
const SAID = '要改：上一轮的 F-1 没改，F-028 说明的提交 `89e8c21` 还是没引任何规范页'

/** The vstatd run ended on a 要改 review after its rounds; F-028 is a justification with its citations. */
function endedBoard(): Board {
  const b = vstatdBoard('bench')
  const run = b.run!
  run.status = 'failed'
  b.runs[0].status = 'failed'
  run.bench = { ...run.bench!, step: null, running: null }
  run.review_redo = { role: 'reviewer', summary: SAID, targets: ['dev-fix'] }
  const f = run.backlog!.triage!.findings.find((x) => x.id === 'F-028')!
  Object.assign(f, { decision: 'justify', cites: ['[VSTATD-IF p.9 §6.4]', '[CC1-PN §4.2]'] })
  return b
}

describe('按评审意见再改一轮', () => {
  test('the decision is prefilled for the justification the review names; 同意 sends it with the name', async () => {
    const user = userEvent.setup()
    localStorage.setItem('vstatd-team:signer', '王工')
    setApiRoutes({
      [`GET ${API}/board*`]: () => clone(endedBoard()),
      [`POST ${API}/runs/r1006a/retry`]: () => ({ ok: true, run: 'r1006a', roles: ['dev-fix'], status: 'fixing' }),
    })
    render(<TeamPage pollMs={60_000} />)
    const box = within(await screen.findByTestId('kt-review-redo'))
    expect(box.getByText(`评审：${SAID}`)).toBeInTheDocument()
    const note = box.getByLabelText('你的决定') as HTMLTextAreaElement
    expect(note.value).toContain('不改写已经合入运行分支的提交')
    expect(note.value).toContain('F-028：追加一个空提交（git commit --allow-empty），提交说明写 F-028 和分诊里它的引用 [VSTATD-IF p.9 §6.4] [CC1-PN §4.2]')
    await user.click(box.getByRole('button', { name: '同意，按评审意见再改一轮' }))
    await waitFor(() => expect(apiCalls.filter((c) => c.method === 'POST').map((c) => [c.path, c.body])).toEqual([
      [`${API}/runs/r1006a/retry`, { note: note.value.trim(), by: '王工' }],
    ]))
  })
})
