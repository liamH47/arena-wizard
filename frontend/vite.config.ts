import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// In development the API runs separately on :8000; the proxy keeps every request
// same-origin, which is how production serves it (FastAPI serves the built files).
const backend = 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': backend,
      '/auth': backend,
      '/healthz': backend,
      '/readyz': backend,
    },
  },
})
