// 《个人信息展示规范》PII-1、PII-3：接口返回和导出文件里不出现完整的 11 位手机号。
import test from 'node:test'
import assert from 'node:assert/strict'
import { FULL_PHONE, routes, startServer } from './_lib.js'

test('PII-1: 不带参数的 GET 接口（含导出）返回里没有完整手机号', async () => {
  const list = (await routes()).filter((r) => r.method === 'GET' && !String(r.path).includes(':'))
  const s = await startServer()
  try {
    for (const r of list) {
      const res = await s.get(r.path)
      assert.doesNotMatch(res.text, FULL_PHONE, `GET ${r.path} 返回了完整手机号（只能显示前 3 位和后 4 位，如 199****1234）`)
    }
  } finally {
    await s.close()
  }
})
