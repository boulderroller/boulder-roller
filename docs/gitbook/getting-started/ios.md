# iOS app

The iOS app records rides from your phone and Bluetooth sensors and imports
ride files. It shows the feed, climbs, and leaderboards, and lets you deposit
CAL, collect DUNG, and set ride privacy. You follow and unfollow riders on the web
([Feed and following](../rides/feed.md)).

## Install

The iOS app is available through TestFlight, by invitation, on iPhone with iOS
26 or later. Install from the TestFlight invitation, then sign in with Apple
or email. If you are creating your account, enter your invite code on the
first screen.

## Record a ride

1. Tap **Record** on the feed and allow location access. Recording continues
   with the screen off and in the background.
2. The recording screen shows time, distance, speed, and climbing, and with
   sensors connected, power, heart rate, and cadence. Stops auto-pause;
   **Pause** and **Resume** are manual.
3. Tap **End**. **Save Ride** opens; add a title, notes, and photos, choose
   who can see the ride and how much of the map shows, and tap **Save** to
   upload it. **Later** keeps the ride on your phone until you tap **Review**
   on its feed card.

A ride shorter than 100 m, or with fewer than 30 GPS samples, stays on your
phone and is not uploaded. Its card reads **Saved on this device** with no
**Review** button, and its page offers **Export Ride File** (GPX). If the app
closes mid-ride, the next launch shows **Unfinished Ride Found**, where you
save or discard it.

## Sensors

Pair Bluetooth sensors under Profile → **Sensors**. Paired sensors
reconnect automatically when you start recording.

| Sensor | Bluetooth profile |
|--------|-------------------|
| Heart rate | Heart Rate |
| Power meter | Cycling Power, with zero-offset calibration |
| Speed and cadence | Cycling Speed and Cadence; the app reads cadence only, and speed comes from GPS |

A ride recorded here with one power meter paired is the only kind of ride that
can establish or raise your Threshold, and it counts CAL once your Threshold
is established ([Threshold](../rides/cal.md#threshold)). A ride from GPS alone
gets climb times only.

## Import a file

FIT, GPX, and TCX files import from the Files app. The file is checked on your
phone and **Save Ride** opens, as after a recording; after **Save** it is
uploaded and processed like a web upload. An imported file never sets your
Threshold.

## Screens

| Screen | Contents |
|--------|----------|
| Feed | Recent rides |
| Ride | Map, climbs, results, photos, **Share Card**, **Export Original File** (the file as uploaded) |
| Climbs | Map of climbs; a climb with a vault also shows its leaderboard and vault |
| Deposit, Withdraw | Hold to confirm. Withdraw is not open yet; see [Vaults](../climbs/vaults.md) |
| Settlements | Weekly DUNG, week by week, each with its detail; **Collect** for DUNG earned by deposits |
| Wallet | Address, **Copy Address**, **View on Solana Explorer** |
| Privacy | Default audience for new rides; privacy zones |
| Profile | Name, photo, weight, Threshold |

You create vaults on the web ([Create a
vault](../climbs/vaults.md#create-a-vault)).
