# ClaimSage frontend

The ClaimSage frontend is a React, TypeScript, and Vite application styled with
Tailwind CSS v4. Its initial dashboard is intentionally a placeholder and does
not connect to authentication or backend APIs yet.

## Development

```powershell
npm install
npm run dev
```

## Validation

```powershell
npm run typecheck
npm run lint
npm run build
```

## Structure

- `src/app` — app shell and top-level layout
- `src/components/ui` — reusable shadcn-style primitives
- `src/features` — feature pages, starting with the dashboard
- `src/hooks` — shared React hooks
- `src/lib` — shared utilities and TanStack Query client
- `src/types` — shared TypeScript contracts

The visual system uses Midnight Graphite, Warm Ivory, Emerald, and subtle
Champagne Gold, with Inter and Space Grotesk typography.
