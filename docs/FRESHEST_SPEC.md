# Boulder Rollers Internal Specification

**Document Version:** 2.12
**Last Updated:** October 13, 2026
**Status:** ACTIVE — protocol live on devnet, product live in production, zero-start posture
**Audience:** Internal engineering, product, and founding team

> **Protocol is LIVE on devnet; product is LIVE in production** (`boulderroller.xyz`, `api.boulderroller.xyz`). On-chain Climb completions, direct CAL credit and vault tribute, Settlement Week finalization, staking, and harvest are operational. Shadow mode has been removed; live is the only code path. The TS indexer streams PDA changes to indexed tables, and the API reads from chain-indexed state.
>
> **Zero-start (ratified 2026, reaffirmed 2026-07-05):** There is no TGE. No token generation event is planned, dated, or used as a horizon. DUNG receipts are permanent on-chain records, not money; no liquid market exists or is scheduled. Any future liquidity decision is trigger-based (demonstrated demand), never date-based. Liquidity-era designs are preserved in the [Frozen Design Inventory](#13-frozen-design-inventory) as working sketches, not commitments.
>
> **State note (2026-07-05):** V4-B ontology lift (Climb/Vault split, RideAttestation, RiderSoul) tracked under `wdvr.7`. Canon-first climb identity ratified 2026-07-04 (epic `boulderroller-v2-4crx`): the climb canon is compiled from OSM + DEM; rides are evidence, not identity. First Cohort (epic `boulderroller-v2-klrj`) is the product spine: real Philadelphia riders completing the full loop weekly. Brand is Boulder Roller / CAL / DUNG — a previously sketched "Motion/MOMO" rebrand was rejected and removed from this spec.
>
> **Math-remediation policy (ratified 2026-07-13; supply authority clarified 2026-07-16):** Settlement Weeks hand off Monday 12:00 UTC and finalize after 24 hours; Vault tribute is a lifetime tribute flow meter credited to the oldest open Settlement Week; accepted records retain original `completed_at` provenance under the 30-day ride guard; each week's locked staker share flows to that week's Record Royalty rather than retroactive carry; DUNG halves automatically every 26 Settlement Weeks and holds a 1-bps tail. Lifetime DUNG issuance counters enforce caps and are never reduced by burns; the configured SPL mint's exact supply is circulating authority, while `DungMintState.total_burned` records only Boulder Roller program burns. The Monday clock contract is landed, but deployed clocks still require the cutover runbook; same-week staker flow remains tracked by `scur`.
>
> **Hill-bonding amendment (6–13 Oct 2026):** [§1a](#1a-hill-bonding) records the ratified prospective product rules and their sources. The older economics above and below remain readable as CAL-vault history and liability rules; the supersession table in §1a identifies their replacements for bonded hills. When ratified, the deployed devnet program was the CAL-vault model ([readiness checklist, item 1][HB-READY]). **Since 18 Oct 2026 the devnet program is the stage-1 build (program version 77), for rehearsal only; production keeps stage 1 off for riders.** The stage-1 spec supplies the reference behavior ([STAGE1_SPEC][HB-S1]).
>
> **Co-KOM policy (ratified 2026-07-21; implementation pending):** The ratified target makes every seated rider tied at the fastest validated whole-second time a co-KOM and gives each a crown plus `T-1` on detailed rider surfaces. Standard competition ranks, the ten-seat bound, and pooled payout percentages and bytes remain unchanged. The singular on-chain `kom_holder` becomes only a deterministic legacy representative selected by earliest original ride `completed_at`, then wallet bytes; it adds no payout or sole sporting meaning. A strictly faster time replaces the full prior co-KOM set. These recognition and representative changes are not yet live. Metadata stewardship remains a separate Local Legend concern, and the current V4-A post-Founder metadata coupling to `kom_holder` is transitional rather than canonical. Because rotating the scalar today would also transfer live metadata authority, the separately ratified metadata-authority/ABI rollout is a hard prerequisite before `izuhd` may rotate `kom_holder` for an equal-fastest ride.

---

## Executive Summary

The following is retained CAL-vault product framing. The ratified hill-bonding
launch and product rules are in [§1a](#1a-hill-bonding); this historical framing
does not define its funding or payout promises.

**"Putting a dollar value on a calorie."**

Boulder Rollers is a decentralized cycling economy where physical effort has dollar value. Athletes earn tokens by completing verified climbs and efforts, stake tokens on geographic routes ("vaults"), and compete on permanent leaderboards.

**Core Value Proposition:**
- That hill you climbed 100 times? Stake in it and earn from everyone else who climbs it.
- Geographic routes become investment assets.
- Permanent on-chain records that cannot be deleted by any corporation.

**Target Market:** Serious, data-driven cyclists with TrainingPeaks-quality analytics expectations and a crypto-economic layer that rewards performance.

---

## Table of Contents

1. [Current State: Protocol Live on Devnet](#1-current-state-protocol-live-on-devnet)
   - [Hill Bonding](#1a-hill-bonding)
2. [Two-Token Economy](#2-two-token-economy)
3. [Vault System](#3-vault-system)
4. [Distribution Model](#4-distribution-model)
5. [Local Legend System](#5-local-legend-system)
6. [BeetleCard System](#6-beetlecard-system)
7. [Staking Mechanics](#7-staking-mechanics)
8. [Supply and Emissions](#8-supply-and-emissions)
9. [DUNG Demand & Sustainability Model](#9-dung-demand--sustainability-model)
10. [Anti-Cheat](#10-anti-cheat)
11. [Technical Reference](#11-technical-reference)
12. [Appendix: Document Deprecation](#12-appendix-document-deprecation)
13. [Frozen Design Inventory](#13-frozen-design-inventory)

---

## Implementation Status Legend

This spec documents both **implemented** and **planned** features. Status indicators:

| Symbol | Meaning |
|--------|---------|
| ✅ | Live on devnet |
| ⚠️ | Planned but not yet implemented in code |
| 🔧 | Tunable parameter (governance lever) |
| ❄️ | Frozen — preserved design, not active roadmap (see [Frozen Design Inventory](#13-frozen-design-inventory)) |

> **Philosophy:** This spec is honest about gaps between vision and implementation. Code is source of truth for what exists; this doc is source of truth for where we're heading.

---

## 1. Current State: Protocol Live on Devnet

### Status: LIVE

The protocol is **live on Solana devnet**. The CAL-vault pipelines below are
operational; the ratified hill-bonding module in §1a is not deployed:

| Pipeline | Status |
|----------|--------|
| On-chain Climb completions | Live — rides fire completion instructions |
| Direct CAL credit | Live — `record_ride` → `credit_cal` mints to the rider ATA through a RideAttestation receipt |
| CAL tribute to Vaults | Live policy being corrected forward-only to measured Climb TSS; deployment remains gated |
| Settlement Week finalization | Live — V4-A finalization via `distribute_epoch_rewards(settlement_week, ...)` after 24h grace window |
| Staking (deposit/withdraw) | Live — V4-A Vault-centered |
| Harvest (collect rewards) | Live — `rewards_earned` → rider ATA (`unclaimed_rewards` is the V4-B target name) |
| Local Legend elections | Live — most completions in the term wins the rolling seat |
| Indexer | Live — TS indexer streams PDA changes to `indexed_*` tables |
| Detection engine | Live — canonical_v2 (F1≈0.78). **Tuning FROZEN**; identity moves to map-compiled canon per epic `4crx` |
| Boulder Roller Balance | Live in production — staged rollout (`collect_dung`, internal cohort); see `docs/runbooks/BALANCE_PRODUCTION_ROLLOUT.md` |

Shadow mode has been removed. Live is the only code path.

### Product Surfaces

| Surface | Role |
|---------|------|
| Public root + app (`boulderroller.xyz`) | Cycling app — ride uploads, matched climbs, CAL counted, Balance actions |
| API (`api.boulderroller.xyz`) | Production backend |
| BoulderScan (`scan.boulderroller.xyz`) | Power tool — on-chain state, PDA accounts, tx history, supply metrics |

See `docs/design/LANGUAGE_SPEC.md` for user-facing terminology.

### Zero-Start Posture (No TGE)

There is **no TGE**. The economy launches with full on-chain truth and real scarcity but **no liquid market**: status before liquidity. What riders accumulate — record-board seats, Local Legend terms, DUNG receipts — is permanent and provable, which is the product. This posture simultaneously minimizes fraud incentive (nothing to sell), sharpens the securities position (effort-earned, non-liquid, no investment expectation), and defers audit spend to when real value is actually at stake.

Any future liquidity decision is **trigger-based**: observable evidence that participants covet what is scarce. It is never date-based, and no roadmap, doc, or rider surface may present a TGE as a horizon. Liquidity-era mechanics (allocation sketch, rake flywheel, buybacks, governance) are preserved in the [Frozen Design Inventory](#13-frozen-design-inventory).

The **13 Oct 2026** immediate-sale decision applies once CAL is tradable; it
does not create a market or a launch date. Stage 2 still waits for actual CAL
buyers, so the no-market posture above and the sale option in §1a describe
different states. Market language needs Jon's review before any public
promotion. [Sources: DIAMOND, Markets and whales][HB-DIAMOND];
[DESIGN, Stage 2][HB-DESIGN]; [CHECKLIST item 12][HB-READY].

### Product Spine: First Cohort

The organizing frame for all product work is epic `boulderroller-v2-klrj`: real Philadelphia riders complete the full loop weekly (invite → sign in → ride → Counted → Collect DUNG → weekly receipts). **Philadelphia is the first city, not the only one** (ratified 2026-10-06, replacing "Philadelphia is the product"). The no-money part of the loop is not limited by city: records and the Local Legend can run wherever canon compiles without requiring a hill to bond — this is the direction; records currently show only on climbs with a live Vault (`backend/app/routes/climbs.py:667–675`). Anything that pays riders or holds backers' stake starts in Philadelphia, including the ratified hill-bonding direction in §1a. Only donated yield is live-gated: sponsor cash and boosts may pay a registered hill in a launched city even when the hill is non-live or unbonded (**ratified 13 Oct 2026**, [STAGE1_SPEC §§5, 9][HB-S1]). Demand is open everywhere: anyone can ask for a hill and say what they would stake, no money moves until counsel clears public deposits, and those asks decide where canon is compiled next. Money opens in another city when its canon is ready and enough of its hills reach the bonding line, the escrowed backing threshold for bonding; that line is not a prerequisite for sponsor-cash or boost pay on every hill in a launched city. The end state is a zero-start loop that opens itself wherever its ingredients exist (canon, riders, a local backer whose pledge reaches the line, and permission to pay riders), with no step needing BoulderRoller by hand. Progress toward it is measured by the steps a new place still needs from us. Permission is the one ingredient code cannot compile; it is settled per jurisdiction. Every pipeline stays city-agnostic: Philadelphia-specific hand-craft is a design error. Product filter for design decisions: *does it make the hill matter more?*

---

## 1a. Hill Bonding

### Authority and delivery state

The [diamond principles][HB-DIAMOND] and [diamond.yaml][HB-PARAMS] are the
single origin of hill-bonding rules and parameters. This section projects them
at product level; [PROTOCOL_TRUTHS §16](PROTOCOL_TRUTHS.md#16-hill-bonding)
records roles, money, custody and permanence. Sources are the [settled calls
in DESIGN][HB-DESIGN], [STAGE1_SPEC][HB-S1], [STAGE1_PLAN][HB-PLAN],
[FUNDING][HB-FUNDING] and [CHECKLIST][HB-READY]. Explicit later ratifications
and their resolutions of older source wording are cited below.

- **Deployed — devnet rehearsal only.** The checklist's 8 Oct observation and
  the [13 Oct brief][HB-BRIEF] identify the devnet program of that time as the
  earlier CAL-vault model. On 18 Oct 2026 devnet was upgraded to the stage-1
  build (program version 77); production keeps stage 1 off for riders. **Ratified 13 Oct 2026,
  local/offline only:** STAGE1_SPEC §§1–9 supplies an executable reference,
  not production custody, authentic riding, provider liquidity or authority
  proof. The plan's custody, allocation, integration, client, rehearsal,
  audit and mainnet milestones remain delivery gates. [Sources: STAGE1_SPEC
  introduction and §9; STAGE1_PLAN §7; CHECKLIST items 1, 3–4.][HB-S1]
- **Ratified prospective scope, 8 and 13 Oct 2026; cutover week open.**
  Only future bonded-hill issuance takes the new rules. Existing CAL principal,
  accrued DUNG, carry/claims and historical receipts retain their original entitlement;
  no old liability is rewritten into the new split or mint schedule. [Sources:
  DIAMOND, Settled on 8 October][HB-DIAMOND]; [STAGE1_SPEC §9][HB-S1]. The
  implementation plan uses a new versioned module attached to canonical hills
  and requires an explicit cutover Settlement Week before activation. Only
  that week's choice remains open; this amendment selects no week and executes
  no migration. [Source: STAGE1_PLAN §1.][HB-PLAN]

### Stage 1 launch and product rules

- **Ratified 6 Oct 2026; mechanics ratified 13 Oct.** Rehearse the entire
  pledge-to-payout loop on devnet with test SOL, then start money flows in
  Philadelphia. Its fixed city bonding line is 10 SOL per hill. Demand can
  come from anywhere; another city's money opens when its canon is ready and
  enough hills reach the line, subject to the existing admission gate. The
  no-money record/Local Legend direction remains available wherever canon
  compiles. [Sources: DESIGN, “Settled with Tim” (Cities, Bonding line);
  diamond.yaml `line_sol`; STAGE1_SPEC §§2–3.][HB-DESIGN]
- **Ratified 6 Oct 2026; custody mechanics ratified 13 Oct.** Pledges are
  escrowed. Before bonding, their earnings belong to the owner and cancellation
  returns that lot's actual assets, including its gains or losses. Crossing
  the line bonds atomically and locks all included pledges for 26 weeks;
  four weeks' notice starts only after the lock. Later deposits choose 0, 13,
  26 or 52 weeks, then the same notice. Bonded is permanent; live is measured
  at week opening and requires backing at least half the city line (5 SOL in
  Philadelphia). A partial bonding week's yield waits. [Sources: DESIGN,
  Bonding and settled calls; STAGE1_SPEC §§2–4.][HB-S1]
- **Ratified 13 Oct 2026.** Principal is deposit-time SOL redemption basis,
  returned in the deposited token, subject to the originating lot's losses.
  Only surplus units actually transferred into earnings custody count as
  realized yield; payouts are in kind and below-basis lots harvest nothing.
  A backer's USDC is converted to SOL exposure, not a USDC repayment promise;
  sponsor USDC instead funds riders directly. SOL/LST conversion, admitted
  mints and rate adapters still require implementation proof. [Sources:
  STAGE1_SPEC §§3–4, 9; DESIGN, USDC settled call (6 Oct).][HB-S1]
- **Ratified 13 Oct 2026.** Pilot caps are 2,000 SOL per staking token,
  500 per hill and 5,000 per deployment, with at least seven days before an
  increase; a replacement increase proposal restarts the delay. Reductions
  can block new intake without seizing existing positions. Caps are **running
  totals of deposit-time basis per staking token, hill and deployment**. The cap amounts
  and delay are in STAGE1_SPEC §3 and diamond.yaml `stage1.pilot_caps`.
  **Basis measurement source: Tim, 13 Oct 2026; STAGE1_SPEC amendment pending
  on branch `codex/boulderroller-v2-0jc1s-stage1-custody`**, recorded in the
  [authorities brief][HB-BRIEF]. This decision resolves the current §3
  rate-valued formula in favor of deposit-time basis totals.
- **Ratified 13 Oct 2026.** If an asset's rate has been stale for seven days,
  an owner past their lock and notice may exit in kind with **all of the lot's
  remaining tokens**, and unharvested yield leaves with them. **Source: Tim,
  13 Oct 2026; STAGE1_SPEC amendment pending on branch
  `codex/boulderroller-v2-0jc1s-stage1-custody`**, recorded in the
  [authorities brief][HB-BRIEF]. The current reference specification's ordinary
  harvest-before-exit path does not establish this exception's implementation.
- **Ratified 13 Oct 2026.** While a staking token's rate is stale, a hill's
  pledges in that token count as zero toward its bonding line instead of
  blocking other pledges or the bond, so one stale or delisted token cannot jam
  a hill. Lots in a token that is stale when the hill bonds are not founding
  lots; they stay cancellable, and once the rate is fresh their owner may
  convert them into ordinary stake with a chosen lock. **Source: Tim, 13 Oct
  2026, after the milestone 1a custody review; STAGE1_SPEC amendment pending
  on branch `codex/boulderroller-v2-0jc1s-stage1-custody`**, recorded in the
  [round 3 brief][HB-R3]. The offline reference and the localnet build still
  reject a stale rate here, so neither establishes this rule's implementation.
- **Split and yield-only fee scope ratified 6 Oct 2026; 10% rate and
  allocation mechanics ratified 13 Oct.** Riders receive realized yield
  after the fixed 10% protocol yield fee, plus sponsor cash with no deduction
  from the rider budget. Each available rider pot splits **65% by verified ascents,
  25% equally among occupied top-ten seats, 10% to the earned Local Legend**.
  Paid ascents are capped at one per person, hill and UTC ride day. A person
  may hold one board seat and the earned Legend role; their entitlements
  combine. No collection or withdrawal charge from the legacy CAL-vault
  model is added to stage-1 rider money. [Sources: DESIGN, Stage 1 and
  Founders; STAGE1_SPEC §§1, 4–5; STAGE1_PLAN §§1, 4.][HB-S1]
- **Service-fee direction ratified 13 Oct 2026; principle 7 wording pending
  Jon.** The company may charge for services outside the protocol, including
  running seasons and boosts, on top of, never out of, money for riders.
  Protocol sponsor-cash and boost budgets still pay no fee. [Source: FUNDING,
  Decision and option C.][HB-FUNDING]
- **Ratified 7 Oct 2026; claim treatment ratified 8 Oct; calendar and cap
  mechanics ratified 13 Oct.** Five distinct riders on the hill in a 26-week
  city season are required for its board, paid records and DUNG. Seasons
  share the city's launch anchor, with Monday 12:00 UTC weeks. Below the field,
  ascent pay can flow, record/Legend money waits, DUNG stays unminted, and
  stage-2 CAL claims wait with their share staying with every rider. Each
  person's combined positive weekly cash entitlement is capped at 3× the
  hill's median positive entitlement **per asset**, including paid inactive
  record holders. Excess goes by ascents to riders with cap headroom, then
  stays held; assets are not compared at an invented exchange rate. [Sources:
  DESIGN, Minimum field; DIAMOND, Settled on 8 October; STAGE1_SPEC §§2, 5.][HB-S1]
- **Ratified 6 Oct 2026; mechanics ratified 13 Oct.** Ordinary pay and DUNG
  use the upload week for rides at most seven days old; sporting provenance
  keeps the original ride time. Freeze seats and field at close, finalize
  after 24 hours in week order, and never reopen settled claim sets. Non-live
  yield, empty-seat money and cap excess retain source, asset and original age.
  After 26 weeks they become reserved for the shared pool; before that module
  exists they stay reserved. Assigned unclaimed rider money does not expire.
  [Sources: DESIGN, Late uploads/Stranded money; STAGE1_SPEC §§2, 5–6, 8.][HB-S1]
- **Ratified 15 Oct 2026.** Pay is sent automatically. Once a week is final,
  the keeper submits each registered rider's claim (cash at once, DUNG after
  48 hours) to the address they registered, then closes the week's records and
  recovers their rent. Riders sign only to register; claims stay permissionless
  and cannot be redirected. **Source: Tim, 15 Oct 2026; implementation pending
  on PR #96 and the keeper.**
- **Ratified 13 Oct 2026.** Boosts launch in stage 1 as fully escrowed,
  irrevocable USDC sponsorship for 1–13 future full riding weeks. Divide the
  budget equally across selected hills and ride weeks; use the normal split,
  field and per-asset cap, with no fee and no DUNG. Cash and boosts may pay
  non-live or unbonded hills in an admitted city. Qualifying uploads after the
  window can share the original ride week's budget only before its fixed
  close-plus-24-hour cutoff and within seven days of riding. There is no extra
  tail budget, reopening, refund or later unrelated rider claim; unused money
  waits for the 26-week pool fallback. [Source: STAGE1_SPEC §§5–6, 9;
  diamond.yaml `stage1.boosts` and `stage1.mechanics`.][HB-S1]
- **Ratified 6–8 Oct 2026; timing ratified 13 Oct.** DUNG is constant at
  **1 per 1,000 climb-TSS** on bonded hills, half to riders and half to
  backers. Riders' half splits **55% top ten / 35% ascents / 10% earned
  Legend**. Backers' weights use their active backing and chosen lock:
  0/13/26/52 weeks weigh 0.25/0.5/0.75/1.0; expired locks fall to 0.25.
  Founding pledges, including seed pledges, get **2× weight inside the fixed
  backer half** for their hill's first 26 full bonded weeks, not a larger mint
  and not a bonus truncated by the city season. The triggering backer is
  Founder, a title only with no paid Legend term. No DUNG is admitted below
  the field, in the partial bonding week, or for pre-bond riding; missed
  issuance and missing-recipient shares stay unminted. DUNG has no market
  under zero-start. [Sources: DESIGN, settled calls; DIAMOND, Settled on
  8 October; STAGE1_SPEC §7.][HB-S1]
- **Reference model: equal shares; not separately ratified.** The source
  text fixes DUNG's 55% top-ten bucket within the riders' half but does not
  specify its division among seats. The reference model's `_dung` uses equal
  seat weights. This does not separately ratify a replacement DUNG rank
  allocator. [Source: `tools/stage1_reference/model.py`, `_dung`][HB-MODEL].

### Later stages, markets and outstanding gates

- **Ratified 6 Oct 2026; field rule ratified 8 Oct.** Stage 2 waits for
  actual CAL buyers. CAL remains one per eligible TSS; no extra CAL is minted.
  Climb CAL is staked on that hill by default on a 104-week timer, renewed by
  each verified ascent and withdrawable by the rider at any time. Outside
  capital locks for up to 104 weeks without early exit. Claims initially
  receive 20% of the riders' yield share (18% of yield), leaving 80% of that
  share for direct riding pay. Claims wait for the
  five-rider field.
  [Sources: DESIGN, Stage 2; DIAMOND, Settled on 8 October.][HB-DESIGN]
- **Proposed design details, not separately ratified.** Stage 2's boost
  formula, 40% capital weight and 12-week verified-work window come from
  DESIGN's Stage 2 body, not its 6 Oct settled CAL-claim call.
  [Source: DESIGN, Stage 2, Boost.][HB-DESIGN]
- **Ratified 6 Oct 2026.** Stage 3 starts with gifts and at least two bonded
  hills; it can precede stage 2. DUNG votes direct only the shared pool's
  weekly money, never principal, records or rules. The pool holds donated
  yield, fee-free cash, observed trading fees (zero until observed) and
  season-stranded money, and pays riders under the normal split and cap,
  never CAL claims, voters or backers. No hill receives more than twice its
  share of that week's bonded-hill ascents; excess goes to other hills by
  ascents. Vote weight is DUNG × weeks left / 104; riding renews a rider's
  timer, backing keeps a backer's full while in, and received DUNG needs a
  lock and counts at 40%. Votes persist until changed. Donors get a title,
  not DUNG; no protocol bribes or pay for voting. [Source: DESIGN, Stage 3
  and settled calls; DIAMOND principles/derivations.][HB-DESIGN]
- **Ratified 13 Oct 2026.** Once CAL is tradable under the zero-start market
  trigger, riders may sell earned CAL immediately or hold it; show sale cash
  separately from retained-token value. This does not establish a market or
  change the trigger-based posture above. Every payout is funded and riders
  are paid in every phase.
  "Rider pay does not guarantee a profit on retained tokens or cover every riding cost."
  Trading profit is separate: it can
  come from later buyers without new backing and does not establish prior
  rider funding. Market language needs Jon's review before any public
  promotion. [Sources: DIAMOND, Markets and whales][HB-DIAMOND]; [DESIGN,
  Stage 2][HB-DESIGN]; [CHECKLIST item 12][HB-READY].
- **Hardened ladder trigger ratified 13 Oct 2026.** Stage-2 price ladders
  require sufficient market depth, an independent price reference and a real
  riding field. **Proposed:** escrowed price steps, step caps, their activation
  mechanics and the no-unwind rule. Numerical thresholds, oracle selection
  and the tournament's synthetic reference are not ratified production
  settings. [Sources: DIAMOND, Markets and whales / Price ladders][HB-DIAMOND];
  [diamond.yaml `ladder` and `model`][HB-PARAMS].
- **Proposed / gated.** Longer 104/208-week backing locks, concentration
  publication and excluding CAL purchases from the rider app are not ratified.
  Provider admission, production oracle selection, custody/identity proofs,
  client flows and audited deployment remain unproven. The intended 10%
  yield fee requires the program upgrade authority behind a seven-day timelock
  multisig; this is not deployed evidence. The separate service-fee direction
  above is ratified; only principle 7 wording awaits Jon ([FUNDING][HB-FUNDING]).
  This document makes no legal determination. [Sources: DIAMOND,
  Seven alignment rules; diamond.yaml proposed keys; DESIGN, Founders;
  STAGE1_SPEC §9; STAGE1_PLAN §§5–7; CHECKLIST.][HB-PLAN]

### Superseded CAL-vault statements and cutover

These replacements are prospective for bonded hills. Dates are ratification
dates, not deployment dates. The old text remains below; existing liabilities
keep the explicit cutover protection above.

| Retained statement | Replacement and status | Source |
|---|---|---|
| Paid activation: 100 DUNG or 1,000 CAL + $2 (§§3, 9, 11); associated DUNG price-floor claim | **Ratified 6 Oct:** escrowed backing reaches the city line; no activation purchase | DESIGN, Bonding / current-model comparison [HB-DESIGN] |
| Founder receives a paid eight-week Local Legend term (§5; §12 comparison) | **Ratified 8 Oct:** Founder is title only; the 10% rider cash bucket waits for an earned Legend | DIAMOND, Settled on 8 October [HB-DIAMOND] |
| 55/27/3/5/10 DUNG split and wallet-count staker unlock (§§2, 4, 8) | **Ratified 6 Oct:** cash 65/25/10 after the yield fee; DUNG 50/50 riders/backers, riders 55/35/10, backers lock-weighted | DESIGN, settled DUNG split [HB-DESIGN] |
| Legacy rank-weighted DUNG board allocator (§4) | **Cash rule ratified 6 Oct; mechanics 13 Oct:** cash separately allocates a flat 25% among occupied top-ten seats; DUNG's within-board division is not separately ratified (reference model: equal shares) | DESIGN, Stage 1; STAGE1_SPEC §§1, 5 [HB-S1]; `_dung` [HB-MODEL] |
| CAL deposits earn the 27% DUNG bucket (§7) | **Ratified 6 Oct:** SOL/LST backing earns backer DUNG; CAL claims wait for stage 2 and claim rider yield | DESIGN, Stages 1–2 / current-model comparison [HB-DESIGN] |
| 5% collection, proposed 0.5% exit fee and legacy treasury/POL fee model (§§2, 7–9, 13) | **Yield-only scope ratified 6 Oct; 10% rate/services direction 13 Oct:** protocol fee on realized yield, zero deducted from sponsor-cash/boost rider budgets; separate services may be charged on top, never out of rider money; wording pending Jon | STAGE1_SPEC §§4, 8 [HB-S1]; FUNDING decision [HB-FUNDING] |
| 1B/category lifetime caps, 26-week halvings and 1-bps tail (§§2, 8, 13) | **Ratified 8 Oct:** constant 1 DUNG per 1,000 climb-TSS, no lifetime caps or halvings for bonded-hill DUNG; existing obligations preserved | DIAMOND, Settled on 8 October [HB-DIAMOND] |
| 30-day admission into oldest-open-week tribute flow (§§2, 4) | **Ratified 6 Oct; mechanics 13 Oct:** new money module uses seven-day upload-week admission; boosts use ride-week budgets with fixed cutoff; original sporting provenance remains | DESIGN, Late uploads; STAGE1_SPEC §§2, 5–7 [HB-S1] |
| Unconditional record/Legend payout eligibility and indefinite empty-seat carry (§§4–5) | **Pool fallback ratified 6 Oct; field 7–8 Oct; mechanics 13 Oct:** five-rider seasonal field; unassigned held money becomes pool-only at 26 weeks, assigned claims never expire | DESIGN, Minimum field / Stranded money; STAGE1_SPEC §§5–6 [HB-S1] |
| Frozen DUNG voting on rules, fee structure or mint ratio (§§9, 13) | **Ratified 6 Oct:** stage-3 votes steer only weekly pool money, including gifts, stranded rider money and trading fees | DESIGN, Stage 3 [HB-DESIGN] |

### Source resolutions and remaining wording

1. **Resolved, ratified 13 Oct 2026:** in-kind payout replaces the SOL-only
   summaries. [STAGE1_SPEC §9, decisions 1–2][HB-S1].
2. **Resolved, ratified 13 Oct 2026:** deposit-time SOL basis replaces an
   original-token-count principal promise. [STAGE1_SPEC §9, decision 1][HB-S1].
3. **Resolved, ratified 13 Oct 2026:** held money and claims are outstanding
   balances, not lifetime sums of repeated carries. [STAGE1_SPEC §8][HB-S1].
4. **Resolved, ratified 13 Oct 2026:** losses stay with their lot
   ([STAGE1_SPEC §9, decision 1][HB-S1]), and principle 4 now reads "Backers
   risk only yield, plus any loss in their own staking token" (Tim, 13 Oct
   2026). Jon reviews the wording before public use.
5. **Resolved, ratified 13 Oct 2026:** boosts and the plan's mechanics are
   admitted by [STAGE1_SPEC §9][HB-S1] and [diamond.yaml `stage1`][HB-PARAMS].
   Ladder steps remain **proposed**; only the hardened trigger is ratified
   (Tim confirmed 13 Oct 2026 that steps, step caps and no-unwind stay proposed).
6. **Resolved, ratified 13 Oct 2026:** boosts have no per-ascent payment
   guarantee. Their money is irrevocable and reaches only riders, directly
   or through the riders-only pool, subject to field/cap/rounding/hold rules.
   [STAGE1_SPEC §§6, 9][HB-S1]; [DESIGN, Stage 3][HB-DESIGN].
7. **Resolved by Tim, 13 Oct 2026:** caps use running deposit-basis totals;
   STAGE1_SPEC amendment pending on `codex/boulderroller-v2-0jc1s-stage1-custody`.
   [Source: authorities brief][HB-BRIEF].
8. **Exception, not a conflict:** ordinary exit sweeps remain; Tim's
   **13 Oct** seven-day stale-rate exit is the narrow exception. Both hold;
   the spec amendment is pending on that custody branch. [STAGE1_SPEC §4][HB-S1];
   [authorities brief][HB-BRIEF].

[HB-DESIGN]: ../history/explainer-hill-bonding-2026-10-06/DESIGN.md
[HB-DIAMOND]: ../history/hill-bonding-diamond-2026-10-08/DIAMOND.md
[HB-PARAMS]: ../history/hill-bonding-diamond-2026-10-08/diamond.yaml
[HB-S1]: ../history/launch-readiness-2026-10-08/STAGE1_SPEC.md
[HB-PLAN]: ../history/launch-readiness-2026-10-08/STAGE1_PLAN.md
[HB-READY]: ../history/launch-readiness-2026-10-08/CHECKLIST.md
[HB-BRIEF]: ../history/codex-briefs-2026-10-13/authorities.md
[HB-R3]: ../history/codex-briefs-2026-10-13/stage1-custody-round3.md
[HB-FUNDING]: ../history/launch-readiness-2026-10-08/FUNDING.md
[HB-MODEL]: ../tools/stage1_reference/model.py

---

## 2. Two-Token Economy

### CAL (Effort Token)

CAL represents effort from riding. It is the transferable work/currency token per TRUTHS §7.1 and the staking asset riders deposit into a Climb's Vault.

| Property | Value | Status |
|----------|-------|--------|
| Earning | CAL = TSS from ride (1:1) | ✅ Live on devnet |
| Tribute | Distributed to Vaults crossed by the ride | ✅ Live on devnet |
| Transferable | Yes (SPL) | ✅ Live — SPL token on devnet |
| On-chain | SPL token, credited via `credit_cal` for each recorded RideAttestation | ✅ Live on devnet |

> **Architecture:** CAL is a live SPL token on devnet, credited per ride through `record_ride` then `credit_cal`. The `CalMintReceipt` PDA gives structural replay protection for the per-ride mint. The old batch/claim path was removed as part of the V4-A coherence redeploy.

Rewardable TSS is power-only and comes from the versioned `workout-parse`
metrics engine. Explicit `0W` samples count as real coasting, pause gaps over
30 seconds do not add effort time, and automatic CAL requires at least 30
power samples with at least 50% stream coverage. Route and heart-rate-only
estimates may be displayed, but they are not economic authority.

**2026-09-24 clarification (Tim, boulderroller-v2-8906g.5):** CAL is TSS;
there is no separate economic moving-time calculation. Recorded stationary
zeros remain in the frozen metrics-v1 NP/TSS calculation, just like recorded
coasting. Sample gaps longer than 30 seconds still delimit pauses. Implausible
stationary recording is an admission-evidence review decision, never a TSS
rewrite. Tim ratified the **92.62%** stationary-share review gate on
**2026-09-24**, retaining **<=0.5 m/s** and spans **>30s**: none of the 1,416
cached real rides reaches it, with at least a 0.50 percentage-point margin
above the observed maximum (92.110228%). This is evidence-policy
`stationary_recording_review_v2`, not a metrics change. Follow-up on the same
Bead: tighten toward **75% once review has a resolver**. Existing attested
rides keep their values, and held releases continue using admission-frozen
ride and climb NP/duration.

**CAL Tribute Formula:**
```
Policy version: cal_tribute_segment_tss_v2

The rider receives the full attested CAL.

For each eligible matched Vault:
  segment_tss_base_units_i = floor(
    segment_np_duration_s_i * segment_np_milliwatts_i^2
    * 100 * 1_000_000_000
    / (reward_ftp_w^2 * 1_000_000 * 3_600)
  )

exact_tribute_budget_base_units = sum(segment_tss_base_units_i)
```

Tribute is a separate lifetime flow-meter input, not CAL deducted from the
rider or newly minted to the Vault. The immutable ride-time reward FTP supplies
the TSS denominator; mutable profile FTP never has authority. NP is frozen in
integer milliwatts with its pause-aware NP duration, and each Climb amount is
floored independently. Missing, insufficient, or zero segment power gets zero
tribute with no gradient proxy, while the completion and leaderboard result can
still record. One fastest qualifying traversal per ride and Vault supplies the
single receipt. Overlapping eligible climb windows require review instead of
double counting. The summed tribute never exceeds full attested CAL. New plans
use this policy; historical plans remain unchanged.

### DUNG (Value Token)

> **Legacy CAL-vault supply.** The cap below is superseded for future bonded-hill
> DUNG by the constant-rate decision **ratified 8 Oct 2026**; see
> [§1a](#1a-hill-bonding) and [DIAMOND, Settled on 8 October][HB-DIAMOND].

DUNG is the tradeable value token, earned as rewards from vault participation.

| Property | Value |
|----------|-------|
| Total Supply | 1,000,000,000 (1B) |
| Decimals | 9 (SPL standard) |
| Chain | Solana |
| Market | None — zero-start; no listing planned or dated ❄️ |

**Minting model:**
- DUNG is minted only via vault emissions (epoch distribution + collect).
- Rides do **not** mint DUNG directly.

### Token Flow Diagram

> **Legacy CAL-vault flow, retained.** Bonded-hill funding, split, fees and
> admission replace this flow prospectively (**ratified 6–13 Oct 2026**);
> see [§1a](#1a-hill-bonding) for replacements, sources and cutover.

```
EARNING:
  Ride completed
    |
    v
  TSS calculated (power meter required)
    |
    v
  CAL earned = TSS (1:1)
    |
    v
  CAL tribute distributed to vaults crossed
    (weighted by time x intensity factor)

TRIBUTE ACCUMULATION (per Vault):
  Vault receives CAL tribute from rides
    |
    v
  Lifetime tribute flow meter credits the oldest open Settlement Week
  (the ride keeps its original completed_at; no ride-week admission bucket)

SETTLEMENT WEEK FINALIZATION (weekly, Monday 12:00 UTC + 24h grace):
  Each Vault finalizes per-bucket, discrete direct allocation:
    - 55% -> Record Board (permanent all-time top 10)
    - 27% -> Active stakers (pro-rata, discrete allocation, not accrual)
    - 3%  -> Local Legend (rolling stewardship seat)
    - 10% -> Protocol treasury
    - 5%  -> POL (protocol-owned liquidity)
  Per-bucket carry: unavailable-recipient amounts carry within their bucket.
  The staker curve's locked share instead joins that week's Record Royalty.

DEPOSIT (stake):
  User deposits CAL in a Vault
    |
    v
  Principal recorded in VaultStake.cal_staked; redeemable LP in VaultStake.lp_tokens
    |
    v
  Weekly weight uses VaultStake.effective_lp_tokens plus one pending full-balance target

COLLECT REWARDS:
  User collects accrued DUNG from VaultStake.rewards_earned
    |
    v
  Transferred to rider ATA (5% collect fee)
    |
    v
  CAL principal stays deposited

WITHDRAW (unstake):
  User withdraws CAL
    |
    v
  Full-position UI reads and burns every exact on-chain LP base unit
    |
    v
  Returns the LP share of pooled CAL (exit fee applies)
  Retained VaultStake.cal_staked is the remaining deposited-principal basis
    |
    v
  Must collect first or forfeit pending rewards
```

---

## 3. Vault System

### Core Concept

Vaults are on-chain representations of cycling segments (climbs, efforts). They function as:

- **Geographic investment assets** - stake and earn from traffic
- **Competitive arenas** - leaderboard positions for rewards
- **Permanent on-chain objects** - cannot be deleted by any corporation

### Vault Creation

> **Superseded for bonded hills, ratified 6 Oct 2026:** paid activation below
> becomes escrowed pledge-to-bond at the city line. Founder is title only
> (**8 Oct**), without the paid bootstrap Legend term. See
> [§1a](#1a-hill-bonding) and [DESIGN, settled calls][HB-DESIGN].

| Parameter | Value |
|-----------|-------|
| Cost | 1,000 CAL + $2 USDC OR 100 DUNG |
| On-chain | ✅ Permanent, immutable |
| Founder metadata rights | 12 Settlement Weeks (~84 days) |

```rust
// Code-verified constants (names subject to V4-B hard rename; current chain field is `minter`)
VAULT_CREATION_CAL = 1000
VAULT_CREATION_USDC = $2 (6 decimals: 2_000_000)
VAULT_CREATION_DUNG = 100 * DUNG_DECIMALS_MULTIPLIER
MINTER_RIGHTS_EPOCHS = 12
```

**Founder metadata rights (12 Settlement Weeks):**
- Metadata control only (name, description, cover photo)
- NOT perpetual revenue share — Founder is permanent provenance per TRUTHS §6.1, but does not automatically earn permanent royalty (that belongs to the Record Board)
- After 12 Settlement Weeks, the Vault's metadata becomes community-editable via the active Local Legend seat

**Transitional authority note:** the deployed V4-A `update_vault_metadata`
instruction still calls `Vault.rights_holder()`, which falls back to singular
`kom_holder` after Founder rights expire. That compatibility coupling is not
canonical metadata stewardship and does not make a KOM, co-KOM, or the legacy
representative the Local Legend. The co-KOM decision does not expand the
current signer path to every tied rider or change the ABI. Moving metadata
authority to the active Local Legend requires a separate explicit
authority/ABI rollout. That rollout is a hard prerequisite before the co-KOM
implementation may rotate `kom_holder` for an equal-fastest ride; otherwise a
late upload could silently transfer live metadata authority. Local Legend state
already exists, so any data migration must be proven necessary rather than
assumed.

### Vault Signature → Canon Commitment

Each Vault has a 64-byte identity field. **Canon-first climb identity (ratified 2026-07-04, epic `boulderroller-v2-4crx`) redefines this field:** climbs are compiled offline from the OSM road graph + DEM into a versioned canon registry (fixed corridors, intersection-snapped gates); the Vault's 64 bytes become a deterministic **canon commitment** (`canon_id` + version + canonical profile hash). Rides then match by corridor traversal + gate crossing, not detector signatures. Fresh V4-B introduces the immutable on-chain Climb account and binds each new Vault to it. The Vault PDA remains keyed by `vault_id`; V4-A devnet data is test data and is not migrated into the clean V4-B program.

At bootstrap, versioned successors are operational only with a fresh Record
Board. Minor revisions that require `carry_records_forward` remain unavailable
until an explicit on-chain continuity operation moves and verifies the prior
records; a database or account label alone is not sufficient.

Detector-era state, retained for discovery and replay context:

- **Detection engine:** canonical_v2 — momentum + persistence fusion (F1≈0.78, **tuning frozen**); demoted to discovery/nomination after cutover
- **Fuzzy matching** with DCT low-frequency coefficients (DCT_MATCH_COEFFS=6)
- **GPS-gated matching:** 150m start-point proximity gate
- The detector parameter drift guard remains for discovery; the detector-era
  signature-stability blocker retired at the V4-B cutover (`4crx.11`) because
  Vault identity is now enforced by the D12 canon commitment codec and the
  on-chain Climb-to-Vault binding

### Vault Economics Summary

The constants below belong to the legacy CAL-vault model. Future bonded-hill
funding and constant DUNG issuance follow [§1a](#1a-hill-bonding),
**ratified 6–13 Oct 2026**, rather than its CAL-deposit or tunable-ratio rules.

| Constant | Value | Notes |
|----------|-------|-------|
| Vault CAL tribute | Measured Climb TSS | Separate flow-meter amount; rider still receives full CAL |
| `VAULT_CAL_TO_DUNG_THRESHOLD` | 1,000 | CAL needed to emit 1 DUNG 🔧 Governance-adjustable monetary policy lever |
| `VAULT_MIN_STAKE` | 100 CAL | Minimum stake per user |
| `EPOCH_DURATION_SECONDS` | 604,800 | 7 days |

---

## 4. Distribution Model

> **Legacy CAL-vault distribution, retained for its liabilities.** The bucket
> split, wallet-count curve and oldest-open-week admission
> below are superseded for the new hill-bonding module by [§1a](#1a-hill-bonding)
> (**ratified 6–13 Oct 2026**, sources and cutover there). Whole-second
> sporting ties and the ten-seat bound remain; stage-1 cash uses a flat board
> split ([STAGE1_SPEC §§1, 5][HB-S1]). DUNG's within-board division is not
> separately ratified; §1a identifies the reference model's equal shares
> without declaring them a ratified replacement for the legacy rank allocator.

### Settlement Week Finalization

At the end of each Settlement Week (Monday 12:00 UTC + 24-hour finalization grace window), each Vault with pending tribute finalizes per-bucket, with discrete direct allocation to each recipient. Tribute is a lifetime tribute flow meter: every ride accepted by the 30-day age guard records at its original `completed_at` and credits the Vault's oldest open Settlement Week after empty-week catch-up. The week is a payout heartbeat, not a ride-admission bucket. Unavailable-recipient amounts and allocation dust retain bucket identity. The policy-locked portion of the weekly staker maximum is different: it joins the same week's Leaderboard pool and never becomes retroactive staker carry.

The compatibility fields `cal_tribute_accumulated_next` and
`pending_rewards_next_week` remain in the V4-A account layout but receive no
new completion writes. Normal rollover drains any legacy values into the open
flow. The backend confirms every climb completion before `credit_cal`; failed
completion work remains retryable and cannot silently mint CAL first. The
30-day guard is decided once at immutable ride-attestation admission, so child
effects cannot age out between transactions. The receipt-less legacy
`record_vault_completion` instruction remains ABI-visible but fails closed.

Final payout remains one atomic `distribute_epoch_rewards` instruction. Missing
recipient token accounts are created separately and idempotently during
preparation. The economic instruction is then signed as a v0 transaction using
the Vault's managed address lookup table only after finalized reads reproduce
the frozen account manifest, lookup-table generation and extension slot, and
an exact signed size no greater than the reviewed 900-byte ceiling. Unsigned
transport drift returns to preparation; prepared or accepted signatures are
reconciled and never replaced with a legacy transaction.

| Recipient | Share (BPS) | Percentage | Notes |
|-----------|-------------|------------|-------|
| Leaderboard (all-time top 10) | 5500 | 55% | **Leaderboard pool** — permanent weekly allocation to the Climb's all-time top 10 |
| Stakers | 2700 | 27% | Pro-rata direct allocation credited to `VaultStake.rewards_earned` in V4-A (`unclaimed_rewards` in V4-B) |
| Local Legend | 300 | 3% | Rolling stewardship seat (8 Settlement Weeks) |
| Protocol Treasury | 1000 | 10% | Operations |
| POL | 500 | 5% | Protocol-owned liquidity |

```rust
// Code-verified DistributionConfig
pub struct DistributionConfig {
    pub leaderboard_share_bps: u64,     // 5500 = 55%
    pub staker_share_bps: u64,          // 2700 = 27%
    pub local_legend_share_bps: u64,    // 300 = 3%
    pub pol_share_bps: u64,             // 500 = 5%
    pub protocol_fee_bps: u64,          // 1000 = 10%
}
// Total must equal 10000 (100%)
```

### Leaderboard Distribution (Top 10)

| Rank | Percentage |
|------|------------|
| 1st | 30% |
| 2nd | 20% |
| 3rd | 15% |
| 4th | 10% |
| 5th | 8% |
| 6th | 6% |
| 7th | 5% |
| 8th | 3% |
| 9th | 2% |
| 10th | 1% |

```rust
LEADERBOARD_RANK_PCTS: [u8; 10] = [30, 20, 15, 10, 8, 6, 5, 3, 2, 1]
```

**Leaderboard Behavior:**
- **All-time leaderboard** - top 10 fastest times ever (not weekly)
- These 10 riders get paid every epoch they hold a position
- **Standard competition ties** - equal whole-second times share the first rank,
  consume one position each, and split the pooled percentages for those occupied
  positions equally; indivisible base-unit dust remains in Record Royalty carry
- **Deterministic cutoff** - if an equal-time group crosses the ten-seat bound,
  original ride `completed_at` decides membership, then wallet bytes; processing
  or upload order never decides
- **Wire compatibility** - `client.v1 rank` remains occupied position;
  `competition_rank` is the paid standard-competition rank
- **Co-KOM recognition (ratified, pending implementation)** - every seated
  rider at the fastest validated whole-second time will be a co-KOM and receive
  a crown plus `T-1` on detailed rider surfaces; a strictly faster time will
  replace the full prior set
- **Legacy KOM representative (ratified, pending implementation)** -
  `Vault.kom_holder` remains one ABI-compatible representative, targeted for
  selection by earliest original ride `completed_at`, then wallet bytes; it
  adds no payout and has no sole-winner sporting meaning, so read models will
  enumerate co-KOMs from the Leaderboard. Equal-time rotation is blocked until
  the metadata-authority/ABI rollout decouples live stewardship from the scalar
- **Pre-cutover repair** - an already-active board cannot recover an omitted
  rider from its bounded rows; any repair requires a separately ratified,
  evidence-bound one-time migration and does not reopen routine admin replacement
- **Bumping:** take a top-10 seat -> bump a rider off, they stop earning
- Rewards based on permanent standing, not filtered views

**Proportional Distribution for Partial Entries (<10):**

When fewer than 10 riders have completed a vault, rewards are redistributed proportionally among existing entries:

```
rider_share = rank_pct[i] / sum(rank_pct[0..num_entries]) * 100

Example with 3 entries:
  sum = 30 + 20 + 15 = 65
  1st place: 30/65 = 46.15%
  2nd place: 20/65 = 30.77%
  3rd place: 15/65 = 23.08%
```

### Staker Unlock Curve (Anti-Whale Gaming)

The staker pool unlocks gradually based on unique staker count to prevent first-staker gaming:

| Stakers | Unlock % | Stakers Get | Remainder to Leaderboard |
|---------|----------|-------------|--------------------------|
| 0 | 0% | 0% | 27% |
| 1 | 1% | 0.27% | 26.73% |
| 2 | 3% | 0.81% | 26.19% |
| 3 | 6% | 1.62% | 25.38% |
| 4 | 11% | 2.97% | 24.03% |
| 5 | 17% | 4.59% | 22.41% |
| 6 | 25% | 6.75% | 20.25% |
| 7 | 35% | 9.45% | 17.55% |
| 8 | 50% | 13.5% | 13.5% |
| 9 | 70% | 18.9% | 8.1% |
| 10+ | 100% | 27% | 0% |

```rust
STAKER_UNLOCK_PCTS: [u8; 10] = [1, 3, 6, 11, 17, 25, 35, 50, 70, 100]
```

**Design Rationale:**
- First staker only gets 1% of the staker pool - anti-gaming
- Creates network effects (more stakers -> more rewards unlocked)
- Vaults mature from rider-dominated to staker-balanced
- Remainder flows to leaderboard (riders), not burned
- The rule applies independently each week; later staker growth does not unlock
  a historical remainder
- Already-unlocked integer dust must not pass through the curve again

**Implementation (`scur`):** V4-A curves only the current week's base staker
maximum, moves its locked difference into same-week Record Royalty, and adds
prior already-unlocked dust after the curve. The 52-week one-staker invariant
therefore remains exactly 1% of cumulative weekly staker maxima, subject only
to integer dust. On the first new-policy settlement for a deployed legacy
Vault, all pre-policy `carry_stakers` is conservatively reclassified to Record
Royalty and an explicit policy event marks the historical boundary; later
`carry_stakers` is unlocked allocation dust only.

### Settlement Week Timing

```rust
EPOCH_DURATION_SECONDS = 604_800  // 7 days
EPOCH_ANCHOR = 1704110400         // Mon Jan 1 2024 12:00:00 UTC

// Settlement Weeks run: Monday 12:00 UTC to Monday 12:00 UTC
// Normal finalization: Tuesday 12:00 UTC after the 24-hour grace
```

**Migration requirement:** deployed V4-A state and projections may still use
`1704020400`, which is Sunday 11:00 UTC. The landed clock contract initializes
clean test state directly on v2 and requires an explicit historical version for
an existing deployment; old week numbers are never silently reinterpreted
under the new anchor. A live versioned cutover therefore has one
explicit 694,800-second transition week, from its legacy Sunday 11:00 UTC start
through the following v2 Monday 12:00 UTC end. This is the one-time 25-hour
extension beyond a normal seven-day week required for numeric continuity; the
transition lasts 8 days and 1 hour. All later weeks are exactly 604,800 seconds
and normally finalize Tuesday 12:00 UTC.

---

## 5. Local Legend System

**Local Legend** is the canonical name per PROTOCOL_TRUTHS §6.4 — the rolling stewardship seat of a Climb, based on recent participation, economically meaningful but culturally authoritative rather than permanently glorious. It is rolling truth, not permanent truth.

### Overview

Single rotating stewardship seat per Vault, awarded to the rider with the most completions during the term. Unlike KOM/co-KOM (permanent) or the Record Board (permanent top 10), the Local Legend seat can go dormant when activity drops off and rotate when someone else puts in the work. It is also the canonical post-Founder metadata steward; sporting recognition does not grant that authority.

### Parameters

The 3% payout below is the legacy CAL-vault share. [§1a](#1a-hill-bonding)
sets the bonded-hill cash and DUNG shares, field and held-money expiry,
**ratified 6–13 Oct 2026** ([DESIGN][HB-DESIGN];
[STAGE1_SPEC §§5–7][HB-S1]); the sporting role remains distinct.

| Parameter | Value | Notes |
|-----------|-------|-------|
| Seats per Vault | 1 | Not 3 — legacy Swanny model is superseded |
| Term length | 8 Settlement Weeks | ~56 days |
| Selection | Most completions in the term | Tiebreaker: earliest completion (ride-time) |
| DUNG lock required | None | Merit-based, not capital-gated |
| Reward share | 3% | Of Vault Settlement Week allocation |

```rust
LOCAL_LEGEND_TERM_EPOCHS = 8      // 56 days (8 Settlement Weeks)
LOCAL_LEGEND_SHARE_BPS = 300      // 3% of Vault distributions
```

### Founder Bootstrap

> **Superseded for bonded hills, ratified 8 Oct 2026:** the Founder gets a
> title only; an earned Local Legend receives the rider bucket. This retained
> bootstrap history cannot supply a paid stage-1 seat. [Source: DIAMOND,
> Settled on 8 October][HB-DIAMOND]; [replacement and cutover: §1a](#1a-hill-bonding).

- **The Climb's Founder is automatically the first Local Legend** for 8 Settlement Weeks
- No election needed for the first term
- Incentivizes Climb founding — the Founder captures the 3% Local Legend bucket during bootstrap
- After 8 Settlement Weeks, normal election cycle begins
- This IS the Founder reward during bootstrap — there is no separate Founder revenue share on top

### Responsibilities

1. Approve/reject Vault cover photos
2. Flag suspicious completions for community tribunal
3. Recommend the Climb for featuring (optional)

### Gaming Philosophy

**Let them game it.**

- If someone wants to farm the seat by riding constantly, that's the point — they have to actually ride (real physical effort)
- They may pay to found Climbs (revenue)
- Maintaining the seat on many Climbs is expensive in effort
- Natural economics limit abuse potential
- Empty or dormant seats don't redistribute — the 3% bucket carries forward within its own bucket per TRUTHS §P10

---

## 6. BeetleCard System

### Philosophy

**"Halo 2 Philosophy"** - steep progression, no shortcuts:

- Cards reflect actual lifetime effort
- **No catch-up mechanics ever**
- **No resets, no prestige**
- Your card is your permanent cycling record

### BeetleCard Types

| Type | Scope | Metric |
|------|-------|--------|
| Climb | Per Arena (scope_id = arena pubkey) | Climb efforts |
| Steady | Global (zero bytes scope) | Endurance duration |
| Explorer | Global (zero bytes scope) | Tile discovery |

### Leveling, Upgrades, and Cosmetics ❄️ FROZEN

The BeetleCard progression economy — level thresholds, DUNG-burn upgrade curve (25 × 2^(N-1)), Level 10 Elite Gate, visual design, and the cosmetic system — is **frozen until the First Cohort loop is proven**. The on-chain account (`BeetleCard` PDA, `increment_beetle_score`) exists and continues to accumulate score; nothing else in this system is active roadmap. Full preserved design: [Frozen Design Inventory](#13-frozen-design-inventory).

---

## 7. Staking Mechanics

> **Legacy CAL-vault mechanics.** For bonded hills, SOL/LST backing, its
> lock/notice and yield-only fee replace the economic model below
> (**ratified 6–13 Oct 2026**). CAL's yield claim waits for stage 2; legacy
> CAL custody and accrued DUNG retain their entitlement through an explicit
> cutover. See [§1a](#1a-hill-bonding), [DESIGN][HB-DESIGN] and
> [STAGE1_SPEC §§3–4][HB-S1].

### Discrete Per-Settlement-Week Allocation

The staking model abandons continuous reward accrual (Synthetix pattern) in favor of discrete direct allocation at each Settlement Week finalization. This matches the economics, which are inherently weekly and discrete, and eliminates the reward_rate quantization and period_finish bugs that came with the old accrual math. See TRUTHS P8.

1. **Deposit CAL** in a Vault — remaining deposited-principal basis and redeemable pool share are tracked in `VaultStake.cal_staked` and `VaultStake.lp_tokens`. `Vault.total_cal_staked` is the Vault's current gross pooled CAL inventory.
2. Stake changes use a frozen weekly LP snapshot: `effective_lp_tokens` is the open week's weight, while `pending_lp_tokens` and `pending_effective_week_plus_one` hold the next full-balance target. A change exactly at the boundary is effective for the new week; a later change is effective the following week. Mid-week stake changes never affect the current week.
3. At each Settlement Week finalization, the chain iterates eligible stakers, computes each staker's pro-rata share of the unlocked staker bucket, and credits the share directly to `VaultStake.rewards_earned` in V4-A. Event emission: `StakerAllocation { epoch, vault, staker, amount }`.
4. **Collect rewards** anytime — transfers `rewards_earned` to the rider ATA, zeros the field. No rate math, no accrual calculation.
5. **Withdraw CAL** — returns the LP share of pooled CAL and applies the exit fee to those proceeds. A partial exit retains `floor(prior principal * remaining LP / prior position LP)` as principal basis; a full exit clears the basis exactly.
6. Wallet and Boulder Roller Balance actions use the same deterministic position LP account. Its token authority is the `VaultStake` PDA; the Vault remains the LP mint and freeze authority and freezes the account between checked instructions. The token amount must equal `VaultStake.lp_tokens`; LP is internal pool-share accounting, not a rider-transferable asset.
7. Balance custody is not consent. Balance-funded Deposit CAL, Withdraw CAL, and CAL+USDC Vault creation require a rider-signed session setup or rotation plus one exact, expiring, nonce-bound operation signed by that session authority. Login, UI confirmation, the fee payer, and the Backend Authority cannot authorize rider-value movement. Lock, recovery, revocation, or session expiry fails closed; reactivation requires a fresh rider-signed rotation. The wallet-signed route remains the fallback.

> **Language note:** User-facing actions are "Deposit CAL", "Withdraw CAL", and "Collect rewards". See `docs/design/LANGUAGE_SPEC.md` for the language split between chain-canonical and rider-facing vocabulary.

> **Custody boundary:** the current product is one account-bound position. Legacy wallet or Balance LP must be restored into the canonical frozen custody account before the position is redeemable. A future strategy program may explicitly own a separate position and issue its own bearer shares, but that is a distinct versioned product and does not make core Vault LP transferable.

### Staking Parameters

| Parameter | Value | Status |
|-----------|-------|--------|
| Deposit asset | CAL | ✅ Live on devnet |
| Reward token | DUNG | ✅ Live on devnet |
| Minimum deposit | 100 CAL | ✅ Live on devnet |
| Entry fee | 0% | ✅ Live on devnet |
| Collect fee | 5% (to treasury) | ✅ Live on devnet |
| Withdrawal fee | 0.5% (burn/POL split) | ⚠️ **PLANNED** - not yet in code |
| Weekly participation | Frozen `effective_lp_tokens`; one pending full-balance target | ✅ Implemented |

> **Tunable Parameters:** Entry fee, collect fee, and exit fee are economic levers retained for protocol governance. Values may be adjusted post-launch via multisig.

```rust
HARVEST_FEE_BPS = 500  // 5% - implemented
CAL_MIN_STAKE = 100    // 100 CAL minimum stake - implemented
// EXIT_FEE_BPS = 50   // 0.5% - planned, not implemented
```

### Why CAL Staking (not DUNG)

- DUNG is the value/reward token — product of Vaults, not input
- CAL is transferable work/currency (TRUTHS §7.1) — external participants can buy CAL to deposit in Vaults without riding
- Clean separation: stake effort (CAL), earn value (DUNG)
- Permanent record performance and rolling stewardship are separate economic streams, paid by the Record Royalty and Local Legend buckets respectively — staking is the capital-participation stream only, and does not buy riderhood (TRUTHS §7.3)

---

## 8. Supply and Emissions

> **Legacy CAL-vault schedule and liabilities.** The lifetime/category caps,
> halvings, tail and split below are superseded for future bonded-hill DUNG
> (**split ratified 6 Oct; constant issuance ratified 8 Oct 2026**). They do
> not cap the new module's issuance. Historical counters and existing
> entitlements are not reset or discarded. [§1a](#1a-hill-bonding) supplies
> the cutover boundary; [DIAMOND][HB-DIAMOND] and [STAGE1_PLAN §1][HB-PLAN]
> supply the decision and preservation requirement.

### DUNG Token Supply

Total supply is capped at 1B. The category split below is enforced by deployed code; the **allocation-and-distribution story behind it is a frozen sketch** under zero-start — there are no investors, no unlock event, and no distribution date. See [Frozen Design Inventory](#13-frozen-design-inventory) for the preserved allocation design.

```rust
// Code-verified supply caps (with 9 decimals)
MAX_SUPPLY = 1_000_000_000 * DUNG_DECIMALS_MULTIPLIER    // 1B DUNG
COMMUNITY_CAP = 400_000_000 * DUNG_DECIMALS_MULTIPLIER   // 400M
TREASURY_CAP = 250_000_000 * DUNG_DECIMALS_MULTIPLIER    // 250M
TEAM_CAP = 200_000_000 * DUNG_DECIMALS_MULTIPLIER        // 200M
INVESTOR_CAP = 100_000_000 * DUNG_DECIMALS_MULTIPLIER    // 100M
POL_CAP = 50_000_000 * DUNG_DECIMALS_MULTIPLIER          // 50M
```

### Halving Schedule

```rust
EPOCHS_PER_HALVING = 26  // ~6 months at weekly epochs
MIN_EMISSION_RATE_BPS = 1
```

| Period | Epochs | Emission Rate |
|--------|--------|---------------|
| 0-26 | 1-26 | 100% |
| 26-52 | 27-52 | 50% |
| 52-78 | 53-78 | 25% |
| 78-104 | 79-104 | 12.5% |
| ... | ... | Continues halving to the 1-bps tail |

The schedule starts from one immutable emission-start week. Fresh
initialization uses the latest week whose Monday handoff and 24-hour grace have
elapsed; migration preserves the deployed start. Every settlement derives the
number of elapsed 26-week intervals and applies all missed halvings exactly
once. The deployed `lastHalvingEpoch` field keeps its historical ABI name but
stores this immutable start week. At 1 bps the policy rate stops
decreasing. Supply-cap admission can reach zero without changing that rate;
the Settlement Week still finalizes successfully.

The canonical split is 55% Record Royalty, 27% stakers, 3% Local Legend, 5%
POL, and 10% treasury. The program makes that split canonical, binds the DUNG
mint and initialization authority to ProgramConfig, fixes the interval at 26
weeks, and removes manual halving as a monetary-policy control.

All admitted Community allocation is reserved before payout. The global
reservation equals unclaimed `VaultStake` rewards plus every Vault's Record
Royalty, staker, and Local Legend carry. Direct Community mints consume the
reservation; claims and carry retain it. Cap pressure clips only new emission,
never existing carry or claims. POL and treasury mint immediately and must
have zero carry. The one-time state migration therefore requires a complete,
PDA-validated `VaultStake` and Vault census before upgraded settlement begins.

`reservation_policy_version = 1` marks the 130-byte full-liability state.
Settlement fails closed on the 121-byte legacy layout, the 129-byte claim-only
layout, or any other policy marker. Migration preserves the legacy prefix,
permits only a monotonic top-up from the claim-only predecessor, and requires
an unversioned state to remain at the original 10,000-bps rate so a previously
manual halving cannot be silently reinterpreted as the emission start. The
operator must pause all stake, Vault, settlement, collection, and other DUNG
writers; bind exact stake/Vault counts, liability total, and inventory hash;
simulate a prebuilt address-table transaction; and execute only the reviewed
plan hash with a fee payer distinct from the ProgramConfig admin. See
[`DUNG_RESERVATION_MIGRATION.md`](runbooks/DUNG_RESERVATION_MIGRATION.md).

### Protocol Rake & Treasury Flywheel ❄️ FROZEN

The rake flywheel (fee channels → ~40% burn / ~60% growth deployment, governance split, fiat buybacks) and the treasury allocation plan are **liquidity-era designs, frozen under zero-start**. The live fee channels that exist today (10% treasury bucket per settlement, 5% collect fee) continue to accrue to treasury; the *deployment* strategy is not active roadmap. Full preserved design: [Frozen Design Inventory](#13-frozen-design-inventory).

---

## 9. DUNG Demand & Sustainability Model

> **Retained legacy/frozen analysis.** Paid activation and its claimed DUNG
> floor, fee recycling and voting on protocol rules are not hill-bonding
> rules. Their replacements are **ratified 6–13 Oct 2026** in
> [§1a](#1a-hill-bonding): funded backing, a yield-only fee and votes over
> weekly shared-pool money. Market gains are separate from funded payouts
> ([DIAMOND, Markets and whales][HB-DIAMOND]). No modeling figure below is
> evidence of a stage-1 market or payout.

> **Added v2.2 (March 2026)** — Based on quantitative modeling of supply dynamics, DePIN sink research, and game-theoretic analysis of cosmetic marketplaces.

### The Demand Question

Why does someone acquire DUNG? The system needs sustainable demand beyond speculative interest.

### Demand Sources (Ordered by Current Impact)

| Source | Type | Timing | Notes |
|--------|------|--------|-------|
| **BeetleCard upgrades** | One-time per level, 100% burned | Active now | Dominant burn (93-96% of all DUNG burns). ~1,575 DUNG per user to L7 (realistic cap). |
| **Vault creation** | One-time per vault, 100% burned | Active now | 100 DUNG option. Dual-price lever creates $0.02/DUNG arbitrage floor. |
| **Rake burn** | Recurring, proportional to activity | ❄️ Frozen (liquidity era) | ~40% of protocol fees burned. Persistent deflation scaled to economic activity. |
| **Rake recycling** | Recurring deployment | ❄️ Frozen (liquidity era) | ~60% of protocol fees into regional pots, vault bootstrapping, seasonal incentives. |
| **Governance** | Hold to vote on protocol parameters | ❄️ Frozen (liquidity era) | CAL:DUNG ratio, rake split, fee structure. Gives holders influence over monetary policy. |
| **Fiat buybacks** | External revenue → market buy → burn | Future | Sponsors, data licensing, partnerships. The Hyperliquid play. |
| **Cosmetic marketplace** | Recurring purchases, 100% burned | Future (50K+ MAU) | Account-bound, Fortnite model. Season pass + seasonal drops. |

### Quantitative Findings (March 2026 Modeling)

**Minting is negligible relative to burns.**
- Per rider: ~0.58 DUNG minted/month from riding (at 1000:1 ratio)
- At 20K riders over 36 months: ~49K DUNG minted vs ~144M DUNG burned
- Mint/burn ratio: **0.03%** — the system draws down the capped allocation, not a minting equilibrium

**BeetleCard dominates all burns.**
- 93-96% of total burns across all scenarios
- Exponential cost curve (25 × 2^(N-1)) is the safety valve — costs become prohibitive at L7+
- L8+ effectively unreachable (~43 years of riding for L8 score threshold)

**CAL:DUNG ratio has near-zero impact on supply dynamics.**
- At 500:1, 1000:1, 2000:1, or 5000:1, deflation rate changes by <0.01%
- The ratio matters for **vault yield attractiveness** (monetary policy), not supply

**Halving burn is negligible.**
- Only burns undistributed DUNG from vault pots, but pots contain <50K DUNG total over 36 months
- Keep mechanism for narrative/optics but don't over-optimize

**Deflation scenarios (36 months, Base case — 20K riders):**

| Scenario | Supply Burned | Circulating at M36 | Deflation |
|----------|-------------|--------------------|-----------|
| Bear (5K riders) | 23M (2.3%) | 477M | Mild |
| Base (20K riders) | 144M (14.4%) | 356M | Moderate |
| Bull (50K riders) | 487M (48.7%) | 13M | Aggressive — possible liquidity crisis |

### Self-Regulating Properties

The system has built-in governors:

1. **No riders = no inflation.** Empty vaults produce zero DUNG. Inflation is demand-driven.
2. **BeetleCard cost curve is self-limiting.** Exponential costs naturally taper burn rate as users reach high levels.
3. **Growth creates demand, stalling creates equilibrium.** New users need DUNG for BeetleCard. When growth stops, less demand, price drops, lower barrier, attracts users.
4. **The glory loop is independent of tokens.** Riders chase KOMs for glory even if DUNG goes to zero. The base activity doesn't require token value to sustain.

### Three Laws of Token Sinks (DePIN Research)

From analysis of Helium, STEPN, Axie, Render, Fortnite, Hivemapper:

1. **A sink that creates new emission sources is not a sink.** (Axie breeding, STEPN shoe minting — spend tokens to make something that earns more tokens = death spiral.) Boulder Rollers passes: BeetleCard upgrades don't increase earning capacity.
2. **Internal-only sinks are reflexive and unstable.** Need external demand eventually. Boulder Rollers mitigates: fiat buybacks from future revenue + governance utility.
3. **Forced sinks create resentment, voluntary sinks create engagement.** (STEPN mandatory shoe repair vs Fortnite optional skins.) Boulder Rollers passes: all sinks are voluntary.

### Dual-Price Vault Lever

Vault creation: **100 DUNG** OR **1,000 CAL + $2 USDC**

Creates arbitrage-enforced price floor:
- If 100 DUNG < $2 → rational actors pay DUNG (buy pressure)
- If 100 DUNG > $2 → rational actors pay USDC (floor dormant)
- Implicit floor: **$0.02/DUNG**

Buy pressure is weak at small scale (~$3.4K/month at 20K riders) but provides a theoretical minimum.

### Regional Performance Pots ⚠️ CONCEPT

Treasury-funded competitive pools at geographic scale:
- Best W/kg in a region, best VAM on Cat 3+ climbs, geographic leaderboards
- Funded from the 60% growth deployment portion of protocol rake
- Creates recurring competitive incentives beyond individual vault leaderboards
- Design details TBD — needs categories, payout structure, geographic boundaries

---

## 9b. On-Chain Access Control (April 2026)

All privileged instructions are gated by `ProgramConfig.backend_authority`:

| Instruction | Authority | Additional Constraints |
|------------|-----------|----------------------|
| `distribute_epoch_rewards` | backend_authority (signer) | POL/treasury accounts must match ProgramConfig; epoch guard prevents double-distribution per vault |
| `elect_local_legend` | backend_authority (signer) | Off-chain completion count verification |
| `increment_beetle_score` | backend_authority (signer) | Only backend can increment scores |
| `record_climb_completion_v2` | backend_authority (signer) | Only live completion path. Requires `RideAttestation`, a one-time `ClimbCompletionReceiptV2`, an exact tribute-bound V2 hash recomputed by the program, and the writable ride-scoped tribute-ceiling PDA; aggregate tribute cannot exceed attested CAL |
| `record_climb_completion` | backend_authority (signer) | Historical V1 ABI entry point; fails closed because V1 evidence does not bind exact tribute |
| `record_vault_completion` | backend_authority (signer) | Deprecated ABI entry point; fails closed with `InvalidRideAttestation` |
| `admin_create_vault` | backend_authority (signer) | Replaces `create_vault_points_period` (removed) |

Rider-value instructions use a different authority direction:

| Instruction | Authority | Additional Constraints |
|------------|-----------|----------------------|
| `configure_balance_vault_authority` | rider wallet (signer) | Binds one signer and nonzero policy hash for at most seven days; rotation advances generation and resets nonce |
| `revoke_balance_vault_authority` | rider wallet (signer) | Revokes immediately, advances generation, and clears the RiderBalance session header |
| `deposit_cal_from_balance` | configured rider-session signer | Exact rider, Vault, CAL base units, generation, nonce, and expiry are hash-bound and consumed once |
| `withdraw_cal_to_balance` | configured rider-session signer | Exact rider, Vault, LP base units, generation, nonce, and expiry are hash-bound and consumed once |
| `create_vault_from_balance_cal_usdc` | configured rider-session signer | Exact rider, new Vault ID, configured CAL and USDC base units, generation, nonce, and expiry are hash-bound and consumed once |

The fee payer, Backend Authority, Rider Account login, and custody PDAs are not
rider consent. `AppBalance` in the legacy authority enum is an
unconfigured/default state and cannot execute these value actions. ABI `0x44`
is the first interface that enforces this boundary on-chain.

ProgramConfig V3 stores POL and treasury token account addresses. These are set via `configure_treasury_accounts` (admin-only) and validated during distribution to prevent fund redirection.

---

## 10. Anti-Cheat

### Primary: Community Tribunal

Anti-cheat resolution is decentralized:

1. Local Legends flag suspicious rides
2. Local Legends vote on flagged rides
3. Clean vs. Doped determination
4. Conservative approach — prefer false negatives to false positives
5. Community decides, not algorithm

### Secondary: Bio-Passport (Post-Launch)

- Critical Power model tracks user over time
- Anomaly detection flags statistical outliers
- **Shadow banning** for suspicious activity (ride stays visible, no earning)

### Natural Sybil Resistance

**Power meter requirement creates economic barrier:**

- Power meters cost $300-1,000+
- Power data required for TSS calculation
- Power data very hard to fake vs GPS
- Device fingerprinting for verification
- Mathematical validation against expected power curves

### Validation Rules

| Check | Threshold |
|-------|-----------|
| Speed cap | No segments > 80 km/h |
| Segment matching | Within 50m of start/end |
| Device verification | Fingerprinting enabled |

---

## 11. Technical Reference

This retained reference describes CAL-vault accounts and constants, not a
deployed stage-1 module. The **ratified 6–13 Oct 2026** target is
[§1a](#1a-hill-bonding); deployment remains gated ([STAGE1_SPEC §9][HB-S1]).

### Deployed Programs (Devnet)

> **Source of truth:** `protocol/anchor/addresses.devnet.json`

| Program | Address |
|---------|---------|
| boulder_rollers | `EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH` |
| *(archived)* dung_mint | `A1pDYofjye4TUYNLvM3T6rBaDygQasqKmXmgVLjvLCkZ` |
| *(archived)* proof_verifier | `Bd3oT5xavVXpYTwYQ8ZbE6VphGt8Pg48aD4sojTwiiaC` |

### Token Mints (Devnet)

| Token | Address | Decimals |
|-------|---------|----------|
| CAL | `4bxTCxEQp993cXs5nqhfWthRCPSTDv5K6PMgsfunEaJh` | 9 |
| DUNG | `CqDFJWLpr49tB8xjHegy5JR5jwMCfmhicjuWawtKLeCk` | 9 |

### Key PDAs (Devnet)

| Account | Address |
|---------|---------|
| ProgramConfig | `3CJZG9H6e8pZZ6ey2K7PAiyDgsLiHTWH1gsSrJDqehmG` |
| Treasury DUNG ATA | `Ag6YsS8GTTDYF2DUWuet1SBu3ZcoThjK8Dym7BoWdZfx` |
| POL DUNG ATA | `5kwC6G8zqoTnWJqFyH59ABsVnniFYJxm9Wn8Y6XpadjF` |

### PDA Seeds

| Account | Seed | Derivation |
|---------|------|------------|
| Vault | `VAULT_SEED` | `[VAULT_SEED, &vault_id.to_le_bytes()]` |
| VaultStake | `VAULT_STAKE_SEED` | `[VAULT_STAKE_SEED, user, &vault_id.to_le_bytes()]` |
| VaultLeaderboard | `VAULT_LEADERBOARD_SEED` | `[VAULT_LEADERBOARD_SEED, &vault_id.to_le_bytes()]` |
| LocalLegend | `LOCAL_LEGEND_SEED` | `[LOCAL_LEGEND_SEED, &vault_id.to_le_bytes()]` |
| BeetleCard | `BEETLE_CARD_SEED` | `[BEETLE_CARD_SEED, owner, card_type, scope_id]` |
| UserState | `USER_SEED` | `[USER_SEED, owner]` |
| DungMintState | `DUNG_MINT_STATE_SEED` | `[DUNG_MINT_STATE_SEED]` |

```rust
// Seed constants
pub const USER_SEED: &[u8] = b"user";
pub const VAULT_SEED: &[u8] = b"vault";
pub const VAULT_COUNTER_SEED: &[u8] = b"vault_counter";
pub const VAULT_LP_MINT_SEED: &[u8] = b"vault_lp";
pub const VAULT_COMPLETION_SEED: &[u8] = b"vault_completion";
pub const VAULT_STAKE_SEED: &[u8] = b"vault_stake";
pub const VAULT_LEADERBOARD_SEED: &[u8] = b"vault_leaderboard";
pub const LOCAL_LEGEND_SEED: &[u8] = b"local_legend";
pub const BEETLE_CARD_SEED: &[u8] = b"beetle_card";
pub const DUNG_MINT_STATE_SEED: &[u8] = b"dung_mint_state";
```

### Key Account Structures

**UserState (legacy view; CAL balance deprecated):**
```rust
pub struct UserState {
    pub owner: Pubkey,
    pub legacy_cal_snapshot: u64,
    pub legacy_cal_earned_today: u64,
    pub legacy_last_cal_mint: i64,
    pub total_rides: u64,
    pub total_tss: u64,
    pub bio_score: u64,
    pub bump: u8,
}
```

**Vault:**
```rust
pub struct Vault {
    pub id: u64,
    pub signature: [u8; 64],      // 64-byte climb signature
    pub signature_hash: [u8; 32], // SHA256 for PDA
    pub minter: Pubkey,
    pub name: [u8; 64],
    pub vert_m: u32,
    pub distance_m: u32,
    pub avg_gradient_pct: u16,
    pub kom_holder: Pubkey, // Transitional scalar; deterministic representative rollout pending
    pub kom_time_s: u32,
    pub created_at: i64,
    pub minter_rights_expire: i64,
    pub total_cal_tribute: u64,
    pub pending_rewards: u64,
    pub bump: u8,
}
```

### Constants Reference Table

| Constant | Value | Description |
|----------|-------|-------------|
| `DUNG_DECIMALS_MULTIPLIER` | 1,000,000,000 | 1 DUNG with 9 decimals |
| `CAL_TO_DUNG_THRESHOLD` | 1,000 | CAL needed for 1 DUNG |
| `VAULT_CREATION_CAL` | 1,000 | CAL to create vault |
| `VAULT_CREATION_USDC` | 2,000,000 | $2 USDC (6 decimals) |
| `VAULT_CREATION_DUNG` | 100 DUNG | DUNG option for creation |
| `MINTER_RIGHTS_EPOCHS` | 12 | ~84 days metadata control |
| `EPOCH_DURATION_SECONDS` | 604,800 | 7 days |
| `EPOCH_ANCHOR` | 1704110400 | Ratified target: Mon Jan 1 2024 12:00 UTC; landed clock contract, deployment follows the cutover runbook |
| `LOCAL_LEGEND_TERM_EPOCHS` | 8 | ~56 days |
| `LOCAL_LEGEND_SHARE_BPS` | 300 | 3% |
| `HARVEST_FEE_BPS` | 500 | 5% |
| `MINIMUM_STAKE` (vault) | 100 | 100 CAL |
| `EPOCHS_PER_HALVING` | 26 | ~6 months |
| `MAX_MERKLE_PROOF_DEPTH` | 16 | Up to 65,536 leaves |

### Database Tables (Key Schema)

**Chain-indexed tables** (populated by TS indexer from on-chain PDA state):

```sql
-- On-chain vault state (indexer-populated)
indexed_vaults (
    signature_hex CHAR(128),
    signature_hash_hex CHAR(64),
    minter TEXT, name TEXT,
    vert_m INTEGER, distance_m INTEGER, avg_gradient_pct DECIMAL,
    kom_holder TEXT, -- Transitional scalar; never sufficient to enumerate co-KOMs
    kom_time_s INTEGER, pda TEXT
)

-- Staking positions (indexer-populated)
indexed_stakes (vault_pda TEXT, wallet TEXT, cal_staked BIGINT, lp_tokens BIGINT)

-- Leaderboard state (indexer-populated)
indexed_leaderboards (vault_pda TEXT, rank INTEGER, wallet TEXT, best_time_seconds INTEGER)

-- Local Legend state (indexer-populated)
indexed_legends (vault_pda TEXT, holder TEXT, elected_epoch BIGINT, term_end_epoch BIGINT)

-- Supply state (indexer-populated)
indexed_supply (
    max_supply NUMERIC,
    total_minted NUMERIC,
    total_burned NUMERIC, -- Boulder Roller program-burn telemetry
    spl_mint_supply NUMERIC, -- canonical circulating base units
    chain_slot BIGINT, -- DungMintState observation
    spl_mint_supply_slot BIGINT -- independent SPL mint observation
)
```

**Off-chain tables** (backend-managed):

```sql
-- Economic event ledger (dual-write with on-chain)
economic_events (wallet TEXT, event_type TEXT, amount BIGINT,
    tx_signature TEXT, reference_type TEXT, reference_id TEXT)
```

The API reads from `indexed_*` tables for all chain state. The indexer is the sole writer to these tables.
The legacy `dung_supply_state` table and its SQL helpers remain migration
history, not cap, emission, burn, or circulating-supply authority. Caps are
enforced by `DungMintState`; circulating supply is read from the SPL mint.

---

## 12. Appendix: Document Deprecation

### This Document Supersedes

| Document | Status | Notes |
|----------|--------|-------|
| `docs/spec2025.md` | **DEPRECATED** | Founder interview synthesis, many values outdated |
| `docs/TOKENOMICS_V2.md` | **DEPRECATED** | Good but parameters now in code |
| `docs/DUNG_BEETLE_CYCLING_COMPLETE.md` | **DEPRECATED** | Original pitch deck format |
| `docs/PLATFORM_FEATURE_MATRIX.md` | **DEPRECATED** | Pre-architecture decisions |

### Source of Truth Hierarchy

When documents conflict, prefer in this order:

| Priority | Source | Purpose |
|----------|--------|---------|
| 1 | `docs/PROTOCOL_TRUTHS.md` (+ `MOBILE_TRUTHS.md` / `BACKEND_TRUTHS.md` per lane) | Canonical semantics — wins on any conflict |
| 2 | `protocol/anchor/programs/boulder_rollers/src/lib.rs` | Code-level constants |
| 3 | This document (`FRESHEST_SPEC.md`) | Internal engineering/economics detail |
| 4 | `docs/design/LANGUAGE_SPEC.md` | User-facing language and visibility |
| 5 | `docs/gitbook/` | Public-facing documentation |

### Key Differences from Prior Docs

This comparison is retained CAL-vault history. Its creator-reward, paid
activation and CAL-deposit assumptions are superseded for bonded hills by
[§1a](#1a-hill-bonding), **ratified 6–13 Oct 2026** ([DESIGN][HB-DESIGN];
[STAGE1_SPEC][HB-S1]).

| Topic | Old Value | Current Value |
|-------|-----------|---------------|
| Soigneur seats | 3 per vault (Swanny) | 1 per vault |
| Soigneur lock | 1,000 DUNG required | No lock (merit-based) |
| Creator reward | Separate 10% forever | Soigneur 3% for first term only |
| Minter rights | Forever | 12 epochs (~84 days) |
| Protocol mode | Shadow simulation | Live on devnet (shadow gates removed) |
| Minimum deposit | Various | 100 CAL (vaults) |
| Climb/Vault identity | Detector signature | D12 canon commitment + exact Climb-to-Vault binding |
| Anti-cheat primary | Algorithmic CP model | Community tribunal |
| BeetleCard reset | Prestige considered | No catch-up ever |

---

## 13. Frozen Design Inventory

> **Why this section exists (Tim, 2026-07-05):** these designs are a good start on the final shape of the idea — not set in stone, and not active roadmap, but real progress we don't throw away. Nothing here has a date, a commitment, or a claim on current engineering time. Revisit when the First Cohort loop is proven and (for liquidity items) only if a liquidity trigger is ever met. Do not cite this section as justification for building; cite it to avoid re-deriving old thinking.

### 13.1 Supply Allocation Sketch (liquidity era)

For future bonded-hill DUNG, these lifetime/category caps are superseded by
constant issuance, **ratified 8 Oct 2026** ([DIAMOND][HB-DIAMOND];
[§1a cutover](#1a-hill-bonding)). The historical allocation sketch remains below.

Working sketch of eventual supply distribution. No investors exist; no unlock event is planned. The category caps are enforced in deployed code (see §8) — this table is the *story* that once accompanied them.

| Allocation | Amount | Percentage | Sketch notes |
|------------|--------|------------|-------|
| Community | 400,000,000 | 40% | Full unlock at any future distribution event (Hyperliquid-style, no vesting) |
| Treasury | 250,000,000 | 25% | Unlocked as needed |
| Founder/Team | 200,000,000 | 20% | Full unlock, no vesting |
| Investors | 100,000,000 | 10% | Placeholder — no investors or commitments exist |
| POL Liquidity | 50,000,000 | 5% | Protocol-owned, never sold |

### 13.2 Rake & Treasury Flywheel (liquidity era)

For hill bonding, the fee and voting assumptions below are superseded by the
yield-only fee and pool-only votes, **ratified 6 Oct 2026** ([DESIGN][HB-DESIGN];
[§1a](#1a-hill-bonding)). This frozen sketch does not add a stage-1 fee.

- **Fee channels:** 10% of vault settlement → treasury; 5% collect fee → treasury; 0.5% withdraw fee → burn/POL split (fee itself still ⚠️ unimplemented).
- **Deployment split (governance-adjustable):** ~40% direct burn (deflation proportional to activity), ~60% growth deployment (regional performance pots, vault bootstrapping, seasonal incentives).
- **Fiat revenue buybacks:** external revenue (sponsors, data licensing, partnerships) buys DUNG on-market and burns it — external buy pressure verifiable on-chain.
- **Governance:** DUNG holders vote on burn/growth split, CAL:DUNG ratio, fee structure.
- **Treasury allocation sketch:** 40% founder/team, 30% development, 20% marketing/growth, 10% reserve.

### 13.3 BeetleCard Progression Economy

Score accrual is live on-chain; everything below is frozen design.

**Level thresholds and upgrade burns** (`25 × 2^(N-1)` DUNG, 100% burned):

| Level | Score Required | DUNG Burn | Cumulative | Gate |
|-------|----------------|-----------|------------|------|
| 1 | 100 | - | - | - |
| 2 | 500 | 25 | 25 | - |
| 3 | 1,500 | 50 | 75 | - |
| 4 | 5,000 | 100 | 175 | - |
| 5 | 15,000 | 200 | 375 | 50km/week badge |
| 6 | 50,000 | 400 | 775 | - |
| 7 | 150,000 | 800 | 1,575 | 10 segment challenges |
| 8 | 500,000 | 1,600 | 3,175 | Top 10 any segment |
| 9 | 1,500,000 | 3,200 | 6,375 | 30-day streak |
| 10 | 5,000,000 | 6,400 | 12,775 | Elite Gate |

**Level 10 Elite Gate (all required):** 5+ simultaneous KOMs; 4.0+ w/kg verified; 60-day streak; 50,000+ lifetime TSS. Revocable with 30-day grace if KOMs lost.

**Visual design:** Pokemon-card layout, accessories rendered on beetle avatar, 8 accessory categories, clean not cluttered.

**Cosmetic system (was already shelved to 50K+ MAU):** account-bound (Fortnite model), 100% burn on purchase, soulbound card + earned badges vs purchased cosmetics, seasonal drops on the cycling calendar, season pass as primary vehicle. March 2026 modeling: cosmetics <4% of burns below 50K users; BeetleCard upgrades dominate at 93–96%.

**Spec-vs-code gap (preserved):** spec upgrades burn DUNG; deployed code gates levels by effort thresholds (`LEVEL_THRESHOLDS`). Reconcile if/when this system thaws.

### 13.4 Rider Archetypes

Six classes (Sprinter/Puncheur/Breakaway/Rouleur/Climber/GC) derived from power profile; matchup cycle; weight enforcement. Full RFC: `docs/rfcs/RIDER_ARCHETYPES.md`. Frozen — demand-side design awaiting a demand side.

---

## Document History

| Date | Version | Changes |
|------|---------|---------|
| 2026-10-15 | 2.12 | **Pay is sent automatically.** Tim ratified that the keeper submits every registered rider's claim once a week is final and closes the week's records to recover their rent, after the release review measured permanent weekly-record rent at about 6.7 SOL a year for 10 hills under rider-initiated claiming. Riders sign only to register. Implementation is pending on PR #96 and the keeper. |
| 2026-10-13 | 2.11 | **Stale tokens count as zero.** Tim ratified, after the milestone 1a custody review, that a stale staking token counts as zero toward a hill's bonding line instead of blocking pledges or the bond. Lots in a token that is stale at bond time are not founding lots; they stay cancellable until their owner converts them into ordinary stake. The STAGE1_SPEC amendment is pending on the custody branch. |
| 2026-10-13 | 2.10 | Folded the 6–13 Oct ratified hill-bonding decisions into §1a with diamond/spec sources, explicit offline/deployed boundaries, pending cap-basis and stale-rate-exit amendments, prospective supersession and preserved CAL-vault liabilities. |
| 2026-10-07 | 2.9 | **Separate direction from current record visibility.** Clarified that the no-money loop wherever canon compiles is the direction; records currently show only on climbs with a live Vault. |
| 2026-10-06 | 2.8 | **The no-money loop runs anywhere; the end state is a loop that opens itself.** Tim ratified (`boulderroller-v2-klrj.19`): on hills nobody has bonded, records and the Local Legend run wherever canon compiles, so the city trigger gates money only. Recorded the end state, a zero-start loop that opens itself wherever its ingredients exist, measured by the steps a new place still needs from BoulderRoller by hand; permission to pay riders is settled per jurisdiction. |
| 2026-10-06 | 2.7 | **Philadelphia first, not only.** Under the hill-bonding proposal, rider pay comes from backers' staking yield, so a Philadelphia-only limit would cap the backer side as well as the rider side. Tim ratified a split (`boulderroller-v2-klrj.18`): money flows start in Philadelphia; demand is open everywhere, with no money moving until counsel clears public deposits, and it decides where canon is compiled next; a city opens when its canon is ready and enough of its hills reach the bonding line. Rewrote the First Cohort spine paragraph. |
| 2026-07-21 | 2.6 | **Co-KOM semantics ratified; implementation pending.** Ratified crown and `T-1` recognition for every seated rider tied at the fastest validated whole-second time; preserved rtie competition ranks, ten seats, pooled payout bytes and percentages, and the ABI; targeted singular `kom_holder` as a deterministic legacy representative; recorded the deployed post-Founder metadata coupling and made its authority/ABI rollout a prerequisite to equal-time scalar rotation. |
| 2026-07-05 | 2.4 | **Zero-start alignment.** Removed TGE as a horizon everywhere (Tim ditched TGE pre-July for zero start; liquidity decisions are trigger-based, never dated). Purged Motion/MOMO rebrand (rejected). Added Zero-Start Posture and First Cohort spine (Philadelphia is the product, epic `klrj`). Recorded canon-first climb identity (epic `4crx`): vault signature becomes canon commitment, detector tuning frozen, rides are evidence not identity. Moved liquidity-era and frozen designs (allocation sketch, rake flywheel, treasury plan, BeetleCard progression, archetypes) into new Frozen Design Inventory (§13). Fixed source-of-truth hierarchy to put the TRUTHS trio first. Updated production surfaces to boulderroller.xyz. |
| 2026-03-24 | 2.3 | Protocol status updated to LIVE on devnet. Remove all shadow mode / simulation / pre-alpha language — live is the only code path. Update program ID, token mints, and PDA addresses to current devnet deployment. Add canonical_v2 detection engine status (90.8% recall, F1=0.777). Add GPS-gated matching details. Update database schema to reflect indexer-populated `indexed_*` tables. Adopt Deposit/Withdraw/Collect language per LANGUAGE_SPEC.md. Add BoulderScan as separate product surface. |
| 2026-03-04 | 2.2 | Add DUNG Demand & Sustainability Model (Section 10). Mark CAL:DUNG ratio as governance-adjustable monetary policy lever. Replace phased fee destinations with rake flywheel model (40% burn / 60% growth deployment, governance-adjustable). Update BeetleCard cosmetics to account-bound (Fortnite model), shelved until 50K+ MAU. Add regional performance pots concept. Based on quantitative supply modeling, DePIN sink research, and game theory analysis. |
| 2026-01-21 | 2.1 | Remove vesting (100% at TGE Hyperliquid-style), remove Soigneur inactivity penalty (hallucination), mark conversion UI as deferred |
| 2026-01-21 | 2.0 | Initial comprehensive spec, supersedes all prior docs |

---

**This document is the internal source of truth for Boulder Rollers. All implementation should reference this spec. Code constants take precedence for any parameter values.**
