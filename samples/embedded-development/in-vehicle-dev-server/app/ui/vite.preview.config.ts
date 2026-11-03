import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'

/**
 * The standalone preview (preview/ → preview-dist/index.html): the page with fixture data and the
 * stubbed SDK, for screenshots without KiroCrew. Same aliases as vitest.config.ts, and React is
 * bundled IN (there is no host import map here). The app bundle (vite.config.ts → dist/index.mjs)
 * is a separate build and keeps React external.
 *
 * The bundle is inlined into index.html so the one file opens from file:// as well (browsers refuse
 * module scripts from file:// URLs, not inline ones).
 */
const here = (p: string) => fileURLToPath(new URL(p, import.meta.url))
const stub = (name: string) => here(`./src/test/stubs/${name}`)

function inlineBundle(): Plugin {
  return {
    name: 'kt-preview-inline',
    enforce: 'post',
    generateBundle(_options, bundle) {
      const html = Object.values(bundle).find((f) => f.type === 'asset' && f.fileName.endsWith('.html'))
      if (!html || html.type !== 'asset') return
      let source = String(html.source)
      for (const [name, chunk] of Object.entries(bundle)) {
        if (chunk.type !== 'chunk') continue
        const file = chunk.fileName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
        const tag = new RegExp(`<script[^>]*src="[^"]*${file}"[^>]*></script>`)
        if (!tag.test(source)) continue
        const code = chunk.code.replace(/<\/script/gi, '<\\/script')
        source = source.replace(tag, () => `<script type="module">${code}</script>`)
        delete bundle[name]
      }
      html.source = source
    },
  }
}

export default defineConfig({
  root: here('./preview'),
  base: './',
  plugins: [react(), inlineBundle()],
  resolve: {
    alias: [
      { find: '@kirocrew/app-sdk/ui', replacement: stub('app-sdk-ui.tsx') },
      { find: '@kirocrew/app-sdk', replacement: stub('app-sdk.tsx') },
      { find: 'lucide-react', replacement: stub('lucide.tsx') },
    ],
  },
  build: {
    outDir: here('./preview-dist'),
    emptyOutDir: true,
    target: 'es2022',
    modulePreload: false,
    cssCodeSplit: false,
    sourcemap: false,
    assetsInlineLimit: 100_000_000,
    chunkSizeWarningLimit: 4000,
  },
})
