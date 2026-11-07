# Background ride processing — local/offline simulated evidence

**Bead:** `boulderroller-v2-odmi6.7`

**Owner/status:** claude / corrective item-7 pass locally complete, pending
exact-commit coordinator review

**Evidence class:** local/offline simulated only

**Input class:** deterministic owner, file, auth, transfer, network, backend-status,
feed, and reveal fixtures; no production authentication, upload, ride processing,
reveal, deployment, or physical background execution

## Exact mobile render evidence

Both captures come from the final arm64 Debug build on the iPhone 17 simulator.
An exact `#if DEBUG` launch argument supplies persisted-job projections to the
real production `FeedView` and `LocalRideCard`; normal runtime, auth, and network
work is bypassed. The fresh Release executable contains no
`-BRRideUploadRenderFixture` marker.

- `07-upload-processing-simulated.png` shows a nonfinal local ride as
  `Processing`. Its parser-derived distance and time remain visible while
  unavailable climbing truth is `—`; the card is not a final ride button.
  SHA-256: `c5654c92da4ca72158d8c4fe32fcdb31625715e50e6fc89548393bf5e0d0387c`.
- `07-upload-failed-simulated.png` shows an authoritative failed local job as
  `Processing failed`, keeps all unavailable metrics as `—`, and retains the
  existing `Retry` action. SHA-256:
  `576ab5e1c2cfc57aa555c0dbd1601709d1143134bc50020b1bdfbfcc70c0d1f4`.

Exact live-read versus fixture boundary: **no live read occurred**. Rider name,
file summary, upload phase, error state, and retry eligibility are deterministic
fixture inputs. The feed shell, card grammar, dash projection, nonfinal
navigation boundary, and Retry rendering are the exact post-change production
views. No account was created, no session was borrowed, no file was uploaded,
and no reveal was triggered.

## Externally checkable outcome

The app now publishes an owner-bound job directory containing the immutable
source bytes and metadata before its first server or storage call. Source and
metadata are staged together and atomically renamed; a process interruption
cannot publish a source-only job. Every resume revalidates byte count and
SHA-256. The logical job UUID remains stable across auth expiry, ambiguous init,
storage transfer loss, ambiguous completion, process restart, and transient
status failure.

The upload init endpoint accepts that UUID as the ride/upload ID without a
migration. An exact same-owner, same-file `uploading` retry reissues a signed URL
for the same path; changed immutable inputs fail 409 and cross-owner lookup is
404. Completion verifies the object once, durably advances `uploading` to
`pending`, retries the same ride-ID ingest from `pending`, and advances to
`processing` only after queue acceptance. Queue failure remains `pending` and
can be reconciled; processing and later completion replays are read-only. The
client consumes the structured `file_missing` response and reinitializes the
same UUID rather than minting a new job.

The production transfer boundary is a stable background `URLSession` using a
file-backed multipart body and the persisted job UUID as `taskDescription`.
The app delegate restores background-session events, and an allowed
`BGProcessingTask` performs short auth/status reconciliation. The built Release
plist contains `com.boulderroller.app.ride-upload.reconcile` and the
`processing` background mode. Expired or unavailable auth moves the same job to
waiting without incrementing its attempt or deleting its bytes; a valid session
for the same owner resumes it. A different owner cannot send or read the job.
Only phases that can advance automatically reschedule background work; waiting
for auth, under review, failed, and final/reveal-only jobs do not create an
endless background loop.

Feed loading is owner- and generation-bound. It loads local custody first,
preserves Processing/error truth when `/rides` or the local refresh is
unavailable, and does not let a list-only `completed` row replace the local card
until the persisted job has passed final reconciliation. Ambiguous/retryable
transport stays `Processing` with Retry; only an authoritative failed outcome
is `Processing failed`. Owner changes clear the prior rider synchronously, and
late prior-owner reads cannot overwrite the current feed.

A reveal becomes eligible only after status is completed and attested, the
processing stage is completed, canonical match is not false, no processing
failure exists, and successful owned ride-detail and patterns rereads agree on
the authoritative ride ID. Pending, unavailable, under-review, failed,
provisional, mismatched, or incomplete rereads stay nonfinal and never reveal.

Selection now atomically persists one owner-scoped active presentation claim
before returning the payload. A process exit after selection, sign-out, or an
owner switch before acknowledgement leaves that same claim recoverable for its
original owner on the next open. AppSession coalesces overlapping
scene/foreground selection requests, keeps the reveal cover bound while an
acknowledgement is in flight, and cannot advance to or overwrite a second
queued reveal.

The explicit `Done` action is the durable consumption boundary. It validates
the current owner, local job, random claim ID, and authoritative server ride ID;
then it atomically writes the owner/authoritative-ID acknowledgement marker
before marking duplicate local siblings consumed and clearing the active
claim. Only after that write succeeds does AppSession clear the presented
reveal. A crash before the marker may present the same unacknowledged ceremony
again; a crash after the marker cannot replay it, even if metadata cleanup did
not finish. This is delivery acknowledgement semantics, not a claim that a
screen pixel and durable storage can be crash-atomic.

## Red to green

- Initial iOS retained red: eight production-seam lifecycle tests produced ten
  behavioral failures before persistence/reconciliation existed. Restart,
  expired auth, owner switching, ambiguous completion, strict finality,
  exactly-once reveal, and feed-state outcomes were absent; the immutable-byte
  assertion was the one pre-existing truth that already passed.
- Backend stable-ID red: six upload-init/completion contract tests failed
  before client UUID ownership, same-path retry, and completion replay existed.
  A later retained completion-order red produced three route failures plus a
  missing repository transition seam because `processing` was written before
  queue acceptance and `pending` could not resume.
- Corrective behavioral reds bound completed-list false finality, loss of a
  local card on store unavailability, pending completion replay, concurrent
  reconciliation, source-only publication, duplicate authoritative reveal,
  two owner-switch feed races, and ambiguous transport falsely labeled as a
  failure. Each failed against the immediately prior production seam before its
  bounded correction.
- Next-open overlap red: one production AppSession fixture failed three
  assertions—the same owner was consumed twice, the second reveal overwrote the
  first, and zero reveals remained queued. The coalesced implementation passes
  all three assertions.
- Corrective acknowledgement red against exact rejected production code
  `23181980`: 3/3 retained store tests failed (exit 65). A selected reveal was
  nil after store recreation; owner A could not recover it after switching to
  owner B; and selection changed two same-authoritative-ID siblings from
  `[queued, queued]` to `[consumed, consumed]`. The corrected store returns the
  same durable claim across recreation/owner switching, leaves both siblings
  queued before acknowledgement, and consumes both only after exact `Done`
  acknowledgement. A production AppSession seam also proves acknowledgement
  failure retains the visible claim and a later successful acknowledgement
  clears it.
- Render red: the exact Debug launch modes initially resolved to no fixture;
  the production-view harness now admits only the exact Processing and failed
  modes and remains absent from Release.
- Green: 30/30 focused item-7 iOS tests pass on the arm64 iPhone 17 simulator.
  The complete iOS truth suite passes 89/89. The backend upload-handshake and
  repository source is unchanged from the prior 61/61 proof. A fresh arm64
  Release build from final source at
  `/tmp/br-item7-release-corrective.r61Zyg` succeeds; its built executable is
  arm64, the built `Info.plist` contains
  `com.boulderroller.app.ride-upload.reconcile` and `processing`, and the
  executable does not contain `-BRRideUploadRenderFixture`. The Debug test
  build succeeds and `git diff --check` passes.

Commands:

```text
xcodegen generate --spec ios/project.yml

xcodebuild test -project ios/BoulderRoller.xcodeproj -scheme BoulderRoller \
  -destination platform=iOS\ Simulator,id=83285814-8448-43E4-9AB5-630A48FFF29C \
  -only-testing:BoulderRollerTests/RideUploadLifecycleTests \
  -only-testing:BoulderRollerTests/RideUploadBackgroundSchedulingPolicyTests \
  -only-testing:BoulderRollerTests/UploadHTTPErrorDecodingContractTests \
  -only-testing:BoulderRollerTests/AppSessionRideRevealSelectionTests \
  -only-testing:BoulderRollerTests/RideRevealAcknowledgementDurabilityTests

xcodebuild test -project ios/BoulderRoller.xcodeproj -scheme BoulderRoller \
  -destination platform=iOS\ Simulator,id=83285814-8448-43E4-9AB5-630A48FFF29C

ACCESS_TOKEN_SECRET=test-access-secret REFRESH_TOKEN_SECRET=test-refresh-secret \
python3 -m pytest -q \
  backend/tests/routes/test_ride_attestation_handshake.py \
  backend/tests/repositories/test_ride_repository.py

xcodebuild build -project ios/BoulderRoller.xcodeproj -scheme BoulderRoller \
  -configuration <Debug|Release> \
  -destination platform=iOS\ Simulator,id=83285814-8448-43E4-9AB5-630A48FFF29C \
  CODE_SIGNING_ALLOWED=NO

xcrun simctl launch 83285814-8448-43E4-9AB5-630A48FFF29C \
  com.boulderroller.app -BRRideUploadRenderFixture <processing|failed>

xcrun simctl io 83285814-8448-43E4-9AB5-630A48FFF29C screenshot \
  ios/evidence/granularity/<capture-name>.png
```

## Remaining boundary

This is local/offline simulated evidence only. Simulator configuration and
state-machine proof do not establish that iOS granted or completed a background
transfer or `BGProcessingTask` on physical hardware. No backend change is
deployed, and no real file, auth session, rider account, production status,
processing result, or reveal was exercised. The database-plus-NATS handoff is
durably retryable but is not claimed as an unlimited transactional exactly-once
outbox; concurrent pending publication uses the same ride-ID message key and
the existing JetStream deduplication window.

The later Tim gate remains a real-phone, real-ride check covering suspension,
process termination, network loss, expired-auth resume, authoritative backend
completion, feed progression, and one next-open reveal. Item 8 remains open,
unassigned, and untouched pending exact-commit coordinator acceptance of item
7.
