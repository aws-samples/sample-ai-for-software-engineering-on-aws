// 模板自带的占位首页：开发加了自己的页面以后，可以改掉或者从 pages/index.js 里拿掉。
import { html } from '../lib/format.js'

export function render(state = {}) {
  return String(html`<section class="hero glass panel">
    <p class="eyebrow">桃源科技</p>
    <h1 class="display">${state.title || '新页面'}</h1>
    <p class="muted">这个项目从公司网页模板开工，页面还没写。</p>
  </section>`)
}

export function mount(root) {
  root.innerHTML = render({})
}
