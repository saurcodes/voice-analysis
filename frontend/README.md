# Vocal Coach frontend

Vite + React + TypeScript app. Design tokens, owned shadcn/ui components, generated API types
and the test harness are set up in Plan 5 Task 1; pages land in later tasks.

## Scripts

- `npm run dev` - start the dev server (proxies `/api` to `http://localhost:8000`)
- `npm run build` - type-check and build for production
- `npm test` - run the Vitest suite once
- `npm run test:watch` - run Vitest in watch mode
- `npm run lint` - run ESLint
- `npm run gen:api` - regenerate `src/api/types.ts` from `../backend/openapi.json` (never hand-edit that file)
