import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    rollupOptions: {
      output: {
        // The framework changes far less often than the app, so it gets its own file: both download in
        // parallel, and a returning visitor keeps the framework cached across deploys.
        manualChunks(id) {
          if (/node_modules\/(react|react-dom|react-router|react-router-dom|scheduler|@tanstack)\//.test(id)) return 'framework'
        },
      },
    },
  },
  server: {
    proxy: {
      '/auth': 'http://localhost:8000',
      '/github': 'http://localhost:8000',
    },
  },
})
