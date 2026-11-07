# Review day — one session, in order

Operational steps only. Build/run mechanics live in [README.md](README.md).

## 1. Run it
Open the project per the README (XcodeGen → Xcode 26 → iOS 26 simulator, or a
physical iPhone for steps 5–6). The parser framework stages via
`scripts/build_parser.sh` if not already built.

## 2. First login
Sign in with your email. The one-time code to your real inbox is the last
untested auth path in the app — your login completes it. (Sign in with Apple
also works; DEBUG builds additionally offer the dev wallet path.)

## 3. Look around
Feed, ride sheet, climb sheet, avatar sheet, settlements, map viewer — all
reading production. Everything you tap should work; anything that doesn't is
a bug, not a known gap.

## 4. The deposit — this is also the protocol rollout
Your live deposit is the Balance runbook's stage-3 verification ("verify one
internal rider can deposit"). Open a climb → Deposit → hold. Confirm the
position appears (or shows a truthful Delayed).
Then tell Claude: the stage advances to `withdraw_cal` and you verify the
withdraw the same way — CAL returns, position updates. That completes stage 4.

## 5. Sensors on a real phone
Pair your actual HR strap / power meter in Sensors. This is the one test the
simulator physically cannot run (no Bluetooth). Expected: stock-Settings
choreography, devices persist and auto-reconnect.

## 6. Ride
Record a real ride on a real hill with power. This is the first legitimately
fresh, in-window, power-bearing ride in the app — the gold reveal plays for
real for the first time. Nobody has seen it with real earnings yet, on
purpose.

## 7. Evidence map
Everything claimed above is evidenced under [evidence/](evidence/) — screenshots
per surface, two recording-lane videos (labeled simulated GPS), Dynamic Type
captures, and the integrity-check documentation in the evidence README.

Known physical-world gaps going in: BLE untested on hardware until step 5;
leaderboard/PR surfaces populate as real completions land; per-climb CAL /
avg HR / PR chips activate with the ride-contract backend deploy.
