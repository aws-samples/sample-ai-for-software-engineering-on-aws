// 《前端工程规范》FE-2、FE-4：不引第三方资源，不写死密钥。
import test from 'node:test'
import assert from 'node:assert/strict'
import { files } from './_lib.js'

test('FE-2: 网页不引用别的域名的脚本、字体、图片、样式', () => {
  for (const f of files('web', ['.js', '.css', '.html'])) {
    const urls = (f.text.match(/(?:https?:)?\/\/[a-z0-9.-]+\.[a-z]{2,}[^\s"')]*/gi) || []).filter((u) => !/w3\.org/.test(u))
    assert.deepEqual(urls, [], `${f.file} 引用了外部地址`)
  }
})

test('FE-4: 代码里没有写死的密钥', () => {
  for (const f of [...files('web', ['.js']), ...files('server', ['.js'])]) {
    assert.doesNotMatch(f.text, /AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9]{16,}|(?:password|secret|token)\s*[:=]\s*['"][^'"]{6,}/i, `${f.file} 里像是写死了密钥`)
  }
})
