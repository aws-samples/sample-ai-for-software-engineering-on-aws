// 数据原样：server/data/ 里的商品和订单要和知识库的数据一模一样（检查的标准答案都按知识库算）。
import test from 'node:test'
import assert from 'node:assert/strict'
import { CANON, read } from './_lib.js'

test('DATA-1: 商品和订单从知识库原样复制', () => {
  for (const [file, want] of [['server/data/products.json', CANON.products], ['server/data/orders.json', CANON.orders]]) {
    const text = read(file)
    assert.ok(text, `还没有 ${file}（知识库《官方商城商品和订单》写了数据文件路径，原样复制进来）`)
    assert.deepEqual(JSON.parse(text), want, `${file} 和知识库的数据不一样：要原样复制，不能手抄或改内容`)
  }
})
