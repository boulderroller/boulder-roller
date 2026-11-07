# Distribution

DUNG is the token each vault pays weekly to its climb's riders. Each climb's
weekly DUNG is divided as follows.

| Bucket | Share | Recipient |
|--------|-------|-----------|
| Leaderboard pool | 55% | The top ten, by place, plus any unpaid part of the backers' share |
| Backers | 27% | Riders with CAL deposited in the vault |
| Local Legend | 3% | The current Local Legend |
| Protocol | 15% | Treasury (10%) and a reserve held for liquidity (5%) |

## Source

A vault's weekly DUNG is 1 DUNG for every 1,000 CAL of tribute its climb
received that week, multiplied by the emission rate. Tribute comes from rides
([CAL](../rides/cal.md#tribute)). A climb with no powered rides that week
settles nothing.

| Weeks from emission start | Rate |
|---------------------------|------|
| 1–26 | 100% |
| 27–52 | 50% |
| 53–78 | 25% |
| 79–104 | 12.5% |
| … | Halves every 26 weeks, down to a floor of 0.01% |

No transaction or setting can change the schedule; the rate halves on its own.
On devnet the program itself can still be upgraded. If the 400,000,000 DUNG
set aside for riders and backers is reached, weekly emission shrinks, to zero
if needed, and settlements still finalize.

## Leaderboard pool

The pool is paid to occupied seats by place. The shares are listed under
[Leaderboards](../climbs/leaderboards.md#leaderboard-pool).

## Backers

The backers' share is 27% of the week's DUNG. How much of it is paid depends
on how many riders have CAL deposited:

| Backers | Paid |
|---------|------|
| 1 | 1% |
| 2 | 3% |
| 3 | 6% |
| 4 | 11% |
| 5 | 17% |
| 6 | 25% |
| 7 | 35% |
| 8 | 50% |
| 9 | 70% |
| 10 or more | 100% |

The paid part is divided among backers in proportion to CAL deposited. The
rest joins that week's leaderboard pool and does not carry forward.

Example: a week in which a vault settles 1,000 DUNG and has three backers. The
protocol receives 150 (treasury 100, reserve 50) and the Local Legend 30. The
backers' share is 270; with three backers 6% of it is paid, 16.2 DUNG, split
in proportion to CAL deposited. The other 253.8 joins the leaderboard pool,
which pays 550 + 253.8 = 803.8 DUNG by place; with a full leaderboard, first place
receives 30% of it, 241.14 DUNG.

## Local Legend

The Local Legend receives 3%, paid at settlement. When no one holds the seat,
the 3% carries forward to the next Local Legend.
