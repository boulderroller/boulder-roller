# Web Applications

## Structure

| Folder | Framework | Purpose | Status |
|--------|-----------|---------|--------|
| `portal/` | Vite + React | Main dashboard (Figma export) | **Active** - wiring to backend |
| `org/` | Next.js | Marketing/landing site | Active |
| `portal-v2.zip` | - | Backup of Figma export | Archive |

## Portal (Vite)

The main Boulder Roller dashboard. Exported from Figma, being wired to FastAPI backend.

```bash
cd portal
npm install
npm run dev
```

API (browser): `/api` (same-origin facade). Upstream target is `https://api.boulderroller.xyz` in production and `http://localhost:8080` in local dev.

### Production deploy contract

`app.boulderroller.xyz` serves the active `portal/` Vite app. Two Vercel project-root shapes are supported and checked by `cd portal && npm run perf:delivery`:

- Project root `web/portal`: build with `npm run build`, output `build`.
- Project root `web`: build with `cd portal && npm install && npm run build`, output `portal/build`.

Do not point the app domain at `org/`; it is a separate surface.

## Org (Marketing)

Landing page with 3D beetle, waitlist signup. The canonical public root is
`https://boulderroller.xyz`; `.com` and `.org` should redirect into the
canonical `.xyz` product world.

```bash
cd org
npm install
npm run dev
```
