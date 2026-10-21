// 接口路由表：由后端开发按 README「接口约定」和 docs/aidlc/2-inception/requirements.md 实现。
//
// 每条路由：{ method: 'GET', path: '/api/campaign', handler: async (ctx) => 返回值 }
//   ctx.params   路径参数（'/api/campaign/items/:sku' 里的 sku）
//   ctx.query    URLSearchParams
//   ctx.body()   读 JSON 请求体（await；超过 16KB 自动 413，不是 JSON 自动 400）
//   ctx.data     { products, orders }：server/data/ 下的数据（只读）
//   ctx.state    { config, status }：这个服务进程里的活动配置（从 server/config/campaign.json 读来的一份拷贝，
//                运营后台改折扣改的是这里）和活动状态（'draft' 还没上线 / 'live' 已上线）
//   ctx.now()    服务器时间（毫秒，见 ../lib/clock.js）
//   ctx.send(status, data)  返回 200 以外的状态码时用
// 返回值会以 200 写成 JSON。出错就 throw new HttpError(状态码, 'code', '中文说明')（见 ../lib/http.js）。
// 价格怎么算放在 ../lib/pricing.js，这里只管接口。

export const routes = []
