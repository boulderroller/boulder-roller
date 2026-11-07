# Vaults

A vault is the account attached to a climb. CAL is deposited in it and DUNG is
settled from it every week ([Settlement weeks](../dung/settlement-weeks.md)).

## Create a vault

A climb that is open for a vault shows **Create Vault** on its web page; one
that is not shows **No vault**. The climb's name and route come from the
climb.

| Method | Cost |
|--------|------|
| DUNG | 100 DUNG from your wallet, burned |
| CAL and USDC | 1,000 CAL, burned, and 2 devnet test USDC; not open yet |

Creating the vault makes you the climb's founder. Founder status stays with
the climb: you hold the first Local Legend term, shown as **Founder
stewardship**, starting when the vault is created. It confers no leaderboard
seat, KOM, or payout beyond that first term.

## Deposit CAL

Riders with CAL deposited are the climb's backers and share up to 27% of its
weekly DUNG; how much is paid grows with the number of backers, from 1% of
that share for one backer to all of it for ten or more
([Distribution](../dung/distribution.md#backers)).

Open the climb, choose **Deposit CAL** (**Deposit** on iOS), enter a whole
number of CAL from your wallet, and hold to confirm.

| Parameter | Value |
|-----------|-------|
| Minimum deposit | 100 CAL |
| Effective from | The next settlement boundary (Monday 12:00 UTC) |
| Fee | None |

A deposit made mid-week earns nothing for the week in progress and joins the
following week. Deposits have no effect on results, places, or Local Legend.

## Withdraw CAL

Withdrawals are not open yet. When they open, **Withdraw CAL** on your
position (tap your position on iOS) returns CAL to your wallet right away,
less a 0.5% exit fee; on the web it withdraws the whole position. The position
keeps its share of the week in progress. Any **DUNG ready** is collected
first, less the 5% collection fee.

## Collect DUNG

DUNG earned by a deposit is credited to the position at each settlement and
shows as **DUNG ready**. **Collect DUNG** (**Collect** on iOS) sends it to
your wallet less a 5% fee. Leaderboard and Local Legend DUNG goes to
your wallet at settlement, with no fee and nothing to collect.

## States

Deposits, withdrawals, and collections show **Pending** while confirming,
**Delayed** when confirmation is slow, and **Needs review** when Boulder
Roller could not confirm the operation. No funds are lost in any of these
states: an operation that did not go through moved nothing. If **Needs
review** does not clear, contact support ([Contact](../support/contact.md)).
