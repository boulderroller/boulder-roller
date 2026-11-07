# Boulder Roller Balance Production Rollout

This runbook stages Boulder Roller Balance into production without flipping
every economic action at once. The rollout stays rider-first: primary surfaces
say `Collect DUNG`, `Deposit CAL`, `Withdraw CAL`, `Add funds`, `Pay with USDC`,
`Pending`, `Delayed`, and `Needs review`; technical detail stays in support,
admin, and BoulderScan surfaces.

## Controls

Production gates are exposed through `GET /status` under `balance_rollout`.
Public environments enforce the gates by default.

Environment controls:

| Variable | Value |
| --- | --- |
| `BALANCE_ROLLOUT_STAGE` | `off`, `collect_dung`, `deposit_cal`, `withdraw_cal`, `create_vault_usdc`, or `all` |
| `BALANCE_ROLLOUT_COHORT` | `internal`, `dogfood`, `beta`, or `all` |
| `BALANCE_ROLLOUT_OWNER` | person accountable for the active stage |
| `BALANCE_ROLLOUT_ROLLBACK_OWNER` | person authorized to roll back immediately |
| `BALANCE_ROLLOUT_ROLLBACK_CONTACT` | optional on-call contact |
| `BALANCE_ROLLOUT_STARTED_AT` | rollout start timestamp |
| `BALANCE_ROLLOUT_ENFORCED` | optional override; production defaults to enforced |

Action-specific overrides exist for emergency use:

- `BALANCE_ROLLOUT_ENABLE_COLLECT_DUNG`
- `BALANCE_ROLLOUT_ENABLE_DEPOSIT_CAL`
- `BALANCE_ROLLOUT_ENABLE_WITHDRAW_CAL`
- `BALANCE_ROLLOUT_ENABLE_ADD_FUNDS`
- `BALANCE_ROLLOUT_ENABLE_CREATE_VAULT_USDC`
- `BALANCE_ROLLOUT_ENABLE_WITHDRAW_TO_WALLET`

Overrides must still form an ordered prefix. For example, `withdraw_cal`
cannot be enabled unless `collect_dung` and `deposit_cal` are enabled.

## Rollout Order

1. `off`
   - Production code is deployed, but Balance economic actions are closed.
   - `qa:live` must pass and `/status.balance_rollout.enabled_actions` must be empty.

2. `collect_dung`, cohort `internal`
   - Enable only `Collect DUNG`.
   - Verify one internal rider can collect and sees `Pending`, `Collected`, or `Delayed` truthfully.

3. `deposit_cal`, cohort `internal`
   - Enable `Collect DUNG` and `Deposit CAL`.
   - Verify the position appears after projection; if projection lags, rider state must be `Delayed`, not final.

4. `withdraw_cal`, cohort `internal`
   - Enable `Collect DUNG`, `Deposit CAL`, and `Withdraw CAL`.
   - Verify CAL returns to Boulder Roller Balance and the vault position updates.

5. `create_vault_usdc`, cohort `internal`
   - Enable `Add funds`, `Create Vault or Pay with USDC`, and the previous stages.
   - Verify production ProgramConfig points at the real production USDC mint and treasury token account before enabling.

6. Expand cohort to `dogfood`, then `beta`, then `all`.
   - Move only one cohort or one stage at a time.

`Withdraw to wallet` is a boundary action. Keep it closed until the enabled
cohort has proved internal Balance movement without support noise.

## Verification

Before each stage:

```bash
python3 -m pytest \
  backend/tests/services/test_balance_production_rollout.py \
  backend/tests/services/test_balance_rollout_readiness.py \
  backend/tests/services/test_balance_operation_status.py \
  backend/tests/services/test_balance_transaction_coordinator.py \
  backend/tests/routes/test_health_metrics.py \
  backend/tests/routes/test_portfolio_route.py -q

npm run qa:balance-language --prefix web/portal
npm run qa:modal-policy --prefix web/portal
npm run typecheck:gate --prefix web/portal
```

After production deploy:

```bash
EXPECTED_PORTAL_SHA=<deployed-sha> npm run qa:live --prefix web/portal
curl -fsS https://api.boulderroller.xyz/status
```

Live production checks must show:

- canonical portal host: `app.boulderroller.xyz`
- canonical API host: `api.boulderroller.xyz`
- live portal SHA matches the deployed commit
- `environment` is `production`
- `solana_stub_mode` is `false`
- `auth_signature_bypass_effective` is `false`
- `dev_routes_enabled` is `false`
- `balance_rollout.enforced` is `true`
- `balance_rollout.order_valid` is `true`
- `balance_rollout.blockers` is empty
- `balance_rollout.enabled_actions` is an ordered prefix of the rollout order

## Agent Dogfood Ride

Do not use an old personal file as the proof for automatic economics. Historical
files can still be useful parser regressions, but the ride-effort policy routes
stale activity through review. For agent-run dogfood, generate a current
sensor-backed TCX fixture instead:

```bash
python3 backend/scripts/prove_agent_dogfood_ride.py --json
```

The default command writes
`/tmp/boulderroller-agent-dogfood-power-current.tcx`, validates that it has GPS,
altitude, distance, watts, heart rate, and cadence on every trackpoint, and
checks live `/status` for the internal `collect_dung` rollout stage. It does
not upload anything or require credentials.

To upload through a disposable dogfood account:

```bash
BR_TEST_ACCESS_TOKEN=<disposable-account-access-token> \
  python3 backend/scripts/prove_agent_dogfood_ride.py --upload --poll --json
```

To check whether that same account currently has any pending DUNG:

```bash
BR_TEST_ACCESS_TOKEN=<disposable-account-access-token> \
  python3 backend/scripts/prove_agent_dogfood_ride.py \
  --probe-pending-dung --json
```

If the account has pending DUNG on a known vault, prove the permissionless
Collect DUNG route as well:

```bash
BR_TEST_ACCESS_TOKEN=<disposable-account-access-token> \
  python3 backend/scripts/prove_agent_dogfood_ride.py \
  --upload --poll --collect-vault-id <vault-id> --json
```

If the account has any pending DUNG and the first positive vault is acceptable
for dogfood, collect it directly:

```bash
BR_TEST_ACCESS_TOKEN=<disposable-account-access-token> \
  python3 backend/scripts/prove_agent_dogfood_ride.py \
  --probe-pending-dung --collect-first-pending --json
```

Use only a private or disposable account for this fixture. The script never
prints the access token, and the generated TCX stays outside the repository.

## Rollback

Rollback is one environment edit:

```bash
BALANCE_ROLLOUT_STAGE=off
```

Use rollback immediately if any of these appear:

- a Balance action returns a support-level error to a normal rider surface
- a submitted operation shows final state before the authoritative layer confirms it
- production `/status` reports `balance_rollout.order_valid=false`
- `qa:live` fails against the deployed SHA
- fee-payer or signer custody evidence fails the Balance security readiness gate
- production USDC mint or treasury account does not match ProgramConfig

After rollback, verify:

```bash
EXPECTED_PORTAL_SHA=<deployed-sha> npm run qa:live --prefix web/portal
curl -fsS https://api.boulderroller.xyz/status | jq '.balance_rollout'
```
