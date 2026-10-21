// 《前端工程规范》UX-1 和《品牌规范》BR-1、BR-3：品牌动效（web/motion/）。
import test from 'node:test'
import assert from 'node:assert/strict'
import { motion, read, RAW_COLOR } from './_lib.js'

test('UX-1: 动效尊重"减少动态效果"，接口按 README', async () => {
  const js = read('web/motion/motion.js')
  const css = read('web/motion/motion.css')
  assert.match(js, /prefers-reduced-motion/, 'motion.js 要按 prefers-reduced-motion 判断')
  assert.match(css, /@media\s*\(\s*prefers-reduced-motion:\s*reduce\s*\)/, 'motion.css 要有 @media (prefers-reduced-motion: reduce)')
  const m = await motion()
  for (const fn of ['prefersReduced', 'flip', 'reveal', 'bump', 'celebrate']) assert.equal(typeof m[fn], 'function', `motion.js 要导出 ${fn}`)
})

test('BR-3: 关键帧只动 transform 和 opacity', () => {
  const css = read('web/motion/motion.css')
  const frames = css.match(/@keyframes[^{]*\{(?:[^{}]*\{[^}]*\})*[^}]*\}/g) || []
  assert.ok(frames.length > 0, 'motion.css 里还没有动画（@keyframes）')
  for (const f of frames) {
    const props = [...f.matchAll(/([a-z-]+)\s*:/g)].map((m) => m[1])
    const bad = props.filter((p) => !['transform', 'opacity', 'offset', 'animation-timing-function'].includes(p))
    assert.deepEqual(bad, [], `${f.split('{')[0].trim()} 动了 ${bad.join('、')}（只能动 transform 和 opacity）`)
  }
})

test('BR-1: 动效的颜色来自品牌变量，不写死', () => {
  const bad = [...read('web/motion/motion.css').split('\n'), ...read('web/motion/motion.js').split('\n')].filter((ln) => RAW_COLOR.test(ln))
  assert.deepEqual(bad, [], '动效里写死了颜色：CSS 用 var(--brand-…)，canvas 里用 getComputedStyle 读 --brand-… 变量')
})
