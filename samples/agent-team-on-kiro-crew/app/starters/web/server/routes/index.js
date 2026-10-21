// 接口路由表：由后端开发按 README「接口约定」和 docs/aidlc/2-inception/interfaces.md 实现。
//
// 每条路由：{ method: 'GET', path: '/api/people', handler: async (ctx) => 返回值 }
//   ctx.params   路径参数（path 里写 /api/people/:id）
//   ctx.query    URLSearchParams
//   ctx.body()   读 JSON 请求体（await；超过 16KB 自动 413，不是 JSON 自动 400）
//   ctx.data     server/data/ 下的数据（只读）：server/data/employees.json 是 ctx.data.employees
//   ctx.state    这个服务进程里的状态（{}，接口自己往里放）
//   ctx.send(status, data)  返回 200 以外的状态码时用，比如 ctx.send(201, { item })
//   ctx.res      原始响应对象（导出 CSV 这类要自己写头和内容时用）
// 返回值会以 200 写成 JSON。出错就 throw new HttpError(状态码, 'code', '中文说明')（见 ../lib/http.js）。
//
// 可以按功能拆成几个文件，再在这里合并。

export const routes = []
