// 运营后台：由前端开发按 README「页面约定」实现（render 纯函数 + mount 绑事件）。模板里只是占位。
import { html } from '../lib/format.js'

export function render(state) {
  return html`<section class="panel glass">
    <p class="eyebrow">运营后台</p>
    <h1 class="title">双十一活动配置</h1>
    <p class="muted">${state.status === 'error' ? state.error : '页面还没开发'}</p>
  </section>`.toString()
}

export function mount(root) {
  root.innerHTML = render({ status: 'loading', check: null })
}
