# Privacy and your data

## Audience

| Audience | Visible to |
|----------|------------|
| Everyone | Anyone |
| Followers | Riders who follow you ([Feed and following](feed.md)) |
| Only you | You |

New rides default to Everyone. You change the default in Settings (web) or
Privacy (iOS), and can change it per ride.

## Map

Independently of audience, the map other riders see is the full route, the
route with its first and last part hidden (200 m at each end by default; you
can change the distance), or no map. Privacy zones hide any part of a shared
ride inside a circle you define; set them in Privacy (iOS) or Settings (web).

## Sensor data

Only you can see your raw power, heart-rate, cadence, speed, and temperature
streams. The app shows other riders your results and the map you chose, never
samples, CAL, or DUNG. Your CAL, DUNG, and deposits are public on-chain
(below).

## Rides imported from Strava

Rides imported from Strava in the past keep the audience and map setting you
set in Boulder Roller. Strava's own privacy settings were never inherited.

## On-chain data

Boulder Roller writes these to Solana: for each counted ride, a hash of the
file, its start and finish times, training stress, distance, climbing, and
CAL; completions and times on climbs with a vault; leaderboard and Local
Legend changes; deposits and withdrawals; settlements; and DUNG payments. Ride
files and GPS traces are never written on-chain. A ride's audience doesn't
apply on-chain: BoulderScan shows these under your wallet address, and under
your handle if your profile is public.

Training stress is calculated from your Threshold. Anyone who can see a
counted ride's power and duration can combine them with its on-chain training
stress to work out your Threshold. In the app, numbers based on your
Threshold, such as intensity, training load and power zones, are shown only
to you.

The protocol runs on Solana devnet. Records are written there, and a devnet
reset could erase them; restoring them is not guaranteed. Permanent on-chain
records begin at mainnet, which has no scheduled date.

Each counted ride has a transaction behind it; the ride's **Verification**
page links to it on Solana Explorer.
[BoulderScan](https://scan.boulderroller.xyz) decodes the same chain state:
transactions, vault accounts, settlements, deposit positions, and wallet
balances.

## Export and deletion

**Export your data** in Settings (web) downloads your account, ride, and
preference data as a JSON file.

You can request account deletion from Settings (web) or **Delete Account**
(iOS). Requests are completed by support. Your identity and personal data will
be removed. Your climb times, leaderboard history, and settled economics will
remain linked to an anonymous account.
