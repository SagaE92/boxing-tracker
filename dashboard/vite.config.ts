import { svelte } from '@sveltejs/vite-plugin-svelte'
import { defineConfig } from 'vite'

// Relative base: the same build works on GitHub Pages (/boxing-tracker/),
// any static server, and `npx vite preview`.
export default defineConfig({
  base: './',
  plugins: [svelte()],
  build: { outDir: 'dist', emptyOutDir: true, chunkSizeWarningLimit: 900 },
  server: { fs: { allow: ['..'] } },
})
