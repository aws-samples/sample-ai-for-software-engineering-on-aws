import { describe, expect, it } from 'vitest'
import { runningBoard } from '../test/fixtures'
import { clip, fmtAgo, fmtClock, fmtCredits, fmtSpan, parseScore, saving, textWidth, waitingText } from './format'
import { continuation } from './hooks'

describe('format', () => {
  it('formats clocks, spans and ages', () => {
    expect(fmtClock(5)).toBe('0:05')
    expect(fmtClock(1500)).toBe('25:00')
    expect(fmtClock(3723)).toBe('1:02:03')
    expect(fmtSpan(45)).toBe('45 秒')
    expect(fmtSpan(1400)).toBe('23 分钟')
    expect(fmtSpan(3900)).toBe('1 小时 5 分')
    expect(fmtAgo(2)).toBe('刚刚')
    expect(fmtAgo(31)).toBe('31 秒前')
    expect(fmtAgo(185)).toBe('3 分钟前')
    expect(fmtCredits(null)).toBe('—')
    expect(fmtCredits(66.5)).toBe('66.5')
  })

  it('the parallel saving of the fixture is serial − wall: 23 minutes, ×1.9', () => {
    const r = runningBoard().run!
    const s = saving(r)
    expect(s.saved_s).toBe(1400)
    expect(fmtSpan(s.saved_s)).toBe('23 分钟')
    expect(s.speedup).toBeCloseTo(1.93, 2)
    expect(saving({ wall_s: 100, serial_s: 80 }).saved_s).toBe(0)
  })

  it('says what a waiting lane waits for: its dependencies not merged yet', () => {
    const r = runningBoard().run!
    const reviewer = r.roles.find((l) => l.key === 'reviewer')!
    expect(waitingText(reviewer, r.roles)).toBe('等 后端、前端、运维')
    const tester = { depends_on: ['architect'] }
    expect(waitingText(tester, r.roles)).toBe('上游都合并了，马上开工')
  })

  it('parses a tests event score and clips by rendered width', () => {
    expect(parseScore('测试 7/12')).toEqual({ passed: 7, total: 12 })
    expect(parseScore('测试 0/12：实现还没写，全红')).toEqual({ passed: 0, total: 12 })
    expect(parseScore('没有分数')).toBeNull()
    expect(clip('等 后端、前端、运维', 8)).toMatch(/…$/)
    expect(textWidth(clip('Editing frontend/app.js and much more text', 12))).toBeLessThanOrEqual(12)
  })
})

describe('continuation (the typewriter types only what is new)', () => {
  it('finds the new end of a growing or sliding tail', () => {
    expect(continuation('abc', 'abcdef')).toEqual(['abc', 'def'])
    const prev = 'the agent is writing a long line about AC-6 and'
    const next = 'is writing a long line about AC-6 and then AC-7'
    expect(continuation(prev, next)).toEqual(['is writing a long line about AC-6 and', ' then AC-7'])
    expect(continuation('something else entirely', 'a new text altogether')).toBeNull()
    expect(continuation('same', 'same')).toEqual(['same', ''])
  })
})
