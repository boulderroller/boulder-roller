# Glossary

**Backer.** A rider with CAL deposited in a climb's vault. Backers share up to
27% of each weekly settlement, depending on how many there are
([Distribution](../dung/distribution.md#backers)).

**Balance.** The Boulder Roller Balance: CAL, USDC, and DUNG moved in from the
wallet. Not open yet.

**Best.** A rider's fastest time on a climb across their own history.

**BoulderScan.** The protocol explorer at
[scan.boulderroller.xyz](https://scan.boulderroller.xyz).

**CAL.** A unit of work counted from a ride's training stress against the
rider's Threshold. Requires power data. Depositable in vaults.

**CAL tribute.** The training stress measured on a climb, credited to that
climb's vault as a meter. Not deducted from the rider's CAL and not minted as
CAL.

**Climb.** A named hill with a fixed start, route, and finish.

**co-KOM.** A rider sharing the KOM time to the second.

**Completion.** One ride's start-to-finish pass over a climb that has a vault.
Local Legend is decided by completions.

**Devnet.** Solana's test network, where the protocol runs today. Records
there are not permanent.

**DUNG.** The token settled weekly from each vault to its leaderboard, backers,
and Local Legend.

**Established.** The state of a Threshold once its first value has taken
effect. Later changes are raises.

**Establishing.** The state before a rider's first Threshold takes effect.
CAL is held meanwhile.

**Follower.** A rider who follows you. Followers see your rides whose
audience is Followers or Everyone ([Feed and following](../rides/feed.md)).

**Founder.** The rider who created a climb's vault.

**Held.** CAL waiting for the rider's Threshold to be established; the ride's
leaderboard place and Local Legend completion wait with it. Released and
counted once the Threshold takes effect, if that happens within 16 weeks of
the ride's confirmation.

**KOM.** King of the Mountain: the fastest time on a climb.

**Lapsed.** A held ride whose 16-week window closed before the Threshold took
effect. Never counted, never reopened.

**Leaderboard.** The top ten by best time on a climb with a vault, from when
the vault was created. Ties share a place.

**Leaderboard pool.** The share of each weekly settlement paid to the top ten
by place: 55%, plus any unpaid part of the backers' share
([Leaderboards](../climbs/leaderboards.md#leaderboard-pool)).

**Local Legend.** The rider holding a climb's current eight-week term, decided
by most completions in the term before it. The founder holds the first term.

**Needs review.** A deposit, withdrawal, or collection Boulder Roller could
not confirm, or a ride that failed a check CAL depends on (iOS shows **Under
review**). No funds are lost in this state.

**Pending.** A value or operation that is known but not final.

**Place.** The position of a rider's best time on a climb's leaderboard.

**Result.** One rider's time, power, and place on one climb in one ride.

**Settlement week.** Monday 12:00 UTC to Monday 12:00 UTC
([Settlement weeks](../dung/settlement-weeks.md)).

**Threshold.** The rider's power reference, derived from rides recorded in the
iOS app with one power meter paired, and never entered by hand. Training
stress and CAL are measured against it. It only rises, and raises take effect
at Monday 12:00 UTC.

**Top 10.** A rider's best time holds one of a climb's ten leaderboard seats.

**Training stress.** How long and how hard a rider rode relative to their
Threshold. An hour at Threshold is 100; each point counts 1 CAL.

**USDC.** A dollar stablecoin. The USDC used on devnet is a test token with no
value.

**Vault.** The account attached to a climb where CAL is deposited and DUNG is
settled.

**Wallet.** The rider's Solana address. Holds CAL counted from rides and DUNG
paid at settlement or collected, and pays for deposits and vault creation.
