// 公司网页模板：服务器骨架。同时提供接口（/api/*）和网页（web/ 下的静态文件）。
// 接口的路由表在 routes/index.js；这个文件一般不需要改。

import { createServer } from 'node:http'
import { readFile } from 'node:fs/promises'
import { extname, normalize, sep } from 'node:path'
import { fileURLToPath } from 'node:url'
import { HttpError, matchRoute, readJson, sendJson } from './lib/http.js'
import { loadData } from './lib/data.js'
import { routes } from './routes/index.js'

const WEB = fileURLToPath(new URL('../web/', import.meta.url))
const TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.ico': 'image/x-icon',
  '.woff2': 'font/woff2',
  '.json': 'application/json; charset=utf-8',
}
// 公司安全基线：所有响应都带这些头（脚本只能来自本站，不允许内联脚本）
const SECURITY_HEADERS = {
  'X-Content-Type-Options': 'nosniff',
  'Referrer-Policy': 'same-origin',
  'X-Frame-Options': 'DENY',
  'Content-Security-Policy':
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'",
}

export function createApp({ data = loadData() } = {}) {
  const state = {} // 这一次服务进程里的状态（接口自己往里放，重启就清空）
  return createServer(async (req, res) => {
    for (const [k, v] of Object.entries(SECURITY_HEADERS)) res.setHeader(k, v)
    const url = new URL(req.url, 'http://localhost')
    try {
      if (url.pathname.startsWith('/api/')) return await api(req, res, url, data, state)
      return await staticFile(req, res, url)
    } catch (err) {
      if (err instanceof HttpError) return sendJson(res, err.status, { error: { code: err.code, message: err.message } })
      console.error(err)
      return sendJson(res, 500, { error: { code: 'internal', message: '服务器出错了，请稍后再试' } })
    }
  })
}

async function api(req, res, url, data, state) {
  const hit = matchRoute(routes, req.method, url.pathname)
  if (!hit) throw new HttpError(404, 'not_found', '没有这个接口')
  let body
  const ctx = {
    req,
    res,
    data,
    state,
    params: hit.params,
    query: url.searchParams,
    // 请求体按需读：await ctx.body()
    body: async () => (body === undefined ? (body = await readJson(req)) : body),
    send: (status, data) => sendJson(res, status, data),
  }
  const out = await hit.route.handler(ctx)
  if (res.writableEnded) return
  if (out === undefined) {
    res.writeHead(204)
    res.end()
  } else sendJson(res, 200, out)
}

async function staticFile(req, res, url) {
  if (req.method !== 'GET' && req.method !== 'HEAD') throw new HttpError(405, 'method_not_allowed', '不支持这个方法')
  let rel
  try {
    rel = decodeURIComponent(url.pathname)
  } catch {
    throw new HttpError(404, 'not_found', '页面不存在')
  }
  if (rel === '/' || rel === '') rel = '/index.html'
  const file = normalize(WEB + rel)
  if (!file.startsWith(WEB) || file.includes(`${sep}..${sep}`)) throw new HttpError(404, 'not_found', '页面不存在')
  let data
  try {
    data = await readFile(file)
  } catch {
    throw new HttpError(404, 'not_found', '页面不存在')
  }
  res.writeHead(200, { 'Content-Type': TYPES[extname(file)] || 'application/octet-stream', 'Cache-Control': 'no-cache' })
  res.end(req.method === 'HEAD' ? undefined : data)
}
