---
inclusion: always
---

# 桃源科技内部网页：技术约定

- 只用 Node 22 自带的模块，不装任何 npm 包；网页用原生 ES 模块，不用框架、不用打包工具。
- 模板约定在 `README.md`「公司模板约定」：目录、接口外形、页面的 `render` / `mount`、动效接口、全站组件。按约定写，不改模板自带的文件。
- 测试在 `tests/`，用 `node:test`；公司下发的检查在 `tests/enterprise/`，谁都不能改。跑全部：`node tests/enterprise/_run.cjs`；只跑一部分：`node tests/enterprise/_run.cjs <文件名里的词>`。
- 颜色、字体、缓动只用 `web/styles/tokens.css` 的变量。
