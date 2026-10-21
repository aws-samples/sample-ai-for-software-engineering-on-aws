// 《价保规则》PP-1、PP-2：上线前体检里的价保退差（server/lib/pricing.js 的 check）。
import test from 'node:test'
import assert from 'node:assert/strict'
import { CANON, LIMIT, pricing, refCheck, withPct } from './_lib.js'

const data = { products: CANON.products, orders: CANON.orders }
const fixed = withPct(CANON.campaign, { TV65: 90, X9: 80 })

test('PP-1: 价保退差按单算：30 天内、已完成、有价保、比到手价贵的', async () => {
  const { check } = await pricing()
  for (const config of [CANON.campaign, fixed]) {
    const got = check(config, data).priceProtect
    const want = refCheck(config).priceProtect
    assert.equal(got.amount, want.amount, '退差合计（元）')
    assert.equal(got.orders, want.orders, '要退差的单数')
    for (const w of want.bySku) {
      const g = got.bySku.find((s) => s.sku === w.sku)
      assert.ok(g, `bySku 里没有 ${w.sku}`)
      assert.deepEqual([g.orders, g.amount], [w.orders, w.amount], `${w.name} 的退差`)
    }
  }
})

test('PP-2: 退差超过 30 万要 CFO 审批，不能直接上线', async () => {
  const { check } = await pricing()
  const before = check(CANON.campaign, data)
  assert.equal(before.priceProtect.limit, LIMIT)
  assert.equal(before.priceProtect.needsCfo, true, `方案的退差 ${refCheck(CANON.campaign).priceProtect.amount} 元超过 30 万`)
  assert.ok(before.blockers.some((b) => /CFO/.test(b)), '不能上线的原因里要写明要 CFO 审批')
  const after = check(fixed, data)
  assert.equal(after.priceProtect.needsCfo, false, '改过的方案退差在 30 万以内')
  assert.deepEqual([after.canLaunch, after.blockers], [true, []], '改过的方案可以上线')
})
