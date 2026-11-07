# Boulder Roller iOS — release runbook

Bead `boulderroller-v2-odmi6.14`. Secrets never in git; the ASC key and team
id live in `ios/.release-config.env` (gitignored).

## Cut → archive → upload → testers

1. **Cut**: green suite on the release commit (`xcodebuild test`), clean
   tree. If `APPLE_MEMBERSHIP_RENEWAL` in `ios/.release-config.env` is
   within 30 days, stop and renew (or record why not) before releasing —
   a lapsed membership revokes certificates and pulls TestFlight builds
   (credential inventory: `docs/runbooks/MOBILE_CREDENTIALS.md`).
2. **Archive**: `bash ios/scripts/archive.sh` — stamps the git build number,
   archives with dSYMs, preserves symbols under
   `~/BoulderRoller-dSYMs/<version>-<build>-<sha>/`.
3. **Upload**: `bash ios/scripts/upload_testflight.sh` — exports and uploads
   to App Store Connect; fails truthfully listing anything missing.
4. **Invite**: App Store Connect → TestFlight → Internal Testing → add the
   First Cohort group to the processed build (internal testers need no
   review).

Crash symbolication for TestFlight builds:
`docs/runbooks/IOS_CRASH_SYMBOLICATION.md`.

## One-time founder steps (need the Apple Developer account)

Audited against this Mac 2026-08-21: the **paid membership already
exists** — team `37XSG7J2FU` (joined ~2026-05-13), a valid Apple
Development certificate, and the App ID `com.boulderroller.app` already
registered with a one-year managed profile. `ios/.release-config.env` is
created with the team id filled in. A signing archive run gets past
membership and fails on exactly the remaining portal clicks:

1. ~~Team id~~ — done (`DEVELOPMENT_TEAM=37XSG7J2FU`, from the keychain).
2. **Capabilities on the existing App ID** (developer.apple.com →
   Identifiers → com.boulderroller.app): check **Push Notifications** and
   **Sign In with Apple**, save. The managed profile regenerates on the
   next signed build — this is the exact pair the archive currently
   fails on.
3. **App record** (App Store Connect → My Apps → “+”):
   - Platform: iOS · Name: **Boulder Roller** · English (U.S.)
   - Bundle ID: **com.boulderroller.app** (already registered)
   - SKU: `boulderroller-ios`
4. **ASC API key** (Users and Access → Integrations → App Store Connect
   API → Team Keys → Generate; role **App Manager**). Download the `.p8`
   once, store at `~/.appstoreconnect/private_keys/AuthKey_<KEYID>.p8`,
   fill `ASC_KEY_ID`, `ASC_ISSUER_ID`, `ASC_KEY_PATH` in
   `ios/.release-config.env`.
5. **APNs key** (Certificates → Keys → “+”, Apple Push Notifications
   service). Download the `.p8` once; it goes to the droplet for the send
   worker (`docs/runbooks/MOBILE_PUSH_OPERATIONS.md`), never to git.
6. Confirm the membership renewal date at developer.apple.com →
   Membership and correct `APPLE_MEMBERSHIP_RENEWAL` in
   `ios/.release-config.env` (currently estimated 2027-05-13 from the
   certificate dates).

## What each key unlocks

- **Team id (paid Apple Developer membership)**: signed archives, device
  installs, the `aps-environment` entitlement becoming effective.
- **ASC API key**: the TestFlight upload lane (`upload_testflight.sh`) and
  cloud-managed signing (`-allowProvisioningUpdates`).
- **APNs `.p8`**: real push delivery from the backend send worker — until
  then the worker stays feature-flagged off/dry-run and notification copy
  remains `[COPY: Tim]` placeholders.

## Kill switches and forced upgrade (L3.05)

Operator authority: Tim, or the mobile lane acting under an incident with
the change recorded in the owning Bead. Every flip is an environment-file
edit on the droplet followed by an API restart — the deploy log plus the
Bead note are the audit trail. Rollback is the same lever flipped back;
clients pick either direction up on their next `/status` read (bounded by
the app's 15-minute capability cache).

- **Disable one capability** (`/status → mobile_capabilities`):
  `BR_MOBILE_CAP_RIDE_UPLOAD=false` pauses native server handoff — durable
  jobs and local custody stay intact and resume on rollback;
  `BR_MOBILE_CAP_PUSH_REGISTRATION=false` stops new APNs token
  registrations; `BR_MOBILE_CAP_PROFILE_WRITES=false` is contract-only
  until a surface consumes it. Only the exact value `false` disables.
- **Require an upgrade**: `BR_MIN_SUPPORTED_IOS_BUILD=<build>` makes the
  API answer older builds with the typed 426 `upgrade_required` that the
  app renders as its stale-client state. `/health`, `/status`, and
  `/metrics` stay reachable for any build.
- **Maintenance** stays the existing emergency-controls 503 and is a
  distinct client state from unsupported-build; a `/status` outage is
  neither permission nor a kill signal.
- An active recording never depends on `/status`; no switch can interrupt
  one or touch authoritative ride or economic state.
