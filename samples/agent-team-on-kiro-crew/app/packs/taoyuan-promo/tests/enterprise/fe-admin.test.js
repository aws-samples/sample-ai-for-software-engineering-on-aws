// 《价格与促销合规规范》PRC-5 和《前端工程规范》FE-1、UX-4：运营后台（web/pages/admin.js、web/styles/admin.css）。
import test from 'node:test'
import assert from 'node:assert/strict'
import { CANON, bySku, page, read, refCheck, withPct, RAW_COLOR } from './_lib.js'

// 用参考算法造出和接口一样外形的体检结果
function checkOf(config, status = 'draft') {
  const r = refCheck(config)
  const items = r.items
  const blockers = [
    ...items.filter((i) => !i.marginOk).map((i) => `${i.name} 最低到手价 ¥${i.lowest} 低于毛利底线 ¥${i.floor.toFixed(0)}（MGN-2）`),
    ...(r.priceProtect.needsCfo ? [`价保退差 ¥${r.priceProtect.amount} 超过 ¥300,000，要 CFO 审批（PP-2）`] : []),
  ]
  return { status, campaign: { name: config.name, start: config.start, end: config.end }, items, priceProtect: r.priceProtect, margin: r.margin, blockers, canLaunch: blockers.length === 0 }
}
const blocked = checkOf(CANON.campaign)
const ok = checkOf(withPct(CANON.campaign, { TV65: 90, X9: 80 }))

test('PRC-5: 每款一行，看得出哪款不达标，能改折扣和满减', async () => {
  const { render } = await page('admin')
  const out = render({ status: 'ready', check: blocked })
  assert.equal(typeof out, 'string', 'render 要返回字符串')
  const rows = bySku(out)
  for (const i of blocked.items) {
    const seg = rows.get(i.sku)
    assert.ok(seg, `后台没有 ${i.name} 这一行（data-sku="${i.sku}"）`)
    assert.match(seg, new RegExp(`data-ok="${i.marginOk}"`), `${i.name} 这一行要带 data-ok="${i.marginOk}"`)
    assert.match(seg, new RegExp(`<input[^>]*data-pct[^>]*value="${i.pct}"|<input[^>]*value="${i.pct}"[^>]*data-pct`), `${i.name} 的折扣输入框（data-pct，value="${i.pct}"）`)
    assert.match(seg, /<input[^>]*type="checkbox"[^>]*data-fr|<input[^>]*data-fr[^>]*type="checkbox"/, `${i.name} 的满减开关（checkbox，data-fr）`)
  }
})

test('PRC-5: 不能上线时写明原因、价保金额，上线按钮不能点；体检过了能点', async () => {
  const { render } = await page('admin')
  const out = render({ status: 'ready', check: blocked })
  const list = out.match(/data-blockers[\s\S]*?(?=data-pp|data-action="launch"|$)/)?.[0] || ''
  assert.ok(list, '不能上线的原因列表要带 data-blockers')
  for (const b of blocked.blockers) assert.ok(out.includes(b.split('（')[0].slice(0, 12)), `原因没显示：${b}`)
  assert.match(out.replace(/,/g, ''), new RegExp(`data-pp[\\s\\S]*?${blocked.priceProtect.amount}`), `价保汇总（data-pp）要显示退差 ${blocked.priceProtect.amount} 元`)
  assert.match(out, /<button[^>]*data-action="launch"[^>]*disabled|<button[^>]*disabled[^>]*data-action="launch"/, '体检没过，上线按钮要 disabled')
  const good = render({ status: 'ready', check: ok })
  assert.match(good, /<button[^>]*data-action="launch"/, '要有上线按钮')
  assert.doesNotMatch(good, /<button[^>]*data-action="launch"[^>]*disabled|<button[^>]*disabled[^>]*data-action="launch"/, '体检过了，上线按钮能点')
})

test('FE-1: 没有内联脚本和内联事件', async () => {
  const { render } = await page('admin')
  for (const s of [{ status: 'loading', check: null }, { status: 'error', check: null, error: '网络不太好' }, { status: 'ready', check: blocked }, { status: 'saving', check: ok }, { status: 'ready', check: { ...ok, status: 'live' } }]) {
    const out = render(s)
    assert.doesNotMatch(out, /<script/i, `${s.status}：页面里有 <script>`)
    assert.doesNotMatch(out, /<[^>]*\son[a-z]+\s*=/i, `${s.status}：页面里有 onclick= 这类内联事件`)
  }
})

test('UX-4: 后台样式只用品牌变量', () => {
  const css = read('web/styles/admin.css')
  assert.ok(css.split('\n').length > 5, 'web/styles/admin.css 还没写')
  const bad = css.split('\n').filter((ln) => RAW_COLOR.test(ln))
  assert.deepEqual(bad, [], 'admin.css 里写死了颜色：用 tokens.css 的 var(--brand-…)')
})
