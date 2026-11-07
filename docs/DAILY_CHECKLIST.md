# Boulder Rollers - Daily Checklist
**Generated:** January 14, 2026
**Focus:** Today + Tomorrow

---

## Decisions Made (Jan 14)
| Decision | Choice |
|----------|--------|
| Invite enforcement | **Backend** (API rejects unapproved) |
| Staking in Alpha | **Full stake/unstake** on devnet |
| Map privacy | **Visible + opt-in fuzzy endpoints** |
| Ingest architecture | **Keep current** (base64 + Supabase Storage works) |

---

## Today's Priority Tasks

### Engineering (P0 Critical)
- [x] **Production stub mode check** — ✅ ALREADY IMPLEMENTED
  - File: `backend/app/solana_client.py`
  - Lines 71-75: Constructor rejects `SOLANA_STUB=true` if `ENVIRONMENT=production`
  - Lines 455-456: `_stub_response()` throws in production
  - **No work needed**

- [x] **Vault entitlement server-side check** — ✅ IMPLEMENTED
  - File: `backend/app/routes/vaults.py`
  - Added entitlement check to post-TGE path (line 693-699)
  - Added `vaults_used` increment after vault creation in BOTH paths
  - Fixed staking check to use `stake_cap_points` (more semantic)
  - Users can no longer create unlimited vaults

- [x] **Invite code backend enforcement** — ✅ IMPLEMENTED
  - Files: `backend/app/routes/auth.py`, `config.py`, `schemas.py`
  - Added `invite_code` field to `VerifyRequest` and `PrivyVerifyRequest`
  - Added `require_invite_code` config (default ON in production)
  - Enforced in both `/auth/verify` and `/auth/privy/verify`
  - Returning users skip check (only new signups need code)
  - Env var: `REQUIRE_INVITE_CODE=true|false`

### Quick Wins (Ship Today)
- [x] **Add "Stub Mode" warning banner** — ✅ IMPLEMENTED
  - Backend: Added `/status` endpoint in `backend/app/routes/health.py`
  - Schema: Added `StatusResponse` in `backend/app/schemas.py`
  - Frontend: Added `useSystemStatus` hook + `StubModeBanner` component
  - Integration: Banner shows at top of DashboardLayout when `SOLANA_STUB=true`
  - Dismissible with X button, shows environment/version info

- [x] **Show Local Legend badge on VaultView** — ✅ IMPLEMENTED
  - File: `web/portal/src/pages/VaultView.tsx`
  - Enhanced stats grid: Crown icon, gold border, glow effect, completions count
  - Enhanced info card: Gold gradient header, crown icon, gold styling
  - Uses existing `localLegend` data (no new API call needed)

---

## Tomorrow's Priority Tasks

### Product (P1 Pre-TGE)
- ~~**TGE preview modal**~~ — REMOVED (points system deleted April 2026)
  - ~~Backend endpoint `/points/preview`~~ (deleted)

- [ ] **Full stake/unstake UI** (~4hr) ⬅️ DECISION MADE
  - File: `Portfolio.tsx`
  - Enable stake AND unstake transactions on devnet
  - Add transaction confirmation flow
  - Show pending rewards per vault

- [ ] **BeetleCard component stub** (~3hr)
  - Create `web/portal/src/components/BeetleCard.tsx`
  - Display card type + level from `/beetles/my-cards`
  - Add to Profile page

### Map Privacy Implementation
- [ ] **Fuzzy endpoints toggle** (~2hr)
  - Add user setting: "Hide ride start/end"
  - Obscure first/last 200m of GPS track when enabled
  - Default: OFF (visible), user can opt-in

---

## Running Tests
```bash
# Backend tests
cd backend && pytest

# Anchor tests (run individually)
cd protocol/anchor
anchor test --skip-local-validator tests/boulder_rollers_vault.spec.ts

# Smoke test API endpoints
./scripts/smoke.sh
```

---

## Git Workflow
```bash
# Check status
git status

# Recent commits for context
git log --oneline -5

# Create feature branch
git checkout -b feature/stub-mode-check
```

---

## Key Files Reference

| Area | File |
|------|------|
| Solana client | `backend/app/solana_client.py` |
| Vault routes | `backend/app/routes/vaults.py` |
| Auth routes | `backend/app/routes/auth.py` |
| ~~Points service~~ | ~~`backend/app/services/points_service.py`~~ (deleted April 2026) |
| Epoch processor | `backend/app/services/epoch_processor.py` |
| VaultView UI | `web/portal/src/pages/VaultView.tsx` |
| Portfolio UI | `web/portal/src/pages/Portfolio.tsx` |
| Anchor vault | `protocol/anchor/.../lib.rs` |

---

## End of Day Checklist
- [ ] All P0 items addressed or in-progress PR
- [ ] Tests passing (`pytest`, `anchor test`)
- [ ] Commit with descriptive message
- [ ] Update beads if new issues found: `bd add "title" --priority critical`

---

**Sprint Context:** Sprint 1 - Alpha Hardening (1 week)
**Next Sprint:** Core Economy (Epoch, Legend, Harvest)
