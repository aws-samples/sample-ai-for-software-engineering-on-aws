import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, test } from 'vitest'
import { apiCalls, apiError, setApiRoutes } from '../test/stubs/app-sdk'
import { clone, emptyBoard, knowledgeOf, knowledgeTextOf, readinessOf, vstatdBoard } from '../test/fixtures'
import { TeamPage } from '../main'

const API = '/api/apps/vstatd-team'

describe('知识库', () => {
  test('the home page lists the documents with key, figures and the index state; one opens as plain text', async () => {
    const user = userEvent.setup()
    setApiRoutes({ [`GET ${API}/board*`]: () => emptyBoard(), [`GET ${API}/readiness`]: () => readinessOf(), [`GET ${API}/knowledge`]: () => knowledgeOf(),
      [`GET ${API}/knowledge/file*`]: (_b, path) => knowledgeTextOf(new URL(path, 'http://x').searchParams.get('path') ?? '') })
    render(<TeamPage pollMs={60_000} />)
    const home = await screen.findByTestId('kt-kb-home')
    expect(within(screen.getByTestId('kt-empty')).getByTestId('kt-kb-home')).toBe(home)
    expect(await within(home).findByTestId('kt-kb-index')).toHaveTextContent('Kiro Crew 来源「vstatd」：14 份文档 · 已同步')
    const docs = await within(home).findAllByTestId('kt-kb-doc')
    expect(docs).toHaveLength(10)
    const doc = (p: string) => docs.find((d) => d.dataset.path === p)!
    expect(doc('vstatd-interface.md')).toHaveTextContent('vstatd 接口规范VSTATD-IF节 41 · 页 11')
    expect(doc('findings-backlog.md')).toHaveTextContent('发现 30 · fix 22 · later 8')
    expect(doc('cc1-gateway.dbc')).toHaveTextContent('报文 9 · 信号 24')
    expect(doc('vstatd-interface.pdf')).toHaveTextContent('vstatd-interface.md 的 PDF 版')
    expect(within(doc('vstatd-interface.pdf')).queryByRole('button')).toBeNull() // the PDF does not open here
    await user.click(within(doc('team-rules.md')).getByRole('button', { name: '团队规则' }))
    const viewer = await screen.findByTestId('kt-kb-viewer')
    expect(apiCalls.some((c) => c.path === `${API}/knowledge/file?path=team-rules.md`)).toBe(true)
    const pre = await within(viewer).findByTestId('kt-kb-text')
    expect(pre.tagName).toBe('PRE')
    expect(pre.textContent).toContain('<b>不渲染</b> **也不渲染 Markdown**')
    expect(pre.querySelector('b')).toBeNull()
    await user.click(within(viewer).getByRole('button', { name: '关闭文档' }))
    expect(screen.queryByTestId('kt-kb-viewer')).toBeNull()
  })

  test('during a run the panel has a chip per cited document with its citations; a chip opens the viewer', async () => {
    const user = userEvent.setup()
    setApiRoutes({ [`GET ${API}/board*`]: () => clone(vstatdBoard('bench')),
      [`GET ${API}/knowledge/file*`]: (_b, path) => knowledgeTextOf(new URL(path, 'http://x').searchParams.get('path') ?? '') })
    render(<TeamPage pollMs={60_000} />)
    const kb = await screen.findByTestId('kt-kb')
    const chips = within(kb).getAllByTestId('kt-kb-chip')
    expect(chips.map((c) => [c.dataset.key, c.textContent])).toEqual([
      ['VSTATD-IF', 'VSTATD-IF vstatd 接口规范引用 9'], ['CC1-PN', 'CC1-PN CC-1 平台说明引用 2'], ['TR', 'TR 团队规则引用 6']])
    await user.click(within(chips[1]).getByRole('button'))
    const viewer = await screen.findByTestId('kt-kb-viewer')
    expect(await within(viewer).findByTestId('kt-kb-text')).toHaveTextContent('# CC-1 平台说明')
  })

  test('a refused file shows the reason', async () => {
    const user = userEvent.setup()
    setApiRoutes({ [`GET ${API}/board*`]: () => emptyBoard(), [`GET ${API}/knowledge`]: () => knowledgeOf(),
      [`GET ${API}/knowledge/file*`]: () => {
        throw apiError(404, 'not_found', '知识库里没有 team-rules.md')
      } })
    render(<TeamPage pollMs={60_000} />)
    const docs = await screen.findAllByTestId('kt-kb-doc')
    await user.click(within(docs.find((d) => d.dataset.path === 'team-rules.md')!).getByRole('button'))
    expect(await within(screen.getByTestId('kt-kb-viewer')).findByRole('alert')).toHaveTextContent('读不到：知识库里没有 team-rules.md')
  })
})
