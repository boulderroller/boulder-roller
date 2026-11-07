# Economy reference model

Offline Python 3.12 study for `boulderroller-v2-m8mye`. This models the supplied hill-bonding rules and proposals, including Tim's three decisions ratified on **13 October 2026**. It does not implement or deploy product behavior. No dependencies beyond the standard library.

Riders can sell CAL as soon as they earn it, with cash and token value shown separately. The promise is **every payout is funded, and riders are paid in every phase**; the universal claim that every profitable trader first funds riders is retired. Price ladders require sufficient market depth, an independent price reference and a real riding field. The two model defaults are now `model.default.immediate_cal_sale: true` and `model.default.hardened_ladder: true`. Numerical assumptions are unchanged and remain unratified.

```sh
/opt/homebrew/bin/python3.12 -m unittest discover -s tools/economy_reference/tests -v
/opt/homebrew/bin/python3.12 -m tools.economy_reference.tournament
/opt/homebrew/bin/python3.12 -m tools.economy_reference.report
```

The second command writes `history/economy-tournament-2026-10-08/results.json`. `--quick` deliberately omits the factorial grid and records `full_grid: false`; it is not equivalent evidence. `--config PATH` accepts the documented YAML subset. The supplied file's SHA-256 and complete parsed parameters are embedded in the output. To inspect a single case:

```python
from tools.economy_reference.config import load_config
from tools.economy_reference.simulation import run
result = run(load_config(), 'livermore_corner', {'speculator_intensity': 0})
print(result['totals'])
legacy = run(load_config(), 'livermore_corner', scenario='legacy_hold_base_ladder')
```

All behavioral, numerical, market, grid and scenario settings are in `diamond.yaml` under `model:`. Only the two behavior defaults above implement these ratified decisions; the numbers are not empirical estimates or ratified product parameters. Existing economic parameters are unchanged. Named scenarios `legacy_hold`, `legacy_base_ladder` and `legacy_hold_base_ladder` disable one or both defaults for comparison. Explicit `overrides` apply after the named scenario. Results retain the effective flags. The original `cash_only_riders` and `harden_ladder` experiment flags remain aliases for enabling those behaviors. The local parser supports mappings, scalar lists, numbers, strings and booleans, not arbitrary YAML features. No PyYAML installation is necessary.

## What is executable

- `accounting.py`: asset/source conservation, outstanding holds, escrow yield, founding/later lots, locks and notice, claims and work boost, cash split/cap, fixed DUNG allocation, lot-specific votes, shared-pool water filling, loss recovery.
- `market.py`: external CAL/USDC AMM, fee/slippage, inventory origins, daily trailing-price/depth oracle, prefunded irreversible boosts, escrowed capped ladders.
- `simulation.py`: verified synthetic rider identities, upload eligibility, independent record and paid-ascent handling, frozen boards, agent transactions, four explicit phases, source-attributed payments and actor accounts.
- `experiments.py`: unfunded trading, cheap claims on other people's funding, retained-token drawdown, named legacy comparisons, no-whale/zero-speculation controls and unratified claim-gate reruns.
- `tournament.py`: deterministic full factorial, default/scale cases, complete phase accounts and machine-readable output.

## Accounting conventions and unresolved policy choices

1. Cash claims use **net staking yield only**, following the more detailed design and token-led intake. Sponsor cash, boosts and shared-pool distributions never fund CAL claims. Below the field, the claim slice goes to ascent riders: 20% plus 65% of the remaining 80%, giving 72% immediate ascent entitlement before the cap and 28% held for records.
2. The field counts unique people in fixed 26-week calendar seasons starting at week zero. Permanent top-ten seats survive season rollover, while eligibility must be re-established. Local Legend uses most eligible ascents in the current season; ties break by stable identity. These season and tie conventions are modeling choices, not ratified sport policy.
3. The median cap applies to **combined direct cash pay per hill/week**, converted at that scenario's fixed SOL/USD rate, across all sources/assets and positive intended recipients, including absent record holders. CAL claims are separate. Unpaid cap excess retains its recipient, source and deadline; it is retried next week. Expiry is checked before release at exactly one season and sends outstanding money to the pool. Pool allocation renews the recipient hold deadline. These cap details need product clarification.
4. Shares without recipients remain funded holds. DUNG without an eligible recipient remains unminted. Founding 2× affects normalized weights inside the backer half, never the mint rate. A bonded ascent resets all of that rider's earned DUNG timers; CAL timers remain hill-specific. Backer votes attach to individual stake lots and decay after each lot exits, following the detailed design rather than interpreting the diamond's shorter phrase as immediate vote cancellation.
5. Long strategies make the mandatory founding pledge and a distinct 104-week later commitment. The longer lock is **proposed**; only its DUNG lock weight is capped at 1. Capital CAL and received DUNG cannot exceed the 104-week timer. The output retains the unlock calendar and the whale's remaining mandatory yield cost after the horizon.
6. All modeled paid TSS is climb TSS; off-hill paid training stress is **zero**. More off-hill CAL issuance would change dilution and market supply. Riders have distinct trusted identities, correct verified ascents and no failed uploads in the tournament; unit tests exercise rejected/late uploads. Identity fraud, work verification, threshold manipulation and identity collusion detection are outside this study. Crew members are distinct real simulated riders, not Sybils.
7. Regulars repeat home hills; visitors are new identities each week; crew ride more frequently and faster. The default sells all earned CAL: issuance is accounted weekly and sales execute across that week's daily market steps, with no intentional retained inventory. This discretization models immediate-sale availability, not a mandatory sale policy or a production execution guarantee. The legacy hold scenarios retain the old sell/hold/release fractions. Hypothetical speculator bids, sponsors' recurring cash and community purchases are exogenous inputs. There is no inferred adoption or retention. Momentum responds to positive weekly price movement with a bounded signal; late buyers arrive in distribution. Default boost attention does not change riding. A separate explicitly assumed 25% route-response run measures steering; it does not prove demand.
8. The AMM starts with USDC and historically earned CAL owned by an **external LP**. Its 0.3% fees stay with that LP and never become protocol income. Purchases' inventory-origin attribution does not imply that the whale paid a rider: sellers received AMM cash when they sold. P3's payment denominator counts actually delivered whale-funded vault money, separately for independent riders and crew. Wash volume creates no rewards or synthetic external revenue.
9. Each scenario holds SOL/USD and APR constant. Yield is realized weekly after the configured validator commission. Principal is neither revenue nor expenditure in operating P&L. A separate ordinary-staking opportunity cost measures the yield a backer gives up. The optional validator contribution comes from a separate external delegation and bears one protocol yield fee; it supplies no bonding credit or DUNG.
10. Dollar P&L includes cash purchases/sales, realized hill pay, sponsor spend, optional riding costs and crew wages. `economic_cash_usd` also subtracts forgone staking yield. `marked_usd` adds all CAL at spot; `liquidation_usd` gives each actor a pro-rata share of **one joint sale** of unlocked CAL through the AMM. Locked capital CAL has zero immediate liquidation value. Neither is a guaranteed exit. The LP's liquidation measure values its remaining CAL at zero. SOL equivalents divide by the scenario price; they are not in-kind SOL balances.
11. No dollar value is assigned to DUNG, titles, advertising, attention or voting rights. Tax, gas, hardware, borrowing, hedging, staking failures, redemption costs and price risk are absent from the default. Riding and crew costs default to zero and receive a separate $1/ascent stress. Thus positive rider cash does not establish profit after real riding costs.
12. “Committed claim value” is an undiscounted, no-dilution upper-bound cash stream over remaining mandatory weeks, divided by currently claiming CAL. Future APR, competing supply, field eligibility and claim ownership can change. It is not a redemption floor, collateral guarantee or price target.
13. The ratified default ladder trigger requires a full elapsed-day trailing average, deeper liquidity, a field and an independent reference; the direct `Ladder.activate()` API also defaults to these checks. Missing reference or field evidence refuses activation. The reference is fixed and synthetic in this model, **not an available production oracle**. Thresholds remain unratified modeling assumptions. Named legacy base-ladder scenarios use only the trailing average and old minimum AMM depth. Falling price cannot unwind activated backing. Unactivated SOL stays escrowed; its retained yield cancels against the ordinary-staking baseline, so it is not separately accrued in the tournament P&L. Escrow-yield ownership is exercised by core unit tests.

## Evidence and limits

The retired P3 promise remains a diagnostic checked at phase boundaries, not transaction by transaction; it is not a ratified invariant. Generated agent properties cover 40 paths at 5 hills, 50 riders and 26 weeks; the full factorial supplies broader counts. Scale cases pair 5 hills/26 weeks and 20 hills/104 weeks, not their Cartesian product.

The tests include hand-computed accounting examples, generated source/field/cap cases, agent paths across fixed seeds, genuine red-to-green regressions, and the original fixed-seed golden result under `legacy_hold_base_ladder`. That snapshot is unchanged; comparison excludes only the two newly added flag keys while checking every original field. The golden is a reviewed regression snapshot, not independent evidence that every assumption is true. Do not regenerate it to silence a failure without explaining the changed outcome.

The reported financial result uses actual AMM execution and funding amounts, not a target price. The tournament need not produce profitable whales. P2's strong wealth reading and P3's universal trading claim have explicit counterexamples that tests require to stay visible. A protocol invariant can hold while token holders lose money.
