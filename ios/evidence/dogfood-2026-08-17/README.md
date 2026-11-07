# Dogfood session — 2026-08-17 (simulator, production API, dev account)

Full first-rider walk on a signed simulator build against production,
while Tim rode. Rules: browse and record freely; no uploads, no
board-touching writes (stationary recording stays upload-ineligible by
the 30-sample/100 m rule).

## Fixed and landed (same day)

1. **Sign-out-on-every-refresh (production)** — /auth/refresh returns
   tokens+wallet without user_id; the client's sign-in decoder required
   userId, so every successful rotation classified as transient, the
   retry presented the rotated token, the server 409'd, and the session
   honestly ended. Server logs showed 200-then-409 pairs. Fixed with a
   distinct RefreshTokenResponse contract + SessionTokens adoption;
   AuthContractTests pin both wire shapes. Live-verified: two cold
   relaunches survive; server shows clean 200 rotations.
2. **Unsigned-sim evidence gap** — CODE_SIGNING_ALLOWED=NO stripped
   entitlements, so every keychain call failed (-34018): sessions never
   persisted in any live-sim run (masking #1) and the feed wore a false
   "Ride evidence is unavailable" banner. project.yml now ad-hoc signs
   simulator builds (app + tests).
3. **Feed title fallback** — social feed cards rendered the backend
   literal "Ride"; the ratified place/time-of-day rule now applies.

## Verified working, live

- Onboarding → dev sign-in (invite enforcement works; error surfaced
  truthfully) → global feed with real rides.
- Avatar sheet: one tracked-uppercase voice, centered Sign out, truthful
  dashes; **Units editor round-trip against production** (Kilometers →
  Miles, server truth adopted).
- Climb sheet (Shawmont Avenue, real canon): composite hero with real
  cartography + 21%-max gradient personality; Local Legend; vault card
  with education footer; ODbL line; Deposit sheet showing "Minimum
  deposit is 100 CAL." exactly when balance gates it.
- Map viewer: glass chrome, canon facts, attribution.
- Point-of-need permission choreography: OS location prompt fires at
  Record tap with the truthful purpose string; no pre-prompt wall.
- Recording: Workout-bones surface, pause/End circles, quiet dash for
  absent climbing; End on a stationary ride → **"Saved on this device"
  feed card** (`saved-on-device-feed.png`) — ineligible evidence stays
  local, no upload, no fake ceremony.
- Interrupted-ride recovery: found a 0:00 orphan after a start failure,
  offered save/discard, confirm-then-delete worked.
- Privacy room (server truth, joer2 default), Sensors room (Bluetooth-off
  row now hands off to Settings).

## Open (filed or watch)

- **One-time recording start failure**: custody create succeeded, start
  failed after, non-reproducing; console diagnostics now permanent in
  that path (start + custody refresh name their real cause).
- **Units preference is cosmetic**: display formatting is imperial-first
  everywhere regardless of the account setting — the editor persists
  truth the surfaces ignore. Filed.
- "Save Ride" is the blue primary for a 0:00/0-distance recovery — the
  eligible-looking affordance for evidence that cannot upload.
- Recovery sheet buttons are a one-off species (filled rounded-rect +
  red text); worth folding into the app's button grammar someday.
- Onboarding composition (Wall line placement) — for the holistic
  soft-touch pass.
- "Rider" placeholder names/blank avatars on old test rides in the
  global feed (server data, not client).

## Clock-bug resolution (same night)

The dead-process replay was ALREADY evidence-bounded in product code —
proven by the new killed-while-recording test (60 s of fixes, process
death with no boundary, six-hour gap, fresh clock domain → recovery and
saved summary both read 60 s). The five-hour phantom was manufactured
entirely by the test-pollution vector: fake-clock suites writing real
custody files through shared-singleton defaults. That vector is now
walled: ProcessSandbox redirects every DEFAULT store root (custody,
uploads, feed cache) to an isolated temp directory and every keychain
account to a test-prefixed name whenever the process hosts XCTest, and a
regression test pins the wall. Verified live: full suite run, then app
relaunch — feed unchanged, no phantom minted.
