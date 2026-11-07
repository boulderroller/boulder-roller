# Stage 1 integer reference model

Offline milestone 0 oracle for Bead `boulderroller-v2-6c6sv`, using policies
ratified by Tim, 13 Oct 2026.
The [spec](../../history/launch-readiness-2026-10-08/STAGE1_SPEC.md) defines the
exact semantics and remaining production gates. This package makes no network
calls and does not exercise real providers, on-chain custody or verified riders.

From the repository root, use the requested Python 3.12 runtime:

```sh
/opt/homebrew/bin/python3.12 -m venv /private/tmp/stage1-m0-venv
/private/tmp/stage1-m0-venv/bin/python -m pip install -r tools/stage1_reference/requirements.txt
/private/tmp/stage1-m0-venv/bin/python -m pytest tools/stage1_reference/tests -q
/private/tmp/stage1-m0-venv/bin/python -m tools.stage1_reference
```

The CLI runs pledge → bond → realized harvest → funded weekly roots → claim,
alongside USDC sponsorship and an escrowed boost. Its JSON output is labelled
offline. Amounts are base units, never human-readable token decimals.

- `config.py` loads exact decimal/rational values from `diamond.yaml`. Every
  `stage1` section requires `status: ratified`; missing or unknown status and
  unsupported semantic modes reject rather than silently using a default.
- `model.py` implements atomic owner/custody actions, frozen weeks, allocation,
  holds, DUNG mint data and claims. Claims use per-set index bitmaps. Duplicate-person leaves are publisher
  allocation errors; distinct indices remain payable within the committed total.
  Cash and DUNG batches roll back all entries on any failure. Claim/DUNG vectors
  include the resulting bitmap bytes, while proof formats remain unchanged.
  `check()` checks income, custody and total
  asset-unit and held-basis conservation after every successful mutation. Run without `-O` so
  invariant assertions remain enabled. Read-only inspection of state is useful;
  directly editing it bypasses the modeled contract.
- `arithmetic.py` implements exact apportionment and bounded redistribution.
- `merkle.py` supplies versioned context-bound SHA-256 sum roots and proofs.
- `tests/` includes adversarial ownership/rounding examples and six deterministic
  800-action fuzz sequences across three asset ledgers. Hypothesis was not
  available in the requested environment, so the brief's seeded-fuzzer fallback
  is used. A further 120 randomized partial-exit cases target principal leakage.

Rate inputs mean lamports per token base unit, not SOL per whole token. At nine
decimals `Fraction(6, 5)` means a 1.2-SOL token; at twelve decimals that same
whole-token redemption value is `Fraction(3, 2500)`. USDC is six decimals.
Caps use maintained deposit-basis totals. Rate declines and appreciation do not
change those totals. `observe_rate` can take trusted `observed_at` and
`fresh_until` inputs. Rejected observations preserve the admitted rate and
expiry; backing becomes stale only when that window ends. Scenarios without
an explicit window use `mark_rate_stale` as a trusted adapter-expiry input,
never as observation rejection. It cannot shorten an explicit window. A fresh
`observe_rate` resets the seven-day escape clock. After lock and full notice,
continuous staleness permits an in-kind return without harvesting. These
transitions model admission state; they do not prove a real provider rate.

Stale campaign tokens contribute zero toward bonding. Only fresh slots found;
excluded lots remain cancellable and have no active backing or weight. Once
their rate is fresh, `convert` lets the owner choose an ordinary lock, preserving
basis and segregating pre-bond surplus at that rate. Recovery alone cannot
activate or harvest an excluded lot. Existing active weekly valuation still
uses the most recent admitted rate, as specified in the governing spec.

Each model is a one-city deployment experiment. Global fee/cap state must be
shared before extending this oracle to a multi-city deployment.

Founding backers receive 2× weight for their hill's first 26 full bonded weeks,
independent of city season boundaries. Boosts fund riding weeks only. Qualifying
late uploads share their ride week's escrow before its fixed close-plus-24-hour
cutoff, with no funded tail or reopened claim root. Ordinary upload-week cash,
board/field snapshots and DUNG remain unchanged. Unspent escrow retains the
existing 26-week pool-only fallback.

No amendment to product TRUTHS, production adapter admission, deployment,
provider integration, actual DUNG issuance or shared-pool distribution is
included. Ratified policy and offline evidence do not establish those outcomes.

Milestone 1b adds `providers.py`: read-only decoding of retained mainnet provider
account bytes, epoch-scoped admission and authenticated outage bookkeeping.
`python -m tools.stage1_reference.provider_vectors --check` verifies the three
snapshot ratios and six simulated admission vectors shared with local validator
tests. Sources, identities, cadence interpretations and evidence limits are in
STAGE1_SPEC §3.1. Provider snapshots prove parsing; they are not live epoch
rehearsal or provider execution. The original `Model` remains the money oracle;
provider tests feed its admitted ratios into the existing bonding transitions.

Milestone 2a adds `claim_vectors.py`: twelve allocation/hold/claim traces and six
median boundaries consumed by Rust and local-validator tests. Regenerate with
`python -m tools.stage1_reference.claim_vectors`; `--check` verifies retained
vectors. The validator passes only namespaces and public recipient identities
to `--stdin`; `Model` independently computes allocations, caps, holds and proofs.
`--merkle-stdin` is explicitly synthetic malformed/deep-tree evidence, not a
riding allocation. Set `STAGE1_ORACLE_PYTHON` to the reference virtualenv's Python
when running `scripts/build-stage1-localnet.py --test` from `protocol/anchor`.

Milestone 2a.1 adds `Model.skip_empty(hill, through)` for 1..16 finalized weeks
starting at admission/current progress. It creates no settlement objects and
refuses gross harvest weeks (including all-fee harvests) and DUNG obligations.
Round 2 permits quiet held-money spans strictly before original week + 26 and
the next boost tranche due week, without changing any ledger or tranche.
This whole-hill oracle check covers every asset; the program's cursor is per
hill/mint. Claim vectors record skipped weeks and refused maturity skips;
pool and earlier unclaimed leaves remain obligations after a successful skip.

Boost IDs are funder-scoped. Starts are 1..13 weeks after the current city week,
and every Hamilton hill-week share must be at least 1 USDC (1,000,000 base units):
Claude's default, revisable by Tim. Sponsor vectors include quiet skips through
due-minus-one and maturity-minus-one, followed by exact original-age expiry.

Milestone 2c adds `dung_vectors.py`: twenty-one independent opening/issuance traces
cover the founder bonus boundary, lock expiry, per-lot loss rounding, field,
missing Legend, zero TSS/weight, partial/boundary bonding, late pre-bond rides,
just-under/exact default TSS ceiling, and unregistered rider/backer/all shares.
Registration filters shares after apportionment: missing recipients leave DUNG
unminted without increasing anyone else's allocation. The publisher supplies
the resulting payable totals, each bounded separately by the program.
`python -m tools.stage1_reference.dung_vectors` regenerates the retained fixture.
`Model.dung_claim_sets` uses `<mint>:riders` and `<mint>:backers` as separate §8
asset namespaces. `claim_dung` tracks separate issuance and replay state without
touching cash balances. Local validator tests consume those oracle roots and
actually mint test DUNG; synthetic riding inputs are not physical rider proof.

Round 2 keeps allocation previews separate from publication. `configure_dung`
requires the modeled admin and a prospective start week; the default is unset
with a 20,000-TSS ceiling. `publish_dung` admits the ordered hill/week record,
and `publish_dung_claim_set` starts each role's own 172,800-second wait. Later
cap/start changes leave existing entitlements intact. The oracle trusts the
admin identity; it does not simulate the future external multisig's seven-day
delay. Cash settlement is independent of these issuance controls.
