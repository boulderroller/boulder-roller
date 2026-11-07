# RFC: Boulder Roller Balance Transaction Coordinator

**Date:** 2026-06-11
**Status:** ACTIVE BACKEND CONTRACT - rider-session amendment 2026-07-17
**Bead:** `boulderroller-v2-2n28`
**Audience:** Backend, protocol, portal, mobile, security, support

This document defines the backend operation layer for Boulder Roller Balance.
It sits above Solana transaction builders and below route/product surfaces.

The decision is:

**Routes must create a Balance operation record before signing, policy-signing,
delegating, or submitting any normal in-app economic action.** Wallet-boundary
routes may build the expected transaction message first when that is required
to store the prepared message hash, but the coordinator record must exist before
submission.

The operation record is the place where Boulder Roller knows the rider action,
authority model, allowed asset movement, idempotency key, prepared message hash,
confirmation state, projection state, retry count, and support/admin evidence.

---

## 1. Scope

The coordinator is not the fee payer and not token authority. It is the
backend control plane that refuses mismatched action/authority combinations
before a transaction builder or policy/delegate signer is reached.

The executable contract lives in:

- `backend/app/services/boulder_balance_authority.py`
- `backend/app/services/balance_transaction_coordinator.py`

The first implementation includes a test/dev in-memory operation sink and a
Supabase-backed `balance_operations` sink. Route code talks to the coordinator
contract, so rider-session, policy-signer, and delegate adapters can share
the same operation ledger semantics.

---

## 2. Required Operation Fields

Every Balance operation record includes:

| Field | Purpose |
|---|---|
| `operation_id` | stable support/admin handle derived from the idempotency key |
| `rider_account_id` | Boulder Roller account id |
| `protocol_wallet` | linked wallet/account authority being used |
| `action_type` | `collect_dung`, `deposit_cal`, `withdraw_cal`, `create_vault`, `pay_usdc`, or boundary action |
| `authority_model` | rider session, policy signer, SPL delegate, permissionless, or wallet-boundary; app-balance custody alone is not authority |
| `asset`, `amount`, `source`, `destination` | narrow value-movement scope |
| `idempotency_key` | retry/replay guard |
| `prepared_message_hash` | wallet fallback and malicious-client guard |
| `fee_payer` | gas sponsor; never value authority |
| `policy_or_delegate_id` | rider-session, provider-policy, or SPL-delegate id when used (legacy field name retained) |
| `tx_signature` | on-chain signature when submitted |
| `confirmation_status` | prepared, submitted, confirmed, finalized, failed, or expired |
| `projection_status` | not_started, pending, recorded, delayed, or needs_review |
| `retry_count` | retry support and abuse monitoring |
| `failure_reason` | support/debug reason without exposing raw chain plumbing in primary UI |
| `reference_type`, `reference_id` | app object being changed |
| `rider_state` | primary rider language when available |

This is intentionally richer than the older `tx_lifecycle` table, which remains
transaction-level infrastructure.

---

## 3. Authority Checks

Before route code signs, policy-signs, delegates, or submits an operation, the
coordinator must verify:

- action exists in the Balance authority catalog
- requested authority model is allowed for that action
- requested asset belongs to the action's allowed asset set
- source, destination, and amount are present
- ProgramConfig was checked when the action requires it
- revocation/recovery state was checked when the action requires it
- rider-session, Privy policy signer, and SPL delegate paths include a live
  `policy_or_delegate_id`
- Balance-funded Vault value actions select `rider_session`; generic
  `app_balance`, fee payer, backend, and login authority are rejected
- wallet-boundary execution has step-up or wallet confirmation

These checks make route behavior follow the same model as the protocol/security
docs instead of reintroducing scattered prepare/sign/submit assumptions.

---

## 4. Rider State Language

Primary rider surfaces should read from the operation state, not raw chain
plumbing.

| Operation condition | Rider state |
|---|---|
| Prepared or submitted | `Pending` |
| Confirmed/finalized but not projected | `Delayed` |
| Projection delayed | `Delayed` |
| Failure, expiry, or review state | `Needs review` |
| `Collect DUNG` recorded | `Collected` |

`Counted` and `Collectable` remain ride/settlement states produced upstream of
transaction execution. Raw transaction status, signatures, blockhashes, retries,
and BoulderScan links remain support/admin/BoulderScan details.

---

## 5. Route Integration Rules

For each economic route:

1. Resolve the intended `action_type`.
2. Resolve the authority model from the actual path being used.
3. Verify ProgramConfig and revocation state before operation preparation.
4. For wallet-boundary paths, build the expected transaction message when
   needed to compute the prepared message hash.
5. Prepare the coordinator operation before any signature submission, policy
   signer call, delegate execution, or permissionless send.
6. Store the prepared message hash before accepting a wallet-signed payload.
7. Mark submitted only after an RPC signature exists.
8. Keep confirmation and projection status separate.
9. Return `Pending`, `Delayed`, or `Needs review` to primary UI when state is
   not fully reconciled.

The route should never fall back to server-held rider key material.

---

## 6. QA Gates

This backend contract is covered by:

- `backend/tests/services/test_balance_transaction_coordinator.py`
- `backend/tests/services/test_boulder_balance_authority.py`
- `backend/tests/routes/test_vault_replay_queueing.py`

The gate proves:

- every normal Balance action can create a no-prompt operation with its allowed
  primary authority model
- wrong authority models fail before transaction build
- policy/delegate paths require an authority id
- wallet-boundary paths require step-up
- ProgramConfig and revocation checks are enforced
- unsupported assets are rejected
- idempotency keys and operation ids are deterministic
- prepared message hashes are SHA-256
- retry count and operation sink updates work
- rider state language uses `Pending`, `Delayed`, `Needs review`, and
  `Collected` where appropriate
- vault create/deposit/withdraw wallet-boundary routes create durable operation
  rows before submission and return `Delayed` when local projection fails after
  a submitted operation

---

## 7. Remaining Integration Work

The first backend route/persistence slice is active:

- `backend/sql/172_balance_operations.sql` (canonical creation; the historical
  `20260611_119_balance_operations.sql` mirror was never applied in production)
- `backend/app/routes/vaults.py` wallet-boundary create/deposit/withdraw paths

The Stage 1 stack repairs that missing canonical creation, including the
existing account-deletion write fence. Its new mirror is additive; the old
mirror remains immutable. See the [table audit](../runbooks/STAGE1_SCHEMA_PARITY.md).
This schema change does not enable any Balance rollout setting.

The next backend slices should extend the same contract:

| Integration | Requirement |
|---|---|
| Durable operation table | Apply and monitor the `balance_operations` table; extend it only losslessly |
| Vault routes | Complete rider-session, policy, and delegate execution paths behind the same coordinator operation shape |
| Solana submission | Attach operation id to tx lifecycle rows when backend submits directly |
| Support/admin | Query by operation id, rider, wallet, reference object, signature, and failure reason |
| Portal/mobile | Consume rider states, not raw transaction labels, for primary flows |
