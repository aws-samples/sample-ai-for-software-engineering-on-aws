// 公司商城活动模板：调接口。出错时抛 Error，message 是接口给的中文说明。
async function call(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    const err = new Error(data?.error?.message || `请求失败（${res.status}）`)
    err.status = res.status
    err.code = data?.error?.code
    throw err
  }
  return data
}

export const api = {
  get: (path) => call('GET', path),
  post: (path, body = {}) => call('POST', path, body),
  put: (path, body = {}) => call('PUT', path, body),
}
