// 参考实现：双十一活动页。
import { html, parts, yuan, zhe } from '../lib/format.js'

const pad = (n) => String(n).padStart(2, '0')

export function render(state) {
  if (state.status === 'loading') return String(html`<section class="state">加载中…</section>`)
  if (state.status === 'error') return String(html`<section class="state state--error">${state.error}</section>`)
  const c = state.campaign
  const live = c.status === 'live'
  const t = parts(Date.parse(c.end) - state.now)
  const fr = c.fullReduction
  return String(html`<section class="hero glass">
    <p class="eyebrow">${c.name}</p>
    <h1 class="display">双十一</h1>
    <p class="muted">每满 ${fr.every} 减 ${fr.off}，${fr.withDiscount ? '可与折扣叠加' : '不与折扣叠加'}，${fr.withCoupon ? '可与优惠券叠加' : '不与优惠券叠加'}</p>
    ${live ? html`<p data-countdown data-end="${c.end}">距结束 ${t.d} 天 ${pad(t.h)}:${pad(t.m)}:${pad(t.s)}</p>` : html`<p data-countdown data-end="${c.end}">活动还没上线，敬请期待</p>`}
  </section>
  <section class="grid">
    ${state.items.map((i) => html`<article class="glass panel" data-sku="${i.sku}">
      <h3>${i.name}</h3>
      <p>到手价 <b data-final>${yuan(i.final)}</b> <span class="chip">${zhe(i.pct)}</span></p>
      <p class="muted"><s data-line>${yuan(i.linePrice)}</s> <small data-line-note>活动前 7 日最低价</small></p>
      ${live ? html`<button class="btn btn--primary" data-action="add" data-sku="${i.sku}">加入购物车</button>` : ''}
    </article>`)}
  </section>
  <aside class="glass panel" data-cart>${state.cart ? html`小计 ${yuan(state.cart.subtotal)}，满减 −${yuan(state.cart.off)}，合计 ${yuan(state.cart.total)}` : '购物车是空的'}</aside>`)
}

export function mount(root, ctx) {
  let state = { status: 'loading', campaign: null, items: [], now: Date.now(), cart: null }
  const cart = []
  const draw = () => { root.innerHTML = render(state) }
  draw()
  Promise.all([ctx.api.get('/api/campaign'), ctx.api.get('/api/time')])
    .then(([c, t]) => { state = { ...state, status: 'ready', campaign: c.campaign, items: c.items, now: Date.parse(t.now) }; draw() })
    .catch((e) => { state = { ...state, status: 'error', error: e.message }; draw() })
  const onClick = async (e) => {
    const b = e.target.closest('[data-action="add"]')
    if (!b) return
    const hit = cart.find((x) => x.sku === b.dataset.sku)
    if (hit) hit.qty += 1
    else cart.push({ sku: b.dataset.sku, qty: 1 })
    try { state = { ...state, cart: await ctx.api.post('/api/cart/quote', { items: cart }) } } catch (err) { state = { ...state, error: err.message } }
    draw()
  }
  root.addEventListener('click', onClick)
  return () => root.removeEventListener('click', onClick)
}
