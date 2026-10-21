// 公司商城活动模板：页面外壳和路由。一般不需要改。
//   #/        双十一活动页（pages/campaign.js），顾客看的
//   #/admin   运营后台（pages/admin.js）：改折扣、看上线前体检、一键上线
import { api } from './lib/api.js'
import * as motion from './motion/motion.js'
import * as campaign from './pages/campaign.js'
import * as admin from './pages/admin.js'

const PAGES = { campaign, admin }
const root = document.getElementById('app')
const fx = document.getElementById('fx')
let cleanup = null

function current() {
  return location.hash.startsWith('#/admin') ? 'admin' : 'campaign'
}

function show() {
  if (typeof cleanup === 'function') cleanup()
  const name = current()
  for (const a of document.querySelectorAll('[data-nav]')) a.classList.toggle('is-active', a.dataset.nav === name)
  root.replaceChildren()
  cleanup = PAGES[name].mount(root, { api, motion, fx, navigate: (hash) => { location.hash = hash } })
}

window.addEventListener('hashchange', show)
show()
