# Hill bonding: the diamond

The diamond has four layers: evidence (to come), analytics (`ANALYTICS.md`, `analytics.yaml`), economy (this file), and surfaces (to come).

Version 1, 8 October 2026. Seven principles, one launch exception and one parameter file (`diamond.yaml`). Every rule of hill bonding should follow from a principle plus a parameter. A rule that doesn't is either a patch to cut or a principle we haven't written down. Source of the rules: `history/explainer-hill-bonding-2026-10-06/DESIGN.md`.

## The seven principles

1. **Real money only.** Every payout traces to realized outside value: staking yield after validator commission, or cash someone gave. Principal is never paid out, and nothing is paid from the next person to arrive. Losses stay with the asset that suffered them. Money that can't be paid yet waits for its owner, with a time limit and a fallback.
2. **The hill is the unit.** Each hill has one canonical identity. Its stake, pay, records and DUNG belong to it, and hills don't share money except through the shared pool.
3. **Pay follows riding.** Cash goes to riders for verified riding, counted in ascents. Cash leans to everyone who rides; the say leans to the records.
4. **Backers risk only yield, plus any loss in their own staking token.** Backers keep their principal and give up its yield. A loss in the staking token a backer pledged stays with that backer's own lot and never spreads to other backers or to riders. Longer commitment earns more weight, and exits are slow and public. (Wording ratified by Tim, 13 Oct 2026; Jon reviews it before public use.)
5. **The say is rented, never owned.** Weight is amount × weeks left ÷ 104. Riding renews a rider's weeks. Capital sets its weeks with a lock and counts at 40%.
6. **Meaning needs a field.** Records, the say and DUNG count only where enough different riders compete, and shared money goes where people ride.
7. **One fixed cut.** BoulderRoller takes 10% of realized yield and nothing else: no fee on cash, and nothing from riders.

## How each rule derives

| Rule | From | Parameters |
|---|---|---|
| The vault invariant: payouts + fees + held-back yield ≤ realized income + cash received, as running totals | 1 | none |
| Yield is paid only once realized, in kind; losses stay with their lot | 1 | none |
| A backer's USDC is swapped to SOL; sponsors pay cash in USDC | 1, 4 (USDC earns no staking yield) | none |
| Pledges sit in escrow, keep their own yield, and can be cancelled before bonding | 4 | none |
| One bonding line per city; a bonded hill is live while its stake is at least half the line | 2, 6 | `line_sol`, `live_fraction` |
| 26-week bonding lock, 4 weeks' notice; later stake chooses its lock | 4 | `bond_lock_weeks`, `notice_weeks`, `lock_options` |
| 65% to every rider by ascents, 25% to the top ten, 10% to the Local Legend | 3 | `rider_split` |
| Pay by ascents, not TSS | 3 (TSS is the gameable part) | `ascents_per_hill_per_day` |
| One seat per identity, a cap of 3× the median rider-week, the board frozen at week end, 7-day uploads | 3 (verified riding) | `rider_week_cap_x`, `upload_window_days` |
| The 10% fee falls on yield only; sponsor cash and gifts pay none | 7 | `fee_on_yield` |
| Sponsor cash is split like yield | 3 | `rider_split` |
| A hill that is not live carries its yield forward; an empty seat's share waits; after a season, both go to the shared pool | 1, 2 | `season_weeks` |
| The minimum field: records and DUNG switch on at 5 riders a season, while ascent pay flows from day one | 6, 3 | `min_field_riders` |
| The CAL claim: a fifth of the riders' share, with riding as the lock and capital at 40% | 5, 3, 4 | `claim_share_of_riders`, `timer_weeks`, `capital_weight` |
| DUNG: 1 per 1,000 climb-TSS on bonded hills, half to riders and half to backers | 3, 4 | `dung_per_climb_tss`, `dung_split` |
| Riders' DUNG: 55% records, 35% every rider, 10% Local Legend | 3 (the say leans to the records) | `rider_dung_split` |
| Backers' DUNG weighted by lock: 0.25, 0.5, 0.75, 1.0 | 4 | `lock_weights` |
| Vote weight runs on the same timer; DUNG received from someone else votes once locked, at 40% | 5 | `timer_weeks`, `capital_weight` |
| The shared pool holds gifts, any trading fees and stranded money, and pays riders only | 1, 3 | none |
| No hill takes more than twice its share of the week's ascents; the rest goes out by ascents | 6 | `pool_cap_x` |
| No bribes; donors get a title, not DUNG | 3, 5 (the say can't be bought) | none |
| The pool starts once there are gifts and at least two bonded hills | 6 (a vote needs a choice) | `pool_min_hills` |

## Settled on 8 October

These four rules didn't derive. Tim settled them so they do.

- **The founder's seat is a title only.** The backer whose pledge bonds a hill is its Founder, a title. The Local Legend seat's 10% waits for a rider who earns it, like any empty seat. (Principle 3.)
- **CAL claims wait for the field.** Below 5 riders a season, the claim share stays with every rider. (Principle 6.)
- **DUNG is minted at a constant rate:** 1 per 1,000 climb-TSS on bonded hills, in every year. The same ride earns the same DUNG whenever it happens. The lifetime caps and halvings in `PROTOCOL_TRUTHS.md` retire for bonded-hill DUNG, which needs an amendment there. (Principles 3 and 5.)
- **Launch exception: founding backers get 2× DUNG in their hill's first season.** It is the one rule that does not derive from a principle, and it is kept on purpose, with its end date, to reward the backers who start a hill.

One mechanical fix, applied: the design said "20% of yield" for CAL claims in four places. The rule is 20% of the riders' share, which is 18% of yield.

## Markets and whales

Added 8 October from the sessions on intake, token-led expansion and whale strategy. The sources are in `history/codex-reports-2026-10-08/` and have been fact-checked. Items marked **proposed** wait for Tim; the rest restate or apply rules that already exist.

**Ratified by Tim, 13 October 2026**, following the tournament in `history/economy-tournament-2026-10-08/`:
1. Riders can sell CAL the moment they earn it. The app shows cash value and token value separately; holding remains a choice.
2. **Every payout is funded, and riders are paid in every phase.** This replaces the universal promise that no one profits without paying riders first: the tournament's pure trader made $571 from late buyers without backing. Rider pay does not guarantee a profit on retained tokens or cover every riding cost.
3. Price ladders switch on only with a deep enough market, an independent price reference and a real riding field. Hardening reduced default activation to zero in the tournament. The numerical thresholds and synthetic reference remain model assumptions, not ratified production settings.

These decisions change the two reference-model defaults, `model.default.immediate_cal_sale` and `model.default.hardened_ladder`, to `true`. Named legacy scenarios retain the old behavior. They do not ratify the other proposals below or establish deployed behavior.

### What riders earn

A rider has two incomes:
- **Hill pay:** SOL from realized yield plus sponsor cash and boosts. The protocol pays it, and every rule above governs it.
- **CAL:** minted at one per point of eligible paid training stress. Riders can sell it as soon as earned or choose to hold it. Cash from a sale is shown separately from the value of tokens still held. Market price changes that token value; it never adds to the payout budget, so principle 1 holds.

### CAL's floor

In stage 2, CAL locked on a hill claims a fifth of that hill's riders' share, which is 18% of yield. All CAL together is therefore worth under a fifth of the SOL behind hills, at a 5% return.

The **floor per CAL** is the committed claim stream divided by claiming CAL. It counts only committed weeks, because the unlock calendar is public.
- Committed backing raises the floor.
- Riding mints CAL and dilutes it.
- Anything above the floor is hope.

The floor is published, together with backing per CAL, committed weeks and the unlock calendar.

Two consequences follow:
1. **Backing funds riders through realized yield.** It can increase the committed claim stream. Secondary trading can profit without any new backing, so a price pump does not establish prior rider funding. The calculated stream is conditional on yield, eligibility and competing claims; it is not a guaranteed market or redemption floor.
2. **Backing is a contribution.** A backer gives up their yield, and at most 18% comes back to all CAL holders together. Backing also gives DUNG and the say, the Founder title and a name on a hill. Longer commitments extend the claim stream. Neither that stream nor these benefits guarantee a CAL price or make every back-and-dump strategy unprofitable.

### Who buys CAL each week

- **Riders choose whether to sell or hold.** Riding renews retained claims. The ratified reference-model default sells earned CAL immediately; the earlier regular-hold behavior remains a named comparison, not a requirement to retain exposure.
- **Backers are a recurring bid.** The only way to win back yield is to buy riders' CAL and lock it, and locks run down.
- **Speculators** buy the growth story.

### The games whales can play

Every payout is funded, and riders are paid in every phase. Whale trading profit is a separate market outcome: it need not fund riders first, and it can leave later buyers with losses.

| Game | The move | What the whale wins | How riders get paid | Familiar as |
|---|---|---|---|---|
| The claim | Buy CAL and lock it on a hill | Yield back, at 40% weight | Riders receive funded hill pay; purchases pay the actual seller, who may be a trader or LP | ve-token locking, real-yield tokens |
| The founder | Be first to bond a hill | Founder title, 2× DUNG in the first season, name on the hill | The bonded yield | Genesis status |
| The territory | Back a cluster of hills | The biggest say over that city's shared pool; the story | Every hill's yield | The Curve wars (no bribes here) |
| The duration | Lock long | The market prices committed weeks, which lifts the whale's own CAL | Years of yield | The four-year veCRV lock |
| The ladder (stage 2; hardened trigger **ratified 13 Oct**) | Escrow SOL that switches on at price steps only with sufficient depth, an independent reference and a riding field | Public conviction; conditional expansion | Realized yield from activated backing | Buy walls, programmatic buybacks |
| The boost (**proposed**, stage 1) | Prepay extra pay for chosen hills over a chosen window | Riding where and when the whale wants it | The boost itself | Liquidity mining, steering incentives |
| The season | Name a hill's season in cash | Local attention | The cash | Brand partnerships |

### Boosts (**proposed**, stage 1)

A boost is sponsor cash with a window. The rules follow from principles 1, 3, 5 and 7:
- **Escrowed when posted and irrevocable** for the window. Riders who ride for a posted boost always get paid (principle 1).
- **Paid by verified ascents through the normal split**, with one seat per person, the weekly cap and the five-rider field (principles 3 and 6). Below the field, ascent pay still flows and the record shares wait, as for any cash.
- **No fee** (principle 7).
- **Earns a title, never DUNG.** Money can steer riding but cannot buy the say (principle 5).
- **Public:** funder, hills, amount and window are shown on the map and the backer board.

### Price ladders (stage 2; hardened trigger ratified 13 October)

A backer escrows tranches of SOL with price steps.
- A tranche bonds only when CAL's time-averaged price holds above its step **and** the market is deep enough, an independent price reference confirms the trigger and a real riding field exists. All three checks are required; missing evidence leaves the tranche escrowed.
- Once bonded, it is ordinary backing: the bonding lock, notice and the public calendar all apply. Nothing unwinds when the price falls.
- Each step has a cap.

Because the tranches are real escrowed SOL, the expansion tracks price while every payout stays real yield (principles 1 and 4).

The hardened trigger is ratified; deployment and production oracle selection are not established by the offline tournament. Its numerical depth, field and price checks are unchanged modeling assumptions. The old base trigger is available only as a named legacy comparison in the model.

### Seven alignment rules

| Rule | Status | From |
|---|---|---|
| Earning requires commitment: claims pay only staked or locked CAL, so a cornerer must choose between earning (locked) and trading (liquid, earning nothing) | exists | 5 |
| Riders can sell CAL immediately or choose to retain a claim; retained rider CAL comes back whenever they ask | immediate sale **ratified 13 Oct 2026**; publish staked rider CAL | 3, 5 |
| Backing exits slowly while CAL trades freely; the floor counts only committed yield | exists | 4 |
| Concentration in the open: the largest holders' shares of CAL, DUNG and each city's backing are published | **proposed** | 4 |
| Show cash value and token value separately; retain the separate proposal that the rider app has no "buy CAL" | separate values **ratified 13 Oct 2026**; no-buy proposal unchanged | 3 |
| Price ladders activate only with enough depth, an independent reference and a real field; activated backing supplies realized yield | hardened trigger **ratified 13 Oct 2026** | 1, 4 |
| The say never outlives the stake, and DUNG stays off the market until there is a reason | exists | 5 |

### Strategies the rules must survive

The strategy tournament plays each of these against the rules:
- **Livermore's corner:** back many hills, buy riders' CAL as they sell, mark it up, sell, exit.
- **Back-and-dump:** back, lift the floor, sell CAL, give notice.
- **The crew ride:** back hills and have one's own riders collect the pay, CAL and DUNG.
- **Boost-then-dump:** boost hills, sell CAL into the attention.
- **The ladder pump:** push the averaged price over a step.
- **DUNG accumulation.**
- **Wash trading.**

The ratified promise is funded payouts and rider pay in every phase. Trading profit does not prove prior rider funding. The remaining exposures include late buyers, riders who retain CAL, patient liquid CAL, determined crews, and DUNG on the day it trades. Cash receipts and token valuation must remain separate when checking who gained or lost.

## What derives from this

From the principles and `diamond.yaml`, a reference model computes every example: the example hill, the splits, the pool and the caps. It checks the properties that must always hold:
- the invariant is never broken;
- every split sums to 100%;
- no money is left without an owner or a fallback;
- every cap holds;
- across the strategy tournament, riders are paid in every phase of every strategy; cash, token value and riding costs are reported separately;
- retain the counterexample to the retired promise that no strategy profits without paying riders first;
- every game in the table above can be won by a whale under stated conditions.

The spec section, the `PROTOCOL_TRUTHS.md` amendment, the map's numbers, the public docs and the program's constants are then generated from it or checked against it.
