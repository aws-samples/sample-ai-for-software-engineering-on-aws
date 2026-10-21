// 公司商城活动模板：拼 HTML 和格式化。
//   html`<p>${name}</p>`  插进去的值自动转义（数组会逐项拼接，嵌套的 html`` 不再转义）
//   raw(s)                确定安全的 HTML 片段（只给模板自己的常量用）

const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }
export const escape = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ESC[c])

class Safe {
  constructor(s) {
    this.s = s
  }
  toString() {
    return this.s
  }
}
export const raw = (s) => new Safe(String(s))

function part(v) {
  if (v instanceof Safe) return v.s
  if (Array.isArray(v)) return v.map(part).join('')
  if (v === false || v === null || v === undefined) return ''
  return escape(v)
}

export function html(strings, ...values) {
  let out = strings[0]
  values.forEach((v, i) => {
    out += part(v) + strings[i + 1]
  })
  return new Safe(out)
}

// 4319 → ¥4,319（元，四舍五入到元）
export const yuan = (n) => `¥${Math.round(Number(n) || 0).toLocaleString('zh-CN')}`

// 85 → 8.5 折，80 → 8 折，100 → 不打折
export const zhe = (pct) => (pct >= 100 ? '不打折' : `${(pct / 10).toString()} 折`)

// 毫秒差 → { d, h, m, s }（倒计时用；负数当 0）
export function parts(ms) {
  const t = Math.max(0, Math.floor(ms / 1000))
  return { d: Math.floor(t / 86400), h: Math.floor((t % 86400) / 3600), m: Math.floor((t % 3600) / 60), s: t % 60 }
}
