# Leaderboards

Each climb with a vault has one leaderboard of ten seats, ordered by each
rider's best time. It starts empty when the vault is created.

## Rules

- You hold at most one seat per climb, at your best time. A slower ride never
  replaces your best time.
- Times are compared to the whole second.
- Tied times share a place and the next place is skipped: two riders tied at
  third are both T-3, and the next rider is fifth.
- You keep your seat until ten other riders have faster best times.
- The fastest time is the KOM. Riders sharing it to the second are co-KOMs.
  Co-KOM adds no seat and no payout.
- A ride under review takes no seat unless it counts. Once a climb's vault is
  open, a time on its leaderboard is not removed.
- A new course version starts a fresh leaderboard ([Climbs](climbs.md)).

## When your time is hidden

- A seat earned on a ride whose audience is Followers or Only you is kept, and
  still paid at settlement, but hidden on the public leaderboard; no one moves
  up into it.
- If your profile is private, your seat shows as **Rider profile private**.

## Leaderboard pool

Seats share the leaderboard pool: 55% of the climb's weekly DUNG, plus any
part of the backers' share not paid that week, by place
([Distribution](../dung/distribution.md)):

| Place | Share |
|------|-------|
| 1 | 30% |
| 2 | 20% |
| 3 | 15% |
| 4 | 10% |
| 5 | 8% |
| 6 | 6% |
| 7 | 5% |
| 8 | 3% |
| 9 | 2% |
| 10 | 1% |

The pool is divided among occupied seats in these proportions: a leaderboard with
three riders divides the whole pool 30 : 20 : 15, which is 46.2%, 30.8%, and
23.1%. Tied riders add up the shares of the places they hold and split the
total equally: two riders tied at third share 15% + 10% and take 12.5% each.
Leaderboard DUNG goes to your wallet at settlement, with no fee and nothing to
collect.
