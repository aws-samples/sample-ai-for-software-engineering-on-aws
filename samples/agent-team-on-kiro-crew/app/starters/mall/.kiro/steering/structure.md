---
inclusion: always
---

# 桃源科技官方商城：目录

| 路径 | 是什么 |
|---|---|
| `server/lib/pricing.js` | 价格引擎：到手价、划线价、上线前体检、购物车算价 |
| `server/routes/` | 接口 |
| `server/data/` | 数据（从知识库取来） |
| `server/config/campaign.json` | 活动配置（运营方案） |
| `web/pages/campaign.js` | 双十一活动页 |
| `web/pages/admin.js` | 运营后台 |
| `web/motion/` | 品牌动效 |
| `web/styles/` | 样式：`tokens.css` 品牌变量、`base.css` 全站组件，页面各自一个 css |
| `tools/check-campaign.js` | 上线前体检的命令行（`npm run check-campaign`） |
| `tests/` | 测试；`tests/enterprise/` 是公司下发的检查 |
| `docs/aidlc/` | 各阶段的产出 |
