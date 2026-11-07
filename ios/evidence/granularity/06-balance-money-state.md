# Balance money state — local/offline evidence

**Bead:** `boulderroller-v2-odmi6.6`

**Owner/status:** claude / locally complete, pending exact-commit coordinator review

**Evidence class:** local/offline only

**Input class:** deterministic clocked network, ledger, position, and reward
fixtures; no signed production transaction, rollout mutation, deployment, CAL or
DUNG movement, or physical rider evidence

## Exact mobile render evidence

All three captures are local/offline, simulated evidence from the arm64 iPhone
17 simulator (iOS 26.3). They render the actual post-change `ClimbSheet` and
`SettlementsView`; their normal network tasks are bypassed only by an exact
DEBUG launch argument. The harness, its initializers, and its launch route are
inside `#if DEBUG`, and the Release simulator build contains no
`-BRBalanceRenderFixture` marker.

- `06-balance-climb-rollout-simulated.png`: the real Climb Vault card receives a
  successful-empty position fixture and the deterministic current-stage action
  prefix. `Deposited` and `Your position` render as `—`; Deposit is present;
  Your position is static with no chevron, so Withdraw is not actionable.
- `06-balance-settlements-collect-simulated.png`: the real Settlements card
  receives 12 simulated uncollected DUNG and exposes the existing Collect row.
- `06-balance-settlements-needs-review-simulated.png`: the same real Settlements
  card receives the nonfinal `Needs review` state and replaces the action row
  with that ratified status.

SHA-256, in the order above: `961f9fff2915a295433366ed5fdca6f382287739e8873e58b7d3101ce73ca56b`,
`d605c1694304ac058c149a234595e07ef32b143003fc421f845e2c01bffb767c`, and
`640241b50e90a7dd6bde5ee23fc7d3fabbb69696bf7600abc8de4e3fecf270e2`.

Exact live-read versus fixture boundary: **no live read occurred**. The 12 DUNG,
successful-empty position, climb identity, and `collect_dung` + `deposit_cal`
availability are deterministic fixture inputs matching the current rollout
contract; they were not fetched from production. The sheets, row grammar,
finite-value projection, action gating, and status rendering are the exact
post-change production implementations. No account was created or authenticated,
and no Deposit, Withdraw, or Collect action was executed.

## Externally checkable outcome

Deposit, composed withdrawal, one Collect DUNG action, and Collect all now keep
one client request id from signing through submit reconciliation. A submit
response cannot finalize the sheet. The production-used state machine reads the
owned durable operation and exposes `Pending`, `Delayed`, or `Needs review` until
the ledger says `recorded`; it then performs the action-specific positions or
pending-rewards reread before emitting the literal final result. A recorded
deposit with a missing, failed, or unchanged position stays nonfinal. A recorded
withdrawal with unchanged LP base units stays nonfinal. A recorded collection
does not finish until the vault's pending DUNG rereads as zero.
Post-submit position rereads use the same strict resolver as the Climb sheet, so
an unresolved legacy row or duplicate direct/legacy match cannot be ignored to
manufacture finality.

A known pending operation reaches the bounded timeout as `Delayed`. An ambiguous
submit or session expiry after signing looks up the same client request id;
absent or unavailable reconciliation is `Needs review`, never a fresh request or
success. A held-action task cancelled during its reconciliation sleep performs
one status read, stops at the next loop boundary, and becomes nonfinal
`Needs review` rather than spinning until wall timeout. Collect all proves every
position identity and pending-rewards source
before its first write. If one collection finalizes and a later prepare or
ambiguous submit fails, the aggregate becomes `Needs review`, never failed,
delayed, or done. Withdrawal sends only the deployed composed withdraw action;
the client emits no separate pre-harvest.

The authenticated read-only backend boundary supports both operation-id and
stable client-request/reference/action lookup. Ownership is applied inside each
query: the same rider receives the operation, while another rider receives 404.
The JSON response has exactly the twelve rider fields and excludes transaction
signature, fee payer, delegate/policy id, idempotency key, raw failure reason,
metadata, and every other support-only field. No schema or migration changed.

Balance controls derive only from `/status.balance_rollout`. They fail closed
when status is unavailable, enforcement is false, order is invalid, blockers
exist, or enabled actions are not the ordered prefix. The deterministic
current-stage fixture exposes Collect DUNG and Deposit CAL and does not expose
Withdraw.
Failed positions, directory, or pending-rewards reads render the settlement
aggregate as a dash and do not light the avatar dot. Climb position truth resets
before reload and resolves every legacy row: only a successful empty set proves
an exact prior zero; an unrelated legacy resolution failure, a duplicate
direct/legacy match, or an existing row without exact base units leaves Deposit
unavailable. Missing deposited CAL and position CAL render `—`, not `0`.
Malformed, NaN, and infinite money strings also render `—` with non-numeral row
semantics rather than reaching the formatter's legacy zero fallback.

## Red to green

- Retained iOS behavioral red: against the pre-change production state machine,
  13 focused tests produced 24 failures. Any 2xx submit finalized immediately,
  projection lag and pending timeouts became done, finality performed no
  action-specific reread, ambiguous/session-expired submits did not reconcile
  by the original request id, collect-all failed open, and legacy identity
  failure became success.
- Retained partial-success red: after the main reconciliation correction, the
  fixture with one finalized collect followed by a prepare failure still
  returned generic failure; the focused run reported that single behavioral
  failure before the aggregate was corrected to `Needs review`.
- Backend red: the initial rider-route run reported two behavioral 404 failures
  for the same rider because operation-id and stable-request reads were not
  exposed.
- Render-harness red: the exact DEBUG launch-boundary test initially failed
  three assertions because each requested fixture mode resolved to nil. The
  implemented parser now admits only the three exact modes and rejects missing
  or unknown modes; the same test also binds Collect + Deposit enabled and
  Withdraw disabled for the captured current-stage fixture.
- Green: all 29 `BalanceMoneyTruthTests` pass on the booted arm64 iPhone 17
  simulator, including the four vault-position baseline cases, strict
  post-submit identity reconciliation, finite money-display projection, and
  bounded cancelled-task reconciliation. The full item 1–6 iOS truth suite
  passes 59/59. The Debug render build and Release exclusion build both
  succeed. Fourteen backend
  route/read-model tests pass,
  including same-rider reads, other-rider 404s through both lookup shapes, and
  exact support-field exclusion.

Commands:

```text
xcodegen generate --spec ios/project.yml

xcodebuild build -project ios/BoulderRoller.xcodeproj -scheme BoulderRoller \
  -configuration Debug \
  -destination platform=iOS\ Simulator,id=83285814-8448-43E4-9AB5-630A48FFF29C \
  CODE_SIGNING_ALLOWED=NO

xcrun simctl launch --terminate-running-process \
  83285814-8448-43E4-9AB5-630A48FFF29C com.boulderroller.app \
  -BRBalanceRenderFixture <climb-rollout|settlements-collect|settlements-needs-review>

xcrun simctl io 83285814-8448-43E4-9AB5-630A48FFF29C screenshot \
  ios/evidence/granularity/<capture-name>.png

xcodebuild test -project ios/BoulderRoller.xcodeproj -scheme BoulderRoller \
  -destination platform=iOS\ Simulator,id=83285814-8448-43E4-9AB5-630A48FFF29C \
  -only-testing:BoulderRollerTests/BalanceMoneyTruthTests

xcodebuild test -project ios/BoulderRoller.xcodeproj -scheme BoulderRoller \
  -destination platform=iOS\ Simulator,id=83285814-8448-43E4-9AB5-630A48FFF29C

python3 -m pytest -q \
  backend/tests/routes/test_balance_operation_status_route.py \
  backend/tests/services/test_balance_operation_status.py

xcodebuild build -project ios/BoulderRoller.xcodeproj -scheme BoulderRoller \
  -configuration Release \
  -destination platform=iOS\ Simulator,id=83285814-8448-43E4-9AB5-630A48FFF29C \
  CODE_SIGNING_ALLOWED=NO
```

## Remaining boundary

This proves local/offline code behavior only. The Balance rollout stage,
cohort, enforcement, action order, custody, fees, idempotency policy, provider
policy, and production environment are unchanged. Withdraw remains disabled.
Nothing was deployed, pushed, merged, signed against production, or exercised
as a physical rider/world-state action. Item 7 remains open, unassigned, and
untouched pending exact-commit coordinator acceptance of item 6.
