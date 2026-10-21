# 公司下发的检查（法务和价格合规组、财务部、研发中心、设计部）

谁都不能改这个目录。`node tests/enterprise/_run.cjs` 跑 `tests/` 下的全部检查（公司的加上项目自己的）；`node tests/enterprise/_run.cjs pp-` 只跑文件名里带 `pp-` 的。

检查按 `README.md`「公司模板约定」里的价格引擎、接口、页面和动效约定调用你的代码，规则原文在知识库：《价格与促销合规规范》PRC-n、《毛利与定价规则》MGN-n、《价保规则》PP-n、《前端工程规范》FE-n / UX-n、《品牌规范》BR-n。`data/` 里是知识库数据的副本：检查用它核对 `server/data/`，并按知识库的规则自己算一遍标准答案。活动配置读项目里的 `server/config/campaign.json`：关卡上人改了折扣，标准答案跟着变。

文件名决定失败归谁：`data-copy` 归产品经理；`prc-line`、`mgn-check`、`pp-check`、`api-campaign` 归后端开发 #1；`fe-campaign`、`fe-site` 归前端开发 #1；`fe-admin` 归前端开发 #2；`ux-motion` 归动效设计师。
