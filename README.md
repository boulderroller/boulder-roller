# Boulder Roller

Boulder Roller is a training app and a protocol for riding hills.

Every attested ride earns CAL from its training stress. Each climb with a vault
pays DUNG every week to the riders who hold its records and the people who back
it. It runs in Philadelphia first, on Solana devnet.

## How it works

**Climbs.** Every climb is compiled from OpenStreetMap and public elevation
data into a versioned canon. A ride never defines a climb. It is evidence that
someone rode one.

**Rides.** Riders upload a FIT, GPX or TCX file, or record in the iOS app. The
parser matches each ride to canon climbs and measures every effort. The backend
attests the ride on chain.

**CAL.** One CAL per point of training stress (TSS, as TrainingPeaks defines
it). CAL belongs to the rider and can be transferred. Riders deposit it in a
climb's vault to back the climb.

**Tribute.** Each climb with a vault that a ride crosses is credited the
training stress measured on it. Tribute is counted, not taken: the rider keeps
every CAL.

**DUNG.** Weeks close Monday at 12:00 UTC and pay out on Tuesday. A vault mints
DUNG from the tribute its climb took in that week, at a rate that halves every
26 weeks. It goes 55% to the climb's all-time top ten, 27% to riders with CAL
deposited, 3% to its Local Legend, 10% to the protocol treasury and 5% to
protocol-owned liquidity. Supply is capped at 1 billion.

**Hill backing.** Anyone can back a hill with liquid-staked SOL: JitoSOL, mSOL
or JupSOL. A hill bonds at 10 SOL. Its staking yield, less a 10% fee, pays
riders. So does any USDC a sponsor adds, with no fee. Rider pay splits 65% for
ascents, 25% to the top ten and 10% to the Local Legend. This is stage 1. It is
in the devnet program, on a test stake pool because devnet has none of the
three tokens, and switched off for riders.

## Where it stands

- The portal runs at [boulderroller.xyz](https://boulderroller.xyz). Sign-up is
  by invite.
- CAL, DUNG and the vaults run on Solana devnet. The program has one upgrade
  key and has not been audited. Nothing is on mainnet.
- There is no token launch and no market. DUNG is a record, not money. A market
  would open on evidence, never on a date.
- Philadelphia is the first city, not the only one.
- The iOS app records rides from trusted sensors. It is not in the App Store
  yet.
- Points ended in April 2026. Documents that describe points or a token launch
  are history.
- Card leveling, marketplaces and emission tuning are frozen
  (`docs/FRESHEST_SPEC.md` §13).

## Principles

Pay riders for riding.

Every change answers one question: does it make the hill matter more?

The protocol has to be Lindy. Nothing trades long-run health for a short-run
gain.

## Repository

| Path | What it is |
|---|---|
| `backend/` | Python API (FastAPI) and ride processing |
| `web/portal/` | Rider portal (React, Vite) |
| `ios/` | Native iOS app (SwiftUI) |
| `protocol/anchor/` | Solana program (Anchor) |
| `workout-parse/` | Rust ride parser and climb matching |
| `indexer/` | Streams program accounts into the database |
| `backend/sql/` | Database migrations |
| `docs/` | Specs, protocol truths, RFCs and design records |
| `scripts/`, `tools/` | Operations and utilities |
| `infrastructure/` | Terraform and monitoring |
| `mobile/` | Earlier Expo client, replaced by `ios/` |

## Which document wins

| Document | Covers |
|---|---|
| `docs/PROTOCOL_TRUTHS.md` | What the protocol means. Wins any conflict. |
| `docs/BACKEND_TRUTHS.md` | Backend behaviour |
| `docs/PORTAL_TRUTHS.md` | Portal behaviour |
| `docs/MOBILE_TRUTHS.md` | iOS behaviour |
| `docs/FRESHEST_SPEC.md` | The current product, and what is frozen |
| `AGENTS.md` | How to read this repository, written for agents |

## Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI, PostgreSQL (Supabase), Celery, Redis |
| Portal | React 18, Vite, Tailwind CSS, Radix UI, Recharts |
| iOS | SwiftUI, CoreBluetooth, the Rust parser through UniFFI |
| Parser | Rust, PyO3, fitparser, H3 tiles (h3o) |
| Chain | Solana, Anchor, SPL tokens |
| Sign-in | Privy, Sign In With Solana |
| Maps | Mapbox GL JS, Leaflet |

## Run it

Backend, on Python 3.11. Settings are listed in `.env.example`.

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt ../workout-parse
uvicorn app.main:app --reload
```

Portal, at http://localhost:5173.

```bash
cd web/portal
npm ci
npm run dev
```

Parser tests. PyO3 needs Python 3.12 or older; if yours is newer, set
`PYO3_PYTHON`.

```bash
cd workout-parse
cargo test
```

Program tests.

```bash
cd protocol/anchor
cargo test -p boulder_rollers
```

## Data

Climb geometry comes from OpenStreetMap, used under the ODbL. Surfaces built
from the canon carry its attribution.

## License

Proprietary. Contact the owner.

## This repository

A public copy of the main branch on 5 November 2026, commit `5963e455b` of the
private repository where development happens. One person built it with AI
coding agents: 3,373 commits since 29 October 2025. Planning notes, the issue
tracker, legal and grant files and screenshots of other apps are not included.
`AGENTS.md` lists every difference.
