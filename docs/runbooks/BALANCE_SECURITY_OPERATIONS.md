# Boulder Roller Balance Security Operations

**Status:** Active rollout gate  
**Bead:** `boulderroller-v2-5y48`  
**Scope:** Sponsored Boulder Roller Balance execution, fee payer operations,
signer/provider custody, rate limits, support visibility, and production
stop/go rules.

This runbook does not replace the canonical secret work:

| Bead | Role |
|---|---|
| `boulderroller-v2-2f9w` | Rotate, scrub, and inventory exposed secrets |
| `boulderroller-v2-ttkx` | Cut protocol authority secrets over to managed secret workflows |

Production Balance rollout remains closed while either blocker is still required
for the environment being enabled.

Current protocol key roles and local devnet file names are documented in
`docs/security/KEY_MAP.md`. In particular, the Balance fee payer must point to
`boulderroller-fee-payer.json` or an equivalent managed secret with no protocol
authority.

## Release Gate

Run `evaluate_balance_rollout_readiness` before enabling production Balance
execution for any cohort or action. The gate blocks rollout unless all of the
following are true:

| Area | Production requirement |
|---|---|
| Fee payer | Production fee payer pubkey is recorded, funded above minimum runway, and alert threshold is above the minimum. |
| Alerting | Low-balance alert has been exercised in staging or a dry-run production channel. |
| Secret owners | Signer secret owner and provider secret owner are named. |
| Managed secrets | Production signer/provider secrets use the managed secret workflow, or rollout is explicitly blocked by `boulderroller-v2-ttkx`. |
| Secret rotation | No required exposed-secret rotation blocker remains open under `boulderroller-v2-2f9w`. |
| Abuse controls | Replay/idempotency, destination spoofing, treasury spoofing, stale policy/delegate, revocation, rate-limit, and support/admin leakage evidence is attached. |

The executable contract lives in:

```text
backend/app/services/balance_rollout_readiness.py
backend/tests/services/test_balance_rollout_readiness.py
```

## Fee Payer And Rate-Limit Exercise

The Balance fee payer pays network fees only. It is not token authority and must
not be able to move rider value by itself.

For each rollout environment, record:

| Field | Source |
|---|---|
| Fee payer pubkey | Managed secret metadata or deployment secret description |
| Current SOL balance | Solana RPC balance check for the fee payer pubkey |
| Minimum runway | Launch owner decision, defaulting to `2_000_000_000` lamports |
| Alert threshold | Monitoring threshold, defaulting to `5_000_000_000` lamports |
| Alert exercise evidence | Staging alert event, dry-run page, or incident drill link |

Exercise the low-balance alert before production enablement. A valid exercise is
one of:

| Method | Expected evidence |
|---|---|
| Staging threshold drill | Temporarily set staging threshold above current staging balance and confirm alert delivery. |
| Dry-run production alert | Emit the production alert path with `dry_run=true` and record the delivered event. |
| Incident drill | Record the alert page, owner acknowledgement, and refill procedure in the incident log. |

Rate-limit evidence must show that repeated sponsored attempts cannot drain the
fee payer without operation dedupe or throttling. Acceptable evidence is either
a focused automated test or a runbook drill that records:

| Requirement | Evidence |
|---|---|
| Per-rider throttling | Repeated Balance action attempts by one rider hit the configured limit. |
| Idempotency | Repeated attempts with the same idempotency key reuse the operation instead of creating divergent work. |
| Fee budget alert | Attempt volume that would cross the fee budget produces an alert before production funds are exhausted. |
| Support outcome | Rider-visible state remains `Pending`, `Delayed`, or `Needs review`; primary UI does not expose fee payer language. |

The backend enforces daily Balance budgets in
`BalanceTransactionCoordinator` before transaction submission. Defaults are:

| Env var | Default | Scope |
|---|---:|---|
| `BALANCE_ACTION_BUDGETS_ENABLED` | `true` | Master switch for Balance action budgets. |
| `BALANCE_RIDER_DAILY_COLLECT_DUNG_BUDGET` | `12` | Per-rider daily Collect DUNG attempts. |
| `BALANCE_RIDER_DAILY_DEPOSIT_CAL_BUDGET` | `8` | Per-rider daily Deposit CAL attempts. |
| `BALANCE_RIDER_DAILY_WITHDRAW_CAL_BUDGET` | `8` | Per-rider daily Withdraw CAL attempts. |
| `BALANCE_RIDER_DAILY_CREATE_VAULT_BUDGET` | `3` | Per-rider daily Create Vault attempts. |
| `BALANCE_RIDER_DAILY_PAY_USDC_BUDGET` | `8` | Per-rider daily Pay USDC attempts. |
| `BALANCE_RIDER_DAILY_ACTION_BUDGET` | unset | Optional shared default for all per-action rider budgets. |
| `BALANCE_GLOBAL_DAILY_ACTION_BUDGET` | `500` | Global daily circuit breaker across Balance actions. |

When a budget is exhausted, the API returns HTTP 429 with calm rider copy such
as `Today's Collect DUNG limit is reached. Try again tomorrow.` and a
`Retry-After` header ending at the next UTC day boundary.

## Secret Custody

Signer/provider secret ownership must be boring and explicit:

| Secret family | Owner | Production rule |
|---|---|---|
| Balance fee payer | Platform/security owner | Stored in managed deployment secrets, rotated through incident workflow. |
| Privy authorization key or provider signer secret | Platform/security owner | Stored in managed deployment secrets; no local file is the source of truth. |
| SPL delegate authority metadata | Platform/security owner | Revocable and scoped by rider token account, mint, amount, and expiry. |
| Backend authority | Protocol/security owner | Existing ProgramConfig authority rules stay in force. |

If any of these still rely on local env files, copied dashboard values, or
unrotated exposed material, leave production rollout blocked and reference
`boulderroller-v2-2f9w` or `boulderroller-v2-ttkx` instead of opening a duplicate
secret-tracking lane.

## Required Security Evidence

Attach one artifact for every control in `REQUIRED_BALANCE_ROLLOUT_CONTROLS`:

| Control | Preferred artifact |
|---|---|
| `replay_idempotency` | `backend/tests/services/test_balance_transaction_coordinator.py::test_operation_id_is_stable_for_same_intent` plus route replay tests when enabling a route. |
| `destination_spoofing` | `backend/tests/services/test_balance_privy_policy_prototype.py::test_wrong_destination_is_rejected` and Anchor destination constraints for the action. |
| `treasury_spoofing` | Anchor ProgramConfig treasury tests, or `test_wrong_account_role_is_rejected_by_fixture` for policy-signed fixtures. |
| `stale_policy_delegate` | `test_stale_policy_or_delegate_id_is_rejected_before_submission`. |
| `revocation` | `backend/tests/services/test_balance_lifecycle.py::test_locked_recovering_and_revoked_disable_no_prompt_execution`. |
| `rate_limit` | `backend/tests/services/test_balance_transaction_coordinator.py::test_per_rider_daily_budget_blocks_action_before_insert` and `test_global_daily_budget_blocks_before_insert`. |
| `support_admin_leakage` | `backend/tests/services/test_balance_operation_status.py::test_rider_status_omits_support_only_operation_fields`. |

## Stop Conditions

Stop production rollout immediately when any of these occur:

| Condition | Action |
|---|---|
| Fee payer below minimum runway | Pause sponsored Balance execution and refill or rotate the fee payer. |
| Fee payer alert does not fire | Keep rollout closed until monitoring is repaired and exercised. |
| Required secret rotation remains open | Keep rollout closed and continue under `boulderroller-v2-2f9w`. |
| Managed secret workflow is not ready | Keep rollout closed or explicitly block on `boulderroller-v2-ttkx`. |
| Revoked or recovering account can still execute no-prompt Balance action | Disable the affected adapter and move impacted operations to `Needs review`. |
| Destination, treasury, mint, or amount spoofing succeeds | Disable the affected adapter and treat it as a security incident. |
| Rate limit or idempotency fails | Disable sponsored execution for the affected action and preserve existing operation records. |
| Rider status exposes support-only details | Remove the field from rider responses before enabling the action. |

## Rollout Record

For each action cohort, record the readiness decision with:

```text
action:
cohort:
fee_payer_pubkey:
fee_payer_balance_lamports:
fee_payer_alert_evidence:
signer_secret_owner:
provider_secret_owner:
managed_secret_status:
open_secret_blocker_beads:
control_artifacts:
decision:
owner:
timestamp:
```

Keep raw transaction signatures, provider policy ids, fee payer internals, and
debug material in support/admin/BoulderScan records. Primary rider surfaces
should stay Balance-first and use `Pending`, `Delayed`, and `Needs review`.
