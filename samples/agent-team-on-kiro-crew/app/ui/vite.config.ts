import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// KiroCrew App bundle: one ESM file whose DEFAULT export is the page component AppHost renders.
// react, react-dom, react/jsx-runtime, @kirocrew/app-sdk, @kirocrew/app-sdk/ui and lucide-react come
// from the host import map, so they stay external.
export default defineConfig({
  plugins: [react()],
  build: {
    lib: { entry: 'src/main.tsx', formats: ['es'], fileName: () => 'index.mjs' },
    outDir: 'dist',
    emptyOutDir: true,
    cssCodeSplit: false,
    sourcemap: false,
    target: 'es2022',
    rollupOptions: {
      external: ['react', 'react-dom', 'react-dom/client', 'react/jsx-runtime', '@kirocrew/app-sdk', '@kirocrew/app-sdk/ui', 'lucide-react'],
    },
  },
})
