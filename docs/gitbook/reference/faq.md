# FAQ

## Access

**How is access granted?** By invitation. You enter an invite code when you
create your account; without one, **Request invite** on the web sign-in screen
adds your email address to the waitlist.

**Do I need my own crypto wallet?** No. Email sign-in, and Apple sign-in on
iOS, create one for you. If you signed up with a Solana wallet, you sign in
with it on the web.

**Do I need to understand CAL, DUNG, or vaults to start?** No. Rides and
results work without them, and holding a leaderboard seat needs no CAL.

**Does Boulder Roller connect to Strava?**
No. Upload the ride file to Boulder Roller directly. The same file can be
uploaded to both.

## Rides

**Why did my ride match no climbs?** Most rides do not cross a defined climb
start to finish. Climbs are defined only in and around Philadelphia so far.
Poor GPS also prevents matching; missing elevation keeps a matched climb off
the leaderboard.

**Why did my ride count no CAL?** No power meter, or not enough power data
([CAL](../rides/cal.md#computation)). CAL is also held until your Threshold is
established, which only a ride recorded in the iOS app with a power meter can
do ([Threshold](../rides/cal.md#threshold)). A ride under review, or completed
more than 30 days before upload, counts no CAL.

**Why did a held ride lapse?** Your Threshold was not established within 16
weeks of the ride. Only a ride recorded in the iOS app with a power meter can
establish it ([Held rides](../rides/cal.md#held-rides)).

**Can I add a climb?** Not from a ride. Boulder Roller builds and reviews
climbs. Riding a hill that is not a climb nominates it
([Climbs](../climbs/climbs.md#rules)). When a climb is open for a vault, any
rider can create its vault for 100 DUNG and becomes its founder.

**Why do CAL and training metrics differ?** Training metrics switch to a
scheduled Threshold raise right away and show it as pending; CAL uses the new
value only for rides you start from that Monday
([Training](../rides/training.md)).

## DUNG

**When is DUNG paid?**
Weekly, from Tuesday 12:00 UTC, 24 hours after the settlement boundary
([Settlement weeks](../dung/settlement-weeks.md)).

**Do I have to collect leaderboard DUNG?**
No. Leaderboard and Local Legend DUNG is paid at settlement. Only DUNG earned
by a deposit requires **Collect**.

**What are the fees?** 5% when you collect DUNG earned by a deposit and 0.5%
when you withdraw CAL from a vault. Creating a vault costs 100 DUNG. Nothing
else is charged ([Fees and minimums](../dung/fees.md)).

**Does the founder get a share of settlements?** Only through the first Local
Legend term, which the founder holds from the day the vault is created and
which pays the Local Legend's 3%. After that, founder status carries no
payout.

## Data

**What is public?** In the app, other riders see what each ride's audience
allows, and never your raw sensor streams, CAL, or DUNG. On-chain, each
counted ride's times, training stress, distance, climbing, and CAL are public,
with completions, leaderboards, deposits, settlements, and your wallet's CAL
and DUNG, whatever the ride's audience ([On-chain
data](../rides/privacy.md#on-chain-data)).

**Can I delete my data?** Yes. Request deletion from Settings (web) or
**Delete Account** (iOS); support completes each request ([Export and
deletion](../rides/privacy.md#export-and-deletion)).

**Why Solana?** Boulder Roller writes counted results, deposits, and
settlements to Solana so anyone can check them on BoulderScan. The protocol is
on devnet; mainnet has no scheduled date.

Unanswered questions: [Contact](../support/contact.md).
