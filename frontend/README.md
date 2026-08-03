# LavBench Frontend

React 19 + Vite application styled with Vanilla CSS and Tailwind CSS, featuring i18next internationalization (English and Bulgarian), Server-Sent Events (SSE) live data streaming, and full JSDoc-based TypeScript validation.

---

## Development

```bash
# 1. Install dependencies
npm ci

# 2. Start Vite development server (http://localhost:5173)
npm run dev
```

The API reverse proxy is configured in `vite.config.js` for local development (proxying `/api` requests to `http://localhost:5001`) and in `nginx.conf` for production Docker deployments.

---

## Available Scripts

| Command | Description |
| :--- | :--- |
| `npm run dev` | Starts Vite dev server with Hot Module Replacement (HMR) at `:5173`. |
| `npm run build` | Builds optimized production bundle to `dist/`. |
| `npm run test` | Runs vitest unit and component test suite. |
| `npm run test:coverage` | Runs unit tests with v8 code coverage thresholds. |
| `npm run lint` | Runs ESLint across all frontend source files. |
| `npm run format` | Formats frontend source files using Prettier. |
| `npm run format:check` | Checks code formatting against Prettier rules. |
| `npm run check-types` | Validates TypeScript types using `tsc --noEmit`. |
| `npm run generate-api-types` | Auto-generates TypeScript declarations (`src/types/api.d.ts`) from backend OpenAPI spec (`/apidoc/openapi.json`). |
| `npm run preview` | Previews production build locally. |

---

## Testing & Quality Assurance

```bash
# Unit and component tests (vitest + happy-dom + MSW)
npm run test

# Run tests with coverage reporting (lines ≥ 60%, statements ≥ 60%, branches ≥ 55%, functions ≥ 55%)
npm run test:coverage

# TypeScript type checking
npm run check-types
```

Tests use **vitest** with a **happy-dom** environment. API calls are mocked using **MSW** (Mock Service Worker). Component tests use **@testing-library/react**.

---

## Translation Parity Checking

English (`public/locales/en/translation.json`) and Bulgarian (`public/locales/bg/translation.json`) locale files must maintain 100% symmetrical key structures:

```bash
python3 scripts/check_translations.py
```

This script validates key symmetry and detects missing or orphaned translation keys. Runs automatically in CI (`.github/workflows/ci.yml`).

---

## Type System Architecture

The frontend uses **JSDoc `@type` annotations** coupled with auto-generated TypeScript declarations (`src/types/api.d.ts`):

1. Backend spectree `@api.validate` decorators generate the OpenAPI 3.0 spec at `/apidoc/openapi.json`.
2. `npm run generate-api-types` runs `openapi-typescript` to update `src/types/api.d.ts`.
3. `npm run check-types` executes `tsc --noEmit` to validate all JSDoc types and React component props without requiring `.ts`/`.tsx` extensions.

---

## Project Structure

```text
frontend/
├── src/
│   ├── components/        # Reusable UI components
│   │   ├── admin/         # Admin panel modals, worker specs, task forms
│   │   ├── challenge/     # Challenge cards, stage selector, task rules
│   │   ├── layout/        # Navbar, CompetitionBar, ProtectedLayout
│   │   ├── leaderboard/   # Live leaderboard table & score breakdown
│   │   ├── submissions/   # Submission list, code cell viewer & log stream
│   │   └── ui/            # UI primitives (Button, Modal, Toast, Badge)
│   ├── pages/             # Route page components (Login, Admin, Challenge, etc.)
│   ├── services/          # ApiService (fetch wrapper), AuthContext, AppContext
│   ├── context/           # React context providers
│   ├── hooks/             # Custom hooks (useDebounce, useSSE)
│   ├── utils/             # Dates, metric formatters, timezone utilities
│   └── types/             # Auto-generated api.d.ts declarations
├── public/locales/        # i18n translation JSON files (en/, bg/)
├── nginx.conf             # Nginx production reverse proxy config
├── tsconfig.json          # TypeScript config (JSDoc checkJs mode)
├── vite.config.js         # Vite dev server + vitest configuration
└── Dockerfile             # Multi-stage Node/Alpine build + Nginx container
```

---

## Sphinx Documentation

To build Sphinx documentation from the frontend directory:

```bash
pip install -r ../docs/requirements.txt
cd ../docs && make html
```

---

## Docker Deployment

```bash
# Build production frontend container
docker build -t lavbench-frontend .

# Run container on port 80
docker run -p 80:80 lavbench-frontend
```
