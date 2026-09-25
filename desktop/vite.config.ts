import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'

// A static SPA. `strictPort` because Tauri's devUrl points at exactly one port,
// and a silent fallback to 5184 would open a window on a dead origin.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  clearScreen: false,
  // `FH_` is read in dev only; config/check-no-hardcoded-host.mjs is the gate
  // that stops a build-time value from ever reaching a production bundle.
  envPrefix: ['VITE_', 'FH_'],
  server: {
    host: '127.0.0.1',
    port: 5183,
    strictPort: true,
    watch: { ignored: ['**/src-tauri/**'] },
  },
  build: {
    target: 'esnext',
    outDir: 'dist',
    sourcemap: true,
  },
})
