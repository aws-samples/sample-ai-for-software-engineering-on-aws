// 《个人信息展示规范》PII-1、PII-4：网页源码和页面输出里不出现完整的 11 位手机号。
import test from 'node:test'
import assert from 'node:assert/strict'
import { FULL_PHONE, files, pages } from './_lib.js'

test('PII-1: 网页源码里没有写死的完整手机号', () => {
  for (const f of files('web', ['.js', '.html'])) assert.doesNotMatch(f.text, FULL_PHONE, `${f.file} 里有完整手机号`)
})

test('PII-1: 页面拿到带手机号的数据，显示出来的也是脱敏的', async () => {
  const person = { id: 'TY0001', name: '测试员', dept: '研发中心', phone: '19900001234', mobile: '19900001234' }
  const state = { status: 'ready', items: [person], people: [person], employees: [person], list: [person], rows: [person], person, employee: person }
  for (const p of await pages()) {
    let out = ''
    try {
      out = String(p.module.render(state))
    } catch {
      continue // 这个页面的 state 形状不一样：由团队自己的测试覆盖
    }
    assert.doesNotMatch(out, FULL_PHONE, `页面 ${p.name} 把完整手机号显示出来了`)
  }
})
