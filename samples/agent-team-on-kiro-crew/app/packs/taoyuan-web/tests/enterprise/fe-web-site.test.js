// 《前端工程规范》FE-1、FE-2、UX-2：没有内联脚本，不引第三方资源，图片有替代文字。
import test from 'node:test'
import assert from 'node:assert/strict'
import { files, pages } from './_lib.js'

const web = () => files('web', ['.js', '.css', '.html'])

test('FE-1: 页面里没有内联脚本和 onclick 这类内联事件属性', async () => {
  for (const f of files('web', ['.html', '.js'])) {
    assert.doesNotMatch(f.text, /<script(?![^>]*\bsrc=)[^>]*>/i, `${f.file} 里有内联 <script>`)
    assert.doesNotMatch(f.text, /\son[a-z]+\s*=\s*["'{]/i, `${f.file} 里有 on…= 内联事件属性`)
  }
  for (const p of await pages()) {
    const out = String(p.module.render({}))
    assert.doesNotMatch(out, /<script|\son[a-z]+\s*=/i, `页面 ${p.name} 的 render 输出里有内联脚本或事件属性`)
  }
})

test('FE-2: 网页不引用别的域名的脚本、字体、图片、样式', () => {
  for (const f of web()) {
    const urls = (f.text.match(/(?:https?:)?\/\/[a-z0-9.-]+\.[a-z]{2,}[^\s"')]*/gi) || []).filter((u) => !/w3\.org/.test(u))
    assert.deepEqual(urls, [], `${f.file} 引用了外部地址`)
  }
})

test('UX-2: 图片都有 alt（装饰性图片写 alt=""）', async () => {
  for (const f of files('web', ['.html', '.js'])) {
    const imgs = f.text.match(/<img\b[^>]*>/gi) || []
    for (const img of imgs) assert.match(img, /\balt=/i, `${f.file}：${img} 没有 alt`)
  }
  for (const p of await pages()) {
    for (const img of String(p.module.render({})).match(/<img\b[^>]*>/gi) || []) {
      assert.match(img, /\balt=/i, `页面 ${p.name}：${img} 没有 alt`)
    }
  }
})
