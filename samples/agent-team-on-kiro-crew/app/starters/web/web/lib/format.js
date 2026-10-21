// 公司网页模板：拼 HTML 和格式化。
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

// 2026-10-11T12:30:05.000Z → 20:30:05（本地时间）
export const clock = (iso) => new Date(iso).toLocaleTimeString('zh-CN', { hour12: false })
