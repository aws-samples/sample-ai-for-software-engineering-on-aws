// 参考实现：运营后台。
import { html, yuan } from '../lib/format.js'

export function render(state) {
  if (state.status === 'loading') return String(html`<section class="state">加载中…</section>`)
  if (state.status === 'error') return String(html`<section class="state state--error">${state.error}</section>`)
  const k = state.check
  const pp = k.priceProtect
  return String(html`<section class="panel glass">
    <h1 class="title">${k.campaign.name} · 活动配置</h1>
    <table class="table">
      <tr><th>商品</th><th>折扣</th><th>满减</th><th>到手价</th><th>划线价</th><th>毛利底线</th></tr>
      ${k.items.map((i) => html`<tr data-sku="${i.sku}" data-ok="${String(i.marginOk)}">
        <td>${i.name}</td>
        <td><input type="number" data-pct value="${i.pct}" min="50" max="100" /></td>
        <td><input type="checkbox" data-fr ${i.fullReduction ? 'checked' : ''} /></td>
        <td>${yuan(i.final)}</td><td>${yuan(i.linePrice)}</td><td>${i.marginOk ? '达标' : `低于 ${yuan(i.floor)}`}</td>
      </tr>`)}
    </table>
    <p data-pp>价保退差 ${pp.orders} 单，${yuan(pp.amount)}${pp.needsCfo ? '，要 CFO 审批' : ''}</p>
    <ul data-blockers>${k.blockers.map((b) => html`<li>${b}</li>`)}</ul>
    ${k.status === 'live' ? html`<p class="chip chip--done">已上线</p>` : html`<button class="btn btn--primary" data-action="launch" ${k.canLaunch ? '' : 'disabled'}>一键上线</button>`}
  </section>`)
}

export function mount(root, ctx) {
  let state = { status: 'loading', check: null }
  const draw = () => { root.innerHTML = render(state) }
  const load = () => ctx.api.get('/api/campaign/check').then((check) => { state = { status: 'ready', check }; draw() }).catch((e) => { state = { status: 'error', check: null, error: e.message }; draw() })
  draw()
  load()
  const onChange = async (e) => {
    const row = e.target.closest('[data-sku]')
    if (!row) return
    const body = e.target.matches('[data-pct]') ? { pct: Number(e.target.value) } : { fullReduction: e.target.checked }
    try { state = { status: 'ready', check: await ctx.api.put(`/api/campaign/items/${row.dataset.sku}`, body) } } catch (err) { state = { ...state, error: err.message } }
    draw()
  }
  const onClick = async (e) => {
    if (!e.target.closest('[data-action="launch"]')) return
    try { await ctx.api.post('/api/campaign/launch'); ctx.motion.celebrate(ctx.fx) } catch (err) { state = { ...state, error: err.message } }
    load()
  }
  root.addEventListener('change', onChange)
  root.addEventListener('click', onClick)
  return () => { root.removeEventListener('change', onChange); root.removeEventListener('click', onClick) }
}
