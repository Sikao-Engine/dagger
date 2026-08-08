import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { resolve } from 'node:path'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const serverUrl = env.VITE_SERVER_URL || 'http://localhost:8000'

  return {
    base: './',
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: {
        '@': resolve(__dirname, 'src'),
        '@sdk': resolve(__dirname, 'src/sdk'),
        '@core': resolve(__dirname, 'src/core'),
        '@ui': resolve(__dirname, 'src/ui'),
        '@lib': resolve(__dirname, 'src/lib'),
        '@pages': resolve(__dirname, 'src/core/pages'),
      },
    },
    define: {
      'import.meta.env.VITE_SERVER_URL': JSON.stringify(serverUrl),
    },
    server: {
      port: 5173,
      proxy: {
        '/api': {
          target: serverUrl,
          changeOrigin: true,
        },
      },
    },
    build: {
      outDir: 'dist',
      emptyOutDir: true,
      sourcemap: true,
      rollupOptions: {
        output: {
          manualChunks: {
            vendor: ['react', 'react-dom', 'react-router-dom'],
            flow: ['@xyflow/react'],
            table: ['@tanstack/react-table', '@tanstack/react-virtual', 'react-virtuoso'],
            ui: ['lucide-react', 'date-fns', 'zustand', 'clsx', 'tailwind-merge', 'class-variance-authority'],
          },
        },
      },
    },
    test: {
      globals: true,
      environment: 'jsdom',
      setupFiles: ['./src/test-setup.ts'],
      css: true,
    },
  }
})
