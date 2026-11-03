import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, test } from 'vitest'
import { apiCalls, apiError, setApiRoutes } from '../test/stubs/app-sdk'
import { clone, emptyBoard, knowledgeOf, knowledgeTextOf, readinessOf, vstatdBoard } from '../test/fixtures'
import { TeamPage } from '../main'

const API = '/api/apps/vstatd-team'

describe('知识库', () => {
  test('the home page shows the documents as cards by kind with key, figures and the index state; one opens as plain text', async () => {
    const user = userEvent.setup()
    setApiRoutes({ [`GET ${API}/board*`]: () => emptyBoard(), [`GET ${API}/readiness`]: () => readinessOf(), [`GET ${API}/knowledge`]: () => knowledgeOf(),
      [`GET ${API}/knowledge/file*`]: (_b, path) => knowledgeTextOf(new URL(path, 'http://x').searchParams.get('path') ?? '') })
    render(<TeamPage pollMs={60_000} />)
    const home = await screen.findByTestId('kt-kb-home')
    expect(within(screen.getByTestId('kt-empty')).getByTestId('kt-kb-home')).toBe(home)
    expect(await within(home).findByTestId('kt-kb-index')).toHaveTextContent('Kiro Crew 来源「vstatd」：14 份文档 · 已同步')
    const groups = within(home).getAllByTestId('kt-kb-group')
    const paths = (g: HTMLElement) => within(g).getAllByTestId('kt-kb-doc').map((d) => d.dataset.path)
    expect(groups.map((g) => [g.dataset.group, paths(g)])).toEqual([
      ['规范', ['vstatd-interface.md', 'cc1-platform-notes.md', 'team-rules.md']],
      ['待办与数据', ['findings-backlog.md', 'cc1-gateway.dbc', 'vss-mapping.yaml']],
      ['事实条目', ['facts/']],
    ])
    const docs = within(home).getAllByTestId('kt-kb-doc')
    const doc = (p: string) => docs.find((d) => d.dataset.path === p)!
    const chips = (p: string) => [...doc(p).querySelectorAll('.kt-lib-chip')].map((c) => c.textContent)
    expect(doc('vstatd-interface.md')).toHaveTextContent('vstatd 接口规范VSTATD-IFPDF 版')
    expect(within(doc('vstatd-interface.md')).getByTestId('kt-kb-pdf')).toHaveAttribute('title', expect.stringContaining('vstatd-interface.pdf'))
    expect(chips('vstatd-interface.md')).toEqual(['节 41', '页 11'])
    expect(chips('findings-backlog.md')).toEqual(['发现 30', 'fix 22', 'later 8'])
    expect(chips('cc1-gateway.dbc')).toEqual(['报文 9', '信号 24'])
    expect(chips('facts/')).toEqual(['信号 24', '报文 9', '规则 39'])
    expect(within(doc('facts/')).getAllByRole('button', { name: /^查看/ })).toHaveLength(3)
    expect(docs.some((d) => d.dataset.path === 'vstatd-interface.pdf')).toBe(false) // the PDF is a note, not a card
    expect(within(doc('team-rules.md')).queryByRole('button', { name: '团队规则' })).toBeNull() // the title is not a link
    await user.click(within(doc('team-rules.md')).getByRole('button', { name: '查看 团队规则' }))
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
    await user.click(within(docs.find((d) => d.dataset.path === 'team-rules.md')!).getByRole('button', { name: '查看 团队规则' }))
    expect(await within(screen.getByTestId('kt-kb-viewer')).findByRole('alert')).toHaveTextContent('读不到：知识库里没有 team-rules.md')
  })
})
