# Boulder Roller Canonical Mobile Truths

**Status:** ACTIVE
**Date:** 2026-04-17
**Updated:** 2026-08-24 - ratified account deletion custody and anonymization contract; 2026-08-02 - account-bound local ride custody and segmented privacy projections; 2026-07-16
**Ratified:** 2026-04-17 by Tim
**Audience:** Founding, product, mobile
**Purpose:** Semantic source of truth for Boulder Roller's mobile client, bringing it into coherence with PROTOCOL_TRUTHS.

This document sits **under** [PROTOCOL_TRUTHS](./PROTOCOL_TRUTHS.md).

When mobile work conflicts with protocol truth, protocol wins. This document
defines what must remain true inside the rider's device and the app that lives
on it.

If the implementation conflicts with this document, this document wins on
semantics and the implementation must be brought back into coherence.

---

## 1. North Star

The mobile app is the rider's **honest witness**.

Its job is to record what happened on a ride with integrity so the protocol
can make durable economic claims about that effort later, on-chain.

The app is not a training analytics suite. It is not a social feed. It is the
edge of the protocol — the trusted surface where fitness becomes evidence.

The product is:
- a reliable recorder that survives interruption
- a truthful reporter of what hardware participated
- an honest lens into the rider's standing on the protocol

---

## 2. Core Objects on Mobile

### 2.1 Ride

A **Ride** on the device is a bounded session of witnessed effort.

It begins when the rider starts recording and ends when the rider stops, or
the app crashes and the next session recovers it. Until uploaded and attested,
a ride lives only on the rider's device.

A Ride is:
- a sequence of samples (geographic and physiological)
- a device-stamped canonical fingerprint
- the rider's claim that effort took place, pending protocol verification

### 2.2 Recording Session

A **Recording Session** is the live state of ride capture.

It has distinct modes that the rider influences:
- recording
- manually paused
- auto-paused (rider has stopped moving; GPS continues)
- stopped

These modes are not interchangeable. Manual pause reflects rider intent.
Auto-pause reflects physics. The protocol does not see them directly, but the
device must track them distinctly to produce an honest ride.

### 2.3 Connected Hardware

**Connected Hardware** is any paired sensor that testifies during a ride.

When the rider pairs a power meter, heart rate strap, or cadence sensor, they
are telling the app: let this device testify to my effort.

The app records what was connected. It does not fabricate or infer sensor data
it did not receive.

### 2.4 Attestation Stamp

The **Attestation Stamp** is the device's witness signature on a ride.

It is the pair of values — parser version and preliminary ride hash — stamped
on the ride at the moment of stop.

It is the device-side half of the ride-attestation loop
(PROTOCOL_TRUTHS §2.3). The backend closes the loop when it re-canonicalizes
the uploaded ride and compares.

### 2.5 Wallet

The **Wallet** on mobile is the rider's Solana identity surface.

It holds CAL, receives DUNG, and signs protocol transactions. It is not the
ride recorder. It is not the rider's effort identity.

---

## 3. Three Clocks

Time on mobile is not a single thing. Three clocks coexist, and each is
authoritative for a different concern.

### 3.1 Device Wall-Clock

The phone's real-world clock. Authoritative for:
- ride start and end
- pause and resume events
- canonical ride timestamps

It can jump backwards and forwards. Mobile must reason about those jumps
rather than assume monotonic behavior.

### 3.2 GPS Satellite Timestamp

The time reported by the GPS constellation on each fix. Authoritative for:
- ordering individual samples within a ride
- evidence of when each reading was captured

It is the closest thing the device has to externally-witnessed time. It does
not flow while GPS is dark.

### 3.3 Monotonic Device Clock

The phone's CPU-driven forward-only clock. Authoritative for:
- measuring intervals within a single awake session
- nothing that must survive suspension or crash

Mobile must never silently conflate these clocks. Treating one as another is
how ride timing gets corrupted.

---

## 4. Three Evidence Layers

A ride is composed of different kinds of evidence. They are not
interchangeable.

### 4.1 Geographic Evidence

GPS samples: latitude, longitude, altitude, speed.

Geographic evidence is **where** the ride happened. It carries accuracy
metadata. Low-quality geographic evidence must be marked or rejected at
capture time, not laundered into the record.

### 4.2 Physiological Evidence

Connected-hardware samples: power, heart rate, cadence.

Physiological evidence is **how hard** the rider worked. It must be sourced.
If a power meter produced it, the ride says so. If no power meter was paired,
the ride's power field is empty — not zero.

### 4.3 Composed Evidence

Derived aggregates: TSS, distance, elevation gain, moving time, and climb
detections downstream.

Composed evidence is a function of the other two. It must never claim more
than its inputs support. A GPS-only ride composes differently than a
fully-instrumented ride, and the protocol must see both honestly.

---

## 5. Roles on Mobile

### 5.1 Rider

The **Rider** is the person holding the phone.

They own the ride capture session, the local data, and the wallet. They
consent to what records, what uploads, and what earns.

### 5.2 Connected Hardware

Covered in §2.3. The app surfaces what is currently live. It does not pretend
hardware is present when it isn't. A ride without a power meter is a valid
ride, not a defective one.

### 5.3 Wallet

Covered in §2.5. The wallet is how the rider participates in protocol
economics. The wallet is not the recorder.

---

## 6. The Attestation Moment

The device stamps attestation at one moment: ride stop.

At stop, the app:
- finalizes the canonical form of the ride
- computes the preliminary hash
- stamps the parser version that produced it
- writes both onto the ride

Every stop path must stamp. Normal stop, crash-recovered stop, stop from
paused, stop with zero samples. The protocol does not distinguish between
these paths at the attestation layer, and neither can mobile.

If a ride enters the upload queue without an attestation stamp, that is a bug.

---

## 7. The Upload Boundary

Mobile's responsibility for a ride ends when the backend accepts it.

The file hash is the handoff contract. The same ride uploaded twice must
dedup by hash. Retries must produce the same hash. When they don't,
something has drifted — mobile must say so loudly rather than silently
orphan the upload.

Between stop and successful upload, the ride belongs to mobile alone. The
app must preserve it through:
- network loss
- app suspension
- app crash
- phone reboot
- session expiration

A ride that survives the rider's intent to save it is mobile working
correctly. A ride that silently disappears is mobile failing a contract.

---

## 8. Offline Is Normal

Rides happen where networks do not.

The app must complete a ride — start, stop, local finalization — without any
server contact. Upload waits for network; the ride does not.

Mobile must not require server reachability to:
- start a ride
- stop a ride
- compute local metrics
- stamp attestation
- show the rider their own ride

Server reachability is required to:
- upload
- retrieve attested status
- view other riders, climbs, leaderboards, vaults
- transact

---

## 9. Three Representation Layers on Mobile

Mirrors PROTOCOL_TRUTHS §5, interpreted for the device.

### 9.1 Local Truth

The rider's device-side database. Authoritative while offline. Canonical for
the rider's own ride history until attestation. Encrypted at rest.

Local ride evidence is bound to the exact authenticated wallet/account, not to
the device as a whole. Every ride, GPS point, pause, validation result, recovery
lookup, and queued upload is read or written through that owner boundary.
Legacy rows without an owner are quarantined rather than attributed to whoever
signs in next.

When an account logs out, expires, or changes, mobile suspends recording and
clears the former rider's live in-memory recorder and recovery surface. It does
not delete that rider's encrypted database row: returning as the same owner can
recover it. A queued upload rechecks its captured owner before and after the
server handoff, so evidence recorded by one rider cannot be sent under another
rider's credentials.

### 9.2 Attested Truth

The uploaded, canonicalized, hashed form of a ride. Mobile produces the
device-side half and hands off. The protocol closes the loop.

### 9.3 Projected Truth

What the app renders from server-projected state: CAL balances, leaderboards,
climb pages, ride processing stages. These are reading surfaces, not
authoritative sources. Projections are never the source of truth for what the
rider earned.

Route projections preserve every server-supplied visible route fragment. A hidden
endpoint or privacy-zone gap remains a gap in both native and fallback map
rendering; mobile never joins separate fragments into a synthetic line through
the hidden area. Local preview reduction likewise keeps only original adjacent
route edges as independent fragments.

Protocol verification is available only when the finalized on-chain
`ProgramConfig.program_version` exactly matches the generated mobile
expectation from `protocol/program-version.json`. A missing RPC response, a
truncated or invalid account, an older program, or a newer program all disable
verification. Existing projected reading surfaces may remain available, but
the app must not label them verified or authorize version-sensitive protocol
actions until exact compatibility is restored.

---

## 10. Identity on Mobile

The rider's identity has two faces in the app. They must not be collapsed.

### 10.1 Authentication Identity

How the rider signs into the app. Social auth or wallet auth. Serves the
mainstream rider without compromising the crypto-native rider.

### 10.2 Protocol Identity

The wallet address used to claim protocol outcomes. Holds CAL, receives DUNG,
stakes. Signs attestations and transactions.

Today these faces may coincide. They do not have to.

Neither of these is the rider's soulbound effort identity. That layer is
defined in PROTOCOL_TRUTHS §7.3 and lives outside the wallet.

---

## 10.3 Boulder Roller Balance State Language

Mobile primary surfaces should keep Balance language rider-native. The rider
sees rides, climbs, positions, CAL, DUNG, and clear state.

Use:

- `Boulder Roller Balance`
- `CAL counted`, `DUNG ready`, `DUNG collected`
- `Deposit CAL`, `Withdraw CAL`, `Create Vault`, `Pay with USDC`
- `Add funds`, `Withdraw to wallet`
- `Pending`, `Delayed`, and `Needs review`

Do not use gas, transaction, signature, explorer, harvest, unstake, or primary
BoulderScan/proof language in normal Balance flows. Those terms remain valid
inside protocol identity, wallet security, BoulderScan off-ramps, explicit
technical disclosure, tests, and implementation code.

---

## 10.4 Account Deletion

Account deletion **anonymizes** protocol history; it does not erase sporting or
settled authority. This policy was ratified by Tim on 2026-08-24.

The exact cross-layer disposition is:

- **Remove:** authentication identities and sessions, profile/contact fields,
  provider links and device registrations, privacy/configuration data, raw ride
  files, precise private traces, media, and other personal off-chain evidence
  not required for an authoritative sporting or settled row. On the device,
  verified cleanup removes the exact owner's encrypted recording journals,
  upload jobs and sources, post-ride media, profile/physiology data, credentials,
  routes, caches, diagnostics, notifications, and pending owner surfaces.
- **Anonymize:** retained climb attempts and times, Leaderboard and Local Legend
  history, and settled economic records point to a non-reversible anonymous
  marker instead of the rider's profile, contact identity, name, or wallet.
- **Retain:** climb times and sporting placement remain public under that marker.
  Settled economics remain under the existing private/support money authority;
  deletion does not make them public. The install-wide custody master key is
  retained because erasing it could orphan another exact owner's evidence.

Before mobile sends a deletion request it must:

- read the server's current deletion preflight;
- refuse an unavailable or wrong-contract preflight. An available preflight may
  file the durable request while value, claim, stake, or policy requirements
  remain; those requirements must stay visible as blocked/support status and
  cannot dispatch destructive work;
- read both encrypted recording custody and the upload queue;
- union those stores by their stable ride/upload UUID so one handed-off ride is
  shown once;
- surface every active, interrupted, saved-only-on-device, pending-handoff, and
  non-final upload recording;
- obtain an acknowledgement of the exact current inventory, including a
  positive zero-recording result; and
- persist an **unconfirmed** request ID/status-token pair, exact owner, and
  acknowledged inventory in the Keychain before the request crosses the network.

A changed or unreadable local inventory invalidates the acknowledgement. An
unconfirmed capability suspends recording, denies new imports and
upload-queue writes, drains writes that were already admitted, deauthorizes
upload reconciliation, and cancels that owner's active background transfers
without deleting their source files, but it does not activate the accepted
status takeover. Mobile then re-reads the authoritative
preflight and exact local inventory behind that write fence immediately before
DELETE. Only a matching server response promotes that same pair to **accepted**.
An ambiguous response is probed and may be reissued with the same pair. Stable
create conflicts persist a separate lifecycle writer fence before the
unconfirmed pair is removed and route to support instead of reopening account
work. A 404 status probe can race a delayed DELETE commit, so removing an
unconfirmed pair after 404 persists the same separate lifecycle writer fence
first. That 404 replacement fence survives relaunch and cannot be cleared by a
fresh sign-in for the same owner: a delayed DELETE may still commit after the
404. Another exact owner may sign in and use their own account without deleting
or bypassing the original owner's fence. Stable retry conflicts retain the
accepted pair and route to support. An accepted retry is
token-only: mobile rechecks exact local custody, while the server retry owns its
fresh authoritative preflight. The accepted capability takes precedence over
normal authentication routing, so queued, processing, blocked, retryable,
support, legacy-unverified, and completed states remain readable after the
account's session is tombstoned. Takeover and writer fencing are exact-owner
scoped; a retained pair for rider A cannot lock or authorize work for a signed-in
rider B. A failed Keychain read remains fail-closed but
is retried on explicit action and foreground; it is not a permanent terminal
state.

The exact authentication refusals `account_deletion_pending`, `account_deleted`,
and `account_identity_unavailable` are durable account-lifecycle states, not
transient session weather. They stop authenticated/background account work and
route to deletion status/support while preserving local ride custody. A pending
or identity-unavailable refusal can never authorize cleanup. An exact
`account_deleted` refusal may authorize local cleanup only after the same
current-inventory acknowledgement and writer-fence checks; unuploaded rides are
surfaced first. Repeated refusals advance monotonically without dropping the
original owner, and session/cache teardown cannot begin until the lifecycle
record has survived a durable read-back. The lifecycle journal retains one
exact-owner record per affected rider; accepting or completing rider B's
deletion cannot replace or clear rider A's pending, failed, or replacement
fence.

Only a token-authorized server response whose contract and request ID match and
whose internally consistent state is `completed`, or the exact server
`account_deleted` authentication refusal for a request begun elsewhere, may
start local clearing. The token route stores acknowledged ride IDs and their
digest in the capability; the external `account_deleted` route binds the same
confirmation to the live inventory digest before cleanup. Immediately before a
local removal, every remaining fenced ride must belong to the exact acknowledged
set; a new ID blocks cleanup, while a subset permits an idempotent retry after a
prior partial removal. Every other state preserves all owner-bound local
evidence. Verified completion removes:

- the exact owner's encrypted recording journals and upload jobs, source files,
  post-ride photos, and reveal markers;
- the exact owner's feed snapshot, cached profile, and entered physiology;
- authentication/provider credentials and pending import, recovery, reveal,
  notification, and deep-link state; and
- install caches that can contain that rider's images, route geometry, network
  responses, diagnostics, paired-sensor identities, or source selections.

Before the first local source byte is removed, mobile durably records the exact
verified server completion. After every required local removal verifies, mobile
durably records local-cleanup completion. Both phases are read before any status
network call, so an offline relaunch or an aged-out status row cannot trap an
already-cleared install. Cleanup is single-flight; a concurrent poll cannot skip
the durable local marker. On the token-authorized path, successful cleanup
clears only the verified owner's lifecycle-journal row while the verified
capability still carries that exact owner, then durably records local completion
in the capability before its in-memory identity is scrubbed. On the external
`account_deleted` path, successful cleanup atomically replaces only the selected
owner-bound journal row with an ownerless local-completion marker. Other owners'
journal rows survive both paths.

Required profile, session-credential, developer-identity, and owner-file
removals must throw on failure and verify absence before mobile records local
cleanup completion. The install identifier rotates after clearing. The
install-wide custody master key is retained because deleting it could orphan
another exact owner's evidence. Ownerless or unreadable quarantine cannot be
attributed safely: it routes to support and is neither silently retained as
successful cleanup nor globally erased. The deletion status capability remains
until local clearing succeeds and the rider acknowledges the completed state.

Tim confirmed the shared portal/native explainer on 2026-08-24: “Your identity
and personal data will be removed. Your climb times, leaderboard history, and
settled economics will remain linked to an anonymous account.” This sentence may
ship. It is not a permanence promise, and no rider-facing copy may add one while
the mainnet gate remains open. A separate sentence explicitly obtaining consent
to destroy unuploaded ride recordings is still Tim-owned under N14; its native
slot remains empty until Tim supplies and confirms the exact words. Functional
state and action labels remain allowed.

---

## 11. Meaning of Interrupted Rides

An interrupted ride is not a lost ride.

If the app crashes, the phone dies, or the rider closes the app mid-ride, the
next session must recover the in-flight recording and offer it back to the
rider. The rider decides whether to save or discard — the device does not
decide for them.

A recovered ride carries the same attestation lineage as a normally-stopped
ride. Recovery is not a lesser path.

---

## 12. Naming Conventions

These names are canonical in rider-facing mobile copy. Implementation names
may retain exact protocol terms:

- `Ride` is the rider-facing activity object (not "workout," not "activity,"
  and not a second noun built from `record`)
- `Recording Session` (the live state before stop)
- `Attestation Stamp` (the device's witness signature)
- `Connected Hardware` (not "devices," not "peripherals")
- `Wallet` (for the Solana identity surface)
- `Climb`, `Vault`, `CAL`, `DUNG`, `Leaderboard`, `Local Legend`, and
  `Settlement Week`; use `Record Board` only in chain-canonical or technical
  detail

Fitness-first language beats crypto-first language at every rider-visible
surface.

---

## 13. Alignment Implications

### 13.1 Preserve

- device-side attestation stamping as mobile's half of ride truth
- encrypted local ride storage
- recording that survives interruption
- sensor evidence provenance (what connected, what didn't)
- offline-first recording

### 13.2 Repair

- clock-domain confusion in ride timing
- any path where a ride leaves the device without an attestation stamp
- any path where sensor absence is misrepresented as sensor zero
- pairing state leaking across rider sessions
- authentication identity and protocol identity silently conflated in UI

### 13.3 Demote

- server round-trips as a prerequisite for anything the rider does with their
  own ride
- "activity" and "workout" as product language
- UI polish as a gate on correctness work

### 13.4 Prepare

- backend ride-attestation compare loop (mobile half is ready)
- Mobile Wallet Adapter and Seed Vault flows for the Android demo
- a soulbound effort identity surface when the protocol lands it
- broader asset graph surfaces (Route, Zone, Arena, Event, Season) in the
  rider's view

---

## 13.5 Gate 1 Enforcement

Native Gate 1 coverage lives in
[`ios/BoulderRollerTests/NativeGate1CustodyTests.swift`](../ios/BoulderRollerTests/NativeGate1CustodyTests.swift).
Its §N-named tests exercise clock separation (§3), absence vs zero (§4.2),
stop stamping (§6), durable/idempotent upload handoff (§7), offline enqueue
(§8), owner-bound encrypted custody (§9.1), interrupted-ride recovery (§11),
and ride vocabulary (§12). The native test target is configured in
`ios/project.yml` and run by `.github/workflows/ios-ci.yml`; local/CI tests
do not substitute for physical-device evidence. A Gate 1 regression is a
TRUTHS regression. The Expo-era `mobile/src/__tests__/truths/gate1/` coverage
and `docs/design/MOBILE_TRUTHS_GATE_1.md` matrix are historical references.

---

## 14. Canonical Summary

Boulder Roller's mobile client is the rider's honest witness:

- a Ride is a bounded, evidence-composed session of witnessed effort
- the device captures geographic, physiological, and composed evidence with
  provenance
- three clocks coexist; none may impersonate another
- every stop path stamps attestation
- rides survive interruption and network failure
- local storage is authoritative offline, projection is for reading,
  attestation is the handoff
- the Wallet is protocol identity, distinct from authentication identity and
  from effort identity
- fitness-first language beats crypto-first language at every rider-visible
  surface
- when anything conflicts with PROTOCOL_TRUTHS, PROTOCOL_TRUTHS wins

This is the semantic foundation for mobile engineering work. The magic is in
how these truths interpret into code, UX, and test coverage — not in the
truths themselves.
