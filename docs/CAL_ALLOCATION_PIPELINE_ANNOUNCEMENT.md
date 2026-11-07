# The Climb Just Got Real: Boulder Rollers Allocation Pipeline

**How we're turning every pedal stroke into verifiable on-chain economics**

> **⚠ HISTORICAL ANNOUNCEMENT — Pipeline architecture has changed.**
> This post describes the Merkle-batched CAL allocation pipeline from an earlier protocol generation. As of the V4-A coherence redeploy (2026-04-15), Merkle-batched claims have been replaced with direct `credit_cal` instructions tied to on-chain `RideAttestation` objects. See `docs/PROTOCOL_TRUTHS.md` and `docs/design/PROTOCOL_ALIGNMENT_FIX_PLAN.md` for the current model. The narrative framing below about earning from geographic routes remains accurate; the specific pipeline mechanics described are historical.

---

You know that hill you've been grinding all winter? The one where you know every pothole, every false flat, every place the wind hits you sideways?

What if every time someone else climbed it, you earned from it?

That's Boulder Rollers. And we just shipped the infrastructure to make it actually work.

---

## What we built: the CAL Allocation Pipeline

Until now, rides earned points. Simple counter. Goes up when you suffer on the bike.

That era is ending.

We just deployed a Merkle-batched token allocation system that takes your ride data — your TSS, your effort, the vaults you crossed — and converts it into cryptographically verifiable claims on Solana.

Here's the flow:

```
You ride → TSS computed → CAL earned
                        → CAL tributed to every vault you crossed
                        → Vaults accumulate → Weekly distribution → DUNG to stakers, legends, and leaderboard
```

Every step is provable. Every claim has a Merkle proof. No trust required.

---

## Why Merkle trees matter (and why you should care)

Old system: backend says "you earned X points." You trust us.

New system: backend builds a tree of every rider's allocation for the epoch. Publishes the root on-chain. You can independently verify your leaf exists in that tree and claim your tokens yourself.

We run a convenience executor that claims on your behalf. But you don't need us. The contract is permissionless. Your proof is your proof.

This is what "don't trust, verify" actually looks like for fitness data.

---

## The vault economics are live

Every vault — every climb segment fingerprinted with a 64-byte signature — is now a miniature economy:

- **55%** of rewards go to the top 10 leaderboard (fastest times, all-time)
- **27%** goes to stakers (people who locked CAL into the vault)
- **3%** to the Local Legend (most completions, elected every 8 epochs)
- **5%** protocol-owned liquidity
- **10%** treasury

Beat someone's time? You bump them off the leaderboard. They stop earning. You start.

Stake CAL in a vault you believe in — one with traffic, one with a devoted community — and earn DUNG proportional to your share.

The more riders a vault attracts, the more it earns. The more it earns, the more stakers want in. Flywheel.

---

## What's different about this approach

Most "move-to-earn" projects mint tokens from thin air and pray the music doesn't stop.

We took a different path:

- **CAL is effort-based.** You earn it from TSS (Training Stress Score) — the same metric used by TrainingPeaks and elite coaches. You can't fake watts.
- **DUNG is value-based.** Fixed 1B supply. Only minted through vault distributions. Halving schedule on emissions.
- **Vaults are geographic.** They're real climbs, real roads. The signature is derived from gradient profile, distance, and elevation — not GPS coordinates. You can't game it by driving.
- **No vesting.** When TGE happens, tokens are liquid. Hyperliquid model. We think the community earned it.

---

## Shadow mode is live

Right now the full pipeline runs in shadow mode alongside the points system. Every ride triggers the allocation logic, builds the Merkle batch, and logs what *would* happen on-chain.

We're watching. Tuning. Making sure the math holds at scale before we flip the switch.

When we do, your points convert to DUNG, CAL starts flowing, and the vaults go live for real.

---

## For the builders in the back

The technical stack, if you're curious:

- Anchor programs on Solana (devnet, battle-tested with 80+ on-chain tests)
- Merkle-batched SPL token claims (submit root → individual claims with proofs)
- Synthetix-style staking (continuous reward accrual, harvest anytime)
- PDA-controlled mint authorities (program owns the mint, not a multisig)
- Full E2E test coverage including `distributeEpochRewards` and `harvestRewards` — instructions that had never been tested on localnet until this week

We also shipped deployment scripts with dry-run defaults and irreversibility warnings. Because transferring mint authority to a PDA is a one-way door, and we respect one-way doors.

---

## What's next

- Monitor shadow mode through a full epoch cycle
- Validate on devnet with the deployment script sequence
- Flip `CAL_ALLOCATION_MODE=batch` when we're confident
- TGE when the community is ready (you'll know)

---

## The pitch hasn't changed.

That hill you climbed 100 times? Stake in it and earn from everyone else who climbs it.

We just made the "earn" part real.

---

*Boulder Rollers — where suffering on the bike is a financial strategy.*
