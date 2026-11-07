# Boulder Rollers — Language & Visibility Spec

> **Scope:** this is UX-surface guidance — what riders see and the working labels we use in copy. `docs/PROTOCOL_TRUTHS.md` is the chain-canonical authority; when anything here conflicts with TRUTHS, TRUTHS wins. This doc describes the cultural layer, not the protocol layer.
>
> **Arrow of time:** the vocabulary architecture, layer order, and term meanings
> in this doc are the current product-language contract. Example copy and rows
> explicitly marked *designer-territory* remain working choices. When a label
> does not exist yet, leave it blank rather than forcing one.
>
> **Vocabulary amendment (2026-08-13):** the rider vocabulary architecture,
> exact term ledger, state grammar, and translation standard were ratified for
> product use under `boulderroller-v2-m1wsl`. Unresolved triggers remain named
> explicitly rather than filled in by implementation inference.
>
> **Standards amendment (2026-09-07):** the Night Ledger palette supersedes
> the gold/olive visual directions here, and a missing number has no glyph in
> its slot (see `docs/design/PORTAL_STANDARDS_AMENDMENT_2026-09-07.md`).
> Semantic layer order, term meanings and CTAs are unchanged.

## Design Philosophy
- Portal is a cycling app; CAL and DUNG surface naturally, never as jargon
- BoulderScan is the power-user chain explorer that unpacks protocol detail
- Two products, not two modes within one product
- Zero toggles — features appear because you DID the thing
- CAL and DUNG are cycling concepts we define, not crypto jargon we inherit
- Public and portal copy should be literal. Do not invent slogans or campaign
  language unless product leadership supplies the line.

## Voice Posture

The public voice is a rider who understands the system, not a system granting
permission to the rider. Assume the ride happened. State what it contains,
where it went, and what changed.

- Public-root order: `ride -> climbs on the route -> time -> leaderboard`.
- Use familiar athletic nouns before economic codes or protocol terms.
- Keep CAL, DUNG, Balance, and Vault mechanics one layer below the first public
  explanation.
- Use `counted` and `confirmed` only when eligibility, correction, or finality
  is the actual visible question. Do not use them as ambient proof that a ride
  was legitimate.
- Prefer high competence and low ceremony: exact mechanism, few adjectives,
  no heroic posture, no suffering theater, and no forced rider slang.

## Rider Vocabulary Architecture

Primary rider surfaces use ordinary cycling language, reserve one branded
moment for the whole-ride reveal, and introduce Boulder Roller economics only
after the sporting result is clear.

| Layer | Vocabulary | Job | Rule |
|---|---|---|---|
| **Core sporting** | `Ride`, `Climb`, `Result`, `Time`, `Power`, `Place`, `Best`, `Top 10`, `Leaderboard`, `History`, `Start`, `Finish` | Describe what the rider did and where they stand | Use ordinary cycling words. No glossary should be required. |
| **States** | `Matched`, `Counted`, `Confirmed`, `Pending`, `Held`, `Establishing`, `Established`, `Delayed`, `Not counted`, `Needs review`, `Ready`, `Collected`, `Updated`, `Removed` | Explain what happened to a named object | Success is usually implied. State it only when eligibility, correction, availability, or finality is the visible question. |
| **Branded moment** | `Boulder Rolled` | Name the whole-ride post-ride reveal | Use at most once on a surface. Never turn it into generic product grammar or a per-climb state. |
| **Economy** | `CAL`, `CAL tribute`, `DUNG`, `Vault`, `Leaderboard pool` | Describe Boulder Roller-specific instruments and economic consequences | Introduce only after the ride, climb, or result is understood. |
| **Role and identity** | `Local Legend`, `BeetleCard` | Describe recent stewardship and rider identity without turning either into capital | Introduce only when the relevant Climb or rider context is visible. |
| **Technical detail** | `Canon`, `Traversal`, `Attestation`, `Adjudication`, `Policy`, `Gate`, `Proof`, `Accepted`, `Version` | Run and inspect the system | Keep off primary ride surfaces. These terms remain valid on public canon pages, BoulderScan, admin/support, developer, and explicit technical-detail surfaces. |

The compact rule is:

> **Ordinary cycling words + at most one branded moment + optional role,
> identity, or economic detail.**

### Exact Term Ledger

| Term | Exact rider-facing meaning | Good use | Boundary |
|---|---|---|---|
| **Ride** | One recorded or uploaded cycling activity | `4 climbs in this ride` | `Record` remains the capture verb; `Ride` is the object. |
| **Climb** | A named uphill course Boulder Roller recognizes | `Falls Road` | Use `Climb`, not `Segment`, as Boulder Roller's primary noun. |
| **Result** | The rider's performance on one Climb during one Ride | `3:18 · 324 W · 7th` | A sporting Result does not by itself assert CAL eligibility, settlement, or chain finality. |
| **Time** | Elapsed time on the measured Climb | `3:18` | Detailed protocol surfaces may explain gate-crossing and precision rules. |
| **Power** | The rider's average power on the Climb: measured by a power meter, or estimated when none was present | `⚡ 324 W` measured · `≈ 278 W` estimated | Measured power carries the bolt; an estimate carries the estimate mark and never the bolt (Tim, 19 Oct 2026: "Estimates get no power icon"). Estimates use the standard mass, never a rider's weight. W/kg shows to others only when the rider opts in. |
| **Place** | The rider's current sporting rank on the Leaderboard, using `competition_rank` for ties | `7th`, `Rank #7`, or `T-1` | Place can change. Compatibility row `rank` must not override sporting presentation. Reserve `My position` for the rider's deposited-CAL relationship. |
| **Best** | The rider's strongest Result under one comparable measure across their History | `New best` | If the comparison is not obvious, say `Best time` or `Best power`. Do not collapse unlike measures into one Best. |
| **Top 10** | A rider's best validated Result currently holds one of the Climb's ten Leaderboard seats | `Top 10 · 7th` | Historical achievement and current seat are separate facts. |
| **Leaderboard** | Ten seated riders ordered by each rider's best validated Result on one Climb, with competition ranking for ties | `View Leaderboard` | Human-readable surfaces use `Leaderboard`; compatibility identifiers may still use `record_board`. |
| **History** | The rider's earlier Results on that Climb | `Your history` | History is not a synonym for the current Leaderboard. |
| **Start** | Where the measured Climb begins | `Start` on the map | Use the physical label instead of `start gate` on primary surfaces. |
| **Finish** | Where the measured Climb ends | `You turned off before the finish` | Use the physical label instead of `finish gate` on primary surfaces. |
| **Record** | An actual course, city, or historical record | `Course record` | Never use `record` as a noun for every Ride or Result. `Record a ride` remains correct. |
| **Boulder Rolled** | The reserved name for the whole-ride post-ride reveal | `Boulder Rolled` | The exact eligibility trigger is still a separate product decision. A detected Climb alone must not trigger it by inference. |
| **CAL** | Boulder Roller's transferable work-and-currency unit, created from eligible cycling work | `+82 CAL`, `82 CAL pending`, `82 CAL counted` | Use bare `CAL`, not generic `credits`, `points`, or `rewards`. Name pending/final state when it matters. |
| **CAL tribute** | A separate flow-meter amount measured from eligible Climb work | `CAL tribute` followed by per-Climb amounts | The rider keeps full Ride CAL. Tribute is not a deduction, transfer from the rider, or second mint. |
| **DUNG** | Boulder Roller's value and reward token, made available through eligible roles and eligible deposited-CAL positions after settlement | `54 DUNG ready`, `Collect DUNG` | Do not say `earned` before the amount is actually available or final. |
| **Vault** | The economic account attached to a Climb for CAL deposits and DUNG settlement | `Deposit CAL` in the Climb's economy module | Never make the Vault the headline of a Ride or Climb card. |
| **BeetleCard** | Boulder Roller's visible rider identity and progression artifact | `View BeetleCard` | Use only for the actual product object. `Beetle Score` remains unconfirmed as a rider-facing stat label. |
| **Local Legend** | The named recent-activity stewardship role for a Climb | `Legend of Manayunk Wall` | This ratified role name remains valid; do not replace it with a new noun. |
| **Leaderboard pool** | The human-readable economic label for the `record_royalty` DUNG bucket | `Leaderboard pool` | Sporting surfaces say `Top 10`; economic detail says `Leaderboard pool`. Do not introduce `Top 10 royalty`. |
| **Threshold** | Boulder Roller's rider-specific power normalizer, derived from recorded rides | `Threshold` | Never call it `FTP` or `eFTP` on a rider surface, and never show the 200 W network placeholder as the rider's value. |
| **Establishing** | No derived Threshold has been sealed yet | `Threshold — Establishing`; `Status — Establishing` | Athletic register only. Do not use banking language for measurement state. |
| **Established** | The first derived Threshold has been sealed | `Established` | Use for the first value when there has not yet been an actual raise. |
| **Last raised** | Date of the most recent actual Threshold raise | `Last raised` | Do not substitute this for first establishment. |
| **Next Monday** | A Threshold raise is actually scheduled for the next Monday boundary | `Next Monday` | Omit the row unless a promotion is genuinely scheduled. Never use it for an unscheduled candidate. |
| **Held** | CAL is waiting for the rider's Threshold to be established | `Held`; `Held — clears when your Threshold is established.` | Economic register only. `Counted` appears only when CAL is recognized. |

### State Grammar

State words always attach to a named subject. A Climb match, sporting Result,
CAL amount, DUNG collection, and submitted operation can be in different states
at the same time.

| State | Use |
|---|---|
| `Matched` | The Ride route produced a Climb match. Prefer this to generic `Found`. |
| `Counted` | The named object passed the relevant eligibility rule. On most rider surfaces this means `CAL counted`; it is not ambient proof that the whole Ride is final. |
| `Confirmed` | The named object reached the explicit finality boundary shown by the surface. Do not use it as a synonym for `Matched` or `Counted`. |
| `Pending` | The named value or operation is known but not final. |
| `Held` | The named CAL amount is waiting for the rider's Threshold to be established. Use `Held — clears when your Threshold is established.` when the reason must be explicit. |
| `Establishing` | The rider's Threshold has not yet been established. This is an athletic measurement state, not a money state. |
| `Established` | The rider's first Threshold value has been established. Later changes use `raised`. |
| `Delayed` | A named operation is taking longer than expected but has not failed. |
| `Not counted` | The named object did not qualify. Follow it with the concrete reason when known. Natural sentence copy may say `didn't count`. |
| `Needs review` | The system cannot truthfully project a final state without inspection. |
| `Ready` | A named value or action is available, such as `DUNG ready`. |
| `Collected` | A named collectible value was received, such as `DUNG collected`. |
| `Updated` | A visible Climb definition or field changed. State exactly what changed and apply the continuity rules below. |
| `Removed` | A named object left a named surface or eligibility set. Say what was removed, from where, and why. State separately whether the Ride or Result remains; never imply preservation or erasure without authority. |

Showing a Result is normally enough to communicate sporting success. Use
`accepted` only in protocol or technical detail. Use `counted` or `confirmed`
on a rider surface only when the named eligibility or finality boundary is the
thing the rider needs to understand.

## Ride Object Rule

The rider-facing activity object is `Ride`. Do not attach `record` to `ride` as
a second product noun.

| Meaning | Rider-facing language |
|---|---|
| One activity | `Ride` |
| The collection | `Rides` or `Ride history` |
| Processing lifecycle | `Status` or `Ride status` |
| Optional proof detail | `Verification` or `How rides are verified` |
| Athletic achievement | `KOM`, `PR`, `best time`, or `Leaderboard` |
| Live capture action | `Record a ride` |

`record` remains valid as the verb for capture and as a precise athletic term.
Exact protocol and implementation identifiers such as `RideAttestation`,
`record_ride`, database rows, and ABI names remain unchanged and stay in their
technical layer.

## Language Matrix

Rows marked *designer-territory* are the only unresolved labels in this matrix.
The other labels follow the vocabulary contract and ratified language split.

| Concept (TRUTHS canonical) | Working rider-facing label | CTA Button |
|---|---|---|
| CAL earning | `+47 CAL`; use `47 CAL pending` or `47 CAL counted` when state is the visible question | — |
| Staking | `Deposit CAL in this climb` | **`Deposit CAL`** |
| Unstaking | — | "Withdraw CAL" |
| Collecting DUNG from deposited CAL | "12 DUNG ready from Manayunk Wall" | "Collect DUNG" |
| Internal `record_board` identifiers (all-time top 10) | **Leaderboard** — *"3rd on Manayunk Wall"* | — |
| Internal `record_royalty` identifiers (55% bucket) | **Leaderboard pool** | — |
| Local Legend seat | "Legend of Manayunk Wall" | — |
| Founder (creator of a Climb) | "Created by" (existing working label) | — |
| Settlement Week (economic cadence) | *designer-territory* — often invisible; time references like "this week" are usually enough | — |
| Beetle Score / RiderSoul (soulbound effort identity) | *designer-territory* — BeetleCard is the visual artifact; `Beetle Score` is not yet a confirmed rider-facing stat name | — |

**Language split rule** (Tim 2026-04-15; Leaderboard amendment ratified
2026-07-16; co-KOM presentation ratified 2026-07-21):
- Human-readable surfaces, including BoulderScan, use `Leaderboard` and
  `Leaderboard pool`.
- Existing `record_board` and `record_royalty` names remain only as
  compatibility-sensitive code, IDL, schema, event, and raw decoded-field
  identifiers. Do not turn them back into headings, labels, or narrative copy.
- `Founder`, `Settlement Week`, and `RiderSoul` remain valid chain-canonical
  terms. When in doubt on a rider surface, use the shorter fitness-native word.

### Co-KOM Presentation

On detailed rider surfaces, every seated rider tied at the fastest validated
whole-second time receives the same crown and literal `T-1` label. Use
`competition_rank` for this sporting presentation. Compatibility `rank` is the
occupied row position and must not turn tied riders into `1`, `2`, or a single
winner. Singular `kom_holder` is a legacy representative, not rider-facing
authority for who alone gets KOM recognition.

### BoulderScan Movement Vocabulary

BoulderScan uses explorer-style accounting endpoints instead of migration
narration:

- normal weekly DUNG is a `Staker allocation`
- the current share not unlocked by the participation curve moves from
  `Staker allocation` to `Leaderboard pool`
- the historical balance moves from `Prior staker balance` to `Leaderboard
  pool`; the decoded action is `Balance sweep`
- only indivisible post-allocation units are a `Staker rounding remainder`

Prefer explicit `source -> destination` movement. Do not expose `legacy`,
`cutover`, or `same-week reallocation` as product labels.

## Literal Copy Contract

Agents must keep rider and public copy simple, literal, and product-descriptive.
The tone target is closer to Garmin, Strava, TrainingPeaks, and a bankable DeFi
position card than to launch copy or brand poetry.

### Default Copy Shape

- Lead with the product, object, or action: `Boulder Roller`, `Record rides`,
  `Browse climbs`, `Open climb`, `Deposit CAL`.
- Prefer concrete nouns: `ride`, `climb`, `result`, `time`, `power`, `place`,
  `best`, `Top 10`, `leaderboard`, `history`, `start`, `finish`, `CAL`, `DUNG`,
  `vault`, `deposit`, `withdrawal`, `DUNG history`, `collection details`.
- Keep subcopy factual. Say what the product records, matches, shows, orders,
  or links to.
- CTAs must name a real action or destination. If the action does not exist,
  leave the CTA out.
- Trust language must name the mechanism when it is visible: `matched`,
  `BoulderScan`, or `source file`. Explicit technical-detail surfaces may also
  use `receipt` and `signature`. Narrow eligibility and finality states may use
  `counted` or `confirmed` when that distinction is the subject. Do not imply
  final proof where the surface is projected or pending.

### Avoid

- Agent-written slogans, taglines, or poetic hero lines.
- Abstract claims like "where effort lives forever" unless product leadership
  explicitly supplies them.
- `ride-to-earn` as public positioning or metadata.
- Generic crypto positioning before the rider understands the ride, climb, or
  leaderboard.
- CTA filler such as `Start Rolling` when it does not describe the real action.
- New product nouns invented to make a screen feel branded.

### Portal Climb Browsing

Use climb-first language for `/climbs`:

| Surface | Use | Avoid |
|---|---|---|
| Primary nav word | `Map` | `Climbs` as the nav word (the index inside the room keeps it) |
| Page title | `Climbs` | `Vaults` |
| Browse section | `Browse climbs` | `Climb catalog` |
| All tab | `All climbs` | `All vaults` |
| Rider tab | `My positions` | `My stakes` |
| Search | `Search climbs` | `Search vaults` |
| Card action | `Open climb` | `Open vault` |

The climb card's first job is to identify the climb and its athletic record:
name, map/elevation shape, distance, grade, attempts, results, leaderboard, and
the rider's relationship to that climb. Vault status, CAL, DUNG, deposits, and
settlement are consequence-layer details. They can use compact DeFi-native
composition, but only as an attached economy strip or detail module bound to
the climb.

## Visibility Matrix

| Concept | Visibility | Where |
|---------|-----------|-------|
| Ride CAL | **Post-ride summary** — one rider amount, explicitly projected/pending until final | RideView summary |
| CAL Tribute Cascade | **Post-ride summary** — 1→N matched Vault flow-meter amounts animate separately from Ride CAL | RideView summary / Boulder Rolled |
| Leaderboard place | **Post-ride summary** — `NEW: 3rd on Manayunk Wall` when the Result enters the current all-time top 10 | RideView summary |
| Weekly DUNG and collection history | **Portfolio / climb Vault section** — collect when ready; receipt/proof detail stays optional | Portfolio / ClimbView |
| Deposit/Withdraw | **Climb Vault section** — action buttons | ClimbView / VaultView |
| Raw protocol-piping detail (PDAs, tx signatures, bucket carry math) | **BoulderScan** — power-user detail, not portal chrome | scan.boulderroller.xyz |

## Boulder Roller Balance State Model

Primary rider surfaces should describe what Boulder Roller knows about the
rider's Balance before exposing the mechanism that changed it.

| State or action | Primary rider copy | Keep out of primary copy |
|---|---|---|
| Ride matched and usable for CAL | `CAL counted` | proof state, attestation state |
| DUNG available but not collected | `DUNG ready` | harvestable rewards |
| DUNG received | `DUNG collected` | transaction submitted |
| CAL into a climb's economy | `Deposit CAL` | stake transaction |
| CAL out of a climb's economy | `Withdraw CAL` | unstake transaction |
| CAL deposited in a climb | `Your position` | LP token, custody token account |
| Staking tokens into a hill (stage 1) | `Deposit`; lists say `Your deposits` (Tim, 19 Oct 2026) | pledge, stake, lot |
| Stage 1 tokens back out of a hill | `Give notice`, then `Start withdrawal` and `Complete withdrawal` | unstake, exit lot |
| Stage 1 rider pay, if automatic payment failed | `Collect` | self-claim, claim transport |
| Vault creation | `Create Vault` | mint/sign/submit sequence |
| USDC payment | `Pay with USDC` | token transfer transaction |
| App is reconciling a submitted operation | `Deposit pending`, `Withdrawal delayed`, or the corresponding named action | tx pending, gas, signature |
| App needs support/admin inspection | `Ride needs review`, `Deposit needs review`, or the corresponding named object/action | failed tx, protocol error |
| Support/admin/debug detail | BoulderScan or admin language | never primary portal/mobile chrome |

`Boulder Roller Balance` is the rider's economy model. Use `wallet` only when
the surface is actually about protocol identity, signing, custody, or account
security. Use `transaction`, `signature`, `gas`, `explorer`, and raw proof words
only inside BoulderScan, admin/support tooling, explicit technical details, or
code/tests.

A normal action without a wallet popup is still authorized, not permissionless.
Primary surfaces continue to say `Deposit CAL`, `Withdraw CAL`, and `Create
Vault`; they do not expose `rider session`, nonce, policy hash, or signer
mechanics. Session setup, rotation, revocation, lock, and recovery belong to the
account-security boundary. When that authority is unavailable, stop calmly or
show the explicit wallet-confirmation path; never imply that login or tapping a
button grants token authority.

Vault LP is internal pool-share accounting for one account-bound position. Do
not present it as a transferable rider asset or imply a strategy product that
does not exist. A future managed strategy can name and expose its own bearer
share only when that separate product and versioned protocol integration exist.

### Copy QA Targets

The Balance language gate covers:

- `docs/design/LANGUAGE_SPEC.md`, `docs/PORTAL_TRUTHS.md`, and
  `docs/MOBILE_TRUTHS.md`
- `web/portal/src/pages/VaultView.tsx`
- `web/portal/src/components/auth/AccessPanel.tsx`
- `mobile/src/lib/climbDisplay.ts`
- `mobile/src/screens/ClimbsScreen.tsx`

Run `npm run qa:balance-language --prefix web/portal` after changing primary
Balance, auth-entry, climb, vault, or mobile rider copy.

## Post-Ride Summary Screen: Boulder Rolled

The post-ride screen is the moment of delight. Not a data dump — a reveal.

`Boulder Rolled` is the reserved name for this whole-ride reveal. It is not a
per-Climb label, generic success state, CTA, or substitute for `Ride summary`.
Use the branded phrase at most once and do not add an explanatory paragraph to
the primary reveal; help or technical detail can sit behind an explicit action.
The exact eligibility trigger remains a separate product decision. Until it is
specified, implementations must not infer that every matched or detected Climb
earns the branded moment.

Gold cascade animation. Ride CAL and the separate Vault tribute flow must never
be summed together or presented as if tribute were a deduction from the rider:

```
RIDE CAL
847 CAL pending

CAL TRIBUTE · PENDING
Manayunk Wall                         55 CAL
Lyceum Avenue                         29 CAL
```

- Each line appears with a brief flourish
- The rider receives the full Ride CAL amount. Tribute is a separate flow-meter
  allocation across matched Vaults, not a second mint or a deduction.
- If the Result enters a Climb's current Leaderboard (all-time top 10), that is
  the gold moment. The achievement may remain in History, but the current seat
  and Place can change; never call the seat a permanent unlock.
- Any separate short-window placing is chrome — olive, not gold — and must not
  be called the `Leaderboard`.
- No `processing` spinner appears in the reveal itself. The cascade may animate
  immediately from projected values only when the enclosing state says
  `projected` or `pending`. On-chain verification affordances (see
  `docs/design/MOBILE_PROTOCOL_TRUTHS_CROSSWALK.md` §6.8.6) are additive
  post-cascade and never block the animation.

## Translation Standard

Translate system state into the rider's object, outcome, and concrete reason.
These examples govern primary rider surfaces; BoulderScan and explicit
technical detail may show the underlying term after the rider-facing object.

| Do not ship on a primary surface | Ship | Boundary |
|---|---|---|
| `4 accepted traversals` | `4 climbs` | Use only after the Climb matches are known. |
| `Traversal accepted` | Show the Result; say nothing else | If CAL or finality is separately in question, name that state separately. |
| `Proof rejected` | `Falls Road didn't count` followed by the actual reason | If only CAL failed, say `CAL not counted`; do not imply the sporting Result disappeared. |
| `Failed endpoint gate` | `You turned off before the finish` | Use only when that is the observed road-level reason. |
| `Canon v4` | `Falls Road` | Public canon and technical detail may expose the version. |
| `Canon profile refined` without moving an endpoint or measured span | `Climb profile updated July 19` and, when relevant, `Earlier results stay` | Minor profile, corridor, or metadata corrections preserve identity and Results only under the continuity rules in `PROTOCOL_TRUTHS.md`. |
| `Canon boundary updated` | `New Falls Road course begins July 19`; `Earlier course and its Leaderboard remain available` | Moving an endpoint, centerline, orientation, or measured span creates a new canon version and fresh Leaderboard. Do not claim the old Results moved. |
| `Traversal under review` | `Reviewing this result` | Say what is being reviewed when known. |
| `Result removed from the Leaderboard through adjudication` | `Result removed from the Leaderboard` followed by the actual reason | Name the affected surface. Keep adjudication machinery in detail and state historical retention only when the governing rule guarantees it. |
| `Full attested Ride CAL credited` | `+82 CAL` | Until final, use `82 CAL pending` or an equally explicit enclosing projected/pending state. A bare projected amount must not look final. |
| `Measured Climb TSS attributed to eligible Vaults` | `CAL tribute` followed by the per-Climb amounts | Keep this separate from the rider's full Ride CAL. It is neither a deduction nor a second mint. |
| `Record royalty position achieved` | `Top 10 · 7th` | If the economic bucket is the subject, use `Leaderboard pool`. |

### Standard Copy Shapes

These compact examples assume the displayed values are known for the state the
surface claims. A projected reveal must carry an explicit enclosing
projected/pending state; unavailable data must never become `0` or final-looking
copy.

Ride summary:

> **4 climbs · 1 new best · 82 CAL**

Climb Result:

> **Falls Road**<br>
> 3:18 · 324 W · 7th<br>
> **New best**

Climb match that did not count:

> **Falls Road didn't count**<br>
> You turned off before the finish.

Minor Climb-profile correction:

> **Climb profile updated July 19**<br>
> Earlier results stay.

Branded whole-ride moment:

> **Boulder Rolled**

## Terms to Hide, Retire, or Qualify

| Term | Decision | Rider-facing rule |
|---|---|---|
| `Canon` | Keep below primary Ride UI | Name the Climb on primary surfaces. `Canon` remains valid on the open canon registry, BoulderScan, admin, developer, and explicit technical-detail surfaces. |
| `Traversal` | Technical only | Riders ride a Climb and produce a Result. |
| `Attestation` | Technical only | Primary copy uses `Status`, `Verification`, or the concrete outcome. |
| `Adjudication` | Technical only | Explain the call and actual reason, not the process category. |
| `Proof` | Optional technical detail | Primary copy uses `Verification` or `Status`; raw proof belongs in BoulderScan or explicit detail. |
| `Accepted` | Remove from successful primary states | Showing the Result normally means the sporting match succeeded. Keep object-specific CAL/finality states separate. |
| `Versioned record` | Never primary copy | Name the Climb, changed physical feature, and effective date. |
| `Reference layer` | Never primary copy | Name the rider benefit or object. |
| `Policy` | Replace with `rules` on rider surfaces | Technical and governance documents may still use `policy`. |
| `Gate` | Replace with the physical or actual boundary | Use `start` or `finish` for endpoint checks; otherwise name the specific eligibility, review, release, or economic boundary. |
| `Segment` | Avoid as Boulder Roller's primary noun | Use `Climb`; `segment` may appear only when accurately describing an external provider's object. |
| `Flow` | Park as a branded product noun | Ordinary process prose may still use the word. Do not name an invisible product concept `Flow`; reconsider only if riders can perceive a real product object that earns the name. |
| `Arena` | Park | Do not use until riders can perceive a real competitive object that earns the name. |
| `Local Legend` | Keep | This is a ratified named role, introduced only when that Climb context is relevant. |
| `Record Royalty` | Hide compatibility label on human-readable surfaces | Use `Top 10` for sporting status and `Leaderboard pool` for the economic bucket; `record_royalty` remains only a compatibility identifier. |
| `Effort` | Use only when it means measured work | Prefer `Result` for one performance on one Climb. |

The core rider sequence is:

> **Ride → Climb → Result → Best → Top 10 → Leaderboard → History**<br>
> **Branded moment: Boulder Rolled**<br>
> **Economy: CAL, CAL tribute, DUNG, Vault**<br>
> **Role and identity: Local Legend, BeetleCard**<br>
> **Technical detail stays underneath the primary ride experience.**

## What BoulderScan Shows (Not the Portal)

- Transaction signatures and tx hashes
- PDA addresses and account details
- Instruction-level decoded data
- Supply cap, emission schedule, basis points
- Vault tribute flow details
- Raw on-chain state
- Developer-oriented progressive disclosure
