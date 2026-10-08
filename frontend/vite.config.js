import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

// Exact package names: a substring test for 'react' would also catch react-markdown,
// lucide-react, react-i18next and @tanstack/react-query
const REACT_CORE = new Set(['react', 'react-dom', 'scheduler', 'react-router', 'react-router-dom']);
const MARKDOWN_PKG =
  /^(react-markdown|remark-|rehype-|micromark|mdast-|hast-|unist-|vfile|unified$|bail$|trough$|devlop$|zwitch$|ccount$|longest-streak$|markdown-table$|trim-lines$|property-information$|(space|comma)-separated-tokens$|character-(entities|reference)|decode-named-character-reference$|html-url-attributes$|style-to-|inline-style-parser$|is-plain-obj$|extend$|estree-util-|is-(alphabetical|alphanumerical|decimal|hexadecimal)$)/;

function packageName(id) {
  const match = /.*\/node_modules\/((?:@[^/]+\/)?[^/]+)\//.exec(id.replace(/\\/g, '/'));
  return match ? match[1] : null;
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          const pkg = packageName(id);
          if (!pkg || pkg === 'prismjs') return undefined;
          if (REACT_CORE.has(pkg) || pkg.startsWith('@remix-run/')) return 'vendor-react';
          if (MARKDOWN_PKG.test(pkg)) return 'vendor-markdown';
          if (pkg.includes('i18next')) return 'vendor-i18n';
          return 'vendor-helpers';
        },
      },
    },
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:5001',
        changeOrigin: true,
      },
    },
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
        lines: 60,
        functions: 55,
        branches: 55,
        statements: 60,
      },
    },
  },
});
