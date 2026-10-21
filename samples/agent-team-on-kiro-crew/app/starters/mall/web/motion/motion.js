// 品牌动效：由动效设计师按 README「动效接口」实现。模板里是不带动画的占位：页面照样能用，只是没有动效。
export const prefersReduced = () => typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches

// 把 el 的文字换成 text（倒计时的数字跳动用）
export function flip(el, text) {
  if (el) el.textContent = text
}

// 商品卡片依次出现（给每张加 is-in）
export function reveal(cards) {
  for (const c of cards) c.classList.add('is-in')
}

// 加购物车时，让 el（购物车角标）跳一下
export function bump(el) {}

// 活动上线时，在全屏 canvas 上放一次庆祝
export function celebrate(canvas) {}
