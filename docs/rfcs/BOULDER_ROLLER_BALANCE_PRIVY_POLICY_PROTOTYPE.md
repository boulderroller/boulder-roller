# RFC: Boulder Roller Balance Privy Policy Prototype

**Date:** 2026-06-11
**Status:** ACTIVE PROVIDER LIMITATION RECORD
**Bead:** `boulderroller-v2-q7ze`
**Audience:** Backend, protocol, security, portal, mobile

This document closes the first provider-policy prototype gate for Boulder
Roller Balance.

The decision is:

**Privy policy signing can be part of Boulder Roller Balance, but custom Anchor
instruction policy signing is not production-eligible as the only guard until
live provider proof shows instruction/account-level enforcement.**

The repository now has an executable fixture in
`backend/app/services/balance_privy_policy_prototype.py` and a regression gate
in `backend/tests/services/test_balance_privy_policy_prototype.py`.

---

## 1. Provider Capability Result

Privy's Solana policy examples can express useful token-transfer constraints:

- token-program instruction name
- `TransferChecked` mint
- `TransferChecked` amount
- recipient-like account constraints
- time windows

Privy's public custom-program policy surface is strong enough for a Boulder
Rollers program-id guard, but this prototype does not find enough public
provider evidence to treat a custom Anchor policy as the sole guard for:

- custom Anchor instruction name
- custom Anchor account role equality
- custom Anchor amount argument
- custom Anchor destination account
- address-based checks when address lookup tables are used

That means provider policy is defense-in-depth for custom Anchor Balance
actions. Boulder Roller still needs its own coordinator checks, Anchor
constraints, and a fallback path.

---

## 2. Executable Fixture

The fixture models the exact fields that must match before the backend may ask
for policy-signer execution:

| Field | Rejection covered |
|---|---|
| `program_id` | Wrong Boulder Rollers or token program |
| `instruction_name` | Wrong custom Anchor instruction or token instruction |
| `mint` / `asset` | Wrong CAL, DUNG, USDC, or LP scope |
| `destination` | Treasury, escrow, or rider destination spoof |
| `required_accounts` | Missing or wrong Anchor account roles |
| `amount_base_units` | Zero, negative, or over-limit amount |
| `expires_at_unix` | Expired prepared operation |
| `address_lookup_table_addresses` | Address lookup table ambiguity |

The fixture deliberately rejects address lookup table usage for address-bound
policies. If a future route needs ALTs for size, it must use app-balance,
wallet-boundary confirmation, or a provider-verified policy shape that proves
ALT-resolved addresses are evaluated safely.

---

## 3. Action Matrix

| Rider action | Prototype result | Production path |
|---|---|---|
| `Collect DUNG` | Local fixture rejects wrong program, instruction, accounts, mint, destination, amount, expiry, and ALT usage | Prefer permissionless-for-rider successor or app-balance; do not rely on provider policy alone for custom Anchor |
| `Deposit CAL` | Local fixture rejects wrong `stakeCalInVault` scope | Prefer RiderBalance app-balance successor; wallet-boundary fallback when funds remain outside Balance |
| `Withdraw CAL` | Local fixture rejects wrong `unstakeCalFromVault` scope | Prefer RiderBalance app-balance successor; wallet-boundary fallback when funds remain outside Balance |
| `Create Vault` | Local fixture rejects wrong `createVaultWithUsdc` scope | Prefer `createVaultFromBalanceCalUsdc` app-balance successor; wallet-boundary fallback for external funding |
| `Pay with USDC` | Token-transfer policy can be provider-sufficient when quote, mint, amount, and treasury destination match | Provider policy may be used for checked USDC transfer, still recorded through the coordinator |

---

## 4. Route Requirement

Before any future Privy policy-signer route calls the provider, it must:

1. prepare a `BalanceOperationIntent` through the transaction coordinator;
2. evaluate the prepared operation against the Privy policy fixture;
3. reject any fixture failure with `Needs review` or wallet-boundary fallback;
4. record `policy_or_delegate_id`, policy hash, prepared message hash, expiry,
   and fallback state in the Balance operation ledger;
5. never downgrade to server-held rider key material.

For custom Anchor instructions, a passing local fixture is necessary but not
sufficient for provider-only production reliance. The Anchor program must still
own the final safety checks.

---

## 5. QA Gate

Run:

```bash
python3 -m pytest backend/tests/services/test_balance_privy_policy_prototype.py backend/tests/services/test_boulder_balance_authority.py backend/tests/services/test_balance_transaction_coordinator.py -q
```

This gate proves:

- the expected Balance policy attempt is accepted;
- wrong program is rejected;
- wrong custom instruction is rejected;
- missing or wrong account roles are rejected;
- wrong mint is rejected;
- wrong destination is rejected;
- over-limit amount is rejected;
- expired operation is rejected;
- address lookup table usage is rejected;
- boundary actions are not policy-signable;
- custom Anchor policy remains marked provider-insufficient;
- checked USDC token transfer is marked provider-sufficient when quote fields
  match.

---

## 6. References

- Privy policies overview:
  https://docs.privy.io/controls/policies/overview
- Privy Solana policy examples:
  https://docs.privy.io/controls/policies/example-policies/solana
- Privy Solana transactions:
  https://docs.privy.io/wallets/using-wallets/solana/send-a-transaction
- Boulder Roller authority model:
  `docs/rfcs/BOULDER_ROLLER_BALANCE_POLICY_DELEGATE_MODEL.md`
- Boulder Roller transaction coordinator:
  `docs/rfcs/BOULDER_ROLLER_BALANCE_TRANSACTION_COORDINATOR.md`
