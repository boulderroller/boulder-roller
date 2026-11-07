# Boulder Roller docs (maintainer note)

Source for <https://docs.boulderroller.xyz>, built with VitePress and deployed
manually to Vercel after landing on `main`. From the repository root, run
`scripts/deploy-sites.sh docs/gitbook` to deploy the docs when they have changed.

```bash
npm install
npm run dev      # local preview
npm run build    # must pass (dead links fail the build)
```

Rider-facing vocabulary follows `docs/design/LANGUAGE_SPEC.md`; protocol
meaning follows `docs/PROTOCOL_TRUTHS.md`. This file is excluded from the site.
