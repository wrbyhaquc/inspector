import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// dev: `npm run dev` on :5173 proxies API calls to the Python server on :8765
export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': 'http://127.0.0.1:8765' } },
})
