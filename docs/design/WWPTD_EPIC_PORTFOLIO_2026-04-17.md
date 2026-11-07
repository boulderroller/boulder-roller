# WWPTD Epic Portfolio — Post-TRUTHS Alignment Work

**Status:** READY FOR EXECUTION — D1-D4 locked 2026-04-17 by Tim
**Date:** 2026-04-17
**Audience:** Founding, mobile, backend, protocol
**Parent docs:**
- [PROTOCOL_TRUTHS](../PROTOCOL_TRUTHS.md) (ACTIVE)
- [MOBILE_TRUTHS](../MOBILE_TRUTHS.md) (ACTIVE, ratified 2026-04-17)
- [BACKEND_TRUTHS](../BACKEND_TRUTHS.md) (ACTIVE, ratified 2026-04-17)
- [PROTOCOL_ALIGNMENT_FIX_PLAN](./PROTOCOL_ALIGNMENT_FIX_PLAN.md) (execution plan)

---

## Why this doc exists

We now have three canonical TRUTHS docs parented under PROTOCOL_TRUTHS.
A three-facet audit (protocol / mobile / backend) run on 2026-04-17 surfaced
the gaps between today's code and those truths. This doc organizes the
findings into discrete epics with scope, size, owner, dependencies, and
hackathon-visibility — so the work can be cut into bead issues and
dispatched.

**North star for this portfolio:** bring the stack into coherence with its
own TRUTHS before the Colosseum Frontier submission on May 11, 2026.

---

## Epic portfolio

### Mobile lane — parent epic `boulderroller-v2-5hdl`

| Bead | Epic | Scope (what's in) | Size | Owner | Demo-visible? |
|------|------|-------------------|------|-------|---------------|
| `5hdl.1` | **M1** Clock-domain hygiene | Label GPS-time vs wall-time at every arithmetic site in `gpsRecording.ts` and `gpxExporter.ts`; eliminate the cross-domain subtraction audit bug A/B/C; add type-level discipline so future additions can't re-drift | ~1 hr | mobile | No (correctness) |
| `5hdl.2` | **M2** BLE sensor pairing | react-native-ble-plx + GATT parsers for Cycling Power / Heart Rate / Cadence; pairing UI wiring off existing pairing store; snapshot-on-GPS-tick already plumbed | 3-4 wks (full scope per D3) | mobile | **Yes** — fixes phantom CAL, unlocks real TSS |
| `5hdl.3` | **M3** FIT export | Switch exporter to FIT when sensors present; keep GPX fallback for GPS-only rides; backend `workout-parse` already reads FIT natively. Depends on `5hdl.2`. | 3-4 days | mobile | Yes (ride fidelity visible) |
| `5hdl.4` | **M4** Local ride archive + detail | HomeScreen merges local SQLite rides with server-fetched rides; tap into ride detail from either source | ~1 wk | mobile | Yes (app feels whole) |
| `5hdl.5` | **M5** Android demo + Seeker polish | MWA wallet connect, Seed Vault detection, sign-memo demo, grant-application narrative polish | ~1 wk | mobile | **Yes** — Solana Mobile Builder Grant |

**Done-when signals (M-lane):**
- M1: all time arithmetic sites pass explicit-domain linter or type check; research audit bugs A/B/C close.
- M2: 3 GATT profiles read live sensor data into SQLite extended schema; pairing persists across sessions; disconnection drops to null, not zero.
- M3: ride with power meter ships FIT to backend; backend `workout-parse` consumes it natively.
- M4: rider opens HomeScreen offline, sees their rides; tap into detail works offline.
- M5: Android build connects MWA wallet on Seeker; sign-memo flow demonstrable on Android.

---

### Backend lane

Backend epics split by whether they need the protocol agent (V4-B ontology
lift) to land first. **Phase A is unilateral** — frontend + mobile can
consume the new contract while the protocol agent is frozen. **Phase B is
gated** on V4-B primitives.

### Backend lane — parent epic `boulderroller-v2-mfab`

**B1 absorbed:** nomenclature coherence (`routes/segments.py` → climbs, `RecordRoyalty` + `SettlementWeek` in API, retire stale strings, honest `merkle_proof.py` archival) is owned by `wdvr.8` (Propagate cleanup and canonical naming) + `0uv8` (Complete Climb-first surface split). Not duplicated here.

#### Phase A — unilateral (ship while protocol agent frozen)

| Bead | Epic | Scope | Size | Owner | Demo-visible? |
|------|------|-------|------|-------|---------------|
| `mfab.1` | **B2** Role decomposition | Split `ride_processor.RideProcessor` (2,157 LOC) into `RideAttester` + `RideExecutor` + `ProjectionWriter`; make §5 role separation visible in code organization | ~1 wk | backend | No (structure) |
| `mfab.2` | **B3** `finalized_at` first-class | Add `finalized_at` column to `rides` and distribution tables; compute from on-chain settlement events; surface in `/rides/{id}` and `/distributions/*` responses | ~3 days | backend | Yes — riders see "earnings locked" |

#### Phase B — gated on V4-B Climb-first surface (`0uv8`)

| Bead | Epic | Scope | Size | Owner | Demo-visible? |
|------|------|-------|------|-------|---------------|
| `mfab.3` | **B4** Leaderboard truth inversion | Invert `leaderboard_sync_service`: chain `VaultLeaderboard` PDA is authoritative; DB rebuilds from on-chain events; repair path reindexes from chain, never from DB writes | ~1 wk | backend | No (structural — biggest single §10 drift) |
| `mfab.4` | **B5** Per-bucket carry through API | Thread `carry_record_royalty / carry_stakers / carry_local_legend / carry_pol / carry_treasury` through `/distributions/vault/{id}` and related responses | ~3 days | backend | Yes — BoulderScan gains bucket identity |

**Done-when signals (B-lane):**
- B1: grep for "segment" in `routes/` returns 0 results outside archived files; grep for "points" returns 0 outside history.
- B2: `ride_processor.py` deleted or reduced to coordinator; three new services each <500 LOC and single-responsibility.
- B3: rider can query `/rides/{id}` and know whether their ride's epoch is finalized; `finalized_at` non-null after chain finalization.
- B4: DB leaderboard write requires a recently-observed chain event; no service writes `vault_leaderboards` except the indexer.
- B5: `/distributions/vault/{id}` response contains five discrete carry fields; UX can render bucket identity.

---

### Protocol lane

Owned by protocol agent; listed here for portfolio coherence. All already
in flight per PROTOCOL_ALIGNMENT_FIX_PLAN.

| Bead | Epic | Scope | Status | Demo-visible? |
|------|------|-------|--------|---------------|
| `wdvr.7` | **P1 foundation** | First-class `RideAttestation` PDA with child receipts; `RiderSoul`; indexer tables/writers; public attestation APIs | CLOSED (foundation landed) | Partial |
| `0uv8` | **P1 Climb-first surface split** | Make Climb the primary public object; propagate canonical naming across backend/API/BoulderScan/mobile; retire compatibility aliases after consumers migrate | IN_PROGRESS | **Yes** — the "after" of TRUTHS |
| `wdvr.8` | **P2 Cleanup + naming propagation** | Dead-code cleanup, doc updates, BoulderScan/API copy, retire stale migration and compatibility surfaces. Depends on `wdvr.7`. | OPEN | No (cleanup) |

**D1 consequence:** `0uv8` architecture designs against `Climb { vault: Option<Pubkey> }`. Physical layout mirrors ontology.

---

### Cross-cutting

| Bead | Thread | Scope | Owner | Status |
|------|--------|-------|-------|--------|
| — | **X1** TRUTHS ratification | Flip MOBILE_TRUTHS + BACKEND_TRUTHS to ACTIVE; CLAUDE.md cites trio as tiebreaker | Tim + mobile | ✅ DONE 2026-04-17 |
| `flqu` | **X2** Hackathon demo script | Map each epic to the demo beat it enables; freeze narrative by Apr 28; rehearse May 6-10 | Tim + mobile | OPEN |
| — | **X3** Designer push integration | When designer push lands, align UI against MOBILE_TRUTHS §12 vocabulary; reconcile any copy drift | mobile + designer | DEFERRED (awaiting designer push) |

---

## Dependency graph

```
Pre-epic decisions (Tim)
    │
    ├─► X1 TRUTHS ratification ─── unblocks "these are binding" in PRs
    │       │
    │       └─► (all other epics cite TRUTHS as tiebreaker)
    │
    ├─► Pointer-direction decision ─── gates P1 architecture
    │       │
    │       └─► P1 ─── gates B4, B5
    │               │       │
    │               │       └─► Phase B epics begin
    │               │
    │               └─► P2 rides with P1 realloc
    │
    └─► Phase A commitment ─── unblocks B1, B2, B3 (unilateral ship)

Mobile lane is largely independent:
    M1 — standalone, land anytime
    M2 — M5 ─── can parallelize, M5 is grant-deadline-tied
    M3 ─── gated on M2 having working sensor reads

Hackathon-demo convergence (X2) ─── all epics feed into this
```

---

## Proposed sequence to May 11

### Week 1 — Apr 17–21 (protocol iced)

Mobile + backend unilateral lane. Protocol agent returns ~Apr 22.

- **M1 clock-domain** (today, ~1 hr)
- **B1 nomenclature coherence** (drive unilaterally if Phase A is committed)
- **B2 role decomposition** (cleanup pays for itself when protocol agent returns)
- **M4 local ride archive** (app feels whole for demo)

### Week 2 — Apr 22–28 (protocol agent returns)

- **P1 V4-B ontology lift begins** (wdvr.7, pointer-direction decision locked in)
- **M2 BLE pairing starts** (longest-runway mobile epic)
- **B3 finalized_at** (can land alongside V4-B without blocking it)
- **X2 demo script narrative frozen**

### Week 3 — Apr 29–May 5 (convergence)

- **M2 continues**, **M3 FIT export** fast-follows
- **B4 + B5 Phase B epics** begin once V4-B primitives live
- **P2 dormant field cleanup** rides with P1 realloc

### Week 4 — May 6–11 (demo hardening)

- **M5 Android + Seeker polish** for grant narrative
- Demo script rehearsed end-to-end
- Regressions only — no new features
- **Submit May 11**

---

## Decisions

All four decisions locked by Tim on 2026-04-17.

### D1 — Pointer direction in the V4-B account shape → **LOCKED: Option A**

`Climb { vault: Option<Pubkey> }`. The primary object holds the pointer to
its optional attachment. TRUTHS-pure. Physical layout mirrors ontology:
PROTOCOL_TRUTHS §2.2 says *"The Climb is primary. The Vault is attached."*
— and the account shape reflects that. Economic-ergonomic arguments for
the reverse pointer were pragmatic optimization against an ontological
truth; WWPTD declines.

**Consequence for protocol agent:** P1 (wdvr.7) designs against
Climb-as-parent. Economic instructions resolve Vault from Climb; Climb
without Vault is a well-formed account. Pattern generalizes to future asset
graph types (Route, Zone, Arena) per PROTOCOL_TRUTHS §2.1 roadmap.

### D2 — Ratify MOBILE_TRUTHS + BACKEND_TRUTHS → **LOCKED: Ratify**

Both flipped to ACTIVE 2026-04-17. Downstream PRs may cite them as binding
in review. CLAUDE.md updated to reference the TRUTHS trio as tiebreakers.
Agents treat them as canonical for their lane, with PROTOCOL_TRUTHS always
winning on conflict.

### D3 — M2 BLE scope → **LOCKED: Full (power + HR + cadence)**

All three GATT profiles target for M2. 3-4 weeks of runway. Stronger
Solana Mobile Builder Grant narrative, stronger hackathon demo, and the
§4 evidence-layer story is complete on day one rather than staged. Time
budget tight against May 11 but warranted.

### D4 — Phase A backend API shape → **LOCKED: Commit unilaterally**

B1 (naming), B2 (role decomposition), B3 (`finalized_at`) ship against a
contract mobile + frontend can consume immediately. The "gift posture"
applies: when the protocol agent thaws, they should find post-TRUTHS
vocabulary already propagated, roles already decomposed, truth directions
already holding — work of the type they would love to see.

**Reviewer posture (while protocol agent frozen):** the mobile/backend
agent steps up as WWPTD reviewer. Every PR gets checked against
arrow-of-truth and semantic correctness before landing. Drift caught
pre-merge.

---

## Bead map (cut 2026-04-17)

All beads open and ready for agent pickup.

```
boulderroller-v2-5hdl (epic) Mobile WWPTD alignment portfolio
    ├── 5hdl.1  M1 Clock-domain hygiene           [1 hr]  correctness
    ├── 5hdl.2  M2 BLE sensor pairing (full)      [3-4 wk] demo
    ├── 5hdl.3  M3 FIT export (deps: 5hdl.2)      [3-4 d] demo
    ├── 5hdl.4  M4 Local ride archive + detail    [1 wk]  demo
    └── 5hdl.5  M5 Android + Seeker polish        [1 wk]  grant

boulderroller-v2-mfab (epic) Backend WWPTD alignment portfolio
    ├── mfab.1  B2 Role decomposition             [1 wk]  Phase A
    ├── mfab.2  B3 finalized_at first-class       [3 d]   Phase A
    ├── mfab.3  B4 Leaderboard truth inversion    [1 wk]  Phase B (deps: 0uv8)
    └── mfab.4  B5 Per-bucket carry API           [3 d]   Phase B (deps: 0uv8)

boulderroller-v2-flqu  X2 Hackathon demo script      [2 d]   cross-cutting

Existing protocol-lane beads (pre-2026-04-17):
    wdvr.7  (closed) P1 foundation landed
    0uv8    (in_progress) Climb-first surface split
    wdvr.8  (open) Cleanup + canonical naming
```

Agents pick up any open bead by ID. Dependencies encoded on-bead via
`bd depends`. Phase B backend beads (`mfab.3`, `mfab.4`) depend on `0uv8`.
`5hdl.3` depends on `5hdl.2`. Everything else is unblocked.

---

## Appendix: source of findings

Each epic row traces to one of three PM-level audits run 2026-04-17:

- **Protocol audit** (general-purpose agent, 500 words) — principles P1-P15 checked against `protocol/anchor/programs/boulder_rollers/src/lib.rs` and V4-A deployment state. Surfaced: Climb/Vault fusion, IDL naming drift, Synthetix residue, UserState+RiderSoul coexistence.
- **Mobile audit** — MOBILE_TRUTHS §§3, 4, 6, 7, 10, 11, 12 against mobile/src/services, lib/, stores/, screens/. Surfaced: clock-domain partial fix, identity collapse, zero-sample ride hash handling.
- **Backend audit** — BACKEND_TRUTHS §§1, 2, 3, 5, 6, 7, 8, 9, 10, 12 against backend/app/. Surfaced: role tangling, naming drift, leaderboard truth inversion, carry flattening, privacy endpoint gap, merkle_proof misrepresentation.

Audit agent transcripts are in conversation history; this doc is the
PM-level organization of their findings.
