// 《价格与促销合规规范》PRC-2、PRC-3、PRC-4 和《前端工程规范》FE-1、FE-3、UX-4：双十一活动页（web/pages/campaign.js、web/styles/campaign.css）。
import test from 'node:test'
import assert from 'node:assert/strict'
import { CANON, bySku, num, page, read, refCheck, textOf, RAW_COLOR } from './_lib.js'

const want = refCheck(CANON.campaign).items
const items = want.map((i) => {
  const p = CANON.products.find((x) => x.sku === i.sku)
  return { sku: i.sku, name: i.name, category: p.category, price: i.price, linePrice: i.linePrice, final: i.final, pct: i.pct, fullReduction: i.fullReduction, stock: p.stock }
})
const campaign = (status) => ({ name: CANON.campaign.name, start: CANON.campaign.start, end: CANON.campaign.end, status, fullReduction: CANON.campaign.fullReduction })
const state = (status) => ({ status: 'ready', campaign: campaign(status), items, now: Date.parse('2026-11-01T20:00:00+08:00'), cart: null })

test('PRC-2: 每款商品的到手价、划线价，划线价旁边写明是活动前 7 日最低价', async () => {
  const { render } = await page('campaign')
  const out = render(state('live'))
  assert.equal(typeof out, 'string', 'render 要返回字符串')
  const cards = bySku(out)
  for (const i of items) {
    const seg = cards.get(i.sku)
    assert.ok(seg, `活动页上没有 ${i.name}（卡片要带 data-sku="${i.sku}"）`)
    assert.equal(num(textOf(seg, 'data-final')), i.final, `${i.name} 的到手价（data-final）`)
    assert.equal(num(textOf(seg, 'data-line')), i.linePrice, `${i.name} 的划线价（data-line）`)
  }
  const notes = (out.match(/活动前\s*7\s*日最低/g) || []).length
  assert.ok(notes >= 1, '划线价旁边要写明「活动前 7 日最低价」')
  for (const i of items) assert.match(cards.get(i.sku), /活动前\s*7\s*日最低|data-line-note/, `${i.name} 的划线价旁边没有说明`)
})

test('PRC-3: 满减规则写全：门槛、金额、能否叠加折扣和优惠券', async () => {
  const { render } = await page('campaign')
  const out = render(state('live')).replace(/,/g, '')
  const { every, off } = CANON.campaign.fullReduction
  assert.match(out, new RegExp(`满\\s*${every}\\s*减\\s*${off}`), `要写明「每满 ${every} 减 ${off}」`)
  assert.match(out, /折扣/, '要写明能不能和折扣叠加')
  assert.match(out, /优惠券/, '要写明能不能和优惠券叠加')
  assert.doesNotMatch(out, /全网最低|史上最低|巨划算/, '不能用「全网最低」这类说法')
})

test('PRC-4: 倒计时按活动结束时间；没上线不能下单', async () => {
  const { render } = await page('campaign')
  const live = render(state('live'))
  assert.match(live, new RegExp(`data-countdown[^>]*data-end="${CANON.campaign.end.replace(/\+/g, '\\+')}"|data-end="${CANON.campaign.end.replace(/\+/g, '\\+')}"[^>]*data-countdown`), '倒计时元素要带 data-countdown 和 data-end="<活动结束时间>"')
  assert.ok((live.match(/data-action="add"/g) || []).length >= items.length, '上线后每款商品都能加购（data-action="add"）')
  const draft = render(state('draft'))
  assert.doesNotMatch(draft, /data-action="add"/, '活动还没上线，不能有加购按钮')
  assert.match(draft, /还没上线|未上线|还没开始|即将开始|敬请期待/, '活动还没上线要说清楚')
})

test('FE-1、FE-3: 没有内联脚本和内联事件，商品名转义', async () => {
  const { render } = await page('campaign')
  const evil = items.map((i, n) => (n === 0 ? { ...i, name: '<img src=x onerror=alert(1)>' } : i))
  for (const s of [{ status: 'loading', campaign: null, items: [], now: 0, cart: null }, { status: 'error', campaign: null, items: [], now: 0, cart: null, error: '网络不太好' }, { ...state('live'), items: evil }]) {
    const out = render(s)
    assert.doesNotMatch(out, /<script/i, `${s.status}：页面里有 <script>`)
    assert.doesNotMatch(out, /<[^>]*\son[a-z]+\s*=/i, `${s.status}：页面里有 onclick= 这类内联事件`)
  }
  const out = render({ ...state('live'), items: evil })
  assert.ok(!out.includes('<img src=x') && out.includes('&lt;img'), '商品名要转义后显示')
  assert.match(render({ status: 'error', campaign: null, items: [], now: 0, cart: null, error: '网络不太好' }), /网络不太好/, '出错时显示错误信息')
})

test('UX-4: 活动页样式只用品牌变量', () => {
  const css = read('web/styles/campaign.css')
  assert.ok(css.split('\n').length > 5, 'web/styles/campaign.css 还没写')
  const bad = css.split('\n').filter((ln) => RAW_COLOR.test(ln))
  assert.deepEqual(bad, [], 'campaign.css 里写死了颜色：用 tokens.css 的 var(--brand-…)')
})
