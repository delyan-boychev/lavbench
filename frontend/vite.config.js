import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
  ],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules')) {
            if (
              id.includes('react-dom') || 
              id.includes('react-router-dom') || 
              id.includes('react-router') || 
              id.includes('@remix-run') || 
              id.includes('react')
            ) {
              return 'vendor-react';
            }
            if (
              id.includes('prismjs') || 
              id.includes('react-markdown') || 
              id.includes('remark-gfm') || 
              id.includes('micromark') || 
              id.includes('mdast') || 
              id.includes('unist')
            ) {
              return 'vendor-markdown';
            }
            if (id.includes('i18next')) {
              return 'vendor-i18n';
            }
            return 'vendor-helpers';
          }
        }
      }
    }
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:5001',
        changeOrigin: true,
      }
    }
  },
  test: {
    globals: true,
    environment: 'happy-dom',
    setupFiles: './src/setupTests.js',
    exclude: ['node_modules/**'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html', 'lcov'],
      reportsDirectory: './coverage',
      include: ['src/**/*.{js,jsx}'],
      exclude: [
        'src/**/*.test.{js,jsx}',
        'src/mocks/**',
        'src/setupTests.js',
        'src/types/**',
        'src/i18n.js',
        'src/main.jsx',
      ],
      thresholds: {
        lines: 55,
        functions: 55,
        branches: 55,
        statements: 55,
      },
    },
  }
})
