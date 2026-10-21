# 公司下发的检查（研发中心、法务、安全组、设计部）

谁都不能改这个目录。`node tests/enterprise/_run.cjs` 跑 `tests/` 下的全部检查（公司的加上项目自己的）；`node tests/enterprise/_run.cjs pii-` 只跑文件名里带 `pii-` 的。

检查按 `README.md`「公司模板约定」调用你的代码：起一个服务实例调接口（`_lib.js` 的 `startServer`），直接 import 页面模块调 `render`，读 `web/` 和 `server/` 的源码。规则原文在知识库：《前端工程规范》FE-n / UX-n、《品牌规范》BR-n、《个人信息展示规范》PII-n。

文件名里的区域决定失败归谁：`-web-` 是网页（`web/` 下的页面、样式、动效），`-server-` 是服务端（`server/` 下的接口和数据）。架构在 `docs/aidlc/2-inception/ownership.json` 的 `test_areas` 里写明 `web` 和 `server` 各归谁。
