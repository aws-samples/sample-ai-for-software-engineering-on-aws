# 桃源科技官方商城 · 双十一活动

官方商城的双十一大促：顾客看的活动页，和运营用的后台（改折扣、看上线前体检、一键上线）。这个项目从公司的商城活动模板开工：服务器骨架、页面外壳、品牌样式和组件、字体都已经有了，需求只在模板约定的位置上开发。

## 怎么跑

```bash
npm start                 # http://127.0.0.1:3000 （PORT、HOST 环境变量可改）
npm test                  # 跑 tests/ 下的全部检查，等于 node tests/enterprise/_run.cjs
npm run check-campaign    # 上线前体检：按 server/config/campaign.json 算一遍，中文打出能不能上线、为什么
```

只需要 Node 22 或更新版本，不装任何 npm 包。

## 公司模板约定

### 目录

| 路径 | 内容 | 谁改 |
|---|---|---|
| `server/app.js`、`server/lib/http.js`、`data.js`、`clock.js` | 服务器骨架、HTTP 小工具、读数据、服务器时间 | 模板自带，不改 |
| `server/data/` | 数据：`products.json`、`orders.json`，从知识库取来，原样放 | 产品经理 |
| `server/config/campaign.json` | 活动配置：从知识库《双十一活动方案》原样复制；之后方案要改（关卡上人定的），改这个文件 | 后端开发 |
| `server/lib/pricing.js` | 价格引擎（见下面「价格引擎」） | 后端开发 |
| `server/routes/` | 接口 | 后端开发 |
| `web/index.html`、`web/app.js`、`web/lib/`、`web/styles/tokens.css`、`base.css`、`shell.css` | 页面外壳、路由、调接口、拼 HTML、品牌变量和全站组件 | 模板自带，不改 |
| `web/pages/campaign.js`、`web/styles/campaign.css` | 双十一活动页 | 前端开发 |
| `web/pages/admin.js`、`web/styles/admin.css` | 运营后台 | 前端开发 |
| `web/motion/` | 品牌动效：倒计时跳动、商品卡片出现、加购、上线庆祝 | 动效设计师 |
| `tools/check-campaign.js` | 上线前体检的命令行 | 模板自带，不改 |
| `tests/enterprise/` | 公司下发的检查 | 谁都不能改 |
| `docs/aidlc/` | 各阶段的产出 | |

### 数据

商品（`server/data/products.json`）：`sku`、`name`、`category` 品类、`price` 日常价（元）、`cost` 成本（元）、`stock` 库存、`priceProtect` 有没有 30 天价保。
订单（`server/data/orders.json`）：`id`、`sku`、`paid` 成交单价（元）、`qty` 件数、`date` 下单日期（`YYYY-MM-DD`，北京时间）、`status`（已完成 / 已退货）。

### 活动配置

`server/config/campaign.json`：`name`、`start` / `end`（带时区的时间，如 `2026-11-01T00:00:00+08:00`）、`fullReduction`（`every` 每满多少元、`off` 减多少元、`withDiscount` 能否和折扣叠加、`withCoupon` 能否和优惠券叠加）、`items`（每款商品一条：`sku`、`pct` 折扣百分比、`fullReduction` 参不参加满减、`linePriceInput` 运营填的划线价，**不能直接用**）。

### 价格引擎（`server/lib/pricing.js`，公司检查直接调用）

规则在知识库：《价格与促销合规规范》PRC、《毛利与定价规则》MGN、《价保规则》PP。函数名、参数和返回值的外形如下，不要改：

```js
finalPrice(price, pct)          // MGN-1 到手价：price × pct / 100，四舍五入到元
linePrice(sku, data, config)    // PRC-1 划线价：config.start 那天之前 7 天（含前一天往前数 7 天）已完成订单的最低成交价；没有就是日常价
quote(items, config, data)      // 购物车算价，items = [{ sku, qty }]
//   → { lines: [{ sku, name, qty, final, subtotal, fullReduction }], subtotal, off, total }
//     off：参加满减的商品小计合起来，每满 fullReduction.every 减 fullReduction.off；total = subtotal - off
check(config, data)             // PRC-5 上线前体检
//   → {
//       campaign: { name, start, end },
//       items: [{ sku, name, price, cost, pct, final, linePrice, linePriceInput, fullReduction,
//                 lowest, floor, marginOk }],
//       priceProtect: { orders, amount, limit, needsCfo, bySku: [{ sku, name, orders, amount }] },
//       margin: { usual, campaign },
//       blockers: [string],
//       canLaunch: boolean,
//     }
```

`check` 里各项的意思：

- `final` 到手价（MGN-1）；`linePrice` 划线价（PRC-1）；`lowest` 活动期间的最低到手价（MGN-2：参加满减的按 `final × 90%` 四舍五入到元，不参加的就是 `final`）；`floor` 毛利底线 = `cost × 1.08`（不取整）；`marginOk` = `lowest >= floor`。
- `priceProtect`（PP-1、PP-2）：活动前 30 天（含前一天往前数 30 天）已完成订单里，商品有价保、成交单价高于到手价的，每单退差 = (成交单价 − 到手价) × 件数。`orders` 是要退差的单数，`amount` 是合计（元），`limit` = 300000，`needsCfo` = `amount > limit`，`bySku` 按配置里商品的顺序每款一条（没有退差的也列，`orders` 和 `amount` 为 0）。
- `margin`（MGN-3）：按同样 30 天里已完成订单的件数，算日常价和到手价下的毛利率：Σ(价 − 成本)×件数 ÷ Σ价×件数 × 100，保留一位小数（数字，不是字符串）。
- `blockers`：每个不能上线的原因一句中文（某款低于毛利底线、价保要 CFO 审批）；`canLaunch` = 没有原因。

### 接口约定（公司统一，检查按这个调用）

路径以 `/api/` 开头，收发 JSON。出错返回 4xx 和 `{ "error": { "code", "message" } }`，输入不对是 400，不会是 500。活动配置和状态在服务进程里（`ctx.state`），运营后台改的是这一份；状态 `draft` 还没上线，`live` 已上线。

| 接口 | 请求 | 成功 |
|---|---|---|
| `GET /api/time` | | `200 { "now": "<ISO 时间>" }`：服务器时间（PRC-4，用 `ctx.now()`） |
| `GET /api/campaign` | | `200 { "campaign": { "name", "start", "end", "status", "fullReduction" }, "items": [{ "sku", "name", "category", "price", "linePrice", "final", "pct", "fullReduction", "stock" }] }` |
| `GET /api/campaign/check` | | `200`：`check()` 的结果，再加上 `"status"` |
| `PUT /api/campaign/items/:sku` | `{ "pct"?, "fullReduction"? }` | `200`：改完以后的体检结果（同上）。`pct` 不是 50～100 的整数、`fullReduction` 不是布尔值是 `400`；没有这款商品是 `404`；活动已上线不能改，`409`（`live`） |
| `POST /api/campaign/launch` | | `200 { "campaign": { …, "status": "live" } }`。体检没过是 `409`（`blocked`，`message` 写明原因）；已经上线是 `409`（`live`） |
| `POST /api/cart/quote` | `{ "items": [{ "sku", "qty" }] }` | `200`：`quote()` 的结果。活动还没上线不能按活动价算，`409`（`not_live`，PRC-4）；输入不对 `400`；没有这款商品 `404` |

### 页面约定

每个页面模块 `web/pages/<页面>.js` 导出两个函数：

- **`render(state)`**：纯函数，返回 HTML **字符串**。不碰 `document`、`window`、`fetch`，Node 测试里能直接调用。用 `web/lib/format.js` 的 `` html`…` `` 拼（插进去的值自动转义），最后 `String(html`…`)` 返回。`format.js` 里还有 `yuan(4319)` → `¥4,319`、`zhe(85)` → `8.5 折`、`parts(毫秒)` → 倒计时的天时分秒。注意 `html` 会把 `false`、`null` 插成空：布尔值放进属性要先转字符串（`data-ok="${String(ok)}"`）。
- **`mount(root, ctx)`**：浏览器里调用，`ctx` 是 `{ api, motion, fx, navigate }`：`api.get/post/put` 调接口，`motion` 是 `web/motion/motion.js`，`fx` 是全屏的 `<canvas>`。取数据、调 `render` 写进 `root`、绑事件（事件委托：在 `root` 上监听，靠 `data-*` 认出点的是什么）。可以返回一个清理函数，切页面时调用。

`render` 的 `state` 形状是公司统一的，检查按这个调用：

| 页面 | state |
|---|---|
| `campaign` | `{ status: 'loading' \| 'ready' \| 'error', campaign: GET /api/campaign 的 campaign 或 null, items: 同一接口的 items, now: 服务器时间（毫秒）, cart: quote() 的结果或 null, error?: 出错信息 }` |
| `admin` | `{ status: 'loading' \| 'ready' \| 'saving' \| 'error', check: GET /api/campaign/check 的结果或 null, prev?: 改之前的体检结果（有的话，用来显示「比刚才」的变化量）, error?: 出错信息 }` |

页面上必须有的 `data-*`（检查要用）：

- 活动页：倒计时 `data-countdown`（同一个元素上 `data-end` 写活动结束时间）；每张商品卡片 `data-sku="<sku>"`，卡片里到手价的元素 `data-final`、划线价的元素 `data-line`；加购按钮 `data-action="add"`（带 `data-sku`）；购物车汇总 `data-cart`。
- 运营后台：每款商品一行 `data-sku="<sku>"`，行上 `data-ok="true|false"`（毛利是否达标）；折扣输入框 `data-pct`（`<input type="number">`）；满减开关 `data-fr`（`<input type="checkbox">`）；不能上线的原因列表 `data-blockers`；价保汇总 `data-pp`；上线按钮 `data-action="launch"`（不能上线时带 `disabled`）。

不要写 `onclick="…"` 这类内联事件属性，不要写内联 `<script>`：服务器的内容安全策略只允许本站的脚本文件。

### 动效接口（`web/motion/motion.js`，页面只通过它用动效）

| 函数 | 做什么 |
|---|---|
| `prefersReduced()` | 系统是不是要求减少动态效果 |
| `flip(el, text)` | 把 `el` 的文字换成 `text`，倒计时的数字跳动用 |
| `reveal(cards)` | 商品卡片依次出现（给每张加 `is-in`） |
| `bump(el)` | 加购物车时，购物车角标跳一下 |
| `celebrate(canvas)` | 活动上线时，在全屏 canvas 上放一次庆祝，几秒后自己清掉 |

模板里是不带动画的占位，页面照样能用。

### 全站组件（`web/styles/base.css`，页面直接用）

`.glass` 玻璃卡片、`.panel` 内边距、`.hero` 居中大标题区、`.eyebrow` 小标题、`.display` 渐变大字、`.title`、`.big` 大数字、`.muted`；`.btn`、`.btn--primary`（渐变发光的主按钮）、`.btn--ghost`；`.chip`、`.chip--active`、`.chip--done`；`.stat`；`.table`；`.state`、`.state--error`。

## 需求

（开工时写入）
