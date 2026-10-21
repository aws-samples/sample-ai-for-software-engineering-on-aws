// 《前端工程规范》FE-4：代码里不写死密钥、令牌（网页和服务端都不行）。
import test from 'node:test'
import assert from 'node:assert/strict'
import { files } from './_lib.js'

test('FE-4: 代码里没有写死的密钥', () => {
  for (const f of [...files('web', ['.js']), ...files('server', ['.js'])]) {
    assert.doesNotMatch(f.text, /AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9]{16,}|(?:password|secret|token)\s*[:=]\s*['"][^'"]{6,}/i, `${f.file} 里像是写死了密钥`)
  }
})
