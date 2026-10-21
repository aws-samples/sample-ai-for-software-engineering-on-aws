// 上线前体检（模板自带）：按 server/config/campaign.json 和 server/data/ 跑一遍价格引擎的 check()，把结果用中文打出来。
//
//   npm run check-campaign            看结论和原因
//   npm run check-campaign -- --json  原样输出 check() 的结果
//
// 合规审查、部署工程师和运营负责人都用它看「能不能上线」。价格引擎（server/lib/pricing.js）没实现的时候会报错。
import { loadData, loadConfig } from '../server/lib/data.js'
import { check } from '../server/lib/pricing.js'

const yuan = (n) => `¥${Math.round(n).toLocaleString('zh-CN')}`
const config = loadConfig()
if (!config) {
  console.error('还没有活动配置：server/config/campaign.json')
  process.exit(1)
}
const r = check(config, loadData())
if (process.argv.includes('--json')) {
  console.log(JSON.stringify(r, null, 2))
  process.exit(0)
}
const adjusted = r.items.filter((i) => i.linePrice !== i.linePriceInput)
const low = r.items.filter((i) => !i.marginOk)
const pp = r.priceProtect
console.log(`${r.campaign.name} · 上线前体检（按 server/config/campaign.json）`)
console.log(`  商品 ${r.items.length} 款`)
console.log(`  划线价：${adjusted.length ? `${adjusted.length} 款按活动前 7 日最低成交价调整（PRC-1）：` + adjusted.map((i) => `${i.name} ${yuan(i.linePriceInput)}→${yuan(i.linePrice)}`).join('；') : '都等于运营填的'}`)
console.log(`  毛利底线（MGN-2）：${low.length ? `${low.length} 款不达标：` + low.map((i) => `${i.name}（最低到手价 ${yuan(i.lowest)}，底线 ${yuan(i.floor)}）`).join('；') : '都达标'}`)
console.log(`  价保退差（PP-2）：${pp.orders} 单，合计 ${yuan(pp.amount)}${pp.needsCfo ? `，超过 ${yuan(pp.limit)}，要 CFO 审批` : `，在 ${yuan(pp.limit)} 以内`}`)
for (const s of pp.bySku.filter((x) => x.amount > 0)) console.log(`    ${s.name}：${s.orders} 单 ${yuan(s.amount)}`)
console.log(`  预估毛利率（MGN-3）：日常 ${r.margin.usual}% → 活动 ${r.margin.campaign}%`)
console.log(r.canLaunch ? '  结论：可以上线' : `  结论：不能上线（${r.blockers.length} 个原因）\n` + r.blockers.map((b) => `    - ${b}`).join('\n'))
