# Boulder Roller Mobile — Felt Experience Spec

**Status:** HISTORICAL — earlier mobile experience and demo plan
**Date:** 2026-04-16
**Audience:** Mobile build (this agent), design, founder
**Purpose:** Lock the human experience the mobile app must deliver, and the demo arc the hackathon will be judged on. Sits *under* `docs/PROTOCOL_TRUTHS.md` and *above* the crosswalk and code.

Current native experience authority is [MOBILE_DESIGN_CONSTITUTION.md](MOBILE_DESIGN_CONSTITUTION.md) under [MOBILE_TRUTHS.md](../MOBILE_TRUTHS.md).

If the crosswalk or implementation conflicts with this document, this document
wins on what the rider feels, and the implementation must bend to it.

---

## 1. North Star

The mobile app exists so a rider finishes a climb and **feels something true**.

Not "feels rewarded." Not "feels gamified." Feels that the hill they just rode
mattered, that the protocol noticed, and that the moment they earned is now
permanent and theirs.

The protocol is climb-first. The mobile app is **moment-first**. Everything
else (verification, balances, archetypes, leaderboards) serves the moment.

---

## 2. The Demo Arc

There is exactly one arc the hackathon judges on, and exactly one arc we
engineer toward for May 11. Everything outside it is post-hackathon.

```
Open app → Record → Climb a real hill → Finish → Cascade → Attested
```

**Five beats, in order:**

1. **Open** — known sensors reconnect silently, last ride state is intact, no
   loading spinner is the first thing the rider sees.
2. **Record** — GPS is honest, BLE sensors stream cleanly, the screen is calm,
   the rider can put the phone away.
3. **Finish** — stop is decisive. A preliminary `ride_hash` is computed locally
   and stamped before the upload leaves the device. The rider sees an
   "uploaded" state within one second.
4. **Cascade** — the Boulder Rolled celebration. Fortnite-soft. Level delta
   inline with the reward lines. CAL Tribute Cascade animates 1→N for vaults
   the ride paid tribute to. Best Placings cascade after. This is the moment.
5. **Attested** — the cascade resolves into a quiet, permanent state: the ride
   is on-chain, the RideAttestation exists, the rider's claim is binding. No
   toast. The cascade itself was the resolution.

**If any beat fails to land, the demo fails.** Engineering priorities flow
backward from this arc.

---

## 3. The Three Phases of a Ride

The protocol gives us three states for a finished ride. The UI must honor them
as **felt tension and release**, not as status text.

| Phase | Felt as | Visual treatment |
|-------|---------|------------------|
| **Uploaded** | "It went out." | Cascade begins. Provisional CAL shown in dim color. |
| **Provisional** | "It's being checked." | Numbers shimmer or breathe. Verify state is *implicit*, not chip-shaped. |
| **Attested** | "It's mine forever." | Numbers settle into permanent style. One small mark — only here. |

The verify chip lives **only at the attested moment**, and **only on identity-
binding surfaces** (BeetleCard, Boulder Rolled hero stat). Everywhere else, the
rider trusts the cache and we trust the chain underneath.

This is the rule: **verification is a beat, not a chip.**

---

## 4. What Stays Invisible

Things the rider must never see, even if engineering wants to surface them:

- The word "attestation" outside developer telemetry.
- The phrase "on-chain" outside the BeetleCard provenance line.
- IDL version numbers, parser versions, hash bytes.
- The SQL projection vs chain-read split. The rider sees one number.
- Verify chips on cached/projected values (map, history, browse).
- Loading spinners on the post-ride cascade. The cascade IS the load.

Things the rider must always feel:

- Sensors are honest. If a sensor dropped, say so. If GPS went stale, say so.
- The ride is decisive at stop time. No "processing" purgatory.
- The cascade is the payoff. The cascade is the proof.

---

## 5. Hackathon Scope Cut

**In scope (engineered for May 11):**

- The five-beat demo arc, end to end, on devnet, on a real ride.
- BeetleCard with one verified-from-chain stat (CAL balance) at the attested
  moment.
- Boulder Rolled cascade with three-phase resolution.
- Recording surface obligations 1, 3, 4, 5 from the crosswalk (canonical
  reproducibility, parser_version stamp, GPS integrity, crash-recovery
  integrity).
- Preliminary hash bridge wired to backend.
- Compatibility lane preserved — SQL projection still reads, chain overlays
  only where the spec demands.

**Out of scope (post-hackathon):**

- Full Economy tab parity with portal.
- Profile "Verify all" sweep.
- UniFFI native canonicalization (Phase C).
- Rider archetype matchup mechanic UI (the data model can land; the screen
  doesn't ship for the demo).
- V4-A → V4-B rename sweep beyond what the demo arc touches. Coordinate with
  protocol agent's `0uv8` migration; do not run ahead.

---

## 6. The One Felt Failure Mode

The thing we are most likely to ship and most likely to regret is a verify
chip on every number on every screen. It will look like progress and feel like
a developer dashboard.

If a designer or engineer reaches for a chip, the question is: **does this
surface bind identity or settle a claim?** If no, the chip does not belong.

---

## 7. Build Sequence (gates, not phases)

Each gate is a screen recording of a real ride on devnet. Tests pass is not a
gate. Demo state is the gate.

1. **Gate M1 — Recording is honest.** A real ride produces a canonical
   `ride_hash` that re-canonicalizes bit-for-bit on a second pass. parser_version
   is stamped. GPS staleness and sensor dropouts are surfaced.
2. **Gate M2 — Stop is decisive.** Preliminary hash is computed at stop time,
   stamped on the upload, and the backend confirms the match.
3. **Gate M3 — Cascade lands.** Boulder Rolled animates the three phases —
   uploaded, provisional, attested — driven by real backend + chain state, not
   mock timers.
4. **Gate M4 — Verification binds identity.** BeetleCard shows CAL balance
   read from chain via Privy wallet, with the verify mark appearing only at
   the attested moment.
5. **Gate M5 — Demo arc.** The five beats run end to end, on devnet, in one
   take, on a real ride. This is the hackathon submission.

Anything not on this list is not on the critical path. File it and move on.
