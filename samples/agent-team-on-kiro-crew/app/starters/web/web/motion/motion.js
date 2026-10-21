// 品牌动效：按 README「动效接口」实现。模板里是不带动画的占位：页面照样能用，只是没有动效。
export const prefersReduced = () => typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches

// 把 el 的文字换成 text（数字跳动用）
export function flip(el, text) {
  if (el) el.textContent = text
}

// 卡片、列表项依次出现（给每个加 is-in）
export function reveal(items) {
  for (const it of items) it.classList.add('is-in')
}

// 点按反馈：让 el 跳一下
export function bump(el) {}

// 在全屏 canvas 上放一次庆祝
export function celebrate(canvas) {}
