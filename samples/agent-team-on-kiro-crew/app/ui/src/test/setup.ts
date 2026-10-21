/**
 * Per-test environment: jsdom has no matchMedia, scrollIntoView or clipboard; the host sets data-mode /
 * data-theme on <html>. Every test starts on the page's own URL with empty stubs and storage.
 */
import '@testing-library/jest-dom/vitest'
import { afterEach, beforeEach, vi } from 'vitest'
import { cleanup } from '@testing-library/react'
import { resetStubs } from './stubs/app-sdk'

const listeners = new Set<() => void>()

beforeEach(() => {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    configurable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: (_: string, cb: () => void) => void listeners.add(cb),
      removeEventListener: (_: string, cb: () => void) => void listeners.delete(cb),
      addListener: (cb: () => void) => void listeners.add(cb),
      removeListener: (cb: () => void) => void listeners.delete(cb),
      dispatchEvent: () => false,
    })),
  })
  HTMLElement.prototype.scrollIntoView = vi.fn()
  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: { writeText: vi.fn(async () => {}), readText: vi.fn(async () => '') },
  })
  document.documentElement.dataset.mode = 'dark'
  document.documentElement.dataset.theme = 'kiro-dark'
  window.history.replaceState(null, '', '/apps/aidlc-team')
  resetStubs()
  localStorage.clear()
})

afterEach(() => {
  cleanup()
  listeners.clear()
  localStorage.clear()
})
