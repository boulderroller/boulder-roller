# Batch C — stranger safety: privacy zones, exposure, permissions, profile

**Beads:** `boulderroller-v2-f4acp.1.4` (zones + exposure),
`boulderroller-v2-f4acp.1.8` (permission choreography),
`boulderroller-v2-f4acp.1.9` (profile editing). Exposure contract:
`boulderroller-v2-joer2` (ratified 2026-08-02, closed).

**Owner/status:** claude / all four batch items implemented; per-item
remaining scope listed at the bottom.

**Evidence class:** live production API against the existing dev test
account (Rider HJTP) on the iPhone 17 simulator (iOS 26.3), plus the unit
suite. Every production write was the account's own reversible setting and
was reverted after capture: privacy zone created → deleted; account default
flipped Followers → back to Everyone; one ride flipped Only you → back to
Everyone; neighborhood set → cleared; avatar uploaded → removed. Nothing
earned, no permanent surfaces, no new accounts.

**Suite:** 255 tests, 0 failures (baseline 222 + 33 new:
`PrivacyContractTests`, `PermissionChoreographyTests`,
`ProfileEditContractTests`).

## Item 1 — Privacy zones (`batch-c/c1-*.png`)

The avatar sheet's Riding group gains a Privacy row
(`c1-avatar-sheet-privacy-row.png`). The Privacy room renders server truth
only — settings and zones load together and fail closed together; an
unavailable contract is an unavailable room with Retry, never zones shown
as silently empty (unit-tested).

Zone editor is address-free: the circle is pinned to the map center and the
rider drags the map under it; radius presets mirror the backend's exact
allowed set {200, 400, 800, 1600 m} and the optional label mirrors the
50-char cap; the Add gate mirrors the server-declared `max_zones`, never a
compiled copy. Live lifecycle verified end-to-end against production zone
CRUD: create with 400 m + label (`c1-zone-editor-400m-label.png` →
`c1-privacy-screen-zone-created.png`), reopen loads the saved zone, confirmed
destructive delete returns the room to empty
(`c1-privacy-screen-zone-deleted-cleanup.png` — this is also the cleanup
proof). Footer is the one-line grouped-list education string:
"Rides you share hide inside your zones." The owner's own surfaces stay
complete — projection is entirely server-side (`ride_privacy.py` edge law).

Dynamic Type: `c1-avatar-sheet-a11y-large.png`,
`c1-privacy-screen-a11y-large.png` (accessibility Large — labels wrap, the
single trailing element truncates, nothing clips or overlaps). Rows are
combined accessibility elements with labels throughout.

## Item 2 — Exposure defaults, mechanism only (`batch-c/c2-*.png`)

The joer2 ratification already exists (Tim, 2026-08-02): Strava's pattern;
audience and map visibility separate; **future rides default to Everyone
with first/last 200 m hidden**; defaults affect future rides only;
Followers/Only-you rides stay off public Leaderboards; privacy failure
blocks publication. The DB defaults already implement it
(`sql/097`, `sql/147`).

Client mechanism shipped, mirroring the backend contract exactly:

- Vocabulary `public|followers|private` → Everyone / Followers / Only you
  (Strava-shaped system strings per the ratified pattern; unit-pinned).
- Account default: Privacy room "Who can see" row → three-checkmark picker,
  live `PUT /privacy/settings` round-trip verified
  (`c2-audience-picker-default.png`, `c2-default-changed-followers.png`,
  then reverted). Footer mirrors the server's `defaultsApplyTo`:
  "Applies to new rides."
- Per-ride override: owner-only "Who can see" row on the ride sheet
  (`c2-ride-sheet-audience-row.png`), rendered only from the
  server-resolved `privacy` decision, live `PATCH /rides/{id}` verified
  with re-read of authoritative state
  (`c2-ride-audience-only-you-live.png`, then reverted).
- The client never invents a default: uploads omit `visibility` so the
  server applies the account default; a failed write leaves prior truth
  standing (unit-tested). The ratified values are pinned in exactly one
  documented constant, `ExposureDefaults` (PrivacyModels.swift), for
  Tim's one-line re-ratification if the default ever moves.

## Item 3 — Permission choreography (`batch-c/c3-*.png`)

Audit results and fixes (`PermissionChoreography.swift` + tests):

- **Location**: already asked at first Record tap; verified live after
  `simctl privacy reset` — the OS prompt fires exactly at the Record tap
  with the truthful purpose string
  (`c3-location-prompt-at-record-tap.png`); Deny renders the truthful
  blocked state with a Settings hand-off and the rest of the app stays
  usable (`c3-location-denied-truthful-state.png`). No pre-prompt context
  screen — Law 9 (no invented copy) makes the OS prompt at the right
  moment the choreography.
- **Bluetooth (fixed)**: `RecordingView.onAppear` used to bring up
  `CBCentralManager` unconditionally — stacking the system Bluetooth ask
  onto the location ask at a rider's first Record. Now the central comes
  up at Record open only when paired devices exist (reconnect is the
  demonstrated need); the first-ever ask belongs to the Sensors room
  (`SensorPairingView.onAppear → startScanning`). Simulators cannot render
  CoreBluetooth prompts, so this is proven by the code gate + policy tests,
  stated honestly here.
- **Notifications**: no `UNUserNotificationCenter` call exists anywhere —
  correct, since push delivery isn't built (odmi6.8). The ask-timing seam
  is documented in code: ask when the first settlement/displacement becomes
  possible for this rider, deep-link targets first, never at launch.
- **Location Always**: not requested anywhere — correct, since the app
  declares no background-location capability and records foreground-only.
  The ratified timing is encoded dormant in
  `PermissionChoreography.shouldOfferAlwaysUpgrade` (only after a first
  successful while-in-use recording, only at next Record open, only once
  background recording ships) and pinned by tests, including the test that
  the shipped flag is still false.
- **Photos**: profile editing uses `PhotosPicker`, which runs
  out-of-process — no permission prompt at all (verified live; the picker
  itself displays "can only access the items you select").

## Item 4 — Profile editing (`batch-c/c4-*.png`)

The avatar-sheet identity header is now the pencil (header is the tap,
pencil is the hint). The Profile sheet edits display name and neighborhood
(server limits 50/100 mirrored), and runs the avatar photo through the
signed lane: init → storage PUT → complete, with the truthful Uploading…
state, standing failure states, and success only when `complete` returns
the refreshed profile (`c4-profile-avatar-uploaded-live.png` — live
production upload, subsequently removed via the confirmed Remove Photo
path, which restored initials from server truth). Preflight mirrors the
server media contract (JPEG/PNG/WebP/HEIC/HEIF, ≤ 15 MB) and refuses
locally without network calls. Session adoption is identity-pinned
(another account's profile response is refused).

**Contract discovery (fixed during live verification):** the backend's
`update_user_profile` drops JSON nulls for identity fields (only
physiology is null-clearable), so a null "clear" was a silent no-op the
sheet would have misreported as success. The client now ships the empty
string as the clear (which the server persists), and every rendering
surface treats empty-as-absent (`riderShownName`, unit-tested). Verified
live: neighborhood cleared and confirmed gone after a fresh
`GET /users/me`.

## First-run walk (`batch-c/c5-*.png`)

On the existing test account only (dev sign-in reuses the persisted wallet
seed; no accounts created): signed-out arrival renders the onboarding
surface (`c5-firstrun-01-onboarding.png`); sign-in lands on the feed; the
first Record tap produces the location moment above. The empty-feed
invitation state remains covered by `evidence/02-feed-empty.png` (this
account has rides, so the invitation legitimately does not appear).

**Known blocker observed (pre-existing, not batch C):** this simulator's
local ride custody store cannot activate — the feed shows the standing
"Ride evidence is unavailable / Retry" banner (visible from first launch,
before any batch C surface ran) and Record presents the custody alert whose
Retry and Cancel both re-fail, trapping the rider until force-quit. The
recorder refusing to fake a working state is designed behavior; the missing
exit is not. Filed for the custody lane (fy7x2/odmi6.7) as a spawned task
chip; the allow-path "Waiting for GPS…" render remains covered by the
earlier `13-recording-*.png` evidence.

## Remaining scope (honest, per bead)

- `f4acp.1.4`: pre-submit exposure moment on import/recorded-ride upload
  (the ratified "sees and can change before submission" surface), the
  map-visibility default row, and per-ride map-visibility controls are not
  in this batch. Server-side enforcement (defaults, edge law, leaderboard
  exclusion) is live regardless.
- `f4acp.1.8`: physical-device fresh-install walk (real Bluetooth prompt,
  real Settings round-trip) belongs to the cohort stranger-walk lane.
- `f4acp.1.9`: no square-crop step (system PhotosPicker only; the avatar
  renders center-cropped in the circle). Username editing intentionally
  untouched.
