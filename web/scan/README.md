# BoulderScan

Public on-chain explorer frontend for the Boulder Roller protocol.

## Local development

```bash
npm install
npm run dev
npm test
```

By default the app expects the indexer API on `/api` and proxies that path to
`http://localhost:3001` during Vite development.

## Environment

- `VITE_SCAN_API_URL` - Base URL for the public read API. Defaults to `/api`.
- `VITE_SCAN_API_PROXY_TARGET` - Optional explicit proxy target for local dev.
- `VITE_USE_SCAN_FIXTURES` - When `true`, render against local fixture data.
- `VITE_ALLOW_FIXTURE_FALLBACK` - When `true`, dev mode may fall back to fixtures
  if the API is unavailable. Default is `false` so backend failures stay visible.

## Launch verification

Run the automated launch checks from `web/scan`:

```bash
npm run smoke:launch
npm run smoke:browser
```

Useful overrides:

- `BOULDERSCAN_API_URL` - API base URL, defaults to `http://localhost:3001`
- `BOULDERSCAN_FRONTEND_URL` - frontend base URL, defaults to `http://localhost:3004`
- `BOULDERSCAN_CLIMB_ID` - known climb id for route checks; when omitted, launch smoke derives one from `/v1/observatory` `top_vaults` and browser smoke derives one from the Observatory climb links
- `BOULDERSCAN_VAULT_ID` - legacy fallback for older scripts; `BOULDERSCAN_CLIMB_ID` wins
- `BOULDERSCAN_TX_SIGNATURE` - optional known signature for transaction route checks
- `BOULDERSCAN_ACCOUNT_PUBKEY` - optional known pubkey for account route checks
- `BOULDERSCAN_SKIP_FRONTEND=true` - skip direct frontend route checks

For public HTTPS URLs, `smoke:launch` also verifies DNS resolution, TLS
validation, `/health` indexer freshness status, `scan_freshness.v1` payloads,
the frontend `/api/health` facade, API CORS headers, and CORS preflight
behavior from the frontend origin.

`smoke:browser` launches Chromium with Playwright, waits for the Observatory,
Climb, Transaction, and Account sections to hydrate, and fails if a page
remains stuck in a loading or unavailable page state.

## Production contract

- Frontend host: `scan.boulderroller.xyz`
- Public API host: `scan-api.boulderroller.xyz`
- API owner: the TypeScript indexer service on port `3001`

## Launch scope

BoulderScan v1 includes only:

- Observatory (`/`)
- Climb (`/climb/:id`)
- Legacy vault redirect (`/vault/:id`)
- Transaction (`/tx/:signature`)
- Account (`/account/:pubkey`)
