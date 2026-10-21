// 双十一活动页（顾客看的）：由前端开发按 README「页面约定」实现（render 纯函数 + mount 绑事件）。模板里只是占位。
import { html } from '../lib/format.js'

export function render(state) {
  return html`<section class="hero glass">
    <p class="eyebrow">桃源科技官方商城</p>
    <h1 class="display">双十一</h1>
    <p class="muted">${state.status === 'error' ? state.error : '页面还没开发'}</p>
  </section>`.toString()
}

export function mount(root) {
  root.innerHTML = render({ status: 'loading', campaign: null, items: [], now: Date.now(), cart: null })
}
