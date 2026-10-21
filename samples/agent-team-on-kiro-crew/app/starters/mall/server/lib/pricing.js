// 价格引擎：由后端开发按 README「价格引擎」和知识库的《价格与促销合规规范》《毛利与定价规则》《价保规则》实现。
// 公司检查直接调用这里导出的函数，函数名和参数、返回值的外形按 README 写，不要改。模板里只是占位。

// MGN-1 到手价
export function finalPrice(price, pct) {
  throw new Error('价格引擎还没实现：finalPrice')
}

// PRC-1 划线价
export function linePrice(sku, data, config) {
  throw new Error('价格引擎还没实现：linePrice')
}

// PRC-5 上线前体检
export function check(config, data) {
  throw new Error('价格引擎还没实现：check')
}

// 购物车算价（满减）
export function quote(items, config, data) {
  throw new Error('价格引擎还没实现：quote')
}
