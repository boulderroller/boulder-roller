# Live beta-contract wiring — production-read evidence (2026-08-11)

**Beads:** `boulderroller-v2-odmi6.2` (client half of corrected elevation),
`boulderroller-v2-odmi6.5` (server sync seam swap), client halves of the
backend contracts `boulderroller-v2-odmi6.2.1` / `nrbu5` / `g0o24` / `coq7q`
(all deployed to production by the backend lane in `4fb8a7d2` on main).

**Evidence class:** production READ evidence — iPhone 17 simulator (iOS 26.3),
DEBUG build against `api.boulderroller.xyz`, test account "Rider HJTP" (DEBUG
SIWS dev wallet). Reads plus the account's own profile PUTs only; no upload,
no CAL, no Balance action, no permanent surface touched. Captures recorded
live in-window; nothing time-shifted. Simulator captures are still not
physical-device evidence.

## What was wired (suite 218/218 green, up from the 201 baseline)

1. **Climbing truth (A):** feed cards and the ride sheet's stat trio read
   `elevationCorrectedM` (the trustworthy DEM-corrected total) instead of the
   raw device total; null renders a dash, never zero and never the raw
   fallback. `Ride`/`GpsPoint` decode the new fields; `ElevationCorrection`
   provenance decodes alongside.
2. **Relief returns (B):** the ride-sheet ELEVATION section renders exactly
   when ≥2 DEM-corrected per-point values exist; the trace draws only
   corrected samples, gaps (never bridges) nil runs per the backend contract,
   keeps counted climb spans tinted blue from pattern offsets, and the
   section is omitted entirely when correction abstained (ratified
   Strava-faithful omission).
3. **Climb tap-through (C):** ride-sheet climb rows key on
   `vaultMatch.vaultClimbId ?? climbId` (`ClimbPattern.canonClimbId`) so
   authoritative canon traversals without completions navigate to the climb
   sheet; rows without canon identity stay inert (no dead controls).
4. **Physiology server sync (D):** `RiderPhysiologyStore` swapped its
   documented sync-later seam to the live contract. Hydrate at session start
   (server value fills only when local has no entry; server null never
   clears; unknown provenance fails closed); push on edit (PUT value, PUT
   explicit JSON null on Clear; best-effort, never blocks local truth).
5. **Title precedence (E):** no code change needed — tests bind that
   server-generated titles pass through untouched and the client fallback
   fires only on the legacy unnamed shape (wire `"Ride"`/null).

## Production captures

- `live-feed-corrected-climbing-production-read.png` — feed after sign-in:
  corrected Climbing on every backfilled ride (201 ft / 364 ft on the two
  simulated-GPS Shawmont rides that previously had **no** trustworthy
  elevation, 66 ft on the under-review ride, 3,172 ft on the 34 mi import).
- `live-ride-sheet-corrected-relief-production-read.png` — the Monday
  6:02 PM Evening Ride: Elevation stat 201 ft (was "— ft" in the pre-change
  capture `../12b-ride-sheet-recorded-ride-simulated-gps.png`), ELEVATION
  relief section returned from corrected per-point data with the Shawmont
  span tinted blue, truthful dashes on power/TSS.
- `live-climb-tapthrough-production-read.png` — the Shawmont Avenue climb
  sheet opened from that ride's climb row. The same row was a chevron-less
  dead end in the pre-change capture; production serves `climbId` on the
  pattern with **no completion** (vault still shows zero completions), so
  this is the pattern-only tap-through the backend contract promised.
- `live-physiology-unset-production-read.png` — avatar sheet before any
  entry: FTP and Weight both dash (server post-migration serves null/null —
  the fabricated 200/75 era is gone end to end).
- `live-physiology-set-production-read.png` — after in-app entry:
  FTP 245 W, Weight 81.4 kg (metric account), PUTs fired on Done.
- `live-physiology-hydrated-after-local-wipe-production-read.png` — app
  terminated, the local `br_rider_physiology_v1_<rider>` key deleted, fresh
  sign-in: both values return (245 W / 81.4 kg) — the round-trip proof that
  the PUTs persisted server-side and session-start hydration fills an empty
  local store.
- `live-physiology-cleared-after-local-wipe-production-read.png` — after
  in-app Clear on both fields (explicit JSON null PUTs), local wipe, fresh
  sign-in: both rows dash. Had the server not persisted the clears,
  hydration would have refilled 245/81.4 as in the previous cycle — the
  discriminating observation for the null half of the contract.

## Contract deltas found (wired to what production serves; documented, not guessed)

- **Validation ranges differ at the edges.** Client plausible ranges (bead
  odmi6.5, unchanged): FTP 30–500 W, weight 30–200 kg. Live PUT contract:
  FTP 50–500 W, weight 30–300 kg. Consequences, both truthful: a client FTP
  of 30–49 W stays local (the push 422s and is tolerated by design); a
  server weight above 200 kg is refused on hydration (local stays dash).
  Noted on bead odmi6.5.
- **GPS points may omit the key entirely** on never-corrected legacy rides
  (vs null when corrected data exists with gaps) — both decode to nil.

## Honest gaps

- **No abstained ride on this account** (all four rides sit inside the
  Delaware Valley grid), so the dash-on-abstention render is proven by the
  truthful-abstention decode test plus `Format.feet(nil)`, not by a live
  ride; producing one would need a new upload, which test accounts must not
  create. The pre-change 12b capture shows the identical dashed stat.
- Physical-device, VoiceOver-on-hardware, and cohort-scale checks remain on
  the existing lane-wide physical gates.
- Pre-existing observation (not this pass, left untouched): a stale
  encrypted custody blob from an older build surfaces the fail-closed "Ride
  evidence is unavailable" dialog once per fresh sign-in on this simulator;
  Retry clears it. Also, session resume after process kill lands on
  onboarding (refresh flow does not survive relaunch here) — DEV re-auth
  succeeds every time. Both belong to the custody/session lane (fy7x2.1).

## Out-of-scope consistency notes (flagged, not wired)

- Reveal beat-three "Climbing" and the rider-profile recent-ride subtitle
  still read raw `elevationM` (`RideUploadRuntime` reveal projection — a
  durable persisted shape owned by accepted item-7 code — and
  `PublicRiderRideSummary`, whose endpoint does not yet serve corrected
  fields). Follow-up noted on bead odmi6.2.
