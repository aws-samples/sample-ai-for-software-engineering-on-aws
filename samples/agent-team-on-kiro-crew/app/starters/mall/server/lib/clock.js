// 公司商城活动模板：服务器时间。所有「现在几点」都从这里取（价格与促销合规规范 PRC-4：以服务器时间为准）。
//
// 演示环境的约定：环境变量 DEMO_NOW（或 server/config/clock.json 的 now）给了一个时刻，服务启动时就把
// 「现在」对齐到那一刻，之后按真实时间往前走；都没给就是真实时间。这样任何一天演示，活动都在进行中。
import { readFileSync, existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const FILE = fileURLToPath(new URL('../config/clock.json', import.meta.url))
const boot = Date.now()
const configured = process.env.DEMO_NOW || (existsSync(FILE) ? JSON.parse(readFileSync(FILE, 'utf8')).now : '')
const start = configured ? Date.parse(configured) : NaN

// 现在（毫秒）
export function now() {
  return Number.isFinite(start) ? start + (Date.now() - boot) : Date.now()
}
