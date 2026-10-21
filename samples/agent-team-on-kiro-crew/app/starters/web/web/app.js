// 公司网页模板：页面外壳和路由。一般不需要改，页面在 pages/index.js 里登记。
//   #/<页面名>  显示 pages/<页面名>.js；没写页面名时显示登记的第一个
//   每个页面自己的样式是 styles/<页面名>.css（有就加载）
import { api } from './lib/api.js'
import * as motion from './motion/motion.js'
import { pages } from './pages/index.js'

const root = document.getElementById('app')
const fx = document.getElementById('fx')
const nav = document.getElementById('nav')
const names = Object.keys(pages)
let cleanup = null

nav.replaceChildren(...names.map((name) => {
  const a = document.createElement('a')
  a.href = `#/${name}`
  a.dataset.nav = name
  a.textContent = pages[name].title
  return a
}))
nav.hidden = names.length < 2

function current() {
  const name = location.hash.replace(/^#\/?/, '').split(/[/?]/)[0]
  return names.includes(name) ? name : names[0]
}

function style(name) {
  let link = document.getElementById('page-style')
  if (!link) {
    link = document.createElement('link')
    link.id = 'page-style'
    link.rel = 'stylesheet'
    document.head.append(link)
  }
  link.href = `styles/${name}.css`
}

async function show() {
  if (typeof cleanup === 'function') cleanup()
  cleanup = null
  const name = current()
  for (const a of nav.querySelectorAll('[data-nav]')) a.classList.toggle('is-active', a.dataset.nav === name)
  style(name)
  root.replaceChildren()
  const page = await pages[name].load()
  cleanup = page.mount(root, { api, motion, fx, navigate: (hash) => { location.hash = hash } })
}

window.addEventListener('hashchange', show)
show()
