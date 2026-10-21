// 接口约定（README「接口约定」）、《价格与促销合规规范》PRC-4、PRC-5：活动、体检、改折扣、上线、购物车算价。
import test from 'node:test'
import assert from 'node:assert/strict'
import { CANON, currentConfig, refCheck, refFinal, startServer, withPct } from './_lib.js'

const fixed = withPct(CANON.campaign, { TV65: 90, X9: 80 })

test('DATA-2: 活动配置从知识库方案复制来，只有折扣可以按人的决定改', () => {
  const c = currentConfig()
  for (const k of ['name', 'start', 'end', 'fullReduction']) assert.deepEqual(c[k], CANON.campaign[k], `server/config/campaign.json 的 ${k} 和知识库方案不一样`)
  assert.deepEqual(c.items.map((i) => i.sku), CANON.campaign.items.map((i) => i.sku), '商品和顺序要和方案一样')
  for (const i of c.items) assert.ok(Number.isInteger(i.pct) && i.pct >= 50 && i.pct <= 100, `${i.sku} 的折扣要是 50～100 的整数`)
})

test('PRC-4: 服务器时间；活动和体检接口', async () => {
  const s = await startServer()
  try {
    const t = await s.get('/api/time')
    assert.equal(t.status, 200)
    assert.equal(Date.parse(t.json.now), Date.parse('2026-11-01T20:00:00+08:00'), '/api/time 要用 ctx.now()')
    const c = await s.get('/api/campaign')
    assert.equal(c.status, 200)
    assert.equal(c.json.campaign.status, 'draft', '刚启动时活动还没上线')
    const want = refCheck(currentConfig())
    assert.equal(c.json.items.length, want.items.length)
    for (const w of want.items) {
      const g = c.json.items.find((i) => i.sku === w.sku)
      assert.deepEqual([g?.final, g?.linePrice], [w.final, w.linePrice], `${w.name} 的到手价和划线价`)
    }
    const k = await s.get('/api/campaign/check')
    assert.equal(k.status, 200)
    assert.equal(k.json.status, 'draft')
    assert.equal(k.json.priceProtect.amount, want.priceProtect.amount, '体检接口的价保退差')
  } finally {
    await s.close()
  }
})

test('PRC-5: 改折扣：输入不对 400，没有这款 404，改完返回新的体检', async () => {
  const s = await startServer({ config: CANON.campaign })
  try {
    for (const body of [{ pct: 45 }, { pct: 85.5 }, { pct: '80' }, { fullReduction: 'yes' }]) {
      const r = await s.put('/api/campaign/items/TV65', body)
      assert.equal(r.status, 400, `${JSON.stringify(body)} 应该是 400`)
      assert.ok(r.json?.error?.message, '错误要有中文说明')
    }
    assert.equal((await s.put('/api/campaign/items/NOPE', { pct: 80 })).status, 404)
    const r = await s.put('/api/campaign/items/TV65', { pct: 90 })
    assert.equal(r.status, 200)
    const tv = r.json.items.find((i) => i.sku === 'TV65')
    assert.equal(tv.final, refFinal(5399, 90), '改完 TV65 的到手价')
    assert.equal(r.json.priceProtect.amount, refCheck(withPct(CANON.campaign, { TV65: 90 })).priceProtect.amount, '改完重新算价保')
  } finally {
    await s.close()
  }
})

test('PRC-5: 体检没过不能上线，过了可以；上线后不能再改', async () => {
  const blocked = await startServer({ config: CANON.campaign })
  try {
    const r = await blocked.post('/api/campaign/launch')
    assert.equal(r.status, 409, '体检没过，上线应该是 409')
    assert.equal(r.json?.error?.code, 'blocked')
    assert.match(r.json?.error?.message || '', /CFO|毛利/, '409 要写明为什么不能上线')
  } finally {
    await blocked.close()
  }
  const ok = await startServer({ config: fixed })
  try {
    const r = await ok.post('/api/campaign/launch')
    assert.equal(r.status, 200, `体检过了应该能上线：${r.text.slice(0, 200)}`)
    assert.equal(r.json.campaign.status, 'live')
    assert.equal((await ok.get('/api/campaign')).json.campaign.status, 'live')
    assert.equal((await ok.post('/api/campaign/launch')).status, 409, '已经上线了再上线是 409')
    assert.equal((await ok.put('/api/campaign/items/TV65', { pct: 85 })).status, 409, '上线后不能改折扣')
  } finally {
    await ok.close()
  }
})

test('PRC-4: 购物车：没上线不按活动价算；上线后满减算对', async () => {
  const s = await startServer({ config: fixed })
  try {
    const items = [{ sku: 'TV65', qty: 1 }, { sku: 'RF300', qty: 1 }, { sku: 'T1', qty: 1 }]
    const early = await s.post('/api/cart/quote', { items })
    assert.equal(early.status, 409, '活动还没上线，不能按活动价算（PRC-4）')
    assert.equal(early.json?.error?.code, 'not_live')
    await s.post('/api/campaign/launch')
    const r = await s.post('/api/cart/quote', { items })
    assert.equal(r.status, 200, r.text.slice(0, 200))
    const want = refCheck(fixed).items
    const f = (sku) => want.find((i) => i.sku === sku)
    const subtotal = items.reduce((n, i) => n + f(i.sku).final * i.qty, 0)
    const frBase = items.filter((i) => f(i.sku).fullReduction).reduce((n, i) => n + f(i.sku).final * i.qty, 0)
    const off = Math.floor(frBase / fixed.fullReduction.every) * fixed.fullReduction.off
    assert.deepEqual([r.json.subtotal, r.json.off, r.json.total], [subtotal, off, subtotal - off], '小计、满减、合计（手机不参加满减）')
    assert.equal((await s.post('/api/cart/quote', { items: [] })).status, 400, '空购物车是 400')
    assert.equal((await s.post('/api/cart/quote', { items: [{ sku: 'TV65', qty: 0 }] })).status, 400, '件数要是正整数')
    assert.equal((await s.post('/api/cart/quote', { items: [{ sku: 'NOPE', qty: 1 }] })).status, 404)
  } finally {
    await s.close()
  }
})
