# RFC: Rider Archetypes

**Status:** Draft
**Date:** 2026-04-13
**Author:** Tim (sketches + direction) + Claude (doc)
**Related:** `mobile_design_sketches_2026-04-13.md`, `docs/design/MOBILE_DATA_CONTRACTS.md`

---

## Context

The BeetleCard mobile screen (see sketches) includes a footer panel:

```
STRENGTH: punchy hills
WEAKNESS: TT
BEST AGAINST: Breakaway
```

Every rider has a class. Each class has a terrain strength, a terrain weakness, and counters exactly one other class (Pokémon-style matchup flavor). Pure identity / flavor — no on-chain effects.

A `rider_type` column already exists in the `users` table from migration `030_user_preferences.sql` with enum `climber / sprinter / tt / rouleur / allrounder / diesel`. Today it is user-picked and used only for "UI customization."

This RFC formalizes:
1. The canonical class list (naming, count, reconciliation with existing enum)
2. How a rider gets classified — **derived from power profile from day one**, with user override
3. The matchup matrix (strength / weakness / best-against per class)

## Non-goals

- **No combat mechanic.** Cosmetic only.
- **No numeric effects** — no CAL multipliers, no leaderboard weighting, no tribute adjustments.
- **No Anchor changes.** Off-chain identity layer.
- **No on-chain archetype storage.** Users table only.

---

## Proposal

### 1. Canonical class list (6)

| Enum value (DB) | Display name | Power profile signature | Terrain niche |
|---|---|---|---|
| `sprinter` | **Sprinter** | Peak 5s–30s (NM dominant) | Flat finales |
| `puncheur` | **Puncheur** | Peak 1–3min (AC dominant) | Punchy hills |
| `breakaway` | **Breakaway** | Peak 5–20min (VO2 dominant) | Rolling solo efforts |
| `rouleur` | **Rouleur** | High absolute FTP, low FTP/kg | Flats and time-trials |
| `climber` | **Climber** | High FTP/kg | Sustained climbs 10min+ |
| `gc` | **GC** | Elite across climbing AND FTP | Mixed parcours / grand tours |

**Why these 6:**
- Each maps to a distinct power-profile quadrant. No overlap, no slang classes.
- Dropped `diesel` — overlapped `rouleur` (both = sustained flat power). "Diesel" was slang, not a distinct profile.
- Dropped `allrounder` → renamed to `gc`. GC is genuinely different from Rouleur because it can climb *and* TT — versatility is the axis, not raw power.
- Dropped `tt` as a separate class — collapsed into `rouleur`. A TT specialist is the most extreme Rouleur; the power profile is identical.
- Added `puncheur` (was missing — AC-dominant riders didn't have a home).
- Added `breakaway` (VO2-dominant riders didn't have a clean home either).

**DB change:** update `chk_users_rider_type` constraint to the new 6-class list. Backfill:
- `tt → rouleur`
- `allrounder → gc`
- `diesel → rouleur`

No data loss; every old class maps to a new one.

**Display:** Use the plain display name everywhere. Do not append "Spec" — feels forced in small UI.

### 2. Classification — derived from day one

**No user-picked default mode.** Every user has a *derived* class computed from their power profile, with an optional manual override.

**Schema additions** (migration `036_rider_archetype_v2.sql`):
```sql
ALTER TABLE users
  ADD COLUMN rider_type_derived text,       -- latest computation, nullable until first ride
  ADD COLUMN rider_type_locked boolean NOT NULL DEFAULT false,
  ADD COLUMN rider_type_updated_at timestamptz;
-- rider_type remains the EFFECTIVE value: locked override if rider_type_locked, else rider_type_derived
```

**Inputs:** best power for standard durations — 5s, 1min, 5min, 20min — from the user's rolling best-efforts rollup. FTP/kg if user weight is known.

**Algorithm (Coggan-style ratio classifier):**
1. Normalize each best effort by the 20-min value. This gives 3 ratios: `r5s`, `r1min`, `r5min`.
2. Compute FTP/kg if weight known.
3. Apply rule table (tunable thresholds, initial values below):

   | Class | Condition |
   |---|---|
   | **Sprinter** | `r5s > 3.5` AND `r1min > 1.9` AND FTP/kg < 4.5 |
   | **Puncheur** | `r1min > 1.8` AND `r5min > 1.25` AND `r5s < 3.5` |
   | **Breakaway** | `r5min > 1.2` AND `r1min < 1.8` AND FTP/kg < 4.8 |
   | **Climber** | FTP/kg ≥ 4.8 AND `r5s < 2.8` |
   | **GC** | FTP/kg ≥ 4.5 AND `r5min ≥ 1.15` AND `r1min ≥ 1.7` (elite across both) |
   | **Rouleur** | Default — high absolute FTP but none of the above specializations |

   Evaluation order: Climber > GC > Sprinter > Puncheur > Breakaway > Rouleur (most specialized first). Thresholds will be calibrated against the golden corpus before shipping.

4. **Weight is required.** Onboarding forces weight entry (Zwift pattern) before the rider can ride. See "Weight enforcement" section below — this is a protocol-wide decision, not archetype-specific.

**When it runs:** on ride ingest in `backend/app/services/ride_processor.py`, immediately after the best-efforts rollup updates. Writes `rider_type_derived` and `rider_type_updated_at`.

**Flap protection:** the derived class only *changes* if the new class wins for **5 consecutive rides**, or if there's a meaningful step-change in best efforts (>5% on any axis). Prevents noisy reclassification from one off day or from classifier threshold imprecision near boundaries.

**User override:** profile settings lets the user lock a specific class (`rider_type_locked = true`, `rider_type = '<chosen>'`). When locked, derivation still runs in the background and the UI can surface "Your derived class: Climber" as a nudge. Unlocking resumes auto.

**First-ride behavior:** new users have `rider_type_derived = NULL` until their first ride produces best efforts. BeetleCard shows `Unknown` or `Rookie` placeholder for that brief window. First ride → first derivation → first real class.

### 3. Matchup matrix (cosmetic)

Each class beats exactly one other class. True 6-cycle:

**Sprinter → Breakaway → Climber → Puncheur → Rouleur → GC → Sprinter**

**Strength and Weakness are terrain niches. Best Against is a class.** (Matches Tim's sketch intent: "weakness: TT" = weak at time trials, a terrain, not the TT class.)

| Class | Strength (terrain) | Weakness (terrain) | Best against (class) |
|---|---|---|---|
| Sprinter | Flat finales (<30s) | Long climbs | Breakaway |
| Puncheur | Punchy hills (30s–3min) | Long TTs | Rouleur |
| Breakaway | Rolling solo efforts (5–20min) | Pack sprints | Climber |
| Rouleur | Flats and time-trials | Punchy hills | GC |
| Climber | Sustained climbs (10min+) | Flat finales | Puncheur |
| GC | Mixed parcours / grand tours | Pure sprints | Sprinter |

**Best-against cycle:** Sprinter → Breakaway → Climber → Puncheur → Rouleur → GC → Sprinter. Each class beats exactly one other on a mixed parcours.

**Narrative justification for each best-against edge:**
- *Sprinter catches Breakaway* on the flat run-in
- *Breakaway out-tactics Climber* on rolling terrain where pure climbing doesn't pay
- *Climber drops Puncheur* on long sustained climbs
- *Puncheur attacks Rouleur* on steep kicks the flat-power specialist can't follow
- *Rouleur out-powers GC* on long flats and TTs (raw watts beat versatility)
- *GC out-lasts Sprinter* across a multi-day selection

**Narrative justification for each weakness:**
- *Sprinter* has no sustained FTP → long climbs drop them
- *Puncheur* has AC but not raw FTP → bled dry on a TT
- *Breakaway* lacks top-end sprint → caught on the flat finale
- *Rouleur* is heavy → gradients above 8% murder them
- *Climber* is light with no NM → invisible in a flat sprint
- *GC* is balanced not explosive → outgunned in a pure sprint

Each pair has a real cycling-fan story.

**Matchup is purely cosmetic.** Zero effect on CAL allocation, vault rewards, leaderboard sorting, or any game mechanic. It is BeetleCard footer flavor text and nothing else. If this ever changes it's a separate RFC.

### 4. Where archetype surfaces

- **BeetleCard screen** — class name + matchup footer (strength / weakness / best against). Optional "AUTO" badge if derived, nothing if locked.
- **Leaderboard rows** — small class icon next to username (v1.1, not blocking).
- **Vault detail** — "best for: Climber" hint based on vault's dominant effort profile (future, separate RFC).
- **Not surfaced on-chain.** Ever.

---

## Implementation scope

### Ships in this RFC (pre-BeetleCard)

1. **Migration `036_rider_archetype_v2.sql`:**
   - Swap enum to the new 6 values.
   - Backfill old values (`tt→rouleur`, `allrounder→gc`, `diesel→rouleur`).
   - Add `rider_type_derived`, `rider_type_locked`, `rider_type_updated_at` columns.
2. **Backend classifier** (`backend/app/services/rider_classifier.py`):
   - `classify(best_efforts, ftp_w, weight_kg) → RiderType`
   - Thresholds as constants, calibrated against golden corpus.
   - Flap-protection logic wrapping raw classification.
3. **Ride ingest hook** — call classifier after best-efforts rollup in `ride_processor.py`.
4. **API** — `/api/me/profile` returns `rider_type` (effective), `rider_type_derived`, `rider_type_locked`.
5. **Mobile archetype table** (`mobile/src/lib/archetypes.ts`):
   - Static lookup: class → { display, strength, weakness, bestAgainst, icon }.
   - Read `rider_type` from profile, render BeetleCard footer from table.
6. **Profile settings** — lock/unlock toggle, manual class picker when locked.
7. **Onboarding weight gate** — blocks BeetleCard render and ride submission until weight is set. See "Weight enforcement" below.

### Out of scope for this RFC

- Leaderboard icons (v1.1)
- Vault "best for" hints (separate RFC)
- Onboarding flow redesign (separate PR, uses derived class as suggestion)
- Icon visual design (placeholder until design pass)

---

## Weight enforcement (protocol-wide, not archetype-scoped)

Weight is required for every user before they can ride. This is the **Zwift pattern** and it's a protocol-integrity decision, not an archetype decision:

- FTP/kg gates Climber and GC classification.
- Weight feeds TSS calculation (via kJ → kcal conversion and effort normalization).
- Weight gates CAL allocation indirectly through FTP/kg power zones.
- Without enforcement, power-to-weight is trivially gameable (claim 50kg, earn climber rewards on a flat ride).

**Enforcement:**
- Onboarding: weight field is mandatory on first profile save. No skip, no default.
- Update cadence: user can edit weight at any time, but edits are rate-limited (e.g. max one change per 30 days) to prevent gaming. Limit is tunable; start at 30 days.
- Validation: clamp to plausible range (30–200 kg / 66–440 lb). Reject outliers.
- Mobile: BeetleCard and ride submission are both hard-gated on `weight_kg IS NOT NULL`.

**This belongs in its own tiny RFC** once the economic-security surface is fully mapped. For this RFC it's a prerequisite that BeetleCard depends on, flagged here so it isn't forgotten.

---

## Open questions

1. **Icons** — one per class. Placeholder until design pass. Not blocking Figma if we use simple shapes.
2. **Classifier calibration** — initial thresholds are educated guesses. Need to run against the golden corpus (1,416 rides, see `golden_corpus_2026-03-20.md`) and tune before shipping. Expect 1–2 rounds of threshold adjustment.
3. **Weight-change rate limit** — 30 days is a guess. Could be longer (90 days) for stronger gaming resistance, or tied to a cooldown on earning while pending.
4. **Localization** — matchup flavor is English-only. Small table, easy to translate later.

---

## Migration plan

1. Write `036_rider_archetype_v2.sql` — enum swap, backfill, new columns.
2. Write `backend/app/services/rider_classifier.py` with constants from the table above.
3. Unit tests against hand-crafted power profiles (one per expected class).
4. Calibration pass against golden corpus — adjust thresholds until classification matches human intuition on ~80%+ of riders.
5. Wire into `ride_processor.py` ingest hook.
6. Update `schemas.py` `RiderType` enum + `/api/me/profile` response.
7. Run migration against devnet Supabase (when unpaused — see `supabase_pause_2026-04.md`).
8. Ship weight enforcement (onboarding required field + rate limit).
9. Mobile BeetleCard reads new values and renders footer.

**No backfill script needed** — no users exist yet. Classifier runs fresh on every ride from launch day forward.

**Note on Supabase pause:** Project is limited until 2026-04-09. Migration can be written and tested locally, deployed after unpause.

---

## Decision log

- **2026-04-13:** Drafted off Tim's whiteboard sketches.
- **2026-04-13:** Class list finalized at 6 — Sprinter/Puncheur/Breakaway/Rouleur/Climber/GC. Dropped Diesel (overlapped Rouleur), dropped TT (collapsed into Rouleur), renamed Allrounder → GC, added Puncheur and Breakaway.
- **2026-04-13:** Derivation is day-one, not deferred. User-picked is an override mode, not the default.
- **2026-04-13:** Matchup is 6-cycle, cosmetic only. "Spec" suffix dropped.
- **2026-04-13:** No class-change cooldown. Free to lock/unlock anytime.
- **2026-04-13:** Weight is required (Zwift pattern). Onboarding gates BeetleCard and ride submission on weight entry. Rate-limit weight edits (initial: 30 days) to prevent gaming. Flagged for its own protocol-integrity RFC.
- **2026-04-13:** Flap window set to 5 consecutive rides (from 3) to reduce noise from classifier threshold imprecision.
- **2026-04-13:** No backfill — no users yet.
