# Protocol Agent Return Brief — Welcome Back

**Status:** HISTORICAL — April 2026 return brief
**Date:** 2026-04-17
**Audience:** Protocol agent (iced until ~2026-04-22)
**Author:** Mobile/backend agent, acting dispatcher during freeze

Current agent authority is [AGENTS.md](../../AGENTS.md) and [AGENT_OPERATING_MODEL.md](../AGENT_OPERATING_MODEL.md), with protocol semantics in [PROTOCOL_TRUTHS.md](../PROTOCOL_TRUTHS.md).

---

## TL;DR

While you were iced, the mobile/backend agent stepped up as WWPTD dispatcher per Tim's direction. TRUTHS trio got drafted, ratified, and propagated. 11 beads cut for the WWPTD alignment portfolio. Phase 1 of mobile + Phase A of backend landed cleanly. Your lane is untouched where it matters — on-chain code, `wdvr.*` work, `0uv8` architecture — and explicitly pre-cleaned where it didn't (naming, stale docstrings, dead script archival).

You return to find:
- Your code honored at every boundary (indexer as cache, attestation derives once, RideAttestation first-class)
- Mobile post-TRUTHS alignment shipped end-to-end (`5hdl.1`, `5hdl.4`, `5hdl.5`)
- Backend nomenclature Phase A shipped with back-compat aliases so no client breaks (`mfab.5`)
- Demo script drafted with your epics mapped to concrete beats
- Four open Tim-decision gates already locked (D1–D4)

**Your critical-path epics** (`0uv8`, `wdvr.8`) are unchanged. Your in-flight work is the gating dependency for Phase B backend epics (`mfab.3`, `mfab.4`), which are queued and briefed but not started.

---

## What the dispatcher landed while you were iced

### TRUTHS trio ratified
- `docs/PROTOCOL_TRUTHS.md` — ACTIVE, unchanged (Tim-authored)
- `docs/MOBILE_TRUTHS.md` — CANDIDATE → ACTIVE 2026-04-17
- `docs/BACKEND_TRUTHS.md` — CANDIDATE → ACTIVE 2026-04-17
- `CLAUDE.md` §Source of Truth updated to cite trio; WWPTD filter named

### Portfolio + dispatch docs
- `docs/design/WWPTD_EPIC_PORTFOLIO_2026-04-17.md` — 13 epics mapped with bead IDs
- `docs/design/WWPTD_DISPATCHER_PLAYBOOK.md` — dispatch principles + current sprint state
- `docs/design/HACKATHON_DEMO_SCRIPT.md` — demo narrative candidate

### Commits on main (in order)
- `fc5a4222` Close 5hdl.1 M1 clock-domain hygiene
- `764e3c9a` Land M1 clock-domain hygiene (cross-domain subtraction labeled, not eliminated — see MOBILE_TRUTHS §3)
- `f01413f4` Merge 5hdl.4 M4 ride archive + detail
- `331f7e1d` Close 5hdl.4 bead
- `a8f32cb5` Land mfab.5 backend Phase A nomenclature slice (feeds into your `wdvr.8` / `0uv8` work)
- `96842fcd` Merge 5hdl.5 M5 Android + Seeker polish
- `01b55adb` Archive `scripts/migrate_v3_security.ts` honestly (was dead after V4-A)
- `1da8ccb0` Draft X2 demo script

---

## Decisions locked (Tim-ratified) — these are binding

### D1 — Pointer direction in V4-B

**`Climb { vault: Option<Pubkey> }`**

Tim chose the TRUTHS-pure layout: the primary object holds the pointer to its optional attachment. Physical layout mirrors ontology per PROTOCOL_TRUTHS §2.2 ("Climb is primary. Vault is attached."). Economic-ergonomic arguments for the reverse pointer were declined.

**Design consequence for `0uv8`:** architect against Climb-as-parent. Economic instructions resolve Vault from Climb; Climb-without-Vault is a well-formed account (the future Route/Zone/Arena types attach the same way). Expect a small indirection cost in hot paths; Tim's call was that ontological truth wins over runtime ergonomics.

### D2 — TRUTHS ratified (landed)

### D3 — M2 BLE scope is full (power + HR + cadence, ~3-4 wk)
Not yours to execute, but mobile-lane depends on this for the demo.

### D4 — Phase A backend commits unilaterally
This is why `mfab.5` landed while you were iced. Contract is published; mobile + frontend consume it now.

---

## What's pre-positioned as gift work

### Backend nomenclature Phase A (shipped)
`mfab.5` landed the mechanical rename slice:
- `backend/app/routes/segments.py` → `routes/climbs.py`
- Router mounted on BOTH `/climbs` (canonical) and `/segments` (compat alias)
- `tx_type="vault_create_points_period"` → `"admin_create_vault"`
- `merkle_proof.py` docstring rewritten to honestly describe it as DEAD CODE per V4-A
- Stale "points"-era comments swept across backend

**Deferred to future slices (when you're back):**
- Adding `Climb` + `Vault` as top-level schema classes in `backend/app/schemas.py`
- `RecordRoyalty` + `SettlementWeek` response fields
- Hard rename + compat alias retirement

Second mfab.5 agent (worktree-agent-a2e3bfb3) also produced a Climb + Vault schema class addition — not committed. The worktree is gone but the work is summarized in agent transcripts if you want to cherry-pick it for a future slice.

### Dead code archived honestly
- `protocol/anchor/scripts/migrate_v3_security.ts` — ARCHIVED header, DO NOT RUN, V3 obsolete after V4-A redeploy (commit `01b55adb`)
- `backend/app/services/merkle_proof.py` — docstring now honest (DEAD CODE per V4-A)

### Portal rename bead cut for you
`boulderroller-v2-kaol` captures the 20+ files in `web/portal/src/` still speaking pre-TRUTHS vocabulary. Backend back-compat aliases mean portal can migrate client-side without breaking — good candidate to include in `wdvr.8` cleanup scope or leave as its own slice.

---

## Open beads in your lane

| Bead | Status | Notes |
|------|--------|-------|
| `wdvr` | open | parent epic, unchanged |
| `wdvr.8` | open | your Phase 2 tail work — propagate cleanup + canonical naming; my `mfab.5` feeds into this |
| `0uv8` | in_progress | Climb-first surface split; D1 design consequence noted above |
| `kaol` | open (new) | portal nomenclature rename, 20+ files, unblocked |

Downstream-dependent (waiting on your work):
- `mfab.3` B4 leaderboard truth inversion — gated on `0uv8`
- `mfab.4` B5 per-bucket carry API — gated on `0uv8`

---

## What I didn't touch in your lane

- On-chain code in `protocol/anchor/` — untouched except the archived header on `migrate_v3_security.ts`
- `lib.rs` — untouched
- IDL — untouched
- Anchor tests — untouched
- Realloc / redeploy / fresh program ID decisions — yours
- `RideAttestation` PDA shape + child receipts — yours
- `RiderSoul` migration — yours

I held the P-D2 worktree-isolation rule everywhere on-chain. Dispatcher agents ran in worktrees and reviewed against TRUTHS before merge. One double-dispatch hazard on `mfab.5` was caught at review; no drift made it to main.

---

## What to do first when you return

1. Skim this doc.
2. Read `docs/MOBILE_TRUTHS.md` + `docs/BACKEND_TRUTHS.md` (they're short; they're also binding).
3. Red-pen either TRUTHS doc if you see drift from PROTOCOL_TRUTHS — Tim will take your edits.
4. Confirm or reshape the D1 pointer-direction call before executing `0uv8`.
5. Pick up `0uv8` and `wdvr.8`. Mobile/backend agent will stop acting as dispatcher for your lane the moment you're back; we'll hand off cleanly.

If any of the gift work doesn't fit your mental model — unwind it. The "gift" is the intent, not a mandate. TRUTHS alignment is the only thing that's load-bearing.

---

## One request

When you cut the fresh `0uv8` program ID, please name it in `addresses.devnet.json` with a comment line noting **"V4-B Climb-first, supersedes V4-A 37odBJvV…"**. Mobile needs that to wire the read layer cleanly when `wdvr.6` unblocks, and future-you-from-two-months-out will thank present-you.

Welcome back. The sprint continues.
