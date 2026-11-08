import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import type { ModelChoice } from '../types'
import { modelLabel, StartForm, type StartOptions } from './Header'

const MODELS: ModelChoice[] = [
  { id: 'claude-sonnet-5.5', name: 'claude-sonnet-5.5', description: 'Claude Sonnet 5.5 model with 1M context window', rate: 1.3 },
  { id: 'kimi-k3', name: 'kimi-k3', description: 'Kimi K3 is a Kiro Excluded Model. For more info, see documentation.', rate: 2.4 },
]

test("the start form offers Kiro Crew's models, says what the picked one is, and the run takes it", async () => {
  const onStart = vi.fn(async (_requirement: string, _opts?: StartOptions) => {})
  render(<StartForm onStart={onStart} models={async () => MODELS} />)
  const select = await screen.findByLabelText(/模型/)
  expect(screen.getByRole('option', { name: 'kimi-k3 · 2.4x credits' })).toBeInTheDocument()
  await userEvent.selectOptions(select, 'kimi-k3')
  expect(screen.getByText(/Kiro Excluded Model/)).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: '交给团队' }))
  await waitFor(() => expect(onStart).toHaveBeenCalled())
  expect(onStart.mock.calls[0][1]).toMatchObject({ model: 'kimi-k3' })
})

test("left on 按团队设置, or with no list from Kiro Crew, the run takes the team file's models", async () => {
  const onStart = vi.fn(async (_requirement: string, _opts?: StartOptions) => {})
  const { unmount } = render(<StartForm onStart={onStart} models={async () => MODELS} />)
  await screen.findByLabelText(/模型/)
  await userEvent.click(screen.getByRole('button', { name: '交给团队' }))
  await waitFor(() => expect(onStart).toHaveBeenCalled())
  expect(onStart.mock.calls[0][1]).not.toHaveProperty('model')
  unmount()
  const models = vi.fn(async () => [] as ModelChoice[])
  render(<StartForm onStart={onStart} models={models} />)
  await waitFor(() => expect(models).toHaveBeenCalled())
  expect(screen.queryByLabelText(/模型/)).toBeNull()
})

test('a model shows its credit rate when Kiro gives one', () => {
  expect(modelLabel(MODELS[1])).toBe('kimi-k3 · 2.4x credits')
  expect(modelLabel({ id: 'auto', name: 'auto', description: '', rate: null })).toBe('auto')
})
