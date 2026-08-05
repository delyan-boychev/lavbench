// Advisory comment-style checks (mirrors backend scripts/check_comments.py).
// Not part of the main lint config — run via `npm run lint:comments` or the
// frontend-comment-style CI job, which never blocks merges.

import { defineConfig, globalIgnores } from 'eslint/config';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';

// Matches backend/scripts/check_comments.py DIVIDER_BANNER: banners made of
// '=' '─' '═' '█' '░' '*' '-' '_' '~' etc. are forbidden; '// ── Title ──'
// (U+2500) stays the allowed convention.
const DIVIDER_BANNER = /^(?:[═█░·•−_*~]|={2,}|-{2,}|\*{2,}){3,}$/;

const noBannerDivider = {
  meta: {
    type: 'problem',
    docs: {
      description: 'Forbid decorative divider banners',
    },
  },
  create(context) {
    return {
      'Program:exit'() {
        for (const comment of context.sourceCode.getAllComments()) {
          if (DIVIDER_BANNER.test(comment.value.trim())) {
            context.report({
              loc: comment.loc,
              message: "Forbidden divider banner — use '// ── Title ──'",
            });
          }
        }
      },
    };
  },
};

export default defineConfig([
  globalIgnores(['dist', 'coverage']),
  {
    files: ['**/*.{js,jsx}'],
    plugins: {
      'comment-style': { rules: { 'no-banner-divider': noBannerDivider } },
      // Loaded so existing eslint-disable directives referencing their rules
      // resolve; their rules stay disabled in this advisory config.
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    languageOptions: {
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    rules: {
      'comment-style/no-banner-divider': 'warn',
      'spaced-comment': ['warn', 'always'],
      'capitalized-comments': [
        'warn',
        'always',
        {
          ignorePattern:
            'eslint|jsx|ts-|@|i18n|api|http|url|uuid|jwt|csrf|sse|json|db|id|css|html|img|src|formdata|fetch',
        },
      ],
      'no-warning-comments': [
        'warn',
        { terms: ['TODO', 'FIXME', 'HACK', 'XXX'], location: 'start' },
      ],
    },
  },
]);
