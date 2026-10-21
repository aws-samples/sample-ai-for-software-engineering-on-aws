// 公司检查的公共部分：知识库数据的副本、按知识库规则写的参考算法、起一个新的服务实例、加载页面模块、读源码。不要改这个文件。
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
export const ROOT = path.resolve(HERE, '..', '..')
const json = (p) => JSON.parse(fs.readFileSync(p, 'utf8'))
export const CANON = {
  products: json(path.join(HERE, 'data', 'products.json')),
  orders: json(path.join(HERE, 'data', 'orders.json')),
  campaign: json(path.join(HERE, 'data', 'campaign.json')),
}
const BY = new Map(CANON.products.map((p) => [p.sku, p]))
export const LIMIT = 300000

// 项目里现在的活动配置（关卡上人改过的话，就是改过的）
export function currentConfig() {
  const file = path.join(ROOT, 'server', 'config', 'campaign.json')
  if (!fs.existsSync(file)) throw new Error('还没有活动配置：server/config/campaign.json（从知识库《双十一活动方案》复制）')
  return json(file)
}
export const withPct = (config, pcts) => ({ ...config, items: config.items.map((i) => (i.sku in pcts ? { ...i, pct: pcts[i.sku] } : i)) })

// ---- 参考算法：照知识库《价格与促销合规规范》《毛利与定价规则》《价保规则》 ----

// 活动开始那天（北京时间）往前第 n 天的日期 YYYY-MM-DD
export function dayBefore(startIso, n) {
  const bj = new Date(Date.parse(startIso) + 8 * 3600 * 1000)
  return new Date(Date.UTC(bj.getUTCFullYear(), bj.getUTCMonth(), bj.getUTCDate()) - n * 86400000).toISOString().slice(0, 10)
}
const done = (o, from, to) => o.status === '已完成' && o.date >= from && o.date <= to

export const refFinal = (price, pct) => Math.floor((price * pct + 50) / 100) // MGN-1，四舍五入到元
export function refLine(sku, config) { // PRC-1
  const from = dayBefore(config.start, 7), to = dayBefore(config.start, 1)
  const seen = CANON.orders.filter((o) => o.sku === sku && done(o, from, to)).map((o) => o.paid)
  return seen.length ? Math.min(...seen) : BY.get(sku).price
}
export function refCheck(config) { // PRC-5
  const from = dayBefore(config.start, 30), to = dayBefore(config.start, 1)
  const items = config.items.map((i) => {
    const p = BY.get(i.sku)
    const final = refFinal(p.price, i.pct)
    const lowest = i.fullReduction ? Math.floor((final * 9 + 5) / 10) : final
    return { sku: i.sku, name: p.name, price: p.price, cost: p.cost, pct: i.pct, final, linePrice: refLine(i.sku, config),
      linePriceInput: i.linePriceInput, fullReduction: i.fullReduction, lowest, floor: p.cost * 1.08, marginOk: lowest * 100 >= p.cost * 108 }
  })
  const fin = new Map(items.map((i) => [i.sku, i.final]))
  const bySku = items.map((i) => ({ sku: i.sku, name: i.name, orders: 0, amount: 0 }))
  const at = new Map(bySku.map((s) => [s.sku, s]))
  let units = new Map()
  for (const o of CANON.orders) {
    if (!done(o, from, to) || !fin.has(o.sku)) continue
    units.set(o.sku, (units.get(o.sku) || 0) + o.qty)
    if (BY.get(o.sku).priceProtect && o.paid > fin.get(o.sku)) {
      const s = at.get(o.sku)
      s.orders += 1
      s.amount += (o.paid - fin.get(o.sku)) * o.qty
    }
  }
  const amount = bySku.reduce((n, s) => n + s.amount, 0)
  const orders = bySku.reduce((n, s) => n + s.orders, 0)
  const rate = (price) => {
    let gain = 0, sales = 0
    for (const i of items) {
      const u = units.get(i.sku) || 0
      gain += (price(i) - i.cost) * u
      sales += price(i) * u
    }
    return Math.round((gain / sales) * 1000) / 10
  }
  const low = items.filter((i) => !i.marginOk)
  return {
    items, priceProtect: { orders, amount, limit: LIMIT, needsCfo: amount > LIMIT, bySku },
    margin: { usual: rate((i) => i.price), campaign: rate((i) => i.final) },
    low: low.map((i) => i.sku), blockers: low.length + (amount > LIMIT ? 1 : 0),
  }
}

// ---- 调用项目的代码 ----

export const pricing = () => import(pathToFileURL(path.join(ROOT, 'server', 'lib', 'pricing.js')).href)
export const page = (name) => import(pathToFileURL(path.join(ROOT, 'web', 'pages', `${name}.js`)).href)
export const motion = () => import(pathToFileURL(path.join(ROOT, 'web', 'motion', 'motion.js')).href)
export const read = (rel) => (fs.existsSync(path.join(ROOT, rel)) ? fs.readFileSync(path.join(ROOT, rel), 'utf8') : '')

// 每个用例自己起一个新的服务（活动配置和状态在服务进程里，互不影响），用完 close()。config 不传就用项目里的
export async function startServer({ config } = {}) {
  const { createApp } = await import(pathToFileURL(path.join(ROOT, 'server', 'app.js')).href)
  const srv = createApp(config ? { config: structuredClone(config), clock: () => Date.parse('2026-11-01T20:00:00+08:00') } : { clock: () => Date.parse('2026-11-01T20:00:00+08:00') })
  await new Promise((resolve) => srv.listen(0, '127.0.0.1', resolve))
  srv.unref() // 忘了 close() 的服务（比如断言在 close 之前失败了）也不会让测试进程一直不退出
  const base = `http://127.0.0.1:${srv.address().port}`
  const req = async (method, p, body) => {
    const res = await fetch(base + p, {
      method,
      headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
    const text = await res.text()
    let data = null
    try { data = JSON.parse(text) } catch { /* not JSON */ }
    return { status: res.status, json: data, text }
  }
  return {
    get: (p) => req('GET', p),
    post: (p, body = {}) => req('POST', p, body),
    put: (p, body = {}) => req('PUT', p, body),
    close: () => new Promise((resolve) => srv.close(resolve)),
  }
}

export function files(rel, exts) {
  const out = []
  const walk = (dir) => {
    if (!fs.existsSync(dir)) return
    for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
      const p = path.join(dir, ent.name)
      if (ent.isDirectory()) walk(p)
      else if (exts.some((x) => ent.name.endsWith(x))) out.push({ file: path.relative(ROOT, p), text: fs.readFileSync(p, 'utf8') })
    }
  }
  walk(path.join(ROOT, rel))
  return out
}

// 写死的颜色值（品牌规范：颜色只用 tokens.css 的变量）
export const RAW_COLOR = /#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?)\(\s*\d/
// 一段 HTML 里，每个 data-sku 后面到下一个 data-sku 之前的那一段
export function bySku(html) {
  const out = new Map()
  const marks = [...html.matchAll(/data-sku="([^"]+)"/g)]
  marks.forEach((m, i) => { if (!out.has(m[1])) out.set(m[1], html.slice(m.index, i + 1 < marks.length ? marks[i + 1].index : html.length)) })
  return out
}
// 元素里的数字（¥4,319 → 4319）
export const num = (s) => Number(String(s).replace(/[^\d.-]/g, ''))
export const textOf = (seg, attr) => (seg.match(new RegExp(`${attr}[^>]*>([^<]*)`)) || [])[1] ?? null
