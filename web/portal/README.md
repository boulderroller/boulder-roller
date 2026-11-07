# Boulder Roller Portal

This package contains the authenticated Boulder Roller web portal. The portal is
the rider reading surface for rides, climbs, records, proof, portfolio state,
and account settings.

## Product Direction

Use these files before changing portal copy, layout, or product hierarchy:

- `../../docs/PORTAL_TRUTHS.md`
- `../../docs/design/BR_IDENTITY_SYSTEM.md`
- `../../docs/design/LANGUAGE_SPEC.md`
- `../../docs/design/PRODUCT_PATH_REGISTRY.md`
- `./DESIGN_SYSTEM_RULES.md`
- `../../AGENTS.md`

Do not use old source-adjacent markdown plans as current direction. Historical
portal planning files that used to live under `src/` are archived at
`../../history/docs/portal-src-markdown-archive-2026-06-03/`.

## Running Locally

```bash
npm install
npm run dev
```

Useful gates:

```bash
npm run typecheck:gate
npm run nomenclature:gate
npm run test:e2e -- e2e/portal-v2-routes.spec.ts
```
