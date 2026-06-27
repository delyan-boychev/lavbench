# LavBench Frontend

React + Vite application with Tailwind CSS, i18next internationalization, and JSDoc-based type checking.

## Development

```bash
npm install
npm run dev          # Start dev server at http://localhost:5173
```

The API proxy is configured in `nginx.conf` for production and in `vite.config.js` for development.

## Scripts

| Command                      | Description                                        |
| ---------------------------- | -------------------------------------------------- |
| `npm run dev`                | Start Vite dev server with HMR                     |
| `npm run build`              | Production build to `dist/`                        |
| `npm run test`               | Run vitest unit/component tests (362 tests)        |
| `npm run test:coverage`      | Run tests with v8 coverage report                  |
| `npm run lint`               | ESLint across the project                          |
| `npm run check-types`        | TypeScript type check via `tsc --noEmit`           |
| `npm run generate-api-types` | Generate TypeScript declarations from OpenAPI spec |
| `npm run preview`            | Preview production build locally                   |

## Testing

```bash
# Unit and component tests
npm run test

# With coverage thresholds (lines ≥ 60%, statements ≥ 60%, branches ≥ 55%, functions ≥ 55%)
npm run test:coverage
```

Tests use **vitest** with **happy-dom** environment. API calls are mocked with **MSW**. Component tests use **@testing-library/react**.

## Translation Checking

English and Bulgarian locale files must stay in sync:

```bash
python3 scripts/check_translations.py
```

This validates key parity between `public/locales/en/translation.json` and `public/locales/bg/translation.json`. Runs automatically in CI.

## Type System

The frontend uses **JSDoc `@type` annotations** with an auto-generated TypeScript declaration file (`src/types/api.d.ts`). The pipeline:

1. Backend Flasgger docstrings define the OpenAPI spec
2. `openapi-typescript` generates `src/types/api.d.ts`
3. `tsc --noEmit` validates all types at build time

See [CONTRIBUTING.md](../CONTRIBUTING.md) for type system conventions.

## Architecture

```
frontend/
├── src/
│   ├── components/        # Reusable UI components
│   │   ├── admin/         # Admin panel components
│   │   ├── challenge/     # Challenge/task browsing
│   │   ├── layout/        # Navbar, CompetitionBar, ProtectedLayout
│   │   ├── leaderboard/   # Leaderboard table
│   │   ├── submissions/   # Submission list and viewer
│   │   └── ui/            # Shared UI primitives (Button, Modal, etc.)
│   ├── pages/             # Route-level page components
│   ├── services/          # ApiService, AuthContext, AppContext
│   ├── context/           # React context providers
│   ├── hooks/             # Custom hooks (useDebounce)
│   ├── utils/             # formatDate, metrics, timezones
│   └── types/             # Auto-generated api.d.ts
├── public/locales/        # i18n — en/, bg/
├── nginx.conf             # Nginx reverse proxy config
├── tsconfig.json          # TypeScript config (JSDoc mode)
├── vite.config.js         # Vite + vitest config
└── Dockerfile             # Multi-stage Node/Alpine + Nginx build
```

## Docker

```bash
docker build -t lavbench-frontend .
docker run -p 80:80 lavbench-frontend
```

The multi-stage build compiles the React app with `node:26-alpine`, then serves static assets via Nginx with API proxying to the backend.
