# What happens to a ride

```text
file -> checks -> climb matching -> results and CAL -> weekly settlement
```

## Checks

Boulder Roller checks the file before producing any result. A ride without
timestamps produces no climb results. A ride without elevation across a climb
still gets a time there but takes no leaderboard place.

## Climb matching

Each climb has a start, a route, and a finish fixed from the road map before
any ride. Your ride produces a result on a climb when it crosses the start,
follows the route, and crosses the finish in that order. The ride supplies
your time and, if it is among the ten fastest on a climb with a vault, your
place. It never changes the climb.

Riding a hill that is not a defined climb nominates it
([Climbs](../climbs/climbs.md#rules)).

## Determinism

A valid file processed under the same rules always produces the same result.
This is the property that allows a result to move a leaderboard or count CAL.

## States

| State | Meaning |
|-------|---------|
| **Counting** (web), **Processing** (iOS) | Processing, or awaiting chain confirmation |
| **Held** | CAL waits for your Threshold ([Held rides](cal.md#held-rides)) |
| **Needs review** (web), **Under review** (iOS) | The ride failed a check that CAL depends on ([Review](#review)) |

A ride that leaves these states is either counted or **Not counted**, with the
reason shown; its numbers are final only then.

## Review

A ride goes under review when it fails a check that CAL and leaderboard places
depend on. The ride and its data are kept, but it counts no CAL and takes no
place. The causes:

- The file Boulder Roller received doesn't match what your phone recorded, or
  it arrived incomplete.
- Power data covered too little of the ride to count CAL, or the effort could
  only be estimated from heart rate or the route.
- The ride was completed more than 30 days before upload, or its clock is
  wrong, such as a finish time in the future.

The ride shows **Needs review** on the web and **Under review** on iOS. Review
does not clear on its own. If you think the ride should have counted, contact
support with the ride date ([Contact](../support/contact.md)).

Counted rides are written to Solana ([On-chain data](privacy.md#on-chain-data)).
