/**
 * The board reads two sentences of the checks in their own English words (Finding.tsx GONE and UNTRACED) to tell a
 * hold no form can clear. Those words are the checks', so this test reads the checks' source (read only: the app
 * never imports or changes checks/) and fills in each sentence as the check writes it: a check reworded without the
 * board fails here instead of the board quietly offering forms that cannot help.
 */
/// <reference types="vite/client" />
import { describe, expect, test } from 'vitest'
import { GONE, UNTRACED } from './Finding'

/** A file of checks/lib, read as text. Node's fs, untyped here (the page has no Node types): it is outside the
 * app's root, which Vite's own ?raw import refuses. */
async function lib(name: string): Promise<string> {
  const fs = await import(/* @vite-ignore */ 'node:fs' as string)
  const here = import.meta.url // a variable: Vite turns new URL(…, import.meta.url) into an asset import
  return fs.readFileSync(new URL(`../../../../checks/lib/${name}`, here), 'utf-8') as string
}

/** The f-strings of the one call that holds *marker*, joined as Python joins adjacent literals. */
function sentence(src: string, marker: string): string {
  const call = src.split('\n').findIndex((l) => l.includes(marker))
  expect(call, `the check no longer says “${marker}”`).toBeGreaterThanOrEqual(0)
  const lines = src.split('\n').slice(call, call + 3)
  const parts: string[] = []
  for (const l of lines) {
    const m = [...l.matchAll(/f"((?:[^"\\]|\\.)*)"/g)]
    if (!m.length) break
    parts.push(...m.map((x) => x[1]))
    if (/\)\s*$/.test(l)) break // the call ends on this line
  }
  return parts.join('')
}

/** The sentence with each {…} filled in, in order. */
const fill = (s: string, values: string[]) => {
  let i = 0
  return s.replace(/\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}/g, () => values[i++] ?? '?')
}

describe('the checks’ own words the board reads', () => {
  test('UNTRACED is what checks/lib/check_trace.py writes of a commit citing a finding not fixed or justified',
    async () => {
      const s = sentence(await lib('check_trace.py'), 'which the approved triage does not fix or justify')
      for (const decision of ['defer', 'later', 'not in the batch']) {
        const text = fill(s, ['0123456789ab', 'F-022', decision])
        const m = UNTRACED.exec(`trace 没过：${text}`)
        expect(m, text).not.toBeNull()
        expect([m![1], m![2], m![3]]).toEqual(['0123456789ab', 'F-022', decision])
      }
    })

  test('GONE is what checks/lib/check_static.py writes of a finding no longer reported', async () => {
    const s = sentence(await lib('check_static.py'), 'no longer reported, but triaged as')
    for (const decision of ['later', 'defer']) {
      const text = fill(s, ['F-025', decision])
      const m = GONE.exec(`static 没过：${text}`)
      expect(m, text).not.toBeNull()
      expect([m![1], m![2]]).toEqual(['F-025', decision])
    }
  })
})
