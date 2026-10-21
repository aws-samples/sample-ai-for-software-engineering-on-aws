// 《价格与促销合规规范》PRC-1、《毛利与定价规则》MGN-1：划线价和到手价（server/lib/pricing.js）。
import test from 'node:test'
import assert from 'node:assert/strict'
import { CANON, pricing, refFinal, refLine } from './_lib.js'

const data = { products: CANON.products, orders: CANON.orders }

test('MGN-1: 到手价 = 日常价 × 折扣，四舍五入到元', async () => {
  const { finalPrice } = await pricing()
  for (const [price, pct] of [[5399, 80], [5399, 90], [2999, 70], [3299, 85], [1990, 85], [699, 100]]) {
    assert.equal(finalPrice(price, pct), refFinal(price, pct), `finalPrice(${price}, ${pct}) 应该是 ${refFinal(price, pct)}`)
  }
})

test('PRC-1: 划线价取活动前 7 天的最低成交价，不用运营填的', async () => {
  const { linePrice } = await pricing()
  for (const p of CANON.products) {
    assert.equal(linePrice(p.sku, data, CANON.campaign), refLine(p.sku, CANON.campaign), `${p.name} 的划线价不对`)
  }
  const moved = CANON.products.filter((p) => refLine(p.sku, CANON.campaign) !== p.price).map((p) => p.sku)
  assert.ok(moved.length >= 3, '数据里有几款商品活动前 7 天卖过更低的价')
})

test('PRC-1: 7 天以外的低价、退货的订单都不算', async () => {
  const { linePrice } = await pricing()
  const sku = 'TV65'
  const extra = [
    { id: 'X1', sku, paid: 1999, qty: 1, date: '2026-10-24', status: '已完成' }, // 第 8 天
    { id: 'X2', sku, paid: 2999, qty: 1, date: '2026-10-30', status: '已退货' },
  ]
  const got = linePrice(sku, { products: CANON.products, orders: [...CANON.orders, ...extra] }, CANON.campaign)
  assert.equal(got, refLine(sku, CANON.campaign), '7 天以外的、退货的订单不能拿来做划线价')
})
