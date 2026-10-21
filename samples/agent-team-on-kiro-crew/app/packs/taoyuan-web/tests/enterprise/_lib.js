// 公司检查的公共部分：起一个新的服务实例、调接口、加载页面模块、读源码。不要改这个文件。
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
export const ROOT = path.resolve(HERE, '..', '..')

// 每个用例自己起一个新的服务（状态在服务进程里，互不影响），用完 close()
export async function startServer() {
  const { createApp } = await import(pathToFileURL(path.join(ROOT, 'server', 'app.js')).href)
  const srv = createApp()
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
    let json = null
    try { json = JSON.parse(text) } catch { /* not JSON */ }
    return { status: res.status, json, text, type: res.headers.get('content-type') || '' }
  }
  return {
    get: (p) => req('GET', p),
    post: (p, body = {}) => req('POST', p, body),
    put: (p, body = {}) => req('PUT', p, body),
    del: (p) => req('DELETE', p),
    close: () => new Promise((resolve) => srv.close(resolve)),
  }
}

// 接口路由表（server/routes/index.js 导出的 routes）
export async function routes() {
  const file = path.join(ROOT, 'server', 'routes', 'index.js')
  if (!fs.existsSync(file)) return []
  return (await import(pathToFileURL(file).href)).routes || []
}

// 登记的页面：[{ name, title, module }]
export async function pages() {
  const file = path.join(ROOT, 'web', 'pages', 'index.js')
  if (!fs.existsSync(file)) return []
  const { pages: list } = await import(pathToFileURL(file).href)
  const out = []
  for (const [name, p] of Object.entries(list || {})) {
    out.push({ name, title: p.title, module: await import(pathToFileURL(path.join(ROOT, 'web', 'pages', `${name}.js`)).href) })
  }
  return out
}

export const read = (rel) => (fs.existsSync(path.join(ROOT, rel)) ? fs.readFileSync(path.join(ROOT, rel), 'utf8') : '')

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

// 写死的颜色值：#fff、#7c3aed、rgb(…)、rgba(…)、hsl(…)（品牌规范：颜色只用 tokens.css 的变量）
export const RAW_COLOR = /#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?)\(\s*\d/
// 完整的 11 位手机号（脱敏后的 199****1234 不算）
export const FULL_PHONE = /(?<!\d)1[3-9]\d{9}(?!\d)/
