# Boulder Roller Product Path Registry

**Status:** REFERENCE — dated path and surface snapshot, not current assignments
**Created:** 2026-04-22
**Authority:** This registry sits under `docs/PROTOCOL_TRUTHS.md`, `docs/BACKEND_TRUTHS.md`, and `docs/MOBILE_TRUTHS.md`. It does not redefine protocol semantics; it maps those semantics onto product paths, contracts, surfaces, gates, and beads.

Current authority is the [TRUTHS-first hierarchy](../FRESHEST_SPEC.md#source-of-truth-hierarchy); native surfaces are documented in [`ios/README.md`](../../ios/README.md), and live assignments belong in Beads per [AGENTS.md](../../AGENTS.md).

## Purpose

Boulder Roller has one product spine:

`record ride -> upload evidence -> process evidence -> attest ride -> earn on climb -> settle vault -> view result -> public verify`

Every mobile, portal, backend, indexer, and BoulderScan feature should attach to one of the product paths below. If a change cannot name its path, it is probably breadth, cleanup, or experimental work and should not silently affect core product truth.

Each path must define:

| Requirement | Meaning |
|---|---|
| Contract | The API, payload, account, event, or fixture shape that consumers may depend on. |
| State transition | The database rows, chain accounts, indexed projections, or local-device records that change. |
| Surfaces | The mobile, portal, BoulderScan, or operator screens that must consume the path. |
| Gates | The executable tests, smokes, or launch checks that prove the path still works. |
| Tracker | Beads that own remaining work or intentionally parked follow-up. |

## BoulderScan Language Rule

BoulderScan is the public proof witness. It should mirror Etherscan/Solscan conventions more than rider-app language.

Use explorer-native terms where they are clearer: `Transaction`, `Account`, `Program`, `Token`, `Vault`, `Events`, `Metadata`, `Holders`, `Transfers`, `Instruction`, and `Address`.

The rider app can soften language for felt experience. BoulderScan should make proof legible to technical users, investors, validators, and outsiders who expect an explorer. A BoulderScan Vault page should feel like a Solscan account/token/NFT detail page adapted for Boulder Roller: header, summary cards, decoded fields, metadata, related transactions, events, and raw account escape hatch.

Visible competitive language is `Leaderboard`; its undistributed accounting
bucket is `Leaderboard pool`. Existing `record_board` and `record_royalty`
identifiers may appear only in raw decoded or compatibility detail. Token-flow
summaries should show explicit accounting movement, such as `Staker allocation
-> Leaderboard pool` and `Prior staker balance -> Leaderboard pool`, rather than
deployment-history labels such as `legacy` or `cutover`.

## Path Status Model

| Status | Meaning |
|---|---|
| Green | Contract, state transition, surface, and gate exist for the current devnet lane. |
| Yellow | Shape exists, but a surface, real-device validation, live-data confirmation, or deployment check remains. |
| Red | Product path is not coherent enough for a real user or operator loop. |

## P1 Record Ride

**Status:** Yellow

**User outcome:** A rider records GPS and sensor evidence honestly on device.

**Contract:** Mobile recording session writes durable local ride data, GPS samples, sensor samples, parser version, preliminary ride hash inputs, and crash-recovery markers.

**State transition:** Device-local SQLite moves from recording session to stopped ride with canonical evidence preserved. No backend or chain truth is created yet.

**Surfaces:** Mobile `RecordScreen`, `PostRideScreen`, local ride store, upload queue.

**Gates:** Mobile recording pipeline tests, GPS validation tests, canonical hash symmetry tests, real-device M1 validation.

**Tracker:** `boulderroller-v2-dg98.1` owns real-device M1 completion. Related completed foundation includes mobile canonical hash, SQLCipher, GPS integrity, upload idempotency, and clock-domain hygiene.

## P2 Upload Ride

**Status:** Yellow

**User outcome:** A stopped ride uploads once, with enough evidence for backend canonicalization and review.

**Contract:** Upload init carries `file_hash`, `preliminary_ride_hash`, and `parser_version`; enqueue is idempotent.

**State transition:** Mobile upload queue records uploaded state; backend creates or updates ride rows without duplicate side effects.

**Surfaces:** Mobile upload queue, backend ride upload routes, mobile post-ride uploaded state.

**Gates:** Mobile upload queue tests, backend preliminary-hash handshake tests, client.v1 route contract tests, real-device M2 validation.

**Tracker:** `boulderroller-v2-dg98.2` owns the real-device stop/upload validation.

## P3 Process Evidence

**Status:** Yellow

**User outcome:** Backend turns uploaded evidence into deterministic ride facts: canonical ride hash, TSS, climb matches, CAL eligibility, and review state.

**Contract:** Backend parser output must produce stable ride hash, parser version, TSS, climb candidates, canonical climb matches, and ride status fields through `client.v1`.

**State transition:** Backend ride rows move through processing states; `patterns_climb`, ride earnings, and review fields are populated. No economic side effect should happen without a valid ride attestation path.

**Surfaces:** Backend ride processor, portal ride detail, mobile ride status, admin repair/backfill endpoints.

**Gates:** Backend ride processor client contract smoke, ride hash symmetry gate, client surface requirements gate, climb backfill tests.

**Tracker:** `boulderroller-v2-mv7l` remains the main detector-quality lane. `boulderroller-v2-bdh` is now only a live-data confirmation case for one historical Corey ride, not the canonical detector strategy.

## P4 Attest Ride

**Status:** Yellow

**User outcome:** A ride becomes verifiable protocol evidence with a commitment that can be checked against source ride data.

**Contract:** `RideAttestation` PDA/event plus `client.v1` ride status fields: `attestationStatus`, `rideHashHex`, `preliminaryRideHashHex`, `preliminaryParserVersion`, `canonicalMatch`, `reviewReason`, `rideAttestationPda`, and attested timestamp fields.

**State transition:** Backend review state resolves to attested or under review; chain/indexer projection records the attestation; client status becomes provisional or attested.

**Surfaces:** Backend ride attester, indexer ride attestation projection, mobile post-ride state, portal RideView, BoulderScan attestation-related panels.

**Gates:** Ride attestation handshake tests, client.v1 schema/fixture gates, full-stack fixture smoke, mobile M3/M4 validation.

**Tracker:** `boulderroller-v2-dg98.3` and `boulderroller-v2-dg98.4` own rider-visible attested resolution and identity-binding verification.

## P5 Earn On Climb

**Status:** Green

**User outcome:** A valid ride crossing a climb can produce CAL, climb completion, Record Board placement, tribute, and receipt-backed economic consequences.

**Contract:** `client.v1` ride earnings and climb summary DTOs; on-chain CAL
credit plus `ClimbCompletionReceiptV2` tied to ride evidence. A climb earning
exposes `completionEvidenceVersion`, `tributeBound`, and `tributeTruthSource` so
completion identity and exact tribute authority cannot be conflated.

**State transition:** Rider token state, climb completion receipt, Record Board projection, ride earnings projection, and vault tribute/carry state update.

**Surfaces:** Backend ride processor, indexer projections, portal RideView and climb surfaces, mobile post-ride result surfaces, BoulderScan climb/vault/event pages.

**Gates:** Valid Record Board full-stack smoke, V1 fail-closed and V2
wrong-tribute atomicity on a local validator, PostgreSQL V1 quarantine and
amount-mismatch finality tests, ride processor contract smoke, settlement
conservation gate, indexer V2 wire/persistence tests, and BoulderScan proof
witness tests.

**Tracker:** `boulderroller-v2-8346` owns exact completion tribute evidence.
Historical V1 rows stay visible as identity evidence but cannot make an amount
authoritative. Future failures should attach to this path instead of creating
detached reward/leaderboard terminology.

## P6 Settle Vault

**Status:** Green

**User outcome:** A vault settlement allocates DUNG through discrete protocol buckets without Synthetix-style reward-rate drift.

**Contract:** Settlement event projections, `SettlementStatus`, per-bucket carry, Record Board payout history, staker allocation, Local Legend payout, POL, and treasury outputs.

**State transition:** Vault carry buckets, recipient unclaimed rewards, payout projections, distribution history, and settlement finality fields update on the settlement clock.

**Surfaces:** Backend settlement processor, indexer settlement projections, portal economy views, BoulderScan vault settlement tabs.

**Gates:** Settlement conservation gate, full-stack smoke, valid Record Board smoke, client.v1 settlement fixtures.

**Tracker:** No current red/yellow construction bead. Keep future work bucket-specific; do not flatten carry or reintroduce reward-rate language.

## P7 View Rider Result

**Status:** Yellow

**User outcome:** A rider sees what happened without needing to understand backend jobs or explorer internals.

**Contract:** `RideAttestationStatus`, `RideEarnings`, `ClimbSummary`, `RecordBoard`, and `SettlementStatus` DTOs.

**State transition:** No new truth is created by this path. It reads projected, attested, and on-chain truth through explicit labels.

**Surfaces:** Mobile `PostRideScreen`, mobile `RideDetailScreen`, portal `RideView`, portal climb surfaces.

**Gates:** Client proof surface requirements gate, portal scoped typecheck/perf release, mobile attestation derivation tests, mobile M3/M5 validation.

**Tracker:** Mobile M3/M5 are the key remaining product-shape work. Portal has contract wiring but still needs normal bug hunting.

## P8 Public Verify

**Status:** Yellow

**User outcome:** An outsider can inspect the protocol trail without trusting the rider app or backend UI.

**Contract:** BoulderScan indexer API for observatory, vault/climb, transaction, account, event, supply, ride attestation, and settlement projections.

**State transition:** No new truth is created by this path. BoulderScan reads indexed chain truth and selected public projections.

**Surfaces:** BoulderScan Observatory, Vault page, Climb route/redirects, Transaction page, Account page, event feed, metadata panels.

**Gates:** BoulderScan typecheck/tests, launch smoke, hydrated browser smoke, proof witness tests.

**Tracker:** `boulderroller-v2-cpyu.9` owns staging/public launch checks. The open `boulderroller-v2-cpyu` epic remains the umbrella until launch is actually reachable and verified.

## P9 Auth And Identity

**Status:** Yellow

**User outcome:** A rider enters with a coherent identity and wallet model across mobile and portal.

**Contract:** Invite validation, Privy/social identity, wallet identity, refresh/session contract, and wallet-signing semantics remain distinct but linked.

**State transition:** Auth identity rows, wallet links, refresh tokens, user profile, and rider protocol identity become available to app surfaces. No ride or token truth is created by login itself.

**Surfaces:** Portal auth screens, mobile login/wallet screens, backend auth routes, wallet connect/signing surfaces.

**Gates:** Auth gate script, auth route tests, portal scoped typecheck, mobile wallet tests.

**Tracker:** `boulderroller-v2-3de` is still relevant for production auth migration. Secrets rotation beads are parked by sprint decision, not deleted.

## P10 Admin And Operator Repair

**Status:** Yellow

**User outcome:** Operators can seed, repair, backfill, deploy, and smoke without corrupting protocol truth.

**Contract:** Admin repair endpoints, seed scripts, smoke scripts, address registry, deploy runbooks, bd workflow, and protocol gate commands.

**State transition:** Operator actions may create, repair, or reseed protocol state. Every such action must either be chain-native or clearly marked as projection repair.

**Surfaces:** Backend dev/admin routes, scripts, runbooks, BoulderScan launch checks, droplet/staging deployment workflows.

**Gates:** Protocol gate script, auth gate script, deploy verification, backfill tests, BoulderScan launch smoke.

**Tracker:** `boulderroller-v2-c3dx` is the bd workflow cleanup; `boulderroller-v2-bdh` is the live Corey rerun; security/secret beads remain tracked but parked for the current build sprint.

## How To Use This Registry

Every new core-path bug should name its path ID in the bead description or close reason.

Every new product surface should say whether it reads on-chain truth, attested truth, or projected truth.

Every new gate should prove one of these paths. A gate that does not attach to a path is probably a useful unit test, not a product-spine gate.

Every future cleanup should preserve BoulderScan's explorer-native language unless the live product explicitly decides otherwise.
