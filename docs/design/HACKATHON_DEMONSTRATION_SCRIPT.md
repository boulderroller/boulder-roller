# Hackathon Demonstration Script — Candidate Draft

**Status:** CANDIDATE — awaiting Tim red-pen
**Date:** 2026-04-17
**Bead:** `boulderroller-v2-flqu` (X2)
**Audience:** Founding, mobile, protocol
**Deadline anchors:** Colosseum Frontier submission May 11, 2026 · Narrative freeze by Apr 28.

---

## 1. Framing

The demo has two overlapping audiences:
- **Colosseum Frontier judges** evaluating a Solana-native consumer product.
- **Solana Mobile Builder Grant** reviewers evaluating the Seeker/MWA integration story.

Both want the same thing: a 60–90 second narrative where a rider does a ride, the protocol attests it, and the rider verifies the outcome on-chain independently. The beats must feel like **fitness-first software where the crypto disappears into correctness** — not a wallet demo that happens to involve cycling.

Tagline (PROTOCOL_TRUTHS aligned):
> "That hill you climbed 100 times? Stake in it and earn from everyone else who climbs it."

---

## 2. Demo principles

- **Show, don't narrate.** Every claim ("CAL credited", "on-chain", "attestation stamped") must be visible on screen within 2 seconds of the claim.
- **Lead with the ride, close with the verification.** The crypto is the payoff, not the opener.
- **Fitness-first vocabulary at every rider-visible surface** (MOBILE_TRUTHS §12). The word "Ride" appears. The word "workout" does not.
- **Arrow of truth is visible.** The rider records → the device attests → the chain confirms → the rider verifies. Any beat that reverses or collapses this arrow gets cut.
- **No fake data paths.** Every tx signature, every CAL amount, every on-chain value is real devnet output captured in the demo session.

---

## 3. Beat-by-beat narrative (target 75 seconds)

### Cold open · 5s · tagline + climb silhouette

Static card, voiceover tagline. Camera cut to a hand holding a Seeker on a bike.

### Act 1 — the honest witness · 25s · mobile recording

| Beat | Screen | Enabled by |
|------|--------|-----------|
| Rider opens BoulderRoller on Seeker, MWA wallet already connected | HomeScreen, rides list showing prior rides | `5hdl.4` M4 (landed) |
| Rider taps Record, starts riding a climb | RecordScreen: live GPS + live power meter numbers | existing recording + `5hdl.2` M2 BLE (in flight) |
| Short b-roll of the ride in motion, 5–10s | map polyline building, metrics ticking | existing |
| Rider hits Stop | transient PostRideScreen — summary stats | existing + M1 clock-domain hygiene |
| Caption on screen: "Attestation stamped on device" | brief on-screen chip showing parser_version + preliminary hash short-form | attestation lineage (landed earlier) |

### Act 2 — the backend attests · 20s · backend → on-chain

| Beat | Screen | Enabled by |
|------|--------|-----------|
| Cut to a laptop view of BoulderScan or a tx explorer | tx in-flight, state "attesting" | existing BoulderScan |
| Backend recanonicalizes, compares preliminary hash — match ✓ | visible "hash verified" banner in the admin/explorer view | backend preliminary-hash handshake (landed 2026-04-17) |
| RideAttestation PDA committed on-chain | Solscan tx page | V4-A `credit_cal` tied to RideAttestation |
| CAL credited to rider's wallet | CAL balance increments on-screen | V4-A live |
| Climb completion recorded, Record Board potentially updated | vault/climb page | V4-A live |

### Act 3 — the rider sees the protocol · 15s · back to mobile

| Beat | Screen | Enabled by |
|------|--------|-----------|
| Cut back to Seeker | HomeScreen — new ride at top with "Synced" badge | `5hdl.4` M4 (landed) |
| Tap into ride detail | RideDetailScreen — processing stages all green, CAL earned number visible | `5hdl.4` M4 + existing PostRideScreen components |
| Wallet screen → Protocol Wallet (MWA) | sign-memo flow confirmable live | `5hdl.5` M5 (landed) |

### Act 4 — the rider verifies · 10s · independent verification

| Beat | Screen | Enabled by |
|------|--------|-----------|
| Rider taps Solscan link from wallet screen | Solscan page showing the attestation tx | `5hdl.5` M5 (landed) |
| Caption: "This isn't my app telling me I earned. This is Solana telling me." | sticky text over Solscan | narrative only |

### Close · 5s · tagline reprise

Tagline appears over a slow dolly-out of the climb. Fade to project name + Colosseum / Solana Mobile credits.

---

## 4. Epic → beat mapping

| Demo beat | Portfolio epic / bead | Status |
|-----------|----------------------|--------|
| HomeScreen rides list with Synced badge | `5hdl.4` M4 | ✅ landed |
| RideDetailScreen with stages + CAL earned | `5hdl.4` M4 | ✅ landed |
| MWA connect on Seeker + Solscan link | `5hdl.5` M5 | ✅ first slice landed; physical Seeker verification needed (Alexei) |
| Live power meter during recording | `5hdl.2` M2 BLE | ⏳ in flight (3-4 wk) |
| FIT export with sensor data | `5hdl.3` M3 | ⏳ gated on M2 |
| Preliminary-hash handshake on upload | backend handshake (landed today) | ✅ landed |
| On-chain RideAttestation + credit_cal | V4-A (protocol agent) | ✅ live on devnet |
| Climb completion + Record Board write | V4-A | ✅ live |
| Climb-first API vocabulary in BoulderScan | `mfab.5` Phase A + `kaol` portal rename | 🟡 backend landed, portal pending |
| `finalized_at` visibility on settled rides | `mfab.2` B3 | ⏳ queued |

---

## 5. Gaps and risks

### Must-close before demo day

1. **BLE sensor data in the demo recording.** Without M2, the recorded ride's power column is null and the backend estimates TSS. Demo either:
   - Waits for M2 (4-week runway; tight against May 11), or
   - Shows GPS-only recording with an on-screen annotation ("power meter pairing in roadmap"), which is honest but weaker for the grant narrative.
   - **Recommendation:** commit to M2 power-first at minimum (~2wk) for the demo; HR and cadence can be staged cuts.

2. **Physical Seeker verification.** `5hdl.5` M5 flagged four items needing physical device testing (Seed Vault double-tap UX, MWA authorize against Seed Vault, `isSeedVaultAvailable(true)` on Seeker firmware, memo tx landing on devnet from Seeker). Route to Alexei soon so fixes land before rehearsal.

3. **Demo devnet state must be reproducible.** A pre-staged devnet wallet with a known prior ride history makes the HomeScreen "existing rides" beat visually stronger. Need a one-shot script that seeds this state before each rehearsal.

### Nice-to-have, can cut

- **Settlement Week / DUNG distribution narrative.** Shows richer economics but adds 30s+ to the demo and depends on Phase B backend work (`mfab.3`, `mfab.4`). Save for post-hackathon video.
- **Vault staking demo moment.** Staking UX is deferred per portfolio; attempting it in the demo would expose gaps.
- **Multiple riders bumping the Record Board.** Narrative is great but requires two scripted devices or simulated traffic.

### Don't attempt

- **Real-time on-chain balance display in the mobile app.** Blocked on `wdvr.6` read-layer work. The demo shows CAL via the backend `/rides/{id}` response, not via a direct RPC read.
- **VerifyChip on ride detail.** Designed in crosswalk, blocked. Deferred.

---

## 6. Rehearsal schedule

| Date | Milestone |
|------|-----------|
| Apr 22 (protocol agent thaws) | Demo script locked as shape; content may still shift |
| Apr 28 | **Narrative freeze.** No new beats after this. |
| May 1 | First full dry-run on Seeker. Catch latency / UX jank. |
| May 4 | Second dry-run with final copy and timing. Record draft video. |
| May 6-10 | Polish video, prepare README / pitch deck. Only regression fixes in code. |
| May 11 | Submit. |

---

## 7. Setup checklist (pre-rehearsal)

- [ ] Seeker device provisioned with latest EAS build (`docs/design/SOLANA_MOBILE_BUILD_NOTES.md`)
- [ ] Devnet wallet seeded with prior ride history (history visible on HomeScreen opener)
- [ ] Seeker wallet has enough devnet SOL for MWA signing
- [ ] BoulderScan tab pre-loaded in browser for Act 2 cut
- [ ] Solscan devnet pinned for Act 4
- [ ] Power meter (or simulator) paired and live before recording
- [ ] Pre-recorded backup ride file (in case live GPS misbehaves)

---

## 8. Open questions for Tim

1. **Recording venue** — live outdoor ride on Seeker with real climb, or studio setup with simulated GPS? Real is stronger narratively; studio is more reliable.
2. **Voice over vs. captions** — voice is warmer, captions are more accessible and survive muted autoplay.
3. **Grant video vs. hackathon video** — same 75-second cut or two edits? Mobile Builder Grant video may want more Seeker close-up; Colosseum video may want more climb / economy framing.
4. **Cut Act 2 backend-screen moment?** — Showing the laptop breaks the mobile-native feel. Alternative: have the mobile app reveal the on-chain confirmation via a push (blocked on `3C` push infra from the audit). Or compress Act 2 to a single Solscan cut with voiceover.

---

## 9. Canonical summary

The demo narrative is:
1. Rider records honestly on a mobile device (MOBILE_TRUTHS §1 North Star).
2. The device attests the ride (MOBILE_TRUTHS §6).
3. The backend translates the attestation into protocol commitments (BACKEND_TRUTHS §1).
4. The chain confirms. The rider verifies independently (FIX_PLAN P13).

Every beat must hold that arrow. Every beat must be visible on screen. Every claim must be real devnet data.

The demo ships when: it holds TRUTHS, fits in ~75 seconds, and can be rehearsed end-to-end without a hand of God.
