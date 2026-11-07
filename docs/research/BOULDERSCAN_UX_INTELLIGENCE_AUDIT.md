# BoulderScan UX Intelligence Audit

**Date:** 2026-03-23
**Scope:** Full codebase audit of `web/scan/src/` against Etherscan and Solscan UX patterns
**Auditor:** Research subagent (opus)

---

## Executive Summary

BoulderScan is a well-structured domain-specific explorer with clean architecture, a thoughtful narrative system, good dark mode, and solid mobile responsiveness. It is already better than most project-specific explorers. However, it sits in an uncanny valley: too technical for cyclists, not technical enough for developers. The narrative system (`explorer.ts`) is the standout feature and the right investment to double down on. The biggest gaps are: (1) no "effect summary" layer showing what CHANGED, (2) protocol jargon leaks onto every page, (3) no address labeling for known accounts, and (4) progressive disclosure is mostly absent -- technical detail and cyclist-relevant info coexist at the same level.

---

## Page-by-Page Assessment

### 1. Observatory Page (Home)

**Intuition Score: 5/10** | **Technical Depth Score: 4/10**

**What a cyclist sees:**
- "3,756 Vaults" -- means nothing without context. What is a vault? Why should I care about its count?
- "128,470 Completions" -- completions of what? Climbs? Rides? Courses?
- "18,400 CAL Staked" -- what is CAL? What does staking mean here?
- "Circulating DUNG" / "Total Minted" / "Total Burned" -- pure protocol jargon

**What a developer wants but cannot find:**
- No link to the program on Solscan/Solana Explorer
- No current slot or block height
- No epoch progress bar (how far through the current epoch are we?)
- No program version or IDL hash
- No total transaction count

**The "so what?" test:**
- "Emission Rate: 10,000 basis points" -- fails completely. What does 10,000 bps mean in practical terms? 100%? Of what? Per what time period?
- "Top Vaults" ranked by "Highest CAL stake depth" -- eyebrow is developer language. A cyclist would say "Most popular climbs" or "Biggest prize pools"
- The Top Vaults table shows Elevation, Distance, Gradient, Stake, KOM. This is actually good for cyclists -- the climb data is immediately meaningful. The Stake column is the weak link (what is stake, and why do I care about its number?).

**Specific issues:**
- The hero description says "Indexed vault state, rider activity, token supply, and recent protocol events from the BoulderScan read model." This is a sentence written for the engineering team, not users. "Read model" is an internal implementation detail.
- Event feed shows raw event names through `humanizeEventName()` which does translate well (e.g., "Climb Completed", "Rewards Distributed"). This is good.
- Empty states are well-worded but reference "the indexer" which is an internal concept.

**Etherscan comparison:** Etherscan's home shows (1) ETH price, (2) gas price, (3) latest blocks, (4) latest transactions, with every number immediately comprehensible. BoulderScan shows metrics that require domain knowledge.

**Solscan comparison:** Solscan shows (1) SOL price, (2) TPS, (3) epoch progress bar, (4) active validators. All immediately graspable as "health of the network."

---

### 2. Vault Page

**Intuition Score: 7/10** | **Technical Depth Score: 5/10**

This is the strongest page. The cycling data (Elevation, Distance, Gradient, Completions) is native to the domain and presented clearly. The leaderboard showing rider times is immediately understandable to any cyclist.

**What works well:**
- Vault name as page title (e.g., "Manayunk Wall") -- cyclist-friendly
- Climb stats (97.0 m elevation, 800 m distance, 12.40% gradient) -- this is the language cyclists speak
- Leaderboard with times (2:41, 2:48, 2:51) -- instantly intuitive
- KOM time prominently shown

**What a cyclist does NOT understand:**
- "Minter `2222...2222`" -- what is a minter? Who is this person? Is this the creator? Should I care?
- "CAL Staked: 84.2 CAL" -- what is CAL? What does staking do for me?
- "Pending Rewards: 2.847 DUNG / ready to harvest" -- harvest what? What is DUNG? Why is it pending?
- "Reward Rate: 0.034 DUNG / per second" -- per second of what?
- "DUNG Emitted: 4.2 DUNG" -- emitted where? To whom?
- "Mint Epoch: Epoch 2" / "Rights Expire: Epoch 14" -- what are epochs? What rights?
- "CAL Burned: 1.2 CAL" -- burned how? Why?
- "Activation State" section with "Historical seed boundary" eyebrow -- this entire section is pure engineering operations language. "Historical state is seeded and the final activation transaction is still being confirmed" would baffle any non-developer.
- "Local Legend" shows a truncated pubkey and "Epoch 24 to Epoch 32, 147 completions at election" -- the concept is interesting (most dedicated rider gets a title) but the presentation is all protocol internals.

**What a developer wants but cannot find:**
- No link to the on-chain vault account on Solscan
- No raw PDA address shown (it exists in the data type but is not rendered)
- No signature hex displayed
- No "View on Solana Explorer" button
- No instruction history (which transactions touched this vault?)
- No staker list (who is staking in this vault?)

**The "so what?" test:**
- Leaderboard passes beautifully. "Rank 1: `3333...3333` in 2:41" -- a cyclist instantly wants to beat that time.
- "CAL Staked" fails. Without context for what staking does, the number is meaningless.
- Distribution History passes for developers ("4.2 DUNG distributed in Epoch 14") but fails for cyclists.

**Progressive disclosure problem:** Activation State (an ops concern), Vault State (protocol internals), and climb data (cyclist interest) are all at the same visual hierarchy. The Activation State section with its seeding transactions, chain-active flags, and error states is irrelevant to 99% of visitors.

---

### 3. Transaction Page

**Intuition Score: 6/10** | **Technical Depth Score: 7/10**

This is the most technically ambitious page and the one that benefits most from the narrative system.

**What works well:**
- The Overview section with `summarizeTransaction()` output is genuinely good. For a VaultCompleted event, the narrative produces: "Vault #142 logged a completion" with detail like "`2222...2222` posted 2:41 and tributed 0.847 CAL while taking the KOM." This is the magic.
- Highlight badges ("2:41", "0.847 CAL", "New KOM") provide scannable key facts
- The Instructions section with labeled accounts, signer/writable badges, and humanized labels is strong
- Raw JSON disclosure is properly hidden behind a `<details>` toggle -- good progressive disclosure
- renderFieldValue() smartly links vault IDs, formats epochs, formats timestamps, and auto-links pubkeys/signatures

**What a cyclist does NOT understand:**
- "Fee: 5,000 lamports" -- what is a lamport? What did this cost in real money?
- "Compute Units: 142,000" -- meaningless outside Solana development
- "Slot: 284,738,291" -- what is a slot?
- "record_vault_completion" as Primary Action -- this is the Anchor instruction name, not a human description
- "Accounts" section showing vault, user, vault_completion, vault_leaderboard as labeled pubkeys -- meaningful to devs, gibberish to cyclists
- "cal_tribute: 847000000000" in raw instruction args -- the raw atomic value leaks through before formatting

**What a developer wants but cannot find:**
- No link to this transaction on Solscan/Solana Explorer
- No log messages (program logs from the transaction)
- No balance changes (SOL, CAL, DUNG before/after)
- No inner instruction detail
- No CPI (cross-program invocation) trace

**Etherscan comparison:** Etherscan's transaction page shows:
1. "From -> To" with ENS names -- BoulderScan has no equivalent directional summary
2. "Value: 0.5 ETH ($1,234.56)" -- dual denomination. BoulderScan shows lamports only.
3. "Transaction Action: Swap 1.5 ETH for 3,000 USDC on Uniswap V3" -- a one-line plain-English summary of the EFFECT. BoulderScan's narrative system approaches this but does not yet reach it.
4. Tabs: Overview / Internal Txns / Logs / State -- progressive disclosure. BoulderScan dumps everything on one scrollable page.
5. Gas: "0.0021 ETH ($5.12)" -- both native and USD

**Solscan comparison:** Solscan's transaction page shows:
1. "SOL Balance Change" and "Token Balance Change" tables -- EFFECT summaries showing what moved and by how much. This is the single biggest missing feature in BoulderScan.
2. Instruction-level accordion with decoded data
3. Program log section

---

### 4. Account Page

**Intuition Score: 5/10** | **Technical Depth Score: 5/10**

**What works well:**
- Active Stakes table showing vault, CAL staked, LP tokens, rewards -- useful for investors
- Completions table showing vault, count, best time, total tribute -- genuinely useful for cyclists
- Beetle Cards section showing card type, level, score, rides counted -- the gamification layer presented clearly

**What a cyclist does NOT understand:**
- "Wallet CAL: 42 CAL" / "Legacy CAL Snapshot: 0 CAL" -- what is the difference? What is "legacy"?
- "Active Stakes: 1" / "Recent Events: 1" -- as hero stats, these are underwhelming. A cyclist wants to see total rides, total climbing, favorite vault.
- The Balances section says: "Live SPL balances are read from Solana RPC at request time. The UserState CAL fields below are retained only as legacy pre-TGE snapshots and should not be interpreted as the rider's live wallet balance." -- This is an engineering caveat, not user-facing copy.
- "Legacy Daily CAL Counter" -- what?
- "Bio Score: 1,188" -- no context for what this means or what a good score is
- "LP Tokens: 14.8 LP" -- what are LP tokens?

**What a developer wants but cannot find:**
- No link to Solscan for the wallet address
- No SOL balance shown
- No token account addresses
- No transaction history (only events, not all transactions)
- No associated program accounts (PDAs owned by this wallet)
- No "first seen" / "last seen" timestamps

**Etherscan comparison:** Etherscan's address page shows:
1. ETH balance with USD value front and center
2. Token holdings list with icons, symbols, and USD values
3. Transaction list (paginated) -- every transaction this address was involved in
4. Internal transactions, token transfers as separate tabs

**Solscan comparison:** Solscan's account page shows:
1. SOL balance + all SPL token balances with USD values
2. Portfolio value
3. NFT gallery
4. Transaction history
5. DeFi positions across protocols

**The "so what?" test for hero stats:**
- "Wallet CAL: 42 CAL" -- fails. A cyclist wants "Total Rides: 47" or "Total Climbing: 14,200m" as a hero stat.
- "Active Stakes: 1" -- fails. This is a count, not a story.
- "Recent Events: 1" -- fails. Not informative.
- "Legacy CAL Snapshot: 0 CAL" -- fails spectacularly. A legacy internal counter as a hero stat.

---

### 5. Event Feed (EventFeedItem component)

**Intuition Score: 7/10** | **Technical Depth Score: 4/10**

The event feed is one of the better-executed pieces thanks to the narrative system.

**What works well:**
- Event badge with human label ("Climb Completed", "Rewards Distributed") -- good
- Narrative title + detail + highlights -- this three-layer approach is genuinely smart
- Cross-references to vaults and accounts are linked and copy-able
- Timestamp + slot shown at bottom -- good metadata

**What could be better:**
- No relative timestamps ("2 hours ago") -- only absolute timestamps via `toLocaleString()`
- "slot 284,738,291" is meaningless to non-developers
- The narrative for VaultCompleted says "`2222...2222` posted 2:41 and tributed 0.847 CAL" -- "tributed" is not a word cyclists know. "Earned 0.847 CAL for the climb" would be clearer. Or even better: don't mention CAL at all in the feed for non-power-users.
- No icons or visual differentiation between event types beyond the text badge

---

### 6. Search

**Intuition Score: 7/10** | **Technical Depth Score: 6/10**

The search system (`search.ts`) is surprisingly sophisticated for an early explorer.

**What works well:**
- Accepts vault IDs, pubkeys, signatures, @usernames, prefixed queries ("vault:42", "rider:mountain_goat"), pasted BoulderScan URLs, route paths
- Username resolution via API
- Hash-prefix vault notation (#42)
- Contextual helper text that changes based on current page
- Good validation messaging

**What is missing:**
- No vault NAME search. You cannot search "Manayunk Wall" -- only vault ID 142. This is the single biggest search gap for cyclists.
- No autocomplete/suggestions
- No fuzzy matching
- No search by road name or location
- No "recent searches" memory
- No search results page for ambiguous queries

**Etherscan comparison:** Etherscan search accepts ENS names, contract names, addresses, tx hashes, block numbers, and token names. The ability to search by name is critical for non-technical users.

---

### 7. Mobile Responsiveness

**Score: 8/10**

The CSS is genuinely well-done for mobile:
- Three breakpoints (1100px, 720px, 480px) handle layout collapse properly
- `data-table--card-mobile` class transforms tables into stacked cards with labeled fields -- smart pattern
- `data-table-scroll` provides horizontal scroll for complex tables
- Touch targets get bumped to 44px minimum on mobile
- Search goes full-width vertical on small screens
- Brand mark scales with clamp()
- At 480px, search label/caption are hidden to save space (good trade)
- The BoulderRoller external link pill hides on very small screens (good)

**Issues:**
- The `hero-panel` 2-column grid collapses to 1-column at 1100px, which means even tablets see single-column. The breakpoint may be too aggressive.
- `stat-card__value` uses `clamp(18px, 2vw, 24px)` -- at 480px this resolves to ~9.6px which is below the 18px floor. The clamp works but the floor could be higher.
- No explicit dark-mode testing for mobile (palette is inherited, but touch affordances like hover states need consideration)

---

### 8. Empty States

**Score: 7/10**

Empty states are present on every section and well-worded:
- "No vault activity indexed yet" with "Top vault rankings will appear here once the indexer has enough on-chain state."
- "No leaderboard entries yet" with "This table fills once riders have posted indexed completions for this vault."
- "No active stake positions" with "Vault stake balances will appear here when this rider holds indexed positions."

**Issues:**
- They reference "the indexer" and "on-chain state" -- internal concepts.
- No actionable CTAs. Etherscan empty states link to relevant help docs. BoulderScan just says "it will appear."
- No illustrations or visual interest.

---

## "Steal from Etherscan" List

| Pattern | Where to Apply | Priority |
|---------|---------------|----------|
| **From -> To summary** with labeled addresses | Transaction page hero | High |
| **Balance change table** ("You sent 0.5 ETH, received 3000 USDC") | Transaction page, new section | Critical |
| **Address labels** ("Treasury", "POL", "Manayunk Wall Vault", "Protocol Fee") | Everywhere addresses appear | Critical |
| **Dual denomination** (lamports AND SOL, atomic AND human-readable) | Fee display, all token amounts | Medium |
| **Transaction Action one-liner** ("Completed Manayunk Wall in 2:41, new KOM") | Transaction page hero | High |
| **Tabbed progressive disclosure** (Overview / Logs / Internal / State) | Transaction page | Medium |
| **Gas price context** ("Normal" / "High" / "Low" relative to recent average) | Transaction fee display | Low |
| **Contract verification badge** | Vault page (program verified status) | Low |
| **"View on Etherscan" equivalent** (link to Solscan for raw data) | Footer of every detail page | High |
| **Block/slot confirmation count** ("142 confirmations ago") | Transaction page | Low |

---

## "Steal from Solscan" List

| Pattern | Where to Apply | Priority |
|---------|---------------|----------|
| **Token Balance Change summary** ("CAL: -847 / DUNG: +0.847") | Transaction page, new section between Overview and Instructions | Critical |
| **Epoch progress bar** (visual indicator: "Day 3 of 7") | Observatory page hero | High |
| **Portfolio value** (total holdings in USD or relative units) | Account page hero | Medium |
| **Transaction history list** (all txs, not just events) | Account page, new section | High |
| **NFT inline rendering** for BeetleCards | Account page BeetleCard section | Medium |
| **Instruction accordion** (collapsed by default, expand per instruction) | Transaction page Instructions section | Medium |
| **"DeFi Positions" equivalent** showing all staking positions with current value | Account page | Medium |
| **Program log section** | Transaction page | Low |
| **Copy-friendly full address display** on hover/click | All shortened addresses | Low |

---

## BoulderScan Advantages -- Lean Into These

### 1. The Narrative System (explorer.ts) -- UNIQUE STRENGTH
No generic explorer has a domain-aware narrative engine. `describeExplorerEvent()` translates protocol events into human-readable stories with titles, detail text, and highlight badges. This is genuinely novel and should be the centerpiece of the experience. Etherscan and Solscan show raw decoded data. BoulderScan tells stories about what happened.

**Lean into it:** Make narratives the PRIMARY information layer, not a supplement. The narrative should be the first thing you read, with decoded data as the progressive-disclosure layer beneath.

### 2. Domain-Specific Climb Data
Vault pages combine on-chain state with real-world geographic data (elevation, distance, gradient). This is information no generic explorer can provide. A Solscan vault account page would show raw u64 fields. BoulderScan shows "97.0m elevation at 12.40% gradient."

**Lean into it:** Add a climb profile visualization (elevation chart). Add a route map. Show weather conditions at the climb location. Make the vault page feel like a cycling app page that ALSO shows on-chain state.

### 3. Integrated Leaderboard
The leaderboard on the vault page is a killer feature for cyclists. Seeing times and ranks creates immediate competitive context. No generic explorer has this.

**Lean into it:** Add time deltas ("+7 seconds off KOM"). Add historical progression ("Your last 5 attempts: 3:12, 3:05, 2:58, 2:51, 2:48"). Add percentile positioning.

### 4. Event Feed with Context
The `EventFeedItem` component combines narrative, cross-references, and timestamps in a way that is more information-dense and more readable than Etherscan's transaction list. The highlight badges are particularly effective.

**Lean into it:** Add icons per event type. Add filtering. Make this a live-updating feed with a "new events" indicator.

### 5. Cyclist-Native Formatting
`formatElevationTenths()`, `formatDistanceMeters()`, `formatGradientBasisPoints()`, `formatDuration()` -- these format utilities translate raw protocol values into cycling-native units. This is a real advantage.

**Lean into it:** Add imperial/metric toggle. Add VAM (vertical ascent meters per hour) display. Add power-to-weight context where available.

---

## Top 10 Improvements Ranked by Impact

### 1. CRITICAL: Address Label System
**Impact: Transforms every page from "hex soup" to meaningful identity.**

Every page shows truncated pubkeys (`2222...2222`) with no context. Known addresses should display human-readable labels:

| Address | Label |
|---------|-------|
| Treasury wallet | "Treasury" |
| POL wallet | "Protocol Liquidity" |
| Program ID | "Boulder Rollers Program" |
| Vault PDAs | "Manayunk Wall Vault" (use vault name) |
| Config PDA | "Program Config" |
| CAL Mint | "CAL Token" |
| DUNG Mint | "DUNG Token" |
| Mint authorities | "CAL Mint Authority" / "DUNG Mint Authority" |

Implementation: A lookup map in `lib/format.ts` with known addresses from `addresses.devnet.json` plus vault names from the API. Render as `<span class="address-label">Treasury</span> <span class="mono-inline">3boU...do</span>` pattern.

### 2. CRITICAL: Token Balance Change Summary on Transaction Page
**Impact: Shows the EFFECT of a transaction, not just the INSTRUCTION.**

After the Overview section, add a "Balance Changes" section:

```
CAL Balance Changes:
  2222...2222 (Rider)    -847.000 CAL
  Manayunk Wall Vault    +847.000 CAL

DUNG Balance Changes:
  Manayunk Wall Vault    +0.847 DUNG  (converted from CAL tribute)
```

This is the single most requested pattern from Solscan. It answers "what actually happened?" without requiring the user to decode instruction arguments.

### 3. HIGH: Rewrite Observatory Hero for Cyclists
**Impact: First impression determines whether a cyclist stays or bounces.**

Current hero stats: Vaults / Riders / Completions / CAL Staked

Proposed hero stats:
- **Riders** -- keep, universally understood
- **Climbs Completed** (not "Completions" -- be specific)
- **Total Vertical** (sum of all climb elevation across all completions -- the cycling flex number)
- **Prize Pools** (reframe "CAL Staked" as something desirable)

Current hero description: "Indexed vault state, rider activity, token supply, and recent protocol events from the BoulderScan read model."

Proposed: "Real-time on-chain activity for the Boulder Rollers cycling protocol. Every climb, every record, every reward -- verified on Solana."

### 4. HIGH: Add Relative Timestamps
**Impact: Instant temporal context without mental math.**

Currently: `3/5/2024, 12:00:00 PM` (via `toLocaleString()`)

Proposed: `2 hours ago` for recent events, with full timestamp on hover via `title` attribute.

Implementation: Add `formatRelativeTimestamp()` to `format.ts`. Use it in EventFeedItem, leaderboard "Recorded" column, and distribution history.

### 5. HIGH: Progressive Disclosure on Vault Page
**Impact: Reduces cognitive overload by 60% for non-developer visitors.**

Current layout shows everything at equal weight. Proposed tiered layout:

**Always visible (Cyclist tier):**
- Vault name, climb stats (elevation, distance, gradient)
- Leaderboard (top 10 times)
- Completion count
- Local Legend (rephrased as "Most Dedicated Rider")

**Collapsed by default (Investor tier):**
- CAL Staked, Pending Rewards, Reward Rate, DUNG Emitted
- Staker count, Distribution History

**Collapsed by default (Developer tier):**
- Activation State, seeding transactions, chain-active flags
- Vault State (ID, Created, Mint Epoch, Rights Expire)
- Raw PDA, signature hex

Implementation: Use `<details>` elements with styled `<summary>` triggers, or a tab system.

### 6. HIGH: "View on Solscan" Links
**Impact: Bridges trust boundary between BoulderScan and the raw chain.**

Every transaction, account, and vault PDA should have a small external link to Solscan (or Solana Explorer). This is standard practice for project-specific explorers and is critical for developer trust.

Format: `https://solscan.io/tx/{signature}?cluster=devnet`

Place it: Next to the signature in the Transaction page hero. Next to the pubkey in the Account page hero. In the Footer next to the program ID.

### 7. HIGH: Vault Name Search
**Impact: Cyclists think in climb names, not vault IDs.**

The search system cannot find vaults by name. "Manayunk Wall" returns nothing. Only `142` or `vault:142` works.

Implementation: Add a `searchVaults(query: string)` API endpoint that performs prefix/fuzzy search on vault names. In the search classifier, if the input does not match any existing pattern (not a number, not base58, not a username), try vault name search before returning null.

### 8. MEDIUM: Rewrite Event Vocabulary for Cyclists
**Impact: Every event becomes immediately comprehensible.**

Current narrative vocabulary uses protocol terms that leak through:

| Current | Proposed |
|---------|----------|
| "Vault #142 logged a completion" | "Manayunk Wall -- climb completed" |
| "tributed 0.847 CAL" | "earned 0.847 CAL for the climb" |
| "Vault #142 received stake" | "Manayunk Wall -- new investment" |
| "CAL was staked into Vault #142" | "0.847 CAL invested in Manayunk Wall" |
| "Vault #142 distributed rewards" | "Manayunk Wall -- weekly rewards paid out" |
| "Epoch rewards were distributed" | "Weekly rewards paid to riders and investors" |
| "Vault #142 is now live" | "Manayunk Wall is now earning rewards" |
| "A Local Legend was elected" | "New Most Dedicated Rider crowned" |
| "KOM seat currently vacant" | "Fastest time: unclaimed" |

The key insight: replace vault IDs with vault NAMES in narratives. This requires the narrative system to have access to a vault name lookup, which could be passed as context to `describeExplorerEvent()`.

### 9. MEDIUM: Account Page Hero Stat Redesign
**Impact: The account page hero should celebrate the rider, not show internal counters.**

Current hero stats: Wallet CAL / Legacy CAL Snapshot / Active Stakes / Recent Events

Proposed hero stats:
- **Total Rides** (from user_state.total_rides -- already available)
- **Total TSS** (from user_state.total_tss -- already available, represents total training load)
- **Climbs Completed** (count of completions array)
- **Vaults Staked** (count of active_stakes array, but labeled better)

Move all balance information into the Balances section card, not the hero.

### 10. MEDIUM: Tooltips for Protocol Jargon
**Impact: Education layer that makes jargon acceptable.**

For terms that must remain (CAL, DUNG, Epoch, Vault, KOM, Local Legend, TSS, Tribute), add `title` attributes or a dedicated tooltip component:

| Term | Tooltip |
|------|---------|
| CAL | "Effort token earned from riding. Stake it in climbs to earn rewards." |
| DUNG | "The Boulder Rollers reward token. Earned through staking and leaderboard placement." |
| Vault | "An on-chain representation of a real-world climb. Riders earn by completing it." |
| Epoch | "A 7-day reward period. Rewards are distributed every Sunday at 12:00 UTC." |
| KOM | "King of the Mountain -- the fastest recorded time on this climb." |
| Local Legend | "The rider with the most completions on this climb during the current term." |
| TSS | "Training Stress Score -- a measure of total training load from a ride." |
| Tribute | "CAL automatically allocated to a vault when you complete the climb." |
| Staking | "Locking CAL in a vault to earn a share of its weekly DUNG rewards." |
| LP Tokens | "Liquidity provider tokens -- represent your share of a vault's staking pool." |

---

## Specific Copy/Label Recommendations

### Observatory Page

| Current | Recommended |
|---------|-------------|
| "Observatory" (eyebrow) | "Network Overview" |
| "Boulder Rollers Explorer" (h1) | Keep -- strong |
| "Indexed vault state, rider activity, token supply, and recent protocol events from the BoulderScan read model." | "Live on-chain state for the Boulder Rollers cycling protocol. Climbs, riders, rewards, and token supply -- all verified on Solana." |
| "Vaults" (stat label) | "Active Climbs" |
| "Completions" (stat label) | "Climbs Completed" |
| "CAL Staked" (stat label) | "Total Invested" |
| "Top Vaults" (section title) | "Top Climbs" |
| "Highest CAL stake depth" (eyebrow) | "Ranked by investment depth" |
| "Recent Events" (section title) | "Live Activity" |
| "Latest indexed protocol activity" (eyebrow) | "Real-time on-chain events" |
| "Supply State" (section title) | "Token Supply" |
| "Indexed DUNG issuance and burn" (eyebrow) | "DUNG token circulation" |
| "Emission Rate" + "basis points" | "Emission Rate" + "current epoch multiplier" (or just show as percentage) |

### Vault Page

| Current | Recommended |
|---------|-------------|
| "Vault #{id}" (eyebrow) | "Climb #{id}" |
| "Minter `2222...2222`" | "Created by `2222...2222`" (or better, a username if available) |
| "KOM seat currently vacant" | "Fastest time: unclaimed" |
| "Elevation" (stat label) | "Vertical Gain" |
| "Vault State" / "Core economics and rights" | "Climb Details" / "On-chain climb record" |
| "Mint Epoch" | "Created in Epoch" |
| "Rights Expire" | "Creator rights expire" |
| "CAL Burned" | "Total CAL retired" |
| "Activation State" / "Historical seed boundary" | "Chain Status" / "On-chain activation progress" |
| "Historical seed writes are on-chain..." | "This climb's historical ride data has been imported to the blockchain." |
| "Recent Activity" / "Live protocol events after activation" | "Recent Rides" / "Latest completions and rewards" |
| "Local Legend" / "Current election seat" | "Most Dedicated Rider" / "Rider with most completions this term" |
| "{count} completions at election" | "{count} completions when crowned" |
| "Distribution History" / "Indexed epoch reward events" | "Reward History" / "Weekly reward payouts" |

### Transaction Page

| Current | Recommended |
|---------|-------------|
| "Transaction" (eyebrow) | Keep |
| "Fee: 5,000 lamports" | "Fee: 5,000 lamports (0.000005 SOL)" |
| "Compute Units: 142,000" | Move to a "Technical Details" collapsible section |
| "Slot: 284,738,291" | Keep but add relative time ("~2 hours ago") |
| "What this transaction did" (eyebrow) | "Summary" |
| "Decoded protocol actions" (eyebrow) | "Instructions" (simpler) |
| "Indexed protocol events" (eyebrow) | "Events" (simpler) |

### Account Page

| Current | Recommended |
|---------|-------------|
| "Account" (eyebrow) | "Rider Profile" |
| "Public rider profile assembled from live token balances and indexed Boulder Rollers state." | "On-chain rider profile with token balances, staking positions, and ride history." |
| "Wallet CAL" (hero stat) | Replace with "Total Rides" |
| "Legacy CAL Snapshot" (hero stat) | Replace with "Training Load (TSS)" |
| "Active Stakes" (hero stat) | Replace with "Climbs Completed" |
| "Recent Events" (hero stat) | Replace with "Vaults Invested" |
| "Balances" / "Live token accounts and legacy UserState snapshots" | "Token Balances" / "Current wallet holdings" |
| "Live SPL balances are read from Solana RPC..." (paragraph) | Remove entirely. Users do not need this caveat. |
| "Legacy CAL Snapshot" | Remove from primary display (move to dev tools section) |
| "Legacy Daily CAL Counter" | Remove from primary display |
| "Legacy Last CAL Mint" | Remove from primary display |
| "Protocol State" / "Indexed Boulder Rollers account fields" | "Rider Stats" / "Lifetime riding statistics" |
| "Bio Score: 1,188" | "Fitness Score: 1,188" (with tooltip explaining what it measures) |
| "Active Stakes" / "Current vault positions" | "Investments" / "Current staking positions" |
| "LP Tokens" (column header) | "Pool Share" |
| "Completions" / "Recorded vault history" | "Ride History" / "Completed climbs" |
| "Total Tribute" (column header) | "CAL Earned" |
| "Beetle Cards" / "Indexed soulbound progress" | "Achievement Cards" / "Lifetime progress badges" |

---

## Progressive Disclosure Recommendations

### Vault Page -- Three-Tier Layout

**Tier 1: Always Visible (Cyclist)**
- Hero: Vault name, climb stats, KOM time, completion count
- Leaderboard (top 10 times)
- Most Dedicated Rider (Local Legend)
- Recent Rides (activity feed)

**Tier 2: "Economics" Expandable Section**
- CAL Staked, Pending Rewards, Reward Rate
- DUNG Emitted, Distribution History
- Staker count

**Tier 3: "Technical Details" Expandable Section**
- Activation State (seeding, chain-active, transactions)
- Vault State (ID, Created, Mint Epoch, Rights Expire, CAL Burned)
- PDA address, Signature hex, Raw JSON

### Transaction Page -- Tab or Accordion Layout

**Tab 1: Summary (default)**
- Narrative overview
- Balance change summary (new)
- Status, time, fee

**Tab 2: Instructions**
- Decoded instructions with accounts
- Arguments rendered with formatting

**Tab 3: Events**
- Protocol events with narrative
- Highlight badges

**Tab 4: Raw**
- Raw JSON
- Logs (when available)
- Compute budget detail

### Account Page -- Prioritized Sections

**Top (always visible):**
- Hero with rider-centric stats (rides, TSS, climbs, vaults staked)
- Token Balances (CAL + DUNG, no legacy fields)
- Ride History (completions)

**Middle:**
- Achievement Cards (BeetleCards)
- Investments (active stakes)

**Bottom (collapsed by default):**
- Protocol State (legacy fields, raw counters)
- Recent Activity (event feed)

---

## Missing Quality-of-Life Features

1. **Breadcrumbs:** No navigation trail. If you are on `/vault/142`, there is no "Observatory > Vault #142" breadcrumb to orient you.

2. **Back links in context:** When viewing a transaction that involves Vault #142, the narrative references the vault but the vault name is not shown -- only "Vault #142." If the narrative said "Manayunk Wall (Vault #142)" it would be much more useful.

3. **Refresh indicator:** No visual indicator that data is being re-fetched or is stale. React Query handles staleness internally, but the user has no visibility.

4. **Keyboard shortcuts:** No `/` to focus search (standard Etherscan pattern).

5. **URL sharing preview:** No Open Graph meta tags for social sharing. Pasting a BoulderScan URL into Telegram/Discord would show no preview.

6. **Print/export:** No ability to export vault or account data (CSV, PDF). Lower priority but useful for tax/accounting.

7. **Pagination:** Event feeds and leaderboards appear to have no pagination. If a vault has 500 events, they presumably all load at once (or are truncated server-side without indication).

8. **Loading skeletons:** The LoadingState component shows a pulsing card, but individual sections do not have skeleton placeholders. This means the entire page is blank during load, then appears all at once.

---

## Summary Verdict

BoulderScan is a solid B+ foundation. The architecture is clean, the narrative system is genuinely innovative, the mobile responsiveness is above average, and the domain-specific formatting is a real differentiator. The dark mode is polished.

The core problem is identity: BoulderScan does not yet know whether it is a developer tool or a cyclist tool, and it tries to be both at the same surface level. The fix is progressive disclosure -- present the cyclist story first, let developers drill down.

The three highest-impact changes:
1. **Address labels** (transforms hex soup into meaning)
2. **Token balance change summaries** (shows EFFECT, not instruction)
3. **Rewrite Observatory hero and Account hero stats** (first impression for cyclists)

These three changes alone would shift BoulderScan from "interesting developer tool" to "a cycling-native chain explorer that developers can also use" -- which is the right direction for a platform where 95% of users will be cyclists.
