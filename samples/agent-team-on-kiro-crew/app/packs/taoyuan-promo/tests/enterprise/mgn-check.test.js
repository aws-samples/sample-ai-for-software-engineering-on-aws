// 《毛利与定价规则》MGN-2、MGN-3：上线前体检里的毛利底线和预估毛利率（server/lib/pricing.js 的 check）。
import test from 'node:test'
import assert from 'node:assert/strict'
import { CANON, pricing, refCheck, withPct } from './_lib.js'

const data = { products: CANON.products, orders: CANON.orders }
const fixed = withPct(CANON.campaign, { TV65: 90, X9: 80 })

test('MGN-2: 每款的最低到手价和毛利底线', async () => {
  const { check } = await pricing()
  for (const config of [CANON.campaign, fixed]) {
    const got = check(config, data)
    const want = refCheck(config)
    assert.equal(got.items.length, want.items.length, '体检要列出配置里的每一款商品')
    for (const w of want.items) {
      const g = got.items.find((i) => i.sku === w.sku)
      assert.ok(g, `体检里没有 ${w.name}`)
      assert.equal(g.final, w.final, `${w.name} 到手价`)
      assert.equal(g.linePrice, w.linePrice, `${w.name} 划线价`)
      assert.equal(g.lowest, w.lowest, `${w.name} 最低到手价（参加满减的按到手价的 90% 算）`)
      assert.ok(Math.abs(g.floor - w.floor) < 0.01, `${w.name} 毛利底线是成本的 108%`)
      assert.equal(g.marginOk, w.marginOk, `${w.name} 是否达标`)
    }
  }
})

test('MGN-2: 方案里有低于底线的不能上线，改过的方案没有', async () => {
  const { check } = await pricing()
  const before = check(CANON.campaign, data)
  const low = before.items.filter((i) => !i.marginOk).map((i) => i.sku).sort()
  assert.deepEqual(low, [...refCheck(CANON.campaign).low].sort(), '低于毛利底线的商品')
  assert.equal(before.canLaunch, false, '有低于底线的商品，不能上线')
  for (const i of before.items.filter((x) => !x.marginOk)) {
    assert.ok(before.blockers.some((b) => b.includes(i.name)), `不能上线的原因里要写出 ${i.name}`)
  }
  assert.equal(check(fixed, data).items.every((i) => i.marginOk), true, '改过的方案每款都达标')
})

test('MGN-3: 预估毛利率', async () => {
  const { check } = await pricing()
  for (const config of [CANON.campaign, fixed]) {
    const got = check(config, data).margin
    const want = refCheck(config).margin
    assert.deepEqual(got, want, '预估毛利率（按过去 30 天已完成订单的件数，保留一位小数）')
  }
})
