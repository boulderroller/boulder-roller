# Client Contract Compatibility Inventory — 2026-04-21

Scope: compatibility lanes left intentionally open after the `client.v1` contract integration. Canonical clients should read Climb-first DTOs and proof surfaces; these aliases exist only to keep deployed clients, old URLs, and operator habits safe during rollout.

| Alias | Owner | Active Consumer | Current Behavior | Retirement Plan |
| --- | --- | --- | --- | --- |
| Backend `/segments/*` | Backend API | Portal route alias, historical tests, older mobile/portal clients | Mounted to the canonical climbs router as an explicit compatibility alias | Keep through alpha client rollout, then remove the mount and flip naming gates to forbid new `/segments` dependencies |
| Backend response `segments` / `segment_id` / `segment_name` | Backend API | Older portal/mobile clients expecting segment-era keys | Mirrored from canonical `climbs`, `climb_id`, and `climb_name` fields | Remove after deployed clients consume `client.v1` `ClimbSummary` / `RecordBoard` fields only |
| Indexer `/v1/vaults` and `/v1/vaults/:id` | Indexer API | BoulderScan fallback, legacy dashboards, operator scripts | Serves vault-first read model while `/v1/climbs` becomes canonical | Keep as fallback until BoulderScan and operator scripts use `/v1/climbs`; then redirect detail URLs and remove list fallback |
| BoulderScan `/vault/:id` | BoulderScan UI | Shared old links and explorer bookmarks | Redirects to canonical climb page instead of owning a separate vault page | Keep redirect permanently if links are public; remove only if analytics show no meaningful traffic |
| BoulderScan `getVault` / `getVaults` | BoulderScan API adapter | Deploy-order fallback while indexer rolls from vault to climb routes | `getClimb()` tries canonical `/v1/climbs/:id`, then falls back to legacy `/v1/vaults/:id` on 404 | Remove fallback after production indexer exposes `/v1/climbs` in all environments |
| Mobile `getVault` / `getVaults` | Mobile API adapter | Existing mobile screens/tests during naming migration | Delegates to canonical climb reads; exposed only as compatibility names | Remove when all mobile screens call `getClimbs` / `getClimb` directly and current app versions are outside support window |
| Portal `getVault*` economic methods | Portal API adapter | Vault staking/distribution UI | Still valid for economic vault actions and history, not climb identity | Keep where the domain object is the optional vault economy; rename only route/read identity calls, not vault-specific economics |
| Portal `/segments/:climbId` | Portal router | Old deep links | Renders the canonical `ClimbView` | Keep as redirect/alias through rollout; prefer `/climbs/:climbId` in all new navigation |

`boulderroller-v2-ejy8` remains blocked until deployed mobile, portal, BoulderScan, bots, and operator scripts no longer depend on these compatibility lanes.

## Enforcement Added 2026-04-21

- `backend/tests/truths/alignment/test_client_contract_integration_gate.py` now asserts mobile compatibility methods delegate to `getClimbs` / `getClimb` instead of calling `/vaults` directly.
- The same gate asserts portal canonical identity reads use `/climbs/*` while segment response aliases remain explicit compatibility fallbacks.
- BoulderScan is allowed to keep `getVault()` only as a named deploy-order fallback from canonical `/v1/climbs/:id` to legacy `/v1/vaults/:id`.

## Retirement Conditions

- **Mobile:** all screens and stores call `getClimbs` / `getClimb`; one public release cycle has elapsed with no supported app version depending on `getVault*`.
- **Portal:** all navigation emits `/climbs/:climbId`; `/segments/:climbId` remains only a redirect/deep-link alias.
- **BoulderScan:** all deployed indexer environments serve `/v1/climbs` and `/v1/climbs/:id`; fallback traffic to `/v1/vaults/:id` is zero or intentionally permanent for old links.
- **Backend:** route logs show no meaningful `/segments/*` traffic from current clients; then remove the mount and convert the alignment gate from "explicit compatibility allowed" to "new segment identity dependencies forbidden."
- **Operator scripts:** no active seed, smoke, or runbook command reads climb identity through vault-first routes except where the optional vault economy is the actual domain object.
