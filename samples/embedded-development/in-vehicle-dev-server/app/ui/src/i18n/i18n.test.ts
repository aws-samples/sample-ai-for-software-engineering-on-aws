/**
 * The two dictionaries and what keeps the page in them: the same keys and params in zh.json and en.json, no Chinese
 * left in the page's code outside the dictionaries (a line that must keep it says why: // i18n-keep), and the
 * messages by code rendering from their params (in Chinese the text is shown as the app wrote it).
 */
/// <reference types="vite/client" />
import ts from 'typescript'
import { describe, expect, test } from 'vitest'
import zh from './zh.json'
import en from './en.json'
import { format, lang, locale, t } from './index'
import { evText, msgText } from './events'

const CJK = /[\u3400-\u9fff\u3000-\u303f\uff00-\uffef]/
const params = (s: string) => [...new Set([...s.matchAll(/\{(\w+)\}|\[\[(\w+)\|/g)].map((m) => m[1] ?? m[2]))].sort()
// an English amount says thousands where the Chinese says 万 (tens of thousands): both get both numbers
const OWN_PARAMS = new Set(['board.SignOff.1'])

describe('the dictionaries', () => {
  test('zh.json and en.json have the same keys, and each entry the same params', () => {
    expect(Object.keys(en).sort()).toEqual(Object.keys(zh).sort())
    const differ = Object.keys(zh).filter((k) => !OWN_PARAMS.has(k) && params(zh[k as keyof typeof zh]).join() !== params(en[k as keyof typeof en]).join())
    expect(differ).toEqual([])
  })

  test('en.json is English: no Chinese outside the protocol words a person types or the language names', () => {
    const KEEP = new Set(['AppBar.lang.zh'])
    expect(Object.entries(en).filter(([k, v]) => !KEEP.has(k) && CJK.test(v)).map(([k]) => k)).toEqual([])
  })

  test('the page loads in Chinese by default, with its dates and numbers in zh-CN', () => {
    expect(lang()).toBe('zh')
    expect(locale()).toBe('zh-CN')
    expect(t('AppBar.1')).toBe('团队看板')
    expect(format('{a}/{b}', { a: 1 })).toBe('1/{b}')
  })
})

/** Every string, template and JSX text in the page's code (src and the preview) that holds Chinese, by file:line. */
const SOURCES = import.meta.glob<string>(['../**/*.{ts,tsx}', '!../**/*.test.{ts,tsx}', '!../i18n/**', '!../test/**', '!../types.ts', '../../preview/main.tsx'],
  { query: '?raw', import: 'default', eager: true })

function chineseLiterals(): string[] {
  const out: string[] = []
  for (const [file, text] of Object.entries(SOURCES)) {
    const lines = text.split('\n')
    const src = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, file.endsWith('x') ? ts.ScriptKind.TSX : ts.ScriptKind.TS)
    const visit = (n: ts.Node) => {
      let s: string | null = null
      if (ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n)) s = n.text
      else if (ts.isTemplateExpression(n)) s = n.getText()
      else if (ts.isJsxText(n)) s = n.text
      else if (n.kind === ts.SyntaxKind.RegularExpressionLiteral) s = n.getText()
      if (s !== null) {
        s = s.replace(/\/\*[\s\S]*?\*\//g, '') // a stylesheet's comments
        const line = src.getLineAndCharacterOfPosition(n.getStart()).line
        if (CJK.test(s) && !/i18n-keep/.test(lines[line])) out.push(`${file}:${line + 1}: ${s.trim().slice(0, 40)}`)
        if (ts.isTemplateExpression(n)) return
      }
      ts.forEachChild(n, visit)
    }
    visit(src)
  }
  return out
}

describe('the guard', () => {
  test('no Chinese in the page\'s code outside the dictionaries (types.ts and the tests aside)', () => {
    expect(Object.keys(SOURCES).length).toBeGreaterThan(30)
    expect(Object.keys(SOURCES)).toContain('../../preview/main.tsx')
    expect(chineseLiterals()).toEqual([])
  })
})

describe('messages by code', () => {
  const roles = [{ key: 'dev-fix', title: '开发 · 修复' }, { key: 'triage', title: '分诊', gate_label: '分诊' }]

  test('every ev.<code> renders from its params, roles named, optional parts shown only when set', () => {
    expect(msgText('handoff', { r_from: 'triage', outs: ['triage.json', 'triage.md'], r_role: 'dev-fix' }, roles)).toBe('分诊把 triage.json、triage.md 交给开发 · 修复')
    expect(msgText('handoff', { r_from: 'triage', outs: [], r_role: 'dev-fix' }, roles)).toBe('分诊把 产出 交给开发 · 修复')
    expect(msgText('approved', { g_gate: 'triage', note: '' }, roles)).toBe('人批准了分诊')
    expect(msgText('plan.split', { r_role: 'triage', plan: [{ r_role: 'dev-fix', what: 'x' }], skip: [] }, roles)).toBe('分诊提议分工：开发 · 修复 · x')
    expect(msgText('failed.bench', { why: { code: 'hold.no_artifact', params: { artifact: 'vstatd' } } })).toBe('台架要人处理：没有要部署的构建 vstatd（build.sh 的产物）')
    for (const k of Object.keys(zh).filter((x) => x.startsWith('ev.') && !x.startsWith('ev.sep.'))) {
      const code = k.slice(3)
      const p = Object.fromEntries(params(zh[k as keyof typeof zh]).map((n) => [n, n.startsWith('r_') || n.startsWith('g_') ? 'dev-fix' : 1]))
      expect(msgText(code, p, roles), code).not.toMatch(/\{\w+\}|\[\[|\]\]/)
    }
  })

  test('in Chinese an event shows its text as the app wrote it; without a code too', () => {
    expect(evText({ text: '分诊完成：旧的', code: 'done', params: { r_role: 'triage', summary: '新的' } }, roles)).toBe('分诊完成：旧的')
    expect(evText({ text: '分诊完成：旧的' })).toBe('分诊完成：旧的')
  })
})
