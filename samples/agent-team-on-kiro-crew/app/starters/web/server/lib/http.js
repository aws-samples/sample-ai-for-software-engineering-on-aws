// 公司模板：HTTP 小工具。零依赖，只用 Node 自带的模块。
// 路由处理函数抛 HttpError，app.js 会把它写成统一的错误格式：
//   { "error": { "code": "<英文短码>", "message": "<给用户看的中文>" } }

export class HttpError extends Error {
  constructor(status, code, message) {
    super(message)
    this.status = status
    this.code = code
  }
}

export const BODY_LIMIT = 16 * 1024 // 请求体上限 16KB，超过返回 413

export function sendJson(res, status, body) {
  const text = JSON.stringify(body)
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(text),
    'Cache-Control': 'no-store',
  })
  res.end(text)
}

// 读 JSON 请求体：超过上限抛 413，不是合法 JSON 抛 400。
export function readJson(req, limit = BODY_LIMIT) {
  return new Promise((resolve, reject) => {
    let size = 0
    const chunks = []
    req.on('data', (chunk) => {
      size += chunk.length
      if (size > limit) {
        reject(new HttpError(413, 'body_too_large', '请求内容太大'))
        req.destroy()
        return
      }
      chunks.push(chunk)
    })
    req.on('end', () => {
      const text = Buffer.concat(chunks).toString('utf8')
      if (!text.trim()) return resolve(undefined)
      try {
        resolve(JSON.parse(text))
      } catch {
        reject(new HttpError(400, 'invalid_json', '请求内容不是合法的 JSON'))
      }
    })
    req.on('error', reject)
  })
}

// 路由表里的 path 可以带参数：'/api/products/:id'。匹配上返回 { route, params }。
export function matchRoute(routes, method, pathname) {
  for (const route of routes) {
    if (route.method !== method) continue
    const want = route.path.split('/')
    const got = pathname.split('/')
    if (want.length !== got.length) continue
    const params = {}
    let ok = true
    for (let i = 0; i < want.length; i++) {
      if (want[i].startsWith(':')) {
        try {
          params[want[i].slice(1)] = decodeURIComponent(got[i])
        } catch {
          ok = false
          break
        }
      } else if (want[i] !== got[i]) {
        ok = false
        break
      }
    }
    if (ok) return { route, params }
  }
  return null
}
