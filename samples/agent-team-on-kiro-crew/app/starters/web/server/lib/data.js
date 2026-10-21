// 公司网页模板：读 server/data/ 下的数据文件（JSON）。数据从知识库取来放进去，这里只负责读，不改内容。
import { readFileSync, readdirSync, existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const DIR = fileURLToPath(new URL('../data/', import.meta.url))

// { <文件名>: 内容 }：server/data/employees.json 读成 data.employees，没有数据文件就是 {}
export function loadData() {
  if (!existsSync(DIR)) return {}
  const out = {}
  for (const name of readdirSync(DIR)) {
    if (name.endsWith('.json')) out[name.slice(0, -5)] = JSON.parse(readFileSync(DIR + name, 'utf8'))
  }
  return out
}
