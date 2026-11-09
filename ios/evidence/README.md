# iOS evidence — bead boulderroller-v2-fy7x2 (completion lane)

All screenshots from iPhone 17 simulator, iOS 26.3, DEBUG build against the
**production API** (test account "Rider HJTP", DEBUG SIWS dev wallet).
Files labeled `simulated-gps` used `simctl location` waypoint playback along
the real Shawmont Avenue canon centerline (production canon geometry) — the
GPS is simulated, everything else (upload, pipeline, canon match, reveal) is
the real production path, recorded live in-window. **No data was time-shifted.**

## Slice one (2026-08-10 morning, predecessor)
- 01–12: onboarding, feed states, avatar sheet (+Dynamic Type), settlements,
  climb sheet, map viewer, rider profile, processing beat, import, ride sheet.

## Completion lane (2026-08-10 evening)
- `13-recording-climb-band-simulated-gps.png` — recording surface mid-climb:
  OUTDOOR RIDE eyebrow, Workout numerals, climb band live (canon recognized
  Shawmont Avenue: live canon grade, progress, elapsed-on-climb). No delta
  row — the account holds no PR on this climb (truthful absence).
- `13b-recording-paused-simulated-gps.png` — paused state (End + Resume).
- `recording/13-recording-simulated-gps.mp4` — full first recorded ride
  (waiting-for-GPS → metrics → climb band window → pause → End → processing
  → reveal). Band visible ~t=230–350s.
- `recording/13b-climb-band-simulated-gps.mp4` — second ride, full climb
  with the final build (eyebrow + elapsed-on-climb line).
- `16-reveal-summary-fresh-ride-simulated-gps.png` — reveal on a
  legitimately fresh recorded ride, processed by production: canon check
  "Shawmont Avenue 2:52". Zero-CAL ride ⇒ gold beat skipped (ceremony
  proportional to consequence) — single summary beat.
- `12b-ride-sheet-recorded-ride-simulated-gps.png` — ride sheet of the
  recorded ride: real cartography, absent metrics shown as "—" (no power,
  no HR, no elevation from simulated GPS — no fake zeros), canon climb row.
- `05b-climb-sheet-vault-deposit-row.png` — Shawmont climb sheet: composite
  hero, Vault card, blue Deposit action row (live), ODbL attribution.
- `17-deposit-sheet-zero-balance.png` — Deposit sheet: giant numeral input,
  Balance 0 + Max, card-stack sentence, ratified footnote, held blue capsule
  (inert until a valid amount exists — account holds 0 CAL).
- `14-sensors-screen-simulator-no-ble.png` — Sensors room on simulator:
  CoreBluetooth is unsupported in the simulator, so the room shows its
  Bluetooth-off state. **Hardware gap (honest):** the My Devices / Available /
  Searching choreography and live HR/power/cadence parsing are implemented
  (full CoreBluetooth against HR 0x180D / power 0x1818 / CSC 0x1816) but
  need a physical device + real sensors to exercise.
- `15-import-error-duplicate.png` — import error state: backend rejected a
  re-upload of an already-uploaded file; message shown, Done exits.

## Known verification gaps (not silently skipped)
- **Deposit/Withdraw/Collect live runs:** the test account holds 0 CAL
  (GPS-only rides truthfully earn none; min stake is 100 CAL), and per the
  orchestrator's ruling no CAL is credited or donated to test accounts —
  test accounts must never earn onto permanent surfaces. The money room
  ships fully wired (sheets, dev-wallet + Privy signing, Balance
  prepare→sign→submit for stake/unstake/harvest); live-execution evidence
  is captured at Tim's review session, whose planned opening is his own
  stage-3 deposit.
- **Leaderboard/PR surfaces on fresh data:** the recorded rides produced
  canon matches but no authoritative vault completions (zero-effort rides),
  so the board stayed empty — truthful absence.
- **Permanent-record integrity check (2026-08-10):** after both simulated
  rides, production shows the Shawmont Avenue vault (the only vault) with
  leaderboard entries `[]`, `kom_holder: null`, `total_completions: 0` —
  the test account touched no permanent surfaces.
