/**
 * The board's two languages. The fixed text of the page lives in zh.json and en.json under one key each; t(key,
 * params) returns it in the language chosen in the app bar, with {name} replaced from params. The language is read
 * from this browser's storage when the page loads (Chinese by default) and switching reloads the page, so that the
 * tables built when a module loads are in the new language too.
 *
 * Not translated, by design: finding IDs (F-xxx), check names (build, static, unit …), file paths, commits, commands,
 * and what the backend and the agents write (event texts without a code, reasons, replies, the audit trail's own
 * words); events that carry a code are rendered from ev.<code> here.
 */
import zh from './zh.json'
import en from './en.json'

export type Lang = 'zh' | 'en'
export const LANG_KEY = 'vstatd-team:lang'
const DICTS: Record<Lang, Record<string, string>> = { zh, en }

function stored(): Lang {
  try {
    return typeof localStorage !== 'undefined' && localStorage.getItem(LANG_KEY) === 'en' ? 'en' : 'zh'
  } catch {
    return 'zh'
  }
}

let current: Lang = stored()
if (typeof document !== 'undefined') document.documentElement.lang = current === 'en' ? 'en' : 'zh-CN'

/** The language of this page load. */
export const lang = (): Lang => current
/** The locale for dates, times and numbers. */
export const locale = (): string => (current === 'en' ? 'en-US' : 'zh-CN')

export type Params = Record<string, string | number | boolean | null | undefined>

export function format(s: string, params?: Params): string {
  return params ? s.replace(/\{(\w+)\}/g, (m, k: string) => (k in params ? String(params[k] ?? '') : m)) : s
}

export function t(key: string, params?: Params): string {
  return format(DICTS[current][key] ?? DICTS.zh[key] ?? key, params)
}

/** Whether a key exists (an event code the dictionary knows). */
export const has = (key: string): boolean => key in DICTS.zh

/** Remembers the choice and reloads the page in it. */
export function setLang(next: Lang): void {
  try {
    localStorage.setItem(LANG_KEY, next)
  } catch {
    /* storage refused: the choice lasts until the reload */
  }
  current = next
  if (typeof location !== 'undefined' && !/jsdom/.test(navigator.userAgent)) location.reload()
}
