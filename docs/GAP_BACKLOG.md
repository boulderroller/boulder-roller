# Boulder Rollers — Gap Backlog

**Generated:** 2026-01-08
**Source:** Vision vs Reality Audit
**Status:** Prioritized implementation gaps

---

## Priority Tiers

| Tier | Criteria | Timeline |
|------|----------|----------|
| **P0** | Blocking alpha release or user safety | Immediate |
| **P1** | Core loop incomplete, affects all users | Before TGE |
| **P2** | Important feature gaps, affects experience | Post-alpha |
| **P3** | Nice-to-have, polish, future features | V2+ |

---

## P0 — Critical (Alpha Blockers)

### 1. On-Chain Stub Mode in Production
**Gap:** Solana client defaults to stub mode, returns fake signatures
**Impact:** Users think transactions succeeded when they didn't
**Files:** `backend/app/solana_client.py`
**Fix:**
- [ ] Add environment check: error if `SOLANA_STUB=true` in production
- [ ] Implement proper fallback UX when RPC fails (retry queue, user notification)
- [ ] Add transaction verification polling

### ~~2. Vault Creation Entitlement Enforcement~~ — RESOLVED (removed)
**Gap:** ~~Entitlements checked client-side but may not be enforced server-side~~
**Status:** Resolved — pre-TGE entitlement gates removed April 2026. Vault creation now costs 100 DUNG or 1000 CAL + $2 USDC on-chain. No lifetime-points gating.
~~**Files:** `backend/app/routes/vaults.py`, `backend/app/services/points_service.py`~~
(`points_service.py` deleted April 2026)
**Remaining:**
- [ ] Rate limit vault creation

### 3. Invite Code Backend Enforcement
**Gap:** Docs mention "backend enforcement" as optional
**Impact:** Alpha could leak to unapproved users
**Files:** `backend/app/routes/auth.py`
**Fix:**
- [ ] Require valid invite code on all auth flows (not just frontend gate)
- [ ] Add `invited_at` timestamp to user record
- [ ] Block API access without valid invite

---

## P1 — High Priority (Pre-TGE Required)

### 4. Epoch Distribution End-to-End
**Gap:** Background processor exists, on-chain distribution untested in production
**Impact:** Stakers/leaderboard won't receive rewards
**Files:** `backend/app/services/epoch_processor.py`, Anchor `distribute_epoch_rewards`
**Fix:**
- [ ] Run full epoch cycle on devnet with real vaults
- [ ] Add monitoring/alerting for epoch transitions
- [ ] Create admin endpoint to manually trigger distribution
- [ ] Add distribution receipt verification

### 5. Local Legend Election Completion
**Gap:** DB + Anchor done, frontend minimal, no election notifications
**Impact:** Feature invisible to users
**Files:** `backend/app/services/swanny_service.py`, `web/portal/src/pages/VaultView.tsx`
**Fix:**
- [ ] Add Local Legend badge to VaultView
- [ ] Show election countdown/status
- [ ] Notification when elected
- [ ] Admin dashboard for election monitoring

### 6. Harvest Flow (Claim Staking Rewards)
**Gap:** Anchor instruction exists, no frontend UI
**Impact:** Users can stake but can't claim rewards
**Files:** `protocol/anchor/.../lib.rs` (harvest_vault_rewards), frontend
**Fix:**
- [ ] Add "Claim Rewards" button to Portfolio
- [ ] Show pending rewards per vault
- [ ] Transaction confirmation flow
- [ ] 5% fee disclosure

### 7. BeetleCard Frontend
**Gap:** Anchor instructions + backend routes exist, no UI
**Impact:** Core identity feature invisible
**Files:** `backend/app/routes/beetles.py`, need new frontend components
**Fix:**
- [ ] Create BeetleCard component with visual rendering
- [ ] Add to Profile page
- [ ] Show upgrade path with DUNG costs
- [ ] Level gate requirements display

### ~~8. Points -> DUNG TGE Conversion UI~~ — RESOLVED (removed)
**Status:** Resolved — points system removed April 2026. No TGE conversion UI needed.
~~**Gap:** Backend calculates conversion, no user-facing preview/execution~~
~~**Files:** `backend/app/routes/points.py` (has `/preview`), frontend~~
(`points.py` routes and `points_service.py` deleted April 2026)

---

## P2 — Medium Priority (Post-Alpha)

### 9. USDC Payment Integration
**Gap:** Shadow USDC tracking exists, no actual payment
**Impact:** Vault creation requires workaround (CAL only)
**Files:** `backend/app/services/`, need Stripe/USDC integration
**Fix:**
- [ ] Integrate Solana Pay or Stripe for $2 USDC option
- [ ] Reconcile shadow_usdc with actual payments
- [ ] Add payment confirmation flow

### 10. Gas Sponsorship
**Gap:** Docs say "core loop actions sponsored" — not implemented
**Impact:** Users pay gas for every action
**Files:** Need new service
**Fix:**
- [ ] Implement fee payer for: ride completion recording, CAL credit, leaderboard updates
- [ ] Track sponsored gas usage
- [ ] Set budget limits

### 11. Social Features Completion
**Gap:** API endpoints exist, frontend minimal
**Impact:** No community engagement
**Files:** `backend/app/routes/social.py`, `feed.py`, `interactions.py`
**Fix:**
- [ ] Comments on rides
- [ ] Kudos button
- [ ] Follow/following
- [ ] Activity feed on dashboard

### 12. iOS App Update
**Gap:** iOS mentioned in docs, code outdated/missing
**Impact:** Mobile users blocked
**Fix:**
- [ ] Audit existing iOS code (if any)
- [ ] Decision: native vs PWA
- [ ] If native: align with web portal features

### 13. Strava Auto-Sync
**Gap:** Manual import only, no webhook/polling
**Impact:** Users must manually trigger imports
**Files:** `backend/app/services/strava_service.py`
**Fix:**
- [ ] Implement Strava webhook subscription
- [ ] Or: polling job for connected accounts
- [ ] Deduplication already exists

### 14. Advanced Analytics
**Gap:** Basic trends exist, TrainingPeaks-quality promised
**Impact:** Data-driven cyclists underwhelmed
**Files:** `backend/app/routes/analytics.py`
**Fix:**
- [ ] Power zones chart
- [ ] Fatigue/fitness (CTL/ATL/TSB)
- [ ] Season planning
- [ ] Export to CSV/JSON

---

## P3 — Lower Priority (V2+)

### 15. Bio-Passport / Anti-Cheat
**Gap:** Not implemented
**Impact:** Cheating possible
**Fix:**
- [ ] Critical Power model tracking
- [ ] Anomaly detection
- [ ] Shadow ban infrastructure

### 16. Community Tribunal
**Gap:** Not implemented
**Impact:** No decentralized moderation
**Fix:**
- [ ] Local Legend voting on flagged rides
- [ ] Dispute resolution flow
- [ ] Appeals process

### 17. Attribute Marketplace
**Gap:** Not implemented
**Impact:** No cosmetic trading
**Fix:**
- [ ] Tradeable BeetleCard attributes
- [ ] Listing/bidding flow
- [ ] 5% protocol fee

### 18. POL Vault Automation
**Gap:** Not implemented
**Impact:** Manual liquidity management
**Fix:**
- [ ] TWAP swap automation
- [ ] PumpSwap LP management
- [ ] Rebalancing triggers

### 19. Full Governance
**Gap:** Not implemented
**Impact:** Founder controls parameters
**Fix:**
- [ ] Squads multisig setup
- [ ] 2-day timelock on changes
- [ ] Proposal/voting UI

### 20. Native GPS Recording
**Gap:** File upload only
**Impact:** Users need separate app to record
**Fix:**
- [ ] Mobile GPS recording
- [ ] Background tracking
- [ ] Live upload

### 21. Virtual Climbs (Zwift)
**Gap:** Not implemented
**Impact:** Indoor riders excluded from climb vaults
**Fix:**
- [ ] Zwift API integration
- [ ] Virtual vault matching
- [ ] Effort verification

---

## Quick Wins (Low Effort, High Impact)

| Item | Effort | Impact | Files |
|------|--------|--------|-------|
| Add "Stub Mode" warning banner | 1hr | Prevents confusion | `web/portal` |
| Show Local Legend on VaultView | 2hr | Feature visibility | `VaultView.tsx` |
| ~~TGE preview modal~~ | ~~4hr~~ | ~~User excitement~~ | Removed (no points system) |
| Production stub mode check | 1hr | Prevents bugs | `solana_client.py` |
| Harvest button (disabled state) | 2hr | Shows feature exists | `Portfolio.tsx` |

---

## Dependency Graph

```
P0 Blockers
    └── P1 Core Features
            ├── Epoch Distribution → Harvest Flow
            └── BeetleCard Frontend → Marketplace (P3)

P2 Enhancements
    ├── USDC Integration (standalone)
    ├── Gas Sponsorship (standalone)
    └── Social Features → Feed polish

P3 Future
    ├── Anti-Cheat → Tribunal
    └── Governance (standalone)
```

---

## Recommended Sprint Plan

### Sprint 1: Alpha Hardening (1 week)
- P0 items 1-3
- Quick wins

### Sprint 2: Core Economy (2 weeks)
- P1 items 4-6 (Epoch, Legend, Harvest)
- Integration testing on devnet

### Sprint 3: Identity & TGE Prep (2 weeks)
- P1 items 7-8 (BeetleCard, TGE UI)
- Marketing prep

### Sprint 4: Polish (1 week)
- P2 items based on alpha feedback
- Bug fixes

---

## Tracking

Use `bd` (beads) for issue tracking per project convention:
```bash
bd add "P0: Production stub mode check" --priority critical
bd add "P1: Epoch distribution e2e test" --priority high
```

---

**Owner:** Engineering
**Review:** Weekly during standup
**Update:** After each sprint
