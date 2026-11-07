# Tokenomics & Upgrades - Original Notes

**Source:** Brainstorm session with friend
**Date:** December 2024

---

## Original Proposal

### Core Goals

- Make DUNG a meaningful sink: upgrades/equips cost DUNG, with escalating costs and optional cooldowns.
- Gate power by achievements/segments, not just spend: unlock tiers via on-chain or verifiable achievements (rides, segments, streaks).
- Preserve flexibility: upgradable NFTs without inflationary emissions; upgrades mutate the NFT state instead of minting more supply.

### Architecture (Solana)

Use pNFTs (Metaplex Programmable NFTs) or a custom program with:
- Item accounts storing: level, tier, XP, equipped slots, bound player wallet.
- Achievement registry: merkle or PDA-based proofs of achievements (e.g., segment completions, streaks). Could be issued as SBTs or stored as PDAs keyed by wallet.
- Upgrade instruction: checks item ownership/binding, verifies achievement gates, burns/escrows DUNG fee, bumps level/tier, updates item metadata (off-chain metadata URI or on-chain data).
- Equipment slots: either a "character" NFT with slot state (helmet/frame/tires) or pure cosmetic badges. Slotting costs DUNG and may require achievements per slot.

Custody: player holds the pNFT; upgrades are recorded on-chain; DUNG is transferred/burned in the upgrade instruction (recommended: burn to a burn address or send to a treasury vault + periodic burn %).

### Tokenomics Mechanics

**Sinks:**
- Upgrade costs: escalating (e.g., level N cost = base * growth^N). Early levels cheap, later levels expensive to curb whales.
- Slot unlock costs: pay DUNG to unlock additional equip slots or cosmetic layers.
- Rerolls/resets: optional DUNG cost to respec or reroll minor attributes.
- Crafting/combining: fusing two items into a higher tier consumes both + DUNG.
- Cooldowns: optional DUNG to speed up upgrade cooldowns; otherwise time-gated to prevent spamming.

**Gates:**
- Achievement thresholds: segment completions, weekly streaks, ride volume (kcals/TSS), leaderboard ranks. Upgrades require both gate + DUNG, so spend alone isn't enough.
- Rarity caps: certain tiers only if achievement SBTs are present; SBTs are non-transferable to avoid selling progress.

**Emissions:**
- Keep DUNG emissions on a decay schedule; don't print extra for upgrades. Upgrades are net sinks.
- If you do loot drops: emit new NFTs through achievements/season rewards, not by DUNG spend alone.

### Progression Model

- Item levels: 1–10 (or more) with exponential DUNG costs; each tier adds modest performance/cosmetic changes to avoid runaway power creep.
- Achievements as gates: e.g., Level 3 requires "Ride 100 km/week" badge; Level 5 requires "Complete 10 segment challenges"; Level 7 requires "Top 10 on a segment" SBT; etc.
- Cooldowns: 12–24h between upgrades unless paying a smaller DUNG fee to skip (tune carefully to avoid P2W).

### Economic Controls

- Burn vs treasury: Burn a % of DUNG spent on upgrades (e.g., 50–80% burn, rest to treasury/ops). Adjust burn fraction via governance.
- Caps per epoch: limit total upgrade throughput per wallet/day to prevent heavy extraction or market shocks.
- Dynamic pricing (optional): If DUNG price pumps/dumps, you can adjust base costs per season via governance—but avoid frequent changes.

### Governance and Safety

- Multisig + timelock controls:
  - Upgrade cost parameters, burn %, growth rate.
  - Achievement gate definitions (ideally stored on-chain and versioned).
  - Treasury spend routes.
- Transparent schedules: publish seasonal parameters; don't change mid-season unless for critical fixes.

### Suggested Defaults (Original)

- Cost curve: cost(N) = 50 * 1.6^(N-1) DUNG (rounded).
- Slot unlocks: 100 / 250 / 500 DUNG.
- Reroll/reset: 30 DUNG + 20% burn (optional).
- Burn/POL split: 60% burn, 40% to POL.
- Cooldowns: 12–24h; optional skip fee (tune carefully).
- Rate limits: e.g., 3–5 upgrades/day/wallet.
- Gates (examples): L3 "100 km/week"; L5 "10 segment challenges"; L7 "Top 10 segment"; L9 "30-day streak"; slots can require specific badges.

---

## Flow Summary

1. Auth/Seed: On first auth, create user_state with cal_balance=2500, next_cal_airdrop=now+24h.
2. Upload: No CAL pre-charge; ride processes; kcals deducted post-processing (clamped, never blocks).
3. Upgrade: Check ownership/binding, achievements, cooldown, rate limit; charge DUNG; burn/POL split; update item state; emit events.
4. POL: Vault accumulates DUNG; when threshold (e.g., 5k DUNG) hit, swap half to USDC via TWAP, LP into DUNG/USDC. Tunable thresholds/splits/pools.
5. Seasonality: Set parameters per season; avoid mid-season changes unless critical; publish cost curve, burn/POL split, gates, cooldowns, POL ops.

---

## Solana Layout (Sketch)

- Item pNFT: level/tier/slots/cooldown/bound wallet in PDA.
- Achievement registry: PDAs/SBTs keyed by wallet; upgrade verifies required keys.
- Upgrade program: inputs (item, owner, payer, achievements, DUNG account, burn address, POL vault); checks (gates, cooldown, rate limit); actions (transfer fee, burn %, send POL %, update state, emit events); optional cooldown skip fee.
- POL vault: PDA holding DUNG/USDC; off-chain cron/TWAP (or on-chain instruction) to swap + add LP.
- Governance: Multisig + timelock to change cost params, burn/POL %, thresholds, gate registry, POL pool targets.

---

## Anti-Exploit Notes

- Rate limits per wallet/day
- Cooldowns
- Non-transferable achievements
- Transparent POL events
- Tunable burn/POL split

---

## CAL Specifics (Aligned)

- Seed 2500 CAL + 24h timer on signup.
- Deduct post-ride by kcals burned; clamp to balance (no hard fails).
- Daily airdrop via Celery on next_cal_airdrop <= now; set next_cal_airdrop when missing.
- CAL remains off-chain pacing only.

---

**Note:** These are the original brainstorm notes. See `TOKENOMICS_V2.md` for the finalized source of truth with updated parameters.
