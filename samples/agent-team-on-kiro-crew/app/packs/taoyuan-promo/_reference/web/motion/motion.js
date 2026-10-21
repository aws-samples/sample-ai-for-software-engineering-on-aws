// 参考实现：品牌动效（最小）。
export const prefersReduced = () => typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches
export function flip(el, text) { if (el) el.textContent = text }
export function reveal(cards) { for (const c of cards) c.classList.add('is-in') }
export function bump(el) { if (el && !prefersReduced()) el.classList.add('is-bump') }
export function celebrate(canvas) {}
