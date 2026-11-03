import { render, screen, within } from '@testing-library/react'
import { describe, expect, test } from 'vitest'
import { setApiRoutes } from '../test/stubs/app-sdk'
import { emptyBoard, teamOf } from '../test/fixtures'
import { TeamPage } from '../main'

const API = '/api/apps/vstatd-team'

describe('组队预览', () => {
  test('the start form shows the roles by phase with gates and templates, the checks by when they run and the knowledge', async () => {
    setApiRoutes({ [`GET ${API}/board*`]: () => emptyBoard(), [`GET ${API}/team`]: () => teamOf() })
    render(<TeamPage pollMs={60_000} />)
    const pick = await screen.findByLabelText('组队预览')
    expect(within(pick).getAllByTestId('kt-pick-role').map((r) => r.dataset.key)).toEqual(['triage', 'architect', 'tester', 'dev-fix', 'dev-refactor', 'reviewer'])
    const phases = within(pick).getByLabelText('按 AI-DLC 阶段').querySelectorAll('li')
    expect([...phases].map((li) => li.querySelector('.kt-pick-phase')?.textContent)).toEqual(['2 启动', '3 构建', '✓ 评审关卡'])
    const role = (k: string) => within(pick).getAllByTestId('kt-pick-role').find((r) => r.dataset.key === k)!
    expect(role('triage')).toHaveTextContent('分诊 · 人批准（分诊）embedded-developer-agent')
    expect(role('tester')).not.toHaveTextContent('人批准')
    expect(role('reviewer')).toHaveAttribute('title', 'AI-DLC 专家 aidlc-architecture-reviewer-agent · 可写：只读')
    expect(within(pick).queryByTestId('kt-pick-missing')).toBeNull()
    const checks = within(pick).getAllByTestId('kt-pick-checks')
    expect(checks.map((c) => c.textContent)).toEqual(['上台架前buildstaticunitsizetrace', '台架后runtime-limitslogdiff', '签字前release'])
    expect(within(checks[0]).getByText('build')).toHaveAttribute('title', '失败没写文件时交给开发 · 修复 · 最多 3 轮')
    expect(within(pick).getByTestId('kt-pick-kb')).toHaveTextContent('知识库「vstatd」：14 份文档 · 已同步')
  })

  test('a template without its file is marked on its roles, with the fix', async () => {
    setApiRoutes({ [`GET ${API}/board*`]: () => emptyBoard(), [`GET ${API}/team`]: () => teamOf(['embedded-quality-agent']) })
    render(<TeamPage pollMs={60_000} />)
    const pick = await screen.findByLabelText('组队预览')
    const roles = within(pick).getAllByTestId('kt-pick-role')
    expect(roles.filter((r) => r.className.includes('is-absent')).map((r) => r.dataset.key)).toEqual(['tester'])
    expect(within(pick).getByTestId('kt-pick-missing')).toHaveTextContent('模板 embedded-quality-agent 不在 ~/.kiro/agents：在场景文件夹里跑 bash setup.sh')
  })
})
