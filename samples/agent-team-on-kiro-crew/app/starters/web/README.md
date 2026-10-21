# 桃源科技 · 内部网页

桃源科技给自己的部门做的内部网页。这个项目从公司的网页模板开工：服务器骨架、页面外壳和路由、品牌样式和组件、字体、小桃子都已经有了，需求只在模板约定的位置上开发。

## 怎么跑

```bash
npm start          # http://127.0.0.1:3000 （PORT、HOST 环境变量可改）
npm test           # 跑 tests/ 下的全部检查，等于 node tests/enterprise/_run.cjs
```

只需要 Node 22 或更新版本，不装任何 npm 包。

## 公司模板约定

### 目录

| 路径 | 内容 | 谁改 |
|---|---|---|
| `server/app.js`、`server/server.js`、`server/lib/` | 服务器骨架、HTTP 小工具、读数据 | 模板自带，不改 |
| `server/data/` | 数据：从知识库取来的 JSON，原样放 | 按分工 |
| `server/routes/` | 接口 | 按分工 |
| `web/index.html`、`web/app.js`、`web/lib/`、`web/styles/tokens.css`、`base.css`、`shell.css` | 页面外壳、路由、调接口、拼 HTML、品牌变量和全站组件 | 模板自带，不改 |
| `web/pages/`、`web/styles/<页面名>.css` | 页面和它们的样式；`web/pages/index.js` 登记页面 | 按分工 |
| `web/motion/` | 品牌动效 | 按分工 |
| `deploy/` | 部署配置 | 按分工 |
| `tests/enterprise/` | 公司下发的检查 | 谁都不能改 |
| `docs/aidlc/` | 各阶段的产出 | |

### 数据

数据在 Kiro Crew 知识库「桃源科技」里：知识库的说明文档写了完整数据文件的路径。要用就原样复制到 `server/data/`（不手抄、不改内容），`server/lib/data.js` 按文件名读：`server/data/employees.json` 在接口里是 `ctx.data.employees`。

### 接口约定（公司统一）

- 路径以 `/api/` 开头，收发 JSON。路由写在 `server/routes/`，格式见 `server/routes/index.js` 开头的说明。
- 出错返回 4xx 和 `{ "error": { "code": "<英文短码>", "message": "<给用户看的中文>" } }`；输入不对是 400，不会是 500。
- 列表接口返回 `{ "<复数名>": [...] }`，单个对象返回 `{ "<单数名>": {...} }`。
- 只返回页面要用的字段；个人信息怎么展示见知识库《个人信息展示规范》。
- 导出文件（CSV）`text/csv; charset=utf-8`，第一行是中文表头。

### 页面约定

每个页面模块 `web/pages/<页面名>.js` 导出两个函数，并在 `web/pages/index.js` 里登记（`{ title, load }`，第一个是首页）：

- **`render(state)`**：纯函数，返回 HTML **字符串**。不碰 `document`、`window`、`fetch`，Node 测试里能直接调用。用 `web/lib/format.js` 的 `` html`…` `` 拼（插进去的值自动转义），最后 `String(html`…`)` 返回。
- **`mount(root, ctx)`**：浏览器里调用，`ctx` 是 `{ api, motion, fx, navigate }`：`api.get/post/put/del` 调接口，`motion` 是 `web/motion/motion.js`，`fx` 是全屏的 `<canvas>`。取数据、调 `render` 写进 `root`、绑事件（事件委托：在 `root` 上监听，靠 `data-*` 认出点的是什么）。可以返回一个清理函数，切页面时调用。

`state` 的形状、页面上测试要用的 `data-*`，由架构写在 `docs/aidlc/2-inception/interfaces.md`。

不要写 `onclick="…"` 这类内联事件属性，不要写内联 `<script>`：服务器的内容安全策略只允许本站的脚本文件。

### 动效接口（`web/motion/motion.js`，页面只通过它用动效）

| 函数 | 做什么 |
|---|---|
| `prefersReduced()` | 系统是不是要求减少动态效果 |
| `flip(el, text)` | 把 `el` 的文字换成 `text`（数字跳动） |
| `reveal(items)` | 卡片、列表项依次出现（给每个加 `is-in`） |
| `bump(el)` | 点按反馈：让 `el` 跳一下 |
| `celebrate(canvas)` | 在全屏 canvas 上放一次庆祝 |

模板里是不带动画的占位，页面照样能用。

### 全站组件（`web/styles/base.css`，页面直接用）

`.glass` 玻璃卡片、`.panel` 内边距、`.hero` 居中大标题区、`.eyebrow` 小标题、`.display` 渐变大字、`.title`、`.big` 大数字、`.muted`；`.btn`、`.btn--primary`（渐变发光的主按钮）、`.btn--ghost`；`.chip`、`.chip--active`、`.chip--done`；`.stat`；`.table`；`.state`、`.state--error`；`.mascot`。

## 需求

（开工时写入）
