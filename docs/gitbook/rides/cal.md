# CAL

CAL is counted from a ride's training stress against your Threshold: each
point of training stress counts 1 CAL, and an hour at exactly your Threshold
is 100.

```text
Ride CAL 82
CAL tribute · Manayunk Wall 11.8 CAL · Lyceum Avenue 5.6 CAL
```

## Computation

- Power data is required: at least 30 power samples covering at least 50% of
  the ride, and 30 seconds of moving time under power.
- CAL uses the Threshold in effect when you started the ride. A raise applies
  to rides you start from the Monday it takes effect.
- Coasting at zero watts counts. Gaps longer than 30 seconds in the recording,
  such as an auto-pause, don't count; a stop recorded without pausing counts
  as zero watts.

## Threshold

Your Threshold is the power reference that training stress and CAL are
measured against. You can't type it in.

Only a ride recorded in the Boulder Roller iOS app with one power meter paired
can establish or raise it. Boulder Roller reads your best 3-, 7-, and
15-minute power from those rides. Uploaded files never set it, even with
power.

A new or raised Threshold takes effect at the next Monday 12:00 UTC. It only
rises. Until it is established, CAL is held.

## Held rides

Until your Threshold is established, CAL is held, and so are the ride's
leaderboard place and its Local Legend completion.

When your Threshold is established, Boulder Roller recalculates each held ride
once against it and counts it in the current settlement week, not the week you
rode.

Each held ride carries a 16-week window, counted from the day the ride was
confirmed on Solana, normally the day you upload it. If your Threshold takes
effect inside that window, the ride is released and counted. If it does not,
the ride lapses: it is never counted and cannot be reopened. Only a ride
recorded in the iOS app with one power meter paired establishes your
Threshold, so held rides are released by recording one, not by waiting
([Threshold](#threshold)).

## Destination

CAL counted from a ride is credited to your wallet. From the wallet you can
deposit it in a climb's vault ([Vaults](../climbs/vaults.md), [Balance and
wallet](../dung/balance.md)).

## Tribute

When you complete a climb that has a vault, the vault receives tribute: the
training stress you produced on that climb, measured from your power and time
on the climb against your Threshold. Each climb is measured on its own.

- Tribute is counted separately: none of it is taken from your CAL, and it
  never becomes CAL.
- Across all climbs in one ride, tribute never exceeds the ride's CAL.
- A climb with missing or insufficient power data produces no tribute. Nothing
  is estimated from gradient.
- If you ride a climb more than once in one ride, only your fastest qualifying
  pass counts.
- Rides processed under the earlier rule, a fixed 10% of ride CAL split across
  the climbs crossed, keep that rule.

Holding or depositing CAL never changes your place, KOM (King of the
Mountain), or Local Legend count.
