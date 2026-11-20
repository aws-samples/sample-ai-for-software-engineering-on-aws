/**
 * 设置 (settings/SettingsView.tsx): the page reads `GET /settings`, sends only what the person changed, puts a field
 * back to the team file's value with 恢复默认, says what the backend refused, and shows the build server's own
 * `bench_*` paths read only, with the lines to paste.
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, test } from 'vitest'

import { apiCalls, setApiRoutes, StubApiError } from '../test/stubs/app-sdk'
import { parseView, searchOf } from '../nav'
import VstatdTeamApp from '../main'
import { SettingsView } from './SettingsView'
import type { SettingsPage } from '../types'

const API = '/api/apps/vstatd-team'

const CONFIGS = {
  build: '~/workplace/vstatd-team/server/build.toml',
  bench: '~/workplace/vstatd-team/server/bench.toml',
}

const DIRECT: SettingsPage = {
  settings: {
    mode: 'direct',
    server_configs: { ...CONFIGS },
    baseline: '${sample}/bench/baseline',
    docker: { runner: '', host: '' },
    board_decides: false,
  },
  defaults: {
    mode: 'direct',
    server_configs: { ...CONFIGS },
    baseline: '${sample}/bench/baseline',
    docker: { runner: '', host: '' },
    board_decides: false,
  },
  release: null,
}

const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x)) as T

describe('设置', () => {
  test('?view=settings is a tab of its own, next to 评分卡', async () => {
    expect(parseView('?view=settings')).toEqual({ kind: 'settings' })
    expect(searchOf({ kind: 'settings' })).toBe('?view=settings')
    setApiRoutes({ [`GET ${API}/settings`]: () => clone(DIRECT) })
    render(<VstatdTeamApp pollMs={60_000} />)
    await userEvent.click(await screen.findByRole('tab', { name: '设置' }))
    expect(await screen.findByTestId('st-root')).toBeInTheDocument()
    expect(window.location.search).toBe('?view=settings')
    window.history.replaceState(null, '', '/')
  })

  test('every field starts from the team file, 保存 is off until something changes', async () => {
    setApiRoutes({ [`GET ${API}/settings`]: () => clone(DIRECT) })
    render(<SettingsView />)
    const mode = (await screen.findByLabelText('连接方式')) as HTMLSelectElement
    expect(mode.value).toBe('direct')
    expect((screen.getByLabelText('基线目录') as HTMLInputElement).value).toBe('${sample}/bench/baseline')
    expect((screen.getByLabelText('Docker 命令') as HTMLInputElement).value).toBe('')
    expect((screen.getByLabelText('servers 模式下看板上也能批准、拒绝（board_decides）') as HTMLInputElement).checked).toBe(false)
    expect(screen.getByTestId('st-save')).toBeDisabled()
    expect(screen.queryByTestId('st-release')).not.toBeInTheDocument() // direct mode reads no server configuration
    // nothing differs from the team file, so no field offers 恢复默认
    expect(screen.queryAllByRole('button', { name: '恢复默认' })).toHaveLength(0)
  })

  test('a change is sent as the whole settings object, and 恢复默认 puts the field back', async () => {
    const saved: unknown[] = []
    setApiRoutes({
      [`GET ${API}/settings`]: () => clone(DIRECT),
      [`POST ${API}/settings`]: (body) => {
        saved.push(body)
        const b = body as { settings: SettingsPage['settings'] }
        return { ok: true, settings: b.settings, defaults: clone(DIRECT.defaults), release: null }
      },
    })
    render(<SettingsView />)
    const host = (await screen.findByLabelText('Docker 主机')) as HTMLInputElement
    await userEvent.type(host, 'tcp://bench.example:2375')
    expect(screen.getByTestId('st-save')).toBeEnabled()
    await userEvent.click(screen.getByTestId('st-save'))
    await waitFor(() => expect(saved).toHaveLength(1))
    const want = { ...DIRECT.settings, docker: { runner: '', host: 'tcp://bench.example:2375' } }
    expect(saved[0]).toEqual({ settings: want })
    expect(await screen.findByTestId('st-saved')).toBeInTheDocument()
    // the saved value differs from the team file's, so the field offers 恢复默认 and it clears the field
    const field = host.closest('.st-field')!
    await userEvent.click(within(field as HTMLElement).getByRole('button', { name: '恢复默认' }))
    expect((screen.getByLabelText('Docker 主机') as HTMLInputElement).value).toBe('')
  })

  test('what the backend refuses is said and the page keeps the draft', async () => {
    setApiRoutes({
      [`GET ${API}/settings`]: () => clone(DIRECT),
      [`POST ${API}/settings`]: () => {
        throw new StubApiError(400, { error: '设置没存：「Docker 主机」要以 unix:// 开头', code: 'invalid_settings',
          problems: ['「Docker 主机」要以 unix:// 开头'] })
      },
    })
    render(<SettingsView />)
    await userEvent.type(await screen.findByLabelText('Docker 主机'), 'bench.example:2375')
    await userEvent.click(screen.getByTestId('st-save'))
    expect(await screen.findByTestId('st-error')).toHaveTextContent('要以 unix:// 开头')
    expect((screen.getByLabelText('Docker 主机') as HTMLInputElement).value).toBe('bench.example:2375')
    expect(screen.queryByTestId('st-saved')).not.toBeInTheDocument()
  })

  test('in servers mode the build server\'s bench paths are shown read only, with the lines to paste', async () => {
    const page: SettingsPage = {
      ...clone(DIRECT),
      settings: { ...clone(DIRECT.settings), mode: 'servers' },
      release: {
        ok: false,
        detail: '缺 bench_results、bench_runs、bench_baseline，build 服务器判不了 release 检查：把下面三行加到 build.toml 的 [paths] 里',
        missing: ['bench_results', 'bench_runs', 'bench_baseline'],
        paste_lines: ['bench_results = "/srv/bench/state/results"', 'bench_runs = "/srv/bench/state/runs"',
          'bench_baseline = "/srv/bench/baseline"'],
        config: '~/workplace/vstatd-team/server/build.toml',
      },
    }
    setApiRoutes({ [`GET ${API}/settings`]: () => clone(page) })
    render(<SettingsView />)
    const block = await screen.findByTestId('st-release')
    expect(within(block).getByTestId('st-release-state')).toHaveTextContent('没配好')
    expect(within(block).getByTestId('st-release-lines').textContent).toBe(page.release!.paste_lines.join('\n'))
    expect(block).toHaveTextContent('app 只读这个文件')
    // the page never offers to write the server's file: the only write it has is 保存 of the app's own settings
    expect(within(block).queryAllByRole('button')).toHaveLength(0)
    // and direct mode's fields say they are not used now
    expect(screen.getByTestId('st-direct')).toHaveTextContent('现在是 servers 模式')
  })

  test('every field has an id of its own, not its translated label', async () => {
    // a label's text holds spaces (and an apostrophe in English), which an HTML id may not, and it changes with
    // the language: each field carries a written-out id instead, as the board_decides checkbox does
    setApiRoutes({ [`GET ${API}/settings`]: () => clone(DIRECT) })
    render(<SettingsView />)
    const baseline = (await screen.findByLabelText('基线目录')) as HTMLInputElement
    expect(baseline.id).toBe('st-baseline')
    for (const [label, id] of [['build 服务器的配置文件', 'st-build-config'], ['Docker 主机', 'st-docker-host'],
      ['servers 模式下看板上也能批准、拒绝（board_decides）', 'st-board-decides']]) {
      const field = screen.getByLabelText(label) as HTMLInputElement
      expect(field.id).toBe(id)
      expect(document.querySelector(`label[for="${id}"]`)).toHaveTextContent(label)
    }
  })

  test('a read that fails says so instead of an empty form', async () => {
    setApiRoutes({
      [`GET ${API}/settings`]: () => {
        throw new StubApiError(500, { error: '读不了团队配置', code: 'bad_team' })
      },
    })
    render(<SettingsView />)
    expect(await screen.findByRole('alert')).toHaveTextContent('读不了团队配置')
    expect(screen.queryByTestId('st-save')).not.toBeInTheDocument()
    expect(apiCalls.filter((c) => c.method === 'POST')).toHaveLength(0)
  })
})
