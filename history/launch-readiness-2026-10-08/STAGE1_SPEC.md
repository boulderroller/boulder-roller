# Stage 1 milestone 0: executable ratified semantics

Bead: `boulderroller-v2-6c6sv`. Evidence class: **local, offline reference
behavior**. This is a prospective money-module specification, not a claim about
the deployed protocol, provider liquidity, legal clearance, or verified riders.
No product code or existing protocol authority is amended by this milestone.

Authority for this bounded experiment is [the brief](../codex-briefs-2026-10-08/stage1-m0.md),
[the plan](STAGE1_PLAN.md), the supplied
`history/explainer-hill-bonding-2026-10-06/DESIGN.md` in the human-visible root,
and [DIAMOND.md](../hill-bonding-diamond-2026-10-08/DIAMOND.md).
All six brief defaults and the mechanical resolutions below are **ratified by Tim, 13 Oct 2026**;
their parameters live in [diamond.yaml](../hill-bonding-diamond-2026-10-08/diamond.yaml)
under `stage1:`. The existing top-level settled split/lock/DUNG parameters are
reused. Semantic modes are named and checked at load time: an unsupported policy
must stop execution, never silently use a previous default. Every `stage1`
section must declare `status: ratified`; missing or unknown status fails closed.
The ratification in §9 supersedes the brief's pending labels and the model's
original city-season founder bonus and separately funded boost upload tail.

The executable oracle is [tools/stage1_reference](../../tools/stage1_reference/README.md).
It covers one launch city and one deployment-wide ledger. At Philadelphia launch
these coincide. A later multi-city implementation must share fee and exposure
accumulators at deployment scope; constructing independent city models does not
prove the global cap or global fee residual.

## 1. Units, identity and trusted inputs

All amounts are nonnegative integers: SOL lamports, deposited token base units,
USDC micro-units (six decimals), DUNG nano-units (nine decimals). Climb-TSS is
an integer in millionths of a TSS. Rates are positive exact integer ratios
`r = lamports / token_base_unit`. Rates and allocation weights may be rational;
transfers, principal bases and obligations are always integers. YAML decimal
scalars are read as strings and converted to exact ratios, never binary floats.
The model uses unbounded Python integers; Merkle sums are checked unsigned
128-bit values. A program implementation must separately enforce its token and
account integer limits and checked intermediate multiplication.

Each model instance has a deployment namespace, city, immutable launch timestamp
and immutable city line. A hill key represents an already admitted canonical
climb. A person key represents an already verified unique person; a recipient is
registered before a payable leaf is created; otherwise its cash share is held
for the person under §§5–6. Under §7, that unregistered person's DUNG share
stays unminted; it is not held or minted later when a recipient registers.
These are caller-supplied **assumptions**. The
model does not establish canon, person uniqueness, signatures, provider rates,
upload timestamps, authentic TSS, board truth, or actual redemption liquidity.
One person may hold a top-ten seat and the earned Local Legend role; their cash
entitlements combine before the cap. Duplicate top-ten identities are rejected.
The Founder title never inserts a paid seat.

For milestone 1a, `init_hill_bond` is city-admin admission. The hill PDA uses
the stable canonical `canon_id`, so successive canonical versions share one
permanent bond. New pledges must supply the current, non-superseded Climb of
that lineage. An already existing legacy CAL vault does not prevent admission:
this is the migration path, without changing its CAL principal or behavior.

Board membership and Local Legend election are external sporting inputs. Retain
the bounded ten-person board and existing whole-second tie rules from
`docs/PROTOCOL_TRUTHS.md` §§6.2–6.4; the cash board split is flat, so tied ranks
do not change money among the ten admitted people. A legacy bootstrap Founder
must not be passed as an earned Local Legend. The oracle does not run elections.

## 2. Calendar and immutable weekly measurements

The city launches at a Monday 12:00 UTC boundary. Week `w` is the half-open
interval `[launch + w*604800, launch + (w+1)*604800)`. Season index is
`w // stage1.seasons.weeks`, initially 26 weeks per season. Locks and notice are
exact elapsed durations from their event timestamps, not rounded calendar weeks.

The opening snapshot uses the state immediately before the boundary's new
transactions. Live means already bonded and active principal backing at least
`city_line * live_fraction`, initially 5 SOL against Philadelphia's 10-SOL line.
For each non-exiting lot, backing is `min(B, floor(U*r))`; owner reserves,
unharvested appreciation above basis, earnings and cash escrow never count.
The reference uses its most recently supplied rate observation. Production must
validate adapter freshness and provenance **before** admitting that observation;
this model's clock alone supplies no such evidence.

The opening live result and DUNG backer weights are frozen. A midweek deposit,
loss, notice or exit affects the next opening, not past live state. A hill bonded
during a week holds that week's rider yield and admits no DUNG that partial
week. Its first full opening can be live. At an exactly coincident timestamp,
the boundary snapshot happens first, then the transaction. Bonded is permanent;
live is recalculated each week.

At close, freeze that week's upload records, board, earned Local Legend,
season-field result and admitted asset list. Finalization is allowed at close
plus 86,400 seconds and must proceed in week order. Empty payout weeks may be
passed by the cursor proof in §8.1; this never discards other asset or DUNG work.
The grace does not extend the ordinary upload interval. Uploads received inside
the week count for that upload week when processing and confirmation finish
strictly before close plus 86,400 seconds. A late finalizer cannot extend this
fixed processing cutoff. Boosts use the ride
week and admit its qualifying uploads strictly before that week's fixed
close-plus-grace cutoff (§6). This does not change the closing snapshots.
A delayed finalizer consumes those historical inputs, never today's board,
field or backing, and cannot extend the cutoff. Claim sets cannot be
republished. Every asset present at close receives a root, including an empty
root when no one can be paid.

## 3. Lots, bonding, cancellation and losses

A deposit creates a new owner/hill/asset-bound lot with `U` deposited units and
protected integer SOL basis `B = ceil(U*r_deposit)` lamports. The upward rounding
is deliberate: flooring can turn original deposited token units into harvestable
income at an unchanged rate. It conservatively retains less than one extra
lamport of coverage; it is not an outside guarantee of that rounded value.

Campaign backing uses the lesser of basis and actual redemption value, so a
loss delays bonding and appreciation cannot replace the committed principal
line. When a pledge crosses the line, the pledge and bond serialize atomically
against the hill. All included lots become founding lots. The triggering owner
gets the Founder title. Immediately freeze each founding lot's pre-bond
surplus `max(0, U-ceil(B/r_bond))` as that owner's separate token reserve.
Pre-bond yield is fee-free owner property and is never rider income. Indivisible
sub-token surplus stays in principal custody as rounding residue; it cannot be
transferred as a fractional token unit.

Milestone 1a freezes membership by a monotonic lot sequence cutoff and retained
cancellation tombstones, together with an immutable mask of token slots fresh
at bond time and their rates. Each included lot has a frozen bond-rate quote. The
physical reserve transfer and stored founding fields may be materialized later,
before any token movement; locks and ownership take effect at the bond itself.
Materialization never uses a later rate. Exact campaign backing remains a sum
of per-lot `min`/`floor`, not an aggregate approximation, maintained separately
for each token slot. A slot that becomes fresh again at a new numeric rate
blocks all pledges and bonding on that hill until every lot in that slot has
been refreshed permissionlessly, one lot at a time. This protects those lots'
founding status; a fresh slot awaiting repricing cannot be treated as zero.
Unchanged numerical rates renew freshness without restarting that work.
Bonded-hill intake bypasses campaign repricing. There is no lot inventory in
an instruction. Repricing work is proportional to that slot's campaign lot
count; repeated numeric changes can restart it. The local test adapter has
32 stable, non-reused asset slots, an implementation bound rather than a new
production allowlist or economic cap.

**Tim's 13 Oct 2026 round-three decision: a stale token counts as zero.**
A stale slot contributes zero to the bonding line, imposes no refresh
requirement, and cannot block another token's pledges or the bond. New deposits
in that stale token still fail because deposit basis requires a fresh rate.
A slot readmitted before the bond counts again at its fresh, fully refreshed
per-lot backing. Fresh slots and the bounded lagging slots below join the
founding set. Stale excluded lots have no founding weight, Founder entitlement
or bond-time quote.
Later freshness changes never alter that frozen membership.

**Milestone 1b review corrections, preserving Tim's intent:** an SPL/Sanctum
pool whose own update marker names the previous epoch is **lagging, not stale**,
regardless of when BoulderRoller last refreshed it. Its backing counts zero
toward the line, but its lots remain founding. Freeze the pool account's own
last-epoch ratio at bond time and segregate pre-bond surplus at that quote, even
if the admitted cache is older or per-lot repricing was unfinished. Grace ends
when the pool updates or has missed a whole epoch
(its marker is at least two epochs old). A pool update requires normal fresh
admission and repricing. Valid mSOL accounting is sampled as current; it does
not enter lagging grace. This prevents an epoch-boundary bonder from excluding
healthy-token lots while retaining Tim's rule that a dead token cannot jam a
hill. It does not admit lagging quotes for new deposits or threshold value.

**Tim's round-four correction:** a rejected or failed rate observation never
shortens an admitted rate's freshness or replaces its admitted quote. The slot
stays fresh through that quote's window and becomes stale only at expiry.
That retained quote preserves exit rights. Pledge, bond and harvest additionally
require clean provider decoding in the same instruction. An authenticated
undecodable backed slot contributes zero and cannot become founding even when
its admitted cache is current; it cannot jam another token's healthy intake.

An excluded lot remains pre-bond custody. Its owner may cancel at any time for
its actual tracked units, even after the hill bonds or its token recovers. With
a fresh rate, the owner may instead convert it once into ordinary stake,
choosing 0, 13, 26 or 52 weeks from conversion time. Conversion segregates
`max(0, U-ceil(B/r_conversion))` into the owner's fee-free reserve, preserves
the original basis and all cap totals, and never confers founding status.
Until conversion, the lot has no active backing or stake weight, cannot be
harvested, and cannot start withdrawal notice. Disabling new intake does not
remove these rights over principal already held.

Milestone 1b requirements (implemented locally in §3.1; absent from milestone 1a):

- Real adapters define freshness on the provider's own update cadence. A rate
  admitted for the current epoch stays fresh for that epoch. Admit at most one
  new rate value per epoch, so ordinary pool-ratio drift cannot continually
  restart per-lot campaign refreshes.
- Rate refresh is permissionless and reads the provider's on-chain state. A
  rejected or failed observation never marks a slot stale.
- The line-crossing pledge refreshes every slot with backing in the same
  instruction, bounded by the number of enabled tokens. Only slots whose
  provider cannot produce a valid current rate count as zero. A bonder cannot
  exclude healthy-token lots from founding status by choosing the moment.
- Validate exact provider and mint addresses, owners and non-executable status
  before any stale-exit fallback. Substitution or wrong ownership is a hard
  failure. Authentic pinned accounts whose layout or accounting cannot produce
  a usable rate are an outage after admitted freshness expires, so the ratified
  seven-day in-kind exit remains available. Unreadability never supplies a rate.

Cancellation before bonding returns that lot's actual units, including its
unrealized gains or losses, and removes its backing atomically. Cancellation
of an included founding lot after bonding fails; excluded lots retain the
rights above. In the two possible serial orders, either cancellation
removes the lot before the threshold test, or bonding includes and locks it
before cancellation fails. No other lot compensates a loss.

Each enabled staking token initially has a 2,000-SOL-equivalent intake cap;
each hill 500 SOL; the deployment 5,000 SOL. **Tim's 13 Oct 2026 round-two
decision:** admission uses running totals of deposit-time basis `B`, per asset,
hill and deployment. Weekly harvests keep lots near basis; appreciation does
not enlarge the cap measurement. One constant-size check adds the new basis to
these counters. Cancellation and actual principal return subtract it; splitting
an exit conserves it. Exiting principal stays counted until returned, and losses
still count at full basis. Rate/loss observations and cap changes preserve the
held-basis totals. Cap reduction may put existing holdings over a cap; that
blocks additional intake without seizure. Owner reserves and rider custody
are excluded.
Every increase waits at least 604,800 seconds from proposal. A replacement
proposal resets the delay. Reductions are immediate. This is a simulated delay,
not an implementation of multisig or loader authority.

### 3.1 Milestone 1b: read-only provider adapters (local evidence)

`boulderroller-v2-u3xca` implements the requirements above on local validators.
No provider CPI, SOL redemption, provider deployment or live-epoch rehearsal is
part of this milestone. The default build has no manual rate setter or pledge/
bond dispatch; those intake wrappers remain in the isolated localnet build until
the signed Stage 1 upgrade. New real-provider refresh instructions have no
admin signer. Register each asset disabled, admit a validated rate, then have
the existing city admin explicitly enable it. Running deposit-basis exposure
counters cap each token separately at the existing 2,000-SOL limit.

The allowlist pins all three identities, rather than accepting arbitrary accounts
owned by a provider program:

| Asset | Owner program | Exact pool/state | Mint |
|---|---|---|---|
| jitoSOL | `SPoo1Ku8WFXoNDMHPsrGSTSG1Y47rzgn41SLUNakuHy` | `Jito4APyf642JPZPx3hGc6WWJ8zPKtRbRs4P815Awbb` | `J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn` |
| mSOL | `MarBmsSgKXdrN1egZf5sqe1TMai9K1rChYNDJgjq7aD` | `8szGkuLTAux9XMgZ2vtY39jVSowEcpBfFfD8hXSEqdGC` | `mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So` |
| JupSOL | `SPMBzsVUuoHA4Jm6KunbsotaahvVikZs1JyTW6iJvbn` | `8VpRhuxa7sUUepdY3kQiTmX9rS5vx4WgaXiAnXq4KCtr` | `jupSoLaHXQiZZTSfEWMTRRgpnyFm8f6sZdosWBjx93v` |

Addresses come from [Jito deployed programs](https://www.jito.network/docs/jitosol/jitosol-liquid-staking/security/deployed-programs/),
[Marinade contract addresses](https://docs.marinade.finance/developers/contract-addresses),
the [Sanctum official LST list](https://github.com/igneous-labs/sanctum-lst-list/blob/0360a1af31a6c6d99ce1947029d732e2cb2d6682/sanctum-lst-list.toml#L1351-L1361)
and [deployed programs](https://learn.sanctum.so/docs/for-developers/deployed-programs).
All state/mint identities and owners were confirmed in one public, finalized
`getMultipleAccounts` response at slot **456636487**, **2026-10-14 00:17:05 UTC**,
Clock epoch **1057**, from `https://api.mainnet-beta.solana.com`. The executable
program accounts were independently read at slot 456637361. This confirms account
identity, not binary/source equivalence. Original RPC responses, validator account
JSON, binary bytes, hashes, capture date and sources are retained in
[`stage1_providers`](../../protocol/anchor/tests/fixtures/stage1_providers/manifest.json).
No credentials or paid RPC were used.

The [milestone 1c release decision](../codex-briefs-2026-10-13/stage1-devnet-release.md)
keeps those three identities compiled into the default mainnet build. Real
provider deposit, pledge and bond are available in default and devnet builds.
The mutually exclusive `stage1-devnet` feature additionally admits one immutable,
admin-registered **SPL test asset** identity (state plus mint), owned by the
[canonical devnet SPL program](https://www.solana-program.com/docs/stake-pool)
`DPoo15wWDqpPJJtS2MUZ49aRxqz5ZaaJCJP4z8bLuib`. It uses the same strict SPL
decoder below, has no synthetic rate setter, and cannot claim a branded mint.
The default build rejects registration. `stage1-localnet` retains its separate
program identity and synthetic test adapter; its ELF is refused for deployment.
The artifact guard admits the devnet ELF only for an explicit devnet target.

jitoSOL and JupSOL use the 611-byte Borsh `StakePool` allocation with account-type
tag **1**; there is no separate numeric layout version. Their exact rate is
`total_lamports / pool_token_supply`. Little-endian u64 offsets are 258, 266 and
274 for numerator, denominator and `last_update_epoch`; mint is at 162 and token
program at 226. Validate the complete variable-width option/fee tags rather than
assuming fixed offsets in the tail; unused allocation padding is not semantic.
The update epoch must equal `Clock.epoch` for a new admission; a future epoch is
invalid for admission (authenticated impossible state follows the outage rule
below). Pinned layouts: [SPL](https://github.com/solana-program/stake-pool/blob/24b4875ffe0fde7e1b140d9979b9f17660e89291/program/src/state.rs)
and [Sanctum multi-validator](https://github.com/igneous-labs/sanctum-spl-stake-pool/blob/5fd31ede7629761d7c98b2358161cdc219e669fa/stake-pool/program/src/state.rs).
Captured raw rates are `10650132353883915/8153209489021421` for jitoSOL and
`5194388907066853/4277554095630348` for JupSOL.

mSOL uses a 2616-byte allocation, Anchor State discriminator
`d8926b5e684bb6b1`, mint at offset 8, and the documented exact ratio
`(active + delayed_cooling + reserve + emergency_cooling - tickets) / msol_supply`.
The respective u64 offsets, including the discriminator, are
376, 226, 496, 568, 528 and 504. Validate booleans and the variable-width
`DelinquentUpgraderState` enum; there is no numeric layout version. The captured
rate is `2254985557764365/1596971612132375`.
[Marinade's formula](https://github.com/marinade-finance/liquid-staking-program/blob/d4e20237f08add67f030927fe12a097b62b837f5/programs/marinade-finance/src/state/mod.rs#L215-L262)
uses virtual accounting supply, not the rounded UI `msol_price`. Both
[deposit](https://github.com/marinade-finance/liquid-staking-program/blob/d4e20237f08add67f030927fe12a097b62b837f5/programs/marinade-finance/src/instructions/user/deposit.rs#L87-L124)
and [delayed unstake](https://github.com/marinade-finance/liquid-staking-program/blob/d4e20237f08add67f030927fe12a097b62b837f5/programs/marinade-finance/src/instructions/delayed_unstake/order_unstake.rs#L40-L66)
price directly from that state. **Cadence interpretation:** Marinade has no global
reward-update epoch. The adapter samples this authoritative accounting quote
once per epoch; `last_stake_delta_epoch` is scheduling, not freshness evidence.
Provider-operation pause does not erase the pure accounting ratio or block
BoulderRoller's in-kind token return. This proves neither full reward-crank
completion nor available SOL redemption. All three mint accounts must be
initialized nine-decimal SPL mints; virtual supply may exceed actual mint supply
after independent burns, so equality is not required.

**JupSOL is eligible for explicit enablement.** The captured stake and SOL
withdrawal fees are each **1/1000**, with no pending withdrawal-fee change,
SOL withdrawal authority, preferred withdrawal validator, or lockup. Current
[Sanctum documentation](https://learn.sanctum.so/docs/technical-documentation/sanctum-lsts)
and the pinned [stake withdrawal](https://github.com/igneous-labs/sanctum-spl-stake-pool/blob/5fd31ede7629761d7c98b2358161cdc219e669fa/stake-pool/program/src/processor.rs#L3110-L3190)
and [SOL withdrawal](https://github.com/igneous-labs/sanctum-spl-stake-pool/blob/5fd31ede7629761d7c98b2358161cdc219e669fa/stake-pool/program/src/processor.rs#L3425-L3540)
paths establish their meanings. The historical zero-fee launch statement is not
current authority. Enablement checks this verified configuration again; unknown
settings cannot newly enable the asset. No provider withdrawal occurs here and
no fee is deducted a second time from the ratio. SOL reserve liquidity is not
promised by these snapshots.

An admitted quote is immutable for its epoch. Intra-epoch drift returns the
first quote; equal numerical ratios in a later epoch renew freshness without
restarting campaign repricing. Rejected observations change neither admission
nor freshness. Expiry uses the actual Clock epoch, never an estimated epoch-end
timestamp. Every unbonded pledge validates and refreshes every backed provider
slot plus its incoming asset in the same instruction, including disabled but
backed assets, using ordered `[asset writable, provider state, mint]` triples.
There are at most three real providers. Missing, substituted or wrong-owner
input aborts atomically. Authenticated unreadability retains the admitted cache
for exits but immediately blocks incoming pledges/bonds and harvest. Existing
unreadable slots count zero toward the line and are excluded from founding,
without changing the cache, its expiry, or the outage timer. This includes live
mint supply exceeding the provider's accounting supply. Each harvest checks
decodability before materialization or income transfers. A healthy new numerical
quote still requires per-lot refresh work before bonding; rollback cannot turn
that slot into zero.

A readable SPL update marker equal to `Clock.epoch - 1` is lagging, independent
of BoulderRoller refresh activity: preserve founding membership at zero
threshold value and freeze the observed pool numerator/denominator. That quote
is separate from the cached exit quote. Lagging takes precedence over cached
freshness for threshold value and blocks incoming deposits even with a current
cached quote. Numeric repricing is unnecessary for this
zero-value membership decision. A successful pledge below the line cannot leave
a temporary lagged quote frozen after recovery: fresh slots restore their
admitted quote, including recovery to an unchanged numerical rate. After the
bond, later recovery cannot change its frozen materialization quote. A marker
at least two epochs old has no grace. mSOL has no lagging classification.
Bonded intake validates/refreshes its own provider pair. Exits retain the
admitted epoch quote after canonical identity checks; a healthy expired cache
requires permissionless refresh first.

**Outage-clock interpretation:** an epoch number does not prove its historical
wall-clock expiry. `record_stage1_provider_outage` starts the seven-day grace
conservatively at a successful authenticated unavailable reading, after admitted
freshness and any lagging grace have expired. It cannot revoke a current
admitted quote. For readable SPL pools it stores `last_update_epoch`; a later
pool update makes that outage record unusable and recording a new outage
restarts grace. A canonical account that fails layout validation, has zero
supply, or yields impossible accounting (including Marinade tickets above total)
instead records an **opaque outage**. Its bytes may change without restarting
the clock: requiring unchanged bytes could indefinitely strand principal after
a provider upgrade. Moving between opaque and readable-stale classifications
restarts grace; a usable admission clears the outage record.

Both exit steps authenticate the state/mint pair, check current unavailability,
the recorded classification (and SPL marker when readable), and elapsed grace.
Wrong addresses or owners remain hard failures at both steps. A healthy current
provider requires fresh valuation; an outage never enables a fabricated or
zero-valued quote. A full mature exit returns actual token units, leaves earnings
unchanged, and records SOL loss as unknown. **Evidence limit:** opaque state
proves unavailability at successful observations, not continuous provider
failure between them; unobserved recovery followed by another opaque failure
cannot be inferred. Native SPL update markers retain their stronger recovery
witness. Zero-rate valuation/loss transitions retain their later gate in §4.

The reference parser reads these same bytes. Shared vectors pin the exact rates
and simulated epoch rules. Validator tests load raw snapshot accounts, with
explicitly synthetic owner inventory and separately labelled mutated account
variants. Replayed Clock epochs are simulated with a short local epoch schedule;
they are not observations of provider behavior through mainnet epochs. Milestone
5 retains that rehearsal gate. Milestones 1a and 1b share unreleased **0x4D** above
main/devnet 0x4C, with one combined `v0x4d.json` ABI snapshot. The version guard
compares the combined stack to main. This does not authorize an on-chain upgrade.

## 4. Harvest, fees and exits

A rate observation credits nothing. Harvest transfers at most
`max(0, U-ceil(B/r))` units from the originating lot into earnings custody. A
below-basis lot contributes zero; recovery never draws from a healthy neighbor.
The transferred token is both the accounting and payout asset. Rates already
reflect upstream provider/validator costs; the model neither invents those
costs nor deducts them a second time. Only net delivered surplus is realizable.

Let `R_asset` be lifetime actually harvested units in this deployment. A harvest
assesses `floor((R_old+harvest)*fee)-floor(R_old*fee)` units, with `fee=1/10`.
The accumulator spans lots, owners and hills and never resets at a claim,
season, fee withdrawal or lot exit. Splitting ten one-unit harvests still owes
one unit. Releasing held money never charges again. Sponsor/boost cash has zero
fee. Unpaid fees remain a funded liability; paying them does not reduce lifetime
fees assessed.

Founding lots lock until `bond_time + 26 weeks`. Later deposits choose a lock of
0, 13, 26 or 52 weeks from their own deposit time. An owner may start notice only
at or after lock expiry, specifying a positive basis amount no larger than the
remaining lot basis. Only one request can be pending per lot. Four weeks of
notice follow; thus a founding lot's earliest exit initiation is 30 weeks after
bonding. Cancelling notice before exit initiation is allowed; restarting notice
starts the full duration again. Owner authorization is checked at every exit
action.

At exit initiation, sweep genuine surplus first. For requested `B_exit`, split
`U_exit = floor(U*B_exit/B)` units, subtract exactly `B_exit` from the remaining
basis, and conserve all units. **Partition rounding is owner property:** if
either new partition has units above `ceil(its_basis/r)`, move those units into
the exiting owner's dust reserve, never into rider earnings. That residual is
at most one token base unit after the initial sweep. It travels with the exit
and cannot be collected through `withdraw_prebond`. A partial request smaller
than one returnable token base unit fails atomically, including rollback of any
attempted harvest; the owner can cancel and request a larger or full exit.
This avoids both synthetic income from rounded-down basis and an exact-divisibility restriction
that would make ordinary partial exits unusable.

An exiting partition immediately leaves active backing and future DUNG weights;
it remains in exposure/custody until returned. Income still belongs to riders
during notice and deactivation, excluding already segregated owner reserves:
pre-bond reserves and exit dust, including their token appreciation, remain
owner property. At actual return, sweep any newly harvestable
surplus again, then return remaining principal token units plus owner dust to
the same owner. The model's explicit `liquid=True` is a test input, not a provider
receipt or an instant-exit promise. Each child retains its assigned loss; the
other original lots remain untouched. SOL conversion and USDC-to-SOL backing
are external adapters: no simulated USDC repayment guarantee is provided here.
Loss tests model positive redemption-rate declines. Token burns, missing custody
units and a provider's zero-rate collapse require later adapter loss transitions;
the oracle does not claim to exercise those events.

**Tim's 13 Oct 2026 round-two decision:** after at least 604,800 continuous
seconds without a fresh admitted rate, an owner past lock and notice can return
all remaining token units in kind. Backers risk only yield (diamond principle
4): any unharvested surplus leaves with the owner and harvest stays blocked
while stale. A fresh readmission resets the stale clock; invalid observations
do not. The local fixture's stale interval starts when its admitted 60-second
freshness window expires. A full remaining-basis notice may create a full exit
without a rate; an already exiting partition may also complete. A partial
notice cannot authorize the whole original lot, and its fresh-rate partition
calculation remains required. Basis totals decrement only at actual return.
Fresh-rate realized loss values all returned principal plus owner dust; a
rate-free return records the SOL loss as unknown, never zero. The offline model
accepts explicit adapter-expiry and fresh-readmission inputs; these are not
provider evidence.

## 5. Paid riding, field and cash allocation

An admitted upload must have a unique receipt, a trusted nonfuture ride timestamp
no earlier than city launch, and age **at most** seven days, inclusive. Its paid
week for ordinary yield, sponsorship and DUNG is its upload week. Boost cash
uses the original ride week as specified in §6. The original ride timestamp
remains sporting provenance.
The earliest admitted upload owns the paid ascent for `(hill, person, UTC ride
day)`, with initially one ascent per day, even if another upload arrives in a
different week. Rejected uploads consume no receipt. TSS is a separate verified
input; multiple genuine receipts may contribute tribute even when cash ascent
deduplication removes an extra ascent. Fake or duplicated underlying rides are
an admission failure the oracle cannot detect merely from different receipt IDs.

The seasonal field contains distinct admitted people on that hill in the city's
current season. It resets at the shared season boundary. Before five people,
ascents can receive cash, record/Legend buckets wait and DUNG is not admitted.
Cash sponsorship and boosts may pay a registered non-live or unbonded hill;
only donated **yield** is live-gated by default. The city's money-admission gate
must have been satisfied before constructing this model. Geography/counsel
admission is not inferred from a registered hill ID.

For available money, split 65% ascents / 25% occupied top ten / 10% earned
Local Legend. Use Hamilton largest remainders for every integer apportionment:
floor exact shares, then assign leftover units by descending fractional
remainder and ascending UTF-8 key bytes. No top-ten seat means its whole bucket
waits; fewer than ten occupied seats share the whole 25%. No earned Legend means
its whole 10% waits. Without ascents, its 65% waits. Below the field, both record
buckets wait even if the supplied board has people.

Equivalent funding tranches (same hill, asset, original week, due week, kind,
bucket and boost eligibility) coalesce **before** splitting. Preserve source-ID
lineage. This prevents same-week tiny transfers from redirecting all rounding
to the first rider. Different original ages and eligibility are never merged
away. Rounding across genuinely different funding ages/windows can differ by
base units; the model does not value or smooth assets across weeks.

Combine every positive pre-cap entitlement per person, hill, week and **asset**,
across new funds and released holds. The median includes inactive record holders
who have a positive entitlement and excludes every zero. For an even count use
the exact average of the two middle values. The cap is
`floor(multiplier * median)`, initially 3×. USDC and an LST are never added or
compared at a fabricated exchange price. This cap is cash-only, not DUNG.

Process source pieces in `(original week, source ID, bucket)` order, assigning
each person's entitlement up to their remaining fixed cap. Then redistribute
each piece's excess by eligible ascents, repeatedly saturating available
headroom without recalculating the median. A boost's excess stays with its
window-qualified ascent population. If no such rider has headroom, retain the
remainder in that source's cap bucket. Thus all final leaves are at or below
the original cap, and total payments plus new holds equal the available money.
Paid records may exist without this week's ascents; excess from them still has
only ascent riders as redistribution recipients.

**Keeper round 2:** a missing recipient registration does not reject the ride,
block the week, or discard the person's capped share. Allocate normally, then
retain that share as a person-attributed hold with its original source age.
It is not available for another person's allocation. Within the same original
source and week, ordinary bucket labels precede `reserved:<person>` in the
existing UTF-8 allocation order; this keeps attribution deterministic when
ordinary earnings and an older person hold compete for cap headroom.

## 6. Holds, sponsorship and boosts

A held tranche retains asset, hill, source lineage, original distribution week,
due week, reason/bucket and any boost window. Outstanding holds include fully
escrowed **future** sponsor tranches; future due dates prevent early spending.
An absent Legend's 10% remains a Legend bucket; it is not split 65/25/10 again.
A non-live yield pot stays whole until a live week. Cap excess retries as ascent
money, subject to the next week's cap and any original boost restrictions.

Person-attributed holds release only to that person's immutable recipient once
registered. They join that later week's combined entitlement and cap; any
remainder stays attributed, never redistributed. They have already earned
their share, so release does not require fresh riding or a newly live hill.
The keeper retains the attribution in its database and aggregates it in the
on-chain cap-hold bucket. At original age 26 expiry takes precedence, moves the
amount to pool, and removes the payable person attribution.

At settlement `w`, a tranche born for distribution in week `b` expires when
`w-b >= held_age_weeks`, initially 26. Age is measured from its original
distribution close, not from keeper execution, release attempts, or a city
season boundary. Future boost tranches begin ageing at their own due week, not
at posting. Expiry takes precedence over release. Mark expired money `pool` and
keep it reserved forever in stage 1: it can no longer pay the originating hill,
and a later shared-pool module needs an explicit internal custody handoff.
Such a transfer would not create new income. Assigned unclaimed leaves never
expire under this held-money rule.

Before a settled funding book closes, every remaining ordinary hold moves into
its permanent hill/asset cursor. The carried entry retains the source PDA,
original week, five buckets, lineage, revision, pool history and any prepared
release proposal. Closure does not restart its age or change a ledger value.
Release and expiry accept the absent original funding PDA as a witness to that
entry; they never recreate the book. Entries disappear when their held balance
reaches zero. The cursor prepays capacity for 26 entries once, bounded by the
original-age rule. Sponsor boost tranches retain their separate stream records,
windows and cash-hold ring; closing a funding book does not discard them.

Sponsor USDC is received into cash escrow exactly once and pays the ordinary
split without fee. A boost is irrevocable USDC sponsorship, fully received at
posting, with immutable ID, funder, unique hill list, total amount, start week,
1–13-week **riding** duration and integer hill/ride-week schedule. It must
start 1–13 weeks after the current city week. Every hill-week tranche must be
at least 1 USDC (1,000,000 base units) after Hamilton allocation. These two
bounds are **Claude's default, revisable by Tim**. IDs belong to their funder;
another funder may independently use the same ID. No cancel/refund operation
exists and funding does not create a backer position or DUNG.

Apportion the full boost equally across chosen hills and **N riding weeks**
for an N-week riding window. There is no extra tail week or separate late-upload
budget. Hamilton dust ties use hill UTF-8 bytes then chronological week.
Ascents must have been ridden in the original half-open riding window, in the
week being settled, and uploaded within seven days. An upload after the window
closes still shares that ride week's existing budget if it arrives strictly
before the week's close plus the normal 86,400-second finalization grace.
At or after that cutoff it cannot participate in the boost, even if the keeper
has not yet run. No settled root reopens and no upload earns two boost weeks.

Board and Legend shares use each ride week's normal frozen seats and seasonal
field; they are not restricted to people who rode during the boost window.
Late uploads do not alter those snapshots or that week's ordinary cash/DUNG
records. They still enter their ordinary upload week's records and field.

Unused cash may retry only through the final riding week's settlement, retaining
its bucket and original age. After the window, it stays held for the existing
26-week pool-only fallback; later unrelated riding cannot claim it.
Empty window, no riders, no field,
empty seats and exhausted cap headroom never refund the funder. The obsolete
`boost_tail_weeks` budget parameter is removed; the seven-day upload-age limit
and 86,400-second finalization grace are unchanged.

## 7. Constant DUNG mint data

For an opening-bonded hill with the field, take this upload week's admitted
climb-TSS whose original riding happened at or after bonding. Potential units
are `floor(TSS_micros * 10^9 / (10^6 * 1000))`. There is no year schedule,
halving or lifetime cap in this new module. Sub-unit weekly mint dust is
unminted; it is not a later claim. Below the field or during the partial bonding
week no issuance is admitted and there is no later catch-up.

The composed release leaves both the deployment-wide TSS ceiling and the
issuance start week **unset**. The admin must deliberately configure a positive
ceiling and a prospective start before issuance. The prior audit's suggested
ceiling remains **20,000 climb-TSS per hill-week** (`20_000_000_000` TSS micros),
limiting potential to 20 DUNG; it is a revisable suggestion, not bootstrap state.
A zero ceiling is the explicit unset value and is allowed only with no start.
Publication above the configured ceiling is refused.
Unset and pre-start weeks cannot publish a DungMint. A changed start must open
at or after the executing Clock second, including re-enabling after disabling;
past weeks cannot be enabled retroactively. A cap-only update may retain an
already active start. The effective next week is the later of the hill's DUNG
cursor and the configured start, so pre-start weeks need no empty attestation.
No production cutover week is selected here (PROTOCOL_TRUTHS §16.8).

Each rider or backer DUNG claim set opens **172,800 seconds after its own
publication**, including a root published long after its DungMint froze.
The delay is a waiting period, not a challenge, cancellation or root-replacement
mechanism. Already published allocations and roots survive later ceiling/start
changes. Cash claims are unchanged. The admin setter executes immediately under
the current `ProgramConfig.admin_authority`; the planned seven-day governance
delay must be supplied by the external multisig when it becomes admin. Local
tests do not prove that authority or timelock deployment.

Split the fixed potential 50/50 riders/backers. Within riders' half, use
55% top ten / 35% post-bond verified ascents / 10% earned Legend. Missing
recipients leave that share unminted. The publisher supplies each role's
registered-recipient payable total; the program bounds each total independently
by that role's allocation ceiling. Each role's root must equal its frozen
payable total. Unregistered shares are neither reassigned to another role nor
held for later minting when registration arrives. Backer weight at opening is
`min(basis, floor(units*rate)) * lock_weight * founder_multiplier`. Eligible
active lots aggregate by owner; exiting lots and zero weights are excluded.
Lock weights are 0.25 / 0.5 / 0.75 / 1.0 for 0 / 13 / 26 / 52 weeks. After a
chosen lock expires, its weight becomes the unlocked weight at the next opening.
Founding lots, including seed lots, multiply weight by two for the hill's own
first 26 full opening-bonded weeks. If bonding occurs in city week `b`, the
first full opening is `b+1`; the bonus applies through `b+26` and ends at
`b+27`. A bond transaction exactly at a boundary still follows that boundary's
snapshot. Non-live weeks and weeks without the field still count toward the
26 weeks. City season boundaries do not shorten or reset the bonus. Lock
expiry still lowers the underlying lock weight independently. This changes
division **inside** the backers' half, never potential issuance.

`DungMint` records potential, rider allocations, backer allocations and unminted
units. Their sum equals potential. It is mint instruction data, not an actual
mint transaction, market value, or source of money for the per-asset cash invariant.

## 8. Merkle-sum claims and accounting

**Automatic payout (Tim, 15 Oct 2026).** Once a week's set is final, the keeper
submits every registered recipient's claim: cash immediately, DUNG after that
role set's 48-hour wait. Riders sign only their immutable recipient registration.
Claims remain permissionless and bound to that recipient; riders can submit
their own while the keeper is unavailable. A keeper outage never expires or
closes an unpaid claim. After full payment, the keeper closes each set and then
its weekly funding or DUNG mint record, returning rent to its recorded original
payer. Closure is permissionless and cannot redirect the refund.

The lifetime cash ledger, DUNG allocated/minted counters, publication commitments
and monotonic week cursors live outside weekly records and never close. No week
can be created or published twice, even after all of its weekly PDAs disappear.
Closure changes none of the three accounting equalities below.

For each processed, non-skipped week, one immutable claim set per
`(deployment, city, hill, week, asset)` aggregates
one positive leaf per person and binds the registered recipient. Sort people
by UTF-8 bytes, index from zero, and serialize JSON arrays with UTF-8,
`ensure_ascii=False`, sorted object keys and compact comma/colon separators.
Context is `[deployment,city,hill,week,asset]`; leaf data is
`[context,index,person,recipient,amount]`. Hash domain is ASCII
`BR-stage1-v1:` followed by `leaf`, `empty` or `parent`, then one NUL byte.

Leaf digest hashes domain plus serialized leaf data. Empty digest hashes its
domain plus serialized context and has sum zero. An odd level pads with that
context-bound empty node, **not** a duplicated monetary leaf. Parent digest
hashes its domain plus `left_hash || left_sum_u128_be || right_hash ||
right_sum_u128_be`; its sum is checked `left_sum + right_sum`. Proofs contain
sibling hash/sum pairs; index bits determine sides and the committed leaf count
determines proof depth. Hash and root sum must both match.

Claims authenticate the person and fixed recipient, verify membership and
atomically mark `(hill,week,asset,index)` in the claim set's prepaid bitmap.
Only the index is marked. A duplicate person at different indices is a publisher
allocation error: the publisher already attests allocation and person uniqueness.
Both valid indices may pay, but the committed Merkle sum and funded custody
still bound the total. This does not authorize duplicate allocations in the publisher.
The publisher pays this storage before or together with publication. A claim
creates no tracking account and requires no tracking rent from the recipient.
A replay or redirect changes nothing. Reserve funding precedes root publication. A claim moves value from
outstanding claimable to cumulative paid; fees are not taken again. Empty
roots cannot be claimed. Production needs durable leaf/proof availability and
authorized snapshot attestation: a root alone proves neither riding nor fair
allocation. The offline Python objects are an oracle, not a security boundary
against callers directly mutating their internals.

A hill/asset chain starts at hill admission, not at city week zero. A permanent
cursor advances after a funded settlement or an on-chain proof of empty weeks;
a skipped week has no required funding book or claim set. Skips must prove the
absence of new income in the skipped span. Held money may cross quiet weeks
only when the skip ends strictly before both the earliest active hold's
original week plus 26 and the next boost tranche due week. Skips change no
ledger value or original hold age and never make pool money available.
Assigned claims from earlier processed weeks remain payable after a skip.

For **each** cash/payout asset, every successful action enforces the stronger
equality version of the requested solvency bound:

```
paid_lifetime + fees_assessed_lifetime + claimable_outstanding + held_outstanding
    = realized_net_income_lifetime + admitted_cash_lifetime
earnings_custody = fees_due + claimable_outstanding + held_outstanding
deposits + admitted_cash
    = lot_units + owner_reserves + owner_returns + earnings_custody
      + paid_lifetime + fees_paid
```

Here net income is after provider costs and **before** BoulderRoller's one fee.
Fees assessed includes due and paid exactly once. Principal, pre-bond reserves,
rate appreciation, DUNG and internal carries are never new income. All rejected
actions roll back their entire state. Equality alone does not prove ownership;
the no-appreciation and partial-exit regression tests specifically guard that.

### 8.1 Milestones 2a and 2a.1: local claim program encoding

`boulderroller-v2-r19ey` and `boulderroller-v2-yokjf` introduced the settlement/claim interface inside unreleased
0x4D. The composed release (`boulderroller-v2-7nijk`) replaces receipt/index
accounts with prepaid claim-set storage and adds preparation and batch calls;
the final 0x4D IDL, rather than any slice's intermediate ABI, is authoritative.
The admin sets or revokes `Stage1CityConfig.publisher`; that key can freeze
weekly measurements, publish funded roots and prepare/execute hold transitions.
It has no principal, asset-configuration or admin authority from that role.
Sponsor cash/boost support is described in §8.2, and bonded-hill DUNG in §8.3.
Keeper and proof-serving APIs remain outside these milestones.

For DUNG, `configure_stage1_dung` uses the current program admin, not the
publisher. It stores the deployment's TSS ceiling (zero means unset) and
optional prospective start week (default unset)
in the singleton city config. DungMint publication refuses over-ceiling inputs.
The stored start is `dung_start_week_plus_one`: zero means unset, otherwise
subtract one to obtain the start week. The setter accepts an optional week.
Publication refuses unset and pre-start weeks; publication and skip use `max(cursor, start)`.
Each role's immutable claim set records its publication Clock second and
claims refuse execution before that second plus 172,800. Cash does not gain
this wait. The external admin multisig must enforce seven-day governance;
the program's existing admin signer path supplies no internal admin timelock.
Later parameter changes govern new DungMints, not already frozen entitlements.

**Backer checks on chain only bound attested aggregate totals.** Which backers
receive DUNG, how much each owner receives up to basis, and founding treatment
per owner are publisher attestations, not on-chain enforcement. The program
does not inventory lots or recompute owner entitlements from custody accounts.

For this implementation, namespace strings are the base58 program ID, city PDA,
permanent hill PDA and mint public key. Person strings are signer public keys;
`register_stage1_recipient` immutably binds a person to a recipient wallet. The
person signs authorization; a separate `payer` signer may pay all registration
rent. A zero-SOL embedded wallet can register, and neither payer nor publisher
can redirect or replace the create-once registration.
For a payable leaf registration must precede or share the frozen snapshot's Clock second; exact
within-second ordering is not inferred. The immutable registration and leaf
both bind the recipient, and the SPL destination must have that wallet as owner
and the committed mint. This authenticates wallet control, not unique humans.
The publisher still attests people, sporting inputs, field, median and fairness.
Without registration, the keeper applies the person-attributed hold rule in
§§5–6; no leaf is created until registration exists.

Keeper copies of identities and ride/upload timestamps follow the existing
account-deletion lifecycle. Settled identity fields become its anonymous marker;
private timestamp preimages are removed. Amounts, original leaf indices/hashes,
proofs and commitment envelopes remain reproducible. New snapshot commitments
bind retained component digests, permitting deletion of private preimages;
encoded copies of those preimages are not a deletion substitute. This does not
change permanent on-chain commitments or the lifecycle's existing value gates.
The claimed-index bitmap prevents replay of an index. Duplicate-person allocation
is the publisher trust boundary described in §8; roots still cannot be replaced.

**Keeper interface.** `prepare_stage1_claim_set(leaf_count)` and
`prepare_stage1_dung_claim_set(role, leaf_count)` reserve the canonical set PDA
for the current publisher. Preparation handles a prefunded system account,
charges only missing rent, and grows by at most 10,240 bytes per instruction.
The current publisher can resume preparation after key rotation and correct
an unsealed capacity, including shrinking it; excess lamports stay in the
account. Cash preparation requires a frozen snapshot: an unfrozen empty book
may still be skipped and must not strand an unsealed claim set behind its cursor.
Preparation changes no funding, root, cursor, or claim-opening time.
Publication requires the complete allocation and exact capacity, then seals it
atomically with existing accounting. A sealed set cannot resize, reset or
replace its commitments. Preparation and publication may share one transaction
when its complete serialized message fits.

The compact cash header is 275 bytes; the DUNG role header is 140 bytes,
including the eight-byte Anchor discriminator. `storage_version = 2` uses a
raw LSB-first bitmap of exactly `ceil(N/8)` bytes. No person-key trie, receipt
or index account remains. `leaf_count` is at most 65,536; its largest bitmap
is 8,192 bytes, so every supported set fits one 10,240-byte allocation.

Cash retains the claim context, root, total, leaf count and progress. The other
immutable fields are committed in one 32-byte `metadata_hash`. Fixed Borsh
encoding hashes snapshot, source lineage, release commitment, boost commitment
and new holds under `BR-stage1-v2:cash-audit\0`. The terms hash is SHA256 over
`BR-stage1-v2:claim-terms\0`, the set public key, little-endian cap u64,
frozen time i64 and that audit hash. Each cash claim supplies the 48-byte
`Stage1ClaimTerms` witness (cap, frozen time, audit hash), checked before any
registration, proof or progress change. Durable proof bundles must retain this
witness; absent metadata cannot be invented from a root. `Stage1CashPublished`
emits every full field. The permanent settlement cursor rolls SHA256 over
`BR-stage1-v2:cash-publication\0`, its prior digest and the event's Borsh bytes
(without the event discriminator). Failed publication cannot advance it.

`close_stage1_claim_set` and `close_stage1_dung_claim_set` are permissionless
only when sealed, paid equals total and claimed count equals leaf count. Empty
published sets qualify immediately. Rent returns to the immutable first
preparer, including unsolicited lamports; later preparation top-ups contribute
to that same refund. Neither publisher rotation nor the closer redirects it.
`close_stage1_week_funding` requires the permanent cursor strictly past the
week, zero available money, completed frozen boost processing, and the canonical
cash set absent. Positive ordinary holds are carried as specified in §6. An
untouched book passed by an empty-week skip also closes; no skipped set is
created. The original `open_stage1_week` payer receives its rent and donations.
`close_stage1_dung_mint` requires the permanent hill DUNG cursor strictly past
the week, both published-role bits, both canonical role sets absent, and minted
amounts equal to both allocations. Its original publisher receives its rent.
Skipped DUNG weeks create no mint or role record; zero allocations publish empty
sets that close immediately. While a parent remains, its publication flag/bits
prevent reopening its closed sets. After parent closure, permanent cursor checks
refuse its sole creation instruction, so no set can be prepared or republished.
Idempotent cursor initialization cannot reset progress. Assigned unclaimed
leaves never expire; a partially claimed set or its parent cannot close.
Publication events and permanent commitments survive closure. Fully paid cleanup
remains possible during pauses because no rider entitlement is removed.

`claim_stage1_batch(person, leaves)` accepts 1..4 distinct cash sets of one
asset/mint, in writable remaining-account order. Each leaf supplies index,
amount, the unchanged proof and its cash terms witness. One fixed registration/recipient is shared;
every set independently checks its own snapshot time and namespace.
`claim_stage1_dung_batch` takes corresponding writable `(DungMint, claim set)`
pairs and applies each role's own 48-hour wait. Rider/backer sets may share a
DungMint without losing either progress counter. A duplicate set, bad final
proof, or failed aggregate SPL transfer/mint rolls back every preceding update.
Clients must measure the serialized transaction (maximum 1,232 bytes) and
simulate compute before submission; four is a count ceiling, not a promise
that four maximum-depth proofs fit. Split larger inputs without changing proofs.

Receipt-era sets cannot be decoded as fresh empty bitmap accounts. This release's
cutover requires a finalized publisher disable followed by a complete,
discriminator-only inventory proving fresh Stage1 financial state: every known
Stage1 type except the separately migrated city and unchanged recipient must
be absent, including retired receipt/index types and the devnet pool singleton.
Any match, including undecodable data, blocks upgrade and requires a compatible
migration. A live publisher invalidates that inventory gate; each read advances
the finalized slot floor so inventory cannot precede its disable observation.

The frozen snapshot commitment is a required nonzero 32-byte digest, with its
attested cash cap fixed once. `Stage1HillBond.admitted_week` is fixed at admission
(pre-launch admission is week zero). `Stage1SettlementCursor`, at
`[s1v1_cursor, hill, mint]`, starts there and records the next unprocessed week
plus 26 original-week hold balances and prepaid carried-hold capacity. Freezing and publishing require exactly
that next week. The optional preceding-set ABI witness remains checkable when
provided but is no longer required. The program checks the root's total against its leaf count and cap;
each claim also checks its amount against that cap. It does not recompute the
median or sporting allocation. Canonical leaf JSON is constructed directly from
base58 strings and unsigned integers; the §8 domains, NUL terminators, odd-level
contextual padding and big-endian u128 sums are unchanged. Supported trees have
at most 65,536 leaves (depth 16); large proofs use v0 transactions and address
lookup tables. The oracle constructs allocations and proofs independently.

`init_stage1_settlement` creates only the cursor, permissionlessly and
idempotently. `open_stage1_week` requires that cursor and creates a
hill/week/asset funding account permissionlessly. Operators may initialize the
cursor and open the first book in the same transaction. A book may be opened
only from the cursor's next week through the current chain week; prior/skipped
and future books are refused. The cursor is independent for each hill/mint.
A nonzero harvest, including either withdrawal sweep, supplies this writable
account **after** the existing provider-account prefix. All net income enters
its current week; a missing/wrong book rolls back the entire sweep. Its rolling
lineage commitment binds delivered lot, amount and fee, whose preimages remain
in `Stage1IncomeDelivered` events. Same-week yield coalesces here before splitting.
Five bucket balances encode full/non-live, ascents, top ten, earned Legend and
cap holds. Source identity, mint, hill, original/due week and lineage persist in the book
or its permanent cursor carry after closure.
No boost window can exist in 2a.

A release proposal changes no money and acquires no nonexpiry right. It records
remaining source buckets against a specific frozen target and source revision.
Publication consumes distinct sorted source accounts atomically, preserving their
remainders and recording their complete bucket transitions in a release digest.
New holds cannot exceed the new week's own funds, so released money cannot be
reborn. Root total plus new holds must equal current available funds plus actual
unexpired releases. Each positive source transition must match its cursor
slot's prior balance. At week `w`, the ring slot `w mod 26` must be empty before
new holds can occupy it: any positive `w-26` remainder must first expire, either
in publication or explicit expiry. A zero slot requires no historical empty
book. Explicit expiry targets the cursor's next frozen unpublished week and
clears the same original-week slot atomically. Pool remains inside
held obligations forever and cannot fund publication.

`skip_stage1_empty_weeks(through)` is publisher-authorized, advances 1..16
consecutive finalized weeks (close plus 24h grace), and requires each canonical
funding PDA in chronological order. Every witness must be absent (System-owned,
zero data; unsolicited lamports confer no income) or an untouched book: zero
available/net income/lineage/holds/pool, no snapshot, publication or proposal.
Lineage must be zero even if cumulative fee rounding took the entire harvest.
Missing, duplicate, reordered or foreign witnesses fail with whole-state rollback.
No account is created by skipping, and old weeks cannot later receive income.

**Quiet hold rule (2b Round 2):** a skip must end strictly before the earlier
of the earliest ordinary/cash hold's original distribution week plus 26 and
the next boost tranche due week. For each occupied 26-slot ring entry, in-order
progress determines that exact maturity as
`next_week + ((slot + 26 - next_week % 26) % 26)`. The ledger and hold slots are
unchanged by a skip. The existing slot-empty check at publication still forces
expiry before a maturity slot can be reused. Pool and assigned claims do not
block quiet spans. Frozen books, staged releases and new income remain
unskippable under the canonical witness checks; a quiet skip is not evidence
that a held bucket has become eligible or been paid.

The independent oracle's `skip_empty` is deliberately stricter: its hill-wide
cash cursor checks all assets and refuses positive DUNG allocation previews
before advancing. Admitted DUNG records have their own issuance cursor.
The on-chain cash cursor governs only its own mint; no other asset's progress
or obligations can be discarded.

The asset ledger enforces all three §8 equalities. Before publication, available
income is a subset of held; pool is also a subset of held. `owner_custody` stores
`sum(lot.units + lot.owner_units)`, so internal principal/reserve partitioning
preserves that total and existing readonly account metas. Cash admission and fee
withdrawal are absent, hence admitted cash and fees paid are zero in 2a. Every
value-changing path checks the equalities; earnings operations additionally
require actual SPL custody at least equal to tracked earnings. Unsolicited tokens
remain untracked. Solana transaction rollback covers root sealing, bitmap updates,
source updates, counters and token CPI on any failure.

Evidence is local/offline only. `claim_vectors.py` derives 12 allocation traces
and six median boundary vectors from the independent model. The validator suite
pays those roots in actual local transactions and separately labels adversarial
corrupted snapshots and synthetic maximum-depth trees. The seeded long-sequence
fuzzer exercises production accounting arithmetic on CPU, not live riders or
randomized chain/provider execution. Production attestation, durable proof
availability and deployment remain later gates.

### 8.2 Milestone 2b: sponsor custody and boost schedules (local evidence)

`boulderroller-v2-xz21z` extends the unreleased 0x4D module. The ordinary
claim instructions and publisher attestation boundary in §8.1 also serve USDC.
`register_stage1_cash` creates one immutable `Stage1CashConfig` and its cash-only
asset/earnings escrow. The default build pins
[Circle's native mainnet USDC](https://developers.circle.com/stablecoins/usdc-contract-addresses),
`EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v`. The isolated devnet and localnet
builds register one six-decimal test mint, labelled `is_test`; neither can claim
the mainnet mint or a branded staking mint. Cash cannot be enabled as staking
inventory or acquire a rate, basis, backer lot or DUNG.

`sponsor_stage1` receives actual SPL tokens into that mint's escrow and credits
the current open funding book. `post_stage1_boost` receives the entire amount
atomically with the immutable `Stage1Boost` and one `Stage1BoostHill` per hill.
The boost PDA uses `[s1v1_boost, funder, id]`; only reuse by the same funder
collides. The ID, funder, sorted hill list, total, future start and duration never
change; each hill record stores its exact 13-slot integer schedule. The transaction
implementation supports 1–16 unique registered hills and 1–13 riding weeks;
starts are limited to current city week + 1 through + 13, and every Hamilton
hill-week share must be at least 1,000,000 USDC base units. These bounds are
**Claude's default, revisable by Tim**. Posts above about 6 hills need a rooted
address lookup table; clients/tools request 1,000,000 compute units. The Round 2
devnet-feature probe on a private local validator measured 679,262 CU for
16 hills × 13 weeks, within that limit.
Hill ordering is the UTF-8 bytes
of the base58 hill identity used by claim contexts, followed by chronological
week. There is no cancellation, refund or separate upload-tail budget.

Each receipt increases `admitted_cash_lifetime`, earnings custody and held
obligations by the same delivered units. No fee or harvested-income counter
changes. The first equality's right side is realized yield plus admitted cash;
the custody-source equality's left side is deposited units plus admitted cash.
The escrow-liability equality is unchanged. Unsolicited tokens are not admitted.

Future boost balances remain in their source records and `cursor.future_cash`,
outside the 26-week age rings. A frozen book commits to the current active
stream count and sequence high-water mark. `process_stage1_boost` processes each
of those streams once for that frozen week, in bounded transactions. Future
tranches cannot change; due tranches enter a separate original-age cash ring.
Publisher-supplied remaining buckets obey the same role/cap constraints as
ordinary holds. After the final riding week the exact buckets cannot change
until their own due-week-plus-26 expiry moves them to permanent pool.

Processing stages releases in the frozen book, still within held liabilities;
it does not create claimable funds. Publication requires every frozen active
stream, consumes the staged release once, and binds its transition commitment
in the claim set. A failed publication leaves those funds reserved for that
same frozen book. Streams posted after freeze cannot substitute for omitted
ones. Streams with no future or active buckets retire; staged releases remain
reserved in their frozen book until publication. Two appended cursor minima
track the exact next due week (zero means no future cash) and accumulate the
minimum due strictly after the cursor's current week. The accumulator may be
zero until frozen streams contribute their later dues. Every post updates
both; every frozen stream contributes its immutable future dues to the latter.
Only complete publication promotes that accumulator, then reseeds it for the
advanced cursor. Skips preserve the
next due and reseed the accumulator. This also covers posts during processing
and arbitrarily stale cursors without a bounded future calendar. Quiet skips
obey §8.1's original-maturity and next-due bounds. Ordinary hold slots retain
§8.1's exact-balance checks, and both rings
must clear an expiring slot before reuse.

Sporting truth, seven-day upload admission, daily ascent deduplication, frozen
field/seats, Hamilton splitting/coalescing and the per-asset cap remain
publisher-attested under §§5–6. Differential oracle traces exercise these
boundaries, including late uploads strictly before the cutoff, without claiming
that a token transfer or Merkle root independently verifies a ride. This is
local/offline evidence, not a network release or physical rider outcome.

### 8.3 Milestone 2c: bonded-hill DUNG (local evidence)

`boulderroller-v2-cr5h0` adds `publish_stage1_dung`,
`publish_stage1_dung_claim_set`, `skip_stage1_dung_weeks` and
`claim_stage1_dung`, plus the admin `configure_stage1_dung`, within unreleased 0x4D.
The first freezes one `Stage1DungMint` per permanent hill/week, only after the
week's close plus grace, on an opening-bonded hill with at least five attested
field people. It computes §7 potential and the Hamilton bucket split, leaving
missing recipient buckets unminted. The §7 TSS ceiling and start switch apply;
no legacy year rate, lifetime cap, carry or cash cursor is consulted.
A rejected partial/below-field week creates no record or catch-up.
Zero-TSS eligible weeks may commit zero allocations.

The fixed-size opening input contains eight basis/backing buckets: ordinary and
founding lots, each in 0/13/26/52-week lock order. Backing is the **sum of each
lot's** `min(basis, floor(units*rate))`, excluding exiting and zero-weight lots;
owner weights aggregate before Hamilton allocation. Quarter-weight integers
preserve exact fractions. A nonzero source hash commits historical lots, rates,
owners and sporting inputs. The input also binds each role's registered-recipient
payable total, bounded independently by that role's Hamilton allocation ceiling.
Their difference from potential remains unminted; no role may absorb another's
missing share. The 226-byte mint record stores city/hill/mint/week, two payable role
totals, unminted amount, frozen time, minted counters, publication bits, bump,
snapshot digest and original rent payer. Root totals must equal the frozen payable
totals, including zero-leaf roots when no allocated recipient registered.
`Stage1DungPublished` emits the full input, allocation and exact backer weight.
Its snapshot is SHA256 of `BR-stage1-v2:dung-publication\0` and the full Borsh
event bytes (without the discriminator). The hill rolls that digest under
`BR-stage1-v2:dung-history\0`; each `Stage1DungRolePublished` event then extends
the same hill commitment under `BR-stage1-v2:dung-role-history\0`. Event order
is execution order, including independently delayed role publication. The
hill commitment and lifetime issuance state remain after the weekly mint record
closes under §8.1. The hill's monotonic DUNG cursor permanently prevents its recreation.

The program checks backing <= basis in every bucket, total basis <= retained
lifetime deposited basis, and founding basis <= the ceiling frozen at bonding.
That founding ceiling currently includes all held hill basis at bonding,
including excluded lots. The retained slot masks distinguish membership, but
slot aggregates store lot counts and capped/repriced backing, not original
basis by slot. Backing can be below basis after loss, so substituting it would
wrongly reject later recovery. An exact founding-only ceiling needs additional
per-hill-slot basis tracking or lot inventory; Round 2 adds neither.
Current held basis cannot bound a historical opening after withdrawals. Frozen
founding membership must exist; founding lots may occupy only the 26-week bucket
before their exact bond-time lock expiry, or the unlocked bucket thereafter.
Their multiplier is independently restricted to hill weeks b+1 through b+26.
Ordinary deposit maximum lock ends bound positive locked buckets when
`founding_count == campaign_count`: no excluded pledge can later convert.
That equality also bounds ordinary basis by lifetime deposits minus the frozen
founding ceiling. Otherwise ordinary lock expiry remains attested, because the existing conversion
ABI has a readonly hill and supplies no complete aggregate lock-end history.
These are conservative bounds, not proof of individual inventory, rate freshness,
owner completeness, exiting status, or fair owner/seat allocation. Those remain
publisher attestations under §8.1. Existing custody instruction metas are unchanged.

A separate hill DUNG cursor starts at bond-week+1. Publication freezes exactly
`max(cursor, configured start)`, and no publication or skip runs while the start
is unset. The publisher may skip 1–16 finalized zero-potential weeks with
a nonzero source digest, maximum seasonal field count and u128 total admitted
post-bond TSS: max field <5 or total TSS =0 must hold. Their truth is the same
sporting attestation as publication, not an independent on-chain ride proof.
A domain-separated hash and event bind the range and summary. Positive potential with
missing recipients cannot use this skip. Cash cursors and already published
DUNG claim sets are unaffected.

Each immutable `Stage1DungClaimSet` has role 0 (riders) or 1 (backers), and its
sum must equal that role's frozen allocation exactly. §8 JSON/hashing/proofs are
unchanged; the asset string is `<configured DUNG mint>:riders` or `:backers`, so
proofs cannot cross roles. Both roles can be published with the mint record in
one transaction, or independently afterward. Registrations must predate/share
the mint record's freeze second; index bits prevent replay within a role. A person legitimately paid in both roles can claim both.
Each role opens at its own `published_at + 172800`, independently of the mint
record's freeze time or the other role's publication time. Both single and batch
DUNG claims also require settlement to be unpaused; resuming releases a mature
claim without resetting its timer. Cash claims stay open because funded custody
already bounds their payout.

Claims invoke SPL `mint_to` through the existing DUNG authority PDA to the
registered recipient's configured nine-decimal mint account. `Stage1DungState`
tracks separate u128 allocated/minted lifetime totals; per-role and per-week
progress cannot exceed allocations. No `DungMintState`, legacy emission counter,
reservation, cap, or cash ledger enters these instructions. Failed token CPIs
roll back bitmap updates and counters. Storage preparation starts no wait;
only immutable root publication sets `published_at`. No cutover week or deployment is selected.
The oracle's equal top-ten seat division remains reference behavior, not a new
ratification of a rank allocator (root protocol amendment §16.5).
The oracle's `Settlement.dung` and `dung_claim_sets` are allocation previews;
only explicit `publish_dung` and `publish_dung_claim_set` admit records and
start claim waits. Cash settlement remains independent of DUNG admission.

### 8.4 Composed release authority roles

The same seven-day Squads admin controls program upgrades, configuration,
asset admission, DUNG policy and publisher/guardian/registrar rotation. The
wait starts at threshold approval. Configuration authority remains unset;
there are no spending limits. Proposal review includes every stale Approved
proposal, because member removal does not make prior approvals unexecutable.
Stale Active proposals cannot become approved and do not make status unsafe.

The guardian can pause **and resume** intake and settlement immediately.
Intake includes pledge, bond, conversion, sponsorship and boost posting.
Settlement includes cash snapshots/roots, hold transitions, boost processing,
empty-week skips, DUNG publication, DUNG role roots, DUNG skips and DUNG claims. These
instructions only change the two city flags. Guardian authority never permits
a transfer, a claim rewrite, a rate/lock change or an admin configuration.
Already published cash claims, harvest and eligible owner exit remain available
during either pause. DUNG claims wait during settlement pause even when mature;
intake pause alone does not hold them. Locks and the 48-hour wait still apply.
The admin can replace the guardian through its seven-day process; replacement
preserves both flags. **Claude's default after the audit, revisable by Tim:**
a small separate multisig with no delay serves as guardian. Tim chooses its
members and threshold; this release does not invent them. Guardian resume is
**Claude's default**: a compromised guardian can lift its own pause, and only
the admin can replace it after seven days. This fails open against guardian
compromise. A separate pause-only key is the documented alternative for Tim to
choose later; this release does not implement or select that alternative.

A separate registrar may call only `registerRatifiedClimb` and `initHillBond`
without the admin wait. Registration still verifies the ratified canonical
identity and continuity rules. For the unchanged legacy registration account
list, a registrar supplies the canonical city as the sole read-only remaining
account. Admin registration remains compatible. Hill admission reads the
same city role. This key cannot enable assets, publish claims, change policy,
pause, or move funds. The seven-day admin can replace or revoke it (zero key).

Guardian and registrar remain separate from admin, publisher, backend and
each other. Operator preflight additionally excludes admin multisig members
and its vault, including prospective member additions and batched role edits.
Raw legacy/Squads calls can bypass that operator policy; the governance status
check must then report the actual unsafe combination. See the composed
[upgrade procedure](../../docs/runbooks/STAGE1_DEVNET_UPGRADE.md).

## 9. Ratified decisions and remaining source boundaries

**Round 2 cutover decision, no legacy code change:** BeetleCard upgrades and
DUNG-paid vault creation burn from the shared DUNG mint without distinguishing
issuance origin. Their legacy accounting increments burned totals and requires
burns not to exceed legacy `DungMintState.total_minted`. Bonded-hill
issuance updates its separate state, so spending that fungible DUNG skews the
legacy records; on a zero-start mainnet with zero legacy lifetime issuance,
any positive such burn would fail the legacy invariant. Cutover must decide
how those burn paths and counters account for the shared supply before enabling
bonded-hill issuance. This milestone neither repairs those counters nor enables
a public start week.

1. Principal: SOL redemption value at deposit, returned in the same token,
   with losses in the originating lot — **ratified by Tim, 13 Oct 2026**.
2. Realized yield: surplus units actually transferred to earnings custody,
   paid in kind, with no harvest below basis — **ratified by Tim, 13 Oct 2026**.
3. Pilot caps: 2,000 SOL per token, 500 per hill and 5,000 in total, with
   timelocked increases — **ratified by Tim, 13 Oct 2026**.
4. Seasons: one 26-week city calendar anchored at launch, with Monday
   12:00 UTC weeks — **ratified by Tim, 13 Oct 2026**.
5. Rider-week cap: 3× the median of positive combined entitlements per asset,
   with excess redistributed by ascents within headroom, then held —
   **ratified by Tim, 13 Oct 2026**.
6. Boosts: in stage 1, escrowed at posting, irrevocable, 1–13 weeks, normal
   split, zero fee and no DUNG — **ratified by Tim, 13 Oct 2026**.

The following mechanics are also **ratified by Tim, 13 Oct 2026**: the founding
2× lasts the hill's own first 26 full bonded weeks; boosts pay by ride date with
no separate late-upload budget; cash and boosts can fund non-live/unbonded hills
in a launched city; weekly snapshots, no partial-week DUNG, owner rounding dust,
and lock-expiry weight reductions stand. Pre-bond owner surplus, donated yield
through actual exit liquidity, held-money ageing and claim nonexpiry remain as
specified above. The two timing clarifications are implemented in §§6–7.

No policy question from this ratification round remains open. Deployment
identity, accepted asset mints/rate adapters, freshness bounds, identity
attestors, TSS precision, legal admission and production custody/authority
proofs retain their later implementation gates; this offline milestone supplies
none of those external facts. The funding decision and Jon's review of
principle 7 wording are recorded in [FUNDING.md](FUNDING.md); no additional fee
is deducted from rider money in this model.

The supplied sources conflict in these concrete places:

- DESIGN's SOL-only summary versus its in-kind custody rule and this brief's
  in-kind default; original-token-count wording versus SOL-value principal.
- DESIGN's “running totals” description of held money versus the plan's
  outstanding holds/claims. Repeated carries cannot be counted repeatedly.
- DIAMOND's historical text marks boosts proposed; the ratification above and
  `stage1` metadata now admit them. Its
  “always get paid” wording cannot literally guarantee each ascent an immediate
  positive amount under field, cap, integer rounding and held-money rules.
- Hill-first founder bonus and city-wide field seasons now coexist as specified
  above; the city calendar no longer truncates a late hill's founding bonus.
- Legacy `PROTOCOL_TRUTHS.md` §§4, 6.4, 8.5 retain a 30-day tribute flow,
  bootstrap paid Legend and caps/halvings. The new module uses seven-day upload
  weeks, earned Legend only and constant bonded-hill DUNG. Those authorities
  and existing liabilities remain unchanged here; implementation needs an
  explicit prospective amendment and cutover, never retroactive rewriting.
