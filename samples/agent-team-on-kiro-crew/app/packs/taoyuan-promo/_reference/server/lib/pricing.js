// 参考实现：价格引擎（PRC-1、PRC-5、MGN-1～3、PP-1、PP-2）。
const LIMIT = 300000

function dayBefore(startIso, n) {
  const bj = new Date(Date.parse(startIso) + 8 * 3600 * 1000)
  return new Date(Date.UTC(bj.getUTCFullYear(), bj.getUTCMonth(), bj.getUTCDate()) - n * 86400000).toISOString().slice(0, 10)
}
const done = (o, from, to) => o.status === '已完成' && o.date >= from && o.date <= to

export function finalPrice(price, pct) {
  return Math.round((price * pct) / 100)
}

export function linePrice(sku, data, config) {
  const from = dayBefore(config.start, 7)
  const to = dayBefore(config.start, 1)
  const seen = data.orders.filter((o) => o.sku === sku && done(o, from, to)).map((o) => o.paid)
  return seen.length ? Math.min(...seen) : data.products.find((p) => p.sku === sku).price
}

export function check(config, data) {
  const by = new Map(data.products.map((p) => [p.sku, p]))
  const items = config.items.map((i) => {
    const p = by.get(i.sku)
    const final = finalPrice(p.price, i.pct)
    const lowest = i.fullReduction ? Math.round(final * 0.9) : final
    const floor = p.cost * 1.08
    return { sku: i.sku, name: p.name, price: p.price, cost: p.cost, pct: i.pct, final, linePrice: linePrice(i.sku, data, config),
      linePriceInput: i.linePriceInput, fullReduction: i.fullReduction, lowest, floor, marginOk: lowest * 100 >= p.cost * 108 }
  })
  const from = dayBefore(config.start, 30)
  const to = dayBefore(config.start, 1)
  const fin = new Map(items.map((i) => [i.sku, i.final]))
  const bySku = items.map((i) => ({ sku: i.sku, name: i.name, orders: 0, amount: 0 }))
  const at = new Map(bySku.map((s) => [s.sku, s]))
  const units = new Map()
  for (const o of data.orders) {
    if (!done(o, from, to) || !fin.has(o.sku)) continue
    units.set(o.sku, (units.get(o.sku) || 0) + o.qty)
    if (by.get(o.sku).priceProtect && o.paid > fin.get(o.sku)) {
      at.get(o.sku).orders += 1
      at.get(o.sku).amount += (o.paid - fin.get(o.sku)) * o.qty
    }
  }
  const amount = bySku.reduce((n, s) => n + s.amount, 0)
  const rate = (price) => {
    let gain = 0, sales = 0
    for (const i of items) {
      const u = units.get(i.sku) || 0
      gain += (price(i) - i.cost) * u
      sales += price(i) * u
    }
    return Math.round((gain / sales) * 1000) / 10
  }
  const blockers = [
    ...items.filter((i) => !i.marginOk).map((i) => `${i.name} 最低到手价 ¥${i.lowest} 低于毛利底线 ¥${Math.round(i.floor)}（MGN-2）`),
    ...(amount > LIMIT ? [`价保退差 ¥${amount.toLocaleString('zh-CN')} 超过 ¥300,000，要 CFO 审批（PP-2）`] : []),
  ]
  return {
    campaign: { name: config.name, start: config.start, end: config.end },
    items,
    priceProtect: { orders: bySku.reduce((n, s) => n + s.orders, 0), amount, limit: LIMIT, needsCfo: amount > LIMIT, bySku },
    margin: { usual: rate((i) => i.price), campaign: rate((i) => i.final) },
    blockers,
    canLaunch: blockers.length === 0,
  }
}

export function quote(items, config, data) {
  const by = new Map(data.products.map((p) => [p.sku, p]))
  const cfg = new Map(config.items.map((i) => [i.sku, i]))
  const lines = items.map(({ sku, qty }) => {
    const p = by.get(sku)
    const final = finalPrice(p.price, cfg.get(sku).pct)
    return { sku, name: p.name, qty, final, subtotal: final * qty, fullReduction: cfg.get(sku).fullReduction }
  })
  const subtotal = lines.reduce((n, l) => n + l.subtotal, 0)
  const base = lines.filter((l) => l.fullReduction).reduce((n, l) => n + l.subtotal, 0)
  const off = Math.floor(base / config.fullReduction.every) * config.fullReduction.off
  return { lines, subtotal, off, total: subtotal - off }
}
