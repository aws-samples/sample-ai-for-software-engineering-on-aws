// 公司商城活动模板：读数据和活动配置。数据从知识库取来放进 server/data/，配置放进 server/config/，这里只负责读。
import { readFileSync, existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const DATA = fileURLToPath(new URL('../data/', import.meta.url))
const CONFIG = fileURLToPath(new URL('../config/', import.meta.url))

function read(dir, name, empty) {
  const file = dir + name
  return existsSync(file) ? JSON.parse(readFileSync(file, 'utf8')) : empty
}

// { products: 商品[], orders: 订单[] }：字段见 README「数据」
export function loadData() {
  return { products: read(DATA, 'products.json', []), orders: read(DATA, 'orders.json', []) }
}

// 活动配置（server/config/campaign.json）：运营提报的方案，字段见 README「活动配置」。还没有就是 null
export function loadConfig() {
  return read(CONFIG, 'campaign.json', null)
}
