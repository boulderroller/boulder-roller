# RFC: Boulder Roller Balance and Gasless In-App Execution

**Date:** 2026-06-09
**Status:** TARGET ARCHITECTURE - rider-session authority ratified 2026-07-17
**Bead:** `boulderroller-v2-ora5`
**Audience:** Founding, product, protocol, backend, portal, mobile, security

This RFC sets the pre-product target for Boulder Roller's economic UX:

**Boulder Roller Balance is the rider-facing balance model. Wallet signatures
are boundary events, not normal app events.**

The intent is not to simulate a wallet in the UI. The intent is to make the
protocol feel native to the cycling product while preserving on-chain truth,
program-enforced constraints, and rider exit rights.

Security gate: before implementing the follow-up lanes, read
[`BOULDER_ROLLER_BALANCE_GASLESS_THREAT_MODEL.md`](../security/BOULDER_ROLLER_BALANCE_GASLESS_THREAT_MODEL.md).
That document defines the required authority boundaries, abuse-path controls,
QA gates, and blocker beads for gasless execution.

Protocol gate: the target Anchor account and instruction model is defined in
[`BOULDER_ROLLER_BALANCE_PROTOCOL_MODEL.md`](./BOULDER_ROLLER_BALANCE_PROTOCOL_MODEL.md).
That document controls the successor shapes for permissionless `Collect DUNG`,
RiderBalance, app-balance movement, delegate movement, USDC payment, and
wallet-boundary separation.

Authority gate: the Privy policy signer and SPL delegate execution model is
defined in
[`BOULDER_ROLLER_BALANCE_POLICY_DELEGATE_MODEL.md`](./BOULDER_ROLLER_BALANCE_POLICY_DELEGATE_MODEL.md).
That document controls embedded-wallet policy signing, external-wallet delegate
approval, revocation, and wallet-boundary step-up.

Backend gate: the transaction coordinator contract is defined in
[`BOULDER_ROLLER_BALANCE_TRANSACTION_COORDINATOR.md`](./BOULDER_ROLLER_BALANCE_TRANSACTION_COORDINATOR.md).
That document controls operation ids, authority routing, idempotency, prepared
message hashes, confirmation/projection split, retries, and rider state
language.

---

## 1. Decision

Boulder Roller should build toward this stack:

| Layer | Target |
|---|---|
| Rider-facing model | `Boulder Roller Balance` for CAL, DUNG, and supported app payment rails |
| Account model | Email/social/wallet sign-in with a linked protocol wallet |
| Execution model | Gasless in-app actions through a Boulder Roller fee payer plus rider-scoped session or policy/delegate authority |
| Protocol model | Anchor instructions enforce valid assets, destinations, limits, and supply caps |
| Explorer model | BoulderScan is audit/support/developer infrastructure, not primary rider UI |
| Boundary model | Wallet/security prompts appear for add funds, withdraw, transfer out, export, and authority changes |

Do not design primary rider surfaces around gas, transactions, signatures,
explorer links, proof receipts, or manual chain inspection.

---

## 2. Product Contract

Normal rider language:

```
record/upload ride -> matched climbs -> Counted -> Collectable -> Collected
```

Normal in-app economic language:

- `Boulder Roller Balance`
- `Deposit CAL`
- `Withdraw CAL`
- `Create Vault`
- `Pay with USDC`
- `Collect DUNG`
- `Add funds`
- `Withdraw`

Primary UI should not use:

- gas
- fee payer
- transaction
- tx signature
- explorer
- proof
- wallet prompt
- harvest
- unstake

Those terms remain valid in BoulderScan, support, admin, developer docs,
transaction logs, and security reviews.

---

## 3. Authority Vocabulary

Use these proper nouns consistently:

| Proper noun | Meaning |
|---|---|
| Rider Account | Boulder Roller account created by email, social login, or wallet login |
| Protocol Wallet | Solana wallet linked to the Rider Account; can be Privy embedded or external |
| Rider Wallet | The actual signing wallet when a user-controlled signature is required |
| Boulder Roller Balance | Rider-facing balance inside Boulder Roller, backed by protocol state |
| Boulder Roller Fee Payer | SOL-funded signer that pays network fees for sponsored transactions |
| Backend Authority | ProgramConfig-scoped backend signer for attestation, CAL credit, and settlement execution |
| Boulder Roller Policy Signer | Privy/server-controlled signer scoped by policy to allowed in-app actions |
| Boulder Roller Program Delegate | Program-scoped delegate/PDA authority for limited asset movement under Anchor constraints |
| Rider Session Authority | Rider-configured, revocable signer for exact Balance-funded Vault operations; never the fee payer or login session by implication |
| Vault CAL Escrow | Program-controlled CAL account for a climb vault |
| RiderBalance PDA | Candidate program account representing app-balance state for a rider |
| VaultStake PDA | Program account representing a rider's position in a vault |
| BoulderScan | Explorer/audit surface; not part of primary rider UI |

---

## 4. Target UX Rules

1. Boulder Roller pays gas for normal in-app actions.
2. The rider should not need SOL to use Boulder Roller.
3. The rider should not see explorer or proof links during normal flows.
4. UI confirmation requests an in-app action; it is not token authority. Value
   actions without a repeated wallet popup require a rider-created, revocable
   session or another explicitly granted policy/delegate authority.
5. Wallet authorization appears when value crosses the Boulder Roller boundary
   or account authority changes.
6. Crypto-native riders still retain an advanced path for wallet inspection,
   export, transfer out, and BoulderScan review.

This is intentionally stronger than the old "gas sponsorship for core loop"
posture. The target is an app-native economic surface, not a classic wallet
surface with sponsored fees.

---

## 5. Balance Model

### 5.1 Recommended Target

Use a hybrid of:

1. **Boulder Roller Balance** as the product model.
2. **Privy policy signer and/or program delegate** as the execution mechanism.
3. **Anchor-enforced destinations** as the safety mechanism.
4. **Token accounts and PDAs** as the settlement/custody substrate.

This keeps the UX simple without making the backend a discretionary custodian.

### 5.2 What "Bring It Onto Boulder Roller" Means

For earned CAL, the first ride can create Boulder Roller Balance without a
separate deposit ceremony:

```
ride uploaded -> attested -> CAL Counted -> Boulder Roller Balance increases
```

For external assets, "bring it onto Boulder Roller" is a boundary action:

```
external wallet/token account -> Boulder Roller Balance
```

Examples:

- add CAL from a wallet
- add DUNG from a wallet
- pay with or add USDC for supported app purchases

After that boundary action, ordinary Boulder Roller actions should be
UI-confirmed and gasless.

### 5.3 Candidate Representations

| Representation | Meaning | Use |
|---|---|---|
| Indexed token-account projection | Show wallet ATA balances as Boulder Roller Balance | Fastest bridge, weakest abstraction |
| Escrow-backed app balance | Assets are moved into program-controlled accounts and represented by RiderBalance PDA | Best app-native model |
| Delegate-backed app balance | Assets stay in rider token accounts but a delegate/policy can move limited amounts | Good transition model |
| Policy-signer app balance | User-owned embedded wallet grants scoped signing authority to Boulder Roller | Best fit when Privy policy support is available |

Recommended direction: escrow-backed or delegate-backed Boulder Roller Balance,
with policy signer support for Privy accounts and explicit wallet-boundary
fallbacks for external wallets.

---

## 6. Action Classification

| Rider action | Target state | Authority model | Wallet signature in normal flow? | Notes |
|---|---|---|---|---|
| Sign in | Account opened | Rider Account auth | No wallet signature for email/social | Wallet login may sign auth message only |
| Upload ride | Ride processing | Rider Account auth + attestation pipeline | No | User consents by upload/record action |
| Count CAL | `Counted` | Backend Authority | No | Must be tied to RideAttestation |
| Record climb completion | Matched climb state | Backend Authority | No | Must derive from attested ride |
| Finalize settlement week | Settlement finalized | Backend Authority | No | Operational protocol job |
| DUNG becomes collectable | `Collectable` | Settlement state | No | State created by settlement |
| Collect DUNG | `Collected` | Permissionless-for-rider or policy signer | No | Program must enforce rider destination and treasury |
| Deposit CAL | Position increased | Rider session, delegate, policy signer, or wallet fallback | No after session setup | Exact rider/Vault/amount/expiry intent; custody alone is not consent |
| Withdraw CAL from vault | Position decreased | Rider session, delegate, policy signer, or wallet fallback | No after session setup for in-app Balance; yes for boundary out | Exact LP amount; avoid mixing position change and external withdrawal language |
| Create Vault | Vault created | Rider session, delegate, policy signer, or wallet fallback | No after session setup | Exact new Vault and configured payment amounts |
| Pay with USDC | Payment accepted | Explicit rider session, delegate, policy signer, or wallet fallback | No only after explicit grant | USDC is a payment rail, not ride-loop currency |
| Add funds | External value enters BR | Rider Wallet or regulated onramp flow | Yes / high assurance | Platform-boundary action |
| Withdraw to wallet | External value leaves BR | Rider Wallet or high-assurance account auth | Yes / high assurance | Platform-boundary action |
| Transfer out | Value leaves BR | Rider Wallet or high-assurance account auth | Yes / high assurance | Platform-boundary action |
| Export wallet | Custody boundary | Privy/Rider Wallet controls | Yes / high assurance | Settings/advanced only |
| Change account authority | Authority boundary | Rider Wallet / Privy recovery controls | Yes / high assurance | Security-sensitive |
| Open BoulderScan | Expert inspection | Explicit detail/support/admin action | No | Not a primary CTA |

---

## 7. Protocol Requirements

The backend must not be the thing that makes this safe. The program must make
invalid outcomes impossible.

Required Anchor properties:

1. **Destination enforcement**: collected DUNG can only go to the rider's DUNG
   account or approved Boulder Roller Balance destination.
2. **Treasury enforcement**: protocol fees can only go to
   `ProgramConfig.treasury_token_account`.
3. **Mint enforcement**: CAL, DUNG, LP, and USDC accounts must match expected
   mints.
4. **Escrow enforcement**: deposited CAL can only enter the correct Vault CAL
   Escrow or app-balance escrow.
5. **Supply-cap enforcement**: DUNG minting remains capped in program state.
6. **Idempotency**: collect/claim operations must be replay-safe.
7. **Policy/delegate scope**: delegated movement is limited by amount, asset,
   instruction, destination, and expiry where applicable.
8. **Revocation path**: riders can revoke policy/delegate authority from
   settings or by wallet-level controls.
9. **Custody is not consent**: a RiderBalance PDA, program-owned token account,
   UI confirmation, login session, Backend Authority, or fee payer cannot by
   itself authorize rider-value movement.
10. **Exact rider-session intent**: Balance-funded Vault value actions bind the
    program, rider, signer, action, Vault, exact base-unit amounts, generation,
    nonce, and expiry and consume the nonce once.

---

## 8. Implementation Direction

### 8.1 Replace Wallet-Prompt Assumptions

Do not encode "economic action means rider wallet signature" as a product or
protocol invariant.

Use this distinction instead:

| Category | Definition | Example |
|---|---|---|
| Backend-authorized | Derived from attested state or protocol clock | Count CAL, finalize settlement |
| Permissionless-for-rider | Anyone may trigger because destination is enforced | Collect DUNG for rider |
| Delegated/policy-signed | User pre-authorized scoped in-app actions | Deposit CAL, Create Vault |
| App-balance | Custody/source state inside Boulder Roller Balance; not an authority by itself | Balance CAL/DUNG/USDC |
| Rider-session-signed | Rider pre-authorized one revocable signer; each exact operation is nonce-bound and expiring | Balance-funded Deposit CAL, Withdraw CAL, Create Vault |
| Wallet-boundary | Value or authority crosses out of Boulder Roller | Withdraw, transfer out, export |

### 8.2 Collect DUNG Shape

Current `harvest_rewards` requires `staker: Signer`. The target protocol model
defines a successor shape:

```
collect_stake_rewards_for(staker)
```

The caller can be the Boulder Roller Fee Payer, Backend Authority, Policy
Signer, or any relayer, but the instruction enforces:

- `VaultStake PDA` derives from `staker`
- DUNG recipient is owned by `staker` or by the approved RiderBalance path
- treasury account equals `ProgramConfig.treasury_token_account`
- rewards are reset exactly once
- supply cap is checked before minting

This turns `Collectable -> Collected` into a gasless in-app state transition.

See
[`BOULDER_ROLLER_BALANCE_PROTOCOL_MODEL.md`](./BOULDER_ROLLER_BALANCE_PROTOCOL_MODEL.md)
for the full account constraints and test gates.

### 8.3 Deposit CAL Shape

Depositing CAL moves value. The target is still no visible wallet prompt, but
only after one of these is true:

- CAL is inside Boulder Roller Balance and an active rider-signed Vault-action
  session authorizes the exact deposit.
- Rider granted a scoped delegate allowance.
- Privy policy signer can sign the action under program/destination/amount
  policy.

Until then, external-wallet users may need a boundary fallback.

### 8.4 Create Vault Shape

Creating a vault may spend CAL, DUNG, or USDC. Treat it as an in-app purchase
when funded by Boulder Roller Balance or policy/delegate authority:

```
Choose climb -> Confirm vault creation -> Created
```

The UI confirmation is the product request. Rider consent comes from the
active rider-created session or another explicit policy/delegate grant; the
program binds that grant to the exact Vault and configured payment amounts.

### 8.5 Withdraw Shape

Use precise language:

- `Withdraw CAL` from a vault can mean reducing an in-app position.
- `Withdraw to wallet` means value leaves Boulder Roller.

Only the second is always a wallet-boundary event.

The first still moves rider value. It may remain quiet only through an active
rider session (or another explicit grant) whose exact LP burn intent is checked
and consumed on-chain.

---

## 9. Backend Requirements

Build a Transaction Coordinator rather than scattered prepare/sign/submit
flows.

Minimum state:

- `operation_id`
- `rider_account_id`
- `protocol_wallet`
- `action_type`
- `authority_model`
- `asset`
- `amount`
- `source`
- `destination`
- `idempotency_key`
- `prepared_message_hash`
- `fee_payer`
- `policy_or_delegate_id`
- `rider_session_id` for Balance-funded Vault value actions
- `tx_signature`
- `confirmation_status`
- `projection_status`
- `retry_count`
- `created_at`
- `confirmed_at`
- `failure_reason`

Rider-facing states should be:

- `Counted`
- `Collectable`
- `Collected`
- `Pending`
- `Delayed`
- `Needs review`

Admin/support states can expose transactions, blockhashes, signatures, and
BoulderScan links.

---

## 10. Portal And Mobile Rules

Primary surfaces should show:

- `Boulder Roller Balance`
- `Counted`
- `Collectable`
- `Collected`
- `Deposit CAL`
- `Withdraw CAL`
- `Create Vault`
- `Pay with USDC`
- `Add funds`
- `Withdraw to wallet`

Primary surfaces should not say:

- `Harvest`
- `Stake` as the CTA
- `Unstake` as the CTA
- `Transaction signature`
- `Gas`
- `Sponsored transaction`
- `Open in BoulderScan` as a primary CTA

BoulderScan links belong in:

- details
- history
- support
- admin
- developer surfaces
- explicit advanced settings

---

## 11. Parallel First-Traverse Guidance

The first-traverse/app-entry lane should not hardcode wording or UI that
conflicts with this target.

Tell that lane:

1. Do not promise that every economic action asks for a transaction signature.
2. Do not place gas, transaction, signature, proof, or explorer language in
   primary rider copy.
3. Wallet entry should stay secondary and returning-wallet-oriented.
4. Keep asset/custody approval separate from account sign-in.
5. If a copy surface needs to mention future economics, use literal action
   names: `Boulder Roller Balance`, `Deposit CAL`, `Collect DUNG`, `Add funds`,
   `Withdraw`.
6. Keep UI flexible enough for email/social riders whose normal in-app actions
   do not open wallet prompts.

---

## 12. Implementation Beads To Cut

Follow-up beads:

1. `boulderroller-v2-vwdg` — Protocol model for Boulder Roller Balance and
   permissionless DUNG collection.
2. `boulderroller-v2-jppk` — Implement the permissionless `Collect DUNG`
   Anchor successor and protocol/backend builder tests.
3. `boulderroller-v2-bctm` — Implement RiderBalance escrow and app-balance CAL
   movement. Status: implemented for `Deposit CAL` and `Withdraw CAL` through
   RiderBalance escrow PDAs, Anchor successor instructions, IDL/client updates,
   and backend instruction builders.
4. `boulderroller-v2-bfyz` — Add canonical USDC ProgramConfig/payment
   constraints. Status: implemented for canonical `ProgramConfig` USDC mint,
   USDC treasury token account, configured vault USDC amount, hardened
   wallet-signed USDC vault creation, and Balance-funded CAL+USDC vault
   creation.
5. `boulderroller-v2-2n28` — Backend transaction coordinator for gasless
   authority-model execution. Status: active coordinator contract, durable
   `balance_operations` table, and wallet-boundary vault create/deposit/withdraw
   route adapters landed behind the same operation shape.
6. `boulderroller-v2-jfm6` — Privy policy signer and SPL delegate execution
   path. Status: defined as an authority catalog plus RFC for embedded-wallet
   policy signing, external-wallet SPL delegation, revocation, provider
   verification, and wallet-boundary fallback behavior.
7. `boulderroller-v2-p6gt` — Portal and mobile Boulder Roller Balance state
   language.
8. `boulderroller-v2-0dff` — Threat model and QA gates for gasless in-app
   execution.
9. `boulderroller-v2-ihc1` — Retired from normal stake/unstake API routes:
   unsigned route calls require prepared wallet-signed transactions, and direct
   Solana helpers are left only for isolated devnet smoke scripts.
10. `boulderroller-v2-8348` — Ratified and implemented in ABI `0x44`:
    Balance-funded Deposit CAL, Withdraw CAL, and CAL+USDC Vault creation require
    a rider-configured session signer plus exact expiring nonce-bound intent;
    generic app-balance authority is rejected.

---

## 13. Open Questions

1. Should Boulder Roller Balance be escrow-backed from day one, or initially an
   indexed projection over wallet token accounts plus policy/delegate execution?
2. Should USDC be supported only as a vault-creation/payment rail, or also as a
   general Boulder Roller Balance asset?
3. Should external-wallet no-prompt execution ship broadly through SPL delegate
   approvals, or stay limited until rider comprehension and revocation UX are
   proven?
4. Which optional high-risk settings changes require biometric confirmation
   beyond normal provider step-up?

---

## 14. References

- `docs/PROTOCOL_TRUTHS.md`
- `docs/BACKEND_TRUTHS.md`
- `docs/MOBILE_TRUTHS.md`
- `docs/design/LANGUAGE_SPEC.md`
- `docs/rfcs/PRIVY_AUTH_UX.md`
- `docs/rfcs/USER_ACCOUNT_PDA_ARCHITECTURE.md`
- `docs/security/BOULDER_ROLLER_BALANCE_GASLESS_THREAT_MODEL.md`
- `docs/rfcs/BOULDER_ROLLER_BALANCE_TRANSACTION_COORDINATOR.md`
- Solana fee abstraction: https://solana.com/docs/payments/send-payments/payment-processing/fee-abstraction
- Solana token delegate approvals: https://solana.com/docs/tokens/basics/approve-delegate
- Privy policies: https://docs.privy.io/controls/policies/overview
- Privy Solana policy examples: https://docs.privy.io/controls/policies/example-policies/solana
