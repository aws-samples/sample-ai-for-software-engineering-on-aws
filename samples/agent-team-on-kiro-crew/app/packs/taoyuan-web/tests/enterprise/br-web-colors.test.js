// 《品牌规范》BR-1、《前端工程规范》UX-4：颜色只用 tokens.css 的品牌变量，不在页面里随手写颜色。
import test from 'node:test'
import assert from 'node:assert/strict'
import { files } from './_lib.js'

const TEMPLATE = new Set(['web/styles/tokens.css', 'web/styles/base.css', 'web/styles/shell.css'])

test('BR-1: 页面、页面样式和动效里没有写死的颜色值', () => {
  for (const f of [...files('web/styles', ['.css']), ...files('web/pages', ['.js']), ...files('web/motion', ['.js', '.css'])]) {
    if (TEMPLATE.has(f.file)) continue
    const lines = f.text.split('\n').filter((ln) => !/^\s*(\/\/|\/\*|\*)/.test(ln))
    const bad = lines.filter((ln) => /#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?)\(\s*\d/.test(ln))
    assert.deepEqual(bad, [], `${f.file} 写死了颜色，改用 var(--brand-…)`)
  }
})
