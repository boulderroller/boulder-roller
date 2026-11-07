---
title: Docs
titleTemplate: ':title · Boulder Roller'
---

# About Boulder Roller

Boulder Roller is a cycling app that keeps the record of every hill: who has
ridden it and how fast.

Climbs are currently defined in and around Philadelphia.

A ride comes in as a recording from the iOS app or as a FIT, GPX, or TCX file.
Boulder Roller checks the file and matches it against climbs defined in
advance from the road map and elevation data, each with a fixed start, route,
and finish. For every climb you cross start to finish, the ride produces a
result: your time to the second, your average power when a power meter was
present, and, when the climb has a vault and your best time is among its ten
fastest, your place on its leaderboard. The same file, processed under the
same rules, always produces the same result.

A ride with a power meter also counts CAL, a unit of work computed from the
ride's training stress against your Threshold, once your Threshold is
established ([Threshold](rides/cal.md#threshold)). You can deposit CAL in a
climb's vault. Each week a climb's vault pays DUNG, made from that week's
powered rides on the climb, to its top ten, to riders with CAL deposited (its
backers), and to its Local Legend ([Distribution](dung/distribution.md)).

Access is by invite. The protocol runs on Solana devnet, a test network;
on-chain records become permanent only at mainnet, which has no scheduled
date.

[Get access](getting-started/access.md) ·
[Create an account](getting-started/account.md) ·
[Upload a ride](getting-started/upload.md) ·
[iOS app](getting-started/ios.md)
