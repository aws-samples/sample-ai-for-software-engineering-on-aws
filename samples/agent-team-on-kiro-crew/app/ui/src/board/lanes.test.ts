import { describe, expect, it } from 'vitest'
import type { TestCase } from '../types'
import { groupCases } from './Lanes'

const tc = (id: string, ac: string | null, status: TestCase['status']): TestCase => ({ id, ac, name: `${ac ?? id}: 用例 ${id}`, file: 'tests/api-x.test.js', status, owner: 'backend', ms: 1, message: status === 'fail' ? 'expected 409' : null })

describe('owned tests on a role card', () => {
  it('one chip per criterion, red when any of its cases fails, with the case count', () => {
    const g = groupCases([tc('a', 'AC-1', 'pass'), tc('b', 'AC-1', 'fail'), tc('c', 'AC-1', 'pass'), tc('d', 'AC-2', 'pass'), tc('e', null, 'skip')])
    expect(g.map((x) => [x.key, x.status, x.count])).toEqual([['AC-1', 'fail', 3], ['AC-2', 'pass', 1], ['e: 用例 e', 'skip', 1]])
    expect(g[0].titles[1]).toBe('✗ AC-1: 用例 b：expected 409')
  })
})
