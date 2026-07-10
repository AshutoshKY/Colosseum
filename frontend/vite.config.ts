import { defineConfig } from 'vitest/config'
import { loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  return {
    plugins: [react()],
    server: {
      host: '0.0.0.0',
      proxy: {
        '/api': env.VITE_API_URL || 'http://127.0.0.1:8100',
      },
    },
    test: { environment: 'jsdom', globals: true },
  }
})
